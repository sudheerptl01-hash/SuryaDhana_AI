//! Health poller and the `ShellStatus` contract type.
//!
//! Cadence (tokio tasks, all read-only GETs against the local stack):
//! * every 5 s (1 s while a window is waiting on the boot page): `GET /health` on ui-api, data-service
//!   and master-controller (5 s timeout like the watchdog's tolerance, latency measured) + `GET /` on ui_url
//!   (must be 200 text/html; on 503 `GET /ready` tells "no UI release" apart from other failures) + the
//!   port-squatting guard (who listens on the ui port, from kernel facts, under a hard 5 s timeout; run on
//!   EVERY fast poll that finds the port held, round 3: no cached pass, see trust.rs). Only a definitive
//!   verdict (Foreign, or Unverifiable: a live listener whose executable is gone and that was never verified)
//!   keeps windows off the terminal origin; an inconclusive one (probe failed / timed out / listener vanished)
//!   never does;
//! * every 15 s: NIFTY from `/api/market/nifty-live` (the endpoint the UI header uses; its `time` field
//!   and two failed fetches in a row mark the quote stale) and the served UI build from `/build-info.json`;
//! * every 60 s: ICICI session from `/api/positions/connection-status`. Only `connected` and
//!   `needs_session_refresh` are deserialized; the body (which holds a `login_url` carrying the API key)
//!   is never logged, stored or forwarded;
//! * every 5 min: Decision Desk NAV from `/api/desk/status` (latest NAV, return since the first NAV).
//!
//! After every update the hub calls `crate::on_health_update`, which drives the navigator, tray,
//! `suryadhana:shell` status broadcasts and native notifications.

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex, RwLock};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use serde_json::Value;
use time::format_description::well_known::Rfc3339;
use time::{OffsetDateTime, PrimitiveDateTime, Weekday};
use tokio::sync::Notify;
use url::Url;

use crate::config::Config;
use crate::policy::{ist_offset, TrustFail};

/// `/health` timeout. The watchdog tolerates 8 s; 2 s produced "down" banners for ui-api event-loop
/// stalls the watchdog never acts on (C2-reliability-ops-08).
pub const HEALTH_TIMEOUT: Duration = Duration::from_secs(5);
/// A NIFTY quote whose time is older than this during NSE hours is stale (NSE publishes ~1 min delayed).
pub const QUOTE_STALE_AFTER: Duration = Duration::from_secs(5 * 60);
/// An NSE print (the quote's own `time`) at most this old means NSE is printing NOW, whatever the calendar says
/// (round 4b, R10: the Muhurat session on Sun 8 Nov 2026, any special session): the tray then shows the quote as
/// live, never "· closed". The same window as the UI's NSE_PRINT_MAX_AGE_MS (ui/lib/feedState.ts), so the tray
/// and the header chip agree.
pub const FRESH_PRINT_MAX_AGE: Duration = Duration::from_secs(3 * 60);
/// A print stamped up to this far AHEAD of the Mac's clock (clock skew) still counts as fresh (UI: 2 min).
pub const FRESH_PRINT_MAX_AHEAD: Duration = Duration::from_secs(2 * 60);
/// Status events: a change goes out at most this often...
pub const STATUS_MIN_GAP: Duration = Duration::from_secs(5);
/// ...and a heartbeat at least this often (contract: <= 10 s, ui/components/desktop/status.ts).
pub const STATUS_HEARTBEAT: Duration = Duration::from_secs(8);
/// A service whose port still accepts connections but whose `/health` timed out this many polls IN A ROW is
/// "not responding" (hung: event loop blocked), not down and not starting (PM, 25 Oct: live ui-api hung
/// 14:40–14:48 while the boot page said "the watchdog is starting the stack"). One timeout alone is a blip.
pub const STALL_TIMEOUTS: u32 = 2;
/// Hard limit for one port-squatting probe (it runs on the blocking pool; a stuck probe is abandoned and
/// the verdict is Unknown, so the fast poll loop never stalls).
pub const TRUST_PROBE_TIMEOUT: Duration = Duration::from_secs(5);
/// A service must stay down this long (after the 2-check debounce) before a notification goes out.
pub const DOWN_NOTIFY_DELAY: Duration = Duration::from_secs(20);
/// After a "down" notification for a service, its next outage within this window is silent (crash loops).
pub const DOWN_NOTIFY_COOLDOWN: Duration = Duration::from_secs(600);

// ---------------------------------------------------------------------------------------------
// Contract types (shell <-> UI contract v1, PLAN.md §5)
// ---------------------------------------------------------------------------------------------

/// One service's health.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Svc {
    pub up: bool,
    pub latency_ms: Option<f64>,
}

impl Svc {
    pub const UNKNOWN: Svc = Svc {
        up: false,
        latency_ms: None,
    };
}

/// ICICI Breeze session state.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Icici {
    Connected,
    Expired,
    Unknown,
}

/// What the tray and the boot page say about the ICICI session (round 4b, P4): the contract's three states, plus
/// WHY a session that is not connected cannot be used when ui-api says so (its additive `error_kind` on
/// `/api/positions/connection-status`, round 4a). `ShellStatus.icici` (the frozen UI contract) stays
/// connected / expired / unknown: see [`IciciView::contract`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum IciciView {
    Connected,
    /// ICICI refused the session token (`error_kind` 'expired', or an older ui-api's "not connected"): /login.
    Expired,
    /// ICICI's API could not be reached after ui-api's retries (`error_kind` 'network'): NOT a login problem.
    Unreachable,
    /// The API key or secret is missing or rejected (`error_kind` 'credentials'): fixed on BRKR, not by /login.
    Credentials,
    Unknown,
}

impl IciciView {
    /// The frozen contract value: an outage or missing credentials are never reported as "expired" (which the
    /// UI words as "send /login"); they are "unknown".
    pub fn contract(self) -> Icici {
        match self {
            IciciView::Connected => Icici::Connected,
            IciciView::Expired => Icici::Expired,
            IciciView::Unreachable | IciciView::Credentials | IciciView::Unknown => Icici::Unknown,
        }
    }
}

/// NIFTY 50 last price and day change.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct Nifty {
    pub last: f64,
    pub change_pct: f64,
}

/// `ShellStatus` exactly as frozen in the contract (field names and shapes).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ShellStatus {
    pub at: String,
    pub ui_api: Svc,
    pub data_service: Svc,
    pub master_controller: Svc,
    pub icici: Icici,
    pub ui_build: Option<String>,
    pub nifty: Option<Nifty>,
}

impl Default for ShellStatus {
    fn default() -> Self {
        Self {
            at: now_iso(),
            ui_api: Svc::UNKNOWN,
            data_service: Svc::UNKNOWN,
            master_controller: Svc::UNKNOWN,
            icici: Icici::Unknown,
            ui_build: None,
            nifty: None,
        }
    }
}

impl ShellStatus {
    /// The parts whose change triggers an immediate (throttled) broadcast; latency and `at` excluded.
    pub fn change_key(&self) -> String {
        format!(
            "{}{}{}|{:?}|{:?}|{:?}",
            self.ui_api.up as u8,
            self.data_service.up as u8,
            self.master_controller.up as u8,
            self.icici,
            self.ui_build,
            self.nifty.map(|n| (n.last.to_bits(), n.change_pct.to_bits()))
        )
    }
}

/// Decision Desk paper NAV (tray only; not part of the UI contract).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct Desk {
    pub nav: f64,
    pub return_pct: f64,
    pub date: String,
}

/// Why the terminal can (not) be opened.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum UiState {
    /// No poll finished yet.
    Checking,
    /// ui-api answers /health, serves the UI release, and the port listener is not definitively foreign
    /// (trusted, or the check was inconclusive: see [`TrustView`]).
    Ready,
    /// ui-api does not answer /health and its port is closed (not running / restarting).
    ApiDown,
    /// ui-api's port accepts connections but `/health` timed out [`STALL_TIMEOUTS`] polls in a row: the
    /// process is there but hung (event loop blocked). Not "down", never "starting": the watchdog restarts a
    /// hung core service by itself about 3.5–5.5 min after it hangs (two hung runs in a row,
    /// scripts/stack_watchdog.sh); the boot page says so and names `./start-local.sh restart ui-api`.
    NotResponding,
    /// ui-api is up but has no UI release to serve (GET / = the 503 "build not found" page, /ready ui=missing):
    /// the remedy is `./start-local.sh build-ui` (or `--rollback`), not Start Stack.
    NoRelease,
    /// ui-api is up but GET / is not the terminal for another reason (HTTP status, content type).
    NotServed,
    /// The process listening on the ui port is definitively not the stack's ui-api (port squatting):
    /// never opened, and open terminal windows are pulled back to the boot page.
    Untrusted,
    /// Round 3 (R-RUST-02): a live process of this user holds the ui port, its executable no longer exists
    /// and it is not the listener verified before: it cannot be identified. Treated like Untrusted (never
    /// opened, open windows pulled back); the boot page names `./start-local.sh restart ui-api`.
    Unverifiable,
}

/// The port-squatting guard's last verdict, as the boot page, the tray and the self-test see it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "state", content = "detail", rename_all = "snake_case")]
pub enum TrustView {
    /// Not checked yet (the terminal port did not serve the UI).
    Unchecked,
    /// `verify_ui_listener: false`.
    Off,
    /// Every listener is this user's CPython (detail: pid + executable).
    Trusted(String),
    /// Definitively foreign: windows are kept off the terminal origin.
    Foreign(String),
    /// Inconclusive: windows open / stay open; retried within seconds.
    Unknown(String),
    /// A live listener of this user with a deleted executable that was never verified: windows are kept off
    /// the terminal origin (round 3, R-RUST-02).
    Unverifiable(String),
}

impl TrustView {
    pub fn of(v: &Result<String, TrustFail>) -> TrustView {
        match v {
            Ok(d) => TrustView::Trusted(d.clone()),
            Err(TrustFail::Foreign(e)) => TrustView::Foreign(e.clone()),
            Err(TrustFail::Unknown(e)) => TrustView::Unknown(e.clone()),
            Err(TrustFail::Unverifiable(e)) => TrustView::Unverifiable(e.clone()),
        }
    }
}

/// Freshness of the NIFTY quote.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum QuoteState {
    /// No quote yet / never fetched.
    None,
    /// NSE is open and the quote is current, or NSE printed within [`FRESH_PRINT_MAX_AGE`] whatever the
    /// calendar says (a special session such as Muhurat).
    Live,
    /// NSE is closed (weekend, before 09:15 / after 15:30 IST, or a holiday: the quote is a past session's).
    Closed,
    /// Fetches keep failing (data-service down) or the quote stopped moving during NSE hours.
    Stale,
}

/// Everything the shell knows about the stack right now.
#[derive(Debug, Clone)]
pub struct Snapshot {
    pub status: ShellStatus,
    pub desk: Option<Desk>,
    /// ui-api /health is up AND `GET /` on ui_url serves the terminal (200 text/html) AND the port listener
    /// is not definitively foreign.
    pub ui_ready: bool,
    pub ui_state: UiState,
    /// Why the UI is not ready (for the boot page), empty when ready.
    pub ui_detail: String,
    /// The last NIFTY quote fetched (kept while stale so the tray can say so), and its freshness.
    pub quote: Option<Quote>,
    pub quote_state: QuoteState,
    /// The ICICI session with its reason (tray + boot page); `status.icici` is its contract value.
    pub icici_view: IciciView,
    /// The stack's start/stop markers (watchdog busy, paused services, TCC preflight).
    pub stack: crate::stack::Activity,
    /// The port-squatting guard's last verdict.
    pub trust: TrustView,
    /// Per service (ShellStatus order: ui-api, data-service, master-controller): since when it has been NOT
    /// RESPONDING (port held, `/health` timing out; see [`StallTracker`]); None otherwise.
    pub stalled: [Option<Instant>; 3],
    /// Since when the terminal has been unreachable (None while ready / before the first poll).
    pub unready_since: Option<Instant>,
    /// Completed fast polls.
    pub polls: u64,
}

