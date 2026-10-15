#!/usr/bin/env python3
"""RL agent: cross-sectional contextual bandit for daily top-K stock selection.

Honest framing: 1-step portfolio selection is a contextual bandit, not a
multi-step MDP -- each trading date is an independent episode whose context is
the cross-section of per-stock feature vectors, the action is a K=20 subset,
and the reward is the portfolio's 20-session excess return net of a turnover
cost. The turnover penalty (0.1% on the fraction of names replaced vs the
previous episode's selection) is the one term that makes this objective
genuinely different from per-stock supervised classification.

Policy: small MLP (13 -> 32 -> 1) producing a per-stock score.
Sampling: Plackett-Luce without replacement via Gumbel top-K, with the exact
sequential log-probability (vectorised through a reverse cumulative
logsumexp), trained with REINFORCE.
Baseline/advantage: the per-date universe mean of y_excess_20d is the exact
closed-form expectation of the gross reward of a uniformly-random K-portfolio
(linearity of expectation; sampling without replacement leaves the mean
unchanged), so it is an unbiased, date-conditional control variate that strips
the market/regime component the policy cannot influence. A slow EMA of the
residual absorbs the remaining mean (mostly the expected cost term), and a
running-std normalisation rescales the O(1e-2) rewards so Adam at lr 1e-3
takes meaningful steps; advantages are clipped to +/-5.

Evaluation re-uses the shared harness row sets (iter_folds, preprocess="raw"
just to obtain fold train_df/test_df; own harness Preprocessor("scaled") fit
on fold train rows only) and reports through compute_metrics + save_results +
save_preds with the standard schema, plus an extra "portfolio" key with the
simulator comparison vs random-20 and top-20 cs_rank_mom_20.

Run: cd /home/user/SuryaDhana_AI && python3 -m ml.models.rl
"""
from __future__ import annotations

import os

os.environ["OMP_NUM_THREADS"] = "2"  # must precede numpy/torch imports

import copy
import json
import sys
import time

import numpy as np
import pandas as pd
import torch

torch.set_num_threads(2)

from ml.evaluation import (SEED, Preprocessor, compute_metrics, iter_folds,
                           load_dataset, save_preds, save_results)

MODEL_NAME = "rl_reinforce"
TASK = "beat_mkt_20d"

FS_TOP10 = [
    "atr_pct", "deliv_pct_sma_20", "dist_52w_high", "ret_126d", "mom_12_1",
    "cs_rank_mom_20", "cs_rank_ret_126", "cs_rank_vol_20", "deliv_pct",
    "ret_63d",
]
EXTRA = ["rsi_14", "dist_sma_20", "cs_rank_turnover"]
FEATURES = FS_TOP10 + EXTRA  # 13 channels

K = 20
COST = 0.001                      # 0.1% charged on turned-over fraction
ANNUALIZER = float(np.sqrt(252.0 / 20.0))  # naive: one 20d-horizon reward per day

HP = {
    "arch": "MLP 13->32->1 (ReLU), final layer init ~N(0, 1e-2) for near-uniform initial softmax",
    "optimizer": "Adam", "lr": 1e-3,
    "max_epochs": 45, "patience": 8, "batch_episodes": 8,
    "inner_val": "time-ordered last 15% of train dates, early stop on mean net val reward (deterministic top-K)",
    "inner_val_frac": 0.15,
    "K": K, "cost_per_unit_turnover": COST,
    "sampler": "Plackett-Luce without replacement via Gumbel top-K; exact sequential log-prob",
    "baseline": ("per-date universe mean y_excess_20d (= exact E[gross reward of a random-K "
                 "portfolio], unbiased date-conditional control variate) + EMA(0.99) of the "
                 "residual; advantage / running std, clipped to +/-5"),
    "reward": "mean y_excess_20d of selected (clean rows only) - 0.001 * fraction of names replaced vs previous episode",
    "train_episode_order": "random per epoch (numpy rng), turnover tracked vs previously visited episode, reset each epoch",
    "eval": "deterministic top-K, chronological dates, turnover vs previous date, first date charged 0",
    "seed": SEED, "torch_threads": 2, "omp_threads": 2,
    "preprocessing": "harness Preprocessor('scaled') fit on fold train rows only (13 features)",
    "universe": "harness task frame rows (label present & y_clean_20d), identical to all other model families",
    "wall_clock_guard_s_per_fold": 240,
}


