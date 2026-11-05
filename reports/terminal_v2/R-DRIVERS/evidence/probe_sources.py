"""Paced verification probes (≤ 8 GETs) of free index-weight sources. Records status, size, fields."""
import httpx, time, json, io, csv, sys, datetime as dt
S="/private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/d05b13ef-dfd0-414a-bf06-771267e4c16a/scratchpad/R-DRIVERS"
UA={"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept":"*/*","Accept-Language":"en-US,en;q=0.9"}
out={}
today=dt.date(2026,11,4)
def rec(name,url,r,note=""):
    out[name]={"url":url,"status":r.status_code,"bytes":len(r.content),"ctype":r.headers.get("content-type"),"note":note}
    print(name,r.status_code,len(r.content),r.headers.get("content-type"))
c=httpx.Client(headers=UA,timeout=25,follow_redirects=True)
# 1. nseindia cookie
r=c.get("https://www.nseindia.com/",headers={**UA,"Referer":"https://www.nseindia.com/"}); rec("nse_home","https://www.nseindia.com/",r); time.sleep(1.5)
# 2. equity-stockIndices (per-constituent live; look for ffmc)
u="https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050"
r=c.get(u,headers={**UA,"Referer":"https://www.nseindia.com/market-data/live-equity-market","Accept":"application/json"}); rec("api_equity_stockIndices",u,r)
try:
    j=r.json(); d=j.get("data",[]); print(" rows",len(d)); print(" keys",sorted(d[1].keys()) if len(d)>1 else None)
    json.dump(j,open(f"{S}/sample_equity_stockIndices_NIFTY50.json","w"))
    tot=sum((x.get("ffmc") or 0) for x in d if x.get("priority")!=1 and x.get("symbol")!="NIFTY 50")
    rows=sorted([(x["symbol"],x.get("ffmc"),x.get("lastPrice"),x.get("pChange")) for x in d if x.get("symbol")!="NIFTY 50"],key=lambda t:-(t[1] or 0))
    print(" sum ffmc",tot); print(" top5",[(s,round(f/tot*100,2)) for s,f,_,_ in rows[:5]])
    out["api_equity_stockIndices"]["fields"]=sorted(d[1].keys()); out["api_equity_stockIndices"]["rows"]=len(d)
except Exception as e: print(" parse fail",e, r.text[:200])
time.sleep(1.5)
# 3. top10 weights file (ddmmyy)
for d0 in (today, today-dt.timedelta(days=1)):
    u=f"https://nsearchives.nseindia.com/content/indices/top10nifty50_{d0.strftime('%d%m%y')}.csv"
    r=c.get(u,headers={**UA,"Referer":"https://www.nseindia.com/"}); rec(f"top10_{d0}",u,r)
    if r.status_code==200:
        print(r.text[:400]); open(f"{S}/sample_top10nifty50_{d0}.csv","w").write(r.text); break
    time.sleep(1.5)
time.sleep(1.5)
# 4. constituents lists
for nm,fn in (("nifty50","ind_nifty50list.csv"),("niftybank","ind_niftybanklist.csv")):
    u=f"https://niftyindices.com/IndexConstituent/{fn}"
    r=c.get(u,headers={**UA,"Referer":"https://www.niftyindices.com/"}); rec(f"const_{nm}",u,r)
    if r.status_code==200:
        open(f"{S}/{fn}","w").write(r.text); rd=list(csv.DictReader(io.StringIO(r.text))); print(" rows",len(rd),"fields",rd[0].keys() if rd else None)
    time.sleep(1.5)
# 5. ind_close_all daily index file
u=f"https://nsearchives.nseindia.com/content/indices/ind_close_all_{today.strftime('%d%m%Y')}.csv"
r=c.get(u,headers={**UA,"Referer":"https://www.nseindia.com/"}); rec("ind_close_all",u,r)
if r.status_code==200:
    print(r.text[:300]); open(f"{S}/sample_ind_close_all_{today}.csv","w").write(r.text)
time.sleep(1.5)
# 6. factsheet pdf (HEAD-like: just size)
u="https://www.niftyindices.com/Factsheet/ind_nifty50.pdf"
r=c.get(u,headers={**UA,"Referer":"https://www.niftyindices.com/"}); rec("factsheet_nifty50_pdf",u,r)
if r.status_code==200: open(f"{S}/ind_nifty50_factsheet.pdf","wb").write(r.content)
json.dump(out,open(f"{S}/probe_sources.json","w"),indent=1)
