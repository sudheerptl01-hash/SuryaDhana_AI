"""R-DRIVERS prototype: NIFTY 50 / NIFTY BANK point-contribution leaderboard from stored closes (read-only DB copy).
DESCRIPTIVE attribution only. Weights rebuilt PIT: shares (XBRL filings, filed_at <= d) x prev_close x (1 - promoter %
from the latest shareholding filing broadcast <= d); optional calibration against NSE's daily top-10 weight file."""
import sys, json, csv, io, math, datetime as dt
import duckdb, pandas as pd, numpy as np
sys.path.insert(0, "/Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/data-service"); sys.path.insert(0, "/Users/sudheer/MahaKubera_108/SuryaDhana_AI")
import financials as fin
S = "/private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/d05b13ef-dfd0-414a-bf06-771267e4c16a/scratchpad/R-DRIVERS"
from pathlib import Path; FIN = Path("/Users/sudheer/MahaKubera_108/SuryaDhana_AI/data/nse_archive/financials")
con = duckdb.connect(f"{S}/market_ro.duckdb", read_only=True)
START = "2025-12-01"
out = {}

def members(fn):
    rows = list(csv.DictReader(open(f"{S}/{fn}")))
    return {r["Symbol"].strip(): r["Industry"].strip() for r in rows if r["Series"].strip() == "EQ"}

from shared.nse_panel import adjust, pick_equity_rows
SPLITS = con.execute("select ticker, date, ratio from splits where ratio > 0").df()
SPLITS["date"] = pd.to_datetime(SPLITS["date"]).dt.tz_localize(None).dt.normalize()
FLAGS = []
def load_panel(syms):
    raw = con.execute("""select * from nse_bhavcopy where date >= ? and list_contains(?, symbol) order by date""",
                      [dt.date.fromisoformat(START) - dt.timedelta(days=10), syms]).df()
    raw["date"] = pd.to_datetime(raw["date"])
    adj = adjust(pick_equity_rows(raw), SPLITS)            # the store's own adjustment (splits + bonuses from `splits`)
    adj = adj.sort_values(["symbol", "date"])
    adj["ret"] = adj.groupby("symbol")["adj_close"].pct_change()
    df = adj[adj["date"] >= pd.Timestamp(START)][["symbol", "date", "prev_close", "close", "adj_close", "ret"]].copy()
    for _, r in df[df["ret"].abs() > 0.25].iterrows():
        FLAGS.append({"symbol": r["symbol"], "date": str(r["date"].date()), "ret_pct": round(float(r["ret"] * 100), 1), "note": "jump > 25 % after split adjustment: corporate action missing from `splits`? excluded"})
    df.loc[df["ret"].abs() > 0.25, "ret"] = np.nan
    return df

def promoter_pit(syms):
    sh = con.execute("""select symbol, period_end, broadcast_ts, promoter_pct from nse_shareholding
                        where list_contains(?, symbol) and promoter_pct is not null""", [syms]).df()
    sh["period_end"] = pd.to_datetime(sh["period_end"])
    b = pd.to_datetime(sh["broadcast_ts"], errors="coerce", dayfirst=True)
    sh["public_at"] = b.fillna(sh["period_end"] + pd.Timedelta(days=21)).dt.normalize()
    return sh.sort_values("public_at")

def shares_pit(sym, day):
    c = fin.load(FIN, sym)
    if not c or not c.get("quarters"):
        return None
    q = [x for x in c["quarters"] if (x.get("filed_at") or "9999") <= day.strftime("%Y-%m-%dT%H:%M:%S")]
    if not q:
        return None
    q = sorted(q, key=lambda x: x.get("period_end") or "", reverse=True)
    sh = fin.shares_estimate(fin.with_growth(q))
    if not sh:
        return None
    pe = pd.Timestamp(q[0]["period_end"])
    k = SPLITS[(SPLITS.ticker == sym) & (SPLITS.date > pe) & (SPLITS.date <= day)]["ratio"].prod()
    return sh * float(k)

