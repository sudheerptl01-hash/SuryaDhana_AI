"""The typed alert engine (Terminal v2 PLAN 2.3, 43-page review M41): the rule model, the series catalogue and the
evaluator. PURE: no I/O, no clock reads (``now`` is passed in), no imports from the service. routers/alerts.py owns
storage (SQLite ``alert_rules`` / ``alert_fires``), the upstream reads and the HTTP routes.

A rule is ``{series, op, value, window, cooldown_min, repeat, channel, note}`` over any STORED series:

    series  "<kind>:<arg>[:<arg>…]"   e.g. price:TCS · iv_pctile:NIFTY · oi_strike:NIFTY:24500:CE · fii_net · data_stale:any
    op      above | below | cross_up | cross_down | change_pct | pctile_above | pctile_below | changed
    value   the level (above / below / cross_*), the size of the move in % (change_pct, either way), the percentile
            0–100 (pctile_*); unused by ``changed``
    window  change_pct: sessions back (1 = vs the previous session / the official previous close); pctile_*: the
            look-back in sessions (default 252)
    cooldown_min  minimum minutes between two fires of one rule
    repeat  once (a one-shot: the rule stops after its first fire, as the old price alerts did) | repeat
    channel mac | telegram | both
    note    the owner's own words (checked for direction words like every template)

Semantics (pinned by tests/test_alert_engine.py, each with a negative control):

* level ops (above, below, change_pct, pctile_*) are edge-armed: a rule fires when the condition becomes true while
  ARMED and disarms; it re-arms only once the condition is false again, so a level that stays crossed fires once,
  not every minute. A first observation that already satisfies the condition fires (as a TradingView "greater than").
* cross ops need the previous observation: cross_up fires when prev < value <= now (cross_down mirrored); the first
  observation only records the baseline. ``changed`` fires when the value differs from the previous observation.
* an unavailable observation never fires and never moves the baseline (a data-service outage is not a change).
* cooldown suppresses a fire; a level rule stays armed through it (it fires after the cooldown if still true).
* snoozed: evaluated (the baseline moves) but silent until ``snooze_until``; paused: not evaluated at all.

Honesty rules (PLAN §0, binding): every fire carries the series' badge (``arithmetic`` / ``context``; no ``signal``
exists), its as-of date and its source; NO template, label or note may carry a direction word (``direction_words``
scans them, tests scan every template); nothing here feeds the Decision Desk, the S1 shadow or a ticket price, and no
alert implies direction: "crossed 25,000 from under it", never a word about what happens next.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

# ── vocabulary ────────────────────────────────────────────────────────────────────────────────────────────────
OPS: tuple[str, ...] = ("above", "below", "cross_up", "cross_down", "change_pct", "pctile_above", "pctile_below", "changed")
LEVEL_OPS = frozenset({"above", "below", "change_pct", "pctile_above", "pctile_below"})
EDGE_OPS = frozenset({"cross_up", "cross_down", "changed"})
CHANNELS: tuple[str, ...] = ("mac", "telegram", "both")
REPEATS: tuple[str, ...] = ("once", "repeat")
STATUSES: tuple[str, ...] = ("active", "snoozed", "paused", "fired")
BADGE_ARITH, BADGE_CONTEXT = "arithmetic", "context"
DESCRIBES = "describes, does not predict"

PCTILE_WINDOW = 252
PCTILE_MIN_OBS = 20
HISTORY_DAYS = 400                 # stored sessions read for change_pct / pctile (row-limited reads)
HISTORY_CAL_DAYS = 600             # calendar days for the reads that count calendar days (FII / DII cash): ≈ 410 sessions
#: the longest window a rule may ask for: one less than the sessions the reads return, so a window can be met in full;
#: a store holding fewer sessions is said so in the reading (measure), never computed silently on less
MAX_WINDOW = HISTORY_DAYS - 1
MAX_COOLDOWN_MIN = 7 * 24 * 60
NOTE_MAX = 200
DEFAULT_REPEAT_COOLDOWN_MIN = 30

OP_WORDS: dict[str, str] = {
    "above": "at or over", "below": "at or under", "cross_up": "crosses from under", "cross_down": "crosses from over",
    "change_pct": "moves by ± %", "pctile_above": "percentile at or over", "pctile_below": "percentile at or under",
    "changed": "changes",
}

# Direction vocabulary: the LEARN validator's (reports/terminal_v2/LEARN/validate_learn.py, PLAN §0.1) plus "target"
# and "forecast" (the gold program's GOLD_DIRECTION_WORDS). Word-bounded, case-insensitive. Position NAMES (a short or
# long strangle / straddle, a short or long call / put, "short-option breakevens") are removed before the scan, both
# sides alike: they describe a paper position the owner holds, not a direction. "go long …" is never a position name
# (the removal skips a phrase right after "go "), and "expected move" is the options term, not a prediction.
DIRECTION_PATTERNS: tuple[str, ...] = (
    r"bullish", r"bearish", r"buy(s|ing)?", r"sell(s|ing)?", r"sold", r"overbought", r"oversold", r"break(out|down)s?",
    r"upside", r"downside", r"up-?trend", r"down-?trend", r"out-?perform\w*", r"under-?perform\w*", r"rall(y|ies)",
    r"long", r"short", r"short[- ]covering", r"long[- ]unwinding", r"(will|should|likely to|expected to)\s+(rise|fall|go up|go down)",
    r"price target", r"support level", r"resistance", r"go (long|short)", r"targets?", r"forecast\w*",
)
ALLOWED_PHRASES: tuple[str, ...] = (
    "short-option minimum", "short-option", "short option", "long-option", "long option", "short strangle", "short straddle",
    "long strangle", "long straddle", "short call", "short put", "long call", "long put", "expected move",
)
#: the owner's NOTE is also scanned for predictive phrasing a template never uses ("bounce expected", "goes higher
#: from here"): a note describes the level or the position, never what happens next
NOTE_PATTERNS: tuple[str, ...] = (
    r"bounc\w*", r"expect\w*", r"(go|goes|going|head|heads|heading|move|moves|moving|push|pushes|pushing|trade|trades|trading)\s+(higher|lower)",
    r"(higher|lower) (high|low)s?", r"(will|could|may|might|going to)\s+(rise|fall|climb|drop|recover|crash|go up|go down)",
)
_DIRECTION_RE = re.compile(r"\b(" + "|".join(DIRECTION_PATTERNS) + r")\b", re.IGNORECASE)
_NOTE_RE = re.compile(r"\b(" + "|".join(NOTE_PATTERNS) + r")\b", re.IGNORECASE)

_SYMBOL = re.compile(r"^[A-Z0-9&_-]{1,20}$")
_DATASET = re.compile(r"^[a-z0-9_]{1,60}$")
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
#: price:<alias> for the NSE indices the live hub serves (routers/live.py NSE_INDEX_TICKERS) — never Yahoo
INDEX_TICKERS: dict[str, str] = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "INDIAVIX": "^INDIAVIX", "NIFTYIT": "^CNXIT"}
#: F&O index underlyings the live hub does not quote: a price rule on one would never fire, so it is refused
NO_LIVE_INDEX = frozenset({"FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"})
DRIVER_INDICES = ("NIFTY", "BANKNIFTY")
#: the series id keeps the short name; the drivers store (data-service index_drivers, ingest.INDICES) is keyed by NSE's
#: index names, and /db/index-drivers passes ``index`` through as-is (review 6 Nov: index=NIFTY read nothing, ever)
DRIVER_STORE_NAMES: dict[str, str] = {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK"}
DRIVER_WINDOW = "20"


class RuleError(ValueError):
    """A rule (or a series id, or a Telegram line) that cannot be stored; the message says what to change."""


class ReadSkipped(Exception):
    """An upstream read the router chose not to make (a data-service read that can start a refresh, inside a restart
    freeze window). The series reads 'no value' with this message: it never fires and never moves the baseline."""


def _strip_allowed(text: str) -> str:
    cleaned = str(text or "")
    for phrase in ALLOWED_PHRASES:
        cleaned = re.sub(r"(?<!go )" + re.escape(phrase), " ", cleaned, flags=re.IGNORECASE)
    return cleaned


def direction_words(text: str | None) -> list[str]:
    """The direction words in ``text`` (empty list = clean)."""
    return sorted({m.group(0).lower() for m in _DIRECTION_RE.finditer(_strip_allowed(str(text or "")))})


def note_words(text: str | None) -> list[str]:
    """The direction words AND the predictive phrases in an owner's note (empty list = clean)."""
    cleaned = _strip_allowed(str(text or ""))
    return sorted({m.group(0).lower() for rx in (_DIRECTION_RE, _NOTE_RE) for m in rx.finditer(cleaned)})


