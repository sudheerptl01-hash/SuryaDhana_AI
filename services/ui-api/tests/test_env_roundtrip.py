""".env writes read back exactly (desktop review RAPI-04 / SECREL-03) and keep the file's mode (SECREL-13).

Every value the validator accepts must come back unchanged from python-dotenv (load_dotenv / dotenv_values, the
reader of every service) AND from the plain parsers that strip one layer of quotes
(scripts/daily_session_refresh.read_env_file, routers/config.py); every other key must stay as it was. Values
that cannot be stored exactly are refused before anything changes."""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest
from dotenv import dotenv_values

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import icici_admin

ROOT = Path(__file__).resolve().parents[3]
# A realistic .env: the live layout's shape (values invented), with the posture key right after the ICICI block.
ENV_TEXT = ("# SuryaDhana\nREDIS_URL=redis://localhost:6379/0\nICICI_API_KEY=old-key\nICICI_API_SECRET=old-secret\n"
            "ICICI_SESSION_TOKEN=12345678\nICICI_PASSWORD=old pass\nEXECUTION_LIVE_ALLOWED=0\n"
            "TELEGRAM_BOT_TOKEN=123:abc\n")
KEYS = icici_admin.ICICI_ENV_KEYS


@pytest.fixture
def env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    env = tmp_path / ".env"
    env.write_text(ENV_TEXT)
    os.chmod(env, 0o600)
    monkeypatch.setattr(icici_admin, "find_env_file", lambda: env)
    return env


def _plain(path: Path) -> dict[str, str]:
    """scripts/daily_session_refresh.py read_env_file, verbatim logic."""
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            out[key.strip()] = val.strip().strip('"').strip("'")
    return out


ACCEPTED = ["AbC123xyz", "Secret #2026", "tab nbsp", "p@ss w0rd!#$%^&*()_+-=[]{}|;':,./<>?~`", "it's",
            "a'b'c", '"dq"', 'x"', '"x', " lead", "trail ", "a#b", "x$y", "$HOME", "back\\slash", "", "a=b=c",
            "ünïcødé-ok", "inside 'quotes' is fine unquoted", '"',
            # P13: these needed quoting AND held a ' or \ and were refused; double quotes or a single-quoted \ store
            # them exactly now
            "a #'b", " a\\b", "b\\ #", "it's #x", 'say "hi" #1']


@pytest.mark.parametrize("value", ACCEPTED)
def test_every_accepted_value_reads_back_exactly_everywhere(env_file: Path, value: str) -> None:
    before = dotenv_values(env_file)
    out = icici_admin.persist_env_updates({"ICICI_PASSWORD": value}, allowed_keys=KEYS)
    assert out["persisted"] is True
    after = dotenv_values(env_file)
    assert after["ICICI_PASSWORD"] == value                         # python-dotenv (every service)
    assert _plain(env_file)["ICICI_PASSWORD"] == value              # the plain parsers
    assert {k: v for k, v in after.items() if k != "ICICI_PASSWORD"} == \
           {k: v for k, v in before.items() if k != "ICICI_PASSWORD"}
    assert after["EXECUTION_LIVE_ALLOWED"] == "0" and after["TELEGRAM_BOT_TOKEN"] == "123:abc"


@pytest.mark.parametrize("value", ["AbC123xyz", "a#b", "it's", "x$y"])
def test_ordinary_values_keep_the_old_unquoted_line(env_file: Path, value: str) -> None:
    icici_admin.persist_env_updates({"ICICI_SESSION_TOKEN": value}, allowed_keys=KEYS)
    assert f"ICICI_SESSION_TOKEN={value}\n" in env_file.read_text()


@pytest.mark.parametrize("value", ["Ab${HOME}9", "${EXECUTION_LIVE_ALLOWED}", "x'", "'Quote1", "'", "'\"", " lead'",
                                   'a #\'b"c', " x\\", "a\\\\b #"])
def test_values_that_cannot_be_stored_exactly_are_refused_untouched(env_file: Path, value: str) -> None:
    with pytest.raises(icici_admin.EnvValueError) as exc:
        icici_admin.persist_env_updates({"ICICI_PASSWORD": value}, allowed_keys=KEYS)
    assert env_file.read_text() == ENV_TEXT
    assert str(exc.value).startswith("ICICI_PASSWORD ") and (len(value) < 4 or value not in str(exc.value))


