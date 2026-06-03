from __future__ import annotations

import sys
import pickle
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, status, Query
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.config import get_settings
from shared.logging import configure_logging, get_logger

from models import DirectionClassifier, ReturnRegressor
from training import walk_forward_validation

logger = get_logger(__name__)

# ── Model Catalog Definition ───────────────────────────────────────────────────

MODEL_CATALOG: dict[str, dict] = {
    "xgboost": {
        "name": "XGBoost",
        "description": "Gradient boosted trees — SHAP-native, top performer for tabular data",
        "library": "xgboost",
        "type": "boosting",
        "pros": ["Native SHAP support", "Handles missing values", "Regularization built-in"],
        "cons": ["Slower than LightGBM on large data", "Memory intensive"],
        "default_params": {"n_estimators": 300, "max_depth": 5, "learning_rate": 0.05},
    },
    "lightgbm": {
        "name": "LightGBM",
        "description": "Leaf-wise gradient boosting — faster than XGBoost, excellent on large datasets",
        "library": "lightgbm",
        "type": "boosting",
        "pros": ["2-10× faster than XGBoost", "Lower memory", "Handles categorical natively"],
        "cons": ["More prone to overfitting on small data"],
        "default_params": {"n_estimators": 300, "max_depth": 5, "learning_rate": 0.05},
    },
    "random_forest": {
        "name": "Random Forest",
        "description": "Bagging ensemble — robust out-of-the-box baseline, highly stable",
        "library": "sklearn",
        "type": "ensemble",
        "pros": ["Robust to outliers", "No tuning needed", "Reliable OOB estimate"],
        "cons": ["Slow inference", "High memory", "No iterative improvement"],
        "default_params": {"n_estimators": 200, "max_depth": 12, "min_samples_leaf": 10},
    },
    "extra_trees": {
        "name": "Extra Trees",
        "description": "Extremely randomized trees — faster training, often lower variance than RF",
        "library": "sklearn",
        "type": "ensemble",
        "pros": ["Faster than RF", "Less overfitting via max randomization"],
        "cons": ["Slightly lower accuracy vs RF"],
        "default_params": {"n_estimators": 200, "max_depth": 12, "min_samples_leaf": 5},
    },
    "gradient_boosting": {
        "name": "Gradient Boosting",
        "description": "Sklearn sequential boosting — solid baseline, good calibration",
        "library": "sklearn",
        "type": "boosting",
        "pros": ["Well-calibrated probabilities", "Good for small datasets"],
        "cons": ["Slow training — single threaded"],
        "default_params": {"n_estimators": 100, "max_depth": 4, "learning_rate": 0.1},
    },
    "logistic_regression": {
        "name": "Logistic Regression",
        "description": "Linear baseline with L2 regularization — perfectly calibrated, interpretable",
        "library": "sklearn",
        "type": "linear",
        "pros": ["Perfect calibration", "Instant training", "Fully interpretable coefficients"],
        "cons": ["Assumes linearity", "Cannot capture interactions"],
        "default_params": {"C": 1.0},
    },
}

# ── Global State ───────────────────────────────────────────────────────────────

# Active model globals (mirrors the active registry entry — used by all existing inference endpoints)
_classifier: DirectionClassifier | None = None
_regressor: ReturnRegressor | None = None
_oos_metrics: dict = {}
_X_val: pd.DataFrame | None = None
_y_val: pd.Series | None = None
_val_proba: np.ndarray | None = None

# Multi-model registry
_model_registry: dict[str, dict] = {}
_active_model_id: str | None = None


# ── Generic Classifier Wrapper (all non-XGBoost models) ───────────────────────

