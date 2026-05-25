from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from shared.logging import get_logger

logger = get_logger(__name__)

DEFAULT_PARAMS: dict[str, Any] = {
    "n_estimators": 300,
    "max_depth": 5,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 5,
    "gamma": 0.1,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "scale_pos_weight": 1,
    "random_state": 42,
    "n_jobs": -1,
    "eval_metric": "logloss",
    "early_stopping_rounds": 20,
}


class DirectionClassifier:
    """
    XGBoost classifier predicting 5-day stock direction (UP=1, DOWN=0).

    Outputs probability of UP — confidence = |prob_up - 0.5|.
    Target accuracy: 55%+ on walk-forward validation.
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self._params = {**DEFAULT_PARAMS, **(params or {})}
        self._model: XGBClassifier | None = None
        self._feature_cols: list[str] = []
        self._version: str = "untrained"

    def fit(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame | None = None,
        y_val: pd.Series | None = None,
    ) -> None:
        self._feature_cols = list(X_train.columns)

        params = {k: v for k, v in self._params.items() if k != "early_stopping_rounds"}
        early_stop = self._params.get("early_stopping_rounds", 20)

        self._model = XGBClassifier(**params)

        eval_set = [(X_val, y_val)] if X_val is not None and y_val is not None else None

        fit_kwargs: dict[str, Any] = {"verbose": False}
        if eval_set:
            fit_kwargs["eval_set"] = eval_set
            fit_kwargs["early_stopping_rounds"] = early_stop

        self._model.fit(X_train, y_train, **fit_kwargs)
        logger.info("DirectionClassifier trained", features=len(self._feature_cols))

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        self._require_fitted()
        return self._model.predict_proba(X[self._feature_cols])  # type: ignore[union-attr]

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        proba = self.predict_proba(X)
        return (proba[:, 1] >= 0.5).astype(int)

    def predict_single(self, feature_row: dict[str, float]) -> tuple[int, float, float]:
        """Returns (direction, prob_up, confidence)."""
        X = pd.DataFrame([feature_row])[self._feature_cols]
        proba = self.predict_proba(X)[0]
        prob_up = float(proba[1])
        confidence = abs(prob_up - 0.5)
        direction = 1 if prob_up >= 0.5 else 0
        return direction, prob_up, confidence

    @property
    def feature_importances(self) -> dict[str, float]:
        self._require_fitted()
        return dict(zip(self._feature_cols, self._model.feature_importances_))  # type: ignore[union-attr]

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"model": self._model, "feature_cols": self._feature_cols, "version": self._version}, f)
        logger.info("DirectionClassifier saved", path=path)

    @classmethod
    def load(cls, path: str) -> "DirectionClassifier":
        with open(path, "rb") as f:
            data = pickle.load(f)
        obj = cls()
        obj._model = data["model"]
        obj._feature_cols = data["feature_cols"]
        obj._version = data.get("version", "unknown")
        logger.info("DirectionClassifier loaded", path=path)
        return obj

    def _require_fitted(self) -> None:
        if self._model is None:
            raise RuntimeError("Model is not trained. Call fit() first.")
