import json, sys
R = json.load(open('results.json'))
def p(tag, d):
    for k, v in d.items():
        print(f'  {tag:22s} {k:24s} cagr {v["cagr"]:+.4f}±{v["cagr_sd_seeds"]:.3f} sh {v["sharpe"]:+.2f} dd {v["max_dd"]:+.3f} hit {v["hit_rate"]:.3f} mt {v["mean_trade_net"]*1e4:+.1f}bp', {a: round(b,3) for a,b in v.get('by_year',{}).items()})
for k, v in R['s4b_random'].items(): p(k, v)
for name in sys.argv[1:]:
    print('====', name)
    for k, v in R[f's4b_{name}'].items(): p(k, v)
