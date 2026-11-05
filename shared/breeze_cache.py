"""
Make ICICI Breeze sessions independent of ICICI's slow file server.

BreezeConnect.generate_session() calls get_stock_script_list(), which downloads SecurityMaster.zip **twice** — once
with urllib and *no timeout*. On 14 Oct 2026 directlink.icicidirect.com crawled (~20 KB/s), and every Breeze client
hung: the 08:00 login, /login from Telegram, and the holdings call behind WTCH, BRIEF and the bot.

install() patches the class once per process: the archive comes from a local cache refreshed at most every 20 hours,
each download is capped at 2 minutes, a failed download waits 30 minutes before the next try, and a stale copy is
used rather than waiting. Without any copy the method runs on an empty archive (sessions still work; only Breeze's
symbol → token lookups are missing).
"""
from __future__ import annotations

import io
import os
import threading
import time
from pathlib import Path
from typing import Optional

URL = "https://directlink.icicidirect.com/MotherAppMaster/SecurityMaster.zip"
CACHE = Path(os.getenv("BREEZE_CACHE_DIR", str(Path(__file__).resolve().parents[1] / "data" / "cache" / "breeze"))) / "SecurityMaster.zip"
FRESH_S = 20 * 3600
RETRY_AFTER_FAIL_S = 30 * 60
DOWNLOAD_TIMEOUT_S = 120

_lock = threading.Lock()
_state: dict = {"failed_at": 0.0, "installed": False}


def _download(dest: Path, timeout_s: float = DOWNLOAD_TIMEOUT_S) -> bool:
    """Stream the archive to `dest` within `timeout_s` overall; True when a complete zip was written."""
    import httpx
    deadline = time.time() + timeout_s
    tmp = dest.with_suffix(".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with httpx.stream("GET", URL, timeout=httpx.Timeout(20.0, read=30.0), follow_redirects=True) as r:
            if r.status_code != 200:
                return False
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
                    if time.time() > deadline:
                        raise TimeoutError("security master download too slow")
        import zipfile
        if not zipfile.is_zipfile(tmp):
            return False
        tmp.replace(dest)
        return True
    except Exception:  # noqa: BLE001 — any failure: keep the old copy
        return False
    finally:
        tmp.unlink(missing_ok=True)


def master_bytes(cache: Path = CACHE, now: Optional[float] = None) -> bytes:
    """The archive: the cached copy when fresh, else a bounded download, else the stale copy, else b""."""
    now = now or time.time()
    with _lock:
        fresh = cache.exists() and now - cache.stat().st_mtime < FRESH_S
        if not fresh and now - _state["failed_at"] > RETRY_AFTER_FAIL_S:
            if not _download(cache):
                _state["failed_at"] = now
        return cache.read_bytes() if cache.exists() else b""


class _Resp:
    def __init__(self, data: bytes):
        self._data, self.content, self.status_code = data, data, 200

    def read(self) -> bytes:
        return self._data

    def raise_for_status(self) -> None:
        return None


class _RequestsShim:
    """Stands in for `requests` inside get_stock_script_list only (it re-downloads the same file)."""
    def __init__(self, real, data: bytes):
        self._real, self._data = real, data

    def get(self, url, *a, **k):
        return _Resp(self._data) if url == URL else self._real.get(url, *a, **k)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _empty_zip() -> bytes:
    import zipfile
    buf = io.BytesIO()
    zipfile.ZipFile(buf, "w").close()
    return buf.getvalue()


def _import_breeze():
    """Import breeze_connect with its import-time download (module line `resp = urlopen(SECURITY_MASTER_URL)`, no
    timeout) answered from the cache, then restore urllib. Returns the module, or None if not installed."""
    import sys
    import urllib.request as ur
    if "breeze_connect.breeze_connect" in sys.modules:
        return sys.modules["breeze_connect.breeze_connect"]
    data = master_bytes() or _empty_zip()
    real = ur.urlopen
    ur.urlopen = lambda url, *a, **k: _Resp(data) if url == URL else real(url, *a, **k)
    try:
        import breeze_connect.breeze_connect as bc
    except ImportError:
        return None
    finally:
        ur.urlopen = real
    bc.urlopen = real                  # the module bound our stand-in at import: give it the real one back
    return bc


def install() -> None:
    """Import Breeze without its blocking download and patch get_stock_script_list to use the cache (idempotent).
    Call it *before* `from breeze_connect import BreezeConnect`."""
    if _state["installed"]:
        return
    bc = _import_breeze()
    if bc is None:
        return
    original = bc.BreezeConnect.get_stock_script_list
    swap = threading.Lock()

    def cached_get_stock_script_list(self):
        data = master_bytes() or _empty_zip()   # no copy at all: an empty, valid zip keeps the session usable
        with swap:
            real_urlopen, real_requests = bc.urlopen, bc.requests
            bc.urlopen = lambda url, *a, **k: _Resp(data) if url == URL else real_urlopen(url, *a, **k)
            bc.requests = _RequestsShim(real_requests, data)
            try:
                return original(self)
            finally:
                bc.urlopen, bc.requests = real_urlopen, real_requests

    bc.BreezeConnect.get_stock_script_list = cached_get_stock_script_list
    _state["installed"] = True


def patch_socketio_wait(seconds: float = 20.0) -> None:
    """breeze-connect 1.0.69 hard-codes socketio wait_timeout=3 s; on this network the live-stream
    namespace handshake takes ~3.4 s, so ws_connect() always failed ("Failed to connect to live
    stream"). Raise the budget before any ws_connect. Idempotent (same marker as the catalog
    script's local copy, scripts/breeze_data_catalog.py, which stays untouched)."""
    import socketio
    if getattr(socketio.Client.connect, "_suryadhana_patched", False):
        return
    original = socketio.Client.connect

    def connect(self, *args, **kwargs):
        kwargs["wait_timeout"] = max(kwargs.get("wait_timeout") or 1, seconds)
        return original(self, *args, **kwargs)

    connect._suryadhana_patched = True  # type: ignore[attr-defined]
    socketio.Client.connect = connect