class GenericClassifier:
    """Wraps sklearn-compatible classifiers with the same interface as DirectionClassifier."""

    def __init__(self, model_type: str, params: dict | None = None):
        self.model_type = model_type
        self._feature_cols: list[str] = []
        self._version = "untrained"
        self._params = params or {}
        self._model = self._build(params)

    def _build(self, params: dict | None):
        p = params or {}
        if self.model_type == "random_forest":
            from sklearn.ensemble import RandomForestClassifier
            defaults = {"n_estimators": 200, "max_depth": 12, "min_samples_leaf": 10, "random_state": 42, "n_jobs": -1, "class_weight": "balanced"}
            defaults.update({k: v for k, v in p.items() if k in defaults})
            return RandomForestClassifier(**defaults)
        elif self.model_type == "extra_trees":
            from sklearn.ensemble import ExtraTreesClassifier
            defaults = {"n_estimators": 200, "max_depth": 12, "min_samples_leaf": 5, "random_state": 42, "n_jobs": -1, "class_weight": "balanced"}
            defaults.update({k: v for k, v in p.items() if k in defaults})
            return ExtraTreesClassifier(**defaults)
        elif self.model_type == "gradient_boosting":
            from sklearn.ensemble import GradientBoostingClassifier
            defaults = {"n_estimators": 100, "max_depth": 4, "learning_rate": 0.1, "subsample": 0.8, "random_state": 42}
            defaults.update({k: v for k, v in p.items() if k in defaults})
            return GradientBoostingClassifier(**defaults)
        elif self.model_type == "logistic_regression":
            from sklearn.linear_model import LogisticRegression
            from sklearn.pipeline import Pipeline
            from sklearn.preprocessing import StandardScaler
            C = float(p.get("C", 1.0))
            return Pipeline([("scaler", StandardScaler()), ("clf", LogisticRegression(C=C, max_iter=2000, random_state=42, class_weight="balanced"))])
        elif self.model_type == "lightgbm":
            import lightgbm as lgb
            defaults = {"n_estimators": 300, "max_depth": 5, "learning_rate": 0.05,
                        "subsample": 0.8, "colsample_bytree": 0.8, "random_state": 42,
                        "n_jobs": -1, "verbose": -1, "class_weight": "balanced"}
            defaults.update({k: v for k, v in p.items() if k in defaults})
            return lgb.LGBMClassifier(**defaults)
        else:
            raise ValueError(f"Unknown model_type: {self.model_type}")

    def fit(self, X_train: pd.DataFrame, y_train: pd.Series, X_val=None, y_val=None):
        self._feature_cols = list(X_train.columns)
        self._model.fit(X_train, y_train)
        self._version = "v1"
        logger.info(f"{self.model_type} trained", features=len(self._feature_cols))

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Not fitted")
        return self._model.predict_proba(X[self._feature_cols])

    def predict_single(self, feature_row: dict) -> tuple[int, float, float]:
        X = pd.DataFrame([feature_row])[self._feature_cols]
        proba = self.predict_proba(X)[0]
        prob_up = float(proba[1])
        return (1 if prob_up >= 0.5 else 0), prob_up, abs(prob_up - 0.5)

    @property
    def feature_importances(self) -> dict[str, float]:
        try:
            if hasattr(self._model, "feature_importances_"):
                return {k: float(v) for k, v in zip(self._feature_cols, self._model.feature_importances_)}
            elif hasattr(self._model, "named_steps"):
                clf = self._model.named_steps.get("clf")
                if hasattr(clf, "coef_"):
                    return {k: float(abs(v)) for k, v in zip(self._feature_cols, clf.coef_[0])}
        except Exception:
            pass
        return {}

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"model": self._model, "feature_cols": self._feature_cols,
                         "version": self._version, "model_type": self.model_type}, f)

    @classmethod
    def load(cls, path: str) -> "GenericClassifier":
        with open(path, "rb") as f:
            data = pickle.load(f)
        obj = cls.__new__(cls)
        obj.model_type = data.get("model_type", "unknown")
        obj._model = data["model"]
        obj._feature_cols = data["feature_cols"]
        obj._version = data.get("version", "unknown")
        obj._params = {}
        return obj


# ── Helpers ────────────────────────────────────────────────────────────────────

