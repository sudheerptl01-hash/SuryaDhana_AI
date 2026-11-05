"""R-IV prototype: NIFTY ATM IV history from cached UDiFF F&O bhavcopies (read-only), Black-76 on the
put-call-parity forward, per expiry; a VIX-style 30-day constant-maturity ATM IV; 25-delta skew; compare with
data/nse_archive/derived/option_history.json (near-expiry ATM IV) and India VIX (GET :8010/api/derivatives/vix).
Writes CSV + JSON to the scratchpad only."""
import json, math, sys, zipfile, re, time
from datetime import date, datetime
from pathlib import Path
import numpy as np, pandas as pd, requests

ROOT = Path("/Users/sudheer/MahaKubera_108/SuryaDhana_AI")
OUT = Path("/private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/d05b13ef-dfd0-414a-bf06-771267e4c16a/scratchpad/R-IV")
FO = ROOT / "data/nse_archive/fo"
SYMBOL = sys.argv[1] if len(sys.argv) > 1 else "NIFTY"
START, END = sys.argv[2] if len(sys.argv) > 2 else "2026-10-01", sys.argv[3] if len(sys.argv) > 3 else "2026-11-04"
R = 0.065   # same constant the product uses (option_chain.py); T-bill alternative discussed in the report
FILE_RE = re.compile(r"BhavCopy_NSE_FO_0_0_0_(\d{8})_F_0000\.csv\.zip$")

def ncdf(x): return 0.5 * (1 + math.erf(x / math.sqrt(2)))
def b76(F, K, T, v, call):
    if T <= 0 or v <= 0: return max(0.0, (F - K) if call else (K - F)) * math.exp(-R * T)
    d1 = (math.log(F / K) + 0.5 * v * v * T) / (v * math.sqrt(T)); d2 = d1 - v * math.sqrt(T)
    return math.exp(-R * T) * ((F * ncdf(d1) - K * ncdf(d2)) if call else (K * ncdf(-d2) - F * ncdf(-d1)))
def iv_b76(price, F, K, T, call):
    """Implied vol by bisection on Black-76 (undiscounted forward F). None outside no-arbitrage bounds."""
    if price is None or price <= 0 or T <= 0: return None
    df = math.exp(-R * T); intr = df * max(0.0, (F - K) if call else (K - F))
    if price <= intr + 0.05 or price >= df * (F if call else K): return None
    lo, hi = 1e-3, 5.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if b76(F, K, T, mid, call) > price: hi = mid
        else: lo = mid
    v = 0.5 * (lo + hi)
    return v if 0.01 < v < 4.0 else None
def delta_b76(F, K, T, v, call):
    d1 = (math.log(F / K) + 0.5 * v * v * T) / (v * math.sqrt(T))
    return math.exp(-R * T) * (ncdf(d1) if call else ncdf(d1) - 1)

def files():
    out = []
    for p in FO.glob("*/BhavCopy_NSE_FO_0_0_0_*_F_0000.csv.zip"):
        m = FILE_RE.search(p.name)
        if m: out.append((date(int(m.group(1)[:4]), int(m.group(1)[4:6]), int(m.group(1)[6:])), p))
    return sorted(out)

def load(p):
    with zipfile.ZipFile(p) as z:
        df = pd.read_csv(z.open(z.namelist()[0]), low_memory=False)
    df = df[df.TckrSymb == SYMBOL]
    df["XpryDt"] = pd.to_datetime(df.XpryDt); df["TradDt"] = pd.to_datetime(df.TradDt)
    return df

