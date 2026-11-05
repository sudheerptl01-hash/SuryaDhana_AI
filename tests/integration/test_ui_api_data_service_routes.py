"""Every data-service path ui-api reads must be a route data-service serves.

5 Nov 2026: ui-api read ``/db/iv/*`` and ``/db/index-drivers/{contribution,fit,state,weights}`` (API_CONTRACT §6) while
data-service served ``/db/fo-iv/*`` and the derived ``/db/index-drivers`` only. Each side's tests passed against its own
fakes, and OMON / DERV / EVTS / MEMB / DESK read OFFLINE "no tables yet (404)" with the tables populated. This gate reads
both trees statically (no imports, no network): ui-api's data-service URLs against data-service's route decorators.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DS = ROOT / "services" / "data-service"
UI = ROOT / "services" / "ui-api"

_ROUTE = re.compile(r'@\w+\.(?:get|post|put|delete|patch|api_route|websocket)\(\s*f?"(/[^"]*)"')
# a data-service path in ui-api: right after a quote ("/db/…") or after the base-URL placeholder (f"{data_svc()}/db/…")
_CALL = re.compile(r'(?:f?"|\})(/(?:db|live|jobs)/[A-Za-z0-9_\-/{}.]*)')
# the drivers' reader builds f"/db/index-drivers/{table}" from these literal table names
_DRIVER_TABLE = re.compile(r'reads\.get\("([a-z_]+)"')


def data_service_routes(root: Path = DS) -> list[re.Pattern[str]]:
    paths: set[str] = set()
    for f in root.rglob("*.py"):
        if "tests" in f.parts or "__pycache__" in f.parts:
            continue
        paths.update(m.group(1) for m in _ROUTE.finditer(f.read_text(encoding="utf-8", errors="ignore")))
    return [re.compile("^" + re.sub(r"\{[^}]+:path\}", ".+", re.sub(r"\{[^}:]+\}", "[^/]+", p)) + "$") for p in paths]


def ui_api_calls(files: list[Path]) -> dict[str, set[str]]:
    calls: dict[str, set[str]] = {}

    def add(path: str, f: Path, text: str, at: int) -> None:
        calls.setdefault(path, set()).add(f"{f.relative_to(ROOT) if f.is_relative_to(ROOT) else f.name}:{text[:at].count(chr(10)) + 1}")

    for f in files:
        s = f.read_text(encoding="utf-8", errors="ignore")
        for m in _CALL.finditer(s):
            line = s[s.rfind("\n", 0, m.start()) + 1: m.start()]
            if line.lstrip().startswith("@"):
                continue                              # ui-api's own route decorator, not a call
            p = m.group(1)
            if p.rstrip("/").endswith("{table}"):
                continue                              # expanded from the literal table names below
            add(re.sub(r"\{[^}]*\}", "X", p).rstrip("/") or p, f, s, m.start())
        if "_DriverReads" in s:
            for m in _DRIVER_TABLE.finditer(s):
                add(f"/db/index-drivers/{m.group(1)}", f, s, m.start())
    return calls


def _ui_files() -> list[Path]:
    return sorted([*UI.glob("*.py"), *(UI / "routers").rglob("*.py")])


def missing(calls: dict[str, set[str]], routes: list[re.Pattern[str]]) -> dict[str, set[str]]:
    return {p: w for p, w in calls.items() if not any(r.match(p) for r in routes)}


def test_every_data_service_path_ui_api_reads_is_served() -> None:
    routes = data_service_routes()
    calls = ui_api_calls(_ui_files())
    assert len(routes) > 100 and len(calls) > 60, (len(routes), len(calls))      # the scan found both trees
    for must in ("/db/iv/summary", "/db/iv/surface", "/db/index-drivers/contribution", "/db/index-drivers/state", "/live/quotes"):
        assert must in calls, f"the scan no longer sees ui-api's {must} read"
    gone = missing(calls, routes)
    assert not gone, "ui-api reads data-service paths that no data-service route serves:\n" + "\n".join(
        f"  {p}  ← {', '.join(sorted(w)[:3])}" for p, w in sorted(gone.items()))


def test_negative_control_a_renamed_route_is_caught(tmp_path: Path) -> None:
    """The 5 Nov shape: ui-api reads /db/iv/summary, data-service serves only /db/fo-iv/summary/{symbol}."""
    ds = tmp_path / "ds"
    ds.mkdir()
    (ds / "api.py").write_text('@router.get("/db/fo-iv/summary/{symbol}")\ndef a(): ...\n@router.get("/db/index-drivers")\ndef b(): ...\n')
    ui = tmp_path / "derivatives.py"
    ui.write_text('class _DriverReads: ...\n'
                  'async def f(reads):\n'
                  '    await reads.get("/db/iv/summary", symbol="NIFTY")\n'
                  '    await reads.get("contribution", index="NIFTY 50")\n'
                  '    await get_json(f"{data_svc()}/db/fo-iv/summary/{sym}")\n'
                  '@router.get("/db/own-route")\n'
                  'async def own(): ...\n')
    gone = missing(ui_api_calls([ui]), data_service_routes(ds))
    assert set(gone) == {"/db/iv/summary", "/db/index-drivers/contribution"}, gone     # the f-string call matches; the decorator is skipped