def build(index_name, syms_ind, idx_close, cap=None):
    syms = sorted(syms_ind)
    px = load_panel(syms)
    sh = promoter_pit(syms)
    dates = sorted(px["date"].unique())
    idx = idx_close.reindex(pd.DatetimeIndex(dates)).dropna()
    rows = []
    share_cache = {}
    for d in idx.index:
        day = px[px["date"] == d].set_index("symbol")
        rec = []
        for s in syms:
            if s not in day.index or not np.isfinite(day.loc[s, "ret"]):
                continue
            key = (s, d.strftime("%Y-%m"))
            if key not in share_cache:
                share_cache[key] = shares_pit(s, d)
            shares = share_cache[key]
            if not shares:
                continue
            p = sh[(sh.symbol == s) & (sh.public_at <= d)]
            promo = float(p["promoter_pct"].iloc[-1]) if len(p) else 0.0
            rec.append((s, shares * day.loc[s, "prev_close"] * (1 - promo / 100), day.loc[s, "ret"]))
        if not rec:
            continue
        tot = sum(f for _, f, _ in rec)
        w = {s: f / tot for s, f, _ in rec}
        if cap:   # NSE sector-index capping (single <= cap[0], top-3 <= cap[1]) applied approximately each day
            for _ in range(5):
                over = {s: cap[0] for s, v in w.items() if v > cap[0]}
                if over:
                    rest = 1 - sum(over.values()); free = sum(v for s, v in w.items() if s not in over)
                    w = {s: (over[s] if s in over else v / free * rest) for s, v in w.items()}
                top3 = sorted(w, key=w.get, reverse=True)[:3]
                if sum(w[s] for s in top3) > cap[1]:
                    k = cap[1] / sum(w[s] for s in top3); rest = 1 - cap[1]; free = sum(v for s, v in w.items() if s not in top3)
                    w = {s: (v * k if s in top3 else v / free * rest) for s, v in w.items()}
        prev_level = idx.shift(1).get(d)
        if prev_level is None or not np.isfinite(prev_level):
            continue
        for s, f, r in rec:
            rows.append({"date": d, "symbol": s, "weight": w[s], "ret": r, "points": prev_level * w[s] * r})
    c = pd.DataFrame(rows)
    c["industry"] = c["symbol"].map(syms_ind)
    return c, idx

