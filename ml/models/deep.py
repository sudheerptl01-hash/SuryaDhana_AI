#!/usr/bin/env python3
"""Deep-learning models for the SuryaDhana ML evaluation (agent: quant-dl).

Models
* mlp  -- tabular MLP on ALL features via run_standard_eval (preprocess
          "scaled"), both tasks. Lightly tuned: hidden {128-64, 256-128} x
          dropout {0.25, 0.4} screened ONLY on CV folds 2026-04/2026-05
          (primary task); the winner runs the full protocol once.
* gru  -- GRU(hidden=48) over per-ticker rolling 20-session windows of the
          FS-study selected 10 features + 4 temporal channels (ret_1d,
          gap_pct, vol_z_20, rsi_2). Cannot use run_standard_eval; folds come
          from ml.evaluation.iter_folds(preprocess="raw") and results go
          through compute_metrics + save_results + save_preds with the same
          payload schema run_standard_eval writes. Primary task always;
          up_5d only if runtime budget remains.
* lstm -- optional LSTM twin of the gru (primary task) if budget remains.

Protocol (fixed, see ml/README.md + ml/evaluation.py)
* seed 108 everywhere (torch / numpy / random); 2 CPU threads (shared box).
* The holdout fold is produced by the harness fold iterator and is NEVER
  used for tuning or early stopping.
* Inner validation for early stopping (never test rows):
  - mlp: the LAST 15% of the train-matrix ROWS passed to fit(). Assumption
    (stated per protocol): the harness preserves the dataset's (date,
    ticker) sort, so the tail of X_train ~= the latest train dates. The
    dataset's date order is asserted at runtime in main().
  - gru/lstm: the LAST 15% of train DATES.

Run: cd <repo root> && python3 -m ml.models.deep
"""
from __future__ import annotations

import os

os.environ["OMP_NUM_THREADS"] = "2"  # before numpy/torch imports

import argparse
import json
import random
import time

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

torch.set_num_threads(2)
try:
    torch.set_num_interop_threads(1)
except RuntimeError:
    pass  # already initialized

from sklearn.metrics import roc_auc_score

from ml.evaluation import (RESULTS_DIR, SEED, TASKS, compute_metrics,
                           iter_folds, load_dataset, run_standard_eval,
                           save_preds, save_results)

FAMILY = "deep"
AGENT = "quant-dl"
PRIMARY = "beat_mkt_20d"
SECONDARY = "up_5d"
SCREEN_FOLD_NAMES = ("2026-04", "2026-05")
INNER_VAL_FRAC = 0.15

SEQ_LEN = 20
SEQ_EXTRA = ["ret_1d", "gap_pct", "vol_z_20", "rsi_2"]
SEQ_TRAIN_CAP = 150_000      # halved automatically if epochs project > 120 s
SEQ_BATCH = 1024
SEQ_MAX_EPOCHS = 15
SEQ_HIDDEN = 48
SEQ_DROPOUT = 0.3

MLP_BATCH = 4096
MLP_MAX_EPOCHS = 30
PATIENCE = 4

BUDGET_SECONDS = 30 * 60     # script-internal gate for the optional runs

