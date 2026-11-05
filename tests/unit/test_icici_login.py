"""ICICI unattended login: TOTP, secret lookup, redirect parsing, code-panel detection."""
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "services/ui-api"))

import icici_admin  # noqa: E402
from shared.icici import extract_session_token  # noqa: E402
from shared.icici_login import (  # noqa: E402
    TotpSpec,
    classify_code_panel,
    extract_token,
    fresh_totp,
    parse_totp_secret,
    read_secret,
    totp,
)

# RFC 6238 Appendix B test secret "12345678901234567890" (SHA-1), 6-digit truncation.
RFC_B32 = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"


@pytest.mark.parametrize("t,code", [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"),
                                    (1234567890, "005924"), (2000000000, "279037")])
def test_totp_matches_rfc6238_vectors(t, code):
    assert totp(parse_totp_secret(RFC_B32), t) == code


def test_secret_accepts_spaces_lowercase_and_otpauth_uri():
    spaced = parse_totp_secret("gezd gnbv gy3t qojq gezd gnbv gy3t qojq")
    uri = parse_totp_secret(f"otpauth://totp/ICICI:AD206594?secret={RFC_B32}&issuer=ICICI&digits=6&period=30")
    assert totp(spaced, 59) == totp(uri, 59) == "287082"
    with pytest.raises(ValueError):
        parse_totp_secret("not base32 !!")


def test_fresh_totp_waits_for_next_window_near_expiry():
    spec = parse_totp_secret(RFC_B32)
    clock = {"t": 1111111109 - (1111111109 % 30) + 27.0}   # 3 s left in the window
    slept = []

    def sleep(s):
        slept.append(s)
        clock["t"] += s

    code = fresh_totp(spec, clock=lambda: clock["t"], sleep=sleep)
    assert slept and slept[0] >= 3.0
    assert code == totp(spec, clock["t"]) and code != totp(spec, clock["t"] - 30)


def test_fresh_totp_does_not_wait_with_time_left():
    spec = TotpSpec(b"12345678901234567890")
    assert fresh_totp(spec, clock=lambda: 1_000_000_020.0, sleep=lambda s: pytest.fail("slept")) == \
        totp(spec, 1_000_000_020.0)


def test_read_secret_prefers_env_then_keychain(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    calls = []

    def runner(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="FROMKEYCHAIN\n", stderr="")

    assert read_secret("ICICI_TOTP_SECRET", {"ICICI_TOTP_SECRET": "FROMENV"}, runner) == "FROMENV"
    assert calls == []
    assert read_secret("ICICI_TOTP_SECRET", {}, runner) == "FROMKEYCHAIN"
    assert calls[0][:2] == ["/usr/bin/security", "find-generic-password"] and "ICICI_TOTP_SECRET" in calls[0]


def test_read_secret_missing_everywhere(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    missing = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 44, stdout="", stderr="not found")  # noqa: E731
    assert read_secret("ICICI_TOTP_SECRET", {}, missing) == ""


def test_extract_token_from_get_and_post_redirects():
    assert extract_token("https://127.0.0.1/?apisession=57170372") == "57170372"
    assert extract_token("http://127.0.0.1:9/", "API_Session=TOKsx9&x=1") == "TOKsx9"
    assert extract_token("https://api.icicidirect.com/apiuser/login?api_key=abc") == ""


@pytest.mark.parametrize("fn", [extract_session_token, icici_admin.extract_session_token])
def test_session_token_paste_formats(fn):
    assert fn("57170372") == "57170372"
    assert fn("127.0.0.1/?apisession=57170372") == "57170372"          # copied without the scheme
    assert fn("https://127.0.0.1/?apisession=ab12sx&foo=1") == "ab12sx"  # an "s" no longer truncates
    assert fn("  ") == ""


def test_code_panel_classification():
    assert classify_code_panel("Enter the TOTP from your authenticator app") == "totp"
    assert classify_code_panel("OTP has been sent to your registered mobile number ******4321") == "sms"
    assert classify_code_panel("Enter code") == "unknown"


# ── wrong-password guard (scripts/daily_session_refresh.py) ──────────────────────

def _refresh_module(tmp_path, monkeypatch):
    sys.path.insert(0, str(_ROOT / "scripts"))
    import daily_session_refresh as dsr
    monkeypatch.setattr(dsr, "BLOCK_FILE", tmp_path / "block.json")
    return dsr


def test_credentials_rejection_is_recognised(tmp_path, monkeypatch):
    dsr = _refresh_module(tmp_path, monkeypatch)
    assert dsr.is_credentials_rejection("ICICI rejected the login: Invalid Credentials: ")
    assert dsr.is_credentials_rejection("ICICI rejected the login: wrong password")
    assert not dsr.is_credentials_rejection("ICICI is showing a captcha — log in once by hand")
    assert not dsr.is_credentials_rejection("ICICI rejected the login: code expired")


def test_block_applies_only_to_the_same_credentials(tmp_path, monkeypatch):
    import json
    dsr = _refresh_module(tmp_path, monkeypatch)
    fp = dsr.credential_fingerprint("AD1", "old-pass")
    assert "old-pass" not in fp and len(fp) == 16
    assert dsr.blocked_reason(fp) is None                                   # no block file yet
    dsr.BLOCK_FILE.write_text(json.dumps({"fingerprint": fp, "reason": "Invalid Credentials"}))
    assert dsr.blocked_reason(fp) == "Invalid Credentials"
    assert dsr.blocked_reason(dsr.credential_fingerprint("AD1", "new-pass")) is None   # corrected → lifts
    dsr.BLOCK_FILE.write_text("not json")
    assert dsr.blocked_reason(fp) is None
