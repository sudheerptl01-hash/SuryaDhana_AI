"""routers/alerts.py v2 (PLAN 2.3 / M41): the SQLite store and its migration from price_alerts.json, the typed-rule
routes, the evaluation run against a fake data-service, the dispatch queue the controller reads, and the dry run.
Temp files only (conftest points ALERTS_PATH at tmp; the DB sits next to it)."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers import alerts  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
T0 = datetime.fromisoformat("2026-11-06T10:00:00+05:30")

SUMMARY = {"symbol": "NIFTY", "rows": [{"date": f"2026-10-{d:02d}", "iv30_cm": 12.0 + d / 10, "iv_pctile_252": 50.0 + d} for d in range(1, 31)]
           + [{"date": "2026-11-05", "iv30_cm": 18.0, "iv_pctile_252": 86.0}]}


class World:
    def __init__(self, tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp, self.now, self.ds_calls, self.quote_calls = tmp, T0, [], []
        self.ds: dict[str, Any] = {"/db/iv/summary": SUMMARY}
        self.quotes: dict[str, Any] = {}
        monkeypatch.setenv("ALERTS_PATH", str(tmp / "price_alerts.json"))
        monkeypatch.delenv("ALERTS_DB", raising=False)
        monkeypatch.setattr(alerts, "_now", lambda: self.now)
        alerts._READS.clear()

        async def fetch_ds(path: str, params: dict[str, str]) -> Any:
            self.ds_calls.append((path, tuple(sorted(params.items()))))
            body = self.ds.get(path)
            if callable(body):                                                  # a params-aware fake (the drivers store)
                body = body(params)
            if isinstance(body, Exception):
                raise body
            if body is None:
                raise RuntimeError(f"404 {path}")
            return body
        monkeypatch.setattr(alerts, "_fetch_ds", fetch_ds)
        from routers import news_scanner

        async def get_quotes(symbols: str, fresh: bool = False, response: Any = None) -> dict[str, Any]:
            self.quote_calls.append((symbols, fresh))
            return {"quotes": {s: self.quotes.get(s, {"available": False, "state": "stale"}) for s in symbols.split(",")}}
        monkeypatch.setattr(news_scanner, "get_quotes", get_quotes)
        app = FastAPI()
        app.include_router(alerts.router, prefix="/api/alerts")
        self.c = TestClient(app)

    def db(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.tmp / "alerts.sqlite")
        c.row_factory = sqlite3.Row
        return c

    def tick(self, minutes: float = 1) -> None:
        self.now += timedelta(minutes=minutes)
        alerts._READS.clear()


@pytest.fixture
def w(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, monkeypatch)


# ── migration: price_alerts.json → SQLite, unchanged ───────────────────────────────────────────────────────
LEGACY = {"alerts": {"TCS": {"above": 3300.0, "below": 2900.0, "move": 3.0, "yahoo": "TCS.NS"}, "AAPL": {"above": 300.0, "yahoo": "AAPL"}},
          "history": [{"sym": "INFY", "side": "below", "level": 1500.0, "price": 1499.0, "at": "2026-10-30T05:00:00+00:00"},
                      {"sym": "SBIN", "side": "move", "level": 3.0, "price": 800.0, "change_pct": -3.4, "at": "2026-10-29T05:00:00+00:00"}]}


def test_the_first_open_imports_price_alerts_json_unchanged(w: World) -> None:
    (w.tmp / "price_alerts.json").write_text(json.dumps(LEGACY))
    before = (w.tmp / "price_alerts.json").read_bytes()
    assert w.c.get("/api/alerts").json() == LEGACY
    assert (w.tmp / "price_alerts.json").read_bytes() == before             # a read never rewrites the file
    with w.db() as c:
        rows = {r["id"]: (r["op"], r["value"], r["origin"]) for r in c.execute("SELECT * FROM alert_rules")}
        assert rows == {"px:TCS:above": ("above", 3300.0, "price"), "px:TCS:below": ("below", 2900.0, "price"),
                        "px:TCS:move": ("change_pct", 3.0, "price"), "px:AAPL:above": ("above", 300.0, "price")}
        assert c.execute("SELECT COUNT(*) FROM alert_fires WHERE origin = 'price'").fetchone()[0] == 2
        assert c.execute("SELECT value FROM alert_meta WHERE key = 'migrated_at'").fetchone() is not None
    # the price alerts also show in the unified rules list, read-only, with their summary
    rules = {r["id"]: r for r in w.c.get("/api/alerts/rules").json()["rules"]}
    assert rules["px:TCS:move"]["summary"] == "TCS price moves ±3 % on the day · one-shot · Mac + Telegram"


def test_a_change_is_mirrored_and_an_external_rewrite_is_re_imported(w: World) -> None:
    w.c.put("/api/alerts/TCS", json={"above": 2200})
    mirror = json.loads((w.tmp / "price_alerts.json").read_text())
    assert mirror == {"alerts": {"TCS": {"above": 2200.0, "yahoo": "TCS.NS"}}, "history": []}
    # an older ui-api (rollback) or a test writes the file: the next read takes it
    (w.tmp / "price_alerts.json").write_text(json.dumps({"alerts": {"INFY": {"below": 1400.0, "yahoo": "INFY.NS"}}, "history": []}))
    assert w.c.get("/api/alerts").json()["alerts"] == {"INFY": {"below": 1400.0, "yahoo": "INFY.NS"}}
    # negative control: without the change the DB is authoritative (a stale import would bring TCS back)
    assert "TCS" not in w.c.get("/api/alerts").json()["alerts"]
    (w.tmp / "price_alerts.json").unlink()                                     # deleted by hand: rebuilt from the DB
    assert w.c.get("/api/alerts").json()["alerts"] == {"INFY": {"below": 1400.0, "yahoo": "INFY.NS"}}
    assert json.loads((w.tmp / "price_alerts.json").read_text())["alerts"] == {"INFY": {"below": 1400.0, "yahoo": "INFY.NS"}}


def test_price_fires_are_never_deleted_only_hidden_from_the_last_50(w: World) -> None:
    hist = [{"sym": f"S{i}", "side": "above", "level": 1.0, "price": 2.0, "at": f"2026-10-{1 + i // 10:02d}T0{i % 10}:00:00"} for i in range(60)]
    alerts._write({"alerts": {}, "history": hist})
    assert len(w.c.get("/api/alerts").json()["history"]) == 50
    alerts._write({"alerts": {}, "history": []})
    assert w.c.get("/api/alerts").json()["history"] == []
    with w.db() as c:
        assert c.execute("SELECT COUNT(*) FROM alert_fires").fetchone()[0] == 50    # the 50 the legacy view held, hidden, not gone


# ── typed rules CRUD ────────────────────────────────────────────────────────────────────────────────────────
def test_create_validate_replace_and_actions(w: World) -> None:
    r = w.c.post("/api/alerts/rules", json={"series": "iv_pctile:nifty", "op": "above", "value": 80, "repeat": "repeat"})
    assert r.status_code == 200, r.text
    rule = r.json()
    assert rule["series"] == "iv_pctile:NIFTY" and rule["symbol"] == "NIFTY" and rule["cooldown_min"] == 30 and rule["status"] == "active"
    assert rule["badge"] == "arithmetic" and rule["summary"].startswith("NIFTY IV percentile (252 sessions) at or over 80 · repeat")
    bad = w.c.post("/api/alerts/rules", json={"series": "iv_pctile:NIFTY", "op": "above", "value": 80, "note": "bullish, buy calls"})
    assert bad.status_code == 422 and "direction words" in bad.json()["detail"]
    assert w.c.post("/api/alerts/rules", json={"series": "nope:X", "op": "above", "value": 1}).status_code == 422
    rid = rule["id"]
    sn = w.c.put(f"/api/alerts/rules/{rid}/action", json={"action": "snooze", "minutes": 90}).json()
    assert sn["status"] == "snoozed" and sn["snooze_until"] == "2026-11-06T11:30:00+05:30"
    assert w.c.put(f"/api/alerts/rules/{rid}/action", json={"action": "resume"}).json()["status"] == "active"
    assert w.c.put(f"/api/alerts/rules/{rid}/action", json={"action": "pause"}).json()["status"] == "paused"
    assert w.c.put(f"/api/alerts/rules/{rid}/action", json={"action": "explode"}).status_code == 422
    rep = w.c.put(f"/api/alerts/rules/{rid}", json={"series": "iv_rank:NIFTY", "op": "below", "value": 20}).json()
    assert rep["id"] == rid and rep["series"] == "iv_rank:NIFTY" and rep["created_at"] == rule["created_at"]
    assert w.c.delete(f"/api/alerts/rules/{rid}").json() == {"deleted": rid}
    assert w.c.delete(f"/api/alerts/rules/{rid}").status_code == 404
    w.c.put("/api/alerts/TCS", json={"above": 2200})
    assert w.c.put("/api/alerts/rules/px:TCS:above/action", json={"action": "pause"}).status_code == 409   # price alerts: PUT /{sym}


def test_from_text_answers_200_with_ok_or_the_reason(w: World) -> None:
    ok = w.c.put("/api/alerts/rules/from-text", json={"text": "fo_ban:KAYNES cross_up 0.5 repeat telegram"}).json()
    assert ok["ok"] and ok["rule"]["channel"] == "telegram" and ok["rule"]["repeat"] == "repeat"
    err = w.c.put("/api/alerts/rules/from-text", json={"text": "fo_ban:KAYNES above 1"}).json()
    assert err == {"ok": False, "error": "fo_ban supports cross_up, cross_down, changed (not above)"}
    assert w.c.get("/api/alerts/series").json()["kinds"][0]["kind"] == "price"


# ── evaluation ──────────────────────────────────────────────────────────────────────────────────────────────
def test_an_iv_percentile_rule_fires_once_and_persists_its_state(w: World) -> None:
    rid = w.c.post("/api/alerts/rules", json={"series": "iv_pctile:NIFTY", "op": "above", "value": 80, "repeat": "repeat"}).json()["id"]
    out = w.c.post("/api/alerts/run?scope=eod").json()
    assert out["hits"] == [] and out["rules_checked"] == 1 and len(out["fires"]) == 1
    f = out["fires"][0]
    assert f["text"].startswith("NIFTY IV percentile (252 sessions) 86 is at or over 80 · as of 2026-11-05")
    assert w.quote_calls == []                                    # scope=eod reads no quotes
    w.tick()
    assert w.c.post("/api/alerts/run?scope=eod").json()["fires"] == []      # stays above: no second fire
    with w.db() as c:
        st = json.loads(c.execute("SELECT state FROM alert_rules WHERE id = ?", (rid,)).fetchone()["state"])
    assert st["armed"] is False and st["fires"] == 1 and st["last_value"] == 86.0
    fires = w.c.get("/api/alerts/fires").json()
    assert fires["groups"][0]["symbol"] == "NIFTY" and fires["groups"][0]["count"] == 1 and fires["fires"][0]["origin"] == "rule"


def test_a_dead_upstream_reads_unavailable_and_fires_nothing(w: World) -> None:
    w.ds["/db/iv/summary"] = RuntimeError("503 data-service unreachable")
    w.c.post("/api/alerts/rules", json={"series": "iv_pctile:NIFTY", "op": "above", "value": 80})
    out = w.c.post("/api/alerts/run?scope=eod").json()
    assert out["fires"] == [] and out["rules_checked"] == 1
    rows = w.c.get("/api/alerts/rules/evaluate").json()["rows"]
    assert rows[0]["value"] is None and rows[0]["reason"].startswith("read failed: 503")


def test_the_dry_run_changes_nothing_and_the_run_does(w: World) -> None:
    rid = w.c.post("/api/alerts/rules", json={"series": "iv_pctile:NIFTY", "op": "above", "value": 80}).json()["id"]
    dry = w.c.get("/api/alerts/rules/evaluate").json()["rows"][0]
    assert (dry["id"], dry["value"], dry["satisfied"], dry["as_of"], dry["badge"]) == (rid, 86.0, True, "2026-11-05", "arithmetic")
    with w.db() as c:
        assert c.execute("SELECT state FROM alert_rules WHERE id = ?", (rid,)).fetchone()["state"] == "{}"
        assert c.execute("SELECT COUNT(*) FROM alert_fires").fetchone()[0] == 0
    # negative control: the run over the same data does change state and fire (a one-shot then stops)
    assert len(w.c.post("/api/alerts/run").json()["fires"]) == 1
    assert w.c.get("/api/alerts/rules").json()["rules"][0]["status"] == "fired"


def test_typed_price_rules_ride_the_same_fresh_quote_batch(w: World) -> None:
    w.quotes = {"TCS.NS": {"available": True, "price": 3210.0, "change_pct": 1.2}, "^NSEI": {"available": True, "price": 24990.0}}
    w.c.put("/api/alerts/TCS", json={"above": 3200})
    w.c.post("/api/alerts/rules", json={"series": "price:NIFTY", "op": "cross_up", "value": 25000, "repeat": "repeat"})
    out = w.c.post("/api/alerts/run").json()
    assert [h["sym"] for h in out["hits"]] == ["TCS"] and out["fires"] == []           # NIFTY's first reading is the baseline
    assert [(s.split(","), f) for s, f in w.quote_calls] == [(["TCS.NS"], True), (["^NSEI"], True)]
    assert all("." in t and t.endswith(".NS") or t.startswith("^") for s, _ in w.quote_calls for t in s.split(","))  # never Yahoo
    w.tick()
    w.quotes["^NSEI"] = {"available": True, "price": 25012.0}
    f = w.c.post("/api/alerts/run").json()["fires"]
    assert len(f) == 1 and f[0]["text"].startswith("NIFTY price crossed 25,000.00 from under it (24,990.00 → 25,012.00)")


# ── the dispatch queue (the controller) ─────────────────────────────────────────────────────────────────────
def test_dispatch_starts_with_the_first_call_and_sends_each_fire_once(w: World) -> None:
    w.c.post("/api/alerts/rules", json={"series": "iv_pctile:NIFTY", "op": "above", "value": 80, "repeat": "repeat", "channel": "telegram"})
    w.c.post("/api/alerts/run?scope=eod")                                    # fired before any dispatcher asked
    w.tick()
    first = w.c.post("/api/alerts/run?scope=eod&dispatch=1").json()
    assert first["dispatch"] == []                                           # nothing older than the dispatcher is replayed
    w.quotes = {"TCS.NS": {"available": True, "price": 3290.0, "change_pct": -3.6}}
    w.c.put("/api/alerts/TCS", json={"above": 3200, "move": 3})
    w.tick()
    sent = w.c.post("/api/alerts/run?dispatch=1").json()["dispatch"]
    assert [(d["origin"], d["title"], d["channel"]) for d in sent] == [("price", "SuryaDhana price alert", "both"),
                                                                       ("price", "SuryaDhana price alert", "both")]
    assert sorted(d["text"] for d in sent) == ["TCS -3.6% today (alert at ±3%, now ₹3,290.00)", "TCS rose above ₹3,200.00 (now ₹3,290.00)"]
    w.tick()
    assert w.c.post("/api/alerts/run?dispatch=1").json()["dispatch"] == []   # each once
    # a fire left unclaimed for over 30 min expires instead of arriving late
    w.ds["/db/iv/summary"] = {"rows": SUMMARY["rows"][:-1] + [{"date": "2026-11-06", "iv30_cm": 11.0, "iv_pctile_252": 10.0}]}
    w.tick()
    w.c.post("/api/alerts/run?scope=eod")                                    # re-arms (10 < 80)
    w.ds["/db/iv/summary"] = SUMMARY
    w.tick(31)
    w.c.post("/api/alerts/run?scope=eod")                                    # fires (cooldown 30 min passed), not claimed
    w.tick(31)
    assert w.c.post("/api/alerts/run?scope=eod&dispatch=1").json()["dispatch"] == []
    with w.db() as c:
        assert c.execute("SELECT dispatched_at FROM alert_fires ORDER BY seq DESC LIMIT 1").fetchone()[0] == "expired"


def test_the_first_dispatcher_call_still_sends_what_its_own_run_fired(w: World) -> None:
    """The ui-api restart lands mid-session: the controller's first dispatch=1 run must announce a crossing found in that
    same run (it no longer reads the 'hits' of a ui-api that serves 'dispatch')."""
    w.quotes = {"TCS.NS": {"available": True, "price": 3210.0, "change_pct": 0.4}}
    w.c.put("/api/alerts/TCS", json={"above": 3200})
    w.c.post("/api/alerts/rules", json={"series": "iv_pctile:NIFTY", "op": "above", "value": 80})
    w.tick()
    out = w.c.post("/api/alerts/run?dispatch=1").json()
    assert sorted(d["origin"] for d in out["dispatch"]) == ["price", "rule"] and [h["sym"] for h in out["hits"]] == ["TCS"]
    # negative control: a fire stored before the first dispatcher call (an earlier WTCH check) is not replayed
    w2_rule = w.c.post("/api/alerts/rules", json={"series": "iv_rank:NIFTY", "op": "below", "value": 99}).json()["id"]
    with w.db() as c:
        c.execute("DELETE FROM alert_meta WHERE key = 'dispatch_since'")
        c.execute("UPDATE alert_fires SET dispatched_at = NULL")
    w.tick()
    w.ds["/db/iv/summary"] = {"rows": SUMMARY["rows"][:-1] + [{"date": "2026-11-05", "iv30_cm": 18.0, "iv_pctile_252": 86.0, "iv_rank_252": 40.0}]}
    w.c.post("/api/alerts/run?scope=eod")                                    # the iv_rank rule fires, nobody claims
    w.tick()
    again = w.c.post("/api/alerts/run?scope=eod&dispatch=1").json()["dispatch"]
    assert again == [] and w2_rule


def test_the_dispatch_text_is_the_controllers_own_f_string() -> None:
    """legacy_hit_text must equal what scripts/master_controller.py price_alerts_check formats (pinned on its source)."""
    src = (ROOT / "scripts" / "master_controller.py").read_text(encoding="utf-8")
    assert "text = f\"{h['sym']} {h['change_pct']:+.1f}% today (alert at ±{h['level']:g}%, now ₹{h['price']:,.2f})\"" in src
    assert "f\"₹{h['level']:,.2f} (now ₹{h['price']:,.2f})\")" in src
    h = {"sym": "INFY", "side": "move", "level": 3.0, "price": 1501.25, "change_pct": -3.42}
    assert alerts.legacy_hit_text(h) == "INFY -3.4% today (alert at ±3%, now ₹1,501.25)"
    assert alerts.legacy_hit_text({"sym": "SBIN", "side": "below", "level": 800, "price": 799.1}) == "SBIN fell below ₹800.00 (now ₹799.10)"


def test_the_run_survives_an_engine_failure(w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(scope: str = "all", quotes: Any = None) -> Any:
        raise RuntimeError("engine down")
    monkeypatch.setattr(alerts, "evaluate_rules", boom)
    w.quotes = {"TCS.NS": {"available": True, "price": 3210.0}}
    w.c.put("/api/alerts/TCS", json={"above": 3200})
    out = w.c.post("/api/alerts/run").json()
    assert [h["sym"] for h in out["hits"]] == ["TCS"] and out["rules_error"] == "RuntimeError: engine down"


def test_concurrent_runs_fire_a_rule_once(w: World) -> None:
    w.c.post("/api/alerts/rules", json={"series": "iv_pctile:NIFTY", "op": "above", "value": 80, "repeat": "repeat"})

    async def both() -> list[Any]:
        return await asyncio.gather(alerts.evaluate_rules("eod"), alerts.evaluate_rules("eod"))
    res = asyncio.run(both())
    assert sum(len(f) for f, _ in res) == 1
    with w.db() as c:
        assert c.execute("SELECT COUNT(*) FROM alert_fires WHERE origin = 'rule'").fetchone()[0] == 1


def test_the_controllers_round_delivers_from_this_router(w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """Contract: scripts/master_controller.py alerts_dispatch (O-OPS) against this router, in-process (no network): the
    price hit on its legacy title, the typed fire on its own channel, each delivered once."""
    import httpx
    for p in (str(ROOT), str(ROOT / "scripts")):
        if p not in sys.path:
            sys.path.insert(0, p)
    mc = pytest.importorskip("master_controller")
    if not hasattr(mc, "alerts_dispatch"):
        pytest.skip("the controller's dispatch round is not in this tree yet")
    app = FastAPI()
    app.include_router(alerts.router, prefix="/api/alerts")
    real = httpx.AsyncClient
    monkeypatch.setattr(mc.httpx, "AsyncClient", lambda *a, **k: real(transport=httpx.ASGITransport(app=app), base_url="http://ui-api",
                                                                       timeout=k.get("timeout", 30)))
    macs: list[tuple[str, str, str]] = []
    sent: list[tuple[str, str]] = []

    async def info(title: str, body: str) -> None:
        sent.append((title, body))
    monkeypatch.setattr(mc, "_notify_mac", lambda t, b, k="alert": macs.append((t, b, k)))
    monkeypatch.setattr(mc._alerts, "info", info)
    w.quotes = {"TCS.NS": {"available": True, "price": 3210.0, "change_pct": 0.4}}
    w.c.put("/api/alerts/TCS", json={"above": 3200})
    w.c.post("/api/alerts/rules", json={"series": "iv_pctile:NIFTY", "op": "above", "value": 80, "channel": "telegram"})
    w.tick()
    res = asyncio.run(mc.alerts_dispatch("price_alerts_check", "all"))
    assert len(res["dispatch"]) == 2
    assert macs == [("SuryaDhana price alert", "TCS rose above ₹3,200.00 (now ₹3,210.00)", "price")]
    assert [t for t, _ in sent] == ["Price alert", "Alert"] and sent[1][1].startswith("NIFTY IV percentile (252 sessions) 86 is at or over 80")
    w.tick()
    asyncio.run(mc.alerts_dispatch("price_alerts_check", "all"))
    assert len(macs) == 1 and len(sent) == 2                                 # nothing twice


def test_telegram_snooze_resume_delete_and_fired_reach_these_routes(w: World) -> None:
    """The W2-ALERTS patch to master_controller.py (O-OPS applies it): /alert snooze | resume | pause | del | fired, through
    the bot's own get / put, against this router. Skips until the patch is in the tree."""
    for p in (str(ROOT), str(ROOT / "scripts")):
        if p not in sys.path:
            sys.path.insert(0, p)
    mc = pytest.importorskip("master_controller")
    if not hasattr(mc, "fmt_alert_action"):
        pytest.skip("the Telegram parity patch (snooze / resume / pause / del / fired) is not applied yet")

    async def get(path: str, **params: Any) -> Any:
        r = w.c.get(path, params=params)
        return r.json() if r.status_code == 200 else None

    async def put(path: str, body: dict[str, Any]) -> Any:
        r = w.c.put(path, json=body)
        return r.json() if r.status_code == 200 else None
    rid = w.c.post("/api/alerts/rules", json={"series": "iv_pctile:NIFTY", "op": "above", "value": 80, "repeat": "repeat"}).json()["id"]
    assert "snoozed to 11:30" in asyncio.run(mc.alert_bot_reply(f"/alert snooze {rid} 90", get, put))
    assert "active" in asyncio.run(mc.alert_bot_reply(f"/alert resume {rid}", get, put))
    w.c.post("/api/alerts/run?scope=eod")
    fired = asyncio.run(mc.alert_bot_reply("/alert fired", get, put))
    assert fired.startswith("<b>Fired</b>") and "NIFTY</b> · 1" in fired
    assert "deleted" in asyncio.run(mc.alert_bot_reply(f"/alert del {rid}", get, put))
    # negative controls: an unknown id and a price level are refused, never silently "done"
    assert asyncio.run(mc.alert_bot_reply(f"/alert pause {rid}", get, put)).startswith("Could not pause")
    assert asyncio.run(mc.alert_bot_reply("/alert del r-nosuchrule", get, put)).startswith("Could not del")
    w.c.put("/api/alerts/TCS", json={"above": 2200})                          # a price level's id is not a rule id here
    assert asyncio.run(mc.alert_bot_reply("/alert del px:TCS:above", get, put)).startswith("Usage:")
    assert "TCS" in w.c.get("/api/alerts").json()["alerts"]