impl Default for Snapshot {
    fn default() -> Self {
        Self {
            status: ShellStatus::default(),
            desk: None,
            ui_ready: false,
            ui_state: UiState::Checking,
            ui_detail: "checking…".into(),
            quote: None,
            quote_state: QuoteState::None,
            icici_view: IciciView::Unknown,
            stack: crate::stack::Activity::default(),
            trust: TrustView::Unchecked,
            stalled: [None; 3],
            unready_since: None,
            polls: 0,
        }
    }
}

pub fn now_iso() -> String {
    OffsetDateTime::now_utc().format(&Rfc3339).unwrap_or_default()
}

// ---------------------------------------------------------------------------------------------
// Payload parsing (pure)
// ---------------------------------------------------------------------------------------------

/// `/api/market/nifty-live` -> `{last, change_pct}` (both finite).
pub fn parse_nifty(v: &Value) -> Option<Nifty> {
    let last = v.get("last")?.as_f64()?;
    let change_pct = v.get("change_pct")?.as_f64()?;
    (last.is_finite() && last > 0.0 && change_pct.is_finite()).then_some(Nifty { last, change_pct })
}

/// A NIFTY quote with its NSE timestamp (IST wall clock, `23-Oct-2026 15:30`).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Quote {
    pub nifty: Nifty,
    pub at: Option<PrimitiveDateTime>,
}

/// `23-Oct-2026 15:30` / `23-Oct-2026 15:30:05` (NSE allIndices `timestamp`) -> IST wall clock.
pub fn parse_nse_time(s: &str) -> Option<PrimitiveDateTime> {
    let fmt_s = time::macros::format_description!(
        "[day]-[month repr:short case_sensitive:false]-[year] [hour]:[minute]:[second]"
    );
    let fmt_m =
        time::macros::format_description!("[day]-[month repr:short case_sensitive:false]-[year] [hour]:[minute]");
    let s = s.trim();
    PrimitiveDateTime::parse(s, fmt_s)
        .or_else(|_| PrimitiveDateTime::parse(s, fmt_m))
        .ok()
}

/// `/api/market/nifty-live` -> quote (price + its time).
pub fn parse_quote(v: &Value) -> Option<Quote> {
    Some(Quote {
        nifty: parse_nifty(v)?,
        at: v.get("time").and_then(Value::as_str).and_then(parse_nse_time),
    })
}

/// NSE cash session (09:15-15:30 IST, Monday-Friday). Holidays are not known here: on a holiday the
/// quote's date is a past session's, which [`classify_quote`] reads as closed.
pub fn nse_open(now_utc: OffsetDateTime) -> bool {
    let ist = now_utc.to_offset(ist_offset());
    let minute = ist.hour() as u16 * 60 + ist.minute() as u16;
    !matches!(ist.weekday(), Weekday::Saturday | Weekday::Sunday) && (9 * 60 + 15..15 * 60 + 30).contains(&minute)
}

/// Pure (round 4b, R10): was this NSE print stamped within [`FRESH_PRINT_MAX_AGE`] of now (and at most
/// [`FRESH_PRINT_MAX_AHEAD`] ahead of it)? NSE's index timestamp stops at the session's last print (15:30 on a
/// normal day), so a fresh print means NSE is printing right now.
pub fn fresh_print(at: Option<PrimitiveDateTime>, now_utc: OffsetDateTime) -> bool {
    let Some(at) = at else {
        return false;
    };
    let age = now_utc - at.assume_offset(ist_offset());
    age <= FRESH_PRINT_MAX_AGE && -age <= FRESH_PRINT_MAX_AHEAD
}

/// Freshness of the last quote (pure). `failures` = consecutive failed fetches. Fresh data beats the calendar
/// (round 4b, R10): a print within [`FRESH_PRINT_MAX_AGE`] is live even on a weekend or after hours (Muhurat,
/// Sun 8 Nov 2026, evening; the calendar here knows only Mon–Fri 09:15–15:30). The reverse is never inferred: a
/// quiet feed in calendar hours keeps the old rules (stale after [`QUOTE_STALE_AFTER`], closed on a holiday).
/// Side effect of the rule: on a normal day the 15:30 print reads live until 15:33 (the UI header does the same).
pub fn classify_quote(q: Option<&Quote>, now_utc: OffsetDateTime, failures: u32) -> QuoteState {
    let Some(q) = q else {
        return QuoteState::None;
    };
    if failures >= 2 {
        return QuoteState::Stale;
    }
    if fresh_print(q.at, now_utc) {
        return QuoteState::Live;
    }
    if !nse_open(now_utc) {
        return QuoteState::Closed;
    }
    let Some(at) = q.at else {
        return QuoteState::Live; // no timestamp to judge by
    };
    let now_ist = now_utc.to_offset(ist_offset());
    let at_ist = at.assume_offset(ist_offset());
    if at_ist.date() < now_ist.date() {
        return QuoteState::Closed; // a past session's close during "hours": a trading holiday
    }
    if now_ist - at_ist > QUOTE_STALE_AFTER {
        QuoteState::Stale
    } else {
        QuoteState::Live
    }
}

/// What ShellStatus.nifty carries for a state: the quote when live or closed, null when stale (contract v1).
pub fn contract_nifty(q: Option<&Quote>, st: QuoteState) -> Option<Nifty> {
    match st {
        QuoteState::Live | QuoteState::Closed => q.map(|q| q.nifty),
        QuoteState::Stale | QuoteState::None => None,
    }
}

/// Only the fields the shell needs; every other one (incl. `login_url`) is ignored by serde. `error_kind` is
/// read as a raw value so an unexpected type never voids the two booleans.
#[derive(Debug, Deserialize)]
struct ConnStatus {
    connected: Option<bool>,
    needs_session_refresh: Option<bool>,
    error_kind: Option<Value>,
}

/// `/api/positions/connection-status` body -> ICICI state with its reason. The body is consumed here and dropped.
///
/// Round 4b (P4), ui-api's additive `error_kind` ('expired' | 'network' | 'credentials' | 'unknown'; null when
/// connected): 'network' = ICICI's API was unreachable after ui-api's retries, which is NOT a login problem
/// ([`IciciView::Unreachable`]: no "send /login", no "session expired" notification); 'credentials' = API key or
/// secret missing or rejected ([`IciciView::Credentials`], fixed on BRKR). ui-api's `needs_session_refresh` is
/// ALSO true during an outage, so `error_kind` is read first. 'expired', 'unknown', any other value, null or a
/// missing field (an older ui-api) keep the previous reading: not connected = expired.
pub fn parse_icici(body: &[u8]) -> IciciView {
    let Ok(c) = serde_json::from_slice::<ConnStatus>(body) else {
        return IciciView::Unknown;
    };
    if c.connected == Some(true) {
        return IciciView::Connected;
    }
    match c.error_kind.as_ref().and_then(Value::as_str) {
        Some("network") => return IciciView::Unreachable,
        Some("credentials") => return IciciView::Credentials,
        _ => {}
    }
    if c.needs_session_refresh == Some(true) || c.connected == Some(false) {
        IciciView::Expired
    } else {
        IciciView::Unknown
    }
}

/// `/api/desk/status` -> latest NAV and the return since the first NAV point.
pub fn parse_desk(v: &Value) -> Option<Desk> {
    let latest = v.get("latest")?;
    let nav = latest.get("nav")?.as_f64()?;
    let date = latest.get("date").and_then(Value::as_str).unwrap_or("").to_string();
    let first = v
        .get("nav")
        .and_then(Value::as_array)
        .and_then(|a| a.first())
        .and_then(|p| p.get("nav"))
        .and_then(Value::as_f64)
        .or_else(|| {
            v.get("meta")
                .and_then(|m| m.get("start_capital"))
                .and_then(Value::as_f64)
        })?;
    if !(nav.is_finite() && first.is_finite() && first > 0.0) {
        return None;
    }
    Some(Desk {
        nav,
        return_pct: (nav / first - 1.0) * 100.0,
        date,
    })
}

/// `/build-info.json` -> release id (`id`, falling back to `git_sha`); short, printable only.
pub fn parse_build_info(v: &Value) -> Option<String> {
    let id = v
        .get("id")
        .and_then(Value::as_str)
        .or_else(|| v.get("git_sha").and_then(Value::as_str))?;
    let id = id.trim();
    (!id.is_empty() && id.len() <= 64 && id.chars().all(|c| c.is_ascii_alphanumeric() || "-_.:+".contains(c)))
        .then(|| id.to_string())
}

/// Tray title for a quote and its freshness: live `NIFTY 24,180.5 ▲0.42%`, closed
/// `NIFTY 22,600.0 ▼0.39% · closed`, stale / none `NIFTY — stale` / `NIFTY —`.
pub fn tray_title_for(q: Option<&Quote>, st: QuoteState) -> String {
    match (q, st) {
        (Some(q), QuoteState::Live) => tray_title(Some(q.nifty)),
        (Some(q), QuoteState::Closed) => format!("{} · closed", tray_title(Some(q.nifty))),
        (_, QuoteState::Stale) => "NIFTY — stale".into(),
        _ => tray_title(None),
    }
}

/// Tray title, e.g. `NIFTY 24,180.5 ▲0.42%`.
pub fn tray_title(n: Option<Nifty>) -> String {
    match n {
        None => "NIFTY —".into(),
        Some(n) => {
            let arrow = if n.change_pct > 0.0 {
                "▲"
            } else if n.change_pct < 0.0 {
                "▼"
            } else {
                "•"
            };
            format!(
                "NIFTY {} {}{:.2}%",
                group_thousands(n.last, 1),
                arrow,
                n.change_pct.abs()
            )
        }
    }
}

/// `24180.55` -> `24,180.6` (comma thousands separators, fixed decimals).
pub fn group_thousands(v: f64, decimals: usize) -> String {
    let s = format!("{:.*}", decimals, v.abs());
    let (int, frac) = s
        .split_once('.')
        .map(|(a, b)| (a.to_string(), Some(b.to_string())))
        .unwrap_or((s.clone(), None));
    let mut out = String::new();
    for (i, ch) in int.chars().enumerate() {
        if i > 0 && (int.len() - i) % 3 == 0 {
            out.push(',');
        }
        out.push(ch);
    }
    if let Some(f) = frac {
        out.push('.');
        out.push_str(&f);
    }
    if v < 0.0 {
        format!("-{out}")
    } else {
        out
    }
}

// ---------------------------------------------------------------------------------------------
// Transition tracking (pure)
// ---------------------------------------------------------------------------------------------

/// A debounced up/down change of one service.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Transition {
    WentDown,
    CameUp,
}

/// Debounce: DOWN after 2 consecutive failures, UP after 1 success; the first stable state is the
/// baseline (no notification at launch). A service that is down at launch (the app starts before the
/// stack at login) is *starting*, not recovering: its first UP is not a transition either
/// (C2-reliability-ops-15: no "is back up" banners at every login).
#[derive(Debug, Default, Clone)]
pub struct SvcTracker {
    stable: Option<bool>,
    fails: u32,
    /// The service has been seen up since launch (only then can it go down and come back up).
    seen_up: bool,
}

impl SvcTracker {
    pub fn observe(&mut self, up: bool) -> Option<Transition> {
        if up {
            self.fails = 0;
            let was_seen = self.seen_up;
            self.seen_up = true;
            match self.stable {
                Some(false) if was_seen => {
                    self.stable = Some(true);
                    Some(Transition::CameUp)
                }
                _ => {
                    self.stable = Some(true);
                    None
                }
            }
        } else {
            self.fails += 1;
            if self.fails < 2 {
                return None;
            }
            match self.stable {
                Some(true) => {
                    self.stable = Some(false);
                    Some(Transition::WentDown)
                }
                _ => {
                    self.stable = Some(false);
                    None
                }
            }
        }
    }
}