# ── the series catalogue ──────────────────────────────────────────────────────────────────────────────────────
NUM_OPS = ("above", "below", "cross_up", "cross_down", "change_pct", "pctile_above", "pctile_below")
LEVELS = ("above", "below", "cross_up", "cross_down")


@dataclass(frozen=True)
class Kind:
    kind: str
    label: str            # with {symbol} / {strike} / {side} / {index} / {dataset} placeholders
    unit: str             # ₹ · % · vol pts · pctile · contracts · strike · % a. · pp · ₹ cr · days · flag · count · label
    badge: str
    cadence: str          # live (each minute in session) | eod (stored daily data) | hourly
    params: tuple[str, ...]
    ops: tuple[str, ...]
    source: str
    group: str
    definition: str
    example: str
    history: bool = False          # has a stored daily history (change_pct over N sessions, pctile_*)
    category: bool = False         # the value is a label, not a number (op ``changed`` only)
    optional: tuple[str, ...] = ()  # trailing optional params


KINDS: dict[str, Kind] = {k.kind: k for k in (
    Kind("price", "{symbol} price", "₹", BADGE_ARITH, "live", ("symbol",), LEVELS + ("change_pct",),
         "live NSE quote (Breeze tick → NSE → last close; never Yahoo)", "price",
         "last traded price of an NSE stock or index (NIFTY, BANKNIFTY, INDIAVIX, NIFTYIT); change_pct = the day move vs NSE's official previous close",
         "price:TCS above 3200"),
    Kind("iv30", "{symbol} IV30", "%", BADGE_ARITH, "eod", ("symbol",), NUM_OPS,
         "IV store (iv_summary_daily, NSE F&O bhavcopy, Black-76)", "options",
         "30-day constant-maturity ATM implied volatility of the stored EOD chain", "iv30:NIFTY pctile_above 80", history=True),
    Kind("iv_pctile", "{symbol} IV percentile (252 sessions)", "pctile", BADGE_ARITH, "eod", ("symbol",), LEVELS,
         "IV store (iv_summary_daily)", "options",
         "share of the past 252 sessions whose IV30 was below today's (0–100)", "iv_pctile:NIFTY above 80", history=True),
    Kind("iv_rank", "{symbol} IV rank (252 sessions)", "pctile", BADGE_ARITH, "eod", ("symbol",), LEVELS,
         "IV store (iv_summary_daily)", "options",
         "where today's IV30 sits between its 252-session minimum (0) and maximum (100)", "iv_rank:BANKNIFTY below 20", history=True),
    # the stored iv_minus_rv20 is IV30_CM − RV20_CC (fo_iv catalog IV_MINUS_RV20, review M01: close-to-close is the
    # estimator of record); tests/test_alert_engine.py reads the catalog row and fails if this text names another one
    Kind("iv_rv", "{symbol} IV − RV20 (cc)", "vol pts", BADGE_CONTEXT, "eod", ("symbol",), NUM_OPS,
         "IV store (iv_summary_daily.iv_minus_rv20)", "options",
         "IV30 minus the 20-session close-to-close realised vol (RV20 cc), vol points", "iv_rv:NIFTY below -3", history=True),
    Kind("skew25", "{symbol} 25Δ skew", "vol pts", BADGE_CONTEXT, "eod", ("symbol",), NUM_OPS,
         "IV store (iv_summary_daily)", "options",
         "25-delta put IV minus 25-delta call IV on the 30-day surface (vol points)", "skew25:NIFTY above 4", history=True),
    Kind("straddle", "{symbol} ATM straddle", "₹", BADGE_ARITH, "eod", ("symbol",), LEVELS,
         "stored EOD option chain (NSE F&O bhavcopy)", "options",
         "ATM call + ATM put close of the nearest (or the named) expiry, per unit; the ATM strike and the expiry roll",
         "straddle:NIFTY below 300", optional=("expiry",)),
    Kind("oi_strike", "{symbol} {strike} {side} OI", "contracts", BADGE_ARITH, "eod", ("symbol", "strike", "side"), LEVELS + ("change_pct",),
         "stored EOD option chain (NSE F&O bhavcopy)", "options",
         "open interest at one strike in contracts (the bhavcopy's shares ÷ the lot size, the unit OMON prints); change_pct vs the previous session",
         "oi_strike:NIFTY:24500:CE change_pct 25", optional=("expiry",)),
    Kind("oi_wall", "{symbol} {side} OI wall", "strike", BADGE_CONTEXT, "eod", ("symbol", "side"), ("changed",) + LEVELS,
         "stored EOD option chain (NSE F&O bhavcopy)", "options",
         "the strike holding the most open interest for calls (CE) or puts (PE) of the nearest (or the named) expiry",
         "oi_wall:NIFTY:CE changed", optional=("expiry",)),
    Kind("basis", "{symbol} futures basis (annualised)", "% a.", BADGE_CONTEXT, "eod", ("symbol",), NUM_OPS,
         "nse_fo_daily near-month future vs spot", "futures",
         "near-month futures close vs spot, annualised over calendar days to expiry", "basis:NIFTY below 0", history=True),
    Kind("rollover", "{symbol} rollover", "%", BADGE_CONTEXT, "eod", ("symbol",), LEVELS,
         "derived futures panel (nse_fo_daily)", "futures",
         "share of futures open interest already in the next and far series this cycle", "rollover:NIFTY above 60"),
    Kind("rollover_pace", "{symbol} rollover vs the 3-cycle average at the same DTE", "pp", BADGE_CONTEXT, "eod", ("symbol",), LEVELS,
         "derived futures panel (nse_fo_daily): this cycle's curve vs the previous 3 cycles' average by days to expiry", "futures",
         "this cycle's rollover % minus the average rollover % of the previous 3 cycles at the same days to expiry (percentage points)",
         "rollover_pace:NIFTY above 10"),
    Kind("fo_ban", "{symbol} F&O ban (1 = in the ban list)", "flag", BADGE_ARITH, "eod", ("symbol",), ("cross_up", "cross_down", "changed"),
         "NSE F&O ban list (stored surveillance)", "events",
         "1 while NSE lists the underlying in the F&O ban period; cross_up 0.5 = entry, cross_down 0.5 = exit",
         "fo_ban:KAYNES cross_up 0.5"),
    Kind("results_days", "{symbol} days to results", "days", BADGE_ARITH, "eod", ("symbol",), ("below", "above"),
         "NSE corporate calendar (stored nse_events)", "events",
         "calendar days until the next results date on NSE's calendar (no value when none is known in 60 days); dated by the day "
         "the calendar row was first stored",
         "results_days:TCS below 5"),
    Kind("fii_net", "FII cash net", "₹ cr", BADGE_CONTEXT, "eod", (), NUM_OPS,
         "NSE FII/DII cash statistics (stored)", "flows",
         "FII/FPI cash-market purchases minus sales for the latest session (₹ cr); NSE publishes it the evening after",
         "fii_net pctile_above 95", history=True),
    Kind("dii_net", "DII cash net", "₹ cr", BADGE_CONTEXT, "eod", (), NUM_OPS,
         "NSE FII/DII cash statistics (stored)", "flows",
         "DII cash-market purchases minus sales for the latest session (₹ cr)", "dii_net pctile_below 5", history=True),
    Kind("vix", "India VIX", "", BADGE_ARITH, "live", (), NUM_OPS,
         "live NSE quote in session (^INDIAVIX); vix_daily (NSE file) otherwise", "options",
         "India VIX level; change_pct window 1 = the day move vs the previous close", "vix change_pct 10", history=True),
    Kind("nifty_driver", "{index} 20-session driver", "label", BADGE_CONTEXT, "eod", ("index",), ("changed",),
         "index attribution store (index_driver_state; NIFTY = NIFTY 50, BANKNIFTY = NIFTY BANK)", "index",
         "the member contributing the most index points over 20 sessions (with the store's hysteresis)",
         "nifty_driver:NIFTY changed", category=True),
    Kind("gold_health", "Gold health clauses", "label", BADGE_CONTEXT, "eod", (), ("changed",),
         "stored gold health snapshot (gold_health_daily)", "gold",
         "the set of clauses in the stored daily gold health sentence (numbers removed, so a clause changes, not a figure)",
         "gold_health changed", category=True),
    Kind("data_stale", "Data: {dataset} stale", "flag", BADGE_ARITH, "hourly", ("dataset",), ("cross_up", "cross_down", "changed", "above", "below"),
         "SYS › DATA (/api/data/health)", "data",
         "1 while a dataset is amber or red on SYS › DATA (dataset 'any': the number of amber + red datasets)",
         "data_stale:any above 1"),
)}