def test_the_review_reproduction_no_longer_swallows_keys(env_file: Path) -> None:
    """RAPI-04's scratch cases: '"' and 'x"' used to merge the lines between them into one value (the
    EXECUTION_LIVE_ALLOWED line vanished); '"abc' then 'tok"' swallowed TELEGRAM_BOT_TOKEN and REDIS_URL. Now each
    is quoted so it reads back exactly, and nothing else moves.
    (ICICI_CLIENT_ID / ICICI_PASSWORD here: the raw-read keys accept unquoted values only, see below.)"""
    icici_admin.persist_env_updates({"ICICI_CLIENT_ID": '"', "ICICI_PASSWORD": 'x"'}, allowed_keys=KEYS)
    got = dotenv_values(env_file)
    assert got["ICICI_CLIENT_ID"] == '"' and got["ICICI_PASSWORD"] == 'x"' and got["EXECUTION_LIVE_ALLOWED"] == "0"
    out = icici_admin.persist_env_updates({"ICICI_CLIENT_ID": '"abc'}, allowed_keys=KEYS)
    assert out["persisted"] is True
    icici_admin.persist_env_updates({"ICICI_PASSWORD": 'tok"'}, allowed_keys=KEYS)
    got = dotenv_values(env_file)
    assert got["ICICI_CLIENT_ID"] == '"abc' and got["ICICI_PASSWORD"] == 'tok"'
    assert got["TELEGRAM_BOT_TOKEN"] == "123:abc" and got["REDIS_URL"] == "redis://localhost:6379/0"
    assert got["ICICI_API_SECRET"] == "old-secret" and got["EXECUTION_LIVE_ALLOWED"] == "0"


def test_the_raw_format_would_have_lost_the_lines(tmp_path: Path) -> None:
    """Negative control: the pre-fix writer's f'{key}={value}' for the same two values."""
    raw = tmp_path / "raw.env"
    raw.write_text(ENV_TEXT.replace("ICICI_API_KEY=old-key", 'ICICI_API_KEY="abc')
                   .replace("ICICI_SESSION_TOKEN=12345678", 'ICICI_SESSION_TOKEN=tok"'))
    got = dotenv_values(raw)
    assert got.get("ICICI_API_SECRET") != "old-secret"