MLP_INNER_NOTE = (
    "Early stopping on inner-validation AUC where inner-val = the LAST 15% "
    "of train rows; the harness preserves the dataset's (date,ticker) sort, "
    "so the tail of X_train ~= the latest train dates (never random rows, "
    "never test rows; date order asserted at runtime)."
)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def seed_everything(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


# ---------------------------------------------------------------------------
# 1) Tabular MLP (sklearn-style: fit / predict_proba -> run_standard_eval)
# ---------------------------------------------------------------------------
class TorchMLP:
    """MLP with AdamW + early stopping on the last-15%-of-rows inner val."""

    def __init__(self, hidden=(128, 64), dropout=0.25, lr=1e-3,
                 weight_decay=1e-4, batch_size=MLP_BATCH,
                 max_epochs=MLP_MAX_EPOCHS, patience=PATIENCE,
                 val_frac=INNER_VAL_FRAC, seed=SEED):
        self.hidden = tuple(hidden)
        self.dropout = dropout
        self.lr = lr
        self.weight_decay = weight_decay
        self.batch_size = batch_size
        self.max_epochs = max_epochs
        self.patience = patience
        self.val_frac = val_frac
        self.seed = seed

    def _build(self, n_in: int) -> nn.Module:
        layers, prev = [], n_in
        for h in self.hidden:
            layers += [nn.Linear(prev, h), nn.ReLU(), nn.Dropout(self.dropout)]
            prev = h
        layers.append(nn.Linear(prev, 1))
        return nn.Sequential(*layers)

    def fit(self, X, y):
        seed_everything(self.seed)
        X = torch.as_tensor(np.ascontiguousarray(X, dtype=np.float32))
        y = torch.as_tensor(np.ascontiguousarray(y, dtype=np.float32))
        n = len(y)
        cut = max(1, int(round(n * (1.0 - self.val_frac))))
        X_tr, y_tr, X_va, y_va = X[:cut], y[:cut], X[cut:], y[cut:]
        self.net_ = self._build(X.shape[1])
        opt = torch.optim.AdamW(self.net_.parameters(), lr=self.lr,
                                weight_decay=self.weight_decay)
        lossf = nn.BCEWithLogitsLoss()
        g = torch.Generator().manual_seed(self.seed)
        best_auc, best_state, bad = -1.0, None, 0
        self.epochs_run_, self.best_epoch_ = 0, 0
        y_va_np = y_va.numpy()
        for epoch in range(1, self.max_epochs + 1):
            self.net_.train()
            perm = torch.randperm(len(y_tr), generator=g)
            for i in range(0, len(y_tr), self.batch_size):
                idx = perm[i:i + self.batch_size]
                opt.zero_grad()
                loss = lossf(self.net_(X_tr[idx]).squeeze(-1), y_tr[idx])
                loss.backward()
                opt.step()
            va = self._scores(X_va)
            try:
                auc = roc_auc_score(y_va_np, va)
            except ValueError:   # single-class val (won't happen in practice)
                auc = 0.5
            self.epochs_run_ = epoch
            if auc > best_auc + 1e-5:
                best_auc, bad, self.best_epoch_ = auc, 0, epoch
                best_state = {k: v.detach().clone()
                              for k, v in self.net_.state_dict().items()}
            else:
                bad += 1
                if bad >= self.patience:
                    break
        if best_state is not None:
            self.net_.load_state_dict(best_state)
        self.best_val_auc_ = float(best_auc)
        return self

    @torch.no_grad()
    def _scores(self, X: torch.Tensor) -> np.ndarray:
        self.net_.eval()
        outs = [torch.sigmoid(self.net_(X[i:i + 8192]).squeeze(-1))
                for i in range(0, len(X), 8192)]
        return (torch.cat(outs).numpy() if outs
                else np.zeros(0, dtype=np.float32))

    def predict_proba(self, X) -> np.ndarray:
        X = torch.as_tensor(np.ascontiguousarray(X, dtype=np.float32))
        p = self._scores(X)
        return np.column_stack([1.0 - p, p])


def get_screen_folds(df, features, splits, task=PRIMARY, preprocess="scaled"):
    folds = []
    for f in iter_folds(df, features, splits, task, preprocess=preprocess):
        if f.name in SCREEN_FOLD_NAMES:
            folds.append(f)
        if len(folds) == len(SCREEN_FOLD_NAMES):
            break
    assert [f.name for f in folds] == list(SCREEN_FOLD_NAMES)
    return folds


def screen_mlp(df, features, splits):
    """4-config screen (hidden x dropout) on the first two CV folds ONLY."""
    grid = [{"hidden": h, "dropout": p}
            for h in ((128, 64), (256, 128)) for p in (0.25, 0.4)]
    folds = get_screen_folds(df, features, splits)
    aucs = {i: [] for i in range(len(grid))}
    for fold in folds:
        for i, cfg in enumerate(grid):
            t0 = time.time()
            est = TorchMLP(**cfg).fit(fold.X_train, fold.y_train)
            score = est.predict_proba(fold.X_test)[:, 1]
            auc = roc_auc_score(fold.y_test, score)
            aucs[i].append(auc)
            log(f"[screen mlp] fold={fold.name} cfg={cfg} auc={auc:.4f} "
                f"(ep={est.epochs_run_} best_ep={est.best_epoch_} "
                f"val_auc={est.best_val_auc_:.4f} {time.time() - t0:.0f}s)")
    best_i = max(range(len(grid)), key=lambda i: float(np.mean(aucs[i])))
    best = grid[best_i]
    log(f"[screen mlp] CHOSEN {best} "
        f"mean_auc={np.mean(aucs[best_i]):.4f} folds={aucs[best_i]}")
    return best, float(np.mean(aucs[best_i]))


def run_mlp(df, features, splits):
    best, screen_auc = screen_mlp(df, features, splits)
    made: list[TorchMLP] = []

    def factory(task):
        est = TorchMLP(**best)
        made.append(est)
        return est

    params = {
        "hidden": list(best["hidden"]), "dropout": best["dropout"],
        "optimizer": "AdamW", "lr": 1e-3, "weight_decay": 1e-4,
        "batch_size": MLP_BATCH, "max_epochs": MLP_MAX_EPOCHS,
        "early_stopping_patience": PATIENCE,
        "inner_val": "last 15% of train rows (time-ordered tail)",
        "screen_cv_auc_2folds": screen_auc,
        "seed": SEED, "torch_threads": 2,
    }
    notes = ("Tabular MLP on all features. Tuned ONLY on CV folds "
             "2026-04 + 2026-05 (mean primary-task AUC) over hidden "
             "{128-64, 256-128} x dropout {0.25, 0.4}; holdout untouched "
             f"for tuning. {MLP_INNER_NOTE} Seed 108, 2 torch threads.")
    summary = run_standard_eval(
        "mlp", FAMILY, AGENT, factory, preprocess="scaled", params=params,
        notes=notes, df=df, features=features, splits=splits)

    # annotate epochs-reached per fold into the saved JSONs (params only;
    # schema untouched). Folds are created in order: 4 CV folds then holdout,
    # first for beat_mkt_20d then up_5d.
    fold_names = [s["name"] for s in splits["folds"]] + ["holdout"]
    for ti, task in enumerate(("beat_mkt_20d", "up_5d")):
        ests = made[ti * len(fold_names):(ti + 1) * len(fold_names)]
        detail = {fn: {"epochs_run": e.epochs_run_, "best_epoch": e.best_epoch_,
                       "best_inner_val_auc": round(e.best_val_auc_, 4)}
                  for fn, e in zip(fold_names, ests)}
        path = RESULTS_DIR / f"mlp__{task}.json"
        payload = json.loads(path.read_text())
        payload["params"]["fold_epochs"] = detail
        path.write_text(json.dumps(payload, indent=1, default=str))
    return summary, made


# ---------------------------------------------------------------------------
# 2) Sequence models (GRU / LSTM) over per-ticker 20-session windows
# ---------------------------------------------------------------------------
class SeqNet(nn.Module):
    def __init__(self, n_in: int, hidden: int = SEQ_HIDDEN, cell: str = "gru",
                 dropout: float = SEQ_DROPOUT):
        super().__init__()
        rnn_cls = nn.GRU if cell == "gru" else nn.LSTM
        self.rnn = rnn_cls(n_in, hidden, num_layers=1, batch_first=True)
        self.drop = nn.Dropout(dropout)
        self.fc = nn.Linear(hidden, 1)

    def forward(self, x):                       # x: (B, 20, C)
        out, _ = self.rnn(x)
        return self.fc(self.drop(out[:, -1, :])).squeeze(-1)


def seq_channels(features: list[str]) -> list[str]:
    fs = json.loads((RESULTS_DIR / "feature_selection.json").read_text())
    sel = list(fs["selected"]["features"])
    assert len(sel) == 10
    chans = sel + [c for c in SEQ_EXTRA if c not in sel]
    assert all(c in features for c in chans), "channel missing from manifest"
    return chans


def build_seq_context(df: pd.DataFrame, channels: list[str]):
    """(ticker,date)-sorted channel matrix + helpers for window gathering."""
    s = df.sort_values(["ticker", "date"], kind="mergesort")
    orig = s.index.to_numpy()                    # original RangeIndex labels
    pos_of_orig = np.empty(len(df), dtype=np.int64)
    pos_of_orig[orig] = np.arange(len(df))
    M = s[channels].to_numpy(dtype=np.float32)   # raw values, NaN preserved
    wt = s.groupby("ticker").cumcount().to_numpy()  # within-ticker session idx
    dates_sorted = s["date"].to_numpy()
    return M, pos_of_orig, wt, dates_sorted


def standardize_fold(M, dates_sorted, cutoff) -> np.ndarray:
    """Median-impute + z-score per channel, fit on rows dated <= cutoff."""
    mask = dates_sorted <= np.datetime64(cutoff)
    sub = M[mask]
    med = np.nanmedian(sub, axis=0)
    med = np.where(np.isfinite(med), med, 0.0).astype(np.float32)
    subi = np.where(np.isnan(sub), med, sub)
    mean = subi.mean(axis=0)
    std = subi.std(axis=0)
    std = np.where((std == 0) | ~np.isfinite(std), 1.0, std)
    Mt = np.where(np.isnan(M), med, M)
    return ((Mt - mean) / std).astype(np.float32)


def cap_per_date(dates: np.ndarray, cap: int, seed: int = SEED) -> np.ndarray:
    """Random per-date subsample down to ~cap rows (dates array is sorted)."""
    n = len(dates)
    if n <= cap:
        return np.arange(n)
    frac = cap / n
    rng = np.random.default_rng(seed)
    _, starts = np.unique(dates, return_index=True)
    bounds = np.append(np.sort(starts), n)
    keep = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        k = max(1, int(round((b - a) * frac)))
        keep.append(a + rng.permutation(b - a)[:k])
    return np.sort(np.concatenate(keep))


def _windows(Mt_t: torch.Tensor, pos: torch.Tensor,
             offsets: torch.Tensor) -> torch.Tensor:
    return Mt_t[pos.unsqueeze(1) + offsets]      # (B, 20, C)


@torch.no_grad()
def _seq_scores(net, Mt_t, pos, offsets, batch=4096) -> np.ndarray:
    net.eval()
    outs = []
    for i in range(0, len(pos), batch):
        x = _windows(Mt_t, pos[i:i + batch], offsets)
        outs.append(torch.sigmoid(net(x)))
    return (torch.cat(outs).numpy() if outs else np.zeros(0, dtype=np.float32))


def fit_seq_fold(cell, n_chan, Mt, tr_pos, tr_dates, y_tr,
                 max_epochs=SEQ_MAX_EPOCHS, patience=PATIENCE):
    """Train one fold; inner-val = last 15% of train DATES. Returns net+info."""
    seed_everything(SEED)
    Mt_t = torch.from_numpy(Mt)
    offsets = torch.arange(-(SEQ_LEN - 1), 1)
    udates = np.unique(tr_dates)
    cut = min(max(1, int(round(len(udates) * (1 - INNER_VAL_FRAC)))),
              len(udates) - 1)
    val_start = udates[cut]
    va_mask = tr_dates >= val_start
    p_tr = torch.from_numpy(tr_pos[~va_mask])
    p_va = torch.from_numpy(tr_pos[va_mask])
    y_fit = torch.from_numpy(y_tr[~va_mask])
    y_va = y_tr[va_mask]
    net = SeqNet(n_chan, SEQ_HIDDEN, cell, SEQ_DROPOUT)
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-4)
    lossf = nn.BCEWithLogitsLoss()
    g = torch.Generator().manual_seed(SEED)
    best_auc, best_state, bad = -1.0, None, 0
    epochs_run, best_epoch, ep_times = 0, 0, []
    for epoch in range(1, max_epochs + 1):
        t0 = time.time()
        net.train()
        perm = torch.randperm(len(p_tr), generator=g)
        for i in range(0, len(p_tr), SEQ_BATCH):
            idx = perm[i:i + SEQ_BATCH]
            opt.zero_grad()
            out = net(_windows(Mt_t, p_tr[idx], offsets))
            loss = lossf(out, y_fit[idx])
            loss.backward()
            opt.step()
        va = _seq_scores(net, Mt_t, p_va, offsets)
        try:
            auc = roc_auc_score(y_va, va)
        except ValueError:
            auc = 0.5
        ep_times.append(time.time() - t0)
        epochs_run = epoch
        log(f"    epoch {epoch:2d} val_auc={auc:.4f} ({ep_times[-1]:.0f}s)")
        if auc > best_auc + 1e-5:
            best_auc, bad, best_epoch = auc, 0, epoch
            best_state = {k: v.detach().clone()
                          for k, v in net.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                break
    if best_state is not None:
        net.load_state_dict(best_state)
    info = {"epochs_run": epochs_run, "best_epoch": best_epoch,
            "best_inner_val_auc": round(float(best_auc), 4),
            "n_fit": int(len(p_tr)), "n_inner_val": int(len(p_va)),
            "inner_val_start": str(pd.Timestamp(val_start).date()),
            "epoch_seconds_mean": round(float(np.mean(ep_times)), 1)}
    return net, Mt_t, offsets, info


def bench_seq_epoch_seconds(n_chan: int, cap: int) -> float:
    """Project one training-epoch wall time for the capped train set."""
    seed_everything(SEED)
    net = SeqNet(n_chan, SEQ_HIDDEN, "gru", SEQ_DROPOUT)
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-4)
    lossf = nn.BCEWithLogitsLoss()
    x = torch.randn(SEQ_BATCH, SEQ_LEN, n_chan)
    y = (torch.rand(SEQ_BATCH) > 0.5).float()
    for _ in range(2):                                   # warmup
        opt.zero_grad(); lossf(net(x), y).backward(); opt.step()
    t0 = time.time()
    iters = 8
    for _ in range(iters):
        opt.zero_grad(); lossf(net(x), y).backward(); opt.step()
    per_batch = (time.time() - t0) / iters
    n_batches = int(np.ceil(cap * (1 - INNER_VAL_FRAC) / SEQ_BATCH))
    return per_batch * n_batches