def summarise(name, c, idx, horizons):
    res = {"index": name, "sessions": int(c["date"].nunique()), "first": str(c["date"].min().date()), "last": str(c["date"].max().date())}
    # daily fit: explained vs actual points
    daily = c.groupby("date")["points"].sum()
    actual = idx.diff().reindex(daily.index)
    err = daily - actual
    res["fit"] = {"n": int(len(err.dropna())), "mae_pts": round(float(err.abs().mean()), 2), "rmse_pts": round(float(np.sqrt((err ** 2).mean())), 2),
                  "mean_abs_actual_pts": round(float(actual.abs().mean()), 2), "r2": round(float(1 - (err ** 2).sum() / ((actual - actual.mean()) ** 2).sum()), 4),
                  "explained_share_median": round(float((daily / actual).replace([np.inf, -np.inf], np.nan).dropna().median()), 3)}
    dates = sorted(c["date"].unique()); last = dates[-1]
    res["horizons"] = {}
    for h, n in horizons.items():
        if isinstance(n, str):
            sel = c[c["date"] > pd.Timestamp(n)]
        else:
            sel = c[c["date"].isin(dates[-n:])]
        g = sel.groupby("symbol")["points"].sum().sort_values(ascending=False)
        sec = sel.groupby("industry")["points"].sum().sort_values(ascending=False)
        a = abs(g); top5_share = float(a.sort_values(ascending=False).head(5).sum() / a.sum()) if a.sum() else None
        hhi_c = float(((a / a.sum()) ** 2).sum()) if a.sum() else None
        first_d = sel["date"].min(); idx_move = float(idx.loc[last] - idx.loc[:first_d].iloc[-2]) if len(idx.loc[:first_d]) > 1 else None
        lw = sel[sel["date"] == last].set_index("symbol")["weight"]
        hhi_w = float((lw ** 2).sum()); eff_n = 1 / hhi_w if hhi_w else None
        up = sel.groupby("symbol")["ret"].apply(lambda r: (1 + r).prod() - 1)
        ew = float(up.mean()); cw = float(idx.loc[last] / idx.loc[:first_d].iloc[-2] - 1) if idx_move is not None else None
        res["horizons"][h] = {"sessions": int(sel["date"].nunique()), "from": str(first_d.date()), "index_move_pts": round(idx_move, 1) if idx_move is not None else None,
                              "explained_pts": round(float(g.sum()), 1), "top5_add": [(s, round(v, 1)) for s, v in g.head(5).items()],
                              "top5_drag": [(s, round(v, 1)) for s, v in g.tail(5)[::-1].items()],
                              "top5_abs_share": round(top5_share, 3) if top5_share else None, "hhi_contrib": round(hhi_c, 4) if hhi_c else None,
                              "weight_hhi": round(hhi_w, 4), "effective_n": round(eff_n, 1) if eff_n else None, "top5_weight_pct": round(float(lw.sort_values(ascending=False).head(5).sum() * 100), 2),
                              "sector_pts": [(s, round(v, 1)) for s, v in sec.items()],
                              "members_up": int((up > 0).sum()), "members_down": int((up < 0).sum()), "equal_weight_ret_pct": round(ew * 100, 2),
                              "index_ret_pct": round(cw * 100, 2) if cw is not None else None, "ew_minus_cw_pp": round((ew - cw) * 100, 2) if cw is not None else None}
    # monthly top-5 and leader changes
    c["ym"] = c["date"].dt.strftime("%Y-%m")
    months = []
    prev_leader = None
    for ym, g in c.groupby("ym"):
        s = g.groupby("symbol")["points"].sum().sort_values(ascending=False)
        a = s.abs().sort_values(ascending=False)
        d0, d1 = g["date"].min(), g["date"].max()
        move = float(idx.loc[d1] - idx.loc[:d0].iloc[-2]) if len(idx.loc[:d0]) > 1 else None
        leader = a.index[0]
        months.append({"month": ym, "sessions": int(g["date"].nunique()), "index_move_pts": round(move, 1) if move is not None else None,
                       "explained_pts": round(float(s.sum()), 1), "top5_add": [(k, round(v, 1)) for k, v in s.head(5).items()],
                       "top5_drag": [(k, round(v, 1)) for k, v in s.tail(5)[::-1].items()],
                       "leader_abs": leader, "leader_pts": round(float(s[leader]), 1), "leader_share_of_abs": round(float(a.iloc[0] / a.sum()), 3),
                       "leader_changed": (prev_leader is not None and leader != prev_leader), "top5_abs_share": round(float(a.head(5).sum() / a.sum()), 3)})
        prev_leader = leader
    res["monthly"] = months
    # rolling 20-session leader (by |points|) and by + points: change events
    piv = c.pivot_table(index="date", columns="symbol", values="points", aggfunc="sum").fillna(0.0)
    roll = piv.rolling(20).sum().dropna(how="all")
    lead = roll.abs().idxmax(axis=1); lead_pos = roll.idxmax(axis=1); lead_neg = roll.idxmin(axis=1)
    share = roll.abs().max(axis=1) / roll.abs().sum(axis=1)
    top5s = roll.abs().apply(lambda r: r.sort_values(ascending=False).head(5).sum() / r.sum(), axis=1)
    ev = []
    for i in range(1, len(lead)):
        if lead.iloc[i] != lead.iloc[i - 1]:
            ev.append({"date": str(lead.index[i].date()), "from": lead.iloc[i - 1], "to": lead.iloc[i], "to_pts_20s": round(float(roll.iloc[i][lead.iloc[i]]), 1), "leader_share": round(float(share.iloc[i]), 3)})
    res["rolling20"] = {"as_of": str(lead.index[-1].date()), "leader_abs": lead.iloc[-1], "leader_pos": lead_pos.iloc[-1], "leader_neg": lead_neg.iloc[-1],
                        "leader_share": round(float(share.iloc[-1]), 3), "top5_share": round(float(top5s.iloc[-1]), 3),
                        "leader_changes": len(ev), "events": ev, "leader_tenure_sessions": int((lead == lead.iloc[-1])[::-1].cumprod().sum()),
                        "ranking_20s": [(s, round(v, 1)) for s, v in roll.iloc[-1].sort_values(ascending=False).head(10).items()]}
    # breadth vs index divergence (rolling 20 sessions): EW minus CW
    r = c.pivot_table(index="date", columns="symbol", values="ret").fillna(0.0)
    ew20 = (1 + r).rolling(20).apply(np.prod, raw=True).mean(axis=1) - 1
    cw20 = idx.reindex(r.index).pct_change(20)
    div = (ew20 - cw20) * 100
    res["breadth_div"] = {"as_of": str(div.dropna().index[-1].date()), "ew20_pct": round(float(ew20.dropna().iloc[-1] * 100), 2), "cw20_pct": round(float(cw20.dropna().iloc[-1] * 100), 2),
                          "ew_minus_cw_pp": round(float(div.dropna().iloc[-1]), 2), "pct_members_up_last_session": round(float((r.iloc[-1] > 0).mean() * 100), 1),
                          "series_tail": [(str(d.date()), round(float(v), 2)) for d, v in div.dropna().tail(10).items()],
                          "min": (str(div.idxmin().date()), round(float(div.min()), 2)), "max": (str(div.idxmax().date()), round(float(div.max()), 2))}
    return res, roll, share, top5s, div

