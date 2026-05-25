from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from shared.logging import get_logger
from environment import PortfolioEnv

logger = get_logger(__name__)


class PPOPortfolioAgent:
    """
    Stable-Baselines3 PPO agent for portfolio optimization.

    Learns to select the best 5 stocks from ML signals and allocate
    capital to maximise risk-adjusted returns (Sharpe ratio proxy).
    """

    def __init__(
        self,
        n_candidates: int = 15,
        max_positions: int = 5,
        total_timesteps: int = 100_000,
    ) -> None:
        self.n_candidates = n_candidates
        self.max_positions = max_positions
        self.total_timesteps = total_timesteps
        self._model: Any = None

    def train(self, signals_data: list[dict]) -> None:
        from stable_baselines3 import PPO  # type: ignore[import]
        from stable_baselines3.common.vec_env import DummyVecEnv  # type: ignore[import]

        env = DummyVecEnv([
            lambda: PortfolioEnv(
                signals_data=signals_data,
                n_candidates=self.n_candidates,
                max_positions=self.max_positions,
            )
        ])

        self._model = PPO(
            policy="MlpPolicy",
            env=env,
            learning_rate=3e-4,
            n_steps=2048,
            batch_size=64,
            n_epochs=10,
            gamma=0.99,
            gae_lambda=0.95,
            clip_range=0.2,
            ent_coef=0.01,
            verbose=0,
        )

        self._model.learn(total_timesteps=self.total_timesteps)
        logger.info("PPO agent trained", timesteps=self.total_timesteps)

    def optimize(self, signals: list[dict]) -> dict[str, float]:
        """
        Given a list of ML signals, returns portfolio allocation.

        Returns: {ticker: allocation_pct} for selected stocks.
        """
        if self._model is None:
            return self._fallback_allocation(signals)

        env = PortfolioEnv(
            signals_data=[signals],
            n_candidates=self.n_candidates,
            max_positions=self.max_positions,
        )
        obs, _ = env.reset()
        action, _ = self._model.predict(obs, deterministic=True)
        weights = env._action_to_weights(action)

        result = {}
        for i, w in enumerate(weights):
            if w > 0 and i < len(signals):
                ticker = signals[i].get("ticker", f"STOCK_{i}")
                result[ticker] = round(float(w) * 100, 2)  # convert to %

        logger.info("RL allocation", selected=list(result.keys()))
        return result

    def _fallback_allocation(self, signals: list[dict]) -> dict[str, float]:
        """Equal-weight fallback when model is not trained."""
        top = signals[:self.max_positions]
        weight_pct = round(100.0 / len(top), 2) if top else 0.0
        return {s["ticker"]: weight_pct for s in top if "ticker" in s}

    def save(self, path: str) -> None:
        if self._model is None:
            raise RuntimeError("Agent is not trained. Call train() first.")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._model.save(path)
        logger.info("PPO agent saved", path=path)

    @classmethod
    def load(cls, path: str, n_candidates: int = 15, max_positions: int = 5) -> "PPOPortfolioAgent":
        from stable_baselines3 import PPO  # type: ignore[import]
        obj = cls(n_candidates=n_candidates, max_positions=max_positions)
        obj._model = PPO.load(path)
        logger.info("PPO agent loaded", path=path)
        return obj