def _compute_metrics(y_true: pd.Series, proba: np.ndarray) -> dict:
    from sklearn.metrics import (
        accuracy_score, f1_score, log_loss, roc_auc_score,
        confusion_matrix, roc_curve, precision_score, recall_score,
    )
    try:
        from sklearn.calibration import calibration_curve as _cc
    except ImportError:
        _cc = None

    preds = (proba[:, 1] >= 0.5).astype(int)
    y_int = y_true.astype(int)

    metrics: dict = {
        "accuracy":  round(float(accuracy_score(y_int, preds)), 4),
        "f1_score":  round(float(f1_score(y_int, preds, zero_division=0)), 4),
        "precision": round(float(precision_score(y_int, preds, zero_division=0)), 4),
        "recall":    round(float(recall_score(y_int, preds, zero_division=0)), 4),
        "log_loss":  round(float(log_loss(y_int, proba)), 4),
        "auc_roc":   round(float(roc_auc_score(y_int, proba[:, 1])), 4),
        "version": "v1",
        "val_samples": int(len(y_int)),
    }

    cm = confusion_matrix(y_int, preds)
    metrics["confusion_matrix"] = cm.tolist()

    fpr_arr, tpr_arr, _ = roc_curve(y_int, proba[:, 1])
    step = max(1, len(fpr_arr) // 150)
    metrics["roc_curve"] = {
        "fpr": [round(float(f), 4) for f in fpr_arr[::step]],
        "tpr": [round(float(t), 4) for t in tpr_arr[::step]],
    }

    hist_counts, bin_edges = np.histogram(proba[:, 1], bins=20, range=(0.0, 1.0))
    bin_centers = [(bin_edges[i] + bin_edges[i + 1]) / 2 for i in range(len(bin_edges) - 1)]
    metrics["score_distribution"] = {
        "bins":   [round(float(c), 3) for c in bin_centers],
        "counts": [int(c) for c in hist_counts],
    }

    if _cc is not None:
        try:
            frac_pos, mean_pred = _cc(y_int, proba[:, 1], n_bins=10)
            metrics["calibration"] = {
                "fraction_positives": [round(float(f), 4) for f in frac_pos],
                "mean_predicted":     [round(float(m), 4) for m in mean_pred],
            }
        except Exception:
            pass

    return metrics


def _activate_registry_entry(entry: dict):
    """Mirror a registry entry into the global inference variables."""
    global _classifier, _X_val, _y_val, _val_proba, _oos_metrics, _active_model_id
    _classifier = entry["_model"]
    _X_val      = entry.get("_X_val")
    _y_val      = entry.get("_y_val")
    _val_proba  = entry.get("_val_proba")
    _oos_metrics = entry.get("_oos_metrics", {})
    _active_model_id = entry["model_id"]


# ── Lifespan ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _classifier, _regressor, _active_model_id
    settings = get_settings()
    configure_logging("ml-service", settings.log_level)

    clf_path = "models/xgb_classifier_v1.pkl"
    reg_path = "models/xgb_regressor_v1.pkl"

    if Path(clf_path).exists():
        _classifier = DirectionClassifier.load(clf_path)
        _active_model_id = "xgboost_startup"
        _model_registry["xgboost_startup"] = {
            "model_id": "xgboost_startup",
            "model_type": "xgboost",
            "display_name": "XGBoost (loaded from disk)",
            "metrics": {},
            "feature_cols": _classifier._feature_cols,
            "n_features": len(_classifier._feature_cols),
            "trained_at": "—",
            "is_active": True,
            "training_time_secs": 0.0,
            "_model": _classifier,
            "_X_val": None,
            "_y_val": None,
            "_val_proba": None,
            "_oos_metrics": {},
        }
    if Path(reg_path).exists():
        _regressor = ReturnRegressor.load(reg_path)

    logger.info("ML service started", classifier_loaded=_classifier is not None)
    yield
    logger.info("ML service stopped")


app = FastAPI(title="SuryaDhana — ML Service", version="2.0.0", lifespan=lifespan)


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    active = _model_registry.get(_active_model_id or "", {})
    return {
        "status": "ok",
        "service": "ml-service",
        "classifier_ready": _classifier is not None,
        "regressor_ready": _regressor is not None,
        "active_model": active.get("model_type", "none"),
        "registry_size": len(_model_registry),
    }


# ── Model Catalog ──────────────────────────────────────────────────────────────

@app.get("/catalog")
async def get_catalog() -> dict:
    """Return available model types + which ones have been trained."""
    trained_types = {e["model_type"] for e in _model_registry.values()}
    result = {}
    for key, info in MODEL_CATALOG.items():
        entry = {"key": key, **info, "trained": key in trained_types}
        if key in trained_types:
            # Find latest trained entry of this type
            entries = [e for e in _model_registry.values() if e["model_type"] == key]
            best = max(entries, key=lambda e: e.get("metrics", {}).get("auc_roc", 0))
            entry["best_auc"] = best.get("metrics", {}).get("auc_roc", 0)
        result[key] = entry
    return result


@app.get("/registry")
async def get_registry() -> list:
    """Return all trained models with public metadata (no internal _model objects)."""
    public_keys = {"model_id", "model_type", "display_name", "metrics",
                   "feature_cols", "n_features", "trained_at", "is_active", "training_time_secs"}
    return [
        {k: v for k, v in entry.items() if k in public_keys}
        for entry in sorted(_model_registry.values(), key=lambda e: e.get("trained_at", ""), reverse=True)
    ]


@app.post("/registry/{model_id}/activate")
async def activate_model(model_id: str) -> dict:
    """Set the active model used for inference."""
    if model_id not in _model_registry:
        raise HTTPException(status_code=404, detail=f"Model {model_id} not found")
    for eid, entry in _model_registry.items():
        entry["is_active"] = (eid == model_id)
    _activate_registry_entry(_model_registry[model_id])
    return {"activated": model_id, "model_type": _model_registry[model_id]["model_type"]}


@app.delete("/registry/{model_id}")
async def delete_model(model_id: str) -> dict:
    if model_id not in _model_registry:
        raise HTTPException(status_code=404, detail=f"Model {model_id} not found")
    if _model_registry[model_id].get("is_active"):
        raise HTTPException(status_code=400, detail="Cannot delete the active model. Activate another first.")
    _model_registry.pop(model_id)
    return {"deleted": model_id}


# ── Training ───────────────────────────────────────────────────────────────────

class TrainRequest(BaseModel):
    features: list[dict]
    feature_cols: list[str]
    target_direction: str = "label_direction"
    target_return: str = "label_return_pct"
    date_col: str = "date"
    run_walk_forward: bool = False
    save_models: bool = True
    model_type: str = "xgboost"
    model_params: dict | None = None
    make_active: bool = True


class TrainResponse(BaseModel):
    model_id: str
    model_type: str
    classifier_trained: bool
    regressor_trained: bool
    walk_forward_summary: dict | None
    metrics: dict


@app.post("/train", response_model=TrainResponse)
async def train(req: TrainRequest) -> TrainResponse:
    global _regressor

    df = pd.DataFrame(req.features)
    df = df.dropna(subset=req.feature_cols + [req.target_direction, req.target_return])

    if len(df) < 500:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient data: {len(df)} rows. Need ≥500."
        )

    split = int(len(df) * 0.8)
    X_train = df.iloc[:split][req.feature_cols]
    X_val   = df.iloc[split:][req.feature_cols]
    y_dir_train = df.iloc[:split][req.target_direction]
    y_dir_val   = df.iloc[split:][req.target_direction]
    y_ret_train = df.iloc[:split][req.target_return]
    y_ret_val   = df.iloc[split:][req.target_return]

    t0 = datetime.now()

    # ── Validate before expensive training ────────────────────────────────────
    if X_train.empty:
        raise HTTPException(status_code=400, detail="Training set is empty after filtering. Check date range and data availability.")

    inf_mask = np.isinf(X_train.values)
    if inf_mask.any():
        bad_cols = X_train.columns[inf_mask.any(axis=0)].tolist()[:5]
        logger.warning("Replacing inf values in training features", cols=bad_cols)
        X_train = X_train.replace([np.inf, -np.inf], np.nan).fillna(0)
        X_val   = X_val.replace([np.inf, -np.inf], np.nan).fillna(0)

    nan_mask = X_train.isna()
    if nan_mask.any().any():
        bad_cols = X_train.columns[nan_mask.any(axis=0)].tolist()[:5]
        logger.warning("Filling NaN values in training features", cols=bad_cols)
        X_train = X_train.fillna(0)
        X_val   = X_val.fillna(0)

    if len(y_dir_train.unique()) < 2:
        raise HTTPException(
            status_code=400,
            detail=f"Training labels have only one class: {y_dir_train.unique().tolist()}. "
                   "Run feature engineering and label generation again — dataset may be too narrow."
        )
    # ─────────────────────────────────────────────────────────────────────────

    # Build and train classifier
    try:
        if req.model_type == "xgboost":
            clf = DirectionClassifier(params=req.model_params)
            clf.fit(X_train, y_dir_train, X_val, y_dir_val)
        else:
            clf = GenericClassifier(model_type=req.model_type, params=req.model_params)
            clf.fit(X_train, y_dir_train, X_val, y_dir_val)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=f"Training failed: {exc}") from exc
    except Exception as exc:
        logger.error("Unexpected training error", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Unexpected training error: {exc}") from exc

    # Train regressor (always XGBoost — only for the active model)
    if req.make_active:
        try:
            _regressor = ReturnRegressor(params=req.model_params if req.model_type == "xgboost" else None)
            _regressor.fit(X_train, y_ret_train, X_val, y_ret_val)
        except Exception as exc:
            logger.warning("Regressor training failed — continuing without it", error=str(exc))

    elapsed = (datetime.now() - t0).total_seconds()

    # Compute all OOS metrics
    proba = clf.predict_proba(X_val)
    metrics = _compute_metrics(y_dir_val, proba)

    # Build registry entry
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_id = f"{req.model_type}_{ts}"
    entry = {
        "model_id":          model_id,
        "model_type":        req.model_type,
        "display_name":      MODEL_CATALOG.get(req.model_type, {}).get("name", req.model_type),
        "metrics":           {k: v for k, v in metrics.items() if not isinstance(v, (list, dict))},
        "feature_cols":      list(req.feature_cols),
        "n_features":        len(req.feature_cols),
        "trained_at":        datetime.now().isoformat(),
        "is_active":         req.make_active,
        "training_time_secs": round(elapsed, 1),
        # Internal
        "_model":      clf,
        "_X_val":      X_val.copy(),
        "_y_val":      y_dir_val.copy(),
        "_val_proba":  proba,
        "_oos_metrics": metrics,
    }

    # Deactivate other models if this becomes active
    if req.make_active:
        for eid in _model_registry:
            _model_registry[eid]["is_active"] = False
        _activate_registry_entry(entry)

    _model_registry[model_id] = entry

    # Save XGBoost model to disk for persistence
    if req.model_type == "xgboost" and req.save_models:
        clf.save("models/xgb_classifier_v1.pkl")
        if _regressor:
            _regressor.save("models/xgb_regressor_v1.pkl")
    elif req.save_models:
        clf.save(f"models/{model_id}.pkl")

    wf_summary = None
    if req.run_walk_forward and req.model_type == "xgboost":
        try:
            wf_result = walk_forward_validation(
                df=df, feature_cols=req.feature_cols,
                target_col=req.target_direction, date_col=req.date_col,
                model_factory=lambda: DirectionClassifier(),
            )
            wf_summary = wf_result.summary()
        except Exception as e:
            wf_summary = {"error": str(e)}

    return TrainResponse(
        model_id=model_id,
        model_type=req.model_type,
        classifier_trained=True,
        regressor_trained=req.make_active,
        walk_forward_summary=wf_summary,
        metrics={k: v for k, v in metrics.items() if not isinstance(v, (list, dict))},
    )


# ── Inference ──────────────────────────────────────────────────────────────────

class PredictRequest(BaseModel):
    ticker: str
    features: dict[str, float]


@app.post("/predict")
async def predict(req: PredictRequest) -> dict:
    if _classifier is None:
        raise HTTPException(status_code=503, detail="Models not loaded. Run /train first.")
    direction, prob_up, confidence = _classifier.predict_single(req.features)
    settings = get_settings()
    return {
        "ticker": req.ticker,
        "direction": direction,
        "prob_up": round(prob_up, 4),
        "confidence": round(confidence, 4),
        "expected_return_pct": 0.0,
        "is_high_confidence": confidence >= settings.min_signal_confidence,
        "model_type": _model_registry.get(_active_model_id or "", {}).get("model_type", "unknown"),
    }


# ── Batch Inference (called by master_controller every 15 min) ─────────────────

class BatchPredictRequest(BaseModel):
    tickers: list[str] | None = None  # None = full universe from DuckDB


class BatchPredictResponse(BaseModel):
    signals: list[dict]
    ticker_count: int
    signal_count: int
    model_type: str
    timestamp_ist: str


@app.post("/batch-predict", response_model=BatchPredictResponse)
async def batch_predict(req: BatchPredictRequest) -> BatchPredictResponse:
    """
    Run inference on all tickers using the latest feature row per ticker.
    Called by master_controller every 15 min during market hours.

    Features are fetched from data-service `/db/latest-features` over HTTP —
    ml-service must NOT open its own DuckDB connection: on Docker Desktop (Mac,
    virtioFS) a second connection fails with "Conflicting lock is held in PID 0"
    even read-only, which previously made every intraday inference cycle 503.
    """
    import os
    import time as _t
    import pytz
    import httpx

    if _classifier is None:
        raise HTTPException(status_code=503, detail="Classifier not loaded. Run /train first.")

    IST = pytz.timezone("Asia/Kolkata")
    settings = get_settings()
    data_svc = os.getenv("DATA_SERVICE_URL", "http://data-service:8001")

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            resp = await client.get(f"{data_svc}/db/latest-features")
        resp.raise_for_status()
        df = pd.DataFrame(resp.json().get("data", []))
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"feature fetch from data-service failed: {exc}")

    if req.tickers and "ticker" in df.columns:
        df = df[df["ticker"].isin(req.tickers)]

    if df.empty:
        raise HTTPException(status_code=404, detail="No feature data found. Run feature generation first.")

    feature_cols = _classifier._feature_cols
    df_cols = set(df.columns)
    present_cols = [c for c in feature_cols if c in df_cols]
    missing_cols = [c for c in feature_cols if c not in df_cols]
    signals: list[dict] = []
    t0 = _t.perf_counter()

    # Schema-drift guard: if the active model was trained on a materially different
    # feature set than the current ml_features table, fail loudly (with the exact
    # gap) rather than silently emit nothing — that means the model needs retraining
    # on the current schema. A small gap (>50% present) is tolerated: the missing
    # model features are imputed to 0.0 so predict_single's column order is satisfied.
    if len(present_cols) < len(feature_cols) * 0.5:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Model/feature schema drift: only {len(present_cols)}/{len(feature_cols)} "
                f"model features present in ml_features. Retrain the active model on the "
                f"current schema. Missing: {missing_cols[:10]}"
            ),
        )
    if missing_cols:
        logger.warning("batch_predict feature gap", missing=missing_cols, imputed_zero=len(missing_cols))

    for _, row in df.iterrows():
        try:
            # Provide every model feature (missing ones imputed 0.0) so predict_single's
            # df[feature_cols] selection never KeyErrors on a partial-schema row.
            feat_dict = {c: float(row.get(c, 0.0) or 0.0) for c in feature_cols}
            direction, prob_up, confidence = _classifier.predict_single(feat_dict)
            if confidence >= settings.min_signal_confidence:
                signals.append({
                    "ticker": str(row["ticker"]),
                    "direction": direction,
                    "prob_up": round(float(prob_up), 4),
                    "confidence": round(float(confidence), 4),
                    "is_high_confidence": True,
                    "date": str(row.get("date", "")),
                })
        except Exception:
            continue  # single bad row must not abort the full batch

    elapsed_ms = (_t.perf_counter() - t0) * 1000
    logger.info(
        "batch_predict complete",
        tickers_scanned=len(df),
        signals_emitted=len(signals),
        elapsed_ms=round(elapsed_ms, 1),
    )

    return BatchPredictResponse(
        signals=signals,
        ticker_count=len(df),
        signal_count=len(signals),
        model_type=_model_registry.get(_active_model_id or "", {}).get("model_type", "xgboost"),
        timestamp_ist=datetime.now(IST).isoformat(),
    )


