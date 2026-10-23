#!/bin/sh
# Ten-year re-runs (plan P4): start only after the v2 A/B queue has written its completion marker.
cd /home/user/SuryaDhana_AI
until grep -q "QUEUE DONE" ml/results/improve/ab/v2/queue_ab.log 2>/dev/null; do sleep 60; done
python3 -m ml.improve.ab run --data ml/data_10y --tag 10y --configs control lr_l2 baseline_mom --n-jobs 2 \
 && python3 -m ml.improve.ab compare --data ml/data_10y --tag 10y \
 && python3 -m ml.improve.ab_books --tag 10y --data ml/data_10y --prices ml/results/improve/cache/features_prices_export_10y.parquet --price-start 2017-10-02
echo "QUEUE DONE $(date)"
