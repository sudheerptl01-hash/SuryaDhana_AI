import json,sys
for tag in sys.argv[1:]:
    d=json.load(open(f'variants_{tag}.json'))
    print('==',tag)
    for key,vv in d.items():
        if key=='tag': continue
        if key.endswith('coverage'): print(' ',key,vv); continue
        for sub,v in vv.items():
            f=lambda x: None if x is None else round(x,4)
            s1=v.get('sel_2023_25') or {}; s2=v.get('hold_2026') or {}
            print(f"  {key:26s} {sub:10s} cagr {f(v['cagr'])} sh {f(v['sharpe'])} dd {f(v['max_dd'])} hit {f(v['hit_rate'])} mt {f(v['mean_trade_net'])} bars {f(v.get('avg_bars_held'))} | sel cagr {f(s1.get('cagr'))} sh {f(s1.get('sharpe'))} | 2026 tot {f(s2.get('total'))} | by_year {{{', '.join(f'{k}:{round(x,3)}' for k,x in v['by_year'].items())}}}")
