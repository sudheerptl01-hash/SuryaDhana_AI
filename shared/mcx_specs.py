"""
MCX gold desk reference data: session clock, 2026 holiday calendar, contract specs,
expiry computation and indicative trading costs. Pure stdlib — importable from ui-api,
scripts and tests alike; no network, no FastAPI, no pandas.

Session (MCX commodity derivatives, Mon–Fri, IST):
  * continuous 09:00 → evening close; the 17:00 boundary only matters on partial holidays
  * evening close is US-linked: 23:30 IST while New York is on daylight saving time,
    23:55 otherwise (same rule as routers/gold_preopen.mcx_close_time; a test pins the two)

Holiday calendar 2026 — three closure kinds (MCX holidays ≠ NSE holidays):
  * full     — both sessions closed
  * morning  — morning closed, evening session open (17:00 → close)
  * evening  — morning open (09:00–17:00), evening closed
  Sources (fetched 15 Oct 2026; mcxindia.com itself answers 403 to non-browser clients):
    - ICICI Direct iLearn "MCX holiday list" (icicidirect.com/ilearn/commodity/articles/mcx-holiday-list)
    - Kotak Neo MCX holidays 2026 (kotakneo.com/share-market-holidays/mcx-holidays)
    - 5paisa MCX holidays (5paisa.com/stock-market-holidays/mcx-holidays)
  The three agree on every row except 1 Jan 2026, where ICICI Direct + 5paisa say
  "morning open, evening closed" and Kotak says full close; the broker this desk uses
  (ICICI) wins. Muhurat trading: Sunday 8 Nov 2026, 14:20–15:30 IST by MCX circular MCX/TRD/590/2026 — a dated
  special SESSION (SPECIAL_SESSIONS_2026): trading_window and every session rule built on it count it.

Contract specs (GOLD / GOLDM / GOLDPETAL / GOLDGUINEA) and expiry rules:
  * lot, quotation, tick: Rupeezy specs sheet + OneTradeJournal MCX basics (both list
    GOLD 1 kg / ₹1 tick = ₹100, GOLDM 100 g = ₹10, GOLDGUINEA 8 g = ₹1, GOLDPETAL 1 g = ₹1)
  * GOLDPETAL delivery: 1 g trading unit, physical delivery in multiples of 8 g coins,
    999 purity (Business Standard, 22 Oct 2019: "MCX the first bourse to offer one gram
    gold futures with delivery option")
  * GOLD runs the Feb/Apr/Jun/Aug/Oct/Dec cycle with expiry on the 5th of the contract
    month; GOLDM is monthly, also the 5th; GOLDPETAL and GOLDGUINEA are monthly with
    expiry on the last calendar day. When that day is not a business day the expiry moves
    to the PREVIOUS business day, and observed MCX behaviour treats morning-closed
    holidays as non-business for expiry too (Zerodha/Fyers bulletins: petal/guinea expired
    30 Mar 2026 because 31 Mar was Mahavir Jayanti, a morning closure; GOLD Dec-26 expires
    Fri 4 Dec because the 5th is a Saturday — both reproduced by `active_expiries`).
    SIMPLIFICATION: the exchange's contract-launch circular is the legal source; this
    module computes the rule, and the ui-api router cross-checks against ICICI's daily
    security master when it is available.

Costs (all rates in PERCENT of turnover unless noted; label everything "indicative"):
  * MCX exchange transaction fee, futures: ₹2.10 per lakh = 0.0021% (post-SEBI
    "true to label" unified slab, Oct 2024 — Rupeezy charges sheet, Bajaj Broking note)
  * CTT: 0.01% on the SELL side of non-agri commodity futures (squared off, non-delivery)
  * SEBI turnover fee: ₹10 per crore = 0.0001%, both sides
  * Stamp duty: 0.002% on the BUY side (₹200/crore)
  * GST: 18% on brokerage + exchange transaction fee + SEBI fee
  * Brokerage default ₹20 per order (flat commodity plans; ICICI plan-dependent)
  * SPAN+exposure margin moves daily with volatility; bullion has typically been
    ≈6–12% (OneTradeJournal: "about 5% on calmer commodities to 12%+ on volatile ones").
    The numbers here are INDICATIVE for sizing a paper ticket, never for a real order.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
NY = ZoneInfo("America/New_York")
GRAMS_PER_TROY_OZ = 31.1034768

MORNING_OPEN = time(9, 0)
SESSION_SPLIT = time(17, 0)          # morning/evening boundary — matters on partial holidays

Closure = Literal["full", "morning", "evening"]

# date → (holiday name, closure kind). Weekday holidays only; weekend-falling ones
# (Mahashivratri Sun 15 Feb, Id-Ul-Fitr Sat 21 Mar, Independence Day Sat 15 Aug,
# Diwali Laxmi Pujan Sun 8 Nov) change nothing the weekend rule doesn't already close.
MCX_HOLIDAYS_2026: dict[date, tuple[str, Closure]] = {
    date(2026, 1, 1): ("New Year Day", "evening"),
    date(2026, 1, 26): ("Republic Day", "full"),
    date(2026, 3, 3): ("Holi (2nd day)", "morning"),
    date(2026, 3, 26): ("Shri Ram Navami", "morning"),
    date(2026, 3, 31): ("Shri Mahavir Jayanti", "morning"),
    date(2026, 4, 3): ("Good Friday", "full"),
    date(2026, 4, 14): ("Dr. Baba Saheb Ambedkar Jayanti", "morning"),
    date(2026, 5, 1): ("Maharashtra Day", "morning"),
    date(2026, 5, 28): ("Bakri Id", "morning"),
    date(2026, 6, 26): ("Moharram", "morning"),
    date(2026, 9, 14): ("Ganesh Chaturthi", "morning"),
    date(2026, 10, 2): ("Mahatma Gandhi Jayanti", "full"),
    date(2026, 10, 20): ("Dussehra", "morning"),
    date(2026, 11, 10): ("Diwali-Balipratipada", "morning"),
    date(2026, 11, 24): ("Guru Nanak Jayanti", "morning"),
    date(2026, 12, 25): ("Christmas", "full"),
}
CALENDAR_YEARS = (2026,)             # outside these years only the weekend rule applies
# Dated special sessions (a TRADING session on a day the weekend rule or the holiday table would close): MCX trades the
# `opens`–`closes` window only; it is a session for every session rule — trading_window, the settlement chain
# (gold_preopen.previous_session / band_session / latest_completed_session, data-service previous_mcx_session /
# mcx_close.latest_completed_session) and the VWAP30 window (its last 30 minutes, 15:00–15:30 for Muhurat 2026).
# Muhurat 2026: MCX circular MCX/TRD/590/2026 (19 Oct 2026), "special session 14:05–14:19, trading 14:20–15:30" as
# republished by TeamLease RegTech (docs/GOLD_DATA_DICTIONARY.md F6; the 06 Nov automated brief cites the same circular and
# times). mcxindia.com itself is never fetched (PLAN 0.1 #6). 6 Nov 2026: circular number, date and both windows confirmed in
# a second, independent republication (Algotest: 'MCX/TRD/590/2026 dated October 19, 2026', 14:20–15:30).
# Keep the literal `"date": "YYYY-MM-DD"` keys: ui/components/desktop/__tests__/desktop.check.ts reads them for its drift check.
SPECIAL_SESSIONS_2026 = [
    {"date": "2026-11-08", "name": "Muhurat trading (Diwali Laxmi Pujan)",
     "opens": "14:20", "closes": "15:30", "pre_open": "14:05–14:19", "circular": "MCX/TRD/590/2026",
     "note": ("Sunday special session 14:05–14:19 (special), 14:20–15:30 trading "
              "(MCX circular MCX/TRD/590/2026 of 19 Oct 2026; windows confirmed 6 Nov in two republications: TeamLease RegTech, Algotest)")},
]


def _hhmm(text: str) -> time:
    hh, mm = str(text).split(":")
    return time(int(hh), int(mm))


SPECIAL_SESSION_WINDOWS: dict[date, tuple[time, time]] = {
    date.fromisoformat(s["date"]): (_hhmm(s["opens"]), _hhmm(s["closes"])) for s in SPECIAL_SESSIONS_2026
}
# Customs duty on gold, dated (SOURCES.md F9; PLAN §d): the ladder prints the rate and its notification on every render.
DUTY_HISTORY: tuple[tuple[str, float], ...] = (("2024-07-24", 6.0), ("2026-05-13", 15.0))
DUTY_NOTIFICATION = "Notification 16/2026-Customs (BCD 10 % + AIDC 5 %)"
MARGIN_SOURCE = "zerodha_nrml"      # the NRML mirror the selector carries (dated); the constants above stay indicative
SESSION_NOTE = ("MCX evening close is US-linked: 23:30 IST while New York is on daylight "
                "saving time, 23:55 IST otherwise. Continuous trading from 09:00; the 17:00 "
                "split only matters on partial holidays.")


def holiday_on(day: date) -> tuple[str, Closure] | None:
    """The MCX holiday on `day`, or None. Weekends are handled separately."""
    return MCX_HOLIDAYS_2026.get(day)


def evening_close(day: date) -> time:
    """23:30 IST while New York is on daylight time, else 23:55 (matches gold_preopen)."""
    noon_ny = datetime(day.year, day.month, day.day, 12, tzinfo=NY)
    return time(23, 30) if noon_ny.dst() else time(23, 55)


def special_session_on(day: date) -> dict[str, Any] | None:
    """The dated special session on `day` (SPECIAL_SESSIONS_2026 row), or None."""
    return next((dict(s) for s in SPECIAL_SESSIONS_2026 if s["date"] == day.isoformat()), None)


def is_session_day(day: date) -> bool:
    """True when MCX trades on `day` at all: a weekday that is not a full closure, or a dated special session."""
    return trading_window(day) is not None


def trading_window(day: date) -> tuple[datetime, datetime] | None:
    """The continuous trading stretch on `day` in IST, or None when MCX is shut. A dated special session (Muhurat, Sun
    8 Nov 2026: 14:20–15:30) is a trading window like any other, whatever the weekday."""
    special = SPECIAL_SESSION_WINDOWS.get(day)
    if special is not None:
        return datetime.combine(day, special[0], tzinfo=IST), datetime.combine(day, special[1], tzinfo=IST)
    if day.weekday() >= 5:
        return None
    hol = holiday_on(day)
    close = datetime.combine(day, evening_close(day), tzinfo=IST)
    if hol is None:
        return datetime.combine(day, MORNING_OPEN, tzinfo=IST), close
    _, closure = hol
    if closure == "full":
        return None
    if closure == "morning":                       # evening session only
        return datetime.combine(day, SESSION_SPLIT, tzinfo=IST), close
    # evening closure: morning session only
    return (datetime.combine(day, MORNING_OPEN, tzinfo=IST),
            datetime.combine(day, SESSION_SPLIT, tzinfo=IST))


def _next_window(after: datetime) -> tuple[datetime, datetime]:
    """The first trading stretch that ends after `after` (looking up to 14 days out)."""
    day = after.date()
    for _ in range(15):
        win = trading_window(day)
        if win and win[1] > after:
            return win
        day += timedelta(days=1)
    raise RuntimeError("no MCX trading window found within 14 days")  # pragma: no cover


def session_state(now: datetime) -> dict[str, Any]:
    """OPEN/CLOSED + countdowns for the desk header. `now` must be timezone-aware."""
    now = now.astimezone(IST)
    today = now.date()
    hol = holiday_on(today)
    start, end = _next_window(now)
    is_open = start <= now < end
    seg = None
    if is_open:
        seg = "morning" if now.time() < SESSION_SPLIT else "evening"
    out: dict[str, Any] = {
        "as_of": now.isoformat(timespec="seconds"),
        "is_open": is_open,
        "segment": seg,
        "weekend": today.weekday() >= 5,
        "holiday": {"name": hol[0], "closure": hol[1]} if hol else None,
        # a dated special session today (Muhurat): its window is `opens_at`/`closes_at` while it is still ahead or open
        "special": special_session_on(today),
        "opens_at": start.isoformat(timespec="seconds"),
        "closes_at": end.isoformat(timespec="seconds"),
        "seconds_to_close": int((end - now).total_seconds()) if is_open else None,
        "seconds_to_open": None if is_open else int((start - now).total_seconds()),
        "note": SESSION_NOTE,
    }
    if today.year not in CALENDAR_YEARS:
        out["calendar_warning"] = (f"MCX holiday table covers {CALENDAR_YEARS} only — refresh it from "
                                   "mcxindia.com circulars; weekends are still honoured.")
    return out


def upcoming_holidays(today: date, count: int = 6) -> list[dict[str, str]]:
    rows = [{"date": d.isoformat(), "day": d.strftime("%a"), "name": name, "closure": closure}
            for d, (name, closure) in sorted(MCX_HOLIDAYS_2026.items()) if d >= today]
    return rows[:count]


# ── contract specs ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ContractSpec:
    code: str
    name: str
    lot_grams: int                     # trading unit per lot
    quote_per_grams: int               # price is ₹ per this many grams
    tick_rupees: float
    delivery_unit: str
    purity: str
    expiry_kind: Literal["day5", "month_end"]
    months: tuple[int, ...]            # contract-launch months (1–12)
    span_margin_pct_indicative: float  # INDICATIVE — exchange revises daily
    notes: str = ""

    @property
    def multiplier(self) -> float:
        """Quotation units per lot: ₹1 of price move = this many ₹ of P&L per lot."""
        return self.lot_grams / self.quote_per_grams

    @property
    def tick_value(self) -> float:
        return self.tick_rupees * self.multiplier

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code, "name": self.name,
            "lot": f"{self.lot_grams / 1000:g} kg" if self.lot_grams >= 1000 else f"{self.lot_grams} g",
            "lot_grams": self.lot_grams,
            "quotation": f"₹ per {self.quote_per_grams} g",
            "tick_rupees": self.tick_rupees,
            "tick_value": round(self.tick_value, 2),
            "multiplier": self.multiplier,
            "delivery_unit": self.delivery_unit,
            "purity": self.purity,
            "expiry_rule": ("5th of the contract month" if self.expiry_kind == "day5"
                            else "last calendar day of the contract month") + " (previous business day if closed)",
            "cycle": "Feb/Apr/Jun/Aug/Oct/Dec" if self.months == (2, 4, 6, 8, 10, 12) else "monthly",
            "span_margin_pct_indicative": self.span_margin_pct_indicative,
            "notes": self.notes,
        }


ALL_MONTHS = tuple(range(1, 13))
CONTRACTS: dict[str, ContractSpec] = {
    "GOLD": ContractSpec("GOLD", "Gold (1 kg)", 1000, 10, 1.0, "1 kg", "995",
                         "day5", (2, 4, 6, 8, 10, 12), 6.0,
                         "The benchmark contract; ₹1 move = ₹100 per lot."),
    "GOLDM": ContractSpec("GOLDM", "Gold Mini (100 g)", 100, 10, 1.0, "100 g", "995",
                          "day5", ALL_MONTHS, 6.0,
                          "Monthly expiries on the 5th; one-tenth of GOLD."),
    "GOLDPETAL": ContractSpec("GOLDPETAL", "Gold Petal (1 g)", 1, 1, 1.0,
                              "8 g (coins; trading unit 1 g)", "999",
                              "month_end", ALL_MONTHS, 6.0,
                              "Delivery in multiples of 8 g coins (999)."),
    "GOLDGUINEA": ContractSpec("GOLDGUINEA", "Gold Guinea (8 g)", 8, 8, 1.0, "8 g", "999",
                               "month_end", ALL_MONTHS, 6.0,
                               "Quoted per 8 g; ₹1 move = ₹1 per lot."),
    # GOLD program (SOURCES.md F1, G-INDIA §4): 10 g lot quoted per 10 g like GOLD, 999 purity, monthly, month-end expiry,
    # tick ₹1 = ₹1 per lot; Breeze code GOLDTE (ICICI master ShortName); Oct-26 OI 25,655 on 23 Oct 2026.
    "GOLDTEN": ContractSpec("GOLDTEN", "Gold Ten (10 g)", 10, 10, 1.0, "10 g", "999",
                            "month_end", ALL_MONTHS, 6.0,
                            "Quoted per 10 g like GOLD, one-hundredth of its lot; 999 purity, month-end expiry."),
}


def _expiry_business_day(d: date) -> bool:
    """Business day for EXPIRY purposes: weekdays that are neither full nor morning-closed
    holidays (observed: petal/guinea expired 30 Mar 2026 because 31 Mar was a morning
    closure; evening-only closures like 1 Jan keep the morning open, so expiry stands)."""
    if d.weekday() >= 5:
        return False
    hol = holiday_on(d)
    return hol is None or hol[1] == "evening"


def _back_to_business(d: date) -> date:
    for _ in range(10):
        if _expiry_business_day(d):
            return d
        d -= timedelta(days=1)
    return d  # pragma: no cover — ten straight closed days do not happen


def active_expiries(code: str, today: date, count: int = 3) -> list[date]:
    """The next `count` expiry dates for `code` on/after `today` (computed; the router
    cross-checks against ICICI's security master when available)."""
    spec = CONTRACTS[code]
    out: list[date] = []
    y, m = today.year, today.month
    for _ in range(30):
        if m in spec.months:
            raw = (date(y, m, 5) if spec.expiry_kind == "day5"
                   else date(y, m, calendar.monthrange(y, m)[1]))
            exp = _back_to_business(raw)
            if exp >= today:
                out.append(exp)
                if len(out) >= count:
                    return out
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


# ── indicative costs (rates cited in the module docstring) ──────────────────────

RATES_PCT: dict[str, float] = {
    "exchange_txn": 0.0021,   # MCX futures transaction fee, ₹2.10/lakh (Oct 2024 slab)
    "ctt_sell": 0.01,         # CTT, sell side, non-agri futures (squared off / non-delivery)
    "sebi": 0.0001,           # SEBI turnover fee, ₹10/crore, both sides
    "stamp_buy": 0.002,       # stamp duty, buy side
    "gst": 18.0,              # on brokerage + exchange txn + SEBI fee
}
DEFAULT_BROKERAGE_PER_ORDER = 20.0


def notional(code: str, price: float, lots: int = 1) -> float:
    return price * CONTRACTS[code].multiplier * lots


def indicative_margin(code: str, price: float, lots: int = 1) -> float:
    spec = CONTRACTS[code]
    return notional(code, price, lots) * spec.span_margin_pct_indicative / 100.0


def _side_costs(turnover: float, side: Literal["buy", "sell"], brokerage: float) -> dict[str, float]:
    txn = turnover * RATES_PCT["exchange_txn"] / 100
    sebi = turnover * RATES_PCT["sebi"] / 100
    stamp = turnover * RATES_PCT["stamp_buy"] / 100 if side == "buy" else 0.0
    ctt = turnover * RATES_PCT["ctt_sell"] / 100 if side == "sell" else 0.0
    gst = (brokerage + txn + sebi) * RATES_PCT["gst"] / 100
    total = brokerage + txn + sebi + stamp + ctt + gst
    return {"brokerage": round(brokerage, 2), "exchange_txn": round(txn, 2), "sebi": round(sebi, 2),
            "stamp": round(stamp, 2), "ctt": round(ctt, 2), "gst": round(gst, 2), "total": round(total, 2)}


def round_trip_costs(code: str, price: float, lots: int = 1,
                     brokerage_per_order: float = DEFAULT_BROKERAGE_PER_ORDER) -> dict[str, Any]:
    """Indicative round-trip cost of a squared-off (non-delivery) futures trade, both legs
    priced at `price`. Delivery brings extra costs (delivery charges, different CTT
    treatment) that are OUT of scope here."""
    spec = CONTRACTS[code]
    turnover = notional(code, price, lots)
    buy = _side_costs(turnover, "buy", brokerage_per_order)
    sell = _side_costs(turnover, "sell", brokerage_per_order)
    total = round(buy["total"] + sell["total"], 2)
    return {
        "contract": code, "price": price, "lots": lots,
        "turnover_per_side": round(turnover, 2),
        "buy": buy, "sell": sell, "total": total,
        "pct_of_notional": round(total / turnover * 100, 4) if turnover else None,
        "breakeven_ticks": round(total / (spec.tick_value * lots), 2) if lots else None,
        "breakeven_price_move": round(total / (spec.multiplier * lots), 2) if lots else None,
        "rates_pct": RATES_PCT,
        "indicative": True,
        "assumptions": ("both legs at the same price; squared off before expiry (CTT 0.01% sell side); "
                        f"brokerage ₹{brokerage_per_order:g}/order flat; GST on brokerage + txn + SEBI fee"),
    }
