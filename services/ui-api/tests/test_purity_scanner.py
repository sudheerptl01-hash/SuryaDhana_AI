"""scripts/check_event_loop.py meta-test (S2): the tree is clean AND the scanner
actually catches planted violations — so a green run means something."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCANNER = REPO / "scripts" / "check_event_loop.py"
PY = sys.executable

VIOLATOR = '''
import time
import pandas as pd
from db import get_conn

async def bad_handler():
    time.sleep(1)                       # 1: blocking sleep
    df = pd.read_parquet("big.parquet") # 2: parquet read on the loop
    with get_conn() as conn:            # 3: DuckDB accessor
        conn.execute("SELECT 1")        # 4: .execute in a get_conn module

async def good_handler():
    import asyncio
    def _worker():
        time.sleep(1)                   # fine: inside the to_thread worker
        return pd.read_parquet("big.parquet")
    return await asyncio.to_thread(_worker)
'''


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([PY, str(SCANNER), *args], capture_output=True, text=True, cwd=REPO)


def test_current_tree_is_clean():
    r = _run()
    assert r.returncode == 0, f"purity scan regressed:\n{r.stdout}{r.stderr}"
    assert "OK" in r.stdout


def test_scanner_catches_planted_violations(tmp_path):
    bad = tmp_path / "bad_module.py"
    bad.write_text(VIOLATOR)
    r = _run("--paths", str(bad), "--allowlist", str(tmp_path / "empty.txt"))
    assert r.returncode == 1, f"scanner missed planted violations:\n{r.stdout}"
    for needle in ("time.sleep", "pandas.read_parquet", "get_conn", "conn.execute"):
        assert needle in r.stdout, f"{needle} not flagged:\n{r.stdout}"
    # nested to_thread worker must NOT be flagged: exactly the 4 planted lines
    assert r.stdout.count("[NEW]") == 4, r.stdout
    assert "good_handler" not in r.stdout


def test_allowlist_suppresses_known_findings(tmp_path):
    bad = tmp_path / "bad_module.py"
    bad.write_text("import time\n\nasync def h():\n    time.sleep(1)\n")
    allow = tmp_path / "allow.txt"
    allow.write_text(f"{bad}::time.sleep::h\n")
    r = _run("--paths", str(bad), "--allowlist", str(allow))
    assert r.returncode == 0, r.stdout
    assert "[ALLOWED]" in r.stdout
