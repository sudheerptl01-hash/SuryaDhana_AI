"""
End-to-end check of shared.icici_login.browser_login against a local fake of ICICI's
login page (same element IDs and JS entry points as api.icicidirect.com/apiuser/login),
driven by real headless Chrome. Never touches ICICI.
"""
import http.server
import sys
import threading
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from shared.icici_login import (  # noqa: E402
    LoginNeedsHuman,
    browser_login,
    parse_totp_secret,
    totp,
)

SECRET = parse_totp_secret("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ")

FAKE_PAGE = """<html><body>
<div id="pnlLogmain">
  <input type="text" id="txtuid"><input type="password" id="txtPass">
  <input type="checkbox" id="chkssTnc" value="Y">
  <input type="button" id="btnSubmit" value="Login" onclick="submitform()">
</div>
<div id="dvgetotp"></div>
<script>
const MODE = "__MODE__";
function submitform() {
  if (!document.getElementById('chkssTnc').checked) { alert('Please select Terms and Conditons checkbox.'); return; }
  const uid = document.getElementById('txtuid').value, pw = document.getElementById('txtPass').value;
  if (uid !== 'AD206594' || pw !== 'right-password') {
    document.getElementById('dvgetotp').innerHTML = '<span id="lblerr">Invalid User ID or Password</span>';
    return;
  }
  const label = MODE === 'sms' ? 'OTP has been sent to your registered mobile number ******4321'
              : MODE === 'realtotp' ? 'Verify TOTP Use your Google authenticator app to generate a 6 digit code'
                                    : 'Enter the TOTP from your authenticator app';
  // like ICICI's real TOTP panel: "Having issues? Verify with OTP" → goforotp() texts an OTP instead
  const link = MODE === 'realtotp' ? 'Having issues? <a href="javascript://" onclick="goforotp();">Verify with OTP</a>' : '';
  showPanel(label, link);
}
let FOR_OTP = false;
function showPanel(label, extra) {
  let boxes = '';
  for (let i = 0; i < 6; i++) boxes += '<input type="text" maxlength="1" tg-nm="otp">';
  document.getElementById('dvgetotp').innerHTML = '<div id="pnlOTP"><p>' + label + '</p>' + boxes +
    '<span id="otperr" style="display:none"></span><input type="button" value="Submit" onclick="submitotp()">' + extra + '</div>';
}
function goforotp() {
  setTimeout(() => { FOR_OTP = true; showPanel('Verify OTP: OTP has been sent to your registered mobile number ******4321', ''); }, 300);
}
function submitotp() {
  let code = '';
  document.querySelectorAll('#pnlOTP input[tg-nm=otp]').forEach(b => code += b.value);
  if (MODE === 'badcode') {
    const e = document.getElementById('otperr'); e.style.display = 'block'; e.innerText = 'Invalid OTP'; return;
  }
  if (MODE === 'post') {   // redirect delivered as a form POST, like ICICI's documented flow
    const f = document.createElement('form'); f.method = 'POST'; f.action = 'http://127.0.0.1:9/';
    const i = document.createElement('input'); i.name = 'API_Session'; i.value = 'TOK' + code;
    f.appendChild(i); document.body.appendChild(f); f.submit(); return;
  }
  window.location = 'http://127.0.0.1:9/?apisession=TOK' + (FOR_OTP ? 'SMS' : '') + code;   // GET redirect (what the user saw)
}
</script></body></html>"""


@pytest.fixture(scope="module")
def fake_icici():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            mode = self.path.rsplit("/", 1)[-1] or "totp"
            body = FAKE_PAGE.replace("__MODE__", mode).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/login"
    server.shutdown()


@pytest.fixture(scope="module", autouse=True)
def _need_chrome():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch(channel="chrome", headless=True).close()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"headless Chrome unavailable: {exc}")


def _login(url, password="right-password", spec=SECRET, **kw):
    return browser_login("KEY", "AD206594", password, spec, login_url=url, headless=True,
                         panel_timeout_s=3, finish_timeout_s=3, log=lambda *_: None, **kw)


def _codes_around_now():
    now = time.time()
    return {totp(SECRET, now + d) for d in (-30, 0, 30)}


def test_totp_login_captures_get_redirect(fake_icici):
    token = _login(fake_icici + "/totp")
    assert token.startswith("TOK") and token[3:] in _codes_around_now()


def test_totp_login_captures_post_redirect(fake_icici):
    token = _login(fake_icici + "/post")
    assert token.startswith("TOK") and token[3:] in _codes_around_now()


def test_wrong_password_stops_before_any_code_and_saves_screenshot(fake_icici, tmp_path):
    shot = tmp_path / "fail.png"
    with pytest.raises(LoginNeedsHuman, match="Invalid User ID or Password"):
        _login(fake_icici + "/totp", password="wrong", screenshot_path=str(shot))
    assert shot.exists() and shot.stat().st_size > 0


def test_rejected_code_is_not_retried(fake_icici):
    with pytest.raises(LoginNeedsHuman, match="Invalid OTP"):
        _login(fake_icici + "/badcode")


def test_sms_otp_panel_needs_a_person_when_unattended(fake_icici):
    with pytest.raises(LoginNeedsHuman, match="SMS"):
        _login(fake_icici + "/sms")


def test_missing_totp_secret_needs_a_person_when_unattended(fake_icici):
    with pytest.raises(LoginNeedsHuman, match="TOTP_SECRET"):
        _login(fake_icici + "/totp", spec=None)


def test_sms_otp_is_taken_from_the_provider_and_submitted(fake_icici):
    # the Telegram hand-off: the provider sees ICICI's panel text and returns the code you replied with
    seen = []
    token = _login(fake_icici + "/sms", spec=None, otp_provider=lambda panel: (seen.append(panel), "482913")[1])
    assert token == "TOK482913" and "mobile number" in seen[0]


def test_no_otp_from_the_provider_stops_cleanly(fake_icici):
    with pytest.raises(LoginNeedsHuman, match="no OTP received"):
        _login(fake_icici + "/sms", spec=None, otp_provider=lambda panel: None)


def test_authenticator_panel_without_secret_switches_to_sms_first(fake_icici):
    # ICICI's real panel asks for the Google Authenticator code; no SMS is sent unless "Verify with OTP" is clicked.
    # Without ICICI_TOTP_SECRET the login must click it *before* telling you an OTP is on its way.
    seen = []
    token = _login(fake_icici + "/realtotp", spec=None, otp_provider=lambda panel: (seen.append(panel), "482913")[1])
    assert token == "TOKSMS482913" and "mobile number" in seen[0] and "authenticator" not in seen[0]


def test_authenticator_panel_with_secret_uses_the_secret(fake_icici):
    token = _login(fake_icici + "/realtotp", otp_provider=lambda panel: pytest.fail("must not ask for an SMS"))
    assert token.startswith("TOK") and not token.startswith("TOKSMS") and token[3:] in _codes_around_now()
