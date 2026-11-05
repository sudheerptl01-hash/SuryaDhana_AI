import re, json, sys
txt = open('SOURCES.md', encoding='utf-8').read()
# split into entries by '### <Letter><digits>' headers, stop at the metrics section
body = txt.split('## 10. Derived metrics dictionary')[0]
parts = re.split(r'\n(?=### [A-I]\d+ )', body)
entries = [p for p in parts if p.startswith('### ')]
counts = {}
rows = []
for e in entries:
    hid = re.match(r'### ([A-I]\d+)', e).group(1)
    m = re.search(r'\*\*Verdict:\*\*\s*([A-Z-]+)', e)
    v = m.group(1) if m else 'MISSING'
    counts[v] = counts.get(v, 0) + 1
    rows.append((hid, v))
print('entries', len(entries)); print(json.dumps(counts, indent=1))
print([r for r in rows if r[1] == 'MISSING'])
# metrics
mrows = re.findall(r'^\| (M\d+) \|.*\| ([A-Z-]+(?: [a-z()]+)?)[^|]*\|\s*$', txt, re.M)
mc = {}
for mid, v in mrows:
    key = v.split()[0]
    mc[key] = mc.get(key, 0) + 1
print('metric rows', len(mrows)); print(json.dumps(mc, indent=1))
core = [r[0] for r in rows if r[1]=='PUBLISH-CORE']
print('CORE entries:', core)
