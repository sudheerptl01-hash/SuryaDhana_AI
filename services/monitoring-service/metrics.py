from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry

registry = CollectorRegistry()

# ── Trading metrics ────────────────────────────────────────────────────────────
portfolio_value = Gauge("suryadhana_portfolio_value_inr", "Total portfolio value in INR", registry=registry)
daily_pnl = Gauge("suryadhana_daily_pnl_inr", "Daily P&L in INR", registry=registry)
daily_pnl_pct = Gauge("suryadhana_daily_pnl_pct", "Daily P&L as a fraction", registry=registry)
open_positions = Gauge("suryadhana_open_positions", "Number of open positions", registry=registry)
win_rate = Gauge("suryadhana_win_rate", "30-day rolling win rate", registry=registry)
sharpe_ratio = Gauge("suryadhana_sharpe_ratio", "30-day rolling Sharpe ratio", registry=registry)
max_drawdown = Gauge("suryadhana_max_drawdown_pct", "Current max drawdown as a fraction", registry=registry)

# ── Orders ─────────────────────────────────────────────────────────────────────
orders_placed = Counter("suryadhana_orders_placed_total", "Total orders placed", ["side"], registry=registry)
orders_filled = Counter("suryadhana_orders_filled_total", "Total orders filled", ["side"], registry=registry)
orders_rejected = Counter("suryadhana_orders_rejected_total", "Total orders rejected", registry=registry)
stop_losses_hit = Counter("suryadhana_stop_losses_total", "Total stop-loss exits", registry=registry)
take_profits_hit = Counter("suryadhana_take_profits_total", "Total take-profit exits", registry=registry)
time_stops_hit = Counter("suryadhana_time_stops_total", "Total time-stop exits", registry=registry)

# ── ML / signals ───────────────────────────────────────────────────────────────
signals_generated = Counter("suryadhana_signals_generated_total", "Total signals generated", registry=registry)
high_confidence_signals = Gauge("suryadhana_high_confidence_signals", "High-confidence signals in last batch", registry=registry)
model_accuracy = Gauge("suryadhana_model_accuracy", "Latest model accuracy on recent data", registry=registry)

# ── Data freshness ─────────────────────────────────────────────────────────────
data_lag_seconds = Gauge("suryadhana_data_lag_seconds", "Seconds since last data update", registry=registry)

# ── Latency ────────────────────────────────────────────────────────────────────
signal_generation_latency = Histogram(
    "suryadhana_signal_generation_seconds",
    "Signal generation pipeline latency",
    buckets=[1, 5, 10, 30, 60, 120],
    registry=registry,
)
order_placement_latency = Histogram(
    "suryadhana_order_placement_seconds",
    "Order placement latency",
    buckets=[0.1, 0.5, 1, 2, 5],
    registry=registry,
)