/// Per-service notification state machine (pure), fed with the tracker's transitions after every poll.
///
/// * A WentDown is announced only if the service is still down [`DOWN_NOTIFY_DELAY`] later, so restarts and
///   short stalls never notify; services that went down together are announced in one notification.
/// * A service with a `.pids/paused/<svc>` marker was stopped on purpose (Stop Stack, `start-local.sh
///   stop`): never announced, and neither is its return.
/// * CameUp is announced only for a service whose outage was announced (separate from the down throttle,
///   so "back up" is never swallowed by the "down" notification's throttle: C2-reliability-ops-08).
/// * After an announced outage, the same service's next outage within [`DOWN_NOTIFY_COOLDOWN`] is silent.
#[derive(Debug, Default, Clone)]
pub struct SvcNotifier {
    svcs: [SvcNote; 3],
}

#[derive(Debug, Default, Clone, Copy)]
struct SvcNote {
    down_since: Option<Instant>,
    announced: bool,
    last_announced: Option<Instant>,
}

/// Notifications due after one observation (indices into [`SERVICE_NAMES`]).
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct Notes {
    pub down: Vec<usize>,
    pub up: Vec<usize>,
}

impl SvcNotifier {
    pub fn observe(
        &mut self,
        now: Instant,
        transitions: &[(usize, Transition)],
        up: [bool; 3],
        paused: [bool; 3],
    ) -> Notes {
        let mut notes = Notes::default();
        for &(i, t) in transitions {
            let n = &mut self.svcs[i];
            match t {
                Transition::WentDown => {
                    n.down_since = Some(now);
                    n.announced = false;
                }
                Transition::CameUp => {
                    if n.announced {
                        notes.up.push(i);
                    }
                    n.down_since = None;
                    n.announced = false;
                }
            }
        }
        for (i, n) in self.svcs.iter_mut().enumerate() {
            let Some(since) = n.down_since else { continue };
            if n.announced || up[i] || now.duration_since(since) < DOWN_NOTIFY_DELAY {
                continue;
            }
            let cooling = n
                .last_announced
                .map(|t| now.duration_since(t) < DOWN_NOTIFY_COOLDOWN)
                .unwrap_or(false);
            if paused[i] || cooling {
                n.down_since = None; // silent outage: its return is silent too
                continue;
            }
            n.announced = true;
            n.last_announced = Some(now);
            notes.down.push(i);
        }
        notes
    }
}

/// `ui-api` / `ui-api and data-service` / `data-service, ui-api and master-controller`.
pub fn join_names(names: &[&str]) -> String {
    match names {
        [] => String::new(),
        [a] => a.to_string(),
        [a, b] => format!("{a} and {b}"),
        [rest @ .., last] => format!("{} and {last}", rest.join(", ")),
    }
}

/// When the next `status` event is due (pure): a changed status at most every [`STATUS_MIN_GAP`], and a
/// heartbeat at least every [`STATUS_HEARTBEAT`] (contract notes: <= 10 s; see ui/components/desktop/status.ts).
#[derive(Debug, Default, Clone)]
pub struct StatusCadence {
    last_at: Option<Instant>,
    last_key: String,
}

impl StatusCadence {
    /// True (and recorded) when a broadcast of the status with change key `key` is due at `now`.
    pub fn due(&mut self, key: &str, now: Instant) -> bool {
        let since = self.last_at.map(|t| now.duration_since(t)).unwrap_or(Duration::MAX);
        let due = (key != self.last_key && since >= STATUS_MIN_GAP) || since >= STATUS_HEARTBEAT;
        if due {
            self.last_at = Some(now);
            self.last_key = key.to_string();
        }
        due
    }
}

/// How one `/health` probe ended.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum SvcProbe {
    /// 200 within the timeout (latency ms).
    Up(f64),
    /// Nothing listens: connection refused (or the port closed before the confirming connect).
    Refused,
    /// No answer within the timeout although the port accepts connections: the process is there but hung.
    Hung,
    /// It answered, but not 200 (or the request failed some other way).
    Failed,
}

impl SvcProbe {
    /// The contract view (`ShellStatus` keeps `{up, latency_ms}` only).
    pub fn svc(self) -> Svc {
        match self {
            SvcProbe::Up(ms) => Svc {
                up: true,
                latency_ms: Some((ms * 10.0).round() / 10.0),
            },
            _ => Svc {
                up: false,
                latency_ms: None,
            },
        }
    }
}

/// Consecutive held-port timeouts of one service -> since when it is NOT RESPONDING (pure).
#[derive(Debug, Default, Clone)]
pub struct StallTracker {
    timeouts: u32,
    first: Option<Instant>,
}

impl StallTracker {
    /// Feed one probe at `now`; returns Some(since) while the service counts as not responding.
    pub fn observe(&mut self, probe: SvcProbe, now: Instant) -> Option<Instant> {
        match probe {
            SvcProbe::Hung => {
                self.timeouts += 1;
                let first = *self.first.get_or_insert(now);
                (self.timeouts >= STALL_TIMEOUTS).then_some(first)
            }
            _ => {
                self.timeouts = 0;
                self.first = None;
                None
            }
        }
    }
}

/// `2 min 05 s` / `45 s`.
pub fn mmss(secs: u64) -> String {
    if secs >= 60 {
        format!("{} min {:02} s", secs / 60, secs % 60)
    } else {
        format!("{secs} s")
    }
}

/// Is something holding `port` on the URL's loopback host? A connect that succeeds, or that times out (a full
/// accept backlog of a process that stopped accepting), is "held"; refused is not (blocking, ≤ ~1 s).
pub fn port_held(url: &Url) -> bool {
    let Some(port) = url.port_or_known_default() else {
        return false;
    };
    let addrs: Vec<std::net::SocketAddr> = match url.host_str() {
        Some("localhost") => vec![
            ([127, 0, 0, 1], port).into(),
            (std::net::Ipv6Addr::LOCALHOST, port).into(),
        ],
        _ => vec![([127, 0, 0, 1], port).into()],
    };
    addrs.iter().any(
        |a| match std::net::TcpStream::connect_timeout(a, Duration::from_millis(500)) {
            Ok(_) => true,
            Err(e) => e.kind() == std::io::ErrorKind::TimedOut,
        },
    )
}

/// Watchdog rule for a HUNG core service (scripts/stack_watchdog.sh, W2-OPS 25 Oct): listening but /health not
/// answering on two runs in a row (2 min apart, after a 30 s debounce) -> diagnostics to .logs/hangs/, then
/// `start-local.sh restart <svc>`; ui-api at any time, data-service / master-controller never inside the
/// restart freeze windows, master-controller not while an ICICI login runs (at most 10 min), and at most 3 hang
/// restarts per service per hour (it alerts instead).
pub const HUNG_RESTART_NOTE: &str = "The watchdog restarts a hung core service once it has failed two checks in a \
     row (about 3.5–5.5 min after it hangs), after saving diagnostics to .logs/hangs/";

/// Title and body of a "down" notification for services that went down together (pure). `stalled[i]` = that
/// service holds its port but is not answering (hung). `watchdog` = the watchdog agent is loaded/installed
/// ([`crate::stack::Activity::watchdog_active`]): then the text says it restarts a hung service (W2-OPS'
/// rule, [`HUNG_RESTART_NOTE`]); otherwise that nothing does. Both name the manual restart command.
pub fn down_note(names: &[&str], stalled: &[bool], watchdog: bool) -> (String, String) {
    let hung: Vec<&str> = names
        .iter()
        .zip(stalled)
        .filter(|(_, h)| **h)
        .map(|(n, _)| *n)
        .collect();
    let gone: Vec<&str> = names
        .iter()
        .zip(stalled)
        .filter(|(_, h)| !**h)
        .map(|(n, _)| *n)
        .collect();
    let title = match (names, hung.len() == names.len()) {
        ([one], true) => format!("{one} is not responding"),
        ([one], false) => format!("{one} is down"),
        (many, true) => format!("{} services are not responding", many.len()),
        (many, false) => format!("{} services are down", many.len()),
    };
    let mut body = vec![];
    if !gone.is_empty() {
        body.push(format!(
            "{} not answering /health for 20 s. The watchdog restarts stopped core services within about 2 min{}.",
            join_names(&gone),
            if gone.contains(&"ui-api") {
                "; open terminal windows show a reconnect banner"
            } else {
                ""
            }
        ));
    }
    if !hung.is_empty() {
        let freeze = hung.iter().any(|n| *n != "ui-api");
        let who = if watchdog {
            format!(
                "{HUNG_RESTART_NOTE}{}. To restart it now",
                if freeze {
                    " (data-service / master-controller: never 07:45–09:20 or 18:30–21:15 IST or during an \
                     ICICI login; it alerts instead)"
                } else {
                    ""
                }
            )
        } else {
            format!(
                "The watchdog agent is not loaded, so nothing restarts it automatically. Restart it{}",
                if freeze {
                    " (data-service / master-controller: not 07:45–09:20 or 18:30–21:15 IST)"
                } else {
                    ""
                }
            )
        };
        body.push(format!(
            "{} {} its port but {} not answered /health for 20 s (blocked?). {who}: ./start-local.sh restart {}.",
            join_names(&hung),
            if hung.len() == 1 { "holds" } else { "hold" },
            if hung.len() == 1 { "has" } else { "have" },
            hung.join(" / "),
        ));
    }
    (title, body.join(" "))
}

/// ICICI connected -> expired detection (notify once per transition).
#[derive(Debug, Default, Clone)]
pub struct IciciTracker {
    last: Option<IciciView>,
}

impl IciciTracker {
    /// True when the session just went from connected to expired. A failed probe or an ICICI outage
    /// ([`IciciView::Unreachable`], round 4b P4) says nothing about the session: never a "session expired"
    /// notification, and a real expiry right after the outage still fires.
    pub fn observe(&mut self, now: IciciView) -> bool {
        if matches!(now, IciciView::Unknown | IciciView::Unreachable) {
            return false;
        }
        let fired = self.last == Some(IciciView::Connected) && now == IciciView::Expired;
        self.last = Some(now);
        fired
    }
}

// ---------------------------------------------------------------------------------------------
// The hub (shared state + HTTP)
// ---------------------------------------------------------------------------------------------

/// What changed in one update (passed to `crate::on_health_update`).
#[derive(Debug, Default, Clone)]
pub struct Update {
    pub transitions: Vec<(&'static str, Transition)>,
    pub icici_expired: bool,
    pub build_changed: Option<String>,
    pub tray_dirty: bool,
}

/// Shared health state.
pub struct HealthHub {
    pub snapshot: RwLock<Snapshot>,
    client: reqwest::Client,
    trackers: Mutex<[SvcTracker; 3]>,
    icici: Mutex<IciciTracker>,
    poke: Notify,
    /// A window is waiting on the boot page: poll every second instead of every 5 s.
    pub fast_mode: AtomicBool,
    last_poke: Mutex<Option<Instant>>,
    seq: AtomicU64,
    /// Not-responding detection per service (see [`StallTracker`]).
    stall: Mutex<[StallTracker; 3]>,
    /// Port-squatting guard pins (see [`TrustPins`]).
    trust: Mutex<TrustPins>,
    /// The last verdict written to the log (re-checks every 30 s log only when it changes).
    trust_logged: Mutex<Option<TrustView>>,
    /// Consecutive failed NIFTY fetches.
    nifty_failures: AtomicU64,
}

/// The listeners the last PASS identified (pid + kernel start time). Round 3: there is no cached verdict any
/// more (R-RUST-01: round 2 reused a pass for 30 s, so a squatter swapped in between two polls served the
/// IPC-granted origin for up to 30 s); every fast poll that finds the port held verifies it again (about 2 ms
/// of CPU). The pins only let the SAME processes stay trusted when their executable disappears while they run
/// (R-RUST-02: `brew cleanup` after `brew upgrade` deletes the running ui-api's keg). A pin can never be
/// inherited: a pid is reused, a pid + start time never is.
#[derive(Debug, Default, Clone)]
pub struct TrustPins {
    pins: Vec<crate::policy::ProcId>,
}

impl TrustPins {
    pub fn get(&self) -> Vec<crate::policy::ProcId> {
        self.pins.clone()
    }

