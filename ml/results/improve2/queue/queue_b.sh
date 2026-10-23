#!/bin/sh
# Phase 2 compute queue B (ml/IMPROVEMENT_PLAN_2.md Q6, Q5, Q7). One job at a time after the tuning selection.
cd /home/user/SuryaDhana_AI
export OMP_NUM_THREADS=2
# (wait removed: the tuning selection had already finished)
echo "tune select finished $(date)"; tail -3 ml/results/improve2/tune/select.log
python3 -m ml.improve.tune select --n-jobs 2 > ml/results/improve2/tune/select_final.log 2>&1   # re-assembles from cache (builder's note)
echo "== Q6 events A/B $(date)"
python3 -m ml.improve.ab run --data ml/data_10y --tag 10y_p2 --extra ml/data_ext/event_features_10y.parquet --configs ae1_events --n-jobs 2
echo "== Q5 40-day $(date)"
python3 -m ml.improve.h40 build && python3 -m ml.improve.ab run --data ml/data_10y_h40 --tag 10y_h40 --configs control --n-jobs 2 && python3 -m ml.improve.h40 books --scorer h40 && python3 -m ml.improve.h40 compare
echo "== Q7 tuned $(date)"
python3 -m ml.improve.ab run --data ml/data_10y --tag 10y_p2 --configs q7_tuned --n-jobs 2
echo "== compare + books for 10y_p2 $(date)"
python3 -m ml.improve.ab compare --data ml/data_10y --tag 10y_p2
python3 -m ml.improve.ab_books --tag 10y_p2 --data ml/data_10y --prices ml/results/improve/cache/features_prices_export_10y.parquet --price-start 2017-10-02 --n-trials 261 --configs control ae1_events q7_tuned
python3 -m ml.improve.ab_books --tag 10y_p2 --data ml/data_10y --prices ml/results/improve/cache/features_prices_export_10y.parquet --price-start 2017-10-02 --configs control q7_tuned --n-trials 261 --out-dir ml/results/improve2/tune --out-name books_q7
python3 -m ml.improve.tune report
echo "QUEUE B DONE $(date)"
