import json, sys
R = json.load(open('results.json'))
for name in sys.argv[1:]:
    s = R[f's4_{name}']; Lr = s['learn']
    print('=====', name)
    for k in ['xs_auc_up_by_year','xs_auc_down_by_year','ic_r10_by_year','ic_r20_by_year','top_dec_ex_r10_bps_by_year','bot_dec_ex_r10_bps_by_year','top_dec_ex_r20_bps_by_year','bot_dec_ex_r20_bps_by_year','fno_top_dec_ex_r10_bps_by_year','fno_bot_dec_ex_r10_bps_by_year']:
        if k in Lr: print(f'  {k:32s}', {a: round(b,4) for a,b in Lr[k].items()})
    print('  ic_r10_2026', Lr.get('ic_r10_2026'), 't', Lr.get('ic_r10_t_2026'), 'ic_r20_2026', Lr.get('ic_r20_2026'))
    for blk in ['long','short_fno','long_fno']:
        for k, v in s[blk].items():
            print(f'  {blk:9s} {k:24s} cagr {v["cagr"]:+.4f} sh {v["sharpe"]:+.2f} adj {v["sharpe_rho_adj"]:+.2f} dd {v["max_dd"]:+.3f} hit {v.get("hit_rate",0):.3f} mt {v.get("mean_trade_net",0)*1e4:+.1f}bp bars {v.get("avg_bars_held",0):.1f} npb {v.get("net_per_bar_bps",0):+.2f}', {a: round(b,3) for a,b in v['by_year'].items()} if k.endswith('full') else '')