    /// After a pass: these are the trusted processes now (replaces the old set; a restarted ui-api has a new
    /// pid and start time).
    pub fn set(&mut self, ids: Vec<crate::policy::ProcId>) {
        if !ids.is_empty() {
            self.pins = ids;
        }
    }
}

/// How `GET /` on the ui origin answered.
#[derive(Debug, Clone, PartialEq, Eq)]
enum Root {
    Html,
    Missing,
    Other(String),
}

/// Service display names (also notification titles), in ShellStatus order.
pub const SERVICE_NAMES: [&str; 3] = ["ui-api", "data-service", "master-controller"];

impl HealthHub {
    pub fn new() -> Arc<Self> {
        let client = reqwest::Client::builder()
            .no_proxy()
            .connect_timeout(Duration::from_millis(1500))
            .timeout(Duration::from_secs(2))
            .pool_max_idle_per_host(2)
            .user_agent(concat!("SuryaDhana-Desktop/", env!("CARGO_PKG_VERSION")))
            .build()
            .expect("http client");
        Arc::new(Self {
            snapshot: RwLock::new(Snapshot::default()),
            client,
            trackers: Mutex::new(Default::default()),
            icici: Mutex::new(IciciTracker::default()),
            poke: Notify::new(),
            fast_mode: AtomicBool::new(true),
            last_poke: Mutex::new(None),
            seq: AtomicU64::new(0),
            stall: Mutex::new(Default::default()),
            trust: Mutex::new(TrustPins::default()),
            trust_logged: Mutex::new(None),
            nifty_failures: AtomicU64::new(0),
        })
    }

    /// Current snapshot (cheap clone). A writer that panicked mid-update (poisoned lock) never hides the
    /// last state behind a default ("checking…" forever): the data is still read (wave-2 nit).
    pub fn snapshot(&self) -> Snapshot {
        self.snapshot.read().unwrap_or_else(|e| e.into_inner()).clone()
    }

    /// Ask for an immediate fast poll (Retry button); at most once per second.
    pub fn poke(&self) {
        let mut last = self.last_poke.lock().unwrap_or_else(|e| e.into_inner());
        if last.map(|t| t.elapsed() < Duration::from_secs(1)).unwrap_or(false) {
            return;
        }
        *last = Some(Instant::now());
        self.poke.notify_one();
    }

    async fn get(&self, url: &Url, timeout: Duration) -> Result<(u16, Option<String>, bytes_lite::Bytes, f64), NetErr> {
        let t = Instant::now();
        let resp = self
            .client
            .get(url.clone())
            .timeout(timeout)
            .send()
            .await
            .map_err(|e| classify(&e))?;
        let status = resp.status().as_u16();
        let ctype = resp
            .headers()
            .get(reqwest::header::CONTENT_TYPE)
            .and_then(|v| v.to_str().ok())
            .map(str::to_string);
        let body = resp.bytes().await.map_err(|e| classify(&e))?;
        Ok((
            status,
            ctype,
            bytes_lite::Bytes(body.to_vec()),
            t.elapsed().as_secs_f64() * 1000.0,
        ))
    }

    /// `GET /health` within `timeout`, classified: a timeout is confirmed with a plain TCP connect (the
    /// port still accepts connections = the process is there but hung).
    pub async fn probe_health(&self, base: &Url, timeout: Duration) -> SvcProbe {
        let Ok(url) = base.join("/health") else {
            return SvcProbe::Failed;
        };
        match self.get(&url, timeout).await {
            Ok((200, _, _, ms)) => SvcProbe::Up(ms),
            Ok(_) => SvcProbe::Failed,
            Err(NetErr::Refused) => SvcProbe::Refused,
            Err(NetErr::TimedOut) => {
                let u = url.clone();
                let held = tokio::time::timeout(
                    Duration::from_secs(3),
                    tokio::task::spawn_blocking(move || port_held(&u)),
                )
                .await
                .ok()
                .and_then(|r| r.ok())
                .unwrap_or(false);
                if held {
                    SvcProbe::Hung
                } else {
                    SvcProbe::Refused
                }
            }
            Err(NetErr::Other) => SvcProbe::Failed,
        }
    }

    async fn ui_root(&self, ui: &Url) -> Root {
        match self.get(ui, Duration::from_secs(3)).await {
            Ok((200, Some(ct), _, _)) if ct.to_ascii_lowercase().starts_with("text/html") => Root::Html,
            Ok((200, ct, _, _)) => Root::Other(format!(
                "GET / is not the terminal (content-type {})",
                ct.unwrap_or_default()
            )),
            Ok((503, _, _, _)) => {
                // ui-api's static UI answers 503 when there is no release; /ready says so explicitly
                let missing = match ui.join("/ready") {
                    Ok(u) => self
                        .json(&u, Duration::from_secs(2))
                        .await
                        .map(|v| ready_says_missing(&v))
                        .unwrap_or(false),
                    Err(_) => false,
                };
                if missing {
                    Root::Missing
                } else {
                    Root::Other("GET / returned HTTP 503".into())
                }
            }
            Ok((code, _, _, _)) => Root::Other(format!("GET / returned HTTP {code}")),
            Err(e) => Root::Other(e.describe().into()),
        }
    }

    /// Port-squatting guard for the ui port: verified on EVERY call (no cached pass; see [`TrustPins`]).
    /// Kernel facts only (trust.rs), on the blocking pool under [`TRUST_PROBE_TIMEOUT`]: a probe that overruns
    /// is abandoned as Unknown.
    pub(crate) async fn verify_listener(&self, cfg: &Config) -> TrustView {
        if !cfg.verify_ui_listener {
            return TrustView::Off;
        }
        let port = cfg.ui_url.port_or_known_default().unwrap_or(80);
        let extra = cfg.trusted_python_prefixes.clone();
        let pinned = self.trust.lock().unwrap_or_else(|e| e.into_inner()).get();
        let verdict = bounded_verdict(TRUST_PROBE_TIMEOUT, move || {
            crate::trust::verify_port(port, &extra, &pinned)
        })
        .await;
        self.trust
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .set(verdict.ids.clone());
        let v = verdict.result;
        let view = TrustView::of(&v);
        let changed = {
            let mut last = self.trust_logged.lock().unwrap_or_else(|e| e.into_inner());
            let changed = last.as_ref() != Some(&view);
            *last = Some(view.clone());
            changed
        };
        match (&view, changed) {
            (TrustView::Trusted(d), true) => {
                log::info!("[trust] ui port {port}: listener is a CPython of this user ({d})")
            }
            (TrustView::Foreign(e), true) => log::warn!("[trust] ui port {port} REFUSED (foreign listener): {e}"),
            (TrustView::Unknown(e), true) => {
                log::warn!("[trust] ui port {port} not verified ({e}); windows are not held back, retrying")
            }
            (TrustView::Unverifiable(e), true) => {
                log::warn!("[trust] ui port {port} REFUSED (unverifiable listener): {e}")
            }
            _ => log::debug!("[trust] ui port {port}: verdict unchanged"),
        }
        view
    }

    /// `GET url` -> (HTTP status, JSON body if it parses). For the notification feed (feed.rs).
    pub async fn get_json_status(&self, url: &Url, timeout: Duration) -> Result<(u16, Option<Value>), NetErr> {
        let (code, _, body, _) = self.get(url, timeout).await?;
        Ok((code, serde_json::from_slice(&body.0).ok()))
    }

    async fn json(&self, url: &Url, timeout: Duration) -> Option<Value> {
        match self.get(url, timeout).await {
            Ok((200, _, body, _)) => serde_json::from_slice(&body.0).ok(),
            _ => None,
        }
    }

    /// One fast poll: 3 services + UI root, concurrently; then the listener guard when the UI answers.
    pub async fn poll_fast(&self, cfg: &Config) -> Update {
        let (pui, pds, pmc, root) = tokio::join!(
            self.probe_health(&cfg.ui_url, HEALTH_TIMEOUT),
            self.probe_health(&cfg.data_service_url, HEALTH_TIMEOUT),
            self.probe_health(&cfg.controller_url, HEALTH_TIMEOUT),
            self.ui_root(&cfg.ui_url),
        );
        let (ui, ds, mc) = (pui.svc(), pds.svc(), pmc.svc());
        let now = Instant::now();
        let stalled: [Option<Instant>; 3] = {
            let mut st = self.stall.lock().unwrap_or_else(|e| e.into_inner());
            [
                st[0].observe(pui, now),
                st[1].observe(pds, now),
                st[2].observe(pmc, now),
            ]
        };
        // round 3: whenever something holds the port (it answered, or a /health timeout on a held port), not
        // only when the terminal looks ready: a squatter that fails /health must not keep serving open windows
        let trust = if port_in_use(pui, &root) {
            self.verify_listener(cfg).await
        } else {
            TrustView::Unchecked
        };
        let mut update = Update::default();
        {
            let mut tr = self.trackers.lock().unwrap_or_else(|e| e.into_inner());
            for (i, up) in [ui.up, ds.up, mc.up].into_iter().enumerate() {
                if let Some(t) = tr[i].observe(up) {
                    update.transitions.push((SERVICE_NAMES[i], t));
                }
            }
        }
        let mut s = self.snapshot.write().unwrap_or_else(|e| e.into_inner());
        let before = (
            s.status.ui_api.up,
            s.status.data_service.up,
            s.status.master_controller.up,
            s.ui_ready,
            s.ui_state,
            s.stalled.map(|x| x.is_some()),
        );
        s.status.ui_api = ui;
        s.status.data_service = ds;
        s.status.master_controller = mc;
        s.status.at = now_iso();
        let (state, detail) = ui_state_of(
            ui.up,
            stalled[0].map(|t| now.duration_since(t)),
            cfg.ui_url.port_or_known_default(),
            &root,
            &trust,
        );
        s.stalled = stalled;
        let ready = state == UiState::Ready;
        let trust_changed = s.trust != trust;
        s.trust = trust;
        s.ui_state = state;
        s.ui_detail = detail;
        if ready {
            s.unready_since = None;
        } else if s.unready_since.is_none() {
            s.unready_since = Some(Instant::now());
        }
        s.ui_ready = ready;
        s.polls += 1;
        update.tray_dirty = before != (ui.up, ds.up, mc.up, ready, state, stalled.map(|x| x.is_some()))
            || s.polls == 1
            || trust_changed;
        self.seq.fetch_add(1, Ordering::Relaxed);
        update
    }

