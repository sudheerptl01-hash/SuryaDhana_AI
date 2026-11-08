"""reports/terminal_v2/API_CONTRACT.md ↔ the B3 routers, kept equal by this test (Terminal v2 Wave 1; the gold pattern).

The contract's §8 ("Key inventory") is GENERATED from the fixture payloads of test_terminal_v2_api.py: every route is
called under the fake transport (data-service / master-controller mocked, Breeze faked, the real-format SPAN subset
zipped), every key path and its value types are collected, and the rendered block must equal the one in the document.
When the implementation changes, regenerate with

    TERMINAL_CONTRACT_WRITE=1 python -m pytest services/ui-api/tests/test_terminal_v2_contract.py -q

and commit both. §0–§7 are hand-written semantics; §8 is the exact shape, so a renamed or dropped key never ships
undocumented.
"""
from __future__ import annotations

import os
import re
import sys
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _terminal_v2_fixtures as fx  # noqa: E402
import routers.derivatives as drv  # noqa: E402
import routers.markets as mk  # noqa: E402
import routers.options_strategy as osr  # noqa: E402
from shared import breeze_budget as bb  # noqa: E402

CONTRACT = fx.REPO / "reports" / "terminal_v2" / "API_CONTRACT.md"
BEGIN, END = "<!-- generated: key inventory — begin -->", "<!-- generated: key inventory — end -->"

