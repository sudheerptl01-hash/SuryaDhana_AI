"""Telegram bot (scripts/telegram_bot.py) and the ICICI OTP hand-off (scripts/daily_session_refresh.py)."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import daily_session_refresh as dsr  # noqa: E402
import telegram_bot as tb  # noqa: E402


def _files(monkeypatch, tmp_path):
    req, rep = tmp_path / "req.json", tmp_path / "otp.json"
    for mod in (tb, dsr):
        monkeypatch.setattr(mod, "OTP_REQUEST", req)
        monkeypatch.setattr(mod, "OTP_REPLY", rep)
    # telegram_otp_provider also stamps the "last OTP ask" file: the live one makes the next start-up login check
    # skip for 30 min (--quiet-minutes), so it must never be written by a test (desktop review P16)
    monkeypatch.setattr(dsr, "OTP_LAST_ASK", tmp_path / "otp_last_ask.json")
    return req, rep


def test_the_otp_tests_never_touch_the_live_files(monkeypatch, tmp_path):
    """Every OTP_* path of both modules points into tmp_path once _files() ran (a new OTP file must be added there)."""
    _files(monkeypatch, tmp_path)
    paths = {f"{mod.__name__}.{name}": getattr(mod, name) for mod in (tb, dsr) for name in dir(mod)
             if name.startswith("OTP_") and isinstance(getattr(mod, name), Path)}
    assert paths and all(tmp_path in p.parents for p in paths.values()), paths


def test_otp_handoff_end_to_end(monkeypatch, tmp_path):
    req, rep = _files(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(dsr, "telegram_send", lambda env, text: sent.append(text) or True)
    import time
    t0 = time.time()
    t = [t0]                            # the bot checks the request against the real clock, so start from it

    def sleep(s):                       # while the login waits, you reply "482913" on Telegram
        t[0] += s
        if t[0] >= t0 + 3 and not rep.exists():
            assert tb.otp_pending(now=t[0])
            reply = asyncio.run(tb.handle("482913", None, None, {}))
            assert reply.startswith("Got the OTP")

    provide = dsr.telegram_otp_provider({"ICICI_MOBILE": "9876543286"}, wait_s=60, clock=lambda: t[0], sleep=sleep)
    assert provide("OTP has been sent to your registered mobile number") == "482913"
    assert "ending 86" in sent[0] and not req.exists() and not rep.exists()      # both files cleaned up


def test_otp_times_out_and_says_so(monkeypatch, tmp_path):
    _files(monkeypatch, tmp_path)
    sent = []
    monkeypatch.setattr(dsr, "telegram_send", lambda env, text: sent.append(text) or True)
    t = [0.0]
    provide = dsr.telegram_otp_provider({}, wait_s=10, clock=lambda: t[0], sleep=lambda s: t.__setitem__(0, t[0] + s))
    assert provide("panel") is None and "No OTP received" in sent[-1]


def test_a_code_with_no_login_waiting_is_refused(monkeypatch, tmp_path):
    _files(monkeypatch, tmp_path)
    assert "No ICICI login is waiting" in asyncio.run(tb.handle("123456", None, None, {}))
    assert "No ICICI login is waiting" in asyncio.run(tb.handle("/otp 123456", None, None, {}))


def test_help_lists_every_command_and_parse_alert():
    h = tb.help_text()
    assert all(f"/{c}" in h for c, _, _ in tb.COMMANDS)
    assert tb.parse_alert(["tcs", "above", "2400"]) == ("TCS", {"above": 2400.0})
    assert tb.parse_alert(["TCS", "move", "3%"]) == ("TCS", {"move": 3.0})
    assert tb.parse_alert(["TCS", "sideways", "3"]) is None and tb.parse_alert(["TCS", "above"]) is None


def test_formatters_escape_and_shape():
    pos = {"positions": [], "last_known": {"as_of": "2026-10-12T18:30:00", "positions": [
        {"symbol": "CUPID", "quantity": 200, "buy_price": 355.5}, {"symbol": "M&M", "quantity": 1, "buy_price": 100}]}}
    quotes = {"CUPID.NS": {"price": 353.1, "change_pct": -2.4}, "M&M.NS": {"price": 110.0, "change_pct": 1.0}}
    flags = {"CUPID": {"chips": [{"code": "ASM LT 1", "why": "x"}]}}
    out = tb.fmt_book(pos, quotes, flags)
    assert "last known book" in out and "⚑ ASM LT 1" in out and "M&amp;M" in out and "<b>M&M" not in out
    assert tb.chunks("a\n" * 5000, 100)[0].count("\n") <= 50


def test_unknown_and_plain_text():
    assert "Unknown command" in asyncio.run(tb.handle("/nope", None, None, {}))
    assert "/help" in asyncio.run(tb.handle("hello", None, None, {}))


def test_alert_command_keeps_other_levels():
    calls = []

    async def get(path, **params):
        return {"alerts": {"TCS": {"above": 2400.0}}} if path == "/api/alerts" else {}

    async def put(path, body):
        calls.append((path, body))
        return {"alerts": {}}

    reply = asyncio.run(tb.handle("/alert TCS move 3", get, put, {}))
    assert calls == [("/api/alerts/TCS", {"above": 2400.0, "below": None, "move": 3.0})] and "move ±3%" in reply
    json.dumps(calls)


def test_market_and_results_read_cleanly():
    assert [tb.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 40.4)] == \
        ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "40th"]
    out = tb.fmt_market({}, {"breadth": {"index": 22090.4, "index_chg_pct": 1.22, "adv": 874.0, "dec": 533.0, "pct_above50": 29.77}},
                        {"indices": {"NIFTY 50": {"pe": 19.4, "pb": 2.79, "dy": 1.51}}, "vs_history": {"NIFTY 50": {"pctl": 1}}})
    assert "874 up / 533 down · 30% above" in out and "1st percentile" in out
    res = tb.fmt_results({"since": "x", "rows": [{"symbol": "GTPL", "filed_at": "2026-10-13 19:40", "change_pct": None,
                                                    "revenue_yoy": 19.2, "pat_turn": "to loss", "numbers": "ok", "typical_move_pct": 4.1}]})
    assert "filed 19:40 · revenue +19% y/y · swung to a loss · usually moves ±4.1%" in res and "· ok" not in res


def test_otp_found_in_a_pasted_sms(monkeypatch, tmp_path):
    req, rep = _files(monkeypatch, tmp_path)
    assert tb.extract_otp("Dear Customer, 482913 is your OTP for login. Valid for 5 mins. -ICICI") == "482913"
    assert tb.extract_otp("otp 482 913") == "482913"
    assert tb.extract_otp("482913 or 111222?") is None and tb.extract_otp("hello") is None
    import time
    req.write_text(json.dumps({"at": time.time()}))
    assert "Got the OTP (48…13)" in asyncio.run(tb.handle("Your ICICI OTP is 482913", None, None, {}))
    assert json.loads(rep.read_text())["code"] == "482913"