    /// NIFTY + served UI build.
    pub async fn poll_market(&self, cfg: &Config) -> Update {
        let nifty_url = cfg.ui_url.join("/api/market/nifty-live").ok();
        let build_url = cfg.ui_url.join("/build-info.json").ok();
        let (nifty, build) = tokio::join!(
            async {
                match &nifty_url {
                    Some(u) => self
                        .json(u, Duration::from_secs(4))
                        .await
                        .as_ref()
                        .and_then(parse_quote),
                    None => None,
                }
            },
            async {
                match &build_url {
                    Some(u) => self
                        .json(u, Duration::from_secs(2))
                        .await
                        .as_ref()
                        .and_then(parse_build_info),
                    None => None,
                }
            }
        );
        let mut update = Update::default();
        let failures = if nifty.is_some() {
            self.nifty_failures.store(0, Ordering::Relaxed);
            0
        } else {
            self.nifty_failures.fetch_add(1, Ordering::Relaxed) + 1
        };
        let mut s = self.snapshot.write().unwrap_or_else(|e| e.into_inner());
        if nifty.is_some() {
            s.quote = nifty;
        }
        let state = classify_quote(
            s.quote.as_ref(),
            OffsetDateTime::now_utc(),
            failures.min(u32::MAX as u64) as u32,
        );
        let contract = contract_nifty(s.quote.as_ref(), state);
        if s.status.nifty != contract || s.quote_state != state {
            update.tray_dirty = true;
        }
        if s.quote_state != state {
            log::info!("[market] NIFTY quote {:?} -> {state:?}", s.quote_state);
        }
        s.quote_state = state;
        s.status.nifty = contract;
        if build.is_some() && s.status.ui_build.is_some() && s.status.ui_build != build {
            update.build_changed = build.clone();
        }
        if build.is_some() || !s.status.ui_api.up {
            if s.status.ui_build != build {
                update.tray_dirty = true;
            }
            s.status.ui_build = build;
        }
        update
    }

    /// ICICI session state (never logs or keeps the body).
    pub async fn poll_icici(&self, cfg: &Config) -> Update {
        let mut update = Update::default();
        let Ok(url) = cfg.ui_url.join("/api/positions/connection-status") else {
            return update;
        };
        let view = match self.get(&url, Duration::from_secs(15)).await {
            Ok((200, _, body, _)) => parse_icici(&body.0), // body dropped at end of scope
            _ => IciciView::Unknown,
        };
        update.icici_expired = self.icici.lock().unwrap_or_else(|e| e.into_inner()).observe(view);
        let mut s = self.snapshot.write().unwrap_or_else(|e| e.into_inner());
        if s.icici_view != view {
            update.tray_dirty = true;
            log::info!("[icici] session {:?} -> {view:?}", s.icici_view);
        }
        s.icici_view = view;
        s.status.icici = view.contract();
        update
    }

    /// Decision Desk NAV.
    pub async fn poll_desk(&self, cfg: &Config) -> Update {
        let mut update = Update::default();
        let Ok(url) = cfg.ui_url.join("/api/desk/status") else {
            return update;
        };
        let desk = self
            .json(&url, Duration::from_secs(10))
            .await
            .as_ref()
            .and_then(parse_desk);
        let mut s = self.snapshot.write().unwrap_or_else(|e| e.into_inner());
        if desk.is_some() && s.desk != desk {
            s.desk = desk;
            update.tray_dirty = true;
        }
        update
    }
}

/// `/ready` (`{"status":"ready","ui":"missing",…}`) says the UI release is missing.
pub fn ready_says_missing(v: &Value) -> bool {
    v.get("ui").and_then(Value::as_str) == Some("missing")
}

/// Run a blocking probe on the blocking pool for at most `limit`. A probe that overruns (or panics) is
/// abandoned as Unknown: it can never stall the caller's loop.
pub async fn bounded_probe<F>(limit: Duration, f: F) -> Result<String, TrustFail>
where
    F: FnOnce() -> Result<String, TrustFail> + Send + 'static,
{
    match tokio::time::timeout(limit, tokio::task::spawn_blocking(f)).await {
        Ok(Ok(v)) => v,
        Ok(Err(_)) => Err(TrustFail::Unknown("the listener check failed".into())),
        Err(_) => Err(TrustFail::Unknown(format!(
            "the listener check timed out after {} s",
            limit.as_secs()
        ))),
    }
}

/// [`bounded_probe`] for a full verification (verdict + the identities a pass pins).
pub async fn bounded_verdict<F>(limit: Duration, f: F) -> crate::trust::Verdict
where
    F: FnOnce() -> crate::trust::Verdict + Send + 'static,
{
    let fail = |m: String| crate::trust::Verdict {
        result: Err(TrustFail::Unknown(m)),
        ids: vec![],
    };
    match tokio::time::timeout(limit, tokio::task::spawn_blocking(f)).await {
        Ok(Ok(v)) => v,
        Ok(Err(_)) => fail("the listener check failed".into()),
        Err(_) => fail(format!("the listener check timed out after {} s", limit.as_secs())),
    }
}

/// Pure: does something hold the ui port (so the listener must be verified)? It answered `/health` (any
/// status), or `/health` timed out on a held port, or `GET /` served the terminal. A refused connection is a
/// closed port (nothing to verify).
fn port_in_use(health: SvcProbe, root: &Root) -> bool {
    !matches!(health, SvcProbe::Refused) || *root == Root::Html
}

/// Pure: may windows be pulled back to the boot page? Only for a definitive verdict (Untrusted, or
/// Unverifiable since round 3), never for an inconclusive one (wave 2: an Unknown verdict must never evict).
pub fn evicts(ui_state: UiState) -> bool {
    matches!(ui_state, UiState::Untrusted | UiState::Unverifiable)
}

/// Pure: the boot page's UI state from one poll. `stalled_for` = how long ui-api has been not responding
/// (port held, `/health` timing out), None when it is not.
fn ui_state_of(
    api_up: bool,
    stalled_for: Option<Duration>,
    port: Option<u16>,
    root: &Root,
    trust: &TrustView,
) -> (UiState, String) {
    // a definitive refusal wins over every other state (round 3: also while /health fails or hangs, so a
    // squatter that does not answer /health is still refused and open windows are pulled back)
    match trust {
        TrustView::Foreign(e) => return (UiState::Untrusted, e.clone()),
        TrustView::Unverifiable(e) => return (UiState::Unverifiable, e.clone()),
        _ => {}
    }
    if !api_up {
        return match stalled_for {
            Some(d) => (
                UiState::NotResponding,
                format!(
                    "ui-api holds :{} but has not answered /health for {} (event loop blocked?)",
                    port.unwrap_or(0),
                    mmss(d.as_secs().max(HEALTH_TIMEOUT.as_secs()))
                ),
            ),
            None => (UiState::ApiDown, "ui-api /health not answering".into()),
        };
    }
    match root {
        Root::Missing => (
            UiState::NoRelease,
            "ui-api is up but has no terminal UI release to serve (GET / = 503, /ready ui=missing)".into(),
        ),
        Root::Other(why) => (UiState::NotServed, why.clone()),
        // trusted, off, or inconclusive: the terminal opens (only a definitive verdict holds windows back)
        Root::Html => (UiState::Ready, String::new()),
    }
}

/// Why a request failed (kept apart: a timeout on a held port is "not responding", a refusal is "down").
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NetErr {
    TimedOut,
    Refused,
    Other,
}

impl NetErr {
    pub fn describe(self) -> &'static str {
        match self {
            NetErr::TimedOut => "timed out",
            NetErr::Refused => "connection refused",
            NetErr::Other => "request failed",
        }
    }
}

fn classify(e: &reqwest::Error) -> NetErr {
    // a connect timeout is both is_connect and is_timeout: it is a timeout (the port is held)
    if e.is_timeout() {
        NetErr::TimedOut
    } else if e.is_connect() {
        NetErr::Refused
    } else {
        NetErr::Other
    }
}

/// Minimal owned byte buffer (keeps reqwest's `Bytes` type out of the public API).
mod bytes_lite {
    pub struct Bytes(pub Vec<u8>);
}