NAMED_SYMBOLS = {"fii_net": "FII", "dii_net": "DII", "vix": "INDIAVIX", "gold_health": "GOLD", "data_stale": "DATA"}


# ── rule parsing and validation ──────────────────────────────────────────────────────────────────────────────
def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def parse_series(series: str) -> tuple[Kind, dict[str, Any]]:
    """'oi_strike:NIFTY:24500:CE' → (KINDS['oi_strike'], {'symbol': 'NIFTY', 'strike': 24500.0, 'side': 'CE'})."""
    if not isinstance(series, str) or not series.strip():
        raise RuleError("series is empty: name one, e.g. price:TCS or iv_pctile:NIFTY (GET /api/alerts/series)")
    head, *args = [p.strip() for p in series.strip().split(":")]
    kind = KINDS.get(head.lower())
    if kind is None:
        raise RuleError(f"unknown series kind {head!r}: one of {', '.join(KINDS)}")
    names = kind.params + kind.optional
    if len(args) < len(kind.params) or len(args) > len(names):
        shape = ":".join([kind.kind, *(f"<{p}>" for p in kind.params), *(f"[<{p}>]" for p in kind.optional)])
        raise RuleError(f"{kind.kind} takes {shape}")
    params: dict[str, Any] = {}
    for name, raw in zip(names, args, strict=False):
        params[name] = _param(kind, name, raw)
    return kind, params


def _param(kind: Kind, name: str, raw: str) -> Any:
    if name == "symbol":
        s = raw.upper().removesuffix(".NS")
        if not _SYMBOL.match(s):
            raise RuleError(f"bad symbol {raw!r}: NSE symbols look like TCS, M&M, BAJAJ-AUTO")
        if kind.kind == "price" and s.startswith("^"):
            raise RuleError("name the index: NIFTY, BANKNIFTY, INDIAVIX or NIFTYIT")
        if kind.kind == "price" and s in NO_LIVE_INDEX:
            raise RuleError(f"{s} has no live quote here (only NIFTY, BANKNIFTY, INDIAVIX, NIFTYIT): alert on its options or futures series")
        return s
    if name == "index":
        s = raw.upper()
        if s not in DRIVER_INDICES:
            raise RuleError(f"index must be one of {', '.join(DRIVER_INDICES)}")
        return s
    if name == "strike":
        v = _num(raw)
        if v is None or v <= 0:
            raise RuleError(f"bad strike {raw!r}")
        return v
    if name == "side":
        s = raw.upper()
        if s not in ("CE", "PE"):
            raise RuleError("side must be CE or PE")
        return s
    if name == "expiry":
        if not _ISO_DAY.match(raw):
            raise RuleError(f"expiry must be YYYY-MM-DD, not {raw!r}")
        return raw
    if name == "dataset":
        s = raw.lower()
        if s != "any" and not _DATASET.match(s):
            raise RuleError(f"bad dataset id {raw!r} (an id from SYS › DATA, or 'any')")
        return s
    raise RuleError(f"unknown parameter {name}")  # pragma: no cover - the catalogue names only the above


def series_id(kind: str, params: dict[str, Any]) -> str:
    k = KINDS[kind]
    out = [kind]
    for name in k.params + k.optional:
        v = params.get(name)
        if v is None:
            break
        out.append(fmt_plain(v) if isinstance(v, float) else str(v))
    return ":".join(out)


def rule_symbol(kind: str, params: dict[str, Any]) -> str:
    """The key the fired inbox groups by: the underlying, the index, or a fixed name (FII, GOLD, DATA)."""
    return str(params.get("symbol") or params.get("index") or NAMED_SYMBOLS.get(kind) or kind.upper())


def validate_rule(raw: dict[str, Any]) -> dict[str, Any]:
    """A request body → the normalised rule fields (no id, state or timestamps), or RuleError."""
    if not isinstance(raw, dict):
        raise RuleError("a rule is a JSON object")
    kind, params = parse_series(str(raw.get("series") or ""))
    op = str(raw.get("op") or "").strip().lower()
    if op not in OPS:
        raise RuleError(f"op must be one of {', '.join(OPS)}")
    if op not in kind.ops:
        raise RuleError(f"{kind.kind} supports {', '.join(kind.ops)} (not {op})")
    value = _num(raw.get("value"))
    window = raw.get("window")
    win: int | None = None
    if window not in (None, ""):
        w = _num(window)
        if w is None or w != int(w) or not 1 <= int(w) <= MAX_WINDOW:
            raise RuleError(f"window must be a whole number of sessions, 1–{MAX_WINDOW}")
        win = int(w)
    if op == "changed":
        value = None
        win = None
    elif value is None and kind.unit == "flag" and raw.get("value") in (None, ""):
        value = 0.5                                   # a 0/1 flag: cross_up 0.5 = it became 1
    elif value is None:
        raise RuleError("value is required (a number)")
    if op == "change_pct":
        if not 0 < value <= 500:  # type: ignore[operator]
            raise RuleError("change_pct value is the size of the move in % (either way), 0 < value ≤ 500")
        win = win or 1
        if win > 1 and not kind.history:
            raise RuleError(f"{kind.kind} keeps no daily history here: change_pct supports window 1 only")
    elif op in ("pctile_above", "pctile_below"):
        if not 0 <= value <= 100:  # type: ignore[operator]
            raise RuleError("a percentile is 0–100")
        win = win or PCTILE_WINDOW
        if win < PCTILE_MIN_OBS:
            raise RuleError(f"a percentile needs a window of at least {PCTILE_MIN_OBS} sessions")
    elif op != "changed":
        win = None
    if kind.unit == "pctile" and op in LEVELS and not 0 <= value <= 100:  # type: ignore[operator]
        raise RuleError("IV percentile and rank run 0–100")
    repeat = str(raw.get("repeat") or "once").lower()
    if repeat not in REPEATS:
        raise RuleError("repeat must be once or repeat")
    channel = str(raw.get("channel") or "both").lower()
    if channel not in CHANNELS:
        raise RuleError("channel must be mac, telegram or both")
    cd_raw = raw.get("cooldown_min")
    cooldown = _num(cd_raw) if cd_raw not in (None, "") else (DEFAULT_REPEAT_COOLDOWN_MIN if repeat == "repeat" else 0)
    if cooldown is None or cooldown < 0 or cooldown > MAX_COOLDOWN_MIN:
        raise RuleError(f"cooldown_min must be 0–{MAX_COOLDOWN_MIN} minutes")
    note = str(raw.get("note") or "").strip()
    if len(note) > NOTE_MAX:
        raise RuleError(f"note is longer than {NOTE_MAX} characters")
    if "\n" in note or "\r" in note:
        raise RuleError("note must be one line")
    words = note_words(note)
    if words:
        raise RuleError(f"the note carries direction words {words}: an alert describes a level or a position, never a direction")
    return {"series": series_id(kind.kind, params), "kind": kind.kind, "params": params, "symbol": rule_symbol(kind.kind, params),
            "op": op, "value": value, "window": win, "cooldown_min": int(cooldown), "repeat": repeat, "channel": channel,
            "note": note or None}