def run_seq_model(model_name: str, cell: str, task: str, df, features, splits,
                  M, pos_of_orig, wt, dates_sorted, channels, cap: int):
    label, fwdcol, _ = TASKS[task]
    fold_rows, pred_frames, fold_detail = [], [], {}
    holdout = None
    t0 = time.time()
    for fold in iter_folds(df, features, splits, task, preprocess="raw",
                           feature_subset=channels):
        tr, te = fold.train_df, fold.test_df
        cutoff = tr["date"].max()
        Mt = standardize_fold(M, dates_sorted, cutoff)

        tr_pos_all = pos_of_orig[tr.index.to_numpy()]
        tr_keep = wt[tr_pos_all] >= SEQ_LEN - 1
        tr_pos = tr_pos_all[tr_keep]
        tr_dates = tr["date"].to_numpy()[tr_keep]
        y_tr = tr[label].to_numpy(dtype=np.float32)[tr_keep]
        n_precap = len(tr_pos)
        sub = cap_per_date(tr_dates, cap, seed=SEED)
        tr_pos, tr_dates, y_tr = tr_pos[sub], tr_dates[sub], y_tr[sub]

        te_pos_all = pos_of_orig[te.index.to_numpy()]
        te_keep = wt[te_pos_all] >= SEQ_LEN - 1
        te_pos = te_pos_all[te_keep]
        y_te = te[label].to_numpy(dtype=np.float32)[te_keep]
        fwd_te = te[fwdcol].to_numpy(dtype=np.float32)[te_keep]

        log(f"[{model_name}|{task}] fold={fold.name} train_seq={len(tr_pos)} "
            f"(pre-cap {n_precap}, dropped<{SEQ_LEN} {int((~tr_keep).sum())}) "
            f"test_seq={len(te_pos)} (dropped {int((~te_keep).sum())})")
        net, Mt_t, offsets, info = fit_seq_fold(
            cell, len(channels), Mt, tr_pos, tr_dates, y_tr)
        score = _seq_scores(net, Mt_t, torch.from_numpy(te_pos), offsets)

        m = compute_metrics(y_te, score, fwd_te)
        m["fold"] = fold.name
        m["n_train"] = int(len(tr_pos))
        info.update({"n_train_precap": int(n_precap),
                     "n_test_dropped_short_history": int((~te_keep).sum())})
        fold_detail[fold.name] = info
        if fold.is_holdout:
            holdout = m
        else:
            fold_rows.append(m)
        pf = te.loc[te_keep, ["date", "ticker"]].reset_index(drop=True)
        pf["score"], pf["y"], pf["fwd"] = score, y_te, fwd_te
        pf["fold"] = fold.name
        pred_frames.append(pf)
        log(f"[{model_name}|{task}] fold={fold.name} auc={m['auc']:.4f} "
            f"(best_ep={info['best_epoch']}/{info['epochs_run']}, "
            f"{info['epoch_seconds_mean']}s/epoch)")
        del Mt, Mt_t, net

    aucs = [r["auc"] for r in fold_rows]
    notes = (
        f"{cell.upper()}(input={len(channels)}, hidden={SEQ_HIDDEN}, 1 layer) "
        f"-> Dropout({SEQ_DROPOUT}) -> Linear({SEQ_HIDDEN}->1) over rolling "
        f"windows of the last {SEQ_LEN} sessions ending at (and including) "
        "day t, built within each ticker from the parquet sorted by "
        "(ticker,date); a test row's lookback may extend before test_start "
        "(features are backward-looking -- legal); rows with <20 prior "
        "same-ticker sessions dropped (universe gaps are spanned, 0.2% of "
        "steps >7 calendar days). Channels = FS-study selected top-10 + "
        f"{SEQ_EXTRA}. Channels median-imputed then z-scored with stats "
        "fitted ONLY on rows dated <= the fold's train_end. Train sequences "
        f"capped at ~{cap} per fold by random per-date subsampling (seed "
        "108; ALL test rows kept). AdamW lr=1e-3 wd=1e-4, batch "
        f"{SEQ_BATCH}, max {SEQ_MAX_EPOCHS} epochs, early stopping patience "
        f"{PATIENCE} on inner-validation AUC where inner-val = the LAST 15% "
        "of train DATES (never test rows). Holdout never used for tuning. "
        "Seed 108, 2 torch threads.")
    payload = {
        "model": model_name, "family": FAMILY, "agent": AGENT, "task": task,
        "params": {
            "cell": cell, "hidden": SEQ_HIDDEN, "num_layers": 1,
            "dropout": SEQ_DROPOUT, "seq_len": SEQ_LEN,
            "optimizer": "AdamW", "lr": 1e-3, "weight_decay": 1e-4,
            "batch_size": SEQ_BATCH, "max_epochs": SEQ_MAX_EPOCHS,
            "early_stopping_patience": PATIENCE,
            "inner_val": "last 15% of train dates",
            "train_seq_cap_per_fold": cap,
            "channel_scaling": "train-fitted median impute + z-score "
                               "(rows dated <= train_end)",
            "seed": SEED, "torch_threads": 2,
            "fold_detail": fold_detail,
        },
        "preprocess": "seq_scaled",
        "n_features": len(channels),
        "feature_subset": channels,
        "folds": fold_rows,
        "cv_auc_mean": float(np.mean(aucs)) if aucs else None,
        "cv_auc_std": float(np.std(aucs)) if aucs else None,
        "holdout": holdout,
        "train_seconds": round(time.time() - t0, 1),
        "notes": notes,
    }
    save_results(payload)
    save_preds(model_name, task, pred_frames)
    log(f"[{model_name} | {task}] cv_auc={payload['cv_auc_mean']:.4f} "
        f"(+/-{payload['cv_auc_std']:.4f}) holdout_auc={holdout['auc']:.4f} "
        f"({payload['train_seconds']}s)")
    return payload


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true",
                    help="tiny no-write run to time one MLP+GRU fold")
    ap.add_argument("--parts", default="auto",
                    help="auto | comma list of mlp,gru,gru5,lstm")
    args = ap.parse_args()

    t_start = time.time()
    seed_everything(SEED)
    df, features, splits = load_dataset()
    d = df["date"].to_numpy()
    assert (d[1:] >= d[:-1]).all(), "dataset not date-sorted; inner split invalid"
    log(f"dataset ok: {len(df)} rows, {len(features)} features, date-sorted; "
        f"torch {torch.__version__}, threads=2, seed={SEED}")

    channels = seq_channels(features)
    log(f"gru channels ({len(channels)}): {channels}")

    if args.smoke:
        _smoke(df, features, splits, channels)
        return

    def elapsed():
        return time.time() - t_start

    parts = (None if args.parts == "auto"
             else {p.strip() for p in args.parts.split(",")})

    def want(p):
        return parts is None or p in parts

    # ---- 1) MLP: screen (2 folds) + full protocol (both tasks) ----
    if want("mlp"):
        log("=== mlp: screen + full protocol ===")
        run_mlp(df, features, splits)
        log(f"mlp done at {elapsed() / 60:.1f} min")

    # ---- 2) GRU: primary task (always), up_5d if budget ----
    gru_payload = None
    if want("gru") or want("gru5") or want("lstm"):
        M, pos_of_orig, wt, dates_sorted = build_seq_context(df, channels)
        cap = SEQ_TRAIN_CAP
        proj = bench_seq_epoch_seconds(len(channels), cap)
        if proj > 120:
            cap //= 2
            log(f"projected {proj:.0f}s/epoch > 120s -> halving train cap "
                f"to {cap} (epochs stay at {SEQ_MAX_EPOCHS})")
        else:
            log(f"projected gru epoch time ~{proj:.0f}s at cap={cap}")

        if want("gru"):
            log("=== gru: beat_mkt_20d ===")
            gru_payload = run_seq_model(
                "gru", "gru", PRIMARY, df, features, splits,
                M, pos_of_orig, wt, dates_sorted, channels, cap)
            log(f"gru primary done at {elapsed() / 60:.1f} min")

        gru_cost = (gru_payload["train_seconds"] if gru_payload else 600.0)
        if want("gru5") and (parts is not None or
                             elapsed() + 1.1 * gru_cost < BUDGET_SECONDS):
            log("=== gru: up_5d (budget ok) ===")
            run_seq_model("gru", "gru", SECONDARY, df, features, splits,
                          M, pos_of_orig, wt, dates_sorted, channels, cap)
            log(f"gru up_5d done at {elapsed() / 60:.1f} min")
        elif parts is None:
            log(f"skipping gru up_5d (elapsed {elapsed() / 60:.1f} min + "
                f"~{gru_cost / 60:.1f} min would bust the budget)")

        if want("lstm") and (parts is not None or
                             BUDGET_SECONDS - elapsed() >= 600):
            log("=== lstm: beat_mkt_20d (>=10 min budget left) ===")
            run_seq_model("lstm", "lstm", PRIMARY, df, features, splits,
                          M, pos_of_orig, wt, dates_sorted, channels, cap)
        elif parts is None:
            log(f"skipping lstm (only {(BUDGET_SECONDS - elapsed()) / 60:.1f} "
                "min of budget left)")

    log(f"ALL DONE in {elapsed() / 60:.1f} min")