/// Run a polling loop as its own task and restart it 5 s after a panic (logged by the panic hook), so a bug
/// in one poll never silently freezes the tray, the boot page or the status events.
fn spawn_supervised<F, Fut>(name: &'static str, make: F)
where
    F: Fn() -> Fut + Send + Sync + 'static,
    Fut: std::future::Future<Output = ()> + Send + 'static,
{
    tauri::async_runtime::spawn(async move {
        loop {
            match tauri::async_runtime::spawn(make()).await {
                Ok(()) => break,
                Err(e) => {
                    log::error!("[health] {name} loop stopped ({e}); restarting it in 5 s");
                    tokio::time::sleep(Duration::from_secs(5)).await;
                }
            }
        }
    });
}

/// Spawn the polling loops. `on_update` runs after every poll (on the async runtime). `home` is the home
/// directory the app runs with (the watchdog plist lives under it).
pub fn spawn_pollers<F>(hub: Arc<HealthHub>, cfg: Config, home: PathBuf, on_update: F)
where
    F: Fn(Update) + Send + Sync + Clone + 'static,
{
    // fast loop: services + UI root (+ listener guard)
    {
        let (hub, cfg, cb) = (hub.clone(), cfg.clone(), on_update.clone());
        spawn_supervised("fast", move || {
            let (hub, cfg, cb) = (hub.clone(), cfg.clone(), cb.clone());
            async move {
                loop {
                    let u = hub.poll_fast(&cfg).await;
                    cb(u);
                    let wait = if hub.fast_mode.load(Ordering::Relaxed) {
                        Duration::from_secs(1)
                    } else {
                        Duration::from_secs(5)
                    };
                    tokio::select! {
                        _ = tokio::time::sleep(wait) => {}
                        _ = hub.poke.notified() => {}
                    }
                }
            }
        });
    }
    // market loop: NIFTY + build id, every 15 s (first run immediately)
    {
        let (hub, cfg, cb) = (hub.clone(), cfg.clone(), on_update.clone());
        spawn_supervised("market", move || {
            let (hub, cfg, cb) = (hub.clone(), cfg.clone(), cb.clone());
            async move {
                loop {
                    let u = hub.poll_market(&cfg).await;
                    cb(u);
                    tokio::time::sleep(Duration::from_secs(15)).await;
                }
            }
        });
    }
    // ICICI loop: every 60 s
    {
        let (hub, cfg, cb) = (hub.clone(), cfg.clone(), on_update.clone());
        spawn_supervised("icici", move || {
            let (hub, cfg, cb) = (hub.clone(), cfg.clone(), cb.clone());
            async move {
                loop {
                    let u = hub.poll_icici(&cfg).await;
                    cb(u);
                    tokio::time::sleep(Duration::from_secs(60)).await;
                }
            }
        });
    }
    // Desk loop: every 5 min
    {
        let (hub, cfg, cb) = (hub.clone(), cfg.clone(), on_update.clone());
        spawn_supervised("desk", move || {
            let (hub, cfg, cb) = (hub.clone(), cfg.clone(), cb.clone());
            async move {
                loop {
                    let u = hub.poll_desk(&cfg).await;
                    cb(u);
                    tokio::time::sleep(Duration::from_secs(300)).await;
                }
            }
        });
    }
    // stack bookkeeping: file checks every 5 s, `launchctl print` of the watchdog every 30 s
    spawn_supervised("stack", move || {
        let (hub, cfg, home, cb) = (hub.clone(), cfg.clone(), home.clone(), on_update.clone());
        async move {
            let paths = crate::stack::StackPaths::new(&cfg.repo_root);
            let uid = crate::stack::current_uid();
            let mut loaded: Option<(Instant, bool)> = None;
            loop {
                let is_loaded = match loaded {
                    Some((t, v)) if t.elapsed() < Duration::from_secs(30) => v,
                    _ => {
                        let v = tokio::task::spawn_blocking(move || crate::stack::watchdog_loaded(uid))
                            .await
                            .unwrap_or(false);
                        loaded = Some((Instant::now(), v));
                        v
                    }
                };
                let (p, h) = (paths.clone(), home.clone());
                let mut a = tokio::task::spawn_blocking(move || {
                    crate::stack::probe_files(&p, &h, std::time::SystemTime::now())
                })
                .await
                .unwrap_or_default();
                a.watchdog_loaded = Some(is_loaded);
                let changed = {
                    let mut s = hub.snapshot.write().unwrap_or_else(|e| e.into_inner());
                    let changed = s.stack != a;
                    s.stack = a;
                    changed
                };
                if changed {
                    cb(Update {
                        tray_dirty: true,
                        ..Update::default()
                    });
                }
                tokio::time::sleep(Duration::from_secs(5)).await;
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn shell_status_serializes_exactly_per_contract() {
        let s = ShellStatus {
            at: "2026-10-24T05:40:00Z".into(),
            ui_api: Svc {
                up: true,
                latency_ms: Some(1.7),
            },
            data_service: Svc {
                up: true,
                latency_ms: Some(2.0),
            },
            master_controller: Svc {
                up: false,
                latency_ms: None,
            },
            icici: Icici::Expired,
            ui_build: None,
            nifty: Some(Nifty {
                last: 22600.0,
                change_pct: -0.39,
            }),
        };
        let v = serde_json::to_value(&s).unwrap();
        let keys: Vec<&str> = v.as_object().unwrap().keys().map(String::as_str).collect();
        let mut sorted = keys.clone();
        sorted.sort();
        assert_eq!(
            sorted,
            [
                "at",
                "data_service",
                "icici",
                "master_controller",
                "nifty",
                "ui_api",
                "ui_build"
            ]
        );
        assert_eq!(v["icici"], "expired");
        assert_eq!(v["master_controller"], json!({"up": false, "latency_ms": null}));
        assert_eq!(v["ui_build"], Value::Null);
        assert_eq!(v["nifty"], json!({"last": 22600.0, "change_pct": -0.39}));
        // round trip
        let back: ShellStatus = serde_json::from_value(v).unwrap();
        assert_eq!(back, s);
        for st in ["connected", "expired", "unknown"] {
            let i: Icici = serde_json::from_value(json!(st)).unwrap();
            assert_eq!(serde_json::to_value(i).unwrap(), json!(st));
        }
    }

    #[test]
    fn parses_live_payload_samples() {
        // shapes captured from the live stack on 24 Oct 2026
        let nifty = json!({"index":"NIFTY 50","last":22600.0,"change":-87.65,"change_pct":-0.39,"open":22742.2,"time":"23-Oct-2026 15:30"});
        assert_eq!(
            parse_nifty(&nifty),
            Some(Nifty {
                last: 22600.0,
                change_pct: -0.39
            })
        );
        assert_eq!(parse_nifty(&json!({"last": null, "change_pct": 1.0})), None);
        assert_eq!(parse_nifty(&json!({"detail": "Not Found"})), None);

        let desk = json!({
            "meta": {"start_capital": 500000.0},
            "latest": {"date": "2026-10-23", "nav": 502085.36914345657},
            "nav": [{"date": "2026-09-25", "nav": 500000.0}, {"date": "2026-10-23", "nav": 502085.36914345657}],
            "positions": [], "plans": [], "events": [], "realized": []
        });
        let d = parse_desk(&desk).unwrap();
        assert_eq!(d.date, "2026-10-23");
        assert!((d.return_pct - 0.41707).abs() < 1e-3, "{}", d.return_pct);
        let no_series = json!({"meta": {"start_capital": 400000.0}, "latest": {"nav": 440000.0}, "nav": []});
        assert!((parse_desk(&no_series).unwrap().return_pct - 10.0).abs() < 1e-9);
        assert!(parse_desk(&json!({"latest": null})).is_none());

        assert_eq!(
            parse_build_info(&json!({"id":"20261024-1110-ab12cd3","git_sha":"ab12cd3","files":60})),
            Some("20261024-1110-ab12cd3".into())
        );
        assert_eq!(parse_build_info(&json!({"git_sha":"ab12cd3"})), Some("ab12cd3".into()));
        assert_eq!(parse_build_info(&json!({"id":"<script>"})), None);
        assert_eq!(parse_build_info(&json!({"id":""})), None);
    }

    #[test]
    fn icici_reads_only_its_fields_and_ignores_login_url() {
        let expired = br#"{"connected":false,"error":"expired","needs_session_refresh":true,"login_url":"https://api.icicidirect.com/apiuser/login?api_key=SECRET","backend":{"x":1}}"#;
        assert_eq!(parse_icici(expired), IciciView::Expired);
        assert_eq!(
            parse_icici(br#"{"connected":true,"needs_session_refresh":false}"#),
            IciciView::Connected
        );
        assert_eq!(
            parse_icici(br#"{"connected":false,"needs_session_refresh":false}"#),
            IciciView::Expired
        );
        assert_eq!(parse_icici(b"not json"), IciciView::Unknown);
        assert_eq!(parse_icici(br#"{"detail":"x"}"#), IciciView::Unknown);
    }

    #[test]
    fn an_icici_outage_is_unreachable_never_expired() {
        // round 4b, P4: ui-api's error_kind (fix_round4a.md contract). An outage keeps needs_session_refresh true,
        // so error_kind is read first.
        let body = |kind: &str| {
            format!(
                r#"{{"connected":false,"needs_session_refresh":true,"error_kind":{kind},"login_url":"https://api.icicidirect.com/apiuser/login?api_key=SECRET"}}"#
            )
        };
        let net = parse_icici(body("\"network\"").as_bytes());
        assert_eq!(net, IciciView::Unreachable);
        assert_eq!(
            net.contract(),
            Icici::Unknown,
            "the UI contract never says expired for an outage"
        );
        assert_eq!(parse_icici(body("\"credentials\"").as_bytes()), IciciView::Credentials);
        assert_eq!(IciciView::Credentials.contract(), Icici::Unknown);
        // 'expired' unchanged; 'unknown', null, a missing field (an older ui-api) or an unexpected value keep the
        // previous reading (not connected = expired)
        for k in ["\"expired\"", "\"unknown\"", "null", "42", "\"NETWORK\""] {
            let v = parse_icici(body(k).as_bytes());
            assert_eq!(v, IciciView::Expired, "error_kind {k}");
            assert_eq!(v.contract(), Icici::Expired);
        }
        assert_eq!(
            parse_icici(br#"{"connected":false,"needs_session_refresh":true}"#),
            IciciView::Expired,
            "no error_kind: as before"
        );
        // connected wins over a stray kind
        assert_eq!(
            parse_icici(br#"{"connected":true,"needs_session_refresh":false,"error_kind":"network"}"#),
            IciciView::Connected
        );
        assert_eq!(
            parse_icici(br#"{"connected":true,"needs_session_refresh":false,"error_kind":null}"#),
            IciciView::Connected
        );
        // the boot page's wording keys
        assert_eq!(
            serde_json::to_value(IciciView::Unreachable).unwrap(),
            json!("unreachable")
        );
        assert_eq!(
            serde_json::to_value(IciciView::Credentials).unwrap(),
            json!("credentials")
        );
        // negative control of the rule itself: the same outage body read WITHOUT error_kind is "expired" (the
        // pre-4b reading, which told the owner to send /login during an ICICI outage)
        let stripped = body("\"network\"").replace(r#""error_kind":"network","#, "");
        assert_eq!(parse_icici(stripped.as_bytes()), IciciView::Expired);
    }

    #[test]
    fn tracker_debounces_and_baselines() {
        let mut t = SvcTracker::default();
        assert_eq!(t.observe(true), None); // baseline up, no notification
        assert_eq!(t.observe(false), None); // 1 failure: not yet
        assert_eq!(t.observe(false), Some(Transition::WentDown));
        assert_eq!(t.observe(false), None);
        assert_eq!(t.observe(true), Some(Transition::CameUp));
        assert_eq!(t.observe(true), None);
        let mut t = SvcTracker::default();
        assert_eq!(t.observe(false), None);
        assert_eq!(t.observe(false), None); // baseline down at launch: no notification
                                            // C2-reliability-ops-15: a service that was down when the app started is starting, not
                                            // recovering: its first UP is not "back up" (the old tracker returned CameUp here)
        assert_eq!(t.observe(true), None);
        // a single blip never notifies
        assert_eq!(t.observe(false), None);
        assert_eq!(t.observe(true), None);
        // once it has been up, a real outage is a transition both ways
        assert_eq!(t.observe(false), None);
        assert_eq!(t.observe(false), Some(Transition::WentDown));
        assert_eq!(t.observe(true), Some(Transition::CameUp));
    }

    #[test]
    fn notifier_delays_groups_pairs_and_respects_paused() {
        let t0 = Instant::now();
        let s = |secs: u64| t0 + Duration::from_secs(secs);
        let all_up = [true; 3];
        let none = [false; 3];
        let mut n = SvcNotifier::default();
        // a restart shorter than the delay: nothing at all, not even "back up"
        assert_eq!(
            n.observe(s(0), &[(0, Transition::WentDown)], [false, true, true], none),
            Notes::default()
        );
        assert_eq!(n.observe(s(10), &[], [false, true, true], none), Notes::default());
        assert_eq!(
            n.observe(s(13), &[(0, Transition::CameUp)], all_up, none),
            Notes::default()
        );
        // a real outage of two services: one grouped "down" after 20 s, then their "back up"
        let down2 = [false, false, true];
        assert_eq!(
            n.observe(
                s(100),
                &[(0, Transition::WentDown), (1, Transition::WentDown)],
                down2,
                none
            ),
            Notes::default()
        );
        assert_eq!(n.observe(s(121), &[], down2, none).down, vec![0, 1]);
        assert_eq!(n.observe(s(126), &[], down2, none), Notes::default(), "announced once");
        let up = n.observe(
            s(200),
            &[(0, Transition::CameUp), (1, Transition::CameUp)],
            all_up,
            none,
        );
        assert_eq!(up.up, vec![0, 1], "back up is never swallowed by the down throttle");
        // the same service crashing again within the cooldown: silent both ways
        n.observe(s(300), &[(0, Transition::WentDown)], [false, true, true], none);
        assert_eq!(n.observe(s(330), &[], [false, true, true], none), Notes::default());
        assert_eq!(
            n.observe(s(340), &[(0, Transition::CameUp)], all_up, none),
            Notes::default()
        );
        // C1-desktop-native-07: a service stopped on purpose (paused marker) is never announced
        let mut n = SvcNotifier::default();
        let paused = [true, true, true];
        n.observe(
            s(0),
            &[
                (0, Transition::WentDown),
                (1, Transition::WentDown),
                (2, Transition::WentDown),
            ],
            [false; 3],
            paused,
        );
        assert_eq!(n.observe(s(30), &[], [false; 3], paused), Notes::default());
        let back = n.observe(
            s(90),
            &[
                (0, Transition::CameUp),
                (1, Transition::CameUp),
                (2, Transition::CameUp),
            ],
            all_up,
            none,
        );
        assert_eq!(back, Notes::default(), "no 'back up' after a deliberate Stop/Start");
        assert_eq!(join_names(&["a"]), "a");
        assert_eq!(join_names(&["a", "b"]), "a and b");
        assert_eq!(join_names(&["a", "b", "c"]), "a, b and c");
    }

    #[test]
    fn status_cadence_heartbeat_is_well_inside_the_ui_stale_threshold() {
        // contract notes: the shell pushes at least every 10 s (ui/components/desktop/status.ts
        // SHELL_STATUS_MAX_INTERVAL_MS; the UI greys the dots after 35 s); the 1 s ticker plus this heartbeat
        // keeps the gap <= 9 s
        assert!(STATUS_HEARTBEAT + Duration::from_secs(1) <= Duration::from_secs(10));
        let t0 = Instant::now();
        let at = |ms: u64| t0 + Duration::from_millis(ms);
        let mut c = StatusCadence::default();
        assert!(c.due("a", at(0)), "first status goes out at once");
        assert!(!c.due("a", at(1000)));
        assert!(!c.due("b", at(4000)), "a change waits for the 5 s minimum gap");
        assert!(c.due("b", at(5000)));
        assert!(!c.due("b", at(12_000)));
        assert!(c.due("b", at(13_000)), "heartbeat with nothing changed");
        // the old cadence (30 s heartbeat) would have left a 20+ s gap: never with this one
        let mut c = StatusCadence::default();
        let mut last = 0;
        let mut max_gap = 0;
        for ms in (0..120_000).step_by(1000) {
            if c.due("same", at(ms)) {
                max_gap = max_gap.max(ms - last);
                last = ms;
            }
        }
        assert!(max_gap <= 9000, "{max_gap}");
    }

    #[test]
    fn nse_time_and_quote_freshness() {
        use time::macros::datetime;
        assert_eq!(parse_nse_time("23-Oct-2026 15:30"), Some(datetime!(2026-10-23 15:30)));
        assert_eq!(
            parse_nse_time("24-Oct-2026 11:02:05"),
            Some(datetime!(2026-10-24 11:02:05))
        );
        assert_eq!(parse_nse_time("24-OCT-2026 11:02"), Some(datetime!(2026-10-24 11:02)));
        assert_eq!(parse_nse_time("garbage"), None);
        let q = |t: &str| Quote {
            nifty: Nifty {
                last: 24180.5,
                change_pct: 0.4,
            },
            at: parse_nse_time(t),
        };
        // Monday 26 Oct 2026, 11:00 IST = 05:30 UTC
        let mon_11 = datetime!(2026-10-26 05:30 UTC);
        assert!(nse_open(mon_11));
        assert_eq!(
            classify_quote(Some(&q("26-Oct-2026 10:59")), mon_11, 0),
            QuoteState::Live
        );
        // C1-desktop-native-04: data-service wedged at 10:40, the quote stopped moving
        assert_eq!(
            classify_quote(Some(&q("26-Oct-2026 10:40")), mon_11, 0),
            QuoteState::Stale
        );
        // two failed fetches in a row (ui-api 503: data-service down): stale, whatever the time says
        assert_eq!(
            classify_quote(Some(&q("26-Oct-2026 10:59")), mon_11, 2),
            QuoteState::Stale
        );
        assert_eq!(
            classify_quote(Some(&q("26-Oct-2026 10:59")), mon_11, 1),
            QuoteState::Live,
            "one blip"
        );
        // weekend / after hours / a trading holiday: closed, never "live"
        let sun = datetime!(2026-10-25 06:00 UTC);
        assert!(!nse_open(sun));
        assert_eq!(
            classify_quote(Some(&q("23-Oct-2026 15:30")), sun, 0),
            QuoteState::Closed
        );
        let mon_16 = datetime!(2026-10-26 10:45 UTC); // 16:15 IST
        assert_eq!(
            classify_quote(Some(&q("26-Oct-2026 15:30")), mon_16, 0),
            QuoteState::Closed
        );
        let holiday = datetime!(2026-11-10 04:30 UTC); // Tue 10 Nov, 10:00 IST (NSE holiday)
        assert_eq!(
            classify_quote(Some(&q("09-Nov-2026 15:30")), holiday, 0),
            QuoteState::Closed
        );
        assert_eq!(classify_quote(None, mon_11, 0), QuoteState::None);
        // the contract carries the quote only when it is not stale
        let qq = q("26-Oct-2026 10:59");
        assert!(contract_nifty(Some(&qq), QuoteState::Live).is_some());
        assert!(contract_nifty(Some(&qq), QuoteState::Closed).is_some());
        assert!(contract_nifty(Some(&qq), QuoteState::Stale).is_none());
        // tray titles
        assert_eq!(tray_title_for(Some(&qq), QuoteState::Live), "NIFTY 24,180.5 ▲0.40%");
        assert_eq!(
            tray_title_for(Some(&qq), QuoteState::Closed),
            "NIFTY 24,180.5 ▲0.40% · closed"
        );
        assert_eq!(tray_title_for(Some(&qq), QuoteState::Stale), "NIFTY — stale");
        assert_eq!(tray_title_for(None, QuoteState::None), "NIFTY —");
        // the live payload shape parses with its time
        let v = json!({"index":"NIFTY 50","last":22600.0,"change_pct":-0.39,"time":"23-Oct-2026 15:30"});
        assert_eq!(parse_quote(&v).unwrap().at, Some(datetime!(2026-10-23 15:30)));
    }

    #[test]
    fn fresh_nse_prints_beat_the_calendar_on_a_special_session() {
        // round 4b, R10: Muhurat trading, Sun 8 Nov 2026 (evening; NSE publishes the exact window by circular).
        // The calendar here says closed (a Sunday); NSE printing within 3 min says live.
        use time::macros::datetime;
        let q = |t: &str| Quote {
            nifty: Nifty {
                last: 24180.5,
                change_pct: 0.4,
            },
            at: parse_nse_time(t),
        };
        let muhurat = datetime!(2026-11-08 12:50 UTC); // 18:20 IST
        assert!(!nse_open(muhurat), "a Sunday: the calendar says closed");
        assert_eq!(
            classify_quote(Some(&q("08-Nov-2026 18:19")), muhurat, 0),
            QuoteState::Live
        );
        assert_eq!(
            classify_quote(Some(&q("08-Nov-2026 18:17:05")), muhurat, 0),
            QuoteState::Live
        );
        assert_eq!(
            tray_title_for(Some(&q("08-Nov-2026 18:19")), QuoteState::Live),
            "NIFTY 24,180.5 ▲0.40%",
            "no '· closed' while NSE prints"
        );
        // older than 3 min: the calendar decides again (closed), never stale on a closed day
        assert_eq!(
            classify_quote(Some(&q("08-Nov-2026 18:16")), muhurat, 0),
            QuoteState::Closed
        );
        // after the session: the last Muhurat print, then Friday's close on Monday morning before the open
        let after = datetime!(2026-11-08 14:00 UTC); // 19:30 IST
        assert_eq!(
            classify_quote(Some(&q("08-Nov-2026 19:15")), after, 0),
            QuoteState::Closed
        );
        // a clock skew of up to 2 min ahead still counts; a print from the future beyond that does not
        assert_eq!(
            classify_quote(Some(&q("08-Nov-2026 18:21:30")), muhurat, 0),
            QuoteState::Live
        );
        assert_eq!(
            classify_quote(Some(&q("08-Nov-2026 18:25")), muhurat, 0),
            QuoteState::Closed
        );
        // failing fetches still win (the stored quote is not being refreshed)
        assert_eq!(
            classify_quote(Some(&q("08-Nov-2026 18:19")), muhurat, 2),
            QuoteState::Stale
        );
        // no timestamp: nothing to judge by, the calendar decides
        let undated = Quote {
            at: None,
            ..q("08-Nov-2026 18:19")
        };
        assert_eq!(classify_quote(Some(&undated), muhurat, 0), QuoteState::Closed);
        // a special Saturday session behaves the same
        let sat = datetime!(2026-10-31 05:00 UTC); // Sat 10:30 IST
        assert_eq!(classify_quote(Some(&q("31-Oct-2026 10:29")), sat, 0), QuoteState::Live);
        // a normal weekday: unchanged in hours; the 15:30 close reads live only until 15:33
        let mon_1532 = datetime!(2026-10-26 10:02 UTC);
        assert_eq!(
            classify_quote(Some(&q("26-Oct-2026 15:30")), mon_1532, 0),
            QuoteState::Live
        );
        let mon_1534 = datetime!(2026-10-26 10:04 UTC);
        assert_eq!(
            classify_quote(Some(&q("26-Oct-2026 15:30")), mon_1534, 0),
            QuoteState::Closed
        );
        // the boundary itself
        assert!(fresh_print(parse_nse_time("08-Nov-2026 18:17"), muhurat));
        assert!(!fresh_print(parse_nse_time("08-Nov-2026 18:16:59"), muhurat));
        assert!(!fresh_print(None, muhurat));
    }

    #[test]
    fn ui_state_tells_missing_release_and_squatter_apart() {
        assert!(ready_says_missing(
            &json!({"status":"ready","service":"ui-api","ui":"missing","ui_build_id":null})
        ));
        assert!(!ready_says_missing(&json!({"status":"ready","ui":"ok"})));
        let un = TrustView::Unchecked;
        assert_eq!(
            ui_state_of(false, None, Some(8010), &Root::Html, &un).0,
            UiState::ApiDown
        );
        // C2-reliability-ops-04: 503 + /ready ui=missing is "no UI release", not "stack down"
        let (st, why) = ui_state_of(true, None, Some(8010), &Root::Missing, &un);
        assert_eq!(st, UiState::NoRelease);
        assert!(why.contains("no terminal UI release"));
        assert_eq!(
            ui_state_of(
                true,
                None,
                Some(8010),
                &Root::Other("GET / returned HTTP 500".into()),
                &un
            )
            .0,
            UiState::NotServed
        );
        assert_eq!(
            ui_state_of(true, None, Some(8010), &Root::Html, &TrustView::Trusted("pid 1".into())).0,
            UiState::Ready
        );
        assert_eq!(
            ui_state_of(true, None, Some(8010), &Root::Html, &TrustView::Off).0,
            UiState::Ready
        );
        let (st, why) = ui_state_of(
            true,
            None,
            Some(8010),
            &Root::Html,
            &TrustView::Foreign("pid 66 runs Helper".into()),
        );
        assert_eq!((st, why.as_str()), (UiState::Untrusted, "pid 66 runs Helper"));
        assert!(evicts(st), "a definitive Foreign verdict pulls windows back");
        // wave 2: an inconclusive verdict (probe failed / timed out / listener vanished) opens the terminal
        // and NEVER evicts (round 1 kept windows on the boot page: a TCC-denied probe locked the owner out)
        let (st, _) = ui_state_of(
            true,
            None,
            Some(8010),
            &Root::Html,
            &TrustView::Unknown("timed out".into()),
        );
        assert_eq!(st, UiState::Ready);
        assert!(!evicts(st));
        for s in [
            UiState::Checking,
            UiState::Ready,
            UiState::ApiDown,
            UiState::NoRelease,
            UiState::NotServed,
        ] {
            assert!(!evicts(s), "{s:?}");
        }
    }

    #[test]
    fn a_held_port_that_stops_answering_is_not_responding_never_starting() {
        let t0 = Instant::now();
        let at = |s: u64| t0 + Duration::from_secs(s);
        let mut t = StallTracker::default();
        // one timeout is a blip; the second in a row makes it NOT RESPONDING since the first
        assert_eq!(t.observe(SvcProbe::Hung, at(0)), None);
        assert_eq!(t.observe(SvcProbe::Hung, at(6)), Some(at(0)));
        assert_eq!(t.observe(SvcProbe::Hung, at(12)), Some(at(0)));
        // it answers again (or dies: port closed) -> no longer not responding
        assert_eq!(t.observe(SvcProbe::Up(3.0), at(18)), None);
        assert_eq!(t.observe(SvcProbe::Hung, at(24)), None);
        assert_eq!(t.observe(SvcProbe::Refused, at(30)), None);
        assert_eq!(t.observe(SvcProbe::Hung, at(36)), None, "the count restarted");
        // the contract view stays {up:false, latency:null} for every failure
        for p in [SvcProbe::Refused, SvcProbe::Hung, SvcProbe::Failed] {
            assert_eq!(p.svc(), Svc::UNKNOWN);
        }
        assert_eq!(SvcProbe::Up(1.74).svc().latency_ms, Some(1.7));
        // the boot page's UI state: not responding is its own state (never ApiDown, never evicting)
        let un = TrustView::Unchecked;
        let (st, why) = ui_state_of(
            false,
            Some(Duration::from_secs(70)),
            Some(8010),
            &Root::Other("timed out".into()),
            &un,
        );
        assert_eq!(st, UiState::NotResponding);
        assert!(why.contains(":8010") && why.contains("1 min 10 s"), "{why}");
        assert!(!evicts(st));
        assert_eq!(
            ui_state_of(false, None, Some(8010), &Root::Html, &un).0,
            UiState::ApiDown
        );
        assert_eq!(mmss(5), "5 s");
        assert_eq!(mmss(125), "2 min 05 s");
    }

    #[test]
    fn probes_tell_hung_from_refused_from_up_on_real_sockets() {
        use std::io::{Read, Write};
        let rt = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .enable_all()
            .build()
            .unwrap();
        let hub = HealthHub::new();
        let url = |p: u16| Url::parse(&format!("http://127.0.0.1:{p}")).unwrap();
        // hung: a listener whose owner never accepts (the kernel completes the handshake: a blocked event loop)
        let hung = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let hp = hung.local_addr().unwrap().port();
        let p = rt.block_on(hub.probe_health(&url(hp), Duration::from_millis(300)));
        assert_eq!(p, SvcProbe::Hung, "port held, no answer");
        assert!(port_held(&url(hp)));
        drop(hung);
        // refused: nothing listens
        let p = rt.block_on(hub.probe_health(&url(hp), Duration::from_millis(300)));
        assert_eq!(p, SvcProbe::Refused);
        assert!(!port_held(&url(hp)));
        // up: a minimal HTTP responder
        let ok = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let op = ok.local_addr().unwrap().port();
        std::thread::spawn(move || {
            for s in ok.incoming().take(2) {
                let Ok(mut s) = s else { continue };
                let mut buf = [0u8; 1024];
                let _ = s.read(&mut buf);
                let _ = s.write_all(b"HTTP/1.1 200 OK\r\ncontent-length: 2\r\nconnection: close\r\n\r\nok");
            }
        });
        let p = rt.block_on(hub.probe_health(&url(op), Duration::from_secs(2)));
        assert!(matches!(p, SvcProbe::Up(_)), "{p:?}");
        rt.shutdown_background();
    }

    #[test]
    fn down_notifications_name_the_restart_for_a_hung_service() {
        let (t, b) = down_note(&["ui-api"], &[true], true);
        assert_eq!(t, "ui-api is not responding");
        // PM 25 Oct: say the watchdog restarts a hung ui-api (W2-OPS' rule) AND give the manual command
        assert!(
            b.contains("./start-local.sh restart ui-api")
                && b.contains("watchdog restarts a hung core service")
                && b.contains("about 3.5–5.5 min"),
            "{b}"
        );
        assert!(
            !b.contains("never restarts"),
            "the old 'never restarts' claim is gone: {b}"
        );
        assert!(!b.contains("07:45"), "ui-api has no restart-freeze caveat: {b}");
        // no watchdog agent: never promise an automatic restart
        let (_, b) = down_note(&["ui-api"], &[true], false);
        assert!(
            b.contains("not loaded, so nothing restarts it") && b.contains("./start-local.sh restart ui-api"),
            "{b}"
        );
        assert!(!b.contains("watchdog restarts a hung"), "{b}");
        let (t, b) = down_note(&["ui-api"], &[false], true);
        assert_eq!(t, "ui-api is down");
        assert!(
            b.contains("restarts stopped core services") && b.contains("reconnect banner"),
            "{b}"
        );
        let (t, b) = down_note(&["ui-api", "data-service"], &[false, true], true);
        assert_eq!(t, "2 services are down");
        assert!(
            b.contains("restart data-service") && b.contains("07:45–09:20") && b.contains("ICICI login"),
            "{b}"
        );
        let (t, _) = down_note(&["ui-api", "data-service"], &[true, true], true);
        assert_eq!(t, "2 services are not responding");
    }

    #[test]
    fn a_stuck_or_panicking_probe_is_abandoned_as_unknown() {
        let rt = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(1)
            .enable_all()
            .build()
            .unwrap();
        let t0 = Instant::now();
        // a probe blocked far beyond the limit (e.g. waiting on a privacy prompt): Unknown at the limit
        let v = rt.block_on(bounded_probe(Duration::from_millis(200), || {
            std::thread::sleep(Duration::from_secs(3));
            Ok("late".into())
        }));
        assert!(
            matches!(&v, Err(TrustFail::Unknown(m)) if m.contains("timed out")),
            "{v:?}"
        );
        assert!(
            t0.elapsed() < Duration::from_secs(2),
            "the caller was not stalled: {:?}",
            t0.elapsed()
        );
        let v = rt.block_on(bounded_probe(Duration::from_secs(2), || panic!("probe bug")));
        assert!(matches!(v, Err(TrustFail::Unknown(_))));
        let v = rt.block_on(bounded_probe(Duration::from_secs(2), || Ok("pid 1 runs Python".into())));
        assert_eq!(v, Ok("pid 1 runs Python".to_string()));
        assert_eq!(TrustView::of(&v), TrustView::Trusted("pid 1 runs Python".into()));
        rt.shutdown_background();
    }

    #[test]
    fn a_poisoned_snapshot_lock_still_returns_the_last_state() {
        let hub = HealthHub::new();
        hub.snapshot.write().unwrap().polls = 7;
        let h2 = hub.clone();
        let _ = std::thread::spawn(move || {
            let _g = h2.snapshot.write().unwrap();
            panic!("a writer panicked mid-update");
        })
        .join();
        assert!(hub.snapshot.is_poisoned());
        assert_eq!(hub.snapshot().polls, 7, "not the default 'checking…' snapshot");
    }

    #[test]
    fn trust_pins_are_replaced_by_each_pass_and_never_cleared_by_a_failure() {
        use crate::policy::ProcId;
        let a = ProcId { pid: 1, start: (10, 0) };
        let b = ProcId { pid: 2, start: (20, 0) };
        let mut p = TrustPins::default();
        assert!(p.get().is_empty());
        p.set(vec![a]);
        assert_eq!(p.get(), vec![a]);
        // a refused / inconclusive verdict pins nothing and keeps the last pass (the running ui-api)
        p.set(vec![]);
        assert_eq!(p.get(), vec![a]);
        // a restarted ui-api (new pid + start time) replaces the old pin
        p.set(vec![b]);
        assert_eq!(p.get(), vec![b]);
    }

    #[test]
    fn a_listener_swapped_between_two_polls_is_refused_at_the_next_poll() {
        // R-RUST-01: round 2 reused a pass for 30 s (TrustCache::PASS_TTL), so a squatter that bound the port
        // between two polls was served as the terminal origin. Round 3 verifies on every poll.
        let Some(t) = crate::trust::testutil::Squatter::compile() else {
            eprintln!("skipped: no C compiler (xcode-select --install)");
            return;
        };
        let rt = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(1)
            .enable_all()
            .build()
            .unwrap();
        let hub = HealthHub::new();
        // the "stack's" listener: this test process, trusted through a prefix covering the test binary
        let own = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = own.local_addr().unwrap().port();
        let cfg = Config {
            ui_url: Url::parse(&format!("http://127.0.0.1:{port}")).unwrap(),
            trusted_python_prefixes: vec![std::env::current_exe().unwrap().parent().unwrap().to_path_buf()],
            ..Config::default()
        };
        let v = rt.block_on(hub.verify_listener(&cfg));
        assert!(matches!(v, TrustView::Trusted(_)), "{v:?}");
        // swap: the trusted listener goes away, a compiled squatter (not under any trusted prefix) takes the
        // port, all within one poll interval
        drop(own);
        let _squat = t.spawn(port, false);
        let v = rt.block_on(hub.verify_listener(&cfg));
        assert!(
            matches!(&v, TrustView::Foreign(d) if d.contains("not a Homebrew")),
            "the very next verification refuses it (round 2 returned the cached pass): {v:?}"
        );
        let (st, _) = ui_state_of(true, None, Some(port), &Root::Html, &v);
        assert!(evicts(st), "open windows are pulled back: {st:?}");
        rt.shutdown_background();
    }

    #[test]
    fn definitive_refusals_win_over_every_other_state() {
        let foreign = TrustView::Foreign("pid 66 runs Helper".into());
        let unver = TrustView::Unverifiable("pid 7 executable gone".into());
        // a squatter that does not answer /health (api down) or hangs (port held): still refused
        for (up, stalled, root) in [
            (false, None, Root::Other("GET / returned HTTP 503".into())),
            (false, Some(Duration::from_secs(30)), Root::Other("timed out".into())),
            (true, None, Root::Missing),
            (true, None, Root::Html),
        ] {
            let (st, why) = ui_state_of(up, stalled, Some(8010), &root, &foreign);
            assert_eq!((st, why.as_str()), (UiState::Untrusted, "pid 66 runs Helper"));
            let (st, _) = ui_state_of(up, stalled, Some(8010), &root, &unver);
            assert_eq!(st, UiState::Unverifiable);
            assert!(evicts(st));
        }
        // control: an inconclusive verdict changes nothing (hung stays not responding, ready stays ready)
        let unk = TrustView::Unknown("vanished".into());
        assert_eq!(
            ui_state_of(
                false,
                Some(Duration::from_secs(30)),
                Some(8010),
                &Root::Other("x".into()),
                &unk
            )
            .0,
            UiState::NotResponding
        );
        assert_eq!(ui_state_of(true, None, Some(8010), &Root::Html, &unk).0, UiState::Ready);
        // what gets verified: a refused port is never probed; anything that answered or hangs is
        assert!(!port_in_use(
            SvcProbe::Refused,
            &Root::Other("connection refused".into())
        ));
        assert!(port_in_use(SvcProbe::Failed, &Root::Other("x".into())));
        assert!(port_in_use(SvcProbe::Hung, &Root::Other("timed out".into())));
        assert!(port_in_use(SvcProbe::Up(1.0), &Root::Missing));
        assert!(
            port_in_use(SvcProbe::Refused, &Root::Html),
            "GET / answered: something listens"
        );
        assert_eq!(
            TrustView::of(&Err(TrustFail::Unverifiable("x".into()))),
            TrustView::Unverifiable("x".into())
        );
    }

    #[test]
    fn icici_tracker_fires_once_on_connected_to_expired() {
        let mut t = IciciTracker::default();
        assert!(!t.observe(IciciView::Expired));
        assert!(!t.observe(IciciView::Connected));
        assert!(!t.observe(IciciView::Unknown));
        assert!(t.observe(IciciView::Expired));
        assert!(!t.observe(IciciView::Expired));
        // round 4b, P4: an ICICI outage never fires "session expired" ...
        let mut t = IciciTracker::default();
        assert!(!t.observe(IciciView::Connected));
        assert!(!t.observe(IciciView::Unreachable));
        assert!(!t.observe(IciciView::Unreachable));
        // ... and a real expiry after the outage still does (the outage says nothing about the session)
        assert!(t.observe(IciciView::Expired));
        // missing credentials are not an expiry either
        let mut t = IciciTracker::default();
        assert!(!t.observe(IciciView::Connected));
        assert!(!t.observe(IciciView::Credentials));
        assert!(!t.observe(IciciView::Expired));
    }

    #[test]
    fn tray_title_format() {
        assert_eq!(
            tray_title(Some(Nifty {
                last: 24180.5,
                change_pct: 0.4249
            })),
            "NIFTY 24,180.5 ▲0.42%"
        );
        assert_eq!(
            tray_title(Some(Nifty {
                last: 22600.0,
                change_pct: -0.39
            })),
            "NIFTY 22,600.0 ▼0.39%"
        );
        assert_eq!(
            tray_title(Some(Nifty {
                last: 999.0,
                change_pct: 0.0
            })),
            "NIFTY 999.0 •0.00%"
        );
        assert_eq!(tray_title(None), "NIFTY —");
        assert_eq!(group_thousands(1234567.891, 2), "1,234,567.89");
        assert_eq!(group_thousands(-502085.37, 0), "-502,085");
    }

    #[test]
    fn change_key_ignores_latency_and_time() {
        let mut a = ShellStatus::default();
        let mut b = a.clone();
        b.at = "later".into();
        b.ui_api.latency_ms = Some(99.0);
        assert_eq!(a.change_key(), b.change_key());
        a.ui_api.up = true;
        assert_ne!(a.change_key(), b.change_key());
    }
}