# ── text ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _group_in(n: float, dec: int) -> str:
    s = f"{abs(n):.{dec}f}"
    ip, _, fp = s.partition(".")
    if len(ip) > 3:
        head, tail = ip[:-3], ip[-3:]
        parts: list[str] = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        ip = ",".join(parts) + "," + tail
    return ("−" if n < 0 else "") + ip + (f".{fp}" if fp else "")


def fmt_plain(v: float) -> str:
    """24500.0 → '24500', 24512.5 → '24512.5' (series ids)."""
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def fmt_value(v: Any, unit: str) -> str:
    if v is None:
        return "—"
    if isinstance(v, str):
        return v
    f = float(v)
    if unit == "₹":
        return f"₹{_group_in(f, 2)}"
    if unit in ("%", "% a."):
        return f"{_group_in(f, 2)} %"
    if unit == "vol pts":
        return f"{_group_in(f, 2)} vol pts"
    if unit == "pctile":
        return fmt_plain(f) if f.is_integer() else _group_in(f, 1)
    if unit == "count":
        return _group_in(f, 0)
    if unit == "contracts":                          # OMON's unit (review M05); a lot change can leave a fraction
        return f"{_group_in(f, 0) if f.is_integer() else _group_in(f, 1)} contracts"
    if unit == "pp":
        return f"{'+' if f > 0 else ''}{_group_in(f, 1)} pp"
    if unit == "strike":
        return _group_in(f, 0) if f.is_integer() else _group_in(f, 1)
    if unit == "₹ cr":
        return ("+" if f > 0 else "") + f"₹{_group_in(f, 0)} cr"
    if unit == "days":
        return f"{_group_in(f, 0)} day{'' if abs(f) == 1 else 's'}"
    if unit == "flag":
        return _group_in(f, 0)
    return _group_in(f, 2)


def unit_for(kind: str, params: dict[str, Any]) -> str:
    if kind == "price" and params.get("symbol") in INDEX_TICKERS:
        return ""                                    # index points
    if kind == "data_stale" and params.get("dataset") == "any":
        return "count"
    return KINDS[kind].unit


def label_for(kind: str, params: dict[str, Any]) -> str:
    k = KINDS[kind]
    lab = k.label.format(symbol=params.get("symbol", ""), strike=fmt_plain(params["strike"]) if "strike" in params else "",
                         side=params.get("side", ""), index=params.get("index", ""), dataset=params.get("dataset", ""))
    if kind == "data_stale" and params.get("dataset") == "any":
        lab = "Data: datasets amber or red"
    if params.get("expiry"):
        lab += f" ({params['expiry']} expiry)"
    return lab


def condition_text(rule: dict[str, Any]) -> str:
    """'≥ 80' style condition words for a rule (the rules table, Telegram /rules)."""
    kind, params, op, value = rule["kind"], rule.get("params") or {}, rule["op"], rule.get("value")
    unit = unit_for(kind, params)
    v = fmt_value(value, unit)
    win = rule.get("window")
    if unit == "flag" and op in ("cross_up", "cross_down", "changed"):      # a 0/1 flag reads as its two states
        on = {"fo_ban": "enters NSE's F&O ban list", "data_stale": "turns amber or red"}.get(kind, "turns on")
        off = {"fo_ban": "leaves NSE's F&O ban list", "data_stale": "is fresh again"}.get(kind, "turns off")
        return on if op == "cross_up" else off if op == "cross_down" else f"{on.split(' ', 1)[0]} or {off}"
    if op == "above":
        return f"at or over {v}"
    if op == "below":
        return f"at or under {v}"
    if op == "cross_up":
        return f"crosses {v} from under it"
    if op == "cross_down":
        return f"crosses {v} from over it"
    if op == "change_pct":
        span = "on the day" if (win or 1) == 1 and KINDS[kind].cadence == "live" else f"over {win or 1} session{'s' if (win or 1) > 1 else ''}"
        return f"moves ±{fmt_plain(float(value or 0.0))} % {span}"
    if op == "pctile_above":
        return f"percentile at or over {fmt_plain(float(value or 0.0))} (of {win or PCTILE_WINDOW} sessions)"
    if op == "pctile_below":
        return f"percentile at or under {fmt_plain(float(value or 0.0))} (of {win or PCTILE_WINDOW} sessions)"
    return "changes"


def rule_summary(rule: dict[str, Any]) -> str:
    """One line: 'NIFTY IV percentile (252 sessions) at or over 80 · repeat, cooldown 30 min · mac + telegram'."""
    kind = rule["kind"]
    rep = "one-shot" if rule.get("repeat") == "once" else f"repeat, cooldown {rule.get('cooldown_min') or 0} min"
    ch = {"mac": "Mac", "telegram": "Telegram", "both": "Mac + Telegram"}.get(rule.get("channel") or "both", "Mac + Telegram")
    return f"{label_for(kind, rule.get('params') or {})} {condition_text(rule)} · {rep} · {ch}"


# ── observations and evaluation ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Observation:
    """One read of a series. ``history`` = earlier daily values, oldest first, NOT including ``value``."""
    value: float | str | None
    as_of: str | None = None
    source: str = ""
    history: tuple[float, ...] = ()
    change_pct: float | None = None       # precomputed move for window 1 (a live quote's day move, OI's change)
    note: str | None = None               # why the value is missing / what it is
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Evaluation:
    state: dict[str, Any]
    status: str
    snooze_until: str | None
    fire: dict[str, Any] | None
    satisfied: bool | None                 # None = could not be measured
    metric: float | None
    reason: str | None


def percentile_of(value: float, hist: list[float]) -> float:
    """The share of ``hist`` strictly below ``value`` × 100 (derivatives.py's iv_percentile definition)."""
    return round(100.0 * sum(1 for h in hist if h < value) / len(hist), 2)


def measure(rule: dict[str, Any], obs: Observation) -> tuple[float | None, str | None]:
    """The number the op compares (the value, the move in %, the percentile), or (None, why)."""
    op, v = rule["op"], obs.value
    if v is None:
        return None, obs.note or "no value"
    if op == "changed":
        return None, None
    if isinstance(v, str):
        return None, "the series is a label: only 'changed' applies"
    if op == "change_pct":
        win = rule.get("window") or 1
        if win == 1 and obs.change_pct is not None:
            return float(obs.change_pct), None
        if len(obs.history) < win:
            return None, f"not enough history ({len(obs.history)} of {win} sessions)"
        base = obs.history[-win]
        if not base:
            return None, "the base value is zero"
        return round((float(v) / base - 1.0) * 100.0, 4), None
    if op in ("pctile_above", "pctile_below"):
        win = rule.get("window") or PCTILE_WINDOW
        hist = [h for h in obs.history[-win:] if h is not None]
        if len(hist) < PCTILE_MIN_OBS:
            return None, f"not enough history for a percentile ({len(hist)} of ≥ {PCTILE_MIN_OBS} sessions)"
        # the store may hold fewer sessions than the window: the reading says so (the fire text prints the real n)
        short = f"percentile over {len(hist)} of the {win} sessions asked (the store holds {len(hist)})" if len(hist) < win else None
        return percentile_of(float(v), hist), short
    return float(v), None


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(a)), abs(float(b)))
    return a == b


