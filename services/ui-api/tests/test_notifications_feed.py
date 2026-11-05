"""GET /api/notifications/feed (desktop review completeness-final-02 / K5): the scheduler's alert events for the
desktop shell's native notifications, read from what already exists (notifications.jsonl + price-alert hits)."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers import alerts as price_alerts
from routers import notifications as nf

IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """ALERTS_PATH points at tmp (conftest); notifications.jsonl sits next to it, as in data/."""
    alerts = tmp_path / "price_alerts.json"
    monkeypatch.setenv("ALERTS_PATH", str(alerts))
    inbox = tmp_path / "notifications.jsonl"
    nf._scheduler_cache.__init__()                      # forget parses of other tests' files

    class F:
        def line(self, at: str, kind: str, title: str, body: str) -> None:
            with inbox.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": at, "kind": kind, "title": title, "body": body}) + "\n")

        def hits(self, hits: list[dict]) -> None:              # newest first, as /api/alerts/run writes them
            alerts.write_text(json.dumps({"alerts": {}, "history": hits}))
    return F()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(nf.router, prefix="/api/notifications")
    return TestClient(app, base_url="http://127.0.0.1:8010")


def _ms(iso: str) -> int:
    return int(datetime.fromisoformat(iso).timestamp() * 1000)


def test_empty_when_nothing_was_sent(files) -> None:
    body = _client().get("/api/notifications/feed").json()
    assert body["items"] == [] and body["count"] == 0 and body["next_since"] is None
    assert body["truncated"] is False and isinstance(body["server_time_ms"], int)


def test_scheduler_lines_come_newest_first_with_stable_ids_banner_and_tab(files) -> None:
    files.line("2026-10-23T08:50:02+05:30", "morning", "SuryaDhana · pre-market note", "GIFT NIFTY +0.6%")
    files.line("2026-10-23T11:02:10+05:30", "filing", "SuryaDhana · filing by your stock", "TCS: results")
    files.line("2026-10-23T21:00:07+05:30", "wrap", "Market wrap 2026-10-23", "NIFTY -0.39%")
    first = _client().get("/api/notifications/feed").json()["items"]
    assert [i["kind"] for i in first] == ["wrap", "filing", "morning"]
    assert [i["banner"] for i in first] == [False, True, True]               # wrap is inbox-only
    assert [i["tab"] for i in first] == ["wrap", "filings", "brief"]
    assert first[0]["at"] == "2026-10-23T21:00:07+05:30" and first[0]["at_ms"] == _ms("2026-10-23T21:00:07+05:30")
    assert all(re.fullmatch(r"n-[0-9a-f]{16}", i["id"]) for i in first) and first[0]["source"] == "scheduler"
    files.line("2026-10-24T08:50:01+05:30", "morning", "SuryaDhana · pre-market note", "GIFT NIFTY -0.2%")
    again = _client().get("/api/notifications/feed").json()["items"]
    assert [i["id"] for i in again[1:]] == [i["id"] for i in first]          # ids survive new lines


def test_identical_records_get_distinct_ids_and_bad_lines_are_skipped(files, tmp_path: Path) -> None:
    files.line("2026-10-23T15:40:01+05:30", "close", "SuryaDhana · closing note", "same")
    files.line("2026-10-23T15:40:01+05:30", "close", "SuryaDhana · closing note", "same")
    with (tmp_path / "notifications.jsonl").open("a") as fh:
        fh.write("not json\n[1, 2]\n" + json.dumps({"at": "garbage", "kind": "x"}) + "\n")
    items = _client().get("/api/notifications/feed").json()["items"]
    assert len(items) == 2 and items[0]["id"] != items[1]["id"]
    assert {i["id"].rsplit("-", 1)[-1] for i in items} >= {"2"}


def _hit(sym: str, side: str, level: float, price: float, at: str, **kw) -> dict:
    return {"sym": sym, "side": side, "level": level, "price": price, "at": at, **kw}


def test_a_hit_and_the_schedulers_banner_for_it_are_one_event_with_the_hits_id(files) -> None:
    hit = _hit("TCS", "above", 2200.0, 2203.5, "2026-10-26T04:31:00+00:00")       # 10:01:00 IST
    files.hits([hit])
    early = _client().get("/api/notifications/feed").json()["items"]            # the scheduler has not written yet
    assert len(early) == 1 and early[0]["id"].startswith("h-") and early[0]["source"] == "price_alert"
    assert early[0]["body"] == "TCS rose above ₹2,200.00 (now ₹2,203.50)" and early[0]["tab"] == "watch"
    files.line("2026-10-26T10:01:03+05:30", "price", "SuryaDhana price alert", early[0]["body"])
    later = _client().get("/api/notifications/feed").json()["items"]
    assert [i["id"] for i in later] == [early[0]["id"]]                        # folded: one banner, same id


def test_hits_the_scheduler_never_announced_are_still_in_the_feed(files) -> None:
    """A level crossed by a WTCH page's own /api/alerts/run never reaches notifications.jsonl."""
    files.hits([_hit("INFY", "move", 3.0, 1501.25, "2026-10-26T05:00:00+00:00", change_pct=-3.42),
                _hit("SBIN", "below", 800.0, 799.1, "2026-10-26T04:00:00+00:00")])
    files.line("2026-10-26T09:31:00+05:30", "price", "SuryaDhana price alert", "SBIN fell below ₹800.00 (now ₹799.10)")
    items = _client().get("/api/notifications/feed").json()["items"]
    assert [i["body"] for i in items] == ["INFY -3.4% today (alert at ±3%, now ₹1,501.25)",
                                          "SBIN fell below ₹800.00 (now ₹799.10)"]
    assert all(i["source"] == "price_alert" for i in items)


