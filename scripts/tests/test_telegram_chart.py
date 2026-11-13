"""Telegram /chart renderer (scripts/telegram_chart.py): parsing, whitelist, lock, caption, size cap.

The real Playwright render is NOT run here (that is the manual evidence step); every test drives
``chart_for_telegram`` with a stubbed renderer, exactly as the bot's off-thread call would.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import telegram_chart as tc  # noqa: E402


# ── parsing + whitelist ────────────────────────────────────────────────────────────────────────────────────────────

def test_parse_defaults_to_daily_chrt():
    req = tc.parse_command("/chart TCS")
    assert req == tc.ChartRequest(symbol="TCS", interval="D", tab=tc.CHARTS_TAB)


@pytest.mark.parametrize("text,interval", [("/chart nifty w", "W"), ("/chart TCS M", "M"), ("/chart@SuryaBot TCS d", "D")])
def test_parse_intervals_and_case(text, interval):
    req = tc.parse_command(text)
    assert isinstance(req, tc.ChartRequest) and req.interval == interval


def test_parse_gold_goes_to_the_gold_daily_view_only():
    req = tc.parse_command("/chart GOLD")
    assert req == tc.ChartRequest(symbol="GOLD", interval="D", tab=tc.GOLD_DAILY_TAB)
    assert "DAILY" in tc.parse_command("/chart GOLD W")      # a timeframe on GOLD → refusal line, not a request


@pytest.mark.parametrize("text", [
    "/chart", "/chart TCS W extra", "/charts TCS", "not a command",
    "/chart TCS X",                    # unknown interval
    "/chart ../broker",                # path-ish garbage
    "/chart ?tab=broker",              # URL-ish garbage
    "/chart _TCS",                     # must start with a letter
])
def test_parse_rejects_everything_off_the_grammar(text):
    assert isinstance(tc.parse_command(text), str)


@pytest.mark.parametrize("word", sorted(tc.FORBIDDEN_WORDS))
def test_parse_refuses_brkr_port_rsk_as_symbols(word):
    out = tc.parse_command(f"/chart {word}")
    assert isinstance(out, str) and "not a chartable symbol" in out


def test_every_accepted_parse_lands_on_the_page_whitelist():
    for text in ("/chart TCS", "/chart NIFTY W", "/chart M&M", "/chart GOLD", "/chart BAJAJ-AUTO M"):
        req = tc.parse_command(text)
        assert isinstance(req, tc.ChartRequest) and req.tab in tc.PAGE_WHITELIST


# ── lock: one render at a time ─────────────────────────────────────────────────────────────────────────────────────

def test_lock_is_exclusive_then_released(tmp_path):
    a = tc.RenderLock(tmp_path / "l.lock")
    b = tc.RenderLock(tmp_path / "l.lock")
    assert a.acquire() is True
    assert b.acquire() is False            # held → the second caller is refused
    a.release()
    assert b.acquire() is True
    b.release()
    assert not (tmp_path / "l.lock").exists()


def test_lock_takes_over_a_stale_lock_but_not_a_fresh_one(tmp_path):
    path = tmp_path / "l.lock"
    path.write_text(json.dumps({"pid": 99999, "at": time.time() - 9999}))
    assert tc.RenderLock(path, stale_s=180).acquire() is True    # stale (crashed render) → taken over
    path.write_text(json.dumps({"pid": 99999, "at": time.time()}))
    assert tc.RenderLock(path, stale_s=180).acquire() is False   # fresh → refused


def test_lock_handles_garbage_content_as_stale(tmp_path):
    path = tmp_path / "l.lock"
    path.write_text("not json")
    assert tc.RenderLock(path, stale_s=0).acquire() is True


# ── chart_for_telegram with a stubbed renderer ────────────────────────────────────────────────────────────────────

def _stub_renderer(png_bytes: int = 2_000, as_of: str = "13 Nov 2026 21:00 IST"):
    calls: list[tc.ChartRequest] = []

    def run(req, out_path, *, base=tc.BASE_URL, **kw):
        calls.append(req)
        Path(out_path).write_bytes(b"\x89PNG" + b"0" * max(0, png_bytes - 4))
        return {"path": out_path, "bytes": png_bytes, "as_of": as_of, "viewport": [1600, 900]}

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_happy_path_returns_png_and_asof_caption(tmp_path):
    run = _stub_renderer()
    path, caption = tc.chart_for_telegram("/chart TCS W", out_dir=tmp_path, renderer=run,
                                          lock=tc.RenderLock(tmp_path / "l.lock"))
    assert path is not None and path.exists() and path.suffix == ".png"
    assert run.calls == [tc.ChartRequest("TCS", "W", tc.CHARTS_TAB)]
    assert "TCS" in caption and "CHRT · W" in caption
    assert "as of 13 Nov 2026 21:00 IST" in caption and "source:" in caption
    assert not (tmp_path / "l.lock").exists()      # lock released


def test_usage_line_without_render_on_bad_input(tmp_path):
    run = _stub_renderer()
    path, msg = tc.chart_for_telegram("/chart", out_dir=tmp_path, renderer=run,
                                      lock=tc.RenderLock(tmp_path / "l.lock"))
    assert path is None and msg == tc.USAGE and run.calls == []


def test_busy_lock_means_no_render_and_a_calm_line(tmp_path):
    other = tc.RenderLock(tmp_path / "l.lock")
    assert other.acquire()
    run = _stub_renderer()
    path, msg = tc.chart_for_telegram("/chart TCS", out_dir=tmp_path, renderer=run,
                                      lock=tc.RenderLock(tmp_path / "l.lock"))
    assert path is None and "already running" in msg and run.calls == []
    other.release()


def test_renderer_crash_is_one_line_and_releases_the_lock(tmp_path):
    def boom(req, out_path, *, base=tc.BASE_URL, **kw):
        raise RuntimeError("terminal unreachable")

    lock = tc.RenderLock(tmp_path / "l.lock")
    path, msg = tc.chart_for_telegram("/chart TCS", out_dir=tmp_path, renderer=boom, lock=lock)
    assert path is None and "Chart render failed" in msg and "terminal unreachable" in msg
    assert not (tmp_path / "l.lock").exists()


def test_oversized_png_is_withheld(tmp_path):
    run = _stub_renderer(png_bytes=tc.MAX_BYTES + 1)
    path, msg = tc.chart_for_telegram("/chart TCS", out_dir=tmp_path, renderer=run,
                                      lock=tc.RenderLock(tmp_path / "l.lock"))
    assert path is None and "1 MB" in msg


def test_old_pngs_are_pruned(tmp_path):
    for i in range(tc.KEEP_LAST + 5):
        p = tmp_path / f"OLD_{i}.png"
        p.write_bytes(b"x")
        time.sleep(0.002)
    run = _stub_renderer()
    path, _ = tc.chart_for_telegram("/chart TCS", out_dir=tmp_path, renderer=run,
                                    lock=tc.RenderLock(tmp_path / "l.lock"))
    assert path is not None
    assert len(list(tmp_path.glob("*.png"))) <= tc.KEEP_LAST + 1   # pruned before the new render


# ── labelling: the caption carries source + date and ZERO direction words ─────────────────────────────────────────

DIRECTION_WORDS = ("up", "down", "bull", "bear", "buy", "sell", "long", "short", "target", "breakout",
                   "support", "resistance", "rally", "crash", "upside", "downside", "overbought", "oversold")


@pytest.mark.parametrize("text", ["/chart TCS", "/chart NIFTY W", "/chart RELIANCE M", "/chart GOLD"])
def test_caption_has_source_date_and_no_direction_words(text):
    req = tc.parse_command(text)
    assert isinstance(req, tc.ChartRequest)
    caption = tc.caption_line(req, "13 Nov 2026 21:00 IST")
    words = set(caption.lower().replace("·", " ").replace("—", " ").split())
    hits = words & set(DIRECTION_WORDS)
    assert not hits, f"direction words in the caption: {hits}"
    assert "as of" in caption and "source:" in caption
    assert "describes, does not predict" in caption
    assert len(caption) <= 1024                                     # Telegram's caption cap
