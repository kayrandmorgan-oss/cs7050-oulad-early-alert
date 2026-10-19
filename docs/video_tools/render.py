"""
render.py — turn recorded runs (rec/*.json) + figures into a captioned 1920x1080 MP4.
Terminal scenes replay the REAL captured output with its real timing, sped up where noted on screen.
    python render.py storyboard.json out.mp4
"""
import json, subprocess, sys, textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 1080, 15
NAVY, NAVY2, TERM, INK, MUTED, ORANGE, PAPER = "#14213D", "#1E2D4F", "#0E1525", "#E8ECF2", "#9AA8BD", "#F0A274", "#FAF8F3"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SANSB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
SERIF = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
f_mono = ImageFont.truetype(MONO, 22); f_cap = ImageFont.truetype(SANS, 34); f_bar = ImageFont.truetype(SANS, 26)
f_barb = ImageFont.truetype(SANSB, 26); f_badge = ImageFont.truetype(SANSB, 24)
TX, TY, TW, TH = 80, 112, 1760, 752          # terminal / figure panel
LH, COLS = 30, 128
ROWS = (TH - 70) // LH

def base(step, title):
    im = Image.new("RGB", (W, H), NAVY); d = ImageDraw.Draw(im)
    d.text((80, 36), "CS 7050 · From Clickstream to Early Alert", font=f_bar, fill=MUTED)
    t = f"{step}  {title}"; w = d.textlength(t, font=f_barb); d.text((W - 80 - w, 36), t, font=f_barb, fill=INK)
    return im

def caption(im, text):
    d = ImageDraw.Draw(im)
    lines = textwrap.wrap(text, 92)[:2]
    y = 900 if len(lines) == 2 else 922
    for ln in lines:
        w = d.textlength(ln, font=f_cap); d.text(((W - w) / 2, y), ln, font=f_cap, fill=PAPER); y += 46

def term_frame(step, title, cap, lines, badge):
    im = base(step, title); d = ImageDraw.Draw(im)
    d.rounded_rectangle([TX, TY, TX + TW, TY + TH], 18, fill=TERM)
    for i, c in enumerate(["#E5675F", "#E9B949", "#5FB66B"]): d.ellipse([TX + 24 + i * 30, TY + 20, TX + 40 + i * 30, TY + 36], fill=c)
    if badge:
        bw = d.textlength(badge, font=f_badge) + 32
        d.rounded_rectangle([TX + TW - bw - 20, TY + 12, TX + TW - 20, TY + 48], 10, fill=ORANGE)
        d.text((TX + TW - bw - 4, TY + 16), badge, font=f_badge, fill=NAVY)
    y = TY + 60
    wrapped = []
    for ln in lines:
        if len(ln) <= COLS: wrapped.append(ln)
        else:
            ind = " " * min(len(ln) - len(ln.lstrip()) + 2, 10)
            wrapped.append(ln[:COLS]); rest = ln[COLS:]
            while rest: wrapped.append(ind + rest[:COLS - len(ind)]); rest = rest[COLS - len(ind):]
    for ln in wrapped[-ROWS:]:
        col = ORANGE if ln.startswith("$ ") else ("#7FD1A8" if ("PASS" in ln and "FAIL" not in ln) else ("#F28B82" if " FAIL" in ln else INK))
        d.text((TX + 28, y), ln[:COLS], font=f_mono, fill=col); y += LH
    caption(im, cap); return im

def emulate(text, lines):
    cur = lines.pop() if lines else ""
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\n": lines.append(cur); cur = ""
        elif ch == "\r":
            if i + 1 < len(text) and text[i + 1] == "\n": pass
            else: cur = ""
        elif ch == "\t": cur += "    "
        elif ch >= " ": cur += ch
        i += 1
    lines.append(cur); return lines

