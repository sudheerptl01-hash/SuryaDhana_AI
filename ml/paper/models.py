"""Monthly models of the paper book (ml/paper/SPEC.md 2.1).

For month M: spec = {train_end: the session 22 sessions before M's first session, test_start: M's first session};
rows = ml.scale5y_nested.window_rows(frame, spec, 504) (labelled clean rows of the 504-session window ending at
train_end, exit-date purge at test_start).  Members, exactly as the research harness fits them
(ml/improve/ab.py _fold_job): LightGBM ml.scale5y.make_model("all51"); LambdaRank (LGBMRanker with ab.py's
parameters, grade = floor(10 y_rank_20d) clipped to 0..9, one query per date); CatBoost
ml.scale5y_nested.CB_PARAMS; all on Preprocessor("raw").  The L2 logistic monitor of §10
(make_model("lr_l2") on Preprocessor("scaled")) is fitted on the same rows.

Files: ml/paper/state/models/<M>/ (gitignored: native LightGBM text models, CatBoost .cbm, pickled
preprocessors and logistic model); committed metadata ml/paper/models/<M>.json.

Extension 1 (SPEC.md amendment 10, variant "expanding"): the LightGBM member only, trained on every labelled clean row
from the frame's first session (2017-10-03) to train_end (window_rows with train_sessions = 0, as ml/improve/ab.py
q9_expanding), the same embargo and exit-date purge.  It needs the whole frame (job.py trains it in a child process).
Files ml/paper/state/models/expanding/<M>/, metadata ml/paper/models/expanding/<M>.json.
"""
from __future__ import annotations

import json
import pickle
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ml.paper.common import log, sha256_file, sha256_frame, wjson
from ml.paper.config import (CONTROL_10Y_PREDS, DATA_10Y, EMBARGO_SESSIONS, EXT_FIRST_DATASET_SESSION, EXT_NAME,
                             EXT_TRAIN_SESSIONS, MODELS_META_DIR, N_THREADS, Q9_PREDS, RANKER_PARAMS, RESULTS_DIR, SEED,
                             SPEC_EXT_HASH, SPEC_HASH, STATE_DIR, TRAIN_SESSIONS)

MODELS_STATE = STATE_DIR / "models"
LABEL, CLEAN, FWD = "label_beat_mkt_20d", "y_clean_20d", "y_excess_20d"
REPRO_JSON = RESULTS_DIR / "trainer_reproduction.json"
LOST_STATE_LOG = STATE_DIR / "lost_state_retrains.jsonl"      # gitignored: every lost-state retrain and its checks
MEMBERS_ALL = ("lgbm", "lambdarank", "catboost", "logistic")
REPRO_EXT_JSON = RESULTS_DIR / "trainer_reproduction_expanding.json"
EXT_ROLE = "expanding-window challenger model (SPEC.md amendment 10)"


def state_dir(month: str, variant: str = "base") -> Path:
    return MODELS_STATE / month if variant == "base" else MODELS_STATE / variant / month


def meta_path(month: str, variant: str = "base") -> Path:
    return MODELS_META_DIR / f"{month}.json" if variant == "base" else MODELS_META_DIR / variant / f"{month}.json"


def train_sessions_of(variant: str) -> int:
    return TRAIN_SESSIONS if variant == "base" else EXT_TRAIN_SESSIONS


def check_window_start(dates: pd.DatetimeIndex, train_end: str, variant: str, what: str) -> None:
    """The loaded frame must reach back far enough: 504 sessions before train_end for the frozen models, the
    dataset's first session for the expanding window."""
    if variant == "base":
        if dates.get_loc(pd.Timestamp(train_end)) - TRAIN_SESSIONS < 0:
            raise SystemExit(f"the loaded frame starts {dates[0].date()}, too late for {what}'s {TRAIN_SESSIONS}-session window")
    elif dates[0] != pd.Timestamp(EXT_FIRST_DATASET_SESSION):
        raise SystemExit(f"the expanding window of {what} needs the frame from {EXT_FIRST_DATASET_SESSION}; the loaded "
                         f"frame starts {dates[0].date()}")


