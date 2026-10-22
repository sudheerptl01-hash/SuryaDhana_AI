#!/bin/sh
# Improvement-phase compute queue, v2 A/Bs (ml/IMPROVEMENT_PLAN.md P3 + amendments A3). Runs one job at a time.
cd /home/user/SuryaDhana_AI
# (wait loop removed: the control run had already finished)
X=ml/data_ext/extra_features.parquet; M=ml/data_ext/market_state.parquet; P=ml/data_ext/extra_features_placebo_f2.parquet
python3 -m ml.improve.ab run --data ml/data_5y_v2 --tag v2 --extra $X --market $M --configs ab1_mkt ab2_sector ab3_fo ab4_flows ab5_all --n-jobs 2 \
 && python3 -m ml.improve.ab run --data ml/data_5y_v2 --tag v2 --extra $P --market $M --configs ab2p_sector_placebo --n-jobs 2 \
 && python3 -m ml.improve.ab run --data ml/data_5y_v2 --tag v2 --configs ab6_lambdarank52 ab6_catboost52 ab6_ensemble_all52 --n-jobs 2 \
 && python3 -m ml.improve.ab compare --data ml/data_5y_v2 --tag v2 \
 && python3 -m ml.improve.ab_books --tag v2 --data ml/data_5y_v2 --prices ml/results/improve/cache/features_prices_export_v2.parquet
echo "QUEUE DONE $(date)"