# (name, method, path, query, json) — one representative call per route and mode (the fixture decides the values; the keys are the contract)
ROUTES: list[tuple[str, str, str, dict[str, Any], dict[str, Any] | None]] = [
    ("iv_history", "GET", "/api/derivatives/iv/NIFTY", {"days": 300}, None),
    ("iv_surface", "GET", "/api/derivatives/iv/NIFTY/surface", {"compare": "1m"}, None),
    ("iv_cone", "GET", "/api/derivatives/iv/NIFTY/cone", {}, None),
    ("iv_events", "GET", "/api/derivatives/iv/INFY/events", {"n": 8}, None),
    ("iv_intraday", "GET", "/api/derivatives/iv/NIFTY/intraday", {}, None),
    ("vol_screen", "GET", "/api/derivatives/vol-screen", {"sort": "iv_pctile", "results_within": 10}, None),
    ("option_history_legacy", "GET", "/api/market/option-history/NIFTY", {}, None),
    ("index_drivers", "GET", "/api/market/index-drivers", {"index": "NIFTY 50", "horizon": "1m"}, None),
    ("index_drivers_timeline", "GET", "/api/market/index-drivers/timeline", {"window": 20, "days": 250}, None),
    ("index_drivers_monthly", "GET", "/api/market/index-drivers/monthly", {"months": 12}, None),
    ("desk_attribution_risk_off", "GET", "/api/desk/attribution", {"horizon": "1m"}, None),
    ("margin_breeze", "POST", "/api/options/margin", {}, {"symbol": "NIFTY", "legs": fx.CONDOR_LEGS, "sources": "breeze"}),
    ("margin_span_file", "POST", "/api/options/margin", {}, {"symbol": "NIFTY", "legs": fx.CONDOR_LEGS, "sources": "span_file"}),
    ("margin_heuristic", "POST", "/api/options/margin", {}, {"symbol": "NIFTY", "forward": 23931.0, "legs": fx.CONDOR_LEGS, "sources": "heuristic"}),
    ("data_health", "GET", "/api/data/health", {}, None),
    ("breeze_budget", "GET", "/api/positions/breeze-budget", {}, None),
]
# maps whose keys are DATA (callers, methods, expiries, paths), folded to {*} so the inventory names the shape, not the fixture
DATA_KEYED = {"by_caller", "by_method", "quotas", "net_delta_by_expiry", "store_errors", "inputs_unavailable", "scan_ranges", "stored"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[TestClient]:
    import routers.positions as pos

    fx.install_fake_transport(monkeypatch)
    monkeypatch.setenv(bb.ENV_DB, str(tmp_path / "budget.sqlite"))
    bb.reset_ledger()
    osr._SPAN_CACHE.clear()
    monkeypatch.setenv(osr.SPAN_DIR_ENV, str(fx.span_zip(tmp_path)))

    class FakeBreeze:
        def margin_calculator(self, lists: list[dict[str, str]], exchange_code: str) -> dict[str, Any]:
            return fx.BREEZE_MARGIN_SAMPLE

    monkeypatch.setattr(pos, "_get_breeze_client", lambda: (FakeBreeze(), None))

    async def cash() -> dict[str, Any]:
        return fx.DESK_STATUS_CASH

    monkeypatch.setattr(mk, "_desk_status", cash)
    # §8 must not move with the calendar: /vol-screen?results_within=10 keeps names reporting within N days of TODAY, so
    # the recorded JSON types changed as days passed (8 Nov 2026: the inventory generated on 6 Nov no longer matched).
    monkeypatch.setattr(drv, "_today", lambda: date(2026, 11, 6))
    yield TestClient(fx.make_app())
    bb.reset_ledger()


def _type_of(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object"


_DATA_KEY = re.compile(r"^(\d{4}-\d{2}-\d{2}|\d{8}|[A-Z][A-Z0-9&\-]{2,}|[a-z0-9_\-]+\.[a-z0-9_.\-/]+|/db/.*)$")


def _looks_like_data_key(k: Any) -> bool:
    return isinstance(k, str) and bool(_DATA_KEY.match(k))


def key_paths(value: Any, prefix: str = "", out: dict[str, set[str]] | None = None) -> dict[str, set[str]]:
    """{path → {types}} over a payload; list elements merge under `path[]`; data-keyed maps fold to `{*}`."""
    out = {} if out is None else out
    if isinstance(value, dict):
        keys = list(value.keys())
        leaf = prefix.rsplit(".", 1)[-1]
        data_keyed = leaf in DATA_KEYED or (bool(keys) and all(_looks_like_data_key(k) for k in keys))
        for k, v in value.items():
            p = f"{prefix}.{{*}}" if data_keyed else (f"{prefix}.{k}" if prefix else str(k))
            out.setdefault(p, set()).add(_type_of(v))
            key_paths(v, p, out)
    elif isinstance(value, list):
        for v in value:
            p = f"{prefix}[]"
            out.setdefault(p, set()).add(_type_of(v))
            key_paths(v, p, out)
    return out


def inventory(client: TestClient) -> dict[str, dict[str, list[str]]]:
    inv: dict[str, dict[str, list[str]]] = {}
    for name, method, path, params, body in ROUTES:
        r = client.get(path, params=params) if method == "GET" else client.post(path, params=params, json=body)
        assert r.status_code == 200, f"{method} {path} {params}: {r.status_code} {r.text[:200]}"
        payload = r.json()
        if name.startswith("margin_"):
            assert payload["source"] == {"margin_breeze": "BREEZE", "margin_span_file": "NSE_SPAN_FILE", "margin_heuristic": "HEURISTIC"}[name]
        inv[name] = {p: sorted(t) for p, t in sorted(key_paths(payload).items())}
    return inv


def render(inv: dict[str, dict[str, list[str]]]) -> str:
    lines = [BEGIN, "",
             "Generated by `services/ui-api/tests/test_terminal_v2_contract.py` from the fixture payloads (pinned clock Thu 5 Nov 2026",
             "22:00 IST; the R-IV NIFTY run, a synthetic 3-member index, R-DATA §3's rows, the real-format SPAN subset). `path[]` = list",
             "element, `{*}` = data-keyed map (dates / symbols / callers / paths), types are the JSON types seen (`null` means the fixture",
             "had no value there). Regenerate with `TERMINAL_CONTRACT_WRITE=1`.", ""]
    for name, _method, path, params, body in ROUTES:
        q = ("?" + "&".join(f"{k}={v}" for k, v in params.items())) if params else ""
        b = f" body: {{symbol, legs[{len(body['legs'])}], sources={body['sources']}}}" if body else ""
        lines += [f"### `{name}` — `{_method} {path}{q}`{b}", "", "| key path | types |", "|---|---|"]
        lines += [f"| `{p}` | {', '.join(t)} |" for p, t in inv[name].items()]
        lines.append("")
    lines.append(END)
    return "\n".join(lines)


def _generated_block(text: str) -> str:
    i, j = text.find(BEGIN), text.find(END)
    assert i >= 0 and j > i, "API_CONTRACT.md lacks the generated-block markers"
    return text[i:j + len(END)]


def test_contract_inventory_matches_the_code(client: TestClient) -> None:
    rendered = render(inventory(client))
    text = CONTRACT.read_text(encoding="utf-8")
    if os.environ.get("TERMINAL_CONTRACT_WRITE") == "1":
        CONTRACT.write_text(text.replace(_generated_block(text), rendered), encoding="utf-8")
        text = CONTRACT.read_text(encoding="utf-8")
    assert _generated_block(text) == rendered, "API_CONTRACT.md §8 is out of date: TERMINAL_CONTRACT_WRITE=1 pytest …/test_terminal_v2_contract.py"


def test_contract_states_the_binding_rules() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    for needle in ("describes, does not predict", "No publisher on the request path", "signal", "PAPER", "breeze_budget",
                   "/api/derivatives/iv/{symbol}", "/api/market/index-drivers", "/api/desk/attribution", "POST /api/options/margin",
                   "/api/data/health", "4.8"):
        assert needle in text, needle


def test_every_route_in_the_inventory_carries_a_badge_or_badges(client: TestClient) -> None:
    for name, method, path, params, body in ROUTES:
        if name in ("option_history_legacy", "breeze_budget"):
            continue
        r = client.get(path, params=params) if method == "GET" else client.post(path, json=body)
        p = r.json()
        assert "badge" in p or "badges" in p, name
        flat = str(p)
        assert '"signal"' not in flat and "'signal'" not in flat, name          # no signal badge exists today (PLAN §0.1)
        assert "score" not in p, name
