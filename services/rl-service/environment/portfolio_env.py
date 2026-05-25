from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from shared.logging import get_logger

logger = get_logger(__name__)

MAX_POSITIONS = 5
HOLDING_DAYS = 5
TRANSACTION_COST_PCT = 0.0015  # 0.15% total round-trip costs


class PortfolioEnv(gym.Env):
    """
    Custom Gymnasium environment for portfolio optimization.

    The RL agent receives a batch of ML signals and must decide:
    - Which 5 stocks to select from the top-15 candidates
    - How to allocate capital across selected stocks (within constraints)

    Observation space: signal features for top-15 candidates
    Action space: allocation weights for each candidate slot (continuous)

    Reward: risk-adjusted return (Sharpe-like) over the holding period,
            penalised for excessive sector concentration and correlation.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        signals_data: list[dict],
        n_candidates: int = 15,
        max_positions: int = MAX_POSITIONS,
        transaction_cost: float = TRANSACTION_COST_PCT,
    ) -> None:
        super().__init__()
        self.n_candidates = n_candidates
        self.max_positions = max_positions
        self.transaction_cost = transaction_cost
        self._signals_data = signals_data
        self._current_signals: list[dict] = []
        self._step_idx = 0

        # Each candidate has: [prob_up, confidence, expected_return, rsi_14, bb_pct,
        #                       volume_ratio, sma_ratio_20_50, sector_one_hot(11)]
        self._obs_features_per_stock = 8 + 11  # 11 NSE broad sectors
        obs_dim = n_candidates * self._obs_features_per_stock

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(obs_dim,),
            dtype=np.float32,
        )

        # Action: allocation weight per candidate (agent can set 0 = don't select)
        self.action_space = spaces.Box(
            low=0.0, high=1.0,
            shape=(n_candidates,),
            dtype=np.float32,
        )

    def reset(self, *, seed: int | None = None, options: dict | None = None) -> tuple[np.ndarray, dict]:
        super().reset(seed=seed)
        self._step_idx = 0
        self._current_signals = self._sample_signals()
        obs = self._build_observation(self._current_signals)
        return obs, {}

    def step(self, action: np.ndarray) -> tuple[np.ndarray, float, bool, bool, dict]:
        # Normalise action to weights (sum to 1, only top-max_positions)
        weights = self._action_to_weights(action)

        # Simulate 5-day returns using signal expected_return_pct as proxy
        reward = self._compute_reward(weights)

        self._step_idx += 1
        done = self._step_idx >= len(self._signals_data) - 1

        if not done:
            self._current_signals = self._sample_signals()
        obs = self._build_observation(self._current_signals)

        info = {"weights": weights.tolist(), "step": self._step_idx}
        return obs, float(reward), done, False, info

    def _sample_signals(self) -> list[dict]:
        """Sample top-n_candidates signals from the dataset for the current step."""
        idx = self._step_idx % max(1, len(self._signals_data))
        return self._signals_data[idx][:self.n_candidates] if isinstance(self._signals_data[idx], list) else self._signals_data[:self.n_candidates]

    def _build_observation(self, signals: list[dict]) -> np.ndarray:
        obs_parts = []
        for i in range(self.n_candidates):
            if i < len(signals):
                s = signals[i]
                stock_obs = [
                    float(s.get("prob_up", 0.5)),
                    float(s.get("confidence", 0.0)),
                    float(s.get("expected_return_pct", 0.0)) / 10.0,  # normalise
                    float(s.get("rsi_14", 50.0)) / 100.0,
                    float(s.get("bb_pct", 0.5)),
                    float(s.get("volume_ratio", 1.0)) / 3.0,
                    float(s.get("sma_ratio_20_50", 1.0)) - 1.0,
                    float(s.get("hist_vol_20", 20.0)) / 100.0,
                ]
                # Sector one-hot (11 broad sectors)
                sector_id = int(s.get("sector_id", 0)) % 11
                sector_oh = [0.0] * 11
                sector_oh[sector_id] = 1.0
                obs_parts.extend(stock_obs + sector_oh)
            else:
                obs_parts.extend([0.0] * self._obs_features_per_stock)

        return np.array(obs_parts, dtype=np.float32)

    def _action_to_weights(self, action: np.ndarray) -> np.ndarray:
        """Convert raw action to valid portfolio weights (select top-5, normalise)."""
        action = np.clip(action, 0, 1)
        # Select top max_positions slots
        top_indices = np.argsort(action)[::-1][:self.max_positions]
        weights = np.zeros(self.n_candidates)
        selected_vals = action[top_indices]
        total = selected_vals.sum()
        if total > 0:
            weights[top_indices] = selected_vals / total
        else:
            # Equal weight fallback
            weights[top_indices] = 1.0 / self.max_positions
        return weights

    def _compute_reward(self, weights: np.ndarray) -> float:
        """
        Reward = weighted average expected return (net of costs)
               - sector concentration penalty
               - correlation penalty (proxied by sector overlap)
        """
        signals = self._current_signals
        selected_mask = weights > 0

        if not any(selected_mask):
            return -0.1  # penalty for holding no positions

        # Base return
        returns = np.array([
            float(signals[i].get("expected_return_pct", 0.0)) if i < len(signals) else 0.0
            for i in range(self.n_candidates)
        ])
        net_returns = returns - (self.transaction_cost * 100)  # convert to %
        weighted_return = float(np.dot(weights, net_returns))

        # Sector concentration penalty
        sector_weights: dict[int, float] = {}
        for i, w in enumerate(weights):
            if w > 0 and i < len(signals):
                sec = int(signals[i].get("sector_id", 0)) % 11
                sector_weights[sec] = sector_weights.get(sec, 0.0) + w
        max_sector = max(sector_weights.values()) if sector_weights else 0.0
        sector_penalty = max(0.0, max_sector - 0.40) * 2.0  # penalise > 40% concentration

        # Risk: use confidence variance as proxy
        confidences = np.array([
            float(signals[i].get("confidence", 0.0)) if i < len(signals) else 0.0
            for i in range(self.n_candidates)
        ])
        weighted_confidence = float(np.dot(weights, confidences))
        risk_adjusted = weighted_return * (1 + weighted_confidence)

        reward = risk_adjusted - sector_penalty
        return reward
