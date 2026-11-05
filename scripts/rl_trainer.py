#!/usr/bin/env python3
"""
Production RL Training Pipeline for SuryaDhana

Trains a PPO agent on portfolio optimization using signals from DuckDB.
Logs training metrics (reward, Sortino, win rate, portfolio value) in real-time
to a JSON file for frontend visualization.

Usage:
  python scripts/rl_trainer.py \
    --total-timesteps 100000 \
    --n-candidates 15 \
    --max-positions 5 \
    --log-frequency 1000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

# Add parent directory to path for imports (local + Docker)
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "services" / "rl-service"))

try:
    from services.rl_service.agent.ppo_agent import PPOPortfolioAgent
    from services.rl_service.environment.portfolio_env import PortfolioEnv
except ImportError:
    # Try direct imports (Docker/app structure)
    sys.path.insert(0, "/app/services/rl-service")
    from agent.ppo_agent import PPOPortfolioAgent
    from environment.portfolio_env import PortfolioEnv

try:
    from shared.logging import get_logger
except ImportError:
    # Fallback logging if shared not available
    import logging
    def get_logger(name):
        return logging.getLogger(name)

logger = get_logger(__name__)

# Metrics output file (frontend reads this in real-time)
METRICS_FILE = Path(__file__).resolve().parent.parent / "data" / "rl_training_metrics.json"
MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "rl_agent_v1"


class TrainingCallback:
    """Custom callback to log RL training metrics every N steps."""

    def __init__(self, log_frequency: int = 1000, metrics_file: Path = METRICS_FILE):
        self.log_frequency = log_frequency
        self.metrics_file = metrics_file
        self.timestep = 0
        self.episode = 0
        self.episode_rewards: list[float] = []
        self.training_start_time = time.time()
        self.all_metrics: list[dict] = []

        # Initialize metrics file
        self.metrics_file.parent.mkdir(parents=True, exist_ok=True)
        self._write_metrics([])

    def __call__(self, locals_: dict, globals_: dict) -> bool:
        """Called by PPO.learn() every update step."""
        self.timestep = locals_.get("self").num_timesteps or 0

        # Extract reward from done episodes (if available)
        dones = locals_.get("dones")
        rewards = locals_.get("rewards")

        if rewards is not None and isinstance(rewards, np.ndarray):
            for i, done in enumerate(dones):
                if done and i < len(rewards):
                    self.episode_rewards.append(float(rewards[i]))
                    self.episode += 1

        # Log metrics every log_frequency steps
        if self.timestep > 0 and self.timestep % self.log_frequency == 0:
            self._log_metrics()

        return True  # Continue training

    def _log_metrics(self) -> None:
        """Compute and log current training metrics."""
        elapsed_secs = time.time() - self.training_start_time

        # Compute aggregate statistics
        if self.episode_rewards:
            avg_reward = float(np.mean(self.episode_rewards[-100:]))  # Last 100 episodes
            max_reward = float(np.max(self.episode_rewards[-100:]))
            min_reward = float(np.min(self.episode_rewards[-100:]))
            win_rate = float(sum(1 for r in self.episode_rewards[-100:] if r > 0) / max(1, min(100, len(self.episode_rewards))))
        else:
            avg_reward = max_reward = min_reward = win_rate = 0.0

        # Compute Sortino Ratio proxy (excess return / downside deviation)
        if self.episode_rewards and len(self.episode_rewards) > 1:
            returns = np.array(self.episode_rewards)
            excess = returns - np.mean(returns)
            downside = np.sqrt(np.mean(np.minimum(excess, 0) ** 2))
            sortino = (np.mean(excess) / downside * np.sqrt(252)) if downside > 1e-9 else 0.0
        else:
            sortino = 0.0

        # Simulated portfolio value (starting with 1.0)
        cumulative_return = 1.0 + np.sum(self.episode_rewards) / max(1, len(self.episode_rewards)) * 0.01 if self.episode_rewards else 1.0

        metric = {
            "timestamp": datetime.now().isoformat(),
            "timestep": int(self.timestep),
            "episode": int(self.episode),
            "elapsed_secs": float(elapsed_secs),
            "avg_reward": avg_reward,
            "max_reward": max_reward,
            "min_reward": min_reward,
            "sortino_ratio": float(sortino),
            "win_rate": win_rate,
            "portfolio_value": float(cumulative_return),
        }

        self.all_metrics.append(metric)
        self._write_metrics(self.all_metrics)

        logger.info(
            "RL training progress",
            timestep=self.timestep,
            episode=self.episode,
            avg_reward=f"{avg_reward:.4f}",
            sortino=f"{sortino:.2f}",
            win_rate=f"{win_rate:.2%}",
        )

    def _write_metrics(self, metrics: list[dict]) -> None:
        """Write metrics to JSON file (frontend polls this)."""
        try:
            with open(self.metrics_file, "w") as f:
                json.dump(
                    {
                        "status": "training" if self.timestep > 0 else "ready",
                        "last_updated": datetime.now().isoformat(),
                        "metrics": metrics,
                    },
                    f,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"Failed to write metrics: {e}")


def _signal_from(ticker: str, pred: dict | None, feat: dict) -> dict:
    """Build one RL signal from REAL model output + REAL features (never random)."""
    def g(key: str, default: float = 0.0) -> float:
        v = feat.get(key) if feat else None
        try:
            return float(v) if v is not None else default
        except Exception:
            return default

    rsi = g("rsi_14", 50.0)
    if pred:
        prob_up = float(pred.get("prob_up", pred.get("probability_up", 0.5)) or 0.5)
        er = pred.get("expected_return_pct", pred.get("expected_return"))
        expected_return = float(er) if er is not None else g("ret_5d", 0.0)
        confidence = float(pred.get("confidence", abs(prob_up - 0.5) * 2) or 0.0)
    else:
        # Deterministic proxy from real features (used only until a model is trained)
        prob_up = min(max(rsi / 100.0, 0.05), 0.95)
        expected_return = g("ret_5d", 0.0)
        confidence = abs(prob_up - 0.5) * 2

    return {
        "ticker": ticker,
        "date": str(feat.get("date", "")) if feat else "",
        "prob_up": prob_up,
        "confidence": confidence,
        "expected_return_pct": expected_return,
        "rsi_14": rsi,
        "bb_pct": g("bollinger_pctb", 0.5),
        "volume_ratio": g("volume_ratio", 1.0),
        "sma_ratio_20_50": g("sma_ratio_20_50", 1.0),
        "hist_vol_20": g("realized_vol_20d", 20.0),
        "sector_id": int(g("sector_id", 0.0)),
    }


def load_signal_data_from_duckdb(lookback_days: int = 500) -> list[dict]:
    """Load REAL RL training signals from the single source (via data-service HTTP).

    Previously this opened its own DuckDB connection (lock-conflict prone on Docker
    Desktop) and filled every signal field with ``np.random`` — training the agent on
    noise. It now pulls real model predictions from ml-service /batch-predict and the
    real latest feature matrix from data-service /db/latest-features. Synthetic data is
    a last-resort fallback only, with a loud warning."""
    import urllib.request

    data_svc = os.getenv("DATA_SERVICE_URL", "http://data-service:8001")
    ml_svc   = os.getenv("ML_SERVICE_URL",   "http://ml-service:8003")

    def _get_json(url: str, method: str = "GET", body: dict | None = None, timeout: int = 120) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)

    # 1) REAL latest features per ticker (rsi, bollinger, vol, momentum, …)
    feat_by_ticker: dict[str, dict] = {}
    try:
        for r in _get_json(f"{data_svc}/db/latest-features").get("data", []):
            if r.get("ticker"):
                feat_by_ticker[r["ticker"]] = r
    except Exception as e:
        logger.error(f"RL: failed to load latest features from data-service: {e}")

    # 2) REAL model predictions (prob_up / expected_return / confidence)
    preds: list[dict] = []
    try:
        resp = _get_json(f"{ml_svc}/batch-predict", method="POST", body={})
        preds = resp.get("signals", resp.get("predictions", resp.get("data", []))) or []
    except Exception as e:
        logger.warning(f"RL: batch-predict unavailable ({e}); deriving signal proxies from real features")

    signals: list[dict] = []
    if preds:
        for p in preds:
            tk = p.get("ticker")
            if tk:
                signals.append(_signal_from(tk, p, feat_by_ticker.get(tk, {})))
    elif feat_by_ticker:
        for tk, f in feat_by_ticker.items():
            signals.append(_signal_from(tk, None, f))

    if not signals:
        logger.error("RL: no REAL signals available — train an ML model and run Phase 3 first. "
                     "Falling back to SYNTHETIC data (agent will not learn real edge).")
        return _generate_synthetic_signals(n_signals=500, n_stocks=15)

    logger.info(f"Loaded {len(signals)} REAL RL signals "
                f"(model_preds={len(preds)}, feature_rows={len(feat_by_ticker)})")
    return signals


def _generate_synthetic_signals(n_signals: int = 500, n_stocks: int = 15) -> list[dict]:
    """Generate synthetic signal data for testing."""
    signals = []
    tickers = [f"STOCK{i:02d}" for i in range(n_stocks)]

    for _ in range(n_signals):
        for ticker in tickers:
            signal = {
                "ticker": ticker,
                "date": datetime.now().isoformat(),
                "prob_up": np.random.uniform(0.3, 0.7),
                "confidence": np.random.uniform(0.5, 0.95),
                "expected_return_pct": np.random.uniform(-2, 5),
                "rsi_14": np.random.uniform(20, 80),
                "bb_pct": np.random.uniform(0, 1),
                "volume_ratio": np.random.uniform(0.8, 1.5),
                "sma_ratio_20_50": np.random.uniform(0.95, 1.05),
                "hist_vol_20": np.random.uniform(15, 35),
                "sector_id": np.random.randint(0, 11),
            }
            signals.append(signal)

    logger.info(f"Generated {len(signals)} synthetic signals")
    return signals


def train_ppo_agent(
    total_timesteps: int = 100_000,
    n_candidates: int = 15,
    max_positions: int = 5,
    log_frequency: int = 1000,
) -> None:
    """Train the PPO agent with custom metrics logging."""
    logger.info(
        "Starting RL training",
        timesteps=total_timesteps,
        candidates=n_candidates,
        max_positions=max_positions,
    )

    # Load signal data
    signals = load_signal_data_from_duckdb()

    # Chunk signals into daily batches (for simulation)
    signal_batches = [signals[i : i + n_candidates] for i in range(0, len(signals), n_candidates)]
    if not signal_batches:
        signal_batches = [signals]

    # Create agent
    agent = PPOPortfolioAgent(
        n_candidates=n_candidates,
        max_positions=max_positions,
        total_timesteps=total_timesteps,
    )

    # Create custom callback for logging
    callback = TrainingCallback(log_frequency=log_frequency)

    # Train with callback
    try:
        from stable_baselines3 import PPO

        env = PortfolioEnv(
            signals_data=signal_batches,
            n_candidates=n_candidates,
            max_positions=max_positions,
        )

        model = PPO(
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
            verbose=1,
        )

        # Monkey-patch the model's learn method to call our callback
        original_learn = model.learn
        def learn_with_callback(*args, **kwargs):
            return original_learn(*args, callback=callback, **kwargs)

        model.learn(total_timesteps=total_timesteps)
        agent._model = model

    except ImportError:
        logger.error("stable-baselines3 not installed. Install via: pip install stable-baselines3")
        raise

    # Save trained model
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    agent.save(str(MODEL_PATH))
    logger.info(f"Model saved to {MODEL_PATH}")

    # Finalize metrics
    callback._write_metrics(callback.all_metrics)
    logger.info(f"Training complete. Metrics saved to {METRICS_FILE}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train RL agent for portfolio optimization")
    parser.add_argument("--total-timesteps", type=int, default=100_000, help="Total training timesteps")
    parser.add_argument("--n-candidates", type=int, default=15, help="Number of candidate stocks")
    parser.add_argument("--max-positions", type=int, default=5, help="Max portfolio positions")
    parser.add_argument("--log-frequency", type=int, default=1000, help="Log metrics every N steps")

    args = parser.parse_args()

    train_ppo_agent(
        total_timesteps=args.total_timesteps,
        n_candidates=args.n_candidates,
        max_positions=args.max_positions,
        log_frequency=args.log_frequency,
    )


if __name__ == "__main__":
    main()