# --------------------------------------------------------------------------
# policy + sampling
# --------------------------------------------------------------------------
class PolicyNet(torch.nn.Module):
    def __init__(self, d_in: int, hidden: int = 32):
        super().__init__()
        self.net = torch.nn.Sequential(
            torch.nn.Linear(d_in, hidden),
            torch.nn.ReLU(),
            torch.nn.Linear(hidden, 1),
        )
        torch.nn.init.normal_(self.net[2].weight, std=1e-2)
        torch.nn.init.zeros_(self.net[2].bias)

    def forward(self, x):
        return self.net(x).squeeze(-1)


def sample_portfolio(scores: torch.Tensor, k: int, gen: torch.Generator):
    """Sample k items without replacement from softmax(scores) (Plackett-Luce)
    via Gumbel top-k; return (local indices, differentiable log-prob)."""
    u = torch.rand(scores.shape, generator=gen)
    gumbel = -torch.log(-torch.log(u + 1e-12) + 1e-12)
    order = torch.argsort(scores.detach() + gumbel, descending=True)
    s_sorted = scores[order]                              # differentiable gather
    rev_lse = torch.flip(torch.logcumsumexp(torch.flip(s_sorted, dims=[0]), dim=0), dims=[0])
    logp = (s_sorted[:k] - rev_lse[:k]).sum()             # exact PL sequential log-prob
    return order[:k], logp


# --------------------------------------------------------------------------
# simulator (shared by inner validation, test policy, random, momentum)
# --------------------------------------------------------------------------
def simulate(date_groups, select_fn, exc, tickers):
    """date_groups: chronological list of (date, positional idx array).
    select_fn(date, idx) -> selected positional rows (<= K).
    Returns dict of per-date arrays: net, gross, turnover (turnover excludes
    the first date, which is charged zero cost)."""
    prev = None
    net, gross, turnover = [], [], []
    for d, idx in date_groups:
        sel = select_fn(d, idx)
        if len(sel) == 0:
            continue
        vals = exc[sel]
        vals = vals[~np.isnan(vals)]
        if len(vals) == 0:
            continue
        g = float(vals.mean())
        tick_set = set(tickers[sel])
        if prev is None:
            to = 0.0
        else:
            to = 1.0 - len(tick_set & prev) / len(tick_set)
            turnover.append(to)
        net.append(g - COST * to)
        gross.append(g)
        prev = tick_set
    return {"net": np.asarray(net), "gross": np.asarray(gross),
            "turnover": np.asarray(turnover)}


def sim_stats(sim: dict) -> dict:
    net, gross, to = sim["net"], sim["gross"], sim["turnover"]
    std = float(net.std(ddof=1)) if len(net) > 1 else float("nan")
    return {
        "mean_net_20d_excess": float(net.mean()),
        "std_net": std,
        "ann_sharpe_naive": float(net.mean() / std * ANNUALIZER) if std and std > 0 else None,
        "avg_daily_turnover_pct": float(to.mean() * 100.0) if len(to) else 0.0,
        "mean_gross_20d_excess": float(gross.mean()),
        "n_dates": int(len(net)),
    }


def avg_stats(stat_list: list[dict]) -> dict:
    out = {}
    for key in stat_list[0]:
        vals = [s[key] for s in stat_list if s[key] is not None]
        out[key] = float(np.mean(vals)) if vals else None
    out["n_dates"] = int(stat_list[0]["n_dates"])
    return out


