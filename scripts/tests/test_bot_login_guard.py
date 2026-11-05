"""Telegram /login and /password guard (scripts/master_controller): never burn ICICI attempts on rejected credentials."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import daily_session_refresh as dsr  # noqa: E402
import master_controller as mc  # noqa: E402


def _setup(monkeypatch, tmp_path, user="AB1234", pw="secret1", rejected=True):
    block = tmp_path / ".icici_login_block.json"
    if rejected:
        block.write_text(json.dumps({"fingerprint": dsr.credential_fingerprint(user, pw), "reason": "Invalid Credentials"}))
    monkeypatch.setattr(dsr, "BLOCK_FILE", block)
    monkeypatch.setattr(mc, "_ROOT", tmp_path)
    monkeypatch.setattr(mc, "_env_file_value", lambda k: {"ICICI_CLIENT_ID": user, "ICICI_PASSWORD": pw}[k])
    monkeypatch.delenv("ICICI_PASSWORD", raising=False)
    started = []
    monkeypatch.setattr(mc, "_run_session_refresh", lambda *a, **k: started.append(a))   # a real login must never start
    monkeypatch.setattr(mc, "_env_set", lambda k, v: started.append(("set", k)))
    return started


def test_login_refuses_credentials_icici_rejected(monkeypatch, tmp_path):
    started = _setup(monkeypatch, tmp_path)
    reply = asyncio.run(mc._bot_login([]))
    assert reply.startswith("⛔") and "/login anyway" in reply and not started


def test_same_rejected_password_is_not_reported_as_updated(monkeypatch, tmp_path):
    started = _setup(monkeypatch, tmp_path)
    reply = asyncio.run(mc._bot_password(["secret1"]))
    assert "already saved" in reply and "rejected" in reply and not started
    reply = asyncio.run(mc._bot_password(["new-one"]))
    assert "updated" in reply and started == [("set", "ICICI_PASSWORD")]


def test_only_one_login_at_a_time(monkeypatch, tmp_path):
    started = _setup(monkeypatch, tmp_path, rejected=False)

    async def go():
        async with mc._get_lock("icici_session_refresh"):          # the scheduled login is running
            assert mc._login_running()
            return await mc._bot_login([])
    assert "already running" in asyncio.run(go()) and not started


def test_startup_check_does_not_text_again_right_after_an_ask(monkeypatch, tmp_path):
    import time
    last = tmp_path / "last_ask.json"
    monkeypatch.setattr(dsr, "OTP_LAST_ASK", last)
    assert dsr.minutes_since_otp_ask() is None                            # never asked: the start-up check may log in
    last.write_text(json.dumps({"at": time.time() - 120}))
    assert 1.9 < dsr.minutes_since_otp_ask() < 2.1                          # asked 2 min ago: --quiet-minutes 30 skips
    # every SMS ask records itself, and survives the clean-up of the request / reply files
    monkeypatch.setattr(dsr, "OTP_REQUEST", tmp_path / "req.json")
    monkeypatch.setattr(dsr, "OTP_REPLY", tmp_path / "otp.json")
    monkeypatch.setattr(dsr, "telegram_send", lambda env, text: True)
    t = [5000.0]
    dsr.telegram_otp_provider({}, wait_s=2, clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s))("panel")
    assert json.loads(last.read_text())["at"] == 5000.0 and not (tmp_path / "req.json").exists()


def test_live_prices_reconnect_after_a_failed_push(monkeypatch):
    # 14 Oct: the token reached data-service but its one connect failed; quotes stayed off until reconnected
    calls = []

    class Resp:
        def __init__(self, body):
            self._b = body

        def json(self):
            return self._b

    class Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            calls.append(("status", url))
            return Resp({"connected": False})

        async def post(self, url, json=None):
            calls.append(("configure", url))
            return Resp({"connected": len([c for c in calls if c[0] == "configure"]) >= 2})

    async def no_sleep(s):
        return None
    monkeypatch.setattr(mc.httpx, "AsyncClient", Client)
    monkeypatch.setattr(mc.asyncio, "sleep", no_sleep)
    assert asyncio.run(mc._ensure_live_prices()) is True
    assert [c[0] for c in calls] == ["status", "configure", "status", "configure"]