def _smoke(df, features, splits, channels):
    """Time one small MLP fit and 2 GRU epochs on fold 1. Writes nothing."""
    log("--- smoke: mlp fold 2026-04, 3 epochs ---")
    fold = next(iter_folds(df, features, splits, PRIMARY, "scaled"))
    t0 = time.time()
    est = TorchMLP(max_epochs=3).fit(fold.X_train, fold.y_train)
    auc = roc_auc_score(fold.y_test, est.predict_proba(fold.X_test)[:, 1])
    log(f"mlp smoke: 3 epochs in {time.time() - t0:.0f}s "
        f"({(time.time() - t0) / 3:.1f}s/epoch), test_auc={auc:.4f}")

    log("--- smoke: gru fold 2026-04, 2 epochs, cap 40k ---")
    M, pos_of_orig, wt, dates_sorted = build_seq_context(df, channels)
    proj = bench_seq_epoch_seconds(len(channels), SEQ_TRAIN_CAP)
    log(f"bench projection at cap={SEQ_TRAIN_CAP}: ~{proj:.0f}s/epoch")
    fold = next(iter_folds(df, features, splits, PRIMARY, "raw",
                           feature_subset=channels))
    tr, te = fold.train_df, fold.test_df
    Mt = standardize_fold(M, dates_sorted, tr["date"].max())
    tr_pos_all = pos_of_orig[tr.index.to_numpy()]
    keep = wt[tr_pos_all] >= SEQ_LEN - 1
    tr_pos = tr_pos_all[keep]
    tr_dates = tr["date"].to_numpy()[keep]
    y_tr = tr["label_beat_mkt_20d"].to_numpy(dtype=np.float32)[keep]
    sub = cap_per_date(tr_dates, 40_000)
    t0 = time.time()
    net, Mt_t, offsets, info = fit_seq_fold(
        "gru", len(channels), Mt, tr_pos[sub], tr_dates[sub], y_tr[sub],
        max_epochs=2, patience=PATIENCE)
    te_pos_all = pos_of_orig[te.index.to_numpy()]
    te_keep = wt[te_pos_all] >= SEQ_LEN - 1
    score = _seq_scores(net, Mt_t, torch.from_numpy(te_pos_all[te_keep]),
                        offsets)
    y_te = te["label_beat_mkt_20d"].to_numpy(dtype=np.float32)[te_keep]
    log(f"gru smoke: {info} total {time.time() - t0:.0f}s "
        f"test_auc={roc_auc_score(y_te, score):.4f} "
        f"n_test={int(te_keep.sum())}/{len(te_keep)}")


if __name__ == "__main__":
    main()