# ---------- NIFTY 50
n50 = members("ind_nifty50list.csv")
nifty_y = con.execute("select date, close from market_index_daily where symbol='NIFTY50' and date >= ? order by date", [dt.date.fromisoformat(START)]).df()
nifty_y = pd.Series(nifty_y["close"].values, index=pd.to_datetime(nifty_y["date"]))
_h = pd.read_csv("/Users/sudheer/MahaKubera_108/SuryaDhana_AI/data/nse_archive/derived/index_valuation_history.csv", parse_dates=["date"])
_n = _h[_h["index"] == "NIFTY 50"].sort_values("date"); nifty_nse = pd.Series(_n["close"].values, index=_n["date"]); nifty_nse = nifty_nse[nifty_nse.index >= START]
nifty = nifty_nse.combine_first(nifty_y).sort_index()   # NSE daily index file first (has the 1 Feb 2026 special session); Yahoo fills 2-4 Nov
out["INDEX_SOURCE_NOTE"] = {"nse_rows": int(len(nifty_nse)), "nse_last": str(nifty_nse.index[-1].date()), "yahoo_rows": int(len(nifty_y)), "yahoo_missing_sessions_vs_nse": [str(d.date()) for d in nifty_nse.index.difference(nifty_y.index)], "max_abs_diff_common_pts": round(float((nifty_nse - nifty_y).dropna().abs().max()), 2)}
c50, idx50 = build("NIFTY 50", n50, nifty)
H = {"1d": 1, "5d": 5, "1m": 21, "3m": 63, "60s": 60, "ytd": "2025-12-31"}
r50, roll50, share50, top5s50, div50 = summarise("NIFTY 50", c50, idx50, H)
# calibration of the latest day's rebuilt weights against NSE's top-10 file (04 Nov 2026)
top10 = {r["SYMBOL"].strip(): float(r["WEIGHTAGE(%)"]) for r in csv.DictReader(open(f"{S}/sample_top10nifty50_2026-11-04.csv"))}
lw = c50[c50["date"] == c50["date"].max()].set_index("symbol")["weight"] * 100
cal = [{"symbol": s, "official_pct": v, "rebuilt_pct": round(float(lw.get(s, np.nan)), 2), "diff_pp": round(float(lw.get(s, np.nan) - v), 2),
        "implied_iwf_correction": round(float(v / lw.get(s, np.nan)), 3)} for s, v in top10.items()]
r50["calibration_top10"] = {"date": str(c50["date"].max().date()), "rows": cal, "official_top10_sum": round(sum(top10.values()), 2), "rebuilt_top10_sum": round(float(sum(lw.get(s, 0) for s in top10)), 2),
                            "mae_pp": round(float(np.mean([abs(x["diff_pp"]) for x in cal])), 2)}
