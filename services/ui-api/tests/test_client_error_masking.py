"""RAPI-06 remainder (round 3 review): a credential inside a client error report is masked WHOLE.

The round-3 masker stopped a value at the first space, '#', '&', ',' or '}' even inside quotes, so
'{"password": "Abc#1234"}' was logged as '{"password": "<redacted>#1234"}'. ICICI passwords and PINs use exactly
those characters. Each value here carries three markers (start, middle, end) between special characters; a
leak of any part of it shows up as a marker in the logged text."""
from __future__ import annotations

import base64
import json
import random
import sys
from pathlib import Path
from urllib.parse import quote, urlencode

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers import client_errors as ce

# what ICICI's password rules allow (letters, digits, specials) plus the separators that broke the old pattern
SPECIALS = "@#$%&*!^()-_+={}[]|\\:;\"'<>,.?/~` "
MARKERS = ("Mk1", "Zq9", "Xw7")


def _secret(rng: random.Random) -> str:
    def chunk() -> str:
        return "".join(rng.choice(SPECIALS + "aZ5") for _ in range(rng.randint(1, 4)))
    return MARKERS[0] + chunk() + MARKERS[1] + chunk() + MARKERS[2]


def _leaks(out: str) -> list[str]:
    return [m for m in MARKERS if m in out]


# how a secret can ride inside a UI error text; each returns the text that reaches the report
TEMPLATES = {
    "json": lambda k, v: "POST /api/positions/credentials failed: " + json.dumps({k: v, "client_id": "C1"}),
    "json_compact": lambda k, v: "body=" + json.dumps({k: v}, separators=(",", ":")),
    "json_in_a_string": lambda k, v: "AxiosError: " + json.dumps({"config": {"data": json.dumps({k: v})}}),
    "python_repr": lambda k, v: "ValueError: bad settings " + repr({k: v, "x": 1}),
    "single_quoted": lambda k, v: f"{k}: '" + v.replace("\\", "\\\\").replace("'", "\\'") + "' rejected",
    "url_encoded_query": lambda k, v: "GET /login?" + urlencode({k: v, "tab": "brkr"}) + " -> 401",
    "url_encoded_json": lambda k, v: "GET /x?q=" + quote(json.dumps({k: v}), safe="") + "&tab=port",
    "form_body": lambda k, v: "body " + urlencode({"user": "u", k: v}),
}
KEYS = ("password", "api_secret", "ICICI_PASSWORD", "session_token", "apisession", "api_key", "pin", "SecretKey")


@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_quoted_and_encoded_secrets_with_icici_characters_are_masked_whole(template: str) -> None:
    rng = random.Random(f"rapi06-{template}")
    for _ in range(150):
        key, secret = rng.choice(KEYS), _secret(rng)
        text = TEMPLATES[template](key, secret)
        out = ce._clean_text(text, 4000)
        assert not _leaks(out), (template, text, out)
        assert "<redacted>" in out


@pytest.mark.parametrize("text, kept", [
    ('{"password": "Abc#1234"}', '{"password": "<redacted>"}'),                    # the review's examples
    ('{"password":"Ab&cd,ef}gh"}', '{"password":"<redacted>"}'),
    ('{"api_secret": "x y"}', '{"api_secret": "<redacted>"}'),
    ("{'password': 'hunter2 with space'}", "{'password': '<redacted>'}"),
    ('{"password": "a b#c", "user": "bob"}', '{"password": "<redacted>", "user": "bob"}'),   # the rest is kept
    ('{"password": "a\\"b#c", "tab": "brkr"}', '{"password": "<redacted>", "tab": "brkr"}'),  # escaped quote
    ('password=Ab%23cd%26ef&tab=brkr', 'password=<redacted>&tab=brkr'),             # URL-encoded, next pair kept
    ('password=Ab#cd&tab=brkr', 'password=<redacted>&tab=brkr'),                    # an unencoded '#' is masked
    ('login failed password=Ab,cd!x next', 'login failed password=<redacted> next'),
    ('{"password": ""}', '{"password": ""}'),                                       # empty: nothing to hide
    ('{"password": "cut off after # and more', '{"password": "<redacted>'),         # no closing quote
])
def test_masked_shapes(text: str, kept: str) -> None:
    assert ce._clean_text(text, 500) == kept


