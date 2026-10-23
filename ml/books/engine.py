"""Book construction on top of ml/strategy_backtest.py's engine (imported, defaults untouched).

* ``neutralise``      per-date OLS residual of the score's percentile rank on the controls' percentile ranks,
                      re-ranked (vol; vol+size; vol+size+industry with the score rank first demeaned by industry).
* ``members_*``       per-block basket membership: the engine's top decile, a top quintile, and the buffered
                      decile whose tranche k inherits names of tranche k-H still in the top 20%.
* ``build_blocks_h``  a second block set for H != 20 (open-to-open marks, no label pin).
* ``BookEngine``      ``sb.Engine`` with ``run_members`` (membership supplied by the caller, so it may depend on
                      earlier blocks) and one extra cost variant, the pre-specified name-level cost model.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

import ml.strategy_backtest as sb

AUM_RS = 1e9                    # Rs 100 crore book: order per name q_i = AUM / basket size
STAT_FLOOR = 11e-4              # 11 bps statutory floor per side
IMPACT_K = 0.1                  # square-root impact coefficient
QUINTILE = 0.20
HOLD_FRAC = 0.20                # buffered decile: keep an inherited name while within the top 20%
NAME_KEY = "name_level"


# --------------------------------------------------------------------------- neutralisation
def _pct_rank_by_date(x: np.ndarray, codes: np.ndarray) -> np.ndarray:
    return pd.Series(x).groupby(codes).rank(pct=True).to_numpy(float)


def neutralise(score: np.ndarray, kind: str, codes: np.ndarray, atr: np.ndarray, logturn: np.ndarray,
               ind_codes: np.ndarray | None) -> np.ndarray:
    """New score for one neutralisation kind, computed per signal date on that date's clean universe rows.
    none -> the raw score (identical ordering to its percentile rank, so the engine's books are unchanged)."""
    if kind == "none":
        return score.copy()
    r = _pct_rank_by_date(score, codes)
    ra = _pct_rank_by_date(atr, codes)
    ra = np.where(np.isfinite(ra), ra, 0.5)                 # atr_pct missing on 0.18% of rows -> neutral rank
    rt = _pct_rank_by_date(logturn, codes)
    y = r.copy()
    if kind == "vol+size+industry":
        y = r - pd.Series(r).groupby([codes, ind_codes]).transform("mean").to_numpy(float)
    X = [np.ones_like(r), ra] if kind == "vol" else [np.ones_like(r), ra, rt]
    X = np.column_stack(X)
    res = np.empty_like(r)
    order = np.argsort(codes, kind="stable")
    bounds = np.flatnonzero(np.diff(codes[order])) + 1
    for idx in np.split(order, bounds):
        b, *_ = np.linalg.lstsq(X[idx], y[idx], rcond=None)
        res[idx] = y[idx] - X[idx] @ b
    return _pct_rank_by_date(res, codes)


def industry_groups(base: pd.DataFrame, mp: dict, min_names: int = 5) -> tuple[np.ndarray, dict]:
    """Per row industry code; an industry with fewer than ``min_names`` names on a date joins 'Unclassified'
    for that date."""
    ind = base["ticker"].map(mp).fillna("Unclassified").to_numpy(object)
    codes = base["date"].to_numpy()
    df = pd.DataFrame({"d": codes, "g": ind})
    n = df.groupby(["d", "g"])["g"].transform("size").to_numpy()
    ind2 = np.where(n >= min_names, ind, "Unclassified")
    cats = sorted(set(ind2))
    code_of = {c: i for i, c in enumerate(cats)}
    out = np.array([code_of[c] for c in ind2])
    cov = {"rows_classified_share": float(np.mean(ind != "Unclassified")),
           "rows_in_unclassified_after_min_group_rule": float(np.mean(ind2 == "Unclassified")),
           "industries_used": len(cats) - (1 if "Unclassified" in cats else 0),
           "names_per_date_classified_mean": float(pd.Series(ind != "Unclassified").groupby(codes).sum().mean())}
    return out, cov


# --------------------------------------------------------------------------- baskets
def _order(s: np.ndarray, ci: np.ndarray, valid: np.ndarray) -> np.ndarray:
    cand = np.flatnonzero(valid)
    return cand[np.lexsort((ci[cand], -s[cand]))]           # score desc, ticker asc (as sb.select)


def members_simple(blocks, score: np.ndarray, kind: str) -> list[tuple[np.ndarray, np.ndarray | None]]:
    """top_decile / ls_decile / liq_* via the engine's own select(); top_quintile = top 20% equal weight."""
    out = []
    for b in blocks:
        s = score[b.rows]
        if kind.endswith("top_quintile"):
            valid = np.isfinite(s) & (b.liq if kind.startswith("liq_") else True)
            o = _order(s, b.ci, valid)
            out.append((o[:max(1, int(round(QUINTILE * o.size)))], None))
        else:
            out.append(sb.select(s, b.ci, b.liq, kind))
    return out


def members_buffered(blocks, score: np.ndarray, liq_only: bool, H: int) -> tuple[list, dict]:
    """Buffered decile with hysteresis across tranches. Tranche k (signal date t) inherits every name held by the
    tranche it replaces (block k-H) whose current rank is within the top 20% of today's (liquid) universe, then
    fills up to today's decile size with the highest-ranked names not already held. The first H tranches have no
    predecessor and are plain deciles."""
    out, held = [], []
    n_inh, n_over = [], 0
    for k, b in enumerate(blocks):
        s = score[b.rows]
        valid = np.isfinite(s) & (b.liq if liq_only else True)
        o = _order(s, b.ci, valid)
        kd = max(1, int(round(sb.TOP_FRAC * o.size)))
        if k < H:
            sel = o[:kd]
        else:
            prev = held[k - H]
            topq = o[:max(1, int(round(HOLD_FRAC * o.size)))]
            inh = topq[np.isin(b.ci[topq], prev)]
            rest = o[~np.isin(o, inh)]
            sel = np.concatenate([inh, rest[:max(0, kd - inh.size)]])
            n_inh.append(inh.size / kd)
            n_over += int(inh.size > kd)
        out.append((sel, None))
        held.append(b.ci[sel])
    return out, {"mean_inherited_share_of_decile": float(np.mean(n_inh)) if n_inh else None,
                 "tranches_where_inherited_exceed_decile_size": n_over}


# --------------------------------------------------------------------------- H != 20 block set
def build_blocks_h(base_sub: pd.DataFrame, sessions, tick, O: pd.DataFrame, adv20: pd.DataFrame, H: int):
    """sb.build_blocks for a holding period H with no label to pin to: path = open[t+1 .. t+1+H] / open[t+1] from
    the price grid (forward-filled gaps, entry back-filled when the t+1 open is missing). Signal dates whose t+H+1
    session does not exist are dropped. ``base_sub`` keeps the base index, so b.rows indexes full score arrays."""
    col_of = {t: j for j, t in enumerate(tick)}
    pos_of = {d: i for i, d in enumerate(sessions)}
    Ov, Of, Ob, Av = O.to_numpy(float), O.ffill().to_numpy(float), O.bfill().to_numpy(float), adv20.to_numpy(float)
    blocks, n_bfill, n_drop = [], 0, 0
    for date, grp in base_sub.groupby("date", sort=True):
        p = pos_of[date]
        if p + 1 + H > len(sessions) - 1:
            n_drop += 1
            continue
        rows = grp.index.to_numpy()
        ci = grp["ticker"].map(col_of).to_numpy()
        entry = Ov[p + 1, ci]
        miss = ~np.isfinite(entry)
        n_bfill += int(miss.sum())
        entry = np.where(miss, Ob[p + 1, ci], entry)
        path = Of[p + 1:p + 1 + H + 1, ci] / entry[None, :]
        path[0] = 1.0
        path = pd.DataFrame(path).ffill().fillna(1.0).to_numpy()
        ctr = grp["cs_rank_turnover"].to_numpy(float)
        blocks.append(sb.Block(
            date=date, pos=p, segment=grp["segment"].iat[0], fold=grp["fold"].iat[0], month=grp["month"].iat[0],
            rows=rows, ci=ci, path=path, y_exc=grp["y_excess_20d"].to_numpy(float),
            med=float(np.median(path[H] - 1.0)), liq=ctr >= sb.LIQ_CUT,
            tercile=np.where(ctr >= sb.LIQ_CUT, 2, np.where(ctr >= 0.33, 1, 0)), adv=Av[p, ci]))
    pos = np.array([b.pos for b in blocks])
    assert np.all(np.diff(pos) == 1), "signal dates must be consecutive sessions"
    return blocks, {"H": H, "rows": int(sum(len(b.rows) for b in blocks)), "signal_dates": len(blocks),
                    "signal_dates_dropped_no_exit_session": n_drop, "entry_open_backfilled": n_bfill,
                    "first": str(blocks[0].date.date()), "last": str(blocks[-1].date.date())}


# --------------------------------------------------------------------------- name-level costs
def name_cost_fracs(W: np.ndarray, blocks, size: np.ndarray, comp: dict, H: int, aum: float = AUM_RS) -> dict:
    """Per-tranche cost fractions under the name-level model, netted like trade_fracs but name by name:
    entry of tranche k pays sum_i c_i(t_k) max(w_k,i - w_{k-H},i, 0); its exit (executed with tranche k+H's entry)
    pays sum_i c_i(t_{k+H}) max(w_k,i - w_{k+H},i, 0); c_i(t) = max(11 bps, half_spread + 0.1 sigma sqrt(q / ADV))
    with q = AUM / (size of the tranche whose position is traded). Tranches without a neighbour are charged the
    median steady-state value, as the engine does for turnover."""
    hs, sg, adv = comp["half_spread"], comp["sigma"], comp["adv"]
    n = W.shape[0]
    buy, sell = np.full(n, np.nan), np.full(n, np.nan)
    acc = np.zeros(5)                   # traded weight, cost, half-spread, impact, weight at the floor (buys)

    def c_at(p: int, cols: np.ndarray, nsize: float):
        q = aum / max(nsize, 1.0)
        h, im = hs[p, cols], IMPACT_K * sg[p, cols] * np.sqrt(q / adv[p, cols])
        return np.maximum(STAT_FLOOR, h + im), h, im

    for k in range(H, n):
        d = W[k] - W[k - H]
        p = blocks[k].pos
        ib, is_ = np.flatnonzero(d > 1e-15), np.flatnonzero(d < -1e-15)
        cb, hb, mb = c_at(p, ib, size[k])
        cs, _, _ = c_at(p, is_, size[k - H])
        buy[k] = float((cb * d[ib]).sum())
        sell[k - H] = float((cs * -d[is_]).sum())
        wb = d[ib]
        acc += [wb.sum(), (cb * wb).sum(), (hb * wb).sum(), (mb * wb).sum(), wb[hb + mb <= STAT_FLOOR].sum()]
    ssb = float(np.nanmedian(buy)) if np.isfinite(buy).any() else 0.0
    sss = float(np.nanmedian(sell)) if np.isfinite(sell).any() else 0.0
    tw = acc[0] if acc[0] > 0 else np.nan
    return {"buy": np.where(np.isfinite(buy), buy, ssb), "sell": np.where(np.isfinite(sell), sell, sss),
            "trade_weighted_cost_bps_per_side": 1e4 * float(acc[1] / tw),
            "decomposition_of_buys": {"half_spread_bps": 1e4 * float(acc[2] / tw), "impact_bps": 1e4 * float(acc[3] / tw),
                                      "share_of_traded_weight_at_11bps_floor": float(acc[4] / tw)}}


def breakeven_long(Lend: np.ndarray, buy: np.ndarray, sell: np.ndarray, Rb: np.ndarray) -> float | None:
    """Flat per-side cost c at which the mean tranche net excess vs the benchmark is zero:
    mean(Lend (1 - c b)(1 - c s) - 1 - Rb) = 0, smallest positive root; None when the gross excess is <= 0."""
    G = float(np.mean(Lend - 1.0 - Rb))
    if G <= 0:
        return None
    B = float(np.mean(Lend * (buy + sell)))
    A = float(np.mean(Lend * buy * sell))
    if A < 1e-15:
        return G / B
    disc = B * B - 4 * A * G
    return float((B - math.sqrt(disc)) / (2 * A)) if disc >= 0 else None


def breakeven_ls(Rg: np.ndarray, tl: dict, ts: dict) -> float | None:
    G = float(np.mean(Rg))
    if G <= 0:
        return None
    return G / float(np.mean(tl["buy"] + tl["sell"] + ts["buy"] + ts["sell"]))


# --------------------------------------------------------------------------- engine with caller-built baskets
class BookEngine(sb.Engine):
    """sb.Engine + ``run_members``: identical cost netting, statistics and bootstrap draws as ``Engine.run``, with
    the membership supplied by the caller and the name-level cost model as one extra variant."""

    def __init__(self, blocks, sessions, n_tick, H, comp: dict):
        super().__init__(blocks, sessions, n_tick, H)
        self.comp = comp

    def run_members(self, mem: list, basket: str, costs=sb.COSTS_BPS, with_capacity=True) -> dict:
        H, blocks, cal = self.H, self.blocks, self.cal
        is_ls = basket.endswith("ls_decile")
        Lp, Wl, size_l = sb.leg(blocks, [m[0] for m in mem], self.n_tick, H)
        tl = sb.trade_fracs(Wl, H)
        nl = name_cost_fracs(Wl, blocks, size_l, self.comp, H)
        out = {"basket_size_mean": float(size_l.mean()),
               "turnover_per_rebalance": float(np.nanmean(tl["buy_raw"])),
               "daily_churn": float(np.nanmean(tl["churn"])), "_tranche": {},
               "name_level_trade_weighted_cost_bps_per_side": nl["trade_weighted_cost_bps_per_side"],
               "name_level_cost_decomposition": nl["decomposition_of_buys"]}
        if is_ls:
            Sp, Ws, size_s = sb.leg(blocks, [m[1] for m in mem], self.n_tick, H)
            ts = sb.trade_fracs(Ws, H)
            ns = name_cost_fracs(Ws, blocks, size_s, self.comp, H)
            out["turnover_per_rebalance_short"] = float(np.nanmean(ts["buy_raw"]))
            out["capacity"] = sb.capacity(Wl, blocks, H) if with_capacity else None
            out["capacity_short_leg"] = sb.capacity(Ws, blocks, H) if with_capacity else None
        else:
            out["capacity"] = sb.capacity(Wl, blocks, H) if with_capacity else None
        bname = self.bench_for(basket)
        bench = self.bench[bname]
        out["benchmark"] = bname
        res = {}
        variants = [("gross", 0.0, False)] + [(f"{c}bps", c / 1e4, False) for c in costs] + \
                   [(f"{sb.HEADLINE_COST}bps_no_netting", sb.HEADLINE_COST / 1e4, True), (NAME_KEY, 1.0, False)]
        Rgross_l = Lp[:, -1] - 1.0
        for key, c, nonet in variants:
            if is_ls:
                if key == NAME_KEY:
                    tl_c, ts_c = {"buy": nl["buy"], "sell": nl["sell"]}, {"buy": ns["buy"], "sell": ns["sell"]}
                else:
                    tl_c = {"buy": np.ones_like(tl["buy"]), "sell": np.ones_like(tl["sell"])} if nonet else tl
                    ts_c = {"buy": np.ones_like(ts["buy"]), "sell": np.ones_like(ts["sell"])} if nonet else ts
                r, R = sb.ls_net(Lp, Sp, tl_c, ts_c, c)
                Rg = Rgross_l - (Sp[:, -1] - 1.0)
            else:
                if key == NAME_KEY:
                    buy, sell = nl["buy"], nl["sell"]
                else:
                    buy = np.ones_like(tl["buy"]) if nonet else tl["buy"]
                    sell = np.ones_like(tl["sell"]) if nonet else tl["sell"]
                r, R = sb.long_net(Lp, buy, sell, c)
                Rg = Rgross_l
            D = cal.to_days(r)
            res[key] = {}
            for seg in sb.SEGMENTS:
                m = cal.masks[seg]
                x = cal.seg_series(D, seg)
                codes, draws, ex = cal.month_codes[seg], cal.draws[seg], cal.expo[seg]
                xb = cal.seg_series(bench["D"], seg)
                if is_ls:
                    ent = {"tranche": sb.tranche_stats(R[m], Rg[m], H=H),
                           "daily": sb.series_stats(x, ex, codes, draws, rf=0.0),
                           "beta_alpha_vs_benchmark": sb.beta_alpha(x, xb, ex)}
                else:
                    ent = {"tranche": sb.tranche_stats(R[m], Rg[m], self.med[m], bench["R"][m], H=H),
                           "daily": sb.series_stats(x, ex, codes, draws, rf=sb.RF_ANNUAL),
                           "daily_active": sb.series_stats(x - xb, ex, codes, draws, rf=0.0),
                           "beta_alpha_vs_benchmark": sb.beta_alpha(x, xb, ex)}
                res[key][seg] = ent
            out["_tranche"][key] = {"R": R, "Rg": Rg}
            if key == f"{sb.HEADLINE_COST}bps":
                xc = cal.seg_series(D, "combined")
                out["_skill_daily"] = xc if is_ls else xc - cal.seg_series(bench["D"], "combined")
        out["results"] = res
        if is_ls:
            out["breakeven_cost_per_side"] = breakeven_ls(Rgross_l - (Sp[:, -1] - 1.0), tl, ts)
        else:
            out["breakeven_cost_per_side"] = breakeven_long(Lp[:, -1], tl["buy"], tl["sell"], bench["R"])
        out["_bench_R"] = None if is_ls else bench["R"]
        return out
