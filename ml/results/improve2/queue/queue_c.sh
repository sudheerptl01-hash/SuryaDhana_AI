#!/bin/sh
# Phase 2 compute queue C (ml/IMPROVEMENT_PLAN_2.md Q3 liquid, Q2 CPCV). Starts after queue B.
cd /home/user/SuryaDhana_AI
export OMP_NUM_THREADS=2
until grep -q "QUEUE B DONE" ml/results/improve2/queue/queue_b.log 2>/dev/null; do sleep 60; done
P=ml/results/improve/cache/features_prices_export_10y.parquet
echo "== Q3 liquid L1 $(date)"
python3 -m ml.improve.ab run --data ml/data_10y_liq --tag 10y_liq --configs control --n-jobs 2
echo "== Q3 liquid L2 $(date)"
python3 -m ml.improve.ab run --data ml/data_10y_liq2 --tag 10y_liq2 --configs control --n-jobs 2
python3 -m ml.improve.ab_books --tag 10y_liq --data ml/data_10y_liq --prices $P --price-start 2017-10-02 --n-trials 261
python3 -m ml.improve.ab_books --tag 10y_liq2 --data ml/data_10y_liq2 --prices $P --price-start 2017-10-02 --n-trials 261
python3 -m ml.improve.ab compare --data ml/data_10y_liq --tag 10y_liq
python3 -m ml.improve.ab compare --data ml/data_10y_liq2 --tag 10y_liq2
python3 -m ml.improve.liquid compare
echo "== Q2 CPCV $(date)"
python3 -m ml.improve.cpcv fit --n-jobs 2 > ml/results/improve2/cpcv/fit.log 2>&1
python3 -m ml.improve.cpcv paths && python3 -m ml.improve.cpcv books && python3 -m ml.improve.cpcv report
echo "QUEUE C DONE $(date)"