def expiry_surface(df, day):
    """Per expiry: forward (PCP at ATM), ATM IV (interpolated at F), 25d call/put IV, n strikes with IV."""
    opts = df[df.FinInstrmTp.isin(["IDO", "STO"])]
    futs = df[df.FinInstrmTp.isin(["IDF", "STF"])].sort_values("XpryDt")
    spot = float(opts.UndrlygPric.dropna().iloc[0]) if opts.UndrlygPric.notna().any() else None
    rows = []
    for exp, o in opts.groupby("XpryDt"):
        T = ((exp - pd.Timestamp(day)).days) / 365.0 + 0.0  # expiry at 15:30 of expiry day, from 15:30 close: whole days
        if T <= 0: continue
        ce = o[o.OptnTp == "CE"].set_index("StrkPric"); pe = o[o.OptnTp == "PE"].set_index("StrkPric")
        ks = sorted(set(ce.index) & set(pe.index))
        if not ks: continue
        # price = close where traded else settle (NSE's settle is a model price on untraded strikes)
        def px(side, k):
            r = side.loc[k]; return float(r.ClsPric) if r.TtlTradgVol > 0 else None
        s_ref = spot or float(futs.ClsPric.iloc[0])
        # forward: PCP at the strike nearest spot where both sides traded; else the matching-month future; else spot*e^rT
        cands = sorted(ks, key=lambda k: abs(k - s_ref))
        F, fsrc = None, None
        for k in cands[:3]:
            c, p = px(ce, k), px(pe, k)
            if c is not None and p is not None:
                F, fsrc = k + (c - p) * math.exp(R * T), "pcp"; break
        if F is None:
            fm = futs[futs.XpryDt == exp]
            F, fsrc = (float(fm.ClsPric.iloc[0]), "future") if len(fm) else (s_ref * math.exp(R * T), "spot")
        ivs = {}
        for k in ks:
            c, p = px(ce, k), px(pe, k)
            civ = iv_b76(c, F, k, T, True) if (c is not None and k >= F * 0.97) else None
            piv = iv_b76(p, F, k, T, False) if (p is not None and k <= F * 1.03) else None
            vals = [v for v in (civ, piv) if v]
            if vals: ivs[k] = (float(np.mean(vals)), civ, piv)
        if len(ivs) < 4: continue
        kk = np.array(sorted(ivs)); vv = np.array([ivs[k][0] for k in kk])
        atm = float(np.interp(F, kk, vv))       # ATM = IV at the forward, linear in strike
        # 25-delta skew: find strikes whose delta ≈ ±0.25 using each strike's own IV
        d_c = {k: delta_b76(F, k, T, ivs[k][1], True) for k in ivs if ivs[k][1]}
        d_p = {k: delta_b76(F, k, T, ivs[k][2], False) for k in ivs if ivs[k][2]}
        def at_delta(dd, target, side):
            if len(dd) < 2: return None
            ks_ = np.array(sorted(dd)); ds = np.array([dd[k] for k in ks_])
            order = np.argsort(ds)
            if not (ds.min() <= target <= ds.max()): return None
            k_t = float(np.interp(target, ds[order], ks_[order]))
            return float(np.interp(k_t, kk, [ivs[k][1 if side else 2] or ivs[k][0] for k in kk]))
        iv25c, iv25p = at_delta(d_c, 0.25, True), at_delta(d_p, -0.25, False)
        rows.append({"date": day.isoformat(), "expiry": exp.date().isoformat(), "dte": int(T * 365 + 0.5), "T": T,
                     "spot": spot, "forward": round(F, 2), "forward_source": fsrc, "atm_iv": round(atm * 100, 2),
                     "iv_25d_put": round(iv25p * 100, 2) if iv25p else None, "iv_25d_call": round(iv25c * 100, 2) if iv25c else None,
                     "skew_25d": round((iv25p - iv25c) * 100, 2) if (iv25p and iv25c) else None,
                     "n_iv_strikes": len(ivs), "call_oi": float(ce.OpnIntrst.sum()), "put_oi": float(pe.OpnIntrst.sum())})
    return rows