def condition(rule: dict[str, Any], metric: float | None, value: Any, prev: Any) -> bool | None:
    op = rule["op"]
    if op == "changed":
        if value is None or prev is None:
            return None
        return not _same(value, prev)
    if rule.get("value") is None:
        return None
    x = float(rule["value"])
    if op in ("cross_up", "cross_down"):
        if metric is None or not isinstance(prev, (int, float)):
            return None
        return (prev < x <= metric) if op == "cross_up" else (prev > x >= metric)
    if metric is None:
        return None
    if op in ("above", "pctile_above"):
        return metric >= x
    if op in ("below", "pctile_below"):
        return metric <= x
    if op == "change_pct":
        return abs(metric) >= x
    return None  # pragma: no cover


def _parse_ts(s: Any) -> datetime | None:
    if not isinstance(s, str) or not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def evaluate(rule: dict[str, Any], obs: Observation, now: datetime) -> Evaluation:
    """One rule against one observation at ``now`` (timezone-aware) → the next state, status and the fire (if any)."""
    state = dict(rule.get("state") or {})
    status = rule.get("status") or "active"
    snooze_until = rule.get("snooze_until")
    if status == "snoozed":
        until = _parse_ts(snooze_until)
        if until is None or until <= now:
            status, snooze_until = "active", None
    if status in ("paused", "fired"):
        return Evaluation(state, status, snooze_until, None, None, None, f"rule is {status}")
    prev = state.get("last_value")
    metric, why = measure(rule, obs)
    state["checked_at"] = now.isoformat(timespec="seconds")
    if obs.value is None:
        state["last_error"] = why
        return Evaluation(state, status, snooze_until, None, None, None, why)
    state.pop("last_error", None)
    sat = condition(rule, metric, obs.value, prev)
    # the baseline moves on every real observation (a snoozed rule's edge during the snooze is dropped)
    state["last_value"] = obs.value
    state["last_as_of"] = obs.as_of
    prev_expiry = state.get("last_expiry")
    if obs.extra.get("expiry"):                     # the chain series follow the nearest expiry: remember which one
        state["last_expiry"] = obs.extra["expiry"]
    if metric is not None:
        state["last_metric"] = metric
    if sat is None:
        return Evaluation(state, status, snooze_until, None, None, metric, why or ("baseline recorded" if prev is None else None))
    armed = bool(state.get("armed", True))
    if rule["op"] in LEVEL_OPS and not sat:
        state["armed"] = True
        return Evaluation(state, status, snooze_until, None, False, metric, None)
    if not sat:
        return Evaluation(state, status, snooze_until, None, False, metric, None)
    if rule["op"] in LEVEL_OPS and not armed:
        return Evaluation(state, status, snooze_until, None, True, metric, "already fired; re-arms once the condition is false")
    if status == "snoozed":
        if rule["op"] in EDGE_OPS:
            state["suppressed"] = int(state.get("suppressed", 0)) + 1
        return Evaluation(state, status, snooze_until, None, True, metric, f"snoozed until {snooze_until}")
    last = _parse_ts(state.get("last_fired_at"))
    cd = int(rule.get("cooldown_min") or 0)
    if last is not None and cd and now - last < timedelta(minutes=cd):
        if rule["op"] in EDGE_OPS:
            state["suppressed"] = int(state.get("suppressed", 0)) + 1
        return Evaluation(state, status, snooze_until, None, True, metric, f"cooldown until {(last + timedelta(minutes=cd)).isoformat(timespec='minutes')}")
    if rule["op"] in LEVEL_OPS:
        state["armed"] = False
    state["last_fired_at"] = now.isoformat(timespec="seconds")
    state["fires"] = int(state.get("fires", 0)) + 1
    fire = build_fire(rule, obs, metric, prev, now, prev_expiry=prev_expiry)
    if rule.get("repeat") == "once":
        status = "fired"
    return Evaluation(state, status, snooze_until, fire, True, metric, None)


def fire_text(rule: dict[str, Any], obs: Observation, metric: float | None, prev: Any, prev_expiry: str | None = None) -> str:
    """The direction-free sentence a fire sends (Mac, Telegram, the inbox). ``prev_expiry``: the expiry the previous
    reading came from (chain series): when the nearest expiry rolled in between, the text says the two readings are two
    contracts."""
    kind, params, op = rule["kind"], rule.get("params") or {}, rule["op"]
    unit = unit_for(kind, params)
    lab = label_for(kind, params)
    v, x = obs.value, rule.get("value")
    fv = fmt_value(v, unit)
    if kind == "fo_ban":
        what = f"{params['symbol']} {'is now in' if v == 1 else 'is no longer in'} NSE's F&O ban list"
    elif kind == "data_stale" and params.get("dataset") != "any":
        what = f"dataset {params['dataset']} {'is now amber or red' if v == 1 else 'is no longer amber or red'} on SYS › DATA"
    elif kind == "results_days":
        when = obs.extra.get("event_date")
        what = f"{params['symbol']} results in {fmt_value(v, 'days')}{f' ({when})' if when else ''} (alert: {condition_text(rule)})"
    elif op == "changed":
        what = f"{lab} changed: {fmt_value(prev, unit)} → {fv}"
    elif op == "above":
        what = f"{lab} {fv} is at or over {fmt_value(x, unit)}"
    elif op == "below":
        what = f"{lab} {fv} is at or under {fmt_value(x, unit)}"
    elif op == "cross_up":
        what = f"{lab} crossed {fmt_value(x, unit)} from under it ({fmt_value(prev, unit)} → {fv})"
    elif op == "cross_down":
        what = f"{lab} crossed {fmt_value(x, unit)} from over it ({fmt_value(prev, unit)} → {fv})"
    elif op == "change_pct":
        win = rule.get("window") or 1
        span = "on the day" if win == 1 and KINDS[kind].cadence == "live" else f"over {win} session{'s' if win > 1 else ''}"
        what = f"{lab} moved {_signed(metric)} % {span} (alert at ±{fmt_plain(float(x or 0.0))} %), now {fv}"
    else:
        n = min(len(obs.history), rule.get("window") or PCTILE_WINDOW)
        what = f"{lab} {fv} sits at percentile {fmt_plain(round(metric or 0.0, 1))} of {n} sessions (alert: {condition_text(rule)})"
    cur_expiry = obs.extra.get("expiry")
    if prev_expiry and cur_expiry and prev_expiry != cur_expiry and not params.get("expiry"):
        what += f" · the nearest expiry rolled {prev_expiry} → {cur_expiry}: the two readings are two contracts"
    tail = [f"as of {obs.as_of}" if obs.as_of else "undated", obs.source or KINDS[kind].source, KINDS[kind].badge]
    out = f"{what} · {' · '.join(t for t in tail if t)}"
    if rule.get("note"):
        out += f" · note: {rule['note']}"
    return out


