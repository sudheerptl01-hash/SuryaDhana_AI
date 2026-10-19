import json,sys
for tag in sys.argv[1:]:
    d=json.load(open(f'invest_{tag}.json'))
    print('==',tag)
    for y,o in d['diag'].items():
        print(' ',y,{k:round(v,4) for k,v in o.items()})
    for key in [k for k in d if k.startswith(('long','short'))]:
        for sub,v in d[key].items():
            f=lambda x: None if x is None else round(x,4)
            s1=v.get('sel_2023_25') or {}; s2=v.get('hold_2026') or {}
            print(f"  {key:18s} {sub:10s} cagr {f(v['cagr'])} sh {f(v['sharpe'])} dd {f(v['max_dd'])} hit {f(v['hit_rate'])} mt {f(v['mean_trade_net'])} | sel cagr {f(s1.get('cagr'))} sh {f(s1.get('sharpe'))} | 2026 tot {f(s2.get('total'))} sh {f(s2.get('sharpe'))} | by_year {{{', '.join(f'{k}:{round(x,3)}' for k,x in v['by_year'].items())}}}")
    b=d['benchmark_nifty500']; print('  nifty', round(b['cagr'],4), round(b['sharpe'],3), round(b['max_dd'],3), {k:round(x,3) for k,x in b['by_year'].items()}, 'sel', round(d['benchmark_nifty500_2023_25']['cagr'],4), '2026', round(d['benchmark_nifty500_2026']['total_return'],4))