def topk_select_fn(score_arr: np.ndarray):
    def fn(date, idx):
        k = min(K, len(idx))
        local = np.argsort(-score_arr[idx], kind="stable")[:k]
        return idx[local]
    return fn


# --------------------------------------------------------------------------
# training
# --------------------------------------------------------------------------
def train_policy(tr: pd.DataFrame, Xtr: np.ndarray, fold_i: int,
                 max_epochs: int, log) -> tuple[PolicyNet, dict]:
    torch.manual_seed(SEED + fold_i)
    rng = np.random.default_rng(SEED + fold_i)
    gen = torch.Generator().manual_seed(SEED * 1000 + fold_i)

    exc = tr["y_excess_20d"].to_numpy(np.float64)
    tickers = tr["ticker"].to_numpy()
    groups = tr.groupby("date").indices            # date -> positional idx
    dates = sorted(groups)
    n_val = max(1, int(round(HP["inner_val_frac"] * len(dates))))
    fit_dates, val_dates = dates[:-n_val], dates[-n_val:]
    date_mean = {d: float(np.nanmean(exc[groups[d]])) for d in dates}
    val_groups = [(d, np.asarray(groups[d])) for d in val_dates]

    X_t = torch.from_numpy(Xtr)
    model = PolicyNet(len(FEATURES))
    opt = torch.optim.Adam(model.parameters(), lr=HP["lr"])

    def val_reward() -> float:
        with torch.no_grad():
            scores = model(X_t).numpy()
        sim = simulate(val_groups, topk_select_fn(scores), exc, tickers)
        return float(sim["net"].mean())

    best_val = val_reward()                        # epoch 0 = untrained policy
    best_state = copy.deepcopy(model.state_dict())
    best_epoch, bad, epochs_run = 0, 0, 0
    ema_r, ema_var = 0.0, 1e-4
    t_start = time.time()

    for epoch in range(1, max_epochs + 1):
        epochs_run = epoch
        order = rng.permutation(len(fit_dates))
        prev_sel = None
        opt.zero_grad()
        in_batch = 0
        for oi in order:
            d = fit_dates[oi]
            idx = np.asarray(groups[d])
            scores = model(X_t[idx])
            local, logp = sample_portfolio(scores, min(K, len(idx)), gen)
            sel = idx[local.numpy()]
            vals = exc[sel]
            vals = vals[~np.isnan(vals)]
            if len(vals) == 0:
                continue
            gross = float(vals.mean())
            tick_set = set(tickers[sel])
            to = 0.0 if prev_sel is None else 1.0 - len(tick_set & prev_sel) / len(tick_set)
            reward = gross - COST * to
            resid = reward - date_mean[d]
            adv_raw = resid - ema_r
            adv = float(np.clip(adv_raw / (np.sqrt(ema_var) + 1e-8), -5.0, 5.0))
            ema_r = 0.99 * ema_r + 0.01 * resid
            ema_var = 0.99 * ema_var + 0.01 * adv_raw ** 2
            ((-adv) * logp / HP["batch_episodes"]).backward()
            in_batch += 1
            if in_batch == HP["batch_episodes"]:
                opt.step()
                opt.zero_grad()
                in_batch = 0
            prev_sel = tick_set
        if in_batch:
            opt.step()
            opt.zero_grad()
        vr = val_reward()
        if vr > best_val:
            best_val, best_epoch, bad = vr, epoch, 0
            best_state = copy.deepcopy(model.state_dict())
        else:
            bad += 1
        log(f"    epoch {epoch:2d}  val_net_reward={vr:+.5f}  best={best_val:+.5f} (ep {best_epoch})")
        if bad >= HP["patience"]:
            log(f"    early stop at epoch {epoch} (patience {HP['patience']})")
            break
        if time.time() - t_start > HP["wall_clock_guard_s_per_fold"]:
            log("    wall-clock guard hit, stopping fold training")
            break

    model.load_state_dict(best_state)
    info = {
        "n_train_dates": len(fit_dates), "n_val_dates": len(val_dates),
        "episodes_per_epoch": len(fit_dates), "epochs_run": epochs_run,
        "best_epoch": best_epoch, "best_val_net_reward": best_val,
        "total_episodes": epochs_run * len(fit_dates),
    }
    return model, info