def month_spec(dates: pd.DatetimeIndex, month: str) -> dict:
    in_m = dates[dates.strftime("%Y-%m") == month]
    if len(in_m) == 0:
        raise ValueError(f"no session of {month} in the frame")
    first = in_m.min()
    pos = dates.get_loc(first)
    return {"name": month, "train_end": str(dates[max(pos - EMBARGO_SESSIONS, 0)].date()),
            "test_start": str(first.date()), "test_end": str(in_m.max().date())}


def _ranker(n_threads: int):
    """ml/improve/ab.py kind == 'lambdarank', parameter for parameter."""
    import ml.scale5y as s5
    from lightgbm import LGBMRanker
    p = s5.make_model("all51", n_threads).get_params()
    keep = {k: p[k] for k in ("num_leaves", "learning_rate", "n_estimators", "random_state")}
    est = LGBMRanker(objective="lambdarank", feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
                     min_data_in_leaf=200, num_threads=n_threads, verbosity=-1, **keep)
    got = {k: est.get_params()[k] for k in RANKER_PARAMS}
    assert got == RANKER_PARAMS, f"ranker parameters drifted: {got}"
    return est


def fit_members(tr: pd.DataFrame, feats: list[str], members=MEMBERS_ALL) -> dict:
    import ml.scale5y as s5
    from ml.evaluation import Preprocessor
    from ml.scale5y_nested import CB_PARAMS
    out, secs = {}, {}
    prep = Preprocessor("raw").fit(tr[feats])
    Xtr = prep.transform(tr[feats])
    ytr = tr[LABEL].to_numpy(np.float32)
    out["prep"] = prep
    if "lgbm" in members:
        t = time.time()
        est = s5.make_model("all51", N_THREADS)
        est.fit(Xtr, ytr)
        out["lgbm"], secs["lgbm"] = est, round(time.time() - t, 1)
    if "lambdarank" in members:
        t = time.time()
        d = tr["date"].to_numpy()
        assert (d[1:] >= d[:-1]).all()
        grade = np.clip(np.floor(tr["y_rank_20d"].to_numpy(float) * 10), 0, 9).astype(int)
        group = tr.groupby("date", sort=True).size().to_numpy()
        est = _ranker(N_THREADS)
        est.fit(Xtr, grade, group=group)
        out["lambdarank"], secs["lambdarank"] = est, round(time.time() - t, 1)
    if "catboost" in members:
        from catboost import CatBoostClassifier
        t = time.time()
        est = CatBoostClassifier(**CB_PARAMS, allow_writing_files=False)
        est.fit(Xtr, ytr)
        out["catboost"], secs["catboost"] = est, round(time.time() - t, 1)
    if "logistic" in members:
        t = time.time()
        pl = Preprocessor("scaled").fit(tr[feats])
        est = s5.make_model("lr_l2", N_THREADS)
        est.fit(pl.transform(tr[feats]), ytr)
        out["prep_lr"], out["logistic"], secs["logistic"] = pl, est, round(time.time() - t, 1)
    out["seconds"] = secs
    return out


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


