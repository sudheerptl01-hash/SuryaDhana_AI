#!/usr/bin/env python3
"""Second pass: (1) weekend special trading sessions (Muhurat on Sundays,
Saturday DR sessions, Budget-day sessions) for bhav/sec/idx; (2) NSE PR zips
for every session day, keeping only the Bc (book closure / ex-date) file."""
import glob
import io
import os
import sys
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import requests

os.environ.setdefault("REQUESTS_CA_BUNDLE", "/root/.ccr/ca-bundle.crt")
LAB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LAB)
import download as D  # noqa: E402

BC = os.path.join(LAB, "raw", "bc")
os.makedirs(BC, exist_ok=True)
A = "https://nsearchives.nseindia.com"
_local = threading.local()


def sess():
    if not hasattr(_local, "s"):
        s = requests.Session()
        s.headers.update({"User-Agent": "suryadhana-research/1.0 (archival research pull)"})
        _local.s = s
    return _local.s


def weekend_task(d):
    return D.task(d)


def pr_task(ymd):
    dest = os.path.join(BC, f"{ymd}.csv")
    if os.path.exists(dest) or os.path.exists(dest + ".404"):
        return ymd, "cached"
    d = date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:]))
    url = f"{A}/archives/equities/bhavcopy/pr/PR{d:%d%m%y}.zip"
    for attempt in range(4):
        try:
            r = sess().get(url, timeout=60)
            if r.status_code == 404:
                open(dest + ".404", "w").close()
                return ymd, "404"
            if r.status_code == 200:
                z = zipfile.ZipFile(io.BytesIO(r.content))
                bc = [n for n in z.namelist() if n.lower().startswith("bc") and n.lower().endswith(".csv")]
                if not bc:
                    open(dest + ".404", "w").close()
                    return ymd, "nobc"
                with open(dest, "wb") as fh:
                    fh.write(z.open(bc[0]).read())
                time.sleep(0.15)
                return ymd, "ok"
        except Exception:
            pass
        time.sleep(1.5 * (attempt + 1))
    return ymd, "fail"


def main():
    wk = []
    d = D.START
    while d <= D.END:
        if d.weekday() >= 5:
            wk.append(d)
        d += timedelta(days=1)
    print(f"{len(wk)} weekend dates to probe", flush=True)
    counts = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        for f in as_completed([ex.submit(weekend_task, x) for x in wk]):
            _, res = f.result()
            for k, v in res.items():
                counts[f"wk_{k}:{v}"] = counts.get(f"wk_{k}:{v}", 0) + 1
    print("WEEKEND", counts, flush=True)
    sessions = sorted({os.path.basename(p)[:8] for p in glob.glob(os.path.join(LAB, "raw", "bhav", "*.zip"))})
    print(f"{len(sessions)} session days for PR/Bc", flush=True)
    counts = {}
    done = 0
    with ThreadPoolExecutor(max_workers=3) as ex:
        for f in as_completed([ex.submit(pr_task, x) for x in sessions]):
            _, st = f.result()
            counts[st] = counts.get(st, 0) + 1
            done += 1
            if done % 200 == 0:
                print(f"PR {done}/{len(sessions)} {counts}", flush=True)
    print("PR FINAL", counts, flush=True)


if __name__ == "__main__":
    sys.exit(main())
