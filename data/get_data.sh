#!/usr/bin/env bash
# Fetch the seven OULAD CSVs into data/raw/.
# The official archive (https://analyse.kmi.open.ac.uk/open-dataset) is preferred when it downloads;
# in Oct 2026 it did not, so this script falls back to the public mirror used for the report
# and reassembles studentVle from its 8 parts (dropping the mirror's pandas index column).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p raw
tmp=$(mktemp -d)
git clone --depth 1 https://github.com/LuongAnh1/oulad-data-warehouse.git "$tmp/m"
cp "$tmp"/m/raw_data/{assessments,courses,studentAssessment,studentInfo,studentRegistration,vle}.csv raw/
{ echo "code_module,code_presentation,id_student,id_site,date,sum_click"
  for i in 0 1 2 3 4 5 6 7; do tail -n +2 "$tmp/m/raw_data/studentVle_$i.csv"; done | awk -F, '{print $2","$3","$4","$5","$6","$7}'
} > raw/studentVle.csv
rm -rf "$tmp"
wc -l raw/*.csv   # expect studentVle 10655281 lines (incl. header)