# ── Classification Analysis (active model) ────────────────────────────────────

def _active_entry() -> dict:
    if not _active_model_id or _active_model_id not in _model_registry:
        raise HTTPException(status_code=503, detail="No active model. Train first.")
    return _model_registry[_active_model_id]


def _entry_by_id(model_id: str | None) -> dict:
    mid = model_id or _active_model_id
    if not mid or mid not in _model_registry:
        raise HTTPException(status_code=503, detail="Model not found. Train first.")
    return _model_registry[mid]


@app.get("/metrics")
async def get_metrics(model_id: str | None = Query(None)) -> dict:
    entry = _entry_by_id(model_id)
    m = entry.get("_oos_metrics", {})
    if not m:
        raise HTTPException(status_code=503, detail="No metrics — train the model first")
    return {k: v for k, v in m.items() if not isinstance(v, (list, dict))}


@app.get("/confusion-matrix")
async def get_confusion_matrix(model_id: str | None = Query(None)) -> dict:
    entry = _entry_by_id(model_id)
    cm_raw = entry.get("_oos_metrics", {}).get("confusion_matrix")
    if not cm_raw:
        raise HTTPException(status_code=503, detail="Train model first")
    cm = cm_raw
    tn, fp, fn, tp = cm[0][0], cm[0][1], cm[1][0], cm[1][1]
    total = tn + fp + fn + tp
    return {
        "tn": tn, "fp": fp, "fn": fn, "tp": tp,
        "precision":   round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0,
        "recall":      round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0,
        "specificity": round(tn / (tn + fp), 4) if (tn + fp) > 0 else 0.0,
        "npv":         round(tn / (tn + fn), 4) if (tn + fn) > 0 else 0.0,
        "total": total,
    }