@pytest.mark.parametrize("text, kept", [
    ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.e30.sig rest", "Authorization: Bearer <redacted> rest"),
    ('{"Authorization": "Bearer abc def#ghi"}', '{"Authorization": "Bearer <redacted>"}'),
    ('{"authorization":"Token s3cr3t with space"}', '{"authorization":"Token <redacted>"}'),
    ('headers: {"Authorization": "Mk1 Zq9#Xw7"}', 'headers: {"Authorization": "<redacted>"}'),
    ('Authorization: Digest username="u", response="Zq9" end', "Authorization: <redacted>"),
    ("Authorization: Zq9secret trailing", "Authorization: <redacted>"),
    ("proxy-authorization: Basic Zq9=", "proxy-authorization: Basic <redacted>"),
    ("Cookie: sid=Zq9; theme=dark", "Cookie: <redacted>"),
    ("X-SessionToken: QWxhZGRpbjpvcGVu", "X-SessionToken: <redacted>"),
    ("X-AppKey: 1234abcd", "X-AppKey: <redacted>"),
])
def test_authorization_and_cookie_headers_are_masked(text: str, kept: str) -> None:
    assert ce._clean_text(text, 500) == kept


def test_a_basic_credential_of_a_password_with_icici_characters_is_masked() -> None:
    rng = random.Random("basic")
    for _ in range(50):
        cred = base64.b64encode(f"user:{_secret(rng)}".encode()).decode()
        for text in (f"Authorization: Basic {cred}", f'{{"Authorization": "Basic {cred}"}}', f"auth Basic {cred}"):
            out = ce._clean_text(text, 500)
            assert cred not in out and cred[:12] not in out and "<redacted>" in out, (text, out)


@pytest.mark.parametrize("ordinary", [
    "Unexpected token: < in JSON",                                  # was 'Unexpected token: <redacted> in JSON'
    "Failed to load basic settings for EQS",                         # was 'Failed to load Basic <redacted> for EQS'
    "Failed to load Basic Settings for EQS",
    "Bearer authentication failed",
    "max_tokens: 500",
    "tokens left: 3",
    "token=null while loading", "api_key: undefined", "session_token: None",   # they say what went wrong
    "mapping=1 spin=2 pinned=3 optional=4",
    "Authorization: Bearer undefined", "Authorization: null",                # a missing token, not a secret
    "TypeError: Cannot read properties of undefined (reading 'ltp')",
])
def test_ordinary_error_text_is_not_masked(ordinary: str) -> None:
    assert ce._clean_text(ordinary, 500) == ordinary


def test_masking_happens_before_the_cut_and_in_every_field() -> None:
    secret = "Mk1 #&,}Zq9 Xw7"
    body = {"message": json.dumps({"password": secret}), "stack": "x\n" + json.dumps({"api_secret": secret}),
            "tab": "password='" + secret + "'", "build": "token=" + quote(secret, safe=""),
            "url": "/?tab=port&sym=" + quote("password=" + secret)}
    fields = ce.sanitize_report(body)
    assert not _leaks(json.dumps(fields)), fields
    long = ce._clean_text("x" * 480 + json.dumps({"password": secret}), 500)
    assert not _leaks(long) and len(long) == 500


def test_the_masker_is_linear_on_hostile_input() -> None:
    import time
    for text in ('"password": "' + "\\" * 8000, "password=" + "&a" * 4000, "token: " * 1100,
                 '"Authorization": "' + "Bearer " * 1100, "a" * 8000 + "password"):
        t0 = time.perf_counter()
        ce._clean_text(text, 4000)
        assert time.perf_counter() - t0 < 0.5, text[:40]


def test_a_name_at_the_end_of_a_stack_line_does_not_mask_the_next_line() -> None:
    stack = "Error: no session token:\n    at load (app.js:1:2)\nError: token: Zq9\n    at f (a.js:3)"
    out = ce._clean_text(stack, 4000, keep_newlines=True)
    assert out == "Error: no session token:\n    at load (app.js:1:2)\nError: token: <redacted>\n    at f (a.js:3)"