# --------------------------------------------------------------------------
# per-fold portfolio comparison
# --------------------------------------------------------------------------
def portfolio_lens(te: pd.DataFrame, policy_scores: np.ndarray, fold_i: int):
    exc = te["y_excess_20d"].to_numpy(np.float64)
    tickers = te["ticker"].to_numpy()
    groups = te.groupby("date").indices
    date_groups = [(d, np.asarray(groups[d])) for d in sorted(groups)]

    pol_sim = simulate(date_groups, topk_select_fn(policy_scores), exc, tickers)

    mom = te["cs_rank_mom_20"].to_numpy(np.float64)
    mom = np.where(np.isnan(mom), -1e18, mom)
    mom_sim = simulate(date_groups, topk_select_fn(mom), exc, tickers)

    rng = np.random.default_rng(SEED + 7919 * fold_i)
    rand_sims = []
    for _ in range(20):
        def rand_fn(date, idx, _rng=rng):
            return _rng.choice(idx, size=min(K, len(idx)), replace=False)
        rand_sims.append(simulate(date_groups, rand_fn, exc, tickers))

    cell = {
        "policy": sim_stats(pol_sim),
        "random20": {**avg_stats([sim_stats(s) for s in rand_sims]), "n_draws": 20},
        "momentum20_cs_rank_mom_20": sim_stats(mom_sim),
    }
    raw = {"policy": pol_sim, "momentum": mom_sim, "random_draws": rand_sims}
    return cell, raw


def aggregate_raw(raws: list[dict]) -> dict:
    def cat(sims, key):
        return {"net": np.concatenate([s[key]["net"] for s in sims]),
                "gross": np.concatenate([s[key]["gross"] for s in sims]),
                "turnover": np.concatenate([s[key]["turnover"] for s in sims])}
    pol = sim_stats(cat(raws, "policy"))
    mom = sim_stats(cat(raws, "momentum"))
    rand_stats = []
    for d in range(20):
        draw = {"net": np.concatenate([r["random_draws"][d]["net"] for r in raws]),
                "gross": np.concatenate([r["random_draws"][d]["gross"] for r in raws]),
                "turnover": np.concatenate([r["random_draws"][d]["turnover"] for r in raws])}
        rand_stats.append(sim_stats(draw))
    return {"policy": pol, "random20": {**avg_stats(rand_stats), "n_draws": 20},
            "momentum20_cs_rank_mom_20": mom}


# --------------------------------------------------------------------------
# notes / honest assessment
# --------------------------------------------------------------------------
def fmt_cell(c: dict) -> str:
    sh = c["ann_sharpe_naive"]
    return (f"net {c['mean_net_20d_excess'] * 100:+.2f}%/20d, naive Sharpe "
            f"{sh:+.2f}" if sh is not None else
            f"net {c['mean_net_20d_excess'] * 100:+.2f}%/20d, Sharpe n/a") + \
           f", turnover {c['avg_daily_turnover_pct']:.0f}%/d"