@app.get("/roc-curve")
async def get_roc_curve(model_id: str | None = Query(None)) -> dict:
    entry = _entry_by_id(model_id)
    roc = entry.get("_oos_metrics", {}).get("roc_curve")
    if not roc:
        raise HTTPException(status_code=503, detail="Train model first")
    return {
        "points": [{"fpr": f, "tpr": t} for f, t in zip(roc["fpr"], roc["tpr"])],
        "auc": entry.get("_oos_metrics", {}).get("auc_roc", 0.0),
    }


@app.get("/score-distribution")
async def get_score_distribution(model_id: str | None = Query(None)) -> dict:
    entry = _entry_by_id(model_id)
    sd = entry.get("_oos_metrics", {}).get("score_distribution")
    if not sd:
        raise HTTPException(status_code=503, detail="Train model first")
    return {"histogram": [{"score": s, "count": c} for s, c in zip(sd["bins"], sd["counts"])]}


@app.get("/calibration")
async def get_calibration(model_id: str | None = Query(None)) -> dict:
    entry = _entry_by_id(model_id)
    cal = entry.get("_oos_metrics", {}).get("calibration")
    if not cal:
        raise HTTPException(status_code=503, detail="Train model first")
    return {
        "points": [{"mean_pred": mp, "frac_pos": fp}
                   for mp, fp in zip(cal["mean_predicted"], cal["fraction_positives"])]
    }


