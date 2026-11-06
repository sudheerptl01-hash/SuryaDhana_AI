"""Shared test setup for ui-api."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _fresh_swr_caches():
    """The stale-while-revalidate caches (cache.SWRCache, C-PERF-01) are module-level: never let one test's
    upstream answer be served to another test."""
    def _clear() -> None:
        try:
            from cache import REGISTRY, SWRCache
        except Exception:
            return
        for c in list(REGISTRY.values()):
            if isinstance(c, SWRCache):
                c.invalidate()
    _clear()
    yield
    _clear()


@pytest.fixture(autouse=True)
def _fresh_broker_book_cache():
    """routers.positions caches the broker book for 30 s; never let one test see another's book."""
    try:
        import routers.positions as pos
        pos._BOOK_CACHE.update(at=0.0, key=None, book=None)
    except Exception:
        pass
    yield


@pytest.fixture(autouse=True)
def _isolated_state_files(tmp_path, monkeypatch):
    """Tests must never touch the live state files in data/ (a broker-book test once replaced the real
    last_holdings.json with an empty book). Every writer is pointed at tmp_path; tests may re-patch."""
    monkeypatch.setenv("ALERTS_PATH", str(tmp_path / "price_alerts.json"))
    monkeypatch.setenv("GOLD_LOG_PATH", str(tmp_path / "gold_log.json"))
    monkeypatch.setenv("PREFS_DB", str(tmp_path / "ui_prefs.sqlite"))
    monkeypatch.setenv("PAPER_TRADES_DB", str(tmp_path / "paper_trades.db"))  # legacy execution engine
    monkeypatch.setenv("PAPER_FO_DB", str(tmp_path / "paper_fo.sqlite"))      # the PAPER F&O book + saved OSTR structures (W2-BOOK)
    try:
        import routers.positions as pos
        monkeypatch.setattr(pos, "_last_holdings_path", lambda: tmp_path / "last_holdings.json")
    except Exception:
        pass
    yield
