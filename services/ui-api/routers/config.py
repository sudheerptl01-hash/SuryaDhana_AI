"""Trading configuration — reads from .env, never hardcoded."""
import os
from fastapi import APIRouter

router = APIRouter()


@router.get("/trading")
async def get_trading_config():
    return {
        "max_positions": int(os.getenv("MAX_PORTFOLIO_POSITIONS", "5")),
        "holding_period_days": int(os.getenv("HOLDING_PERIOD_DAYS", "5")),
        "stop_loss_pct": float(os.getenv("STOP_LOSS_PCT", "0.02")),
        "take_profit_multiplier": float(os.getenv("TAKE_PROFIT_MULTIPLIER", "1.0")),
        "max_position_pct": float(os.getenv("MAX_POSITION_PCT", "0.15")),
        "max_sector_pct": float(os.getenv("MAX_SECTOR_PCT", "0.40")),
        "daily_loss_limit_pct": float(os.getenv("DAILY_LOSS_LIMIT_PCT", "0.02")),
        "max_drawdown_pct": float(os.getenv("MAX_DRAWDOWN_PCT", "0.20")),
        "min_signal_confidence": float(os.getenv("MIN_SIGNAL_CONFIDENCE", "0.12")),
        "prediction_horizon_days": int(os.getenv("PREDICTION_HORIZON_DAYS", "5")),
        "historical_years": int(os.getenv("HISTORICAL_YEARS", "5")),
        "stock_universe": os.getenv("STOCK_UNIVERSE_PATH", "data/NSE_1000_MIDCAP_500.csv"),
    }


# ── setup checklist (BRIEF): what still needs the owner, with no secret ever returned ─────────────────────────────

def _repo_root():
    from pathlib import Path
    here = Path(__file__).resolve()
    for p in (here.parents[3], Path("/app")):
        if (p / ".env").exists() or (p / "data").is_dir():
            return p
    return here.parents[3]


def _env_file(root) -> dict:
    out = {}
    try:
        for line in (root / ".env").read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def setup_checks(env: dict, keychain_totp: bool, block: dict | None, last_login: dict | None,
                 autostart: bool | None = None) -> list[dict]:
    """Pure: the owner-only setup items, each ok / not ok with the one-line fix."""
    checks = []
    if autostart is not None:
        checks.append({"key": "autostart", "ok": autostart, "title": "Start after a restart",
                       "detail": "launch agent installed" if autostart else "the stack does not start by itself after the Mac restarts (morning jobs get missed)",
                       "fix": "scripts/install_autostart.sh (once; --remove to undo)"})
    tg = bool(env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"))
    checks.append({"key": "telegram", "ok": tg, "title": "Telegram alerts",
                   "detail": "configured" if tg else "not set: alerts only reach this Mac as notifications",
                   "fix": "Create a bot with @BotFather, put TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env, restart master-controller"})
    totp = bool(env.get("ICICI_TOTP_SECRET")) or keychain_totp
    checks.append({"key": "totp", "ok": totp, "title": "ICICI unattended login (TOTP)",
                   "detail": "authenticator secret stored" if totp else "no TOTP secret: the 08:00 login cannot finish by itself",
                   "fix": "security add-generic-password -U -s suryadhana -a ICICI_TOTP_SECRET -w"})
    if block:
        checks.append({"key": "icici_credentials", "ok": False, "title": "ICICI user ID / password",
                       "detail": f"auto-login stopped after: {block.get('reason', 'rejected')} (retries blocked to avoid an account lock)",
                       "fix": "Correct ICICI_CLIENT_ID / ICICI_PASSWORD in .env: the block lifts as soon as the credentials change, the next 08:00 run logs in by itself (or log in now on the Broker tab)"})
    elif last_login:
        ok = last_login.get("status") in ("valid", "refreshed")
        checks.append({"key": "icici_credentials", "ok": ok, "title": "ICICI daily session",
                       "detail": f"last check {str(last_login.get('at', ''))[:16]}: {last_login.get('status')} ({str(last_login.get('detail', ''))[:80]})",
                       "fix": "" if ok else "Log in once from the Broker tab, or run scripts/daily_session_refresh.py"})
    return checks


@router.get("/setup-status")
def setup_status():
    """Owner setup checklist for BRIEF. Booleans and reasons only: no credential or token is ever returned."""
    import json
    import subprocess
    import sys as _sys
    root = _repo_root()
    env = {**os.environ, **_env_file(root)}
    keychain = False
    if not env.get("ICICI_TOTP_SECRET") and _sys.platform == "darwin":
        try:
            r = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", "suryadhana", "-a", "ICICI_TOTP_SECRET"],
                               capture_output=True, text=True, timeout=5)
            keychain = r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass

    def read(name):
        try:
            return json.loads((root / name).read_text())
        except (OSError, ValueError):
            return None
    from pathlib import Path as _P
    autostart = (_P.home() / "Library" / "LaunchAgents" / "com.suryadhana.stack.plist").exists() if _sys.platform == "darwin" else None
    return {"checks": setup_checks(env, keychain, read(".icici_login_block.json"), read(".session_cache.json"), autostart)}
