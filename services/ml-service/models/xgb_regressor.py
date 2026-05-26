from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from shared.logging import get_logger

logger = get_logger(__name__)

DEFAULT_PARAMS: dict[str, Any] = {
    "n_estimators": 300,
    "max_depth": 4,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 5,
    "gamma": 0.1,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "random_state": 42,
    "n_jobs": -1,
    "eval_metric": "rmse",
    "early_stopping_rounds": 20,
}


class ReturnRegressor:
    """
    XGBoost regressor predicting 5-day forward return %.
    Used alongside DirectionClassifier to estimate magnitude.
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self._params = {**DEFAULT_PARAMS, **(params or {})}
        self._model: XGBRegressor | None = None
        self._feature_cols: list[str] = []
        self._version: str = "untrained"

    def fit(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame | None = None,
        y_val: pd.Series | None = None,
    ) -> None:
        # ── Input validation (Pillar 4) ──────────────────────────────────────
        if X_train.empty or len(y_train) == 0:
            raise ValueError(f"Empty training data: X_train shape {X_train.shape}")

        if X_train.shape[0] != len(y_train):
            raise ValueError(
                f"Shape mismatch: X_train {X_train.shape[0]} rows vs y_train {len(y_train)} rows"
            )

        X_train = X_train.replace([np.inf, -np.inf], np.nan)
        if X_train.isna().any().any():
            logger.warning("NaN/inf in regressor training data — filling with 0")
            X_train = X_train.fillna(0)

        if y_train.isna().any() or np.isinf(y_train).any():
            raise ValueError("Target (return) series contains NaN or inf values — check label generation")

        if X_val is not None and y_val is not None:
            X_val = X_val.replace([np.inf, -np.inf], np.nan).fillna(0)
        # ─────────────────────────────────────────────────────────────────────

        self._feature_cols = list(X_train.columns)

        params = {k: v for k, v in self._params.items() if k != "early_stopping_rounds"}
        early_stop = self._params.get("early_stopping_rounds", 20)

        eval_set_exists = X_val is not None and y_val is not None

        # early_stopping_rounds moved to constructor in XGBoost ≥2.0
        if eval_set_exists:
            self._model = XGBRegressor(**params, early_stopping_rounds=early_stop)
        else:
            self._model = XGBRegressor(**params)

        fit_kwargs: dict[str, Any] = {"verbose": False}
        if eval_set_exists:
            fit_kwargs["eval_set"] = [(X_val, y_val)]

        self._model.fit(X_train, y_train, **fit_kwargs)
        logger.info("ReturnRegressor trained", features=len(self._feature_cols))

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        self._require_fitted()
        return self._model.predict(X[self._feature_cols])  # type: ignore[union-attr]

    def predict_single(self, feature_row: dict[str, float]) -> float:
        X = pd.DataFrame([feature_row])[self._feature_cols]
        return float(self.predict(X)[0])

    @property
    def feature_importances(self) -> dict[str, float]:
        self._require_fitted()
        return dict(zip(self._feature_cols, self._model.feature_importances_))  # type: ignore[union-attr]

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"model": self._model, "feature_cols": self._feature_cols, "version": self._version}, f)
        logger.info("ReturnRegressor saved", path=path)

    @classmethod
    def load(cls, path: str) -> "ReturnRegressor":
        with open(path, "rb") as f:
            data = pickle.load(f)
        obj = cls()
        obj._model = data["model"]
        obj._feature_cols = data["feature_cols"]
        obj._version = data.get("version", "unknown")
        logger.info("ReturnRegressor loaded", path=path)
        return obj

    def _require_fitted(self) -> None:
        if self._model is None:
            raise RuntimeError("Model is not trained. Call fit() first.")
