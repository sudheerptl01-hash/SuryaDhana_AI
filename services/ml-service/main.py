from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.config import get_settings
from shared.logging import configure_logging, get_logger

from models import DirectionClassifier, ReturnRegressor
from training import walk_forward_validation

logger = get_logger(__name__)

_classifier: DirectionClassifier | None = None
_regressor: ReturnRegressor | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global _classifier, _regressor
    settings = get_settings()
    configure_logging("ml-service", settings.log_level)

    clf_path = "models/xgb_classifier_v1.pkl"
    reg_path = "models/xgb_regressor_v1.pkl"

    if Path(clf_path).exists():
        _classifier = DirectionClassifier.load(clf_path)
    if Path(reg_path).exists():
        _regressor = ReturnRegressor.load(reg_path)

    logger.info("ML service started", classifier_loaded=_classifier is not None, regressor_loaded=_regressor is not None)
    yield
    logger.info("ML service stopped")


app = FastAPI(
    title="SuryaDhana — ML Service",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Health ─────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": "ml-service",
        "classifier_ready": _classifier is not None,
        "regressor_ready": _regressor is not None,
    }


# ── Training ───────────────────────────────────────────────────────────────────

class TrainRequest(BaseModel):
    features: list[dict]
    feature_cols: list[str]
    target_direction: str = "label_direction"
    target_return: str = "label_return_pct"
    date_col: str = "date"
    run_walk_forward: bool = True
    save_models: bool = True


class TrainResponse(BaseModel):
    classifier_trained: bool
    regressor_trained: bool
    walk_forward_summary: dict | None
    model_versions: dict[str, str]


@app.post("/train", response_model=TrainResponse)
async def train(req: TrainRequest) -> TrainResponse:
    global _classifier, _regressor

    df = pd.DataFrame(req.features)
    df = df.dropna(subset=req.feature_cols + [req.target_direction, req.target_return])

    if len(df) < 500:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient data: {len(df)} rows. Need at least 500."
        )

    # Time-series split: 80% train, 20% validation (NO SHUFFLE)
    split = int(len(df) * 0.8)
    X_train = df.iloc[:split][req.feature_cols]
    X_val = df.iloc[split:][req.feature_cols]
    y_dir_train = df.iloc[:split][req.target_direction]
    y_dir_val = df.iloc[split:][req.target_direction]
    y_ret_train = df.iloc[:split][req.target_return]
    y_ret_val = df.iloc[split:][req.target_return]

    _classifier = DirectionClassifier()
    _classifier.fit(X_train, y_dir_train, X_val, y_dir_val)

    _regressor = ReturnRegressor()
    _regressor.fit(X_train, y_ret_train, X_val, y_ret_val)

    wf_summary = None
    if req.run_walk_forward:
        wf_result = walk_forward_validation(
            df=df,
            feature_cols=req.feature_cols,
            target_col=req.target_direction,
            date_col=req.date_col,
            model_factory=lambda: DirectionClassifier(),
        )
        wf_summary = wf_result.summary()

    if req.save_models:
        _classifier.save("models/xgb_classifier_v1.pkl")
        _regressor.save("models/xgb_regressor_v1.pkl")

    return TrainResponse(
        classifier_trained=True,
        regressor_trained=True,
        walk_forward_summary=wf_summary,
        model_versions={"classifier": "v1", "regressor": "v1"},
    )


# ── Inference ──────────────────────────────────────────────────────────────────

class PredictRequest(BaseModel):
    ticker: str
    features: dict[str, float]


class PredictResponse(BaseModel):
    ticker: str
    direction: int
    prob_up: float
    confidence: float
    expected_return_pct: float
    is_high_confidence: bool


@app.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest) -> PredictResponse:
    if _classifier is None or _regressor is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Models not loaded. Run /train first."
        )

    direction, prob_up, confidence = _classifier.predict_single(req.features)
    expected_return = _regressor.predict_single(req.features)

    settings = get_settings()
    return PredictResponse(
        ticker=req.ticker,
        direction=direction,
        prob_up=round(prob_up, 4),
        confidence=round(confidence, 4),
        expected_return_pct=round(expected_return, 4),
        is_high_confidence=confidence >= settings.min_signal_confidence,
    )


# ── SHAP explainability ────────────────────────────────────────────────────────

@app.post("/explain")
async def explain(req: PredictRequest) -> dict:
    if _classifier is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Classifier not loaded")

    try:
        import shap  # type: ignore[import]
        X = pd.DataFrame([req.features])
        explainer = shap.TreeExplainer(_classifier._model)
        shap_values = explainer.shap_values(X)
        feature_names = list(req.features.keys())
        shap_map = dict(zip(feature_names, shap_values[0].tolist()))
        top_features = sorted(shap_map.items(), key=lambda x: abs(x[1]), reverse=True)[:10]
        return {"ticker": req.ticker, "top_shap_features": dict(top_features)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"SHAP explanation failed: {exc}")


# ── Feature importance ─────────────────────────────────────────────────────────

@app.get("/feature-importance")
async def feature_importance() -> dict:
    if _classifier is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Classifier not loaded")
    importances = _classifier.feature_importances
    sorted_imp = dict(sorted(importances.items(), key=lambda x: x[1], reverse=True)[:20])
    return {"top_20_features": sorted_imp}