def test_a_price_line_far_from_any_hit_is_not_folded(files) -> None:
    files.hits([_hit("SBIN", "below", 800.0, 799.1, "2026-10-26T04:00:00+00:00")])
    files.line("2026-10-26T11:31:00+05:30", "price", "SuryaDhana price alert", "SBIN fell below ₹800.00 (now ₹799.10)")
    assert len(_client().get("/api/notifications/feed").json()["items"]) == 2   # 2 h apart: two events


def test_hit_text_matches_the_controller_format() -> None:
    """Drift guard: the feed folds a banner into its hit only when the text is identical to what
    scripts/master_controller.py price_alerts_check formats; this pins both f-strings."""
    src = (ROOT / "scripts" / "master_controller.py").read_text(encoding="utf-8")
    assert "text = f\"{h['sym']} {h['change_pct']:+.1f}% today (alert at ±{h['level']:g}%, now ₹{h['price']:,.2f})\"" in src
    assert "f\"{h['sym']} {'rose above' if h['side'] == 'above' else 'fell below'} \"" in src
    assert "f\"₹{h['level']:,.2f} (now ₹{h['price']:,.2f})\")" in src
    assert '_notify_mac, "SuryaDhana price alert", text, "price"' in src
    h = {"sym": "TCS", "side": "move", "level": 5, "price": 2203.456, "change_pct": 5.06}
    assert nf.hit_text(h) == f"{h['sym']} {h['change_pct']:+.1f}% today (alert at ±{h['level']:g}%, now ₹{h['price']:,.2f})"
    assert nf.hit_text({"sym": "X", "side": "sideways"}) is None and nf.hit_text({"side": "above"}) is None


def test_since_is_inclusive_and_next_since_overlaps_one_minute(files) -> None:
    for at, body in (("2026-10-26T10:00:00+05:30", "a"), ("2026-10-26T10:05:00+05:30", "b"),
                     ("2026-10-26T10:10:00+05:30", "c")):
        files.line(at, "move", "SuryaDhana · market move", body)
    c = _client()
    since = _ms("2026-10-26T10:05:00+05:30")
    body = c.get("/api/notifications/feed", params={"since": since}).json()
    assert [i["body"] for i in body["items"]] == ["c", "b"] and body["since"] == since
    assert body["next_since"] == _ms("2026-10-26T10:10:00+05:30") - nf.FEED_OVERLAP_MS
    iso = c.get("/api/notifications/feed", params={"since": "2026-10-26T10:05:00+05:30"}).json()
    naive = c.get("/api/notifications/feed", params={"since": "2026-10-26T10:05:00"}).json()   # no offset = IST
    assert iso["items"] == naive["items"] == body["items"]
    nothing = c.get("/api/notifications/feed", params={"since": _ms("2026-10-27T00:00:00+05:30")}).json()
    assert nothing["items"] == [] and nothing["next_since"] == _ms("2026-10-27T00:00:00+05:30")
    # a poller that passes next_since back never moves it backwards
    again = c.get("/api/notifications/feed", params={"since": body["next_since"]}).json()
    assert again["next_since"] == body["next_since"]


