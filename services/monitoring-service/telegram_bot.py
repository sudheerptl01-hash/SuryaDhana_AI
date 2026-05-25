from __future__ import annotations

from enum import Enum
from typing import Any

from shared.logging import get_logger

logger = get_logger(__name__)


class AlertLevel(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


LEVEL_EMOJI = {
    AlertLevel.CRITICAL: "🔴",
    AlertLevel.WARNING: "🟠",
    AlertLevel.INFO: "🟡",
}


class TelegramAlertBot:
    """Sends structured alerts to a Telegram chat."""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._stub = not (bot_token and chat_id)

    async def send(self, level: AlertLevel, title: str, body: str) -> bool:
        emoji = LEVEL_EMOJI[level]
        message = f"{emoji} *[{level.value}]* {title}\n\n{body}"

        if self._stub:
            logger.info("TELEGRAM STUB", level=level.value, title=title, body=body)
            return True

        try:
            import httpx
            url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json={
                    "chat_id": self._chat_id,
                    "text": message,
                    "parse_mode": "Markdown",
                })
            if resp.status_code != 200:
                logger.error("Telegram send failed", status=resp.status_code, body=resp.text)
                return False
            return True
        except Exception as exc:
            logger.error("Telegram error", error=str(exc))
            return False

    async def send_daily_summary(self, metrics: dict[str, Any]) -> bool:
        lines = [
            f"📊 *Daily Trading Summary*",
            f"Portfolio: ₹{metrics.get('total_value_inr', 0):,.0f}",
            f"P&L: ₹{metrics.get('daily_pnl_inr', 0):+,.0f} ({metrics.get('daily_pnl_pct', 0):+.2%})",
            f"Positions: {metrics.get('num_positions', 0)}/5",
            f"Win rate (30d): {metrics.get('win_rate_30d', 0):.1%}",
            f"Sharpe (30d): {metrics.get('sharpe_30d', 0):.2f}",
            f"Max DD: {metrics.get('max_drawdown_pct', 0):.1%}",
        ]
        return await self.send(AlertLevel.INFO, "Daily Summary", "\n".join(lines))

    async def alert_stop_loss(self, ticker: str, entry: float, exit_price: float, pnl_pct: float) -> bool:
        body = f"Ticker: {ticker}\nEntry: ₹{entry:.2f}\nExit: ₹{exit_price:.2f}\nLoss: {pnl_pct:.2%}"
        return await self.send(AlertLevel.WARNING, f"Stop-Loss Triggered: {ticker}", body)

    async def alert_daily_loss_limit(self, daily_pnl_pct: float) -> bool:
        body = f"Daily P&L: {daily_pnl_pct:.2%}\nTrading halted for today."
        return await self.send(AlertLevel.CRITICAL, "Daily Loss Limit Reached", body)

    async def alert_max_drawdown(self, drawdown_pct: float) -> bool:
        body = f"Max drawdown: {drawdown_pct:.2%}\nEMERGENCY STOP — all trading suspended."
        return await self.send(AlertLevel.CRITICAL, "Max Drawdown Breach", body)
