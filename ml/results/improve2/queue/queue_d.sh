#!/bin/sh
# Phase 2 amendment A1: expanding-window control.
cd /home/user/SuryaDhana_AI
export OMP_NUM_THREADS=2
P=ml/results/improve/cache/features_prices_export_10y.parquet
echo "== Q9 expanding $(date)"
python3 -m ml.improve.ab run --data ml/data_10y --tag 10y_p2 --configs q9_expanding --n-jobs 2
python3 -m ml.improve.ab compare --data ml/data_10y --tag 10y_p2
python3 -m ml.improve.ab_books --tag 10y_p2 --data ml/data_10y --prices $P --price-start 2017-10-02 --n-trials 264 --configs control ae1_events q7_tuned q9_expanding
python3 -m ml.improve.q9
echo "QUEUE D DONE $(date)"
