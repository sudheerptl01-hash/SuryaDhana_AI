"""Failure policy shared by the 43-page audit and the parity check.

What counts as a failure is defined here, once, so ``ui_audit.py`` and ``parity.py`` cannot drift:

* **console error** (``console`` type ``error``) not matching ``IGNORE_CONSOLE`` (dev-only noise)
* **page error** (uncaught exception / unhandled rejection reaching the page)
* **failed request** (first-party = same origin as the audited base): HTTP status >= 400, or a network
  failure, EXCEPT the narrow stream-abort allowlist below
* **third-party** failures (fonts.googleapis.com, TradingView, …) are reported separately and only fail
  under ``--strict``

The stream-abort allowlist is deliberately narrow. A request is excused only when **all** hold:

1. its path is one of the six known streaming endpoints (``STREAM_PATHS``)
2. its failure text is an abort, not an error: Chromium ``net::ERR_ABORTED``, WebKit ``cancelled`` /
   ``Load request cancelled`` (``ABORT_FAILURE``)
3. it failed **after the harness navigated away** from the tab that opened it (the probe's epoch moved on),
   i.e. the browser tore the stream down because the page went away. An abort while the page is still
   showing is a real failure (the live feed stopped).

**Platform seams** (``PLATFORM_SEAM_PATHS``) are the few endpoints the platform layer of PLAN §5 probes whose
answer legitimately depends on the front server (Next :3000 vs same-origin ui-api :8010): the liveness probe
(``/health``, then ``/api/health``), build identity (``/version``, ``/build-info.json``) and server prefs
(``/api/prefs[/<key>]``). The AUDIT still counts their failures (a 404 is a red console line on that base);
only the PARITY comparison sets them aside and reports them separately, because the same UI code takes a
different probe path per topology by design.

**Expected program deltas** (``EXPECTED_DELTAS``) are page-independent requests the desktop program's UI
shell adds by design, so a pre-program baseline (reports/desktop_app/baseline_preprogram) never sends them
while every current build does: today the NSE holiday lookup that the page header and the desktop title strip
share (desktop review C3-logic-unchanged-06): ``GET /api/market/eco-calendar?back=0&ahead=7``, BRIEF's own query
(ui/lib/api.ts ``ECO_SHARED_QUERY``, one cached request per page since wave 2), or ``?back=0&ahead=10`` in round-1
releases (ui/components/desktop/holidays.ts ``HOLIDAYS_URL``). One is matched by method, path AND exact query
values, so the ECO and EVTS pages' own calendar calls (same path, other values) are still compared. When such an endpoint is called on
one side only and every call of it was the expected request, PARITY sets it aside and reports it separately
(``--no-expected-deltas`` compares it like any other endpoint). As with seams, the AUDIT still counts its
failures. A delta whose ``queries`` is ``None`` matches ANY query: used for a whole endpoint family on a page
that has no A side at all (the GOLD page's ``/api/gold/*``). A delta whose ``tabs`` is a set is PAGE-SCOPED
(wave 1b, B6 adversarial major): the probe still tags the request wherever it sees it, but PARITY sets it
aside ONLY on those tabs — a gold read appearing on DESK, ALRT, PORT or any other undeclared page stays an
"API request set differs" DIFF, which is exactly the drift PLAN 0.1 #7 forbids ("nothing gold feeds the
Desk"). ``tabs=None`` keeps the old page-independent meaning (the header's holiday lookup).

**Gold program (26 Oct 2026, reports/gold_program/PLAN.md §b, Appendix A)** adds two more kinds of intended
delta, declared here so PARITY can tell "intended" from "drift":

* ``EXPECTED_NEW_PAGES`` — pages that have NO A side: the 43rd page ``gold`` (GOLD). A pre-program build
  renders the brief for ``?tab=gold`` and never shows a GOLD code chip, so an A visit can only time out.
  PARITY visits B alone, scores it with the audit policy and reports the tab as ``NEW`` (neither PARITY nor
  DIFF); the run's verdict needs every NEW page to pass its B audit. ``--no-expected-deltas`` compares it
  like any other tab (and it will DIFF: that is the point of declaring it).
* ``EXPECTED_STRUCTURE_DELTAS`` — fingerprint changes on EXISTING pages that PLAN §b prescribes: CMDT drops
  the Gold Pre-Open desk (its panels, tables and page-header subtitle), BRF's "Gold open (MCX)" panel becomes
  one line in the Market panel, MCXG's "COMEX × rupee overlay" shrinks to one line and its specs card is
  replaced by the shared contract selector, WEI's GC=F row gains a second line (no structural change),
  BRKR gains the "Auto-login (TOTP)" panel (PLAN §g). A fingerprint entry present on one side only that
  matches a declared pattern for that tab and side is set aside and reported under ``expected_structure``;
  anything undeclared is still a DIFF. Patterns are matched against the NORMALISED fingerprint text
  (numbers masked, see ``normalize_text``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

IGNORE_CONSOLE = re.compile(r"Download the React DevTools|\[HMR\]|\[Fast Refresh\]|favicon", re.IGNORECASE)

STREAM_PATHS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/api/telemetry/logs/stream$"),
    re.compile(r"^/api/pipeline/(?:ml|rl)-stream/[^/]+$"),
    re.compile(r"^/api/ml/train/stream$"),
    re.compile(r"^/api/analytics/(?:wfo-)?backtest/stream$"),
)
ABORT_FAILURE = re.compile(r"^(?:net::ERR_ABORTED|cancelled|Load request cancelled)$", re.IGNORECASE)

PLATFORM_SEAM_PATHS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^/health$"),
    re.compile(r"^/api/health$"),
    re.compile(r"^/version$"),
    re.compile(r"^/build-info\.json$"),
    re.compile(r"^/api/prefs(?:/[^/]+)?$"),
)
RESOURCE_LOAD_CONSOLE = re.compile(r"^Failed to load resource\b", re.IGNORECASE)


@dataclass(frozen=True)
class ExpectedDelta:
    """One request a program's UI sends (or stops sending) by design (see the module docstring).

    ``tabs``: the pages PARITY may set it aside on (``None`` = page-independent, e.g. the header's holiday lookup).
    """

    id: str
    method: str
    path: re.Pattern[str]
    queries: tuple[tuple[tuple[str, str], ...], ...] | None   # accepted exact queries (sorted pairs); None = any query
    note: str
    tabs: frozenset[str] | None = None                         # page-scoped (wave 1b); None = every page


ANY_QUERY = None
NO_QUERY: tuple[tuple[tuple[str, str], ...], ...] = ((),)      # exactly one accepted query: the empty one


EXPECTED_DELTAS: tuple[ExpectedDelta, ...] = (
    ExpectedDelta("header-holidays", "GET", re.compile(r"^/api/market/eco-calendar$"),
                  ((("ahead", "7"), ("back", "0")),     # ui/lib/api.ts ECO_SHARED_QUERY (BRIEF's query, wave 2)
                   (("ahead", "10"), ("back", "0"))),   # round-1 releases: holidays.ts HOLIDAYS_URL
                  "NSE holiday lookup shared by the page header and the desktop title strip (C3-logic-unchanged-06)"),
    # Wave 2 (W2-UI-SHELL) REMOVED these from the pages that do not show them. An older build still sends them on
    # every page, so there they are one-sided by design; EQS, OVRV and PIPE call them on both sides and stay compared.
    ExpectedDelta("w2-stock-list-eqs-only", "GET", re.compile(r"^/api/stocks/list$"),
                  ((("limit", "1500"), ("search", ""), ("skip", "0")),),
                  "the 0.9 MB 1,500-stock list loads only for EQS since wave 2 (C1-trader-ux-03)"),
    ExpectedDelta("w2-enrichment-ovrv-only", "GET", re.compile(r"^/api/dashboard/enrichment-status$"), ((),),
                  "the enrichment status loads only for OVRV since wave 2 (C1-trader-ux-03)"),
    ExpectedDelta("w2-pipeline-pipe-only", "GET",
                  re.compile(r"^/api/pipeline/(?:service-health|model-metrics|feature-importance|data-quality"
                             r"|rl-status|rl-training-metrics)$"), ((),),
                  "the hidden PipelineStudio mounts and polls only once PIPE was opened, since wave 2 (C2-performance-06)"),
    # Round 4b (FEATURE_PARITY P4, UI half): while the header's ICICI light is red, it reads ui-api's cached session status
    # (on the edge, then every 2 min; 10 min hidden) so its tooltip can say 'unreachable (network)' vs 'expired: /login'.
    ExpectedDelta("r4b-header-icici-kind", "GET", re.compile(r"^/api/positions/connection-status$"), ((),),
                  "the header ICICI light reads connection-status error_kind while it is red, since round 4b (P4)"),
    # Gold program (26 Oct 2026, PLAN §b/§d/§g; declarations made exact in wave 1b against the routes and fetchers in the
    # tree — tests/integration/test_desktop_qa_harness.py::test_gold_deltas_are_what_the_ui_sends_and_the_server_mounts
    # keeps them so). What each EXISTING page sends, side B (gold release) vs side A (25 Oct release, ui/dist/previous):
    #   BRF   B: GET /api/gold/health?window=W (Brief.tsx getGoldHealth('W') → ui/lib/gold/api.ts)   A: the desk's
    #         GET /api/commodity/gold-preopen[?inputs] and /gold-preopen/log?threshold=300 (retired, PLAN §b)
    #   WEI   B: GET /api/gold/health?window=W (WorldMarkets.tsx)                                     A: nothing gold
    #   CMDT  B: NOTHING gold (chips only; the tile links to GOLD)                                    A: the desk's reads
    #   MCXG  B: GET /api/gold/contracts?exchange=MCX (McxGoldDesk.tsx getGoldContracts(sel.exchange); the shared
    #         selector offers MCX only, NSE/BSE are disabled)                                         A: GET /api/mcx/specs
    #         (/api/mcx/session, /quote, /overlay and POST /ticket are on BOTH sides and stay compared)
    #   BRKR  B: GET /api/positions/totp/status (IciciTotpPanel.tsx; ?reveal=1 is user-triggered, never on load)
    #   GOLD  B only (EXPECTED_NEW_PAGES): the whole /api/gold/* family, any query — never compared, tagged for the audit
    # A gold read on any OTHER page, or another /api/gold path or query on these, is NOT set aside (PLAN 0.1 #7).
    ExpectedDelta("gold-health-line", "GET", re.compile(r"^/api/gold/health$"), ((("window", "W"),),),
                  "BRF's and WEI's one gold line read /api/gold/health?window=W (PLAN §b): B-only on BRF and WEI",
                  tabs=frozenset({"brief", "world"})),
    ExpectedDelta("gold-mcxg-selector", "GET", re.compile(r"^/api/gold/contracts$"), ((("exchange", "MCX"),),),
                  "MCXG's shared contract selector reads /api/gold/contracts?exchange=MCX (PLAN §b): B-only on MCXG",
                  tabs=frozenset({"mcxgold"})),
    ExpectedDelta("gold-preopen-moved", "GET", re.compile(r"^/api/commodity/gold-preopen(?:/log)?$"), ANY_QUERY,
                  "the Gold Pre-Open desk and its accuracy log moved from CMDT and BRF to GOLD (PLAN §b): A-only there "
                  "(the retired desk's query carries its saved inputs, so any query; the log sends ?threshold=300)",
                  tabs=frozenset({"commodity", "brief"})),
    ExpectedDelta("gold-mcxg-specs-replaced", "GET", re.compile(r"^/api/mcx/specs$"), NO_QUERY,
                  "MCXG's specs card is replaced by the shared contract selector (/api/gold/contracts): A-only on MCXG",
                  tabs=frozenset({"mcxgold"})),
    ExpectedDelta("gold-brkr-totp-status", "GET", re.compile(r"^/api/positions/totp/status$"), NO_QUERY,
                  "BRKR's Auto-login (TOTP) panel reads its status on load (PLAN §g): B-only on BRKR",
                  tabs=frozenset({"broker"})),
    ExpectedDelta("gold-page-api", "GET", re.compile(r"^/api/gold(?:/.*)?$"), ANY_QUERY,
                  "the GOLD page itself (a NEW page, B audited alone): every /api/gold/* read, any query",
                  tabs=frozenset({"gold"})),
)

EXPECTED_DELTA_BY_ID: dict[str, ExpectedDelta] = {d.id: d for d in EXPECTED_DELTAS}
assert len(EXPECTED_DELTA_BY_ID) == len(EXPECTED_DELTAS), "expected delta ids must be unique"


def expected_delta(method: str, url: str, tab: str | None = None) -> str | None:
    """Id of the expected program delta this exact request is (method, path and query values), else None.

    The first declaration wins, so page-exact shapes come before any-query families. With ``tab`` given, a
    page-scoped delta matches only on its own pages; without it (the probe tags every request page-free) the
    tab check happens later, in ``expected_delta_applies`` (PARITY) — the tag alone never sets a request aside.
    """
    p = urlsplit(url)
    query = tuple(sorted(parse_qsl(p.query, keep_blank_values=True)))
    for d in EXPECTED_DELTAS:
        if method.upper() != d.method or not d.path.match(p.path) or (d.queries is not None and query not in d.queries):
            continue
        if tab is not None and d.tabs is not None and tab not in d.tabs:
            continue
        return d.id
    return None


def expected_delta_applies(delta_id: str | None, tab: str | None) -> bool:
    """True when ``delta_id`` names a declared delta that may be set aside on ``tab``.

    Page-independent deltas (``tabs=None``) apply everywhere; a page-scoped one applies only on its pages, and never
    when the tab is unknown (``tab=None``): an unattributed request is compared, not excused.
    """
    d = EXPECTED_DELTA_BY_ID.get(delta_id or "")
    if d is None:
        return False
    return d.tabs is None or (tab is not None and tab in d.tabs)


# ── gold program: pages with no A side, and intended structure changes on existing pages ──────────

@dataclass(frozen=True)
class NewPage:
    """A page the program ADDED: it has no A side in a parity run against a pre-program baseline."""

    id: str        # tab id (?tab=)
    code: str      # function code (the page's code chip)
    since: str     # which program added it
    note: str


EXPECTED_NEW_PAGES: tuple[NewPage, ...] = (
    NewPage("gold", "GOLD", "gold program (26 Oct 2026)",
            "the 43rd page (PLAN §a): a pre-program build has no ?tab=gold and renders the brief instead, so there is "
            "nothing to compare; B is audited on its own"),
)


def expected_new_page(tab: str) -> NewPage | None:
    """The ``NewPage`` declaration for ``tab`` (a page without an A side), else None."""
    return next((p for p in EXPECTED_NEW_PAGES if p.id == tab), None)


@dataclass(frozen=True)
class StructureDelta:
    """Intended fingerprint differences on ONE existing page (see the module docstring).

    ``a_only`` / ``b_only``: per fingerprint list field (``panels``, ``headings``, ``table_headers``,
    ``page_headers``, ``iframes``), the patterns an entry present only on that side may match to be set aside.
    ``counts``: scalar fingerprint fields (``tables``, ``canvas``, ``recharts``) whose values may differ.
    """

    tab: str
    a_only: dict[str, tuple[re.Pattern[str], ...]]
    b_only: dict[str, tuple[re.Pattern[str], ...]]
    counts: frozenset[str]
    note: str


def _rx(*patterns: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


# Panel titles / table headers are those of the pre-program UI (ui/components/GoldPreOpen.tsx, GoldAccuracyLog.tsx,
# Brief.tsx, McxGoldDesk.tsx) on the A side, and PLAN §b's prescribed shape on the B side. Patterns are matched against
# normalised text: "Fair open 08:45" reads "Fair open #:#".
EXPECTED_STRUCTURE_DELTAS: dict[str, StructureDelta] = {
    "commodity": StructureDelta(
        "commodity",
        a_only={"panels": _rx(r"^Gold Pre-Open Desk$", r"^Gap build-up$", r"^Your inputs$", r"^Context$", r"^Headlines$",
                              r"^Manual checks$", r"^Accuracy log$"),
                "table_headers": _rx(r"^Indicator \| Now \| At MCX close", r"\| Fair open #:# \|", r"^Day \| Settlement"),
                "page_headers": _rx(r"^CMDT\b")},
        b_only={"page_headers": _rx(r"^CMDT\b")},
        counts=frozenset({"tables"}),
        note="PLAN §b: CMDT drops <GoldPreOpen /> (desk, gap waterfall, inputs, context table, headlines, manual checks, "
             "accuracy log) and '· Gold desk' from its label/subtitle; the gold board tile gains a GOLD › chip"),
    "brief": StructureDelta(
        "brief",
        a_only={"panels": _rx(r"^Gold open \(MCX\)$")},
        b_only={},
        counts=frozenset(),
        note="PLAN §b: BRF's 'Gold open (MCX)' panel becomes one Line in the Market panel (from /api/gold/health.line)"),
    "world": StructureDelta(
        "world", a_only={}, b_only={}, counts=frozenset(),
        note="PLAN §b: WEI's GC=F row gains a second line and a hover card; no panel, table or heading changes"),
    # B side pinned (wave 1b) to what ui/components/McxGoldDesk.tsx renders: the selector panel "Contracts — MCX gold
    # family" (ui/components/gold/ContractsView.tsx ContractSelector, dense) with its "<FAMILY> EXPIRIES · OI LADDER"
    # table (Expiry | Source | settle ₹/10 g | band ₹ | OI lots | ΔOI lots | carry % p.a. | COMEX month | Tender); the
    # overlay is one LINE inside the Quote panel (no "overlay" panel on B: a retained overlay panel is a DIFF).
    "mcxgold": StructureDelta(
        "mcxgold",
        a_only={"panels": _rx(r"^COMEX × rupee overlay$", r"^Contract specs"),
                "table_headers": _rx(r"^Contract \| Lot \| Quote \| Tick"),
                "page_headers": _rx(r"^MCXG\b")},      # the 25 Oct subtitle names "contract specs · COMEX overlay"
        b_only={"panels": _rx(r"^Contracts — MCX gold family$"),
                "table_headers": _rx(r"^Expiry \| Source \| settle"),
                "page_headers": _rx(r"^MCXG\b")},      # the new subtitle names "contract selector · paper ticket"
        counts=frozenset({"tables"}),
        note="PLAN §b: MCXG's overlay shrinks to one line in the Quote panel (/api/mcx/overlay, GOLD › chip) and its "
             "specs card is replaced by the shared contract selector (c.selector, adds GOLDTEN); the subtitle follows"),
    "broker": StructureDelta(
        "broker",
        a_only={},
        b_only={"panels": _rx(r"^Auto-login \(TOTP\)$")},   # ui/components/gold/IciciTotpPanel.tsx, both BRKR layouts
        counts=frozenset(),
        note="PLAN §g: BRKR gains the 'Auto-login (TOTP)' panel in both connected and not-connected layouts"),
}


def structure_delta(tab: str | None) -> StructureDelta | None:
    """The declared intended structure change for ``tab`` (an existing page), else None."""
    return EXPECTED_STRUCTURE_DELTAS.get(tab) if tab else None


def partition_structure(tab: str | None, field: str, side: str, items: list[str]) -> tuple[list[str], list[str]]:
    """Split one-sided fingerprint entries into (declared, undeclared) for ``tab``/``field``/``side`` ('a' | 'b').

    Without a declaration for the tab (or the field on that side) everything is undeclared, i.e. compared as before.
    """
    d = structure_delta(tab)
    if d is None:
        return [], list(items)
    patterns = (d.a_only if side == "a" else d.b_only).get(field, ())
    if not patterns:
        return [], list(items)
    declared = [x for x in items if any(p.search(x) for p in patterns)]
    return declared, [x for x in items if x not in declared]

APP_ERROR_TEXT = re.compile(
    r"Application error: a client-side exception|Unhandled Runtime Error|Client-side Exception|"
    r"Uncaught Client Exception|Something went wrong|"
    # the terminal's own TabErrorBoundary (ui/components/shell/TabErrorBoundary.tsx): a sub-view that throws shows this and
    # nothing reaches the console as an uncaught error (SYS › DATA, 5 Nov 2026: invisible to the 43-page audit)
    r"\bfailed to render\b", re.IGNORECASE)


def is_stream_path(path: str) -> bool:
    """True for the six known long-lived streaming endpoints (SSE / NDJSON)."""
    return any(p.match(path) for p in STREAM_PATHS)


def is_platform_seam(path_or_url: str) -> bool:
    """True for a platform-seam endpoint (path, absolute URL or a parity endpoint key ``GET /api/x?k``)."""
    s = path_or_url.strip()
    if " " in s:                      # endpoint key: "<METHOD> <path>[?keys]"
        s = s.split(" ", 1)[1]
    path = urlsplit(s).path if "://" in s else s.split("?", 1)[0]
    return any(p.match(path) for p in PLATFORM_SEAM_PATHS)


def is_abort(failure_text: str | None) -> bool:
    """True when the engine reports a cancellation (not a connection/HTTP error)."""
    return failure_text is not None and bool(ABORT_FAILURE.match(failure_text.strip()))


@dataclass(frozen=True)
class FailureVerdict:
    """Classification of one failed request."""

    failure: bool          # counts toward the tab's failure total
    kind: str              # 'http' | 'network' | 'stream_abort_on_navigation' | 'third_party_http' | ...
    reason: str


def classify_request_failure(*, url: str, base_origin: str, status: int | None, failure_text: str | None,
                             left_tab: bool, started_after_drain: bool = False) -> FailureVerdict:
    """Classify one request that ended in HTTP >= 400 (``status``) or a network failure (``failure_text``).

    ``left_tab`` is True when the failure surfaced after the harness navigated away from the request's tab.
    ``started_after_drain`` is True when the request began after the drain had found nothing in flight, in the
    moment before the harness navigated away: a poll the harness's own navigation cut, never one that hung (5 Nov:
    MOV's 2 s quote poll fired between the drain's last check and leave(), and was reported as 'still pending after
    the drain window').
    """
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    first_party = origin == base_origin
    if status is not None and status >= 400:
        if first_party:
            return FailureVerdict(True, "http", f"HTTP {status}")
        return FailureVerdict(False, "third_party_http", f"HTTP {status} (third-party {parts.netloc})")
    text = (failure_text or "").strip() or "unknown failure"
    if not first_party:
        return FailureVerdict(False, "third_party_network", f"{text} (third-party {parts.netloc})")
    if is_abort(text):
        if is_stream_path(parts.path):
            if left_tab:
                return FailureVerdict(False, "stream_abort_on_navigation",
                                      f"{text} (allowlisted: stream torn down by navigation)")
            return FailureVerdict(True, "stream_abort_in_tab", f"{text} (stream aborted while the tab was still open)")
        if left_tab and started_after_drain:
            return FailureVerdict(False, "poll_cut_at_leave",
                                  f"{text} (started after the drain found nothing pending; cut by the harness leaving)")
        if left_tab:   # the probe drains first, so this request was still pending after dwell + drain window
            return FailureVerdict(True, "aborted_by_navigation",
                                  f"{text} (still pending after the drain window; aborted when the harness left)")
        return FailureVerdict(True, "aborted_in_tab", f"{text} (cancelled by the page: client timeout / AbortController)")
    return FailureVerdict(True, "network", text)


def origin_of(url: str) -> str:
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


# ── endpoint keys (parity) ────────────────────────────────────────────────────────────────────────

_NUMERIC = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:T[\d:.]+Z?)?$")
_HEXID = re.compile(r"^(?=.*\d)[0-9a-f]{8,}(?:-[0-9a-f]{4,})*$", re.IGNORECASE)
_SYMBOL = re.compile(r"^(?=.*[A-Z])[A-Z0-9&%._\-]{1,40}$")


def template_segment(seg: str) -> str:
    """Replace live-data path segments (tickers, numbers, dates, job ids) with placeholders.

    API words are lowercase (``/api/stocks/TCS/detail``), so an all-caps segment is a symbol.
    """
    if not seg:
        return seg
    if _DATE.match(seg):
        return "{date}"
    if _NUMERIC.match(seg):
        return "{n}"
    if _HEXID.match(seg):
        return "{id}"
    if _SYMBOL.match(seg):
        return "{sym}"
    return seg


def endpoint_key(method: str, url: str, *, template: bool = True) -> str:
    """``GET /api/stocks/{sym}/detail?days,limit``: method + (templated) path + sorted query KEYS only."""
    p = urlsplit(url)
    path = p.path
    if template:
        path = "/".join(template_segment(s) for s in path.split("/"))
    keys = sorted({k for k, _ in parse_qsl(p.query, keep_blank_values=True)})
    return f"{method.upper()} {path}" + (f"?{','.join(keys)}" if keys else "")


def status_class(status: int | None, failure_kind: str | None = None) -> str:
    """'2xx'…'5xx' for a response, 'ABORT' for an allowlisted abort, 'ERR' for a network failure."""
    if status is not None:
        return f"{status // 100}xx"
    if failure_kind == "stream_abort_on_navigation":
        return "ABORT"
    return "ERR"


# ── text normalisation (live numbers excluded) ─────────────────────────────────────────────────────

_WS = re.compile(r"\s+")
_NUMBERISH = re.compile(r"[+\-−]?[₹$]?\d[\d,]*(?:\.\d+)?(?:\s?(?:%|(?:cr|k|m|bn|ms|s)\b))?", re.IGNORECASE)
_ORIGIN = re.compile(r"(?:https?|wss?)://(?:localhost|127\.0\.0\.1)(?::\d+)?", re.IGNORECASE)
_ASSET = re.compile(r"/_next/static/[^\s\"')]+")   # hashed chunk names differ between builds


def normalize_text(s: str | None, *, limit: int = 240) -> str:
    """Collapse whitespace, mask numbers (prices, %, counts, times) and local origins, cap the length."""
    if not s:
        return ""
    s = _ORIGIN.sub("<origin>", s)
    s = _ASSET.sub("/_next/static/<asset>", s)
    s = _NUMBERISH.sub("#", s)
    s = _WS.sub(" ", s).strip()
    return s[:limit]
