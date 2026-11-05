"""G8 on the three REAL apps: ``/metrics`` 200 with the named series on data-service (:8001), ui-api (:8010) and
master-controller (:8008); ``X-Request-ID`` echoed; the JSON access log excludes ``/health`` but logs an ordinary request
with that service's name and the request id. B7's ``tests/arch/test_metrics_middleware.py`` proves the middleware on a
synthetic app; this proves each service actually installs it.

Each app is imported in its own subprocess (the three share module names such as ``main`` and ``routers``, and each sets the
process's logging service name), through ``TestClient`` without the lifespan: no DuckDB, no scheduler, no Telegram, no
ICICI, no network; every state file ui-api could write is pointed at a temp dir. Negative control: the same harness on a
bare FastAPI app (no ``install_observability``) reports every rule broken."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SERIES = ("sd_http_requests_total", "sd_http_request_seconds", "sd_http_inflight", "sd_duckdb_lock_wait_seconds",
          "sd_job_seconds", "sd_cache_events_total", "sd_breeze_budget_used", "sd_upstream_requests_total",
          "sd_upstream_breaker_open", "sd_feed_lag_seconds")
MARK = "G8RESULT "

LOADERS: dict[str, str] = {
    "data-service": """
        sys.path[:0] = [ROOT, os.path.join(ROOT, "services", "data-service")]
        spec = importlib.util.spec_from_file_location("data_service_main_g8",
                                                      os.path.join(ROOT, "services", "data-service", "main.py"))
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); app = mod.app
    """,
    "ui-api": """
        sys.path[:0] = [ROOT, os.path.join(ROOT, "services", "ui-api")]
        os.chdir(os.path.join(ROOT, "services", "ui-api"))
        spec = importlib.util.spec_from_file_location("ui_api_main_g8", os.path.join(ROOT, "services", "ui-api", "main.py"))
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); app = mod.app
    """,
    "master-controller": """
        sys.path[:0] = [ROOT, os.path.join(ROOT, "scripts")]
        import master_controller as mod; app = mod.app
    """,
    "bare (negative control)": """
        from fastapi import FastAPI
        app = FastAPI()
        @app.get("/health")
        def _h(): return {"status": "ok"}
    """,
}
PORTS = {"data-service": 8001, "ui-api": 8010, "master-controller": 8008, "bare (negative control)": 8099}

DRIVER = """
import importlib.util, json, os, sys
ROOT = {root!r}
{loader}
from fastapi.testclient import TestClient
c = TestClient(app, raise_server_exceptions=False)
h = {{"host": "127.0.0.1:{port}"}}
r_health = c.get("/health", headers={{**h, "x-request-id": "g8-health-1"}})
r_miss = c.get("/g8/not-a-route", headers={{**h, "x-request-id": "g8-miss-1"}})
r_metrics = c.get("/metrics", headers=h)
out = {{"health": r_health.status_code, "health_rid": r_health.headers.get("x-request-id"),
       "miss": r_miss.status_code, "miss_rid": r_miss.headers.get("x-request-id"),
       "metrics": r_metrics.status_code, "metrics_ct": r_metrics.headers.get("content-type", ""),
       "metrics_body": r_metrics.text if r_metrics.status_code == 200 else ""}}