# ── review 6 Nov (round 2) ─────────────────────────────────────────────────────────────────────────────────────
RECORDED = json.loads((Path(__file__).resolve().parent / "fixtures" / "alerts_recorded_20261106.json").read_text(encoding="utf-8"))


def test_the_driver_rule_reads_the_recorded_store_by_its_real_key(w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """The data-service route passes ``index`` through: only 'NIFTY 50' / 'NIFTY BANK' exist (recorded 6 Nov 09:55)."""
    pay = RECORDED["payloads"]
    w.ds["/db/index-drivers"] = lambda params: pay.get(params.get("index", ""), pay["NIFTY"])
    rid = w.c.post("/api/alerts/rules", json={"series": "nifty_driver:NIFTY", "op": "changed", "repeat": "repeat"}).json()["id"]
    row = w.c.get("/api/alerts/rules/evaluate").json()["rows"][0]
    assert (row["id"], row["value"], row["as_of"]) == (rid, "HDFCBANK", "2026-11-05")
    assert ("/db/index-drivers", (("index", "NIFTY 50"),)) in w.ds_calls
    # negative control: the short id the round-1 code sent reads nothing from the same store
    from routers.alerts import engine
    monkeypatch.setattr(engine, "DRIVER_STORE_NAMES", {"NIFTY": "NIFTY", "BANKNIFTY": "BANKNIFTY"})
    w.tick()
    old = w.c.get("/api/alerts/rules/evaluate").json()["rows"][0]
    assert old["value"] is None and old["reason"] == "NIFTY: no stored attribution yet (run index_drivers_daily)"


def test_reads_that_start_a_refresh_wait_out_the_freeze_windows(w: World) -> None:
    """POST /run never makes a data-service read that can start a refresh inside 07:45–09:20 / 18:30–21:15 IST; the rule
    reads no value there (no fire, no baseline move) and is evaluated at the first round outside."""
    w.ds["/db/surveillance"] = {"ban": ["KAYNES"], "dates": {"ban": "2026-11-06"}}
    w.c.post("/api/alerts/rules", json={"series": "fo_ban:KAYNES", "op": "cross_up", "repeat": "repeat"})
    w.c.post("/api/alerts/rules", json={"series": "iv_pctile:NIFTY", "op": "above", "value": 80, "repeat": "repeat"})
    w.now = datetime.fromisoformat("2026-11-06T19:05:00+05:30")
    out = w.c.post("/api/alerts/run?scope=eod").json()
    assert [f["kind"] for f in out["fires"]] == ["iv_pctile"]                   # stored-table reads still run
    assert not any(p == "/db/surveillance" for p, _ in w.ds_calls)
    with w.db() as c:
        st = json.loads(c.execute("SELECT state FROM alert_rules WHERE kind = 'fo_ban'").fetchone()["state"])
    assert "last_value" not in st and st["last_error"].startswith("skipped inside the 18:30–21:15 IST freeze window")
    # negative control: the same run outside the window reads it (the first reading is the cross_up baseline)
    w.now = datetime.fromisoformat("2026-11-06T21:16:00+05:30")
    alerts._READS.clear()
    w.c.post("/api/alerts/run?scope=eod")
    assert any(p == "/db/surveillance" for p, _ in w.ds_calls)
    # the dry run is a page read like BRIEF's: never gated
    w.ds_calls.clear()
    w.now = datetime.fromisoformat("2026-11-06T08:00:00+05:30")
    alerts._READS.clear()
    w.c.get("/api/alerts/rules/evaluate")
    assert any(p == "/db/surveillance" for p, _ in w.ds_calls)
    assert alerts._freeze_window(datetime.fromisoformat("2026-11-06T09:19:59+05:30")) == "07:45–09:20"
    assert alerts._freeze_window(datetime.fromisoformat("2026-11-06T09:20:00+05:30")) is None


def test_a_page_found_hit_reaches_the_mac_once(w: World) -> None:
    """WTCH's own POST /run (no dispatch): with a live controller the hit is queued and the page posts no banner
    (page_notify false); with no controller the page announces it and the queue never repeats it."""
    w.quotes = {"TCS.NS": {"available": True, "price": 3210.0, "change_pct": 0.4}}
    w.c.post("/api/alerts/run?scope=eod&dispatch=1")                           # the controller is live
    w.c.put("/api/alerts/TCS", json={"above": 3200})
    w.tick()
    page = w.c.post("/api/alerts/run").json()
    assert [h["sym"] for h in page["hits"]] == ["TCS"] and page["page_notify"] is False
    w.tick()
    sent = w.c.post("/api/alerts/run?scope=eod&dispatch=1").json()["dispatch"]
    assert [(d["origin"], d["text"]) for d in sent] == [("price", "TCS rose above ₹3,200.00 (now ₹3,210.00)")]
    # negative control: the controller has not asked for > 3 min → the page announces, the queue skips it
    w.c.put("/api/alerts/INFY", json={"above": 1500})
    w.quotes["INFY.NS"] = {"available": True, "price": 1510.0, "change_pct": 0.2}
    w.tick(4)
    lone = w.c.post("/api/alerts/run").json()
    assert [h["sym"] for h in lone["hits"]] == ["INFY"] and lone["page_notify"] is True
    w.tick()
    assert w.c.post("/api/alerts/run?scope=eod&dispatch=1").json()["dispatch"] == []
    with w.db() as c:
        assert c.execute("SELECT dispatched_at FROM alert_fires WHERE symbol = 'INFY'").fetchone()[0] == "page"
    assert "page_notify" not in w.c.post("/api/alerts/run?scope=eod&dispatch=1").json()       # the controller's answer


def test_the_run_never_touches_sqlite_or_the_json_mirror_on_the_event_loop(w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """The legacy price branch used to read and write the store inside the async route (the blocking-in-async pattern
    that froze ui-api once): it now runs in a worker thread."""
    seen: list[bool] = []
    real_read = alerts._read

    def spy() -> dict[str, Any]:
        try:
            asyncio.get_running_loop()
            seen.append(True)                                                  # on the event loop: the defect
        except RuntimeError:
            seen.append(False)
        return real_read()
    monkeypatch.setattr(alerts, "_read", spy)
    w.quotes = {"TCS.NS": {"available": True, "price": 3210.0}}
    w.c.put("/api/alerts/TCS", json={"above": 3200})
    seen.clear()
    w.c.post("/api/alerts/run")
    assert seen and not any(seen), seen

    # negative control: the same spy called from a coroutine does see the loop
    async def on_loop() -> None:
        spy()
    asyncio.run(on_loop())
    assert seen[-1] is True


def _scripts_module(name: str) -> Any:
    for p in (str(ROOT), str(ROOT / "scripts")):
        if p not in sys.path:
            sys.path.insert(0, p)
    return pytest.importorskip(name)


def test_the_morning_note_counts_nse_sessions() -> None:
    """m084, round 2 (the W2-ALERTS patch to master_controller.py; skips until applied): the FII / DII age counts NSE
    sessions with the holiday master, so the morning after a weekday holiday is not flagged."""
    import inspect
    mc = _scripts_module("master_controller")
    if "holidays" not in inspect.signature(mc.fii_age_note).parameters:
        pytest.skip("the m084 session-count patch to master_controller.py is not applied yet")
    hol = {"2026-11-10": "a weekday NSE holiday (test input)"}
    assert mc.fii_age_note("2026-11-09", "2026-11-11", hol) == ""                        # the previous session: no flag
    assert mc.fii_age_note("2026-10-27", "2026-10-30", hol) == " — 2 NSE sessions older than the previous session"
    cash = {"summary": {"latest": {"FII": 4240.0, "DII": -1250.0}, "latest_date": "2026-11-09"}}
    assert "older" not in mc.compose_morning_note({}, {}, cash, [], set(), "2026-11-11", holidays=hol)
    # negative control: without the master the same correct figure reads one weekday older (and says holidays were not counted)
    assert mc.fii_age_note("2026-11-09", "2026-11-11") == " — 1 weekday older than the previous session (NSE holidays not counted)"
    assert "1 weekday older than the previous session (NSE holidays not counted)" in mc.compose_morning_note({}, {}, cash, [], set(), "2026-11-11")


def test_the_nightly_backup_carries_the_alert_store(w: World, tmp_path: Path) -> None:
    """The alert store (rules + the append-only fire log) is backed up with SQLite's backup API (the W2-ALERTS patch to
    scripts/db_backup.py; skips until applied), consistent while ui-api holds it open in WAL mode."""
    bk = _scripts_module("db_backup")
    if not hasattr(bk, "backup_alerts"):
        pytest.skip("the alert-store backup patch to scripts/db_backup.py is not applied yet")
    w.c.post("/api/alerts/rules", json={"series": "iv_pctile:NIFTY", "op": "above", "value": 80, "repeat": "repeat"})
    w.c.post("/api/alerts/run?scope=eod")                                     # one fire in the log
    held = sqlite3.connect(w.tmp / "alerts.sqlite")                           # ui-api holds it open, WAL
    try:
        held.execute("BEGIN")
        meta = bk.backup_alerts(w.tmp / "alerts.sqlite", tmp_path / "bk", "20261106")
    finally:
        held.rollback()
        held.close()
    assert (meta["rules"], meta["fires"], meta["file"]) == (1, 1, "alerts-20261106.sqlite")
    copy = sqlite3.connect(tmp_path / "bk" / "alerts-20261106.sqlite")
    assert copy.execute("PRAGMA journal_mode").fetchone()[0] == "delete" and copy.execute("SELECT COUNT(*) FROM alert_fires").fetchone()[0] == 1
    copy.close()
    assert ("alerts-*.sqlite",) in bk.FAMILIES
    # negative control: no store yet (before ui-api first opens it) → skipped, nothing written
    assert bk.backup_alerts(tmp_path / "nope.sqlite", tmp_path / "bk2", "20261106") == {"skipped": "absent", "src": str(tmp_path / "nope.sqlite")}
    assert not (tmp_path / "bk2").exists()