def build_notes(cv_auc_mean, cv_auc_std, holdout_auc, fold_aucs, cv_port, ho_port, training) -> str:
    pol_cv, rnd_cv, mom_cv = cv_port["policy"], cv_port["random20"], cv_port["momentum20_cs_rank_mom_20"]
    pol_ho, rnd_ho, mom_ho = ho_port["policy"], ho_port["random20"], ho_port["momentum20_cs_rank_mom_20"]
    beats_rand_cv = pol_cv["mean_net_20d_excess"] > rnd_cv["mean_net_20d_excess"]
    beats_rand_ho = pol_ho["mean_net_20d_excess"] > rnd_ho["mean_net_20d_excess"]
    beats_mom_cv = pol_cv["mean_net_20d_excess"] > mom_cv["mean_net_20d_excess"]
    beats_mom_ho = pol_ho["mean_net_20d_excess"] > mom_ho["mean_net_20d_excess"]
    epochs = [t["best_epoch"] for t in training.values()]

    table = (f"PORTFOLIO (CV-agg | holdout): policy [{fmt_cell(pol_cv)} | {fmt_cell(pol_ho)}]; "
             f"random20 [{fmt_cell(rnd_cv)} | {fmt_cell(rnd_ho)}]; "
             f"mom20 [{fmt_cell(mom_cv)} | {fmt_cell(mom_ho)}]. "
             "Rewards are overlapping 20-session excess returns vs the universe MEDIAN sampled daily "
             "(not compounded); the cross-section is right-skewed, so even random-20 earns a positive "
             "mean -- the bar is beating random, not zero. ")

    def vb(cv, ho):
        if cv and ho:
            return "yes on both CV and holdout"
        if ho:
            return "no in CV, yes on holdout"
        if cv:
            return "yes in CV, no on holdout"
        return "no on both"

    assessment = (
        f"HONEST ASSESSMENT: (a) does the learned policy beat random-20 out of sample? {vb(beats_rand_cv, beats_rand_ho)} "
        f"on mean net reward (CV-agg {pol_cv['mean_net_20d_excess'] * 100:+.2f}% vs random {rnd_cv['mean_net_20d_excess'] * 100:+.2f}%; "
        f"holdout {pol_ho['mean_net_20d_excess'] * 100:+.2f}% vs {rnd_ho['mean_net_20d_excess'] * 100:+.2f}%); "
        f"(b) vs the cs_rank_mom_20 heuristic: {vb(beats_mom_cv, beats_mom_ho)} "
        f"(heuristic holdout {mom_ho['mean_net_20d_excess'] * 100:+.2f}%). "
        f"On the classifier lens the policy scores cv_auc {cv_auc_mean:.4f} +/- {cv_auc_std:.4f} "
        f"(fold range {min(fold_aucs):.3f}-{max(fold_aucs):.3f}) and holdout {holdout_auc:.4f}, "
        f"{'roughly matching' if cv_auc_mean >= 0.52 else 'trailing'} the supervised family "
        "(LGBM top-10: cv 0.5307, holdout 0.5219; logistic cv ~0.513) -- REINFORCE is at best recovering the same weak, "
        "regime-unstable momentum/vol tilt the supervised rankers already capture, through a far noisier gradient estimator. "
        "Six months of EOD data (~190-280 episodes per fold, one noisy scalar reward each) is NOT enough for RL here: "
        f"early stopping picked epochs {min(epochs)}-{max(epochs)} across folds, and inner-validation reward curves were "
        "dominated by regime noise, so the variance of the policy-gradient estimate swamps the ~0.52-AUC signal. "
        "The one thing the bandit objective adds -- turnover-aware selection -- does not need RL: a supervised ranker plus a "
        "portfolio constructor with a turnover penalty (or simple score-hysteresis) achieves it deterministically. "
        "RL would start earning its complexity only with multi-step position management (entries/exits, holding-period and "
        "path-dependent costs), a realistic cost/impact model that depends on the agent's own actions, regime/state features, "
        "and years of cross-sectional history (thousands of episodes); none of those hold in this 6-month EOD pilot. "
        "Verdict: do not scale this RL formulation; if portfolio-level objectives matter, bolt a constructor onto the "
        "supervised rankers and judge those on regime stability, per the linear report."
    )
    return table + assessment


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main(smoke: bool = False):
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    df, features, splits = load_dataset()
    missing = [f for f in FEATURES if f not in features]
    assert not missing, f"missing features: {missing}"

    max_epochs = 3 if smoke else HP["max_epochs"]
    fold_rows, pred_frames = [], []
    holdout_row = None
    port_folds, cv_raws, training = {}, [], {}
    ho_port = None
    t0 = time.time()

    def log(msg):
        print(msg, flush=True)

    for fold_i, fold in enumerate(iter_folds(df, features, splits, TASK, preprocess="raw")):
        log(f"[fold {fold.name}] train rows={len(fold.train_df)} test rows={len(fold.test_df)}")
        tr = fold.train_df.reset_index(drop=True)
        te = fold.test_df.reset_index(drop=True)
        prep = Preprocessor("scaled").fit(tr[FEATURES])
        Xtr = prep.transform(tr[FEATURES])
        Xte = prep.transform(te[FEATURES])

        model, info = train_policy(tr, Xtr, fold_i, max_epochs, log)
        training[fold.name] = info

        with torch.no_grad():
            te_logits = model(torch.from_numpy(Xte)).numpy().astype(np.float64)
        sig = 1.0 / (1.0 + np.exp(-te_logits))

        m = compute_metrics(fold.y_test, sig, fold.fwd_test)
        m["fold"] = fold.name
        m["n_train"] = int(len(fold.train_df))
        cell, raw = portfolio_lens(te, te_logits, fold_i)
        port_folds[fold.name] = cell
        if fold.is_holdout:
            holdout_row = m
            ho_port = cell
        else:
            fold_rows.append(m)
            cv_raws.append(raw)

        pf = fold.meta_test.copy()
        pf["score"], pf["y"], pf["fwd"] = sig, fold.y_test, fold.fwd_test
        pf["fold"] = fold.name
        pred_frames.append(pf)
        log(f"  auc={m['auc']:.4f}  policy {fmt_cell(cell['policy'])} | "
            f"random {fmt_cell(cell['random20'])} | mom {fmt_cell(cell['momentum20_cs_rank_mom_20'])}")
        if smoke and fold_i >= 0:
            break

    train_seconds = round(time.time() - t0, 1)
    if smoke:
        log(f"[smoke ok] {train_seconds}s")
        return

    cv_port = aggregate_raw(cv_raws)
    aucs = [r["auc"] for r in fold_rows]
    notes = build_notes(float(np.mean(aucs)), float(np.std(aucs)), holdout_row["auc"],
                        aucs, cv_port, ho_port, training)

    payload = {
        "model": MODEL_NAME, "family": "rl", "agent": "quant-rl", "task": TASK,
        "params": HP, "preprocess": "scaled",
        "n_features": len(FEATURES), "feature_subset": FEATURES,
        "folds": fold_rows,
        "cv_auc_mean": float(np.mean(aucs)),
        "cv_auc_std": float(np.std(aucs)),
        "holdout": holdout_row,
        "train_seconds": train_seconds,
        "notes": notes,
        "portfolio": {
            "definition": ("per-date reward = mean y_excess_20d of the deterministic top-20 minus "
                           "0.001 * fraction of names replaced vs the previous test date (first date "
                           "charged 0; avg_daily_turnover_pct excludes the first date). Rewards are "
                           "overlapping 20-session horizons sampled daily, not compounded. "
                           "ann_sharpe_naive = mean/std * sqrt(252/20). random20 = average stats of "
                           "20 draws, seed-controlled. Universe = harness task-frame test rows "
                           "(clean-labeled), identical for all three policies."),
            "cost_bps_per_unit_turnover": 10,
            "folds": port_folds,
            "cv_aggregate": cv_port,
            "holdout": ho_port,
        },
        "training": training,
    }
    path = save_results(payload)
    ppath = save_preds(MODEL_NAME, TASK, pred_frames)
    log(f"[{MODEL_NAME} | {TASK}] cv_auc={payload['cv_auc_mean']:.4f} (+/-{payload['cv_auc_std']:.4f}) "
        f"holdout_auc={holdout_row['auc']:.4f} ({train_seconds}s)")
    log(f"results -> {path}\npreds -> {ppath}")
    log(json.dumps({"cv_aggregate": cv_port, "holdout": ho_port}, indent=1))


if __name__ == "__main__":
    main(smoke="--smoke" in sys.argv)