def _signed(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{'−' if v < 0 else '+'}{abs(v):.1f}"


def build_fire(rule: dict[str, Any], obs: Observation, metric: float | None, prev: Any, now: datetime,
               prev_expiry: str | None = None) -> dict[str, Any]:
    kind = rule["kind"]
    return {
        "rule_id": rule.get("id"), "series": rule["series"], "kind": kind, "symbol": rule.get("symbol") or rule_symbol(kind, rule.get("params") or {}),
        "op": rule["op"], "threshold": rule.get("value"), "window": rule.get("window"), "observed": obs.value, "metric": metric, "prev": prev,
        "as_of": obs.as_of, "source": obs.source or KINDS[kind].source, "badge": KINDS[kind].badge, "unit": unit_for(kind, rule.get("params") or {}),
        "channel": rule.get("channel") or "both", "note": rule.get("note"), "at": now.isoformat(timespec="seconds"),
        "text": fire_text(rule, obs, metric, prev, prev_expiry), "label": label_for(kind, rule.get("params") or {}),
        "expiry": obs.extra.get("expiry"), "prev_expiry": prev_expiry,
    }


# ── extraction: the upstream payloads → an Observation (pure; routers/alerts.py fetches) ─────────────────────
@dataclass(frozen=True)
class Need:
    """One upstream read: ``source`` quote (a live-hub ticker) | ds (a data-service GET) | local (an in-process view).
    ``side_effect``: the data-service route can start a refresh of its own when read (a background NSE fetch and a
    DuckDB write, or a panel build): /db/fii-dii-cash (≤ every 30 min), /db/events (feed older than 12 h),
    /db/surveillance (NSE files re-read hourly), /db/fo/rollover (the futures panel). The router skips these inside the
    restart freeze windows (routers/alerts.py FREEZE_WINDOWS); every other read is of stored tables only."""
    source: str
    path: str
    params: tuple[tuple[str, str], ...] = ()
    ttl_s: float = 300.0
    side_effect: bool = False


IV_FIELDS = {"iv30": "iv30_cm", "iv_pctile": "iv_pctile_252", "iv_rank": "iv_rank_252", "iv_rv": "iv_minus_rv20", "skew25": "skew_25d_30"}


def quote_ticker(kind: str, params: dict[str, Any]) -> str | None:
    if kind == "vix":
        return "^INDIAVIX"
    if kind == "price":
        s = params["symbol"]
        return INDEX_TICKERS.get(s) or f"{s}.NS"
    return None


def needs(kind: str, params: dict[str, Any], today: date, live: bool = True) -> list[Need]:
    """The reads one series needs. ``live=False`` (out of session): no quote reads (vix falls back to vix_daily)."""
    sym = str(params.get("symbol") or "")
    if kind == "price":
        return [Need("quote", quote_ticker(kind, params) or "", ttl_s=0.0)] if live else []
    if kind in IV_FIELDS:
        return [Need("ds", "/db/iv/summary", (("symbol", sym), ("days", str(HISTORY_DAYS))), 300.0)]
    if kind in ("straddle", "oi_strike", "oi_wall"):
        q = (("expiry", params["expiry"]),) if params.get("expiry") else ()
        return [Need("ds", f"/db/option-chain/{sym}", q, 300.0)]
    if kind == "basis":
        return [Need("ds", "/db/fo/basis-history", (("symbol", sym), ("days", str(HISTORY_DAYS))), 900.0)]
    if kind in ("rollover", "rollover_pace"):         # one read: cycles=3 → avg3 and the by-DTE curve span 3 cycles
        return [Need("ds", "/db/fo/rollover", (("symbol", sym), ("cycles", "3")), 1800.0, side_effect=True)]
    if kind == "fo_ban":
        return [Need("ds", "/db/surveillance", (), 600.0, side_effect=True)]
    if kind == "results_days":
        return [Need("ds", "/db/events", (("start", today.isoformat()), ("end", (today + timedelta(days=60)).isoformat())), 1800.0,
                     side_effect=True)]
    if kind in ("fii_net", "dii_net"):               # this route counts calendar days
        return [Need("ds", "/db/fii-dii-cash", (("days", str(HISTORY_CAL_DAYS)),), 900.0, side_effect=True)]
    if kind == "vix":
        daily = Need("ds", "/db/vix-daily", (("days", str(HISTORY_DAYS)),), 900.0)
        return ([Need("quote", "^INDIAVIX", ttl_s=0.0)] if live else []) + [daily]
    if kind == "nifty_driver":                       # the store's key: NIFTY 50 / NIFTY BANK (never the short id)
        return [Need("ds", "/db/index-drivers", (("index", DRIVER_STORE_NAMES[params["index"]]),), 900.0)]
    if kind == "gold_health":
        return [Need("ds", "/db/gold/health-daily", (("from", (today - timedelta(days=10)).isoformat()),), 1800.0)]
    if kind == "data_stale":
        return [Need("local", "data_health", (), 600.0)]
    raise RuleError(f"no reads defined for {kind}")  # pragma: no cover


def _rows(payload: Any, key: str = "rows") -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return [r for r in payload[key] if isinstance(r, dict)]
    return []


def _day(v: Any) -> str | None:
    s = str(v or "")[:10]
    return s if _ISO_DAY.match(s) else None


def _series_obs(rows: list[dict[str, Any]], date_key: str, value_key: str, source: str, today: date | None = None) -> Observation:
    """The latest dated row's value + the earlier non-null values (oldest first). The latest row is the latest SESSION:
    a null there is reported missing, never filled from an older date."""
    dated = sorted((r for r in rows if _day(r.get(date_key))), key=lambda r: _day(r.get(date_key)) or "")
    if today is not None:
        dated = [r for r in dated if (_day(r.get(date_key)) or "") <= today.isoformat()]
    if not dated:
        return Observation(None, None, source, note="nothing stored yet")
    last = dated[-1]
    v = _num(last.get(value_key))
    hist = tuple(x for x in (_num(r.get(value_key)) for r in dated[:-1]) if x is not None)
    as_of = _day(last.get(date_key))
    if v is None:
        return Observation(None, as_of, source, hist, note=f"no {value_key} stored for {as_of}")
    return Observation(v, as_of, source, hist)


def extract(kind: str, params: dict[str, Any], got: dict[Need, Any], today: date, live: bool = True) -> Observation:
    """The observation for one series from the reads ``needs`` named (a missing / failed read → value None + why)."""
    src = KINDS[kind].source
    reads = needs(kind, params, today, live)
    payloads = [got.get(n) for n in reads]
    if any(isinstance(p, BaseException) for p in payloads) and kind not in ("vix",):
        err = next(p for p in payloads if isinstance(p, BaseException))
        if isinstance(err, ReadSkipped):
            return Observation(None, None, src, note=str(err)[:200])
        return Observation(None, None, src, note=f"read failed: {str(err)[:120]}")
    if kind == "price":
        if not reads:
            return Observation(None, None, src, note="live quotes are read in session only")
        return _quote_obs(payloads[0], src)
    if kind in IV_FIELDS:
        return _series_obs(_rows(payloads[0]), "date", IV_FIELDS[kind], src)
    if kind in ("straddle", "oi_strike", "oi_wall"):
        return _chain_obs(kind, params, payloads[0], src)
    if kind == "basis":
        return _series_obs(_rows(payloads[0]), "date", "basis_ann_pct", src)
    if kind == "rollover":
        p = payloads[0] if isinstance(payloads[0], dict) else {}
        cur = p.get("current") if isinstance(p.get("current"), dict) else None
        if not cur:
            return Observation(None, None, src, note="no rollover cycle stored" + (" (panel updating)" if p.get("updating") else ""))
        v = _num(cur.get("roll_pct"))
        extra = {"near_expiry": cur.get("near_expiry"), "dte": cur.get("dte"), "avg3": p.get("avg3")}
        return Observation(v, _day(cur.get("date")), src, note=None if v is not None else "no rollover % stored", extra=extra)
    if kind == "rollover_pace":
        return _rollover_pace_obs(payloads[0], src)
    if kind == "fo_ban":
        p = payloads[0] if isinstance(payloads[0], dict) else {}
        ban = p.get("ban")
        if not isinstance(ban, list):
            return Observation(None, None, src, note="the ban list is not stored")
        as_of = _day((p.get("dates") or {}).get("ban")) if isinstance(p.get("dates"), dict) else None
        names = {str(s).upper() for s in ban}
        return Observation(1.0 if params["symbol"] in names else 0.0, as_of, src)
    if kind == "results_days":
        rows = [r for r in _rows(payloads[0]) if str(r.get("symbol") or "").upper() == params["symbol"]
                and str(r.get("kind") or "").upper() == "RESULTS" and (_day(r.get("event_date")) or "") >= today.isoformat()]
        if not rows:
            return Observation(None, today.isoformat(), src, note="no results date on NSE's calendar in the next 60 days")
        nxt = min(_day(r.get("event_date")) or "" for r in rows)
        days = (date.fromisoformat(nxt) - today).days
        # dated by the stored calendar row (when NSE's row was first stored, else its announcement), never by today:
        # today only gives the day count (review 6 Nov, 'every number dated')
        row = min((r for r in rows if _day(r.get("event_date")) == nxt), key=lambda r: str(r.get("first_seen") or "~"))
        seen = _day(row.get("first_seen")) or _day(row.get("announced_at"))
        return Observation(float(days), seen, src + (": the calendar row as first stored that day" if seen else ""),
                           extra={"event_date": nxt, "first_seen": seen})
    if kind in ("fii_net", "dii_net"):
        cat = "FII" if kind == "fii_net" else "DII"
        rows = [r for r in _rows(payloads[0]) if str(r.get("category") or "").upper().startswith(cat)]
        return _series_obs(rows, "date", "net_cr", src)
    if kind == "vix":
        return _vix_obs(reads, payloads, src, today)
    if kind == "nifty_driver":
        p = payloads[0] if isinstance(payloads[0], dict) else {}
        d = (p.get("driver") or {}).get(DRIVER_WINDOW) if isinstance(p.get("driver"), dict) else None
        if not d or not d.get("leader"):
            store_name = str(p.get("index") or DRIVER_STORE_NAMES.get(params["index"], params["index"]))   # the key the store was asked
            if p.get("as_of"):                      # attribution stored, but no 20-session driver state yet (a short history)
                return Observation(None, _day(p.get("as_of")), src, note=f"no {DRIVER_WINDOW}-session driver state stored for {store_name} "
                                   f"yet (attribution since {_day(p.get('history_since')) or 'unknown'})")
            return Observation(None, None, src, note=f"{store_name}: {p.get('note') or 'no stored attribution yet'}")
        return Observation(str(d["leader"]), _day(p.get("as_of")), src,
                           extra={"changed_from": d.get("changed_from"), "change_date": _day(d.get("change_date")), "tenure": d.get("tenure")})
    if kind == "gold_health":
        rows = sorted((r for r in _rows(payloads[0]) if _day(r.get("day"))), key=lambda r: _day(r.get("day")) or "")
        if not rows or not rows[-1].get("verdict"):
            return Observation(None, _day(rows[-1].get("day")) if rows else None, src, note="no stored gold health snapshot")
        verdict = str(rows[-1]["verdict"])
        return Observation(gold_clause_key(verdict), _day(rows[-1].get("day")), src, extra={"verdict": verdict})
    if kind == "data_stale":
        return _data_obs(params, payloads[0], src)
    return Observation(None, None, src, note=f"no extractor for {kind}")  # pragma: no cover


def _quote_obs(q: Any, src: str) -> Observation:
    if not isinstance(q, dict) or not q.get("available") or _num(q.get("price")) is None:
        state = q.get("state") if isinstance(q, dict) else None
        return Observation(None, None, src, note=f"no fresh live quote{f' ({state})' if state else ''}")
    tag = " · ".join(str(x) for x in (q.get("source"), q.get("state")) if x)
    as_of = q.get("ltt") or q.get("as_of") or q.get("market_date") or q.get("eod_as_of")   # the tick time, else the session
    return Observation(float(q["price"]), str(as_of) if as_of else None, f"live NSE quote ({tag})" if tag else src,
                       change_pct=_num(q.get("change_pct")))


def _chain_obs(kind: str, params: dict[str, Any], p: Any, src: str) -> Observation:
    if not isinstance(p, dict) or not p.get("found", True) or not isinstance(p.get("rows"), list):
        return Observation(None, None, src, note="no stored option chain")
    as_of, expiry = _day(p.get("date")), _day(p.get("expiry"))
    rows = [r for r in p["rows"] if isinstance(r, dict) and _num(r.get("strike")) is not None]
    if not rows:
        return Observation(None, as_of, src, note="the stored chain has no strikes")
    extra: dict[str, Any] = {"expiry": expiry}
    src_x = f"{src}, expiry {expiry}" if expiry else src
    if kind == "straddle":
        atm = _num(p.get("atm"))
        ref = atm if atm is not None else (_num(p.get("forward")) or _num(p.get("spot")))
        if ref is None:
            return Observation(None, as_of, src_x, note="no ATM strike in the chain")
        row = min(rows, key=lambda r: abs(float(r["strike"]) - ref))
        ce, pe = _num((row.get("ce") or {}).get("price")), _num((row.get("pe") or {}).get("price"))
        if ce is None or pe is None:
            return Observation(None, as_of, src_x, note=f"no call or put close at {fmt_plain(float(row['strike']))}")
        extra["strike"] = float(row["strike"])
        return Observation(round(ce + pe, 2), as_of, f"{src_x}, strike {fmt_plain(float(row['strike']))}", extra=extra)
    side = params["side"].lower()
    if kind == "oi_strike":
        hit: dict[str, Any] | None = next((r for r in rows if abs(float(r["strike"]) - params["strike"]) < 1e-6), None)
        if hit is None:
            return Observation(None, as_of, src_x, note=f"strike {fmt_plain(params['strike'])} is not in the stored chain")
        oi, chg = _oi_contracts(hit.get(side) or {}, _num(p.get("lot")))
        if oi is None:
            return Observation(None, as_of, src_x, note="no OI in contracts at that strike (no OI stored, or no lot size to convert NSE's shares)")
        base = oi - chg if chg is not None else None
        ch = round((oi / base - 1.0) * 100.0, 4) if base else None
        return Observation(oi, as_of, src_x, change_pct=ch, extra=extra)
    best = max(rows, key=lambda r: _num((r.get(side) or {}).get("oi")) or -1.0)
    if (_num((best.get(side) or {}).get("oi")) or 0) <= 0:
        return Observation(None, as_of, src_x, note="no open interest in the chain")
    return Observation(float(best["strike"]), as_of, src_x, extra=extra)


def _oi_contracts(leg: dict[str, Any], lot: float | None) -> tuple[float | None, float | None]:
    """(OI, OI change) in contracts: the chain's own ``oi_contracts`` (data-service after review M05), else NSE's shares
    ÷ the payload's lot (a data-service from before M05); (None, None) when neither is there — never shares labelled
    as contracts."""
    oi_c, chg_c = _num(leg.get("oi_contracts")), _num(leg.get("oi_chg_contracts"))
    if oi_c is not None:
        return oi_c, chg_c
    oi, chg = _num(leg.get("oi")), _num(leg.get("oi_chg"))
    if oi is None or not lot or lot <= 0:
        return None, None
    return round(oi / lot, 1), (round(chg / lot, 1) if chg is not None else None)


def _rollover_pace_obs(p: Any, src: str) -> Observation:
    """This cycle's rollover % minus the previous cycles' average at the same days to expiry (``curve_avg``, built by
    data-service from the cycles asked for: 3), in percentage points."""
    p = p if isinstance(p, dict) else {}
    cur = p.get("current") if isinstance(p.get("current"), dict) else None
    if not cur or _num(cur.get("roll_pct")) is None:
        return Observation(None, None, src, note="no rollover cycle stored" + (" (panel updating)" if p.get("updating") else ""))
    dte = cur.get("dte")
    avg = next((_num(r.get("roll_pct")) for r in (p.get("curve_avg") or []) if isinstance(r, dict) and r.get("dte") == dte), None)
    as_of = _day(cur.get("date"))
    if avg is None:
        return Observation(None, as_of, src, note=f"no earlier cycle stored at {dte} days to expiry")
    roll = float(cur["roll_pct"])
    return Observation(round(roll - avg, 2), as_of, f"{src}, {dte} days to expiry: {roll:.1f} % vs {avg:.1f} %",
                       extra={"dte": dte, "roll_pct": roll, "avg_same_dte": avg, "near_expiry": cur.get("near_expiry")})


def _vix_obs(reads: list[Need], payloads: list[Any], src: str, today: date) -> Observation:
    daily = payloads[-1]
    rows = [] if isinstance(daily, BaseException) else _rows(daily)
    if reads[0].source == "quote" and not isinstance(payloads[0], BaseException):
        live = _quote_obs(payloads[0], src)
        if live.value is not None:
            hist = tuple(x for x in (_num(r.get("close")) for r in sorted(rows, key=lambda r: str(r.get("date")))
                                     if (_day(r.get("date")) or "") < today.isoformat()) if x is not None)
            live.history = hist
            return live
    obs = _series_obs(rows, "date", "close", "vix_daily (NSE daily file)")
    last = max(rows, key=lambda r: str(r.get("date")), default=None)
    if obs.value is not None and last is not None:
        pc = _num(last.get("prev_close"))
        if pc:
            obs.change_pct = round((float(obs.value) / pc - 1.0) * 100.0, 4)
    return obs


def _data_obs(params: dict[str, Any], p: Any, src: str) -> Observation:
    rows = _rows(p)
    if not rows:
        return Observation(None, None, src, note="SYS › DATA did not answer")
    as_of = str(p.get("as_of") or "")[:16] if isinstance(p, dict) else None
    bad = [r for r in rows if str(r.get("state")) in ("amber", "red")]
    if params["dataset"] == "any":
        return Observation(float(len(bad)), as_of, src, extra={"datasets": [str(r.get("id")) for r in bad][:12]})
    row = next((r for r in rows if str(r.get("id")) == params["dataset"]), None)
    if row is None:
        return Observation(None, as_of, src, note=f"dataset {params['dataset']} is not in the catalog")
    return Observation(1.0 if str(row.get("state")) in ("amber", "red") else 0.0, as_of, src, extra={"state": row.get("state")})


_NUMBER = re.compile(r"[+\-−]?\d[\d,]*(\.\d+)?")


def gold_clause_key(verdict: str) -> str:
    """'India basis +1.4 % vs duty-paid landed · GLD +2.1 t on the day · describes, does not predict' →
    'GLD # t on the day | India basis # % vs duty-paid landed': the clauses without their figures, sorted."""
    parts = [p.strip() for p in str(verdict).split(" · ") if p.strip() and p.strip() != DESCRIBES]
    return " | ".join(sorted({_NUMBER.sub("#", p) for p in parts}))


# ── Telegram / GO text → a rule ──────────────────────────────────────────────────────────────────────────────
def parse_rule_text(text: str) -> dict[str, Any]:
    """'iv_pctile:NIFTY above 80 repeat cooldown=60 telegram note=after results' → a rule body (validate_rule runs on it).

    Tokens after ``<series> <op> [value]``: once | repeat · mac | telegram | both · window=N · cooldown=N ·
    note=<rest of the line>. ``changed`` takes no value."""
    t = str(text or "").strip()
    note = None
    m = re.search(r"\bnote=(.*)$", t)
    if m:
        note, t = m.group(1).strip(), t[: m.start()].strip()
    toks = t.split()
    if len(toks) < 2:
        raise RuleError("usage: <series> <op> <value> [once|repeat] [mac|telegram|both] [window=N] [cooldown=N] [note=…]")
    body: dict[str, Any] = {"series": toks[0], "op": toks[1].lower(), "note": note}
    rest = toks[2:]
    if body["op"] != "changed":
        if not rest:
            raise RuleError(f"{body['op']} needs a value")
        body["value"] = rest[0].rstrip("%")
        rest = rest[1:]
    for tok in rest:
        low = tok.lower()
        if low in REPEATS:
            body["repeat"] = low
        elif low in CHANNELS:
            body["channel"] = low
        elif low.startswith("window="):
            body["window"] = low.split("=", 1)[1]
        elif low.startswith("cooldown="):
            body["cooldown_min"] = low.split("=", 1)[1]
        else:
            raise RuleError(f"unknown option {tok!r}")
    return body


# ── the inbox ─────────────────────────────────────────────────────────────────────────────────────────────────
def group_fires(fires: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fires (newest first) → [{symbol, count, last_at, fires: [...]}], the group with the newest fire first."""
    groups: dict[str, dict[str, Any]] = {}
    for f in fires:
        sym = str(f.get("symbol") or "—")
        g = groups.setdefault(sym, {"symbol": sym, "count": 0, "last_at": f.get("at"), "fires": []})
        g["count"] += 1
        g["fires"].append(f)
        if str(f.get("at") or "") > str(g["last_at"] or ""):
            g["last_at"] = f.get("at")
    return sorted(groups.values(), key=lambda g: str(g["last_at"] or ""), reverse=True)


KIND_NAMES: dict[str, str] = {
    "price": "price (stock or index)", "iv30": "IV30", "iv_pctile": "IV percentile", "iv_rank": "IV rank",
    "iv_rv": "IV − RV20 (close-to-close)", "skew25": "25Δ skew", "straddle": "ATM straddle", "oi_strike": "OI at a strike (contracts)",
    "oi_wall": "OI wall (most-OI strike)", "basis": "futures basis", "rollover": "futures rollover",
    "rollover_pace": "rollover vs 3-cycle average (same DTE)", "fo_ban": "F&O ban entry / exit", "results_days": "days to results",
    "fii_net": "FII cash net", "dii_net": "DII cash net", "vix": "India VIX", "nifty_driver": "index driver (20 sessions)",
    "gold_health": "gold health clauses", "data_stale": "a dataset going stale",
}


def catalog() -> list[dict[str, Any]]:
    """The series kinds for the builder, other pages and GET /api/alerts/series."""
    return [{"kind": k.kind, "name": KIND_NAMES.get(k.kind, k.kind), "label": k.label, "unit": k.unit, "badge": k.badge, "cadence": k.cadence, "params": list(k.params),
             "optional": list(k.optional), "ops": list(k.ops), "source": k.source, "group": k.group, "definition": k.definition,
             "example": k.example, "history": k.history, "category": k.category} for k in KINDS.values()]


def template_samples() -> list[str]:
    """Every fire / condition / summary template rendered once per op and kind (the direction-word scan's input)."""
    out: list[str] = []
    for k in KINDS.values():
        params: dict[str, Any] = {"symbol": "NIFTY", "strike": 24500.0, "side": "CE", "index": "NIFTY", "dataset": "any"}
        params = {p: params[p] for p in k.params}
        for op in k.ops:
            rule = {"id": "r-sample", "series": series_id(k.kind, params), "kind": k.kind, "params": params, "symbol": rule_symbol(k.kind, params),
                    "op": op, "value": None if op == "changed" else 1.0, "window": 1 if op == "change_pct" else (PCTILE_WINDOW if op.startswith("pctile") else None),
                    "cooldown_min": 0, "repeat": "repeat", "channel": "both", "note": None}
            for v, prev in ((1.0, 0.0), (0.0, 1.0)):
                val: Any = ("ICICIBANK" if v else "HDFCBANK") if k.category else v
                obs = Observation(val, "2026-11-05", k.source, tuple(float(i) for i in range(30)), change_pct=2.0, extra={"event_date": "2026-11-09"})
                out.append(fire_text(rule, obs, 2.0, ("HDFCBANK" if v else "ICICIBANK") if k.category else prev))
            out.append(rule_summary(rule))
        out += [k.label, k.definition, k.source, KIND_NAMES.get(k.kind, "")]
    out += list(OP_WORDS.values())
    return out
