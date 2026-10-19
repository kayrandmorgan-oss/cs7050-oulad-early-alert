#!/usr/bin/env bash
# Cross-package validation: the same train-February / test-October split in Weka.
# Usage: bash mining/weka_crosscheck.sh  [WEKA_JAR=/path/to/weka.jar]
WEKA_JAR=${WEKA_JAR:-/usr/share/java/weka.jar}
cd "$(dirname "$0")/.."
TR=out/feature_mart_week4_trainB.arff; TE=out/feature_mart_week4_testJ.arff
for clf in "weka.classifiers.functions.Logistic -R 1.0E-8 -M -1" \
           "weka.classifiers.trees.J48 -C 0.25 -M 50" \
           "weka.classifiers.bayes.NaiveBayes"; do
  echo "=== $clf"
  java -Xmx2g -cp "$WEKA_JAR" $clf -t "$TR" -T "$TE" -c last -o -i 2>/dev/null \
    | sed -n '/Error on test data/,$p' | grep -E "Correctly Classified|Weighted Avg|^ +[0-9.]+ +[0-9.]+ .* 1$|ROC"
done
