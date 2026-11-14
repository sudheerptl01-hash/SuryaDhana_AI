"""Every live Breeze SDK call in ui-api goes through the ONE budget ledger (F6-01, 14 Nov 2026).

PLAN §0.11 and ``positions._breeze_call``'s own docstring both say "every caller passes through it", but four
sites reached the SDK straight off ``_get_breeze_client()`` — ``routers/mcx.py`` (get_quotes, get_historical_data_v2)
and ``routers/gold_preopen.py`` (the same pair). The ledger had therefore recorded ZERO ``get_quotes`` in its
whole life (``/api/positions/breeze-budget`` by_method held only generate_session and get_customer_details),
while the CMDT silver/crude desks and the MCXG gold desk poll those paths every 30 s. On a live MCX session that
is ~6 unmetered calls a minute, which outruns ICICI's documented daily ceiling while the ledger still promises
the IV tape and the chain poller a budget that no longer exists. It failed SILENTLY, which is the one failure
mode the rest of this product does not have.

This is the gate, not the fix: it fails on a NEW bare call, so the hole cannot quietly return. Two metering
styles are accepted because both reach the same ledger — ``_breeze_call(...)`` (which wraps ``ledger().guard``
and retries once) and an explicit ``with ledger().guard(caller, method):`` block.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

UI_API = Path(__file__).resolve().parents[1]
REPO = UI_API.parents[1]

#: Every tree that may hold a Breeze SDK call. F9-03: this gate was hardened three times while scanning ONLY
#: services/ui-api, and the whole time `services/data-service/providers/icici_breeze_provider.py` held three
#: unmetered calls on the busiest path in the stack — the live-quote poller the NIFTY and watchlist tasks drive
#: every 15 seconds, whose own comment prices it at ~1,580 calls a day. The budget panel reported thousands of
#: calls remaining while that volume was invisible to it, so the first symptom of exhaustion on a trading day
#: would have been the option chain and margin failing mid-session with the panel still showing plenty left.
#: A gate that guards one directory out of seven is a gate that tells you the wrong thing confidently.
#: F10-01: the fifth hardening of this gate widened one root to five and STILL missed
#: services/execution-service — which held a byte-for-byte copy of the very provider file the same commit had
#: just metered, minus the metering. So the roots are no longer hand-listed: every services/* directory is
#: discovered, and `test_the_gate_scans_a_non_trivial_number_of_files` fails if a new one appears unscanned.
#: Listing roots by hand is how this gate was blind five times; the list itself was the defect.
SCANNED_ROOTS = (
    *sorted(p for p in (REPO / "services").iterdir() if p.is_dir() and not p.name.startswith(".")),
    REPO / "scripts", REPO / "shared", REPO / "alpha_lab",
)

#: Set by the self-test below (and by an adversarial probe) to point the detector at a planted tree instead of
#: the repo. A module-level override rather than reassigning UI_API: F8's probe had to monkeypatch UI_API, which
#: silently also changed the path the relative-name reporting used.
_ROOTS_OVERRIDE: tuple[Path, ...] | None = None

#: the SDK methods that cost a call against ICICI's quota (reads and the margin calculator; order methods are
#: refused outright elsewhere — see test_http_security.py — so they are deliberately not listed as "allowed")
METERED_METHODS = ("get_quotes", "get_historical_data_v2", "get_historical_data", "get_option_chain_quotes",
                   "margin_calculator", "get_margin", "get_portfolio_holdings", "get_portfolio_positions",
                   "get_funds", "get_customer_details", "get_trade_list", "get_order_detail")
# any receiver, not just a local literally named `breeze` (F7-02: self.client.get_quotes(...) and
# clients[0].get_quotes(...) were invisible to the first version of this gate)
#: a dotted call on any receiver, OR the getattr form that reaches the same SDK through a string name (F8-03)
#: F9-04: the `\s*\(` that used to follow the method name made the gate blind to the idiom this codebase
#: MANDATES — `routers/mcx.py` states "Breeze/master work goes through asyncio.to_thread", and
#: `asyncio.to_thread(breeze.get_quotes, ...)` passes the method as a value, with no `(` after its name. The
#: same held for functools.partial and for a bound alias (`fn = breeze.get_quotes`). A reference to a metered
#: method is now enough; a string literal cannot trigger it, because strings are blanked before the window
#: check and a match must start on real code.
_CALL = re.compile(
    r"[\w.\[\]()]+\.(" + "|".join(METERED_METHODS) + r")\b"
    r"|getattr\([^,)]+,\s*[\"'](" + "|".join(METERED_METHODS) + r")[\"']")
#: how many lines above a call the metering may appear (a guard block plus the call's own argument lines)
_WINDOW = 8


def _code_lines(src: str) -> list[str]:
    """The file's CODE lines, with every comment and string literal blanked, line numbers preserved.

    F8-03: the first version of this detector asked "is it metered?" by searching the preceding LINES — comments
    included — for `_breeze_call(` or `ledger().guard(`. Both `routers/mcx.py` and `routers/gold_preopen.py`
    carry comments naming `_breeze_call` exactly where a new quote call would be added, so the next bare call in
    the two files F6-01 was actually about would have been invisible to the gate written to catch it. It also
    skipped any line containing a backtick, which prose uses constantly.

    `tokenize` is used rather than a hand-rolled stripper because the hand-rolled one is the bug: it has to get
    docstrings, trailing comments, implicit concatenation and raw strings all right, and the standard library
    already does. A file that will not tokenize (a syntax error mid-edit) is returned raw, which can only make
    the gate stricter, never blinder.
    """
    import io
    import tokenize as tk

    lines = src.split("\n")
    try:
        toks = list(tk.generate_tokens(io.StringIO(src).readline))
    except (tk.TokenError, IndentationError, SyntaxError):       # pragma: no cover — raw is the safe direction
        return lines
    out = list(lines)
    # F10-06: CPython 3.12+ tokenises an f-string as FSTRING_START / FSTRING_MIDDLE / FSTRING_END rather than
    # STRING, so `f"... ledger().guard( ..."` in the window was never blanked and SILENCED this gate for a real
    # bare call. Confirmed on this stack's interpreter (3.13). The FSTRING_* members do not exist before 3.12,
    # hence getattr rather than a direct reference.
    blankable = {tk.COMMENT, tk.STRING}
    for name in ("FSTRING_START", "FSTRING_MIDDLE", "FSTRING_END"):
        member = getattr(tk, name, None)
        if member is not None:
            blankable.add(member)
    for t in toks:
        if t.type not in blankable:
            continue
        (r1, c1), (r2, c2) = t.start, t.end
        for r in range(r1, r2 + 1):
            i = r - 1
            if i >= len(out):
                continue
            a = c1 if r == r1 else 0
            b = c2 if r == r2 else len(out[i])
            out[i] = out[i][:a] + " " * max(0, b - a) + out[i][b:]
    return out


def _rel(path: Path) -> str:
    """A readable path for the failure message, whichever root the file came from.

    This used to be `path.relative_to(UI_API)`, which raised ValueError the moment the gate scanned anything
    outside services/ui-api — so widening the roots for F9-03 broke the reporting before it broke the logic.
    """
    for base in (REPO, *SCANNED_ROOTS):
        try:
            return str(path.relative_to(base))
        except ValueError:
            continue
    return str(path)


def _bare_sdk_calls() -> list[str]:
    """Every metered SDK call site with no metering visible in the CODE above it, as 'file:line method'."""
    bare: list[str] = []
    roots = SCANNED_ROOTS if _ROOTS_OVERRIDE is None else _ROOTS_OVERRIDE
    for path in sorted({p for root in roots for p in root.rglob("*.py")}):
        if "/tests/" in str(path) or "/node_modules/" in str(path):
            continue
        raw = path.read_text(encoding="utf-8")
        lines, code = raw.split("\n"), _code_lines(raw)
        for n, line in enumerate(lines):
            m = _CALL.search(line)
            if not m:
                continue
            # Matched on the RAW line, because `getattr(breeze, "get_quotes")` carries the method name inside a
            # string literal that blanking would erase — but the match must START on real code, or it is prose
            # (blanking preserves column positions, so a blanked column means "was a comment or a string").
            start = m.start()
            cl = code[n] if n < len(code) else ""
            if start >= len(cl) or cl[start] != line[start]:
                continue
            # `.guard(` on ANY receiver, not just `ledger().guard(`: data-service injects the ledger
            # (`budget.guard(CALLER, METHOD)` in fo_iv/intraday.py), which is better design than reaching for
            # the global — and the first widened run reported both of those correctly-metered calls as bare.
            #
            # F10-04: the window alone was not enough. A `with ...guard(...)` block vouches only for calls
            # INSIDE it, but an 8-line upward window also covered the lines after the block ended — so a bare
            # call on the very next line, at the OUTER indent, was silently excused by its neighbour's guard.
            # A guard only counts when the call is indented deeper than it.
            vouched = False
            for k in range(n, max(-1, n - _WINDOW) - 1, -1):
                src_line = code[k]
                if "_breeze_call(" in src_line:
                    vouched = True
                    break
                if ".guard(" in src_line:
                    guard_indent = len(src_line) - len(src_line.lstrip())
                    call_indent = len(line) - len(line.lstrip())
                    vouched = call_indent > guard_indent
                    break
            if vouched:
                continue
            bare.append(f"{_rel(path)}:{n + 1} {next(g for g in m.groups() if g)}")
    return bare


#: Hand-run diagnostics, exempt because nothing schedules them: a human types the command, watches the output
#: and spends a handful of calls once. They are NOT exempt because metering them would be hard.
#: An allowlist is how a gate rots, so the exemption's REASON is enforced by
#: `test_the_allowlist_is_still_justified` below rather than merely asserted here: each file must still exist,
#: must still contain a metered-method call, and must NOT be reachable from the scheduler. The day one of
#: these becomes a job, the gate fails and says so.
UNSCHEDULED_DIAGNOSTICS = {
    "scripts/breeze_data_catalog.py",       # probes every market-data endpoint for one ticker, by hand
    "scripts/icici_session_helper.py",      # get_customer_details as a session-validity check, by hand
}


def test_the_allowlist_is_still_justified() -> None:
    """The exemption above holds only while these stay hand-run. Enforce exactly that."""
    controller = (REPO / "scripts/master_controller.py").read_text(encoding="utf-8")
    for rel in sorted(UNSCHEDULED_DIAGNOSTICS):
        path = REPO / rel
        assert path.is_file(), f"allowlisted file is gone — drop it from UNSCHEDULED_DIAGNOSTICS: {rel}"
        src = path.read_text(encoding="utf-8")
        assert any(m in src for m in METERED_METHODS), (
            f"{rel} no longer calls a metered method; the exemption is dead weight — remove it")
        stem = Path(rel).stem
        assert stem not in controller, (
            f"{rel} is now referenced by the scheduler, so it is no longer a hand-run diagnostic: meter its "
            f"Breeze calls and remove it from UNSCHEDULED_DIAGNOSTICS")


def test_no_breeze_sdk_call_bypasses_the_budget_ledger() -> None:
    bare = [b for b in _bare_sdk_calls() if b.split(":")[0] not in UNSCHEDULED_DIAGNOSTICS]
    assert not bare, (
        "Breeze SDK call(s) that do not pass through the ledger — wrap them in positions._breeze_call(fn, "
        "caller='ui-api.<area>', ...) or `with ledger().guard(caller, method):`. An unmetered call drains the "
        "real broker quota while every budgeted caller is told it still has room:\n  " + "\n  ".join(bare))


def test_the_four_f6_sites_are_metered_with_their_own_caller_labels() -> None:
    """The specific sites F6-01 found, pinned by caller label so a refactor cannot drop the metering quietly."""
    mcx = (UI_API / "routers" / "mcx.py").read_text(encoding="utf-8")
    gold = (UI_API / "routers" / "gold_preopen.py").read_text(encoding="utf-8")
    assert mcx.count('_breeze_call(breeze.get_quotes, caller="ui-api.mcx"') == 1
    assert mcx.count('_breeze_call(breeze.get_historical_data_v2, caller="ui-api.mcx"') == 1
    assert gold.count('_breeze_call(breeze.get_quotes, caller="ui-api.gold-preopen"') == 1
    assert gold.count('_breeze_call(breeze.get_historical_data_v2, caller="ui-api.gold-preopen"') == 1


def test_the_detector_actually_runs_and_separates_bare_from_metered(tmp_path, monkeypatch) -> None:
    """F7-02: the first version of this control only substring-tested two strings and never called the detector,
    so the gate could have passed while scanning nothing. This plants a two-file tree, points the scanner at it
    and asserts it returns EXACTLY the bare call — including the receiver forms and the window edge a reviewer
    found it blind to."""
    import test_breeze_ledger_coverage as mod

    (tmp_path / "routers").mkdir()
    (tmp_path / "routers" / "bare.py").write_text(
        "def f(c):\n    q = c.get_quotes(stock_code='GOLD')\n"                       # receiver NOT named breeze
        "def g(self):\n    h = self.client.get_historical_data_v2(x=1)\n"            # attribute chain
        # F9-04: the house idiom — `routers/mcx.py` mandates asyncio.to_thread for Breeze work, and passing the
        # method as a VALUE has no '(' after its name, so the old regex could not see it at all
        "async def h(breeze):\n    return await asyncio.to_thread(breeze.get_quotes, 'GOLD')\n"
        "def i(breeze):\n    fn = breeze.get_option_chain_quotes\n    return fn(x=1)\n")
    (tmp_path / "routers" / "metered.py").write_text(
        "def f(breeze):\n    with ledger().guard('x', 'get_quotes'):\n"
        "        q = breeze.get_quotes(stock_code='GOLD')\n"
        "def g(breeze):\n    q = _breeze_call(breeze.get_quotes, caller='x')\n")
    monkeypatch.setattr(mod, "_ROOTS_OVERRIDE", (tmp_path,))
    found = mod._bare_sdk_calls()
    assert len(found) == 4, found                      # all four bare forms, no metered one
    assert all("bare.py" in f for f in found), found

    # and it must not pass by scanning nothing: an empty tree yields no files, which is itself a failure mode
    empty = tmp_path / "empty"
    (empty / "routers").mkdir(parents=True)
    monkeypatch.setattr(mod, "_ROOTS_OVERRIDE", (empty,))
    assert mod._bare_sdk_calls() == []
    assert list(empty.rglob("*.py")) == [], "the empty-tree case is only meaningful while the tree is empty"


def test_the_gate_scans_a_non_trivial_number_of_files() -> None:
    """F7-02: with the roots pointing anywhere wrong, every assertion above passes vacuously. Pin the floor.
    F9-03: and pin that EVERY root is real and non-empty — the gate spent three hardening rounds scanning only
    services/ui-api while the live-quote provider in data-service held three unmetered calls."""
    for root in SCANNED_ROOTS:
        assert root.is_dir(), f"scanned root missing: {root}"
    # Not "every root has python": services/master-controller is a real directory with none (the controller
    # lives in scripts/), and an auto-discovered empty root is harmless — it simply contributes no files. What
    # must hold is that every services/* tree IS in the list, which is the check that would have caught F10-01.
    discovered = {p for p in (REPO / "services").iterdir() if p.is_dir() and not p.name.startswith(".")}
    missing = discovered - set(SCANNED_ROOTS)
    assert not missing, f"a services/* tree is not scanned — the F10-01 hole: {sorted(str(m) for m in missing)}"
    scanned = [p for p in {q for r in SCANNED_ROOTS for q in r.rglob("*.py")} if "/tests/" not in str(p)]
    assert len(scanned) > 200, f"only {len(scanned)} modules scanned across {len(SCANNED_ROOTS)} roots"
    # the two files this gate exists for, one per service
    assert (UI_API / "routers" / "mcx.py").exists()
    assert (REPO / "services/data-service/providers/icici_breeze_provider.py").exists()


#: every (router that caches a broker quote, component that polls it) pair. F7-01: the first version of this
#: test hard-coded the commodity pair, so mcx.py kept the identical 15 s-vs-30 s mismatch — and once the path was
#: metered, each miss became a real ledger call. A new desk must be added here.
QUOTE_PAIRS = (("commodity_desk.py", "commodity/CommodityDesk.tsx"), ("mcx.py", "McxGoldDesk.tsx"))


@pytest.mark.parametrize("router,component", QUOTE_PAIRS)
def test_the_quote_cache_outlasts_the_poll_that_drives_it(router: str, component: str) -> None:
    """A cache shorter than the poll means EVERY poll is a guaranteed miss — and on a metered path, a call."""
    src = (UI_API / "routers" / router).read_text(encoding="utf-8")
    ttl = int(re.search(r"^QUOTE_TTL_S\s*=\s*(\d+)", src, re.M).group(1))
    ui = (UI_API.parents[1] / "ui" / "components" / component).read_text(encoding="utf-8")
    poll_ms = int(re.search(r"QUOTE_MS\s*=\s*([\d_]+)", ui).group(1).replace("_", ""))
    assert ttl >= poll_ms / 1000, (f"{router}: cache {ttl}s must span {component}'s {poll_ms / 1000:g}s poll, "
                                  f"or every poll costs a metered broker call")


# ── a failed login must not spend the day's quota rediscovering itself (F7-05 follow-up, 14 Nov 2026) ─────────
# Measured that day: by_method.generate_session reached 126 on a Saturday with no session obtainable, climbing
# while the terminal sat open, because a failure was retried every 60 s and the desk quote paths call the client
# on every poll. Each attempt is metered, so a flat 60 s is up to 840 calls across a 14 h day — a fifth of the
# cap spent learning the same thing. These pin the backoff AND, more importantly, that recovery is never delayed.

def test_the_login_backoff_grows_and_then_holds() -> None:
    import sys
    sys.path.insert(0, str(UI_API))
    from routers.positions import _CLIENT_RETRY_BACKOFF_S, _retry_wait_s

    assert _retry_wait_s(0) == 0.0                                  # no failures: no wait
    waits = [_retry_wait_s(n) for n in range(1, len(_CLIENT_RETRY_BACKOFF_S) + 1)]
    assert waits == list(_CLIENT_RETRY_BACKOFF_S), waits            # one step per consecutive failure
    assert waits == sorted(waits), "each wait must be at least the previous one"
    assert _retry_wait_s(99) == _CLIENT_RETRY_BACKOFF_S[-1], "it must cap, not grow forever"
    # the whole point: the day's worth of attempts is bounded well under the cap
    day, spent, n = 14 * 3600, 0.0, 0
    while spent <= day:
        n += 1
        spent += _retry_wait_s(n)
    assert n < 120, f"{n} attempts across a trading day is too many for a metered call"


def test_a_new_session_token_bypasses_the_backoff_entirely(monkeypatch) -> None:
    """The recovery path that must never regress: when the 08:00 job (or a paste, or the session guard) writes a
    NEW token, the cache key differs and the client rebuilds at once — a long backoff on the OLD token must not
    keep the terminal broker-less after the thing that fixes it has run."""
    import sys
    sys.path.insert(0, str(UI_API))
    from routers import positions as pos

    attempts: list[str] = []

    def fake_build(api_key, api_secret, token):
        attempts.append(token)
        return (None, "session invalid", "session") if token == "OLD" else (object(), None, None)

    monkeypatch.setattr(pos, "_build_breeze_client", fake_build)
    monkeypatch.setattr(pos, "extract_session_token", lambda raw: raw)
    for k, v in (("ICICI_API_KEY", "k"), ("ICICI_API_SECRET", "s"), ("ICICI_SESSION_TOKEN", "OLD")):
        monkeypatch.setenv(k, v)
    pos._client_cache.update(key=None, client=None, error=None, error_kind=None, at=0.0, fails=0)

    assert pos._get_breeze_client()[0] is None and attempts == ["OLD"]
    pos._get_breeze_client()                                        # immediately again: the backoff holds it
    assert attempts == ["OLD"], f"a second attempt inside the backoff window: {attempts}"
    assert pos._client_cache["fails"] == 1

    monkeypatch.setenv("ICICI_SESSION_TOKEN", "NEW")                # the login job lands a working token
    client, err = pos._get_breeze_client()
    assert client is not None and err is None, (client, err)
    assert attempts == ["OLD", "NEW"], f"the new token must be tried at once: {attempts}"
    assert pos._client_cache["fails"] == 0, "a success resets the failure count"
