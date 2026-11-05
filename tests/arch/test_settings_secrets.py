"""Wave 0.7 (O-T10): ``repr(Settings())`` / ``str`` / ``model_dump_json`` leak none of the secret fields; the values are
still there for the callers that ask (``get_secret_value``). Negative control: a plain-str field with the same
sentinel DOES show, proving the detector sees values. The live .env is never read (``_env_file=None``)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import SecretStr

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shared.config import Settings  # noqa: E402

SENTINELS = {
    "icici_api_key": "LEAK-api-key-7f3a",
    "icici_api_secret": "LEAK-api-secret-9c1d",
    "icici_session_token": "LEAK-session-4e2b",
    "telegram_bot_token": "LEAK-bot-token-11aa",
    "cftc_app_token": "LEAK-cftc-55ff",
    "redis_password": "LEAK-redis-0a0a",
}


def test_the_secret_fields_are_the_contract():
    assert set(Settings.SECRET_FIELDS) == set(SENTINELS)
    for name in Settings.SECRET_FIELDS:
        assert Settings.model_fields[name].annotation is SecretStr, name


def test_repr_str_and_json_dump_leak_nothing(monkeypatch: pytest.MonkeyPatch):
    for name, value in SENTINELS.items():
        monkeypatch.setenv(name.upper(), value)
    s = Settings(_env_file=None)
    rendered = "\n".join([repr(s), str(s), s.model_dump_json(), repr(s.model_dump()), f"{s!r}", f"{s}"])
    for name, value in SENTINELS.items():
        assert value not in rendered, f"{name} leaked through repr/str/dump"
        assert getattr(s, name).get_secret_value() == value
    assert "**********" in rendered


def test_negative_control_a_plain_field_does_show(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STOCK_UNIVERSE_PATH", "data/LEAK-plain-field.csv")
    s = Settings(_env_file=None)
    assert "LEAK-plain-field" in repr(s) and "LEAK-plain-field" in s.model_dump_json()


def test_empty_defaults_and_exported_values(monkeypatch: pytest.MonkeyPatch):
    for name in SENTINELS:
        monkeypatch.delenv(name.upper(), raising=False)
    s = Settings(_env_file=None)
    assert all(getattr(s, name).get_secret_value() == "" for name in SENTINELS)
    assert s.offsite_backup_dir == "" and s.redis_url.startswith("redis://")
