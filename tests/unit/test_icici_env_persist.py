"""persist_env_updates must keep exactly one line per key (re-pasting the same
ICICI session token used to append a duplicate line each time)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "services" / "ui-api"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import icici_admin  # noqa: E402


def _env(tmp_path, monkeypatch, text):
    env = tmp_path / ".env"
    env.write_text(text)
    monkeypatch.setattr(icici_admin, "find_env_file", lambda: env)
    return env


def test_same_value_does_not_duplicate(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch, "A=1\nICICI_SESSION_TOKEN=abc\nB=2\n")
    for _ in range(3):
        icici_admin.persist_env_updates({"ICICI_SESSION_TOKEN": "abc"})
    assert env.read_text().count("ICICI_SESSION_TOKEN=") == 1


def test_update_in_place_and_collapse_existing_duplicates(tmp_path, monkeypatch):
    env = _env(tmp_path, monkeypatch, "A=1\nICICI_SESSION_TOKEN=old\nB=2\nICICI_SESSION_TOKEN=old\n")
    icici_admin.persist_env_updates({"ICICI_SESSION_TOKEN": "new", "C": "3"})
    lines = env.read_text().splitlines()
    assert lines == ["A=1", "ICICI_SESSION_TOKEN=new", "B=2", "C=3"]
