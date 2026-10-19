import json, sys
d = json.load(open('results.json'))
sec = sys.argv[1]
filt = sys.argv[2:] 
for r in d[sec]:
    c = r['cfg']
    key = f"{c['univ']} K{c.get('top_k','-')} s{c['step']} c{c['cost_bps']} q{c.get('select_quantile','')} {r['period']}"
    if any(f not in key for f in filt): continue
    ew = f" ew {r['ew']['cagr']:.3f} exEW {r['excess_cagr_vs_ew']:+.3f} tEW {r['excess_vs_ew_nw_t']:.2f}" if 'ew' in r else ''
    print(f"{key:40s} cagr {r['cagr']:+.3f} sh {r['sharpe']:.2f} dd {r['max_dd']:+.3f} rnd {r['random']['cagr_mean']:+.3f} ex {r['excess_cagr_vs_random']:+.3f} t {r['excess_daily_nw_t']:5.2f} expo {r['exposure']:.2f} hit {r['hit_rate']:.3f} mt {r['mean_trade_net']*1e4:6.1f}{ew}")