def test_a_read_back_mismatch_keeps_the_old_file(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Defence in depth: if a line were ever written in a form that reads back differently, .env is not replaced."""
    monkeypatch.setattr(icici_admin, "env_line", lambda k, v: f"{k}={v} #oops")
    out = icici_admin.persist_env_updates({"ICICI_PASSWORD": "fine"}, allowed_keys=KEYS)
    assert out == {"persisted": False, "path": str(env_file), "reason": "ICICI_PASSWORD would not read back exactly (plain parser)"}
    assert env_file.read_text() == ENV_TEXT and not list(env_file.parent.glob(".env*.tmp"))


def test_a_change_to_another_key_keeps_the_old_file(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file.write_text(ENV_TEXT + "DERIVED=${ICICI_PASSWORD}\n")
    out = icici_admin.persist_env_updates({"ICICI_PASSWORD": "new"}, allowed_keys=KEYS)
    assert out["persisted"] is False and out["reason"] == "DERIVED would change"
    assert "DERIVED=${ICICI_PASSWORD}" in env_file.read_text() and "ICICI_PASSWORD=old pass" in env_file.read_text()


@pytest.mark.parametrize("mode", [0o600, 0o640, 0o644])
def test_the_file_keeps_its_permission_bits(env_file: Path, mode: int) -> None:
    os.chmod(env_file, mode)
    icici_admin.persist_env_updates({"ICICI_SESSION_TOKEN": "fresh"}, allowed_keys=KEYS)
    assert stat.S_IMODE(env_file.stat().st_mode) == mode


def test_the_old_writer_did_widen_a_private_file(tmp_path: Path) -> None:
    """Negative control for SECREL-13: write_text + replace creates the new inode with the umask default."""
    env = tmp_path / ".env"
    env.write_text("A=1\n")
    os.chmod(env, 0o600)
    tmp = env.with_name(".env.tmp")
    old_umask = os.umask(0o022)
    try:
        tmp.write_text("A=2\n")
        tmp.replace(env)
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(env.stat().st_mode) == 0o644


def test_the_plain_parser_here_is_the_scripts_one() -> None:
    """Drift guard: _plain mirrors scripts/daily_session_refresh.py read_env_file and icici_admin.plain_env_value."""
    src = (ROOT / "scripts" / "daily_session_refresh.py").read_text(encoding="utf-8")
    assert "out[key.strip()] = val.strip().strip('\"').strip(\"'\")" in src
    assert icici_admin.plain_env_value("  'x'  ") == "x" and icici_admin.plain_env_value('"y"') == "y"


# ── P13 (round 4a): raw-read keys, the swallow guard, creating a new .env 0600 ─────────────────────────────────

def _raw(path: Path) -> dict[str, str]:
    """scripts/fetch_all_icici.py / scripts/icici_session_helper.py: the text after '=' with .strip() only."""
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            out[key.strip()] = val.strip()
    return out


@pytest.mark.parametrize("key", sorted(icici_admin.RAW_READ_ENV_KEYS))
@pytest.mark.parametrize("value", ["AbC123xyz", "5g8A9~13!5O60Z59@3Q#4+56I5n%P1&", "x$y", "a=b", "it's"])
def test_raw_read_keys_are_stored_unquoted_and_read_back_by_every_parser(env_file: Path, key: str, value: str) -> None:
    out = icici_admin.persist_env_updates({key: value}, allowed_keys=KEYS)
    assert out["persisted"] is True and f"{key}={value}\n" in env_file.read_text()
    assert dotenv_values(env_file)[key] == value and _plain(env_file)[key] == value and _raw(env_file)[key] == value


@pytest.mark.parametrize("key", sorted(icici_admin.RAW_READ_ENV_KEYS))
@pytest.mark.parametrize("value", ["Secret #2026", " lead", "trail ", '"dq"', "x'"])
def test_raw_read_keys_refuse_values_that_need_quoting(env_file: Path, key: str, value: str) -> None:
    with pytest.raises(icici_admin.EnvValueError, match="must fit unquoted") as exc:
        icici_admin.persist_env_updates({key: value}, allowed_keys=KEYS)
    assert env_file.read_text() == ENV_TEXT
    assert str(exc.value) == f"{key} {icici_admin._unstorable_reason(key)}"            # names the key, never the value


def test_quoting_a_raw_read_key_would_have_misled_the_raw_scripts(tmp_path: Path) -> None:
    """Negative control: the quoted form python-dotenv reads correctly still carries its quotes for the raw scripts."""
    env = tmp_path / ".env"
    env.write_text("ICICI_API_SECRET='Secret #2026'\n")
    assert dotenv_values(env)["ICICI_API_SECRET"] == "Secret #2026" and _raw(env)["ICICI_API_SECRET"] == "'Secret #2026'"


def test_the_readback_check_also_runs_the_raw_parser(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(icici_admin, "env_line", lambda k, v: f"{k}='{v}'")
    out = icici_admin.persist_env_updates({"ICICI_API_KEY": "fine"}, allowed_keys=KEYS)
    assert out["persisted"] is False and out["reason"] == "ICICI_API_KEY would not read back exactly (raw parser)"
    assert env_file.read_text() == ENV_TEXT


def test_a_quote_that_would_swallow_the_next_lines_is_refused(env_file: Path) -> None:
    """" x\\" single-quoted reads back fine ALONE (python-dotenv backtracks at the end of the text), but in a real
    file its \\' runs on to the next quote and eats the lines between. The sentinel lines catch that."""
    with pytest.raises(icici_admin.EnvValueError):
        icici_admin.persist_env_updates({"ICICI_PASSWORD": " x\\"}, allowed_keys=KEYS)
    assert env_file.read_text() == ENV_TEXT


def test_the_swallow_is_real_without_the_sentinels(tmp_path: Path) -> None:
    """Negative control for the test above."""
    alone, in_file = tmp_path / "alone.env", tmp_path / "in_file.env"
    alone.write_text("ICICI_PASSWORD=' x\\'\n")
    in_file.write_text("ICICI_PASSWORD=' x\\'\nTELEGRAM_BOT_TOKEN='123:abc'\n")
    assert dotenv_values(alone)["ICICI_PASSWORD"] == " x\\"
    assert dotenv_values(in_file).get("TELEGRAM_BOT_TOKEN") != "123:abc"


def test_a_named_env_file_that_is_missing_is_created_0600(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(icici_admin, "find_env_file", lambda: pytest.fail("env_path given: no search"))
    env = tmp_path / ".env"
    old_umask = os.umask(0o022)
    try:
        out = icici_admin.persist_env_updates({"ICICI_PASSWORD": "Secret #2026"}, env_path=env)
    finally:
        os.umask(old_umask)
    assert out == {"persisted": True, "path": str(env)}
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert dotenv_values(env) == {"ICICI_PASSWORD": "Secret #2026"} and _plain(env) == {"ICICI_PASSWORD": "Secret #2026"}


def test_a_named_env_file_keeps_its_mode_and_other_lines(env_file: Path) -> None:
    os.chmod(env_file, 0o600)
    icici_admin.persist_env_updates({"ICICI_SESSION_TOKEN": "99887766"}, env_path=env_file)
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert env_file.read_text() == ENV_TEXT.replace("ICICI_SESSION_TOKEN=12345678", "ICICI_SESSION_TOKEN=99887766")


def test_without_a_named_file_and_no_env_found_nothing_is_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(icici_admin, "find_env_file", lambda: None)
    monkeypatch.chdir(tmp_path)
    assert icici_admin.persist_env_updates({"ICICI_PASSWORD": "x"}) == {"persisted": False, "path": None}
    assert list(tmp_path.iterdir()) == []


def test_public_error_kinds() -> None:
    assert [icici_admin.public_error_kind(k) for k in ("session_expired", "network", "credentials", "other", None)] == \
        ["expired", "network", "credentials", "unknown", "unknown"]
    assert set(icici_admin.PUBLIC_ERROR_KINDS) == {"expired", "network", "credentials", "unknown"}


# ── a save may REPAIR a .env the pre-fix raw writer corrupted (round 3 review, minor) ─────────────────────────

# What the old f'{key}={value}' writer left behind for a key ending in a stray quote: python-dotenv reads the open
# quote as a multi-line value and swallows the lines up to the next quote, so those keys have no value at all.
CORRUPT = ('A=1\nICICI_API_KEY="abc\nTELEGRAM_BOT_TOKEN=tg\nREDIS_URL=redis://x\nICICI_SESSION_TOKEN=tok"\nZ=2\n')


def test_a_save_repairs_a_file_the_raw_writer_corrupted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text(CORRUPT)
    monkeypatch.setattr(icici_admin, "find_env_file", lambda: env)
    before = dotenv_values(env)
    assert before.get("TELEGRAM_BOT_TOKEN") is None and before.get("REDIS_URL") is None       # the corruption
    out = icici_admin.persist_env_updates({"ICICI_API_KEY": "newkey"}, allowed_keys=KEYS)
    assert out == {"persisted": True, "path": str(env)}
    after = dotenv_values(env)
    assert after["ICICI_API_KEY"] == "newkey" and after["TELEGRAM_BOT_TOKEN"] == "tg" and after["REDIS_URL"] == "redis://x"
    assert after["A"] == "1" and after["Z"] == "2"                                             # nothing else moved
    # the token line the old writer wrote is visible again: the next paste replaces it as usual
    icici_admin.persist_env_updates({"ICICI_SESSION_TOKEN": "fresh-token"}, allowed_keys=KEYS)
    assert dotenv_values(env)["ICICI_SESSION_TOKEN"] == "fresh-token"


def test_a_repair_never_switches_on_a_protected_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    text = 'A=1\nICICI_API_KEY="abc\nEXECUTION_LIVE_ALLOWED=1\nICICI_SESSION_TOKEN=tok"\n'
    env.write_text(text)
    monkeypatch.setattr(icici_admin, "find_env_file", lambda: env)
    assert dotenv_values(env).get("EXECUTION_LIVE_ALLOWED") is None
    out = icici_admin.persist_env_updates({"ICICI_API_KEY": "newkey"}, allowed_keys=KEYS)
    assert out == {"persisted": False, "path": str(env), "reason": "EXECUTION_LIVE_ALLOWED would appear"}
    assert env.read_text() == text and not list(tmp_path.glob(".env*.tmp"))


def test_a_value_held_today_still_may_not_change_or_vanish(tmp_path: Path) -> None:
    """The relaxation is only for keys that APPEAR: a key that has a value today and would lose it or get another
    one still keeps the old file (the DERIVED test above covers a change through interpolation)."""
    before, after = tmp_path / "before.env", tmp_path / "after.env"
    before.write_text("A=1\nB=2\nK=old\n")
    for text, reason in (("A=1\nK=new\n", "B would change"),            # B vanished
                         ("A=1\nB=3\nK=new\n", "B would change"),      # B changed
                         ("A=1\nB=2\nK=new\nC=3\n", None),            # C appeared: allowed
                         ("A=1\nB=2\nK=new\nGUARD_ALLOW_REMOTE_WRITES=1\n", "GUARD_ALLOW_REMOTE_WRITES would appear")):
        after.write_text(text)
        assert icici_admin._readback_problem(before, after, text, {"K": "new"}) == reason, text


# ── each writer has its own temp file (round 4a review of F4-API, minor) ─────────────────────────────────────

def test_two_processes_writing_at_once_never_share_a_temp_file(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ui-api and master-controller both call persist_env_updates; the per-process lock does not cover the other
    process. Writer B (another process, simulated) runs while writer A sits between its temp write and its read-back:
    with one shared '.env.tmp' B truncated and renamed A's temp file. Now each has its own, and both saves land."""
    seen: list[Path] = []
    real = icici_admin._readback_problem
    inner_done: list[dict] = []
    started: list[bool] = []

    def readback(before: Path, after: Path, after_text: str, updates: dict[str, str]) -> str | None:
        seen.append(after)
        if not started:                                        # writer A: let "process B" write now
            started.append(True)
            assert after.exists()                              # A's temp file is in place while B writes
            inner_done.append(_other_process_write(env_file))
            assert after.read_text() == after_text            # B did not truncate or rename A's temp file
        return real(before, after, after_text, updates)
    monkeypatch.setattr(icici_admin, "_readback_problem", readback)
    out = icici_admin.persist_env_updates({"ICICI_SESSION_TOKEN": "from-ui-api"}, allowed_keys=KEYS)
    assert inner_done == [{"persisted": True, "path": str(env_file)}]
    assert len(set(seen)) == 2 and all(p.parent == env_file.parent and p.name.startswith(".env.") for p in seen)
    # A's read-back sees B's newer file and refuses rather than undo B's save (no silent lost update)
    assert out == {"persisted": False, "path": str(env_file), "reason": "ICICI_PASSWORD would change"}
    assert dotenv_values(env_file)["ICICI_PASSWORD"] == "from-controller"
    assert not list(env_file.parent.glob(".env*.tmp"))


def _other_process_write(env_file: Path) -> dict:
    """What master-controller's /password does, from 'another process': its own lock object, the same file."""
    import threading
    lock = icici_admin._ENV_WRITE_LOCK
    icici_admin._ENV_WRITE_LOCK = threading.Lock()                # the other process's lock: not the one held now
    try:
        return icici_admin.persist_env_updates({"ICICI_PASSWORD": "from-controller"}, env_path=env_file)
    finally:
        icici_admin._ENV_WRITE_LOCK = lock


def test_the_temp_file_is_private_and_removed_when_the_write_fails(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    modes: list[int] = []

    def boom(before: Path, after: Path, after_text: str, updates: dict[str, str]) -> str | None:
        modes.append(stat.S_IMODE(after.stat().st_mode))
        raise RuntimeError("disk full")
    monkeypatch.setattr(icici_admin, "_readback_problem", boom)
    with pytest.raises(RuntimeError):
        icici_admin.persist_env_updates({"ICICI_SESSION_TOKEN": "x"}, allowed_keys=KEYS)
    assert modes == [0o600] and env_file.read_text() == ENV_TEXT and not list(env_file.parent.glob(".env*.tmp"))
