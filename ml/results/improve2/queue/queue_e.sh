#!/bin/sh
# Phase 2 amendment A2 (Q10): seed replicates of the control and of Q9.
cd /home/user/SuryaDhana_AI
export OMP_NUM_THREADS=2
P=ml/results/improve/cache/features_prices_export_10y.parquet
echo "== Q10 seed replicates $(date)"
python3 -m ml.improve.ab run --data ml/data_10y --tag 10y_p2 --configs control_s109 control_s110 control_s111 q9_expanding_s109 q9_expanding_s110 --n-jobs 2
python3 -m ml.improve.ab compare --data ml/data_10y --tag 10y_p2
python3 -m ml.improve.ab_books --tag 10y_p2 --data ml/data_10y --prices $P --price-start 2017-10-02 --n-trials 270 --configs control ae1_events q7_tuned q9_expanding control_s109 control_s110 control_s111 q9_expanding_s109 q9_expanding_s110
python3 -m ml.improve.q9
python3 -m ml.improve.q10
python3 -m ml.improve.gates --tag 10y_p2 --n-trials 270
echo "QUEUE E DONE $(date)"