@app.get("/model-params")
async def get_model_params(model_id: str | None = Query(None)) -> dict:
    entry = _entry_by_id(model_id)
    clf = entry["_model"]

    def _cast(v: Any) -> Any:
        if isinstance(v, np.integer): return int(v)
        if isinstance(v, np.floating): return float(v)
        return v

    try:
        params = {k: _cast(v) for k, v in clf._params.items()}
    except AttributeError:
        params = {}

    return {
        "classifier": params,
        "model_type": entry["model_type"],
        "feature_count": entry["n_features"],
        "features": entry["feature_cols"],
    }


@app.get("/feature-importance")
async def feature_importance(model_id: str | None = Query(None)) -> dict:
    entry = _entry_by_id(model_id)
    clf = entry["_model"]
    importances = clf.feature_importances
    sorted_items = sorted(importances.items(), key=lambda x: float(x[1]), reverse=True)[:20]
    return {
        "features": [{"name": str(k), "importance": round(float(v), 6)} for k, v in sorted_items]
    }


# ── SHAP Endpoints ─────────────────────────────────────────────────────────────

def _get_shap_explainer(clf, X_sample: pd.DataFrame):
    import shap
    model_type = getattr(clf, "model_type", "xgboost")
    if model_type in ("xgboost", "lightgbm", "random_forest", "extra_trees", "gradient_boosting"):
        raw_model = clf._model if hasattr(clf, "_model") else clf
        if hasattr(raw_model, "named_steps"):
            raw_model = raw_model.named_steps.get("clf", raw_model)
        return shap.TreeExplainer(raw_model)
    else:
        raw_model = clf._model if hasattr(clf, "_model") else clf
        return shap.LinearExplainer(raw_model, X_sample)


