#!/usr/bin/env python3
"""Download NSE daily files Jan-2021 .. Oct-2026 into raw/{bhav,sec,idx}.

bhav : legacy cm bhavcopy zip before the 08-Jul-2024 UDiFF cutover, UDiFF after
sec  : sec_bhavdata_full (OHLC + delivery qty/% per symbol)
idx  : ind_close_all (all NSE index closes)
404s are cached as .404 markers (holidays). Polite: 3 workers, small sleeps.
"""
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import requests

os.environ.setdefault("REQUESTS_CA_BUNDLE", "/root/.ccr/ca-bundle.crt")
LAB = os.path.dirname(os.path.abspath(__file__))
RAW = {k: os.path.join(LAB, "raw", k) for k in ("bhav", "sec", "idx")}
for p in RAW.values():
    os.makedirs(p, exist_ok=True)

START, END = date(2021, 1, 1), date(2026, 10, 14)
CUTOVER = date(2024, 7, 8)
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
A = "https://nsearchives.nseindia.com"
OLD_CACHE = os.path.join(os.path.dirname(LAB), "label_study", "raw")

_local = threading.local()


def sess():
    if not hasattr(_local, "s"):
        s = requests.Session()
        s.headers.update({"User-Agent": "suryadhana-research/1.0 (archival research pull)"})
        _local.s = s
    return _local.s


def get(url, dest):
    """Fetch url to dest; returns 'ok' | '404' | 'cached' | 'fail'."""
    if os.path.exists(dest):
        return "cached"
    if os.path.exists(dest + ".404"):
        return "cached404"
    for attempt in range(4):
        try:
            r = sess().get(url, timeout=40)
            if r.status_code == 404:
                open(dest + ".404", "w").close()
                return "404"
            if r.status_code == 200 and len(r.content) > 200:
                tmp = dest + ".part"
                with open(tmp, "wb") as fh:
                    fh.write(r.content)
                os.replace(tmp, dest)
                return "ok"
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))
    return "fail"


def task(d):
    ymd, dmy = d.strftime("%Y%m%d"), d.strftime("%d%m%Y")
    res = {}
    # bhav
    udiff_url = f"{A}/content/cm/BhavCopy_NSE_CM_0_0_0_{ymd}_F_0000.csv.zip"
    if d < CUTOVER:
        m = MON[d.month - 1]
        legacy_url = f"{A}/content/historical/EQUITIES/{d.year}/{m}/cm{d:%d}{m}{d.year}bhav.csv.zip"
        res["bhav"] = get(legacy_url, os.path.join(RAW["bhav"], f"{ymd}.L.zip"))
        if res["bhav"] in ("404", "cached404", "fail") and d >= date(2024, 1, 1):
            res["bhav_u"] = get(udiff_url, os.path.join(RAW["bhav"], f"{ymd}.U.zip"))
    else:
        dest = os.path.join(RAW["bhav"], f"{ymd}.U.zip")
        old = os.path.join(OLD_CACHE, f"{ymd}.zip")
        if not os.path.exists(dest) and os.path.exists(old):
            shutil.copy(old, dest)
        res["bhav"] = get(udiff_url, dest)
    time.sleep(0.15)
    res["sec"] = get(f"{A}/products/content/sec_bhavdata_full_{dmy}.csv",
                     os.path.join(RAW["sec"], f"{ymd}.csv"))
    time.sleep(0.15)
    res["idx"] = get(f"{A}/content/indices/ind_close_all_{dmy}.csv",
                     os.path.join(RAW["idx"], f"{ymd}.csv"))
    time.sleep(0.15)
    return d, res


def main():
    days = []
    d = START
    while d <= END:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    print(f"{len(days)} weekdays to fetch", flush=True)
    counts = {}
    done = 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(task, d) for d in days]
        for f in as_completed(futs):
            d, res = f.result()
            for k, v in res.items():
                counts[f"{k}:{v}"] = counts.get(f"{k}:{v}", 0) + 1
            done += 1
            if done % 100 == 0:
                print(f"{done}/{len(days)} {counts}", flush=True)
    print("FINAL", counts, flush=True)
    fails = {k: v for k, v in counts.items() if k.endswith(":fail")}
    if fails:
        print("WARNING failures:", fails, flush=True)


if __name__ == "__main__":
    sys.exit(main())
