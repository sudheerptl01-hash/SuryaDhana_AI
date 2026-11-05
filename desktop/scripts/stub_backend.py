"""Stub ui-api backend for the desktop shell's drills: no live stack is ever contacted.

    /Users/sudheer/Desktop/jupyter_env/bin/python desktop/scripts/stub_backend.py 18771 &
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/desktop_qa/scratch_server.py --ui <export dir> \
        --port 8095 --backend http://127.0.0.1:18771 --block-mutations
    desktop/scripts/relaunch_drill.sh --ui http://127.0.0.1:8095

It answers /health, /ready and /version like ui-api and gives every other request a JSON 404, so terminal pages
commit (all the relaunch drill checks) while the live ui-api sees no load at all. Loopback only.

/api/notifications/feed (round 3, K5) follows the F3-API contract the shell consumes (services/ui-api/routers/
notifications.py; desktop/src-tauri/src/feed.rs): string ids, `at_ms`, inclusive `since` (epoch ms), `next_since` =
newest at_ms - 60 s, `banner` false for inbox-only records. Without ?since= it lists two OLD events (a first start
must announce neither); with since it also returns one fresh event ("SELFTEST feed alert", id n-selftest-fresh, at
the time of the request: returned again by every later poll through the overlap, so the shell must de-duplicate
it), one two hours old (never shown) and one inbox-only wrap (never shown). The self-test's feed_notifications
check relies on this sequence.

Round 4b: /api/positions/connection-status answers as ui-api does during an ICICI outage (round 4a contract:
connected false, needs_session_refresh true, error_kind "network"), and /api/market/nifty-live returns a NIFTY print
stamped NOW in NSE's format, as during a session the calendar does not know (Muhurat): the self-test's
tray_icici_line and tray_fresh_print_is_live checks then exercise the outage wording and the "fresh data beats the
calendar" rule whatever the day. Neither touches ICICI or NSE.
"""
from __future__ import annotations

import datetime as dt
import http.server
import json
import sys
import urllib.parse

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def feed(query: str) -> dict:
    now = dt.datetime.now(IST)

    def ev(eid: str, t: dt.datetime, kind: str, title: str, banner: bool = True) -> dict:
        return {"id": eid, "at": t.isoformat(timespec="seconds"), "at_ms": int(t.timestamp() * 1000), "kind": kind,
                "title": title, "body": f"{title} (stub)", "source": "scheduler", "banner": banner, "tab": "alerts"}

    pool = [
        ev("n-selftest-replay-1", now - dt.timedelta(days=1), "wrap", "SELFTEST replay 1"),
        ev("n-selftest-replay-2", now - dt.timedelta(hours=20), "close", "SELFTEST replay 2"),
    ]
    raw = urllib.parse.parse_qs(query).get("since", [None])[0]
    since = int(raw) if raw and raw.isdigit() else None
    if since is not None:
        pool += [
            ev("n-selftest-fresh", now, "price", "SELFTEST feed alert"),
            ev("n-selftest-old", now - dt.timedelta(hours=2), "filing", "SELFTEST old alert"),
            ev("n-selftest-wrap", now, "wrap", "SELFTEST inbox wrap", banner=False),
        ]
    items = sorted((e for e in pool if since is None or e["at_ms"] >= since), key=lambda e: -e["at_ms"])
    newest = items[0]["at_ms"] if items else None
    next_since = max(newest - 60_000, since or 0) if newest is not None else since
    return {"items": items, "count": len(items), "truncated": False, "since": since, "next_since": next_since,
            "server_time_ms": int(now.timestamp() * 1000)}


def connection_status() -> dict:
    """ui-api's /api/positions/connection-status during an ICICI outage (no login_url, no secrets)."""
    return {"connected": False, "needs_session_refresh": True, "error_kind": "network", "status": "stub",
            "error": "ICICI's API could not be reached (network); this is not a login problem (stub)"}


def nifty_live() -> dict:
    """A NIFTY 50 print stamped now (IST, NSE's `23-Oct-2026 15:30:05` format)."""
    now = dt.datetime.now(IST)
    return {"index": "NIFTY 50", "last": 24180.5, "change": 96.3, "change_pct": 0.4, "open": 24100.0,
            "high": 24200.0, "low": 24050.0, "previous_close": 24084.2, "time": now.strftime("%d-%b-%Y %H:%M:%S")}


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path, _, query = self.path.partition("?")
        if path == "/api/notifications/feed":
            return self._send(200, feed(query))
        if path == "/api/positions/connection-status":
            return self._send(200, connection_status())
        if path == "/api/market/nifty-live":
            return self._send(200, nifty_live())
        if path == "/health":
            return self._send(200, {"status": "ok", "service": "ui-api"})
        if path == "/ready":
            return self._send(200, {"status": "ready", "service": "ui-api", "ui": "ok"})
        if path == "/version":
            return self._send(200, {"service": "ui-api", "version": "stub"})
        return self._send(404, {"detail": "stub backend (desktop drill)"})

    do_POST = do_PUT = do_PATCH = do_DELETE = do_GET

    def log_message(self, *args: object) -> None:
        pass


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18771
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