def card(kind, sc):
    im = Image.new("RGB", (W, H), NAVY); d = ImageDraw.Draw(im)
    if kind == "title":
        d.text((160, 300), sc["eyebrow"], font=ImageFont.truetype(SANSB, 30), fill=ORANGE)
        y = 370
        for ln in sc["lines"]: d.text((160, y), ln, font=ImageFont.truetype(SERIF, 84), fill=PAPER); y += 104
        y += 30
        for ln in sc["sub"]: d.text((160, y), ln, font=ImageFont.truetype(SANS, 36), fill=MUTED); y += 52
    return im

def figure_frame(step, title, cap, img_path):
    im = base(step, title); d = ImageDraw.Draw(im)
    d.rounded_rectangle([TX, TY, TX + TW, TY + TH], 18, fill=PAPER)
    fig = Image.open(img_path).convert("RGB"); fig.thumbnail((TW - 60, TH - 50), Image.LANCZOS)
    im.paste(fig, (TX + (TW - fig.width) // 2, TY + (TH - fig.height) // 2))
    caption(im, cap); return im

class Writer:
    def __init__(self, path):
        self.p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                                   "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "22",
                                   "-pix_fmt", "yuv420p", "-movflags", "+faststart", path], stdin=subprocess.PIPE)
        self.n = 0
    def put(self, im, seconds=None, frames=None):
        b = im.tobytes(); k = frames if frames is not None else max(1, round(seconds * FPS))
        for _ in range(k): self.p.stdin.write(b)
        self.n += k
    def close(self): self.p.stdin.close(); self.p.wait()

def main():
    sb = json.load(open(sys.argv[1])); w = Writer(sys.argv[2]); chapters = []
    for sc in sb:
        start = w.n / FPS; step = sc.get("step", ""); title = sc.get("title", ""); cap = sc.get("caption", "")
        if sc["type"] == "title":
            w.put(card("title", sc), sc["seconds"])
        elif sc["type"] == "figure":
            w.put(figure_frame(step, title, cap, sc["image"]), sc["seconds"])
        elif sc["type"] == "term":
            rec = json.load(open(Path("rec") / f"{sc['rec']}.json"))
            lines = [l for l in sc.get("prefix_lines", [])]
            cmd = "$ " + rec["cmd"]
            # typing the command
            tframes = int(1.4 * FPS)
            for f in range(tframes):
                k = int(len(cmd) * (f + 1) / tframes)
                w.put(term_frame(step, title, cap, lines + [cmd[:k] + "▌"], None), frames=1)
            lines.append(cmd); lines.append("")
            D = max(rec["duration"], 0.01); R = sc.get("run_seconds", D)
            speed = max(1.0, D / R)
            badge = None if speed < 1.5 else f"▶▶ {speed:.0f}× speed · {D/60:.1f} min run" if D >= 90 else f"▶▶ {speed:.0f}× speed"
            ev = rec["events"]; nframes = max(1, int(min(D, R * 1.0 if speed > 1 else D) * FPS))
            j = 0; last = None
            for f in range(nframes):
                t_real = (f + 1) / FPS * speed
                changed = False
                while j < len(ev) and ev[j][0] <= t_real:
                    lines = emulate(ev[j][1], lines); j += 1; changed = True
                if changed or last is None:
                    last = term_frame(step, title, cap, [l for l in lines if l != ""] if sc.get("drop_blank") else lines, badge)
                w.put(last, frames=1)
            while j < len(ev): lines = emulate(ev[j][1], lines); j += 1
            final = term_frame(step, title, sc.get("final_caption", cap), lines, badge)
            w.put(final, sc.get("hold", 4))
        chapters.append({"t": round(start, 1), "step": step, "title": title or sc.get("lines", [""])[0]})
    w.close(); json.dump(chapters, open(Path(sys.argv[2]).with_suffix(".chapters.json"), "w"), indent=1)
    print("frames", w.n, "seconds", round(w.n / FPS, 1))

if __name__ == "__main__":
    main()