out["NIFTY50"] = r50
c50.to_csv(f"{S}/nifty50_daily_contrib.csv.gz", index=False)
# ---------- NIFTY BANK (closes from the NSE daily index files archived by the project; capping 33% / 62%)
h = pd.read_csv("/Users/sudheer/MahaKubera_108/SuryaDhana_AI/data/nse_archive/derived/index_valuation_history.csv", parse_dates=["date"])
bank = h[h["index"] == "NIFTY BANK"].sort_values("date")
bank = pd.Series(bank["close"].values, index=bank["date"])
bank = bank[bank.index >= START]
nb = members("ind_niftybanklist.csv")
cb, idxb = build("NIFTY BANK", nb, bank, cap=(0.33, 0.62))
rb, *_ = summarise("NIFTY BANK", cb, idxb, {"1d": 1, "5d": 5, "1m": 21, "3m": 63, "60s": 60, "ytd": "2025-12-31"})
out["NIFTYBANK"] = rb
cb.to_csv(f"{S}/niftybank_daily_contrib.csv.gz", index=False)
# ---------- Desk book (illustrative: the Desk is risk-off / cash; use the 30 Oct plan's watchlist as the would-be book)
import sqlite3
dd = sqlite3.connect(f"{S}/decision_desk_ro.db")
plan = json.loads(dd.execute("select summary from plans order by created_at desc limit 1").fetchone()[0])
wl = [w["symbol"] for w in plan["watchlist"]][:20]
pxw = load_panel(wl)
sel = pxw[pxw["date"].isin(sorted(c50["date"].unique())[-60:])]
rw = sel.pivot_table(index="date", columns="symbol", values="ret").fillna(0.0)
eq = 0.66 / len(wl)   # equity share 66 %, equal weight; liquid-fund leg assumed flat
book_daily = rw.sum(axis=1) * eq
contrib = (rw * eq * 100).sum().sort_values(ascending=False)
book_ret = float(((1 + book_daily).prod() - 1) * 100)
nif60 = float((idx50.loc[rw.index[-1]] / idx50.loc[:rw.index[0]].iloc[-2] - 1) * 100)
out["DESK_ILLUSTRATIVE"] = {"note": "Desk is risk-off (NIFTY < 200-DMA at the 30 Oct signal), book = 100 % liquid fund; this uses the 30 Oct plan's ranked watchlist as a hypothetical 66 %-equity equal-weight book over the last 60 sessions. ILLUSTRATIVE, not P&L.",
                            "names": wl, "sessions": int(len(rw)), "from": str(rw.index[0].date()), "to": str(rw.index[-1].date()), "book_ret_pct_approx": round(book_ret, 2), "nifty_ret_pct": round(nif60, 2),
                            "active_pp": round(book_ret - nif60, 2), "top5_contrib_pp": [(s, round(v, 2)) for s, v in contrib.head(5).items()], "bottom5_contrib_pp": [(s, round(v, 2)) for s, v in contrib.tail(5)[::-1].items()],
                            "names_up": int((rw.add(1).prod() - 1 > 0).sum()), "nifty_top5_same_window": out["NIFTY50"]["horizons"]["60s"]["top5_add"]}
out["DATA_FLAGS"] = FLAGS
json.dump(out, open(f"{S}/drivers_results.json", "w"), indent=1, default=str)
# charts
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
fig, ax = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
tail = roll50.tail(130)
for s in tail.iloc[-1].abs().sort_values(ascending=False).head(6).index:
    ax[0].plot(tail.index, tail[s], label=s)
ax[0].axhline(0, color="#666", lw=0.6); ax[0].set_title("NIFTY 50: rolling 20-session point contribution, today's top-6 names (descriptive attribution)"); ax[0].legend(ncol=6, fontsize=8); ax[0].set_ylabel("index points")
ax[1].plot(share50.tail(130).index, share50.tail(130) * 100, label="leader share of |contribution| (20s)"); ax[1].plot(top5s50.tail(130).index, top5s50.tail(130) * 100, label="top-5 share (20s)")
ax[1].set_ylabel("%"); ax[1].legend(fontsize=8); ax[1].set_title("Concentration of the move")
ax[2].plot(div50.dropna().tail(130).index, div50.dropna().tail(130), color="#7a5"); ax[2].axhline(0, color="#666", lw=0.6)
ax[2].set_title("Breadth vs index: equal-weight 50 minus NIFTY 50, rolling 20 sessions (pp)"); ax[2].set_ylabel("pp")
plt.tight_layout(); plt.savefig("/Users/sudheer/MahaKubera_108/SuryaDhana_AI/reports/terminal_v2/R-DRIVERS/nifty_drivers_prototype.png", dpi=110)
print(json.dumps({k: out["NIFTY50"][k] for k in ("sessions", "first", "last", "fit", "rolling20", "breadth_div", "calibration_top10")}, indent=1, default=str)[:6000])