sys.stdout.flush()
print({mark!r} + json.dumps(out), flush=True)
"""


def run_service(name: str, tmp: Path) -> dict[str, Any]:
    code = DRIVER.format(root=str(ROOT), loader=textwrap.dedent(LOADERS[name]), port=PORTS[name], mark=MARK)
    env = {**os.environ, "ALERTS_PATH": str(tmp / "alerts.json"), "GOLD_LOG_PATH": str(tmp / "gold_log.json"),
           "PREFS_DB": str(tmp / "prefs.sqlite"), "PAPER_TRADES_DB": str(tmp / "paper.db"),
           "BREEZE_BUDGET_DB": str(tmp / "breeze_budget.sqlite"), "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("SD_ACCESS_LOG", None)
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180, env=env, cwd=str(tmp))
    lines = p.stdout.splitlines()
    res = next((json.loads(ln[len(MARK):]) for ln in reversed(lines) if ln.startswith(MARK)), None)
    if res is None:
        raise AssertionError(f"{name}: no result (exit {p.returncode}); stderr tail: {p.stderr[-1500:]}")
    access = []
    for ln in lines:
        if ln.startswith("{"):
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if d.get("event") == "http.access":
                access.append(d)
    res["access"] = access
    return res


def problems(service: str, res: dict[str, Any]) -> list[str]:
    """Every G8 rule the result breaks (empty = the gate holds)."""
    out: list[str] = []
    if res.get("metrics") != 200:
        out.append(f"/metrics answered {res.get('metrics')}")
    else:
        if not str(res.get("metrics_ct", "")).startswith("text/plain"):
            out.append(f"/metrics content-type {res.get('metrics_ct')}")
        body = res.get("metrics_body", "")
        missing = [s for s in SERIES if s not in body]
        if missing:
            out.append(f"/metrics lacks {missing}")
        if f'service="{service}"' not in body:
            out.append(f"/metrics carries no service=\"{service}\" label")
    if res.get("health") != 200:
        out.append(f"/health answered {res.get('health')}")
    if res.get("health_rid") != "g8-health-1" or res.get("miss_rid") != "g8-miss-1":
        out.append(f"X-Request-ID not echoed ({res.get('health_rid')}, {res.get('miss_rid')})")
    paths = [a.get("path") for a in res.get("access", [])]
    if "/health" in paths or "/metrics" in paths:
        out.append("the access log carries /health or /metrics")
    hit = next((a for a in res.get("access", []) if a.get("path") == "/g8/not-a-route"), None)
    if hit is None:
        out.append("the access log has no line for an ordinary request")
    elif hit.get("service") != service or hit.get("correlation_id") != "g8-miss-1" or hit.get("status") != 404:
        out.append(f"access line mislabelled: service={hit.get('service')} cid={hit.get('correlation_id')} "
                   f"status={hit.get('status')}")
    return out


@pytest.mark.parametrize("service", ["data-service", "ui-api", "master-controller"])
def test_g8_metrics_request_id_and_access_log_on_the_real_app(service: str, tmp_path: Path):
    res = run_service(service, tmp_path)
    found = problems(service, res)
    assert not found, f"{service}: {found}"


def test_g8_negative_control_a_bare_app_breaks_every_rule(tmp_path: Path):
    res = run_service("bare (negative control)", tmp_path)
    found = problems("bare (negative control)", res)
    assert any("/metrics answered 404" in p for p in found), found
    assert any("X-Request-ID not echoed" in p for p in found), found
    assert any("no line for an ordinary request" in p for p in found), found


def test_g8_checker_negative_controls_on_synthetic_results():
    good = {"metrics": 200, "metrics_ct": "text/plain; version=0.0.4", "health": 200, "health_rid": "g8-health-1",
            "miss": 404, "miss_rid": "g8-miss-1",
            "metrics_body": " ".join(SERIES) + ' service="svc"',
            "access": [{"path": "/g8/not-a-route", "service": "svc", "correlation_id": "g8-miss-1", "status": 404}]}
    assert problems("svc", good) == []
    leaky = {**good, "access": good["access"] + [{"path": "/health", "service": "svc"}]}
    assert problems("svc", leaky) == ["the access log carries /health or /metrics"]
    other = {**good, "access": [{**good["access"][0], "service": "data-service"}]}       # the 5 Nov mislabel bug
    assert any("mislabelled" in p for p in problems("svc", other))
    thin = {**good, "metrics_body": "sd_http_requests_total"}
    assert any("lacks" in p for p in problems("svc", thin))