@app.post("/shap-global")
async def get_shap_global(model_id: str | None = Query(None)) -> dict:
    entry = _entry_by_id(model_id)
    clf = entry["_model"]
    X_val = entry.get("_X_val")
    if X_val is None:
        raise HTTPException(status_code=503, detail="Validation data not available — retrain the model")
    try:
        import shap
        feat_cols = clf._feature_cols
        sample = X_val[feat_cols].sample(min(300, len(X_val)), random_state=42)
        explainer = _get_shap_explainer(clf, sample)
        shap_vals = explainer.shap_values(sample)
        shap_arr = np.array(shap_vals[1] if isinstance(shap_vals, list) else shap_vals)
        mean_abs = np.abs(shap_arr).mean(axis=0)
        result = sorted(
            [{"feature": f, "shap_importance": round(float(v), 6)} for f, v in zip(feat_cols, mean_abs)],
            key=lambda x: x["shap_importance"], reverse=True
        )[:20]
        return {"shap_values": result, "sample_size": len(sample)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SHAP computation failed: {e}")


@app.post("/shap-beeswarm")
async def get_shap_beeswarm(model_id: str | None = Query(None), n_samples: int = Query(200), n_features: int = Query(15)) -> dict:
    """
    Returns per-sample SHAP values for the beeswarm plot.
    Output: {features: [...], data: [{feature, shap_value, feature_norm, jitter}]}
    """
    entry = _entry_by_id(model_id)
    clf = entry["_model"]
    X_val = entry.get("_X_val")
    if X_val is None:
        raise HTTPException(status_code=503, detail="Retrain the model to generate beeswarm data")
    try:
        import shap
        feat_cols = clf._feature_cols

        # Get top features by MDI first (to order rows)
        importances = clf.feature_importances
        top_feats = [k for k, _ in sorted(importances.items(), key=lambda x: x[1], reverse=True)][:n_features]
        top_idx = [feat_cols.index(f) for f in top_feats if f in feat_cols]

        sample = X_val[feat_cols].sample(min(n_samples, len(X_val)), random_state=42).reset_index(drop=True)
        explainer = _get_shap_explainer(clf, sample)
        shap_vals = explainer.shap_values(sample)
        shap_arr = np.array(shap_vals[1] if isinstance(shap_vals, list) else shap_vals)  # (n_samples, n_features)

        # Compute global max |SHAP| for x-axis scale
        global_max = float(np.abs(shap_arr[:, top_idx]).max()) if top_idx else 0.1

        data = []
        for fi, feat in enumerate(top_feats):
            if feat not in feat_cols:
                continue
            col_idx = feat_cols.index(feat)
            col_vals = sample[feat].values
            col_min, col_max = float(col_vals.min()), float(col_vals.max())
            rng = col_max - col_min or 1.0

            shap_col = shap_arr[:, col_idx]
            for si in range(len(sample)):
                # Deterministic jitter using sin of sample index
                jitter = float(np.sin(si * 1.7 + fi * 3.1) * 0.35)
                norm = float((col_vals[si] - col_min) / rng)
                data.append({
                    "feature": feat,
                    "feature_idx": fi,
                    "shap_value": round(float(shap_col[si]), 5),
                    "feature_norm": round(norm, 3),  # 0=low (blue), 1=high (red)
                    "jitter": round(jitter, 3),
                })

        return {
            "features": top_feats,
            "global_max_shap": round(global_max, 4),
            "data": data,
            "sample_size": len(sample),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Beeswarm computation failed: {e}")


@app.post("/shap-waterfall")
async def get_shap_waterfall(model_id: str | None = Query(None), sample_idx: int = Query(0)) -> dict:
    """
    Returns waterfall data for a single prediction (base value + per-feature contributions).
    """
    entry = _entry_by_id(model_id)
    clf = entry["_model"]
    X_val = entry.get("_X_val")
    if X_val is None:
        raise HTTPException(status_code=503, detail="Retrain the model to generate waterfall data")
    try:
        import shap
        feat_cols = clf._feature_cols
        idx = min(sample_idx, len(X_val) - 1)
        sample = X_val[feat_cols].iloc[[idx]]

        explainer = _get_shap_explainer(clf, X_val[feat_cols].sample(min(100, len(X_val)), random_state=42))
        shap_vals = explainer.shap_values(sample)
        shap_arr = shap_vals[1][0] if isinstance(shap_vals, list) else shap_vals[0]

        # Base value (expected value of model)
        base_value = float(explainer.expected_value[1] if isinstance(explainer.expected_value, (list, np.ndarray)) else explainer.expected_value)

        # Feature values for this sample
        feat_values = sample.iloc[0].to_dict()

        contributions = sorted(
            [{"feature": f, "shap": round(float(v), 5), "feature_value": round(float(feat_values.get(f, 0)), 4)}
             for f, v in zip(feat_cols, shap_arr)],
            key=lambda x: abs(x["shap"]), reverse=True
        )[:15]

        final_pred = base_value + sum(c["shap"] for c in contributions)

        return {
            "base_value": round(base_value, 4),
            "final_prediction": round(float(final_pred), 4),
            "sample_idx": idx,
            "contributions": contributions,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Waterfall computation failed: {e}")


@app.post("/pdp")
async def get_pdp(feature: str = Query(...), n_points: int = Query(50), model_id: str | None = Query(None)) -> dict:
    entry = _entry_by_id(model_id)
    clf = entry["_model"]
    X_val = entry.get("_X_val")
    if X_val is None:
        raise HTTPException(status_code=503, detail="Train first")
    if feature not in clf._feature_cols:
        raise HTTPException(status_code=400, detail=f"Feature '{feature}' not in model")
    try:
        feat_cols = clf._feature_cols
        X_sample = X_val[feat_cols].sample(min(500, len(X_val)), random_state=42)
        col_vals = X_sample[feature].dropna()
        grid_min, grid_max = float(col_vals.quantile(0.02)), float(col_vals.quantile(0.98))
        grid = np.linspace(grid_min, grid_max, n_points)
        avg_preds = []
        for val in grid:
            X_copy = X_sample.copy()
            X_copy[feature] = val
            proba = clf.predict_proba(X_copy)
            avg_preds.append(round(float(proba[:, 1].mean()), 4))
        return {
            "feature": feature,
            "grid": [round(float(v), 4) for v in grid],
            "avg_prediction": avg_preds,
            "feature_min": round(float(col_vals.min()), 4),
            "feature_max": round(float(col_vals.max()), 4),
            "feature_p50": round(float(col_vals.median()), 4),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDP computation failed: {e}")


@app.post("/explain")
async def explain(req: PredictRequest) -> dict:
    if _classifier is None:
        raise HTTPException(status_code=503, detail="Classifier not loaded")
    try:
        import shap
        X = pd.DataFrame([req.features])
        raw = _classifier._model if hasattr(_classifier, "_model") else _classifier
        explainer = shap.TreeExplainer(raw)
        shap_values = explainer.shap_values(X)
        shap_map = dict(zip(req.features.keys(), shap_values[0].tolist()))
        top_features = sorted(shap_map.items(), key=lambda x: abs(x[1]), reverse=True)[:10]
        return {"ticker": req.ticker, "top_shap_features": dict(top_features)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"SHAP failed: {exc}")