def test_every_kind_the_scheduler_records_opens_a_real_terminal_page() -> None:
    """Drift guard: each kind master-controller records maps to a page id the terminal routes (ui/app/page.tsx)."""
    src = (ROOT / "scripts" / "master_controller.py").read_text(encoding="utf-8")
    kinds = set(re.findall(r'_notify_mac, "[^"]*", \w+, "([a-z]+)"\)', src))
    kinds |= set(re.findall(r'_record_notification, "([a-z]+)"', src))
    assert kinds >= {"price", "filing", "results", "move", "close", "morning", "wrap", "journal"}
    assert kinds <= set(nf.TAB_BY_KIND)
    pages = set(re.findall(r"case '([a-z-]+)'", (ROOT / "ui" / "app" / "page.tsx").read_text(encoding="utf-8")))
    assert set(nf.TAB_BY_KIND.values()) <= pages and "alerts" in pages


def test_bad_parameters_are_refused(files) -> None:
    c = _client()
    assert c.get("/api/notifications/feed", params={"since": "yesterday"}).status_code == 422
    assert c.get("/api/notifications/feed", params={"limit": 0}).status_code == 422
    assert c.get("/api/notifications/feed", params={"limit": nf.MAX_LIMIT + 1}).status_code == 422



@pytest.mark.parametrize("since", ["\u00b2", "\u0661\u0662\u0663", "\uff11\uff12\uff13", "1" * 16, "9" * 40, "-5", "1e12"])
def test_non_ascii_digits_and_absurd_epochs_are_a_422_not_a_500(files, since: str) -> None:
    """str.isdigit accepts superscripts, Arabic-Indic and full-width digits; int() refuses '\u00b2' (was a 500)
    and quietly accepts the others. Only ASCII epoch milliseconds (up to 15 digits) or ISO-8601 are a time."""
    r = _client().get("/api/notifications/feed", params={"since": since})
    assert r.status_code == 422, (since, r.status_code, r.text[:200])


def test_the_largest_accepted_epoch_still_answers(files) -> None:
    body = _client().get("/api/notifications/feed", params={"since": "9" * nf.MAX_SINCE_DIGITS}).json()
    assert body["items"] == [] and body["since"] == int("9" * nf.MAX_SINCE_DIGITS)

def test_limit_bounds_the_answer_and_says_it_was_cut(files) -> None:
    for m in range(12):
        files.line(f"2026-10-26T10:{m:02d}:00+05:30", "move", "SuryaDhana · market move", f"m{m}")
    body = _client().get("/api/notifications/feed", params={"limit": 5}).json()
    assert body["count"] == 5 and body["truncated"] is True
    assert [i["body"] for i in body["items"]] == ["m11", "m10", "m9", "m8", "m7"]


def test_only_the_tail_of_a_huge_inbox_is_read(files, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nf, "MAX_READ_BYTES", 300)
    for m in range(20):
        files.line(f"2026-10-26T10:{m:02d}:00+05:30", "move", "SuryaDhana · market move", f"m{m}")
    items = _client().get("/api/notifications/feed", params={"limit": 200}).json()["items"]
    assert 0 < len(items) < 20 and items[0]["body"] == "m19"           # newest kept; a cut first line is dropped


def test_the_old_inbox_endpoint_is_unchanged(files) -> None:
    files.line("2026-10-23T08:50:02+05:30", "morning", "SuryaDhana · pre-market note", "x")
    app = FastAPI()
    app.include_router(price_alerts.router, prefix="/api/alerts")
    items = TestClient(app, base_url="http://127.0.0.1:8010").get("/api/alerts/feed").json()["items"]
    assert items == [{"at": "2026-10-23T08:50:02+05:30", "kind": "morning", "title": "SuryaDhana · pre-market note",
                      "body": "x"}]


def test_the_feed_is_mounted_in_the_real_app(monkeypatch: pytest.MonkeyPatch, files) -> None:
    import main
    r = TestClient(main.app, base_url="http://127.0.0.1:8010").get("/api/notifications/feed")
    assert r.status_code == 200 and r.json()["items"] == []