class MonthModels:
    """Members of one month loaded from their native files."""

    def __init__(self, month: str, variant: str = "base"):
        import lightgbm as lgb
        self.month, self.variant = month, variant
        d = state_dir(month, variant)
        self.meta = json.loads(meta_path(month, variant).read_text())
        self.members = self.meta["members"]
        with open(d / "preprocess.pkl", "rb") as fh:
            pre = pickle.load(fh)
        self.prep, self.prep_lr = pre["raw"], pre.get("scaled")
        self.feats = self.meta["features"]
        self.lgbm = lgb.Booster(model_file=str(d / "lgbm.txt")) if "lgbm" in self.members else None
        self.ranker = lgb.Booster(model_file=str(d / "lambdarank.txt")) if "lambdarank" in self.members else None
        self.cat = None
        if "catboost" in self.members:
            from catboost import CatBoostClassifier
            self.cat = CatBoostClassifier()
            self.cat.load_model(str(d / "catboost.cbm"))
        self.lr = None
        if "logistic" in self.members:
            with open(d / "logistic.pkl", "rb") as fh:
                self.lr = pickle.load(fh)

    def score(self, rows: pd.DataFrame) -> dict:
        X = self.prep.transform(rows[self.feats])
        out = {}
        if self.lgbm is not None:
            out["lgbm"] = self.lgbm.predict(X, num_threads=N_THREADS)
        if self.ranker is not None:
            out["lambdarank"] = _sigmoid(self.ranker.predict(X, num_threads=N_THREADS))
        if self.cat is not None:
            out["catboost"] = self.cat.predict_proba(X)[:, 1]
        if self.lr is not None:
            out["logistic"] = self.lr.predict_proba(self.prep_lr.transform(rows[self.feats]))[:, 1]
        return out

    def logistic_coefs(self) -> dict:
        return dict(zip(self.feats, self.lr.coef_[0].tolist())) if self.lr is not None else {}


FILE_OF = {"lgbm": "lgbm.txt", "lambdarank": "lambdarank.txt", "catboost": "catboost.cbm", "logistic": "logistic.pkl"}


