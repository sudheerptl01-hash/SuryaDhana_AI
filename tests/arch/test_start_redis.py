"""Wave 0.7 (O-T10): ``start-local.sh start_redis`` binds Redis to 127.0.0.1 and sets ``requirepass`` from REDIS_PASSWORD
(.env) or the Keychain item, never on argv, and exports a REDIS_URL carrying the password for the services it starts.
Negative controls: no password → no requirepass and no password in the URL; a Redis already running without the
configured password is reported, not silently assumed. The script is sourced from a throwaway tree with ``lsof``,
``redis-server``, ``redis-cli`` and ``security`` replaced by recording shims on PATH."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASH = "/bin/bash"


def _shim(bin_dir: Path, name: str, body: str) -> None:
    p = bin_dir / name
    p.write_text("#!/bin/bash\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / ".logs").mkdir(parents=True)
    (repo / ".pids").mkdir()
    shutil.copy2(ROOT / "start-local.sh", repo / "start-local.sh")
    b = repo / "bin"
    b.mkdir()
    rec = repo / "rec"
    rec.mkdir()
    _shim(b, "lsof", 'exit "${LSOF_RC:-1}"\n')                                   # 1 = nothing listening
    _shim(b, "redis-server", f'printf "%s\\n" "$@" > "{rec}/argv"; cat > "{rec}/stdin"; exit 0\n')
    _shim(b, "redis-cli", f'printf "%s|%s\\n" "${{REDISCLI_AUTH:-}}" "$*" >> "{rec}/cli"; '
                          'if [ "${REDISCLI_AUTH:-}" = "${CLI_WANT:-}" ]; then echo PONG; else echo NOAUTH; fi\n')
    _shim(b, "security", 'if [ -n "${KEYCHAIN_PW:-}" ]; then printf "%s" "$KEYCHAIN_PW"; else exit 44; fi\n')
    return repo


def run_start_redis(repo: Path, env: dict[str, str] | None = None,
                    dotenv: str | None = None) -> tuple[subprocess.CompletedProcess, Path]:
    if dotenv is not None:
        (repo / ".env").write_text(dotenv)
    base = {"HOME": str(repo / "home"), "PATH": f"{repo / 'bin'}:/usr/bin:/bin", "LANG": "en_US.UTF-8", "NO_COLOR": "1",
            "USER": os.environ.get("USER", "tester")}
    script = "source ./start-local.sh; start_redis; echo \"URL=${REDIS_URL:-unset}\""
    r = subprocess.run([BASH, "-c", script], cwd=repo, env={**base, **(env or {})}, capture_output=True, text=True,
                       check=False, timeout=60)
    return r, repo / "rec"


def test_no_password_binds_loopback_without_requirepass(tree: Path):
    r, rec = run_start_redis(tree, dotenv="REDIS_URL=redis://localhost:6379/0\n")
    assert r.returncode == 0, r.stderr
    argv = (rec / "argv").read_text().split("\n")
    assert "--bind" in argv and argv[argv.index("--bind") + 1] == "127.0.0.1"
    assert "--daemonize" in argv and "requirepass" not in (rec / "argv").read_text()
    assert not (rec / "stdin").exists() or "requirepass" not in (rec / "stdin").read_text()
    assert "URL=unset" in r.stdout and "no password" in r.stdout


def test_env_password_goes_through_stdin_and_into_redis_url(tree: Path):
    r, rec = run_start_redis(tree, dotenv='REDIS_PASSWORD="s3cr3t-pw"\n')
    assert r.returncode == 0, r.stderr
    argv = (rec / "argv").read_text()
    assert "s3cr3t-pw" not in argv, "the password must never be on argv (ps would show it)"
    assert argv.split("\n")[0] == "-" and "--bind\n127.0.0.1" in argv
    assert (rec / "stdin").read_text().strip() == "requirepass s3cr3t-pw"
    assert "URL=redis://:s3cr3t-pw@127.0.0.1:6379/0" in r.stdout
    assert "s3cr3t-pw" not in r.stdout.replace("URL=redis://:s3cr3t-pw@127.0.0.1:6379/0", ""), "never printed"


def test_keychain_password_is_used_when_env_has_none(tree: Path):
    r, rec = run_start_redis(tree, env={"KEYCHAIN_PW": "kc-pw-77"}, dotenv="")
    assert r.returncode == 0, r.stderr
    assert (rec / "stdin").read_text().strip() == "requirepass kc-pw-77"
    assert "URL=redis://:kc-pw-77@127.0.0.1:6379/0" in r.stdout


def test_env_password_wins_over_keychain(tree: Path):
    _r, rec = run_start_redis(tree, env={"KEYCHAIN_PW": "kc-pw"}, dotenv="REDIS_PASSWORD=env-pw\n")
    assert (rec / "stdin").read_text().strip() == "requirepass env-pw"


def test_already_running_with_the_password_exports_the_url(tree: Path):
    r, rec = run_start_redis(tree, env={"LSOF_RC": "0", "CLI_WANT": "pw1"}, dotenv="REDIS_PASSWORD=pw1\n")
    assert r.returncode == 0, r.stderr
    assert not (rec / "argv").exists(), "no second server started"
    assert "URL=redis://:pw1@127.0.0.1:6379/0" in r.stdout and "password set" in r.stdout
    cli = (rec / "cli").read_text()
    assert "pw1|" in cli and "-a " not in cli, "the password reaches redis-cli via REDISCLI_AUTH, not -a"


def test_already_running_without_the_password_is_reported(tree: Path):
    r, _rec = run_start_redis(tree, env={"LSOF_RC": "0", "CLI_WANT": ""}, dotenv="REDIS_PASSWORD=pw1\n")
    assert r.returncode == 0, r.stderr
    assert "WITHOUT the configured password" in r.stdout and "restart" in r.stdout
    assert "URL=redis://127.0.0.1:6379/0" in r.stdout, "the exported URL carries no password the server would refuse"


def test_already_running_and_no_password_configured(tree: Path):
    r, _rec = run_start_redis(tree, env={"LSOF_RC": "0"}, dotenv="")
    assert r.returncode == 0 and "already listening" in r.stdout and "URL=unset" in r.stdout