def cm30(rows):
    """VIX-style constant-maturity 30-day ATM variance interpolation between the expiries bracketing 30 days."""
    r = sorted([x for x in rows if x["dte"] >= 1], key=lambda x: x["dte"])
    if not r: return None
    near = [x for x in r if x["dte"] <= 30]; far = [x for x in r if x["dte"] > 30]
    if near and far:
        a, b = near[-1], far[0]
        ta, tb, t30 = a["dte"] / 365, b["dte"] / 365, 30 / 365
        va, vb = (a["atm_iv"] / 100) ** 2 * ta, (b["atm_iv"] / 100) ** 2 * tb
        w = (tb - t30) / (tb - ta)
        var30 = (va * w + vb * (1 - w)) / t30
        return round(math.sqrt(max(var30, 0)) * 100, 2)
    return None

t0 = time.time()
surf, summ = [], []
for day, path in files():
    if not (START <= day.isoformat() <= END): continue
    df = load(path)
    rows = expiry_surface(df, day)
    surf.extend(rows)
    near = [x for x in rows if x["dte"] > 2]
    near = sorted(near, key=lambda x: x["dte"])
    monthly = [x for x in rows if 20 <= x["dte"] <= 60]
    summ.append({"date": day.isoformat(), "spot": rows[0]["spot"] if rows else None,
                 "near_expiry": near[0]["expiry"] if near else None, "near_dte": near[0]["dte"] if near else None,
                 "near_atm_iv": near[0]["atm_iv"] if near else None,
                 "iv30_cm": cm30(rows),
                 "monthly_expiry": monthly[0]["expiry"] if monthly else None, "monthly_atm_iv": monthly[0]["atm_iv"] if monthly else None,
                 "monthly_skew_25d": monthly[0]["skew_25d"] if monthly else None,
                 "term_ratio_near_over_monthly": round(near[0]["atm_iv"] / monthly[0]["atm_iv"], 3) if (near and monthly and monthly[0]["atm_iv"]) else None})
print(f"{len(summ)} sessions, {len(surf)} expiry rows, {time.time()-t0:.1f}s")
S = pd.DataFrame(summ); X = pd.DataFrame(surf)
S.to_csv(OUT / f"iv_summary_{SYMBOL}.csv", index=False); X.to_csv(OUT / f"iv_surface_{SYMBOL}.csv", index=False)

# compare with option_history.json and India VIX
oh = json.load(open(ROOT / "data/nse_archive/derived/option_history.json")).get(SYMBOL, [])
OH = pd.DataFrame(oh)[["date", "atm_iv", "expiry"]].rename(columns={"atm_iv": "product_atm_iv", "expiry": "product_expiry"})
vix = requests.get("http://127.0.0.1:8010/api/derivatives/vix", params={"days": 400}, timeout=30).json()["rows"]
V = pd.DataFrame(vix); V["date"] = V["date"].str[:10]; V = V[["date", "vix", "rv20"]]
M = S.merge(OH, on="date", how="left").merge(V, on="date", how="left")
M.to_csv(OUT / f"iv_compare_{SYMBOL}.csv", index=False)
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
print(M[["date", "spot", "near_expiry", "near_dte", "near_atm_iv", "product_atm_iv", "product_expiry", "iv30_cm", "monthly_atm_iv", "monthly_skew_25d", "vix", "rv20"]].to_string(index=False))
def stats(a, b, name):
    m = M[[a, b]].dropna(); d = m[a] - m[b]
    print(f"{name}: n={len(m)} corr_level={m[a].corr(m[b]):.3f} corr_diff={m[a].diff().corr(m[b].diff()):.3f} mean_diff={d.mean():+.2f} mad={d.abs().mean():.2f} max_abs={d.abs().max():.2f}")
stats("near_atm_iv", "product_atm_iv", "ours(near, interp at F) vs product option_history (near, nearest strike)")
stats("near_atm_iv", "vix", "ours near ATM IV vs India VIX")
stats("iv30_cm", "vix", "ours 30d constant-maturity ATM IV vs India VIX")
stats("monthly_atm_iv", "vix", "ours monthly-expiry ATM IV vs India VIX")
json.dump({"sessions": len(summ), "expiry_rows": len(surf), "seconds": round(time.time() - t0, 1)}, open(OUT / f"iv_proto_meta_{SYMBOL}.json", "w"))