def catboost_content_sha256(path: Path) -> str:
    """SHA-256 of a CatBoost model without its model_info block (which carries train_finish_time and a random
    model_guid, so two identical fits never have identical .cbm bytes)."""
    import hashlib
    import tempfile
    from catboost import CatBoostClassifier
    m = CatBoostClassifier()
    m.load_model(str(path))
    with tempfile.TemporaryDirectory() as td:
        jp = Path(td) / "m.json"
        m.save_model(str(jp), format="json")
        j = json.loads(jp.read_text())
    j.pop("model_info", None)
    return hashlib.sha256(json.dumps(j, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def member_hashes(d: Path, members) -> dict:
    """Content identity of each member's file: the file's SHA-256, CatBoost's without its run metadata."""
    out = {}
    for k in members:
        f = d / FILE_OF[k]
        if not f.exists():
            out[k] = None
        else:
            out[k] = catboost_content_sha256(f) if k == "catboost" else sha256_file(f)
    return out


def _pred_checksum(arrs: dict) -> dict:
    import hashlib
    return {k: hashlib.sha256(np.round(np.asarray(v, float), 12).tobytes()).hexdigest() for k, v in arrs.items()}


def train_month(df: pd.DataFrame, feats: list[str], dates: pd.DatetimeIndex, darr: np.ndarray, month: str,
                members=MEMBERS_ALL, role: str = "paper model", variant: str = "base") -> dict:
    from ml.scale5y_nested import window_rows
    spec = month_spec(dates, month)
    check_window_start(dates, spec["train_end"], variant, month)
    tr, _te, n_before, n_purged = window_rows(df, darr, dates, spec, train_sessions_of(variant))
    t0 = time.time()
    fit = fit_members(tr, feats, members)
    d = state_dir(month, variant)
    d.mkdir(parents=True, exist_ok=True)
    files = {}
    if "lgbm" in fit:
        fit["lgbm"].booster_.save_model(str(d / "lgbm.txt"))
        files["lgbm"] = d / "lgbm.txt"
    if "lambdarank" in fit:
        fit["lambdarank"].booster_.save_model(str(d / "lambdarank.txt"))
        files["lambdarank"] = d / "lambdarank.txt"
    if "catboost" in fit:
        fit["catboost"].save_model(str(d / "catboost.cbm"))
        files["catboost"] = d / "catboost.cbm"
    with open(d / "preprocess.pkl", "wb") as fh:
        pickle.dump({"raw": fit["prep"], "scaled": fit.get("prep_lr")}, fh, protocol=4)
    files["preprocess"] = d / "preprocess.pkl"
    if "logistic" in fit:
        with open(d / "logistic.pkl", "wb") as fh:
            pickle.dump(fit["logistic"], fh, protocol=4)
        files["logistic"] = d / "logistic.pkl"
    # reference set: the training window's last date (fixed by the spec); in-memory vs reloaded predictions
    ref = tr[tr["date"] == tr["date"].max()]
    Xr = fit["prep"].transform(ref[feats])
    mem = {}
    if "lgbm" in fit:
        mem["lgbm"] = fit["lgbm"].predict_proba(Xr)[:, 1]
    if "lambdarank" in fit:
        mem["lambdarank"] = _sigmoid(fit["lambdarank"].predict(Xr))
    if "catboost" in fit:
        mem["catboost"] = fit["catboost"].predict_proba(Xr)[:, 1]
    if "logistic" in fit:
        mem["logistic"] = fit["logistic"].predict_proba(fit["prep_lr"].transform(ref[feats]))[:, 1]
    import ml.scale5y as s5
    from ml.scale5y_nested import CB_PARAMS
    params = {"lgbm": {k: v for k, v in s5.make_model("all51", N_THREADS).get_params().items()},
              "lambdarank": dict(RANKER_PARAMS, num_threads=N_THREADS,
                                 grade="floor(10 * y_rank_20d) clipped 0..9, one query per date",
                                 score="sigmoid(raw score)"),
              "catboost": {k: v for k, v in CB_PARAMS.items() if k != "verbose"},
              "logistic": {**s5.make_model("lr_l2", N_THREADS).get_params(), "preprocess": "scaled"},
              "preprocess": "raw (train-window median impute)"}
    rule = (f"ml.scale5y_nested.window_rows: {TRAIN_SESSIONS} sessions back from train_end "
            f"({TRAIN_SESSIONS + 1} sessions inclusive, the research walk-forward's "
            f"convention; train_end {EMBARGO_SESSIONS} sessions before the month's first "
            f"session), labelled clean rows, exit-date purge at the first session") if variant == "base" else (
            f"ml.scale5y_nested.window_rows with train_sessions = 0 (ml/improve/ab.py q9_expanding): every labelled "
            f"clean row from the frame's first session ({EXT_FIRST_DATASET_SESSION}) to train_end (train_end "
            f"{EMBARGO_SESSIONS} sessions before the month's first session), exit-date purge at the first session; "
            f"no 504-session cap")
    meta = {"month": month, "role": role, "members": [m for m in MEMBERS_ALL if m in fit],
            "trained_as_of": spec["test_start"], "spec": spec,
            "training_window": {"first_date": str(tr["date"].min().date()), "last_date": str(tr["date"].max().date()),
                                "sessions": int(tr["date"].nunique()), "rows": int(len(tr)),
                                "labelled_clean_rows_before_purge": int(n_before),
                                "rows_purged_exit_ge_test_start": int(n_purged),
                                "tickers": int(tr["ticker"].nunique()), "label_mean": float(tr[LABEL].mean()),
                                "rule": rule},
            "training_frame_sha256": sha256_frame(tr, ["date", "ticker"] + feats + [LABEL, "y_rank_20d"]),
            "features": feats, "n_features": len(feats),
            "params": {k: v for k, v in params.items() if k in fit or k == "preprocess"},
            "files_sha256": {k: sha256_file(v) for k, v in files.items() if k != "preprocess"},
            "content_sha256": member_hashes(d, [k for k in MEMBERS_ALL if k in fit]),
            "reference_set": {"date": str(ref["date"].max().date()), "rows": int(len(ref))},
            "reference_prediction_sha256": _pred_checksum(mem),
            "seed": SEED, "threads": N_THREADS, "spec_hash": SPEC_HASH, "fit_seconds": fit["seconds"]}
    if variant != "base":
        meta["variant"] = variant
        meta["extension_spec_hash"] = SPEC_EXT_HASH
        meta["train_sessions"] = train_sessions_of(variant)
    if "logistic" in fit:
        meta["logistic_coefficients"] = dict(zip(feats, [round(float(c), 10) for c in fit["logistic"].coef_[0]]))
    wjson(meta_path(month, variant), meta)
    mm = MonthModels(month, variant)
    re = mm.score(ref)
    meta_check = {k: float(np.max(np.abs(np.asarray(re[k]) - np.asarray(mem[k])))) for k in mem}
    log(f"model {month} ({role}): {len(tr):,} rows {meta['training_window']['first_date']}..{meta['training_window']['last_date']}, "
        f"fit {fit['seconds']}, reload max|diff| {meta_check} ({time.time() - t0:.0f} s)", "models")
    if any(v != 0.0 for v in meta_check.values()):
        raise SystemExit(f"reloaded model predictions differ from the fitted ones: {meta_check}")
    return meta


def state_complete(month: str, variant: str = "base") -> bool:
    """Committed metadata exists and every member's state file matches it (no frame needed)."""
    p = meta_path(month, variant)
    if not p.exists():
        return False
    meta = json.loads(p.read_text())
    want = meta.get("content_sha256") or meta["files_sha256"]
    have = member_hashes(state_dir(month, variant), meta["members"])
    return all(have.get(k) == want.get(k) for k in meta["members"]) and (state_dir(month, variant) / "preprocess.pkl").exists()


def ensure_month(df, feats, dates, darr, month: str, variant: str = "base") -> dict:
    p = meta_path(month, variant)
    d = state_dir(month, variant)
    if p.exists():
        meta = json.loads(p.read_text())
        want = meta.get("content_sha256") or meta["files_sha256"]
        have = member_hashes(d, meta["members"])
        missing = [k for k in meta["members"] if have.get(k) != want.get(k)]
        if not missing:
            return meta
        log(f"model {month}: state files missing or changed ({missing}); retraining and verifying against the metadata",
            "models")
        old = meta
        new = train_month(df, feats, dates, darr, month, members=tuple(old["members"]), role=old["role"], variant=variant)
        wjson(p, old)                                            # the committed metadata stays the record
        # identity of a model: its contents and its reference predictions.  The training-frame hash depends on the
        # store at the training run (a later corporate action rescales a ticker's earlier prices at rounding level),
        # so it is compared and reported, not required (SPEC.md 2.1, amendment 6).
        checks = {"reference_predictions": new["reference_prediction_sha256"] == old["reference_prediction_sha256"],
                  "model_contents": new["content_sha256"] == (old.get("content_sha256") or old["files_sha256"])}
        info = {"training_frame_sha256_equal": new["training_frame_sha256"] == old["training_frame_sha256"],
                "training_rows_equal": new["training_window"]["rows"] == old["training_window"]["rows"],
                "training_window_equal": all(new["training_window"][k] == old["training_window"][k]
                                             for k in ("first_date", "last_date", "sessions"))}
        same = all(checks.values()) and info["training_rows_equal"] and info["training_window_equal"]
        log(f"model {month} retrained from a lost state; equal to the committed metadata: {checks}; {info}", "models")
        LOST_STATE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOST_STATE_LOG, "a") as fh:
            rec = {"month": month, "checks": checks, "info": info, "new_training_frame_sha256": new["training_frame_sha256"]}
            if variant != "base":
                rec["variant"] = variant
            fh.write(json.dumps(rec) + "\n")
        if not same:
            raise SystemExit(f"retrained {month} differs from its committed metadata (model contents, reference "
                             f"predictions or training window): {checks} {info}; see ml/paper/RUNBOOK.md, 'lost state'")
        return old
    if variant != "base":
        return train_month(df, feats, dates, darr, month, members=("lgbm",), role=EXT_ROLE, variant=variant)
    return train_month(df, feats, dates, darr, month)


def reproduce_research_holdout(df, feats, dates, darr) -> dict:
    """The trainer on the research holdout fold must reproduce the ten-year control's holdout scores."""
    from ml.scale5y_nested import window_rows
    splits = json.loads((DATA_10Y / "splits.json").read_text())
    spec = splits["holdout"]
    if dates.get_loc(pd.Timestamp(spec["train_end"])) - TRAIN_SESSIONS < 0:
        raise SystemExit("the loaded frame starts too late for the research holdout fold's window")
    tr, te, n_before, n_purged = window_rows(df, darr, dates, spec, TRAIN_SESSIONS)
    t0 = time.time()
    fit = fit_members(tr, feats, ("lgbm",))
    s = fit["lgbm"].predict_proba(fit["prep"].transform(te[feats]))[:, 1]
    from ml.paper.config import RESEARCH_END
    ref = pd.read_parquet(CONTROL_10Y_PREDS)
    ref = ref[ref["fold"] == "holdout"]
    ref["date"] = pd.to_datetime(ref["date"])
    # test rows whose label exits after the research end could not be labelled in the research data (here: rows of a
    # ticker whose 20-row label window crosses a suspension into the new sessions); they are listed, not compared
    late = (pd.to_datetime(te["exit_date"]) > pd.Timestamp(RESEARCH_END)).to_numpy()
    mine = te[["date", "ticker"]].assign(score=s)[~late]
    j = mine.merge(ref[["date", "ticker", "score"]], on=["date", "ticker"], how="outer", suffixes=("", "_10y"),
                   indicator=True)
    both = j[j["_merge"] == "both"]
    d = np.abs(both["score"].to_numpy(float) - both["score_10y"].to_numpy(float))
    res = {"fold": spec, "train_rows": int(len(tr)), "test_rows": int(len(te)), "rows_10y": int(len(ref)),
           "test_rows_label_exit_after_research_end": te.loc[late, ["date", "ticker", "exit_date"]].astype(str).to_dict(
               "records"),
           "rows_matched": int(len(both)), "rows_only_trainer": int((j["_merge"] == "left_only").sum()),
           "rows_only_10y": int((j["_merge"] == "right_only").sum()), "max_abs_score_diff": float(d.max()),
           "rows_with_diff_gt_1e-12": int((d > 1e-12).sum()),
           "identical": bool(d.max() == 0.0 and (j["_merge"] != "both").sum() == 0),
           "identical_rule": "every holdout row the research data could label (label exit on or before the research "
                             "end) is present in both and scores exactly the same",
           "seconds": round(time.time() - t0, 1),
           "reference": "ml/results/improve/ab/10y/preds/control__beat_mkt_20d.parquet (fold holdout)"}
    wjson(REPRO_JSON, res)
    log(f"trainer reproduction on the research holdout: matched {res['rows_matched']:,}, max |diff| "
        f"{res['max_abs_score_diff']:.3g}, identical {res['identical']}", "models")
    return res


def reproduce_research_holdout_expanding(df, feats, dates, darr) -> dict:
    """The expanding-window trainer on the research holdout fold must reproduce Q9's holdout scores
    (ml/results/improve/ab/10y_p2/preds/q9_expanding__beat_mkt_20d.parquet, fold holdout)."""
    from ml.scale5y_nested import window_rows
    from ml.paper.config import RESEARCH_END
    splits = json.loads((DATA_10Y / "splits.json").read_text())
    spec = splits["holdout"]
    check_window_start(dates, spec["train_end"], EXT_NAME, "the research holdout fold")
    tr, te, n_before, n_purged = window_rows(df, darr, dates, spec, EXT_TRAIN_SESSIONS)
    t0 = time.time()
    fit = fit_members(tr, feats, ("lgbm",))
    s = fit["lgbm"].predict_proba(fit["prep"].transform(te[feats]))[:, 1]
    ref = pd.read_parquet(Q9_PREDS)
    ref = ref[ref["fold"] == "holdout"]
    ref["date"] = pd.to_datetime(ref["date"])
    late = (pd.to_datetime(te["exit_date"]) > pd.Timestamp(RESEARCH_END)).to_numpy()
    mine = te[["date", "ticker"]].assign(score=s)[~late]
    j = mine.merge(ref[["date", "ticker", "score"]], on=["date", "ticker"], how="outer", suffixes=("", "_q9"),
                   indicator=True)
    both = j[j["_merge"] == "both"]
    d = np.abs(both["score"].to_numpy(float) - both["score_q9"].to_numpy(float))
    res = {"fold": spec, "variant": EXT_NAME, "train_sessions": EXT_TRAIN_SESSIONS,
           "training_window": {"first_date": str(tr["date"].min().date()), "last_date": str(tr["date"].max().date()),
                               "sessions": int(tr["date"].nunique())},
           "train_rows": int(len(tr)), "train_rows_before_purge": int(n_before), "train_rows_purged": int(n_purged),
           "test_rows": int(len(te)), "rows_q9": int(len(ref)),
           "test_rows_label_exit_after_research_end": te.loc[late, ["date", "ticker", "exit_date"]].astype(str).to_dict(
               "records"),
           "rows_matched": int(len(both)), "rows_only_trainer": int((j["_merge"] == "left_only").sum()),
           "rows_only_q9": int((j["_merge"] == "right_only").sum()), "max_abs_score_diff": float(d.max()),
           "rows_with_diff_gt_1e-12": int((d > 1e-12).sum()),
           "identical": bool(d.max() == 0.0 and (j["_merge"] != "both").sum() == 0),
           "identical_rule": "every holdout row the research data could label (label exit on or before the research "
                             "end) is present in both and scores exactly the same",
           "seconds": round(time.time() - t0, 1),
           "reference": "ml/results/improve/ab/10y_p2/preds/q9_expanding__beat_mkt_20d.parquet (fold holdout)"}
    wjson(REPRO_EXT_JSON, res)
    log(f"expanding trainer reproduction on the research holdout: {len(tr):,} training rows, matched "
        f"{res['rows_matched']:,}, max |diff| {res['max_abs_score_diff']:.3g}, identical {res['identical']}", "models")
    return res


def explain_reproduction_expanding() -> dict:
    """Why the expanding trainer on the paper frame does not reproduce Q9's holdout scores bit for bit.

    (1) The same trainer (fit_members, window_rows(train_sessions=0)) on the research frame ml/data_10y must reproduce
    Q9 exactly: then the trainer is Q9's.  (2) The training rows of the two frames are compared cell by cell (the
    paper frame carries the live corporate-action feed's rescaling, consistency.json).  (3) The paper-frame scores are
    compared with Q9's: AUC, per-date rank correlation, per-date top-decile overlap.  Writes the result under
    "explanation" in trainer_reproduction_expanding.json.  Two fits of about 2.1 million rows, one at a time."""
    import gc
    from sklearn.metrics import roc_auc_score
    from ml.improve.ab import load_frame as ab_load_frame
    from ml.scale5y_nested import window_rows
    from ml.paper.config import RESEARCH_END
    spec = json.loads((DATA_10Y / "splits.json").read_text())["holdout"]
    ref = pd.read_parquet(Q9_PREDS)
    ref = ref[ref["fold"] == "holdout"].copy()
    ref["date"] = pd.to_datetime(ref["date"])
    out: dict = {}

    def fit_score(df, feats, label):
        dates = pd.DatetimeIndex(np.sort(df["date"].unique()))
        darr = df["date"].to_numpy(dtype="datetime64[ns]")
        tr, te, _nb, _np = window_rows(df, darr, dates, spec, EXT_TRAIN_SESSIONS)
        t0 = time.time()
        fit = fit_members(tr, feats, ("lgbm",))
        s = fit["lgbm"].predict_proba(fit["prep"].transform(te[feats]))[:, 1]
        late = (pd.to_datetime(te["exit_date"]) > pd.Timestamp(RESEARCH_END)).to_numpy()
        sc = te[["date", "ticker", LABEL]].assign(score=s)[~late]
        j = sc.merge(ref[["date", "ticker", "score"]], on=["date", "ticker"], suffixes=("", "_q9"), how="inner")
        d = np.abs(j["score"].to_numpy(float) - j["score_q9"].to_numpy(float))
        rec = {"frame": label, "train_rows": int(len(tr)), "rows_matched": int(len(j)), "max_abs_score_diff": float(d.max()),
               "identical": bool(d.max() == 0.0 and len(j) == len(ref)), "fit_seconds": round(time.time() - t0, 1)}
        keep = tr[["date", "ticker"]].reset_index(drop=True), tr[feats].to_numpy(np.float64), tr[LABEL].to_numpy(float)
        return rec, j, keep

    df, feats, _ = ab_load_frame(DATA_10Y, None, None, False)
    r_res, _j, keep_res = fit_score(df, feats, "ml/data_10y (the research frame Q9 ran on)")
    out["on_research_frame"] = r_res
    del df, _j
    gc.collect()
    from ml.paper.job import load_frame as paper_load_frame
    df, feats_p, _s, _d, _a = paper_load_frame(None)
    assert feats_p == feats, "feature lists differ"
    r_pap, j, keep_pap = fit_score(df, feats, "ml/paper/state/frame (the paper frame, live corporate-action feed)")
    del df
    gc.collect()
    keys_equal = bool(keep_res[0].equals(keep_pap[0]))
    cells = {}
    if keys_equal:
        a, b = keep_res[1], keep_pap[1]
        both_nan = np.isnan(a) & np.isnan(b)
        diff = ~both_nan & (a != b)
        per = diff.sum(axis=0)
        cells = {"training_rows_same_keys": True, "feature_cells_differing": int(diff.sum()),
                 "max_abs_feature_diff": float(np.nanmax(np.where(diff, np.abs(a - b), 0.0))),
                 "rows_with_a_differing_cell": int(diff.any(axis=1).sum()),
                 "tickers_with_a_differing_cell": int(keep_pap[0].loc[diff.any(axis=1), "ticker"].nunique()),
                 "per_feature": {f: int(n) for f, n in zip(feats, per) if n},
                 "label_cells_differing": int((keep_res[2] != keep_pap[2]).sum())}
    else:
        cells = {"training_rows_same_keys": False}
    j["d"] = j["date"]
    per_date = []
    for d_, g in j.groupby("d"):
        k = max(1, int(round(0.1 * len(g))))
        top_a = set(g.nlargest(k, "score")["ticker"])
        top_b = set(g.nlargest(k, "score_q9")["ticker"])
        per_date.append({"rho": float(g["score"].rank().corr(g["score_q9"].rank())), "top_decile_overlap": len(top_a & top_b) / k})
    r_pap.update(auc_paper_frame=float(roc_auc_score(j[LABEL], j["score"])),
                 auc_q9=float(roc_auc_score(j[LABEL], j["score_q9"])),
                 per_date_spearman_min=float(min(x["rho"] for x in per_date)),
                 per_date_spearman_mean=float(np.mean([x["rho"] for x in per_date])),
                 per_date_top_decile_overlap_min=float(min(x["top_decile_overlap"] for x in per_date)),
                 per_date_top_decile_overlap_mean=float(np.mean([x["top_decile_overlap"] for x in per_date])),
                 dates=len(per_date))
    out["on_paper_frame"] = r_pap
    out["training_cells_paper_vs_research_frame"] = cells
    out["reading"] = ("the trainer reproduces Q9 exactly on the research frame; on the paper frame the training cells that "
                      "the live corporate-action feed rescales differ at rounding level, LightGBM's bin boundaries and split "
                      "thresholds are taken from the training values, so the fitted trees and the scores "
                      "differ slightly") if r_res["identical"] else "the trainer does not reproduce Q9 on the research frame"
    res = json.loads(REPRO_EXT_JSON.read_text())
    res["explanation"] = out
    wjson(REPRO_EXT_JSON, res)
    log(f"expanding reproduction explained: research frame identical {r_res['identical']} (max |diff| "
        f"{r_res['max_abs_score_diff']:.3g}); paper frame max |diff| {r_pap['max_abs_score_diff']:.3g}, AUC "
        f"{r_pap['auc_paper_frame']:.5f} vs Q9 {r_pap['auc_q9']:.5f}; differing training cells "
        f"{cells.get('feature_cells_differing')}", "models")
    return out
