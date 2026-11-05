//! K5 (round 3, completeness-final-02): the shell is the native notification sink for the stack's own events
//! (price alerts, filings, results, moves, closing / pre-market notes), so they appear as SuryaDhana banners
//! whatever page is open, also while every window is closed to the menu bar.
//!
//! Source: ui-api `GET /api/notifications/feed?since=<epoch ms>` (services/ui-api/routers/notifications.py,
//! F3-API). Its contract: items newest first `{id, at, at_ms, kind, title, body, source, banner, tab}` with a
//! STRING id that is stable for the life of the record; `since` is inclusive (`at_ms >= since`); the answer's
//! `next_since` is the newest `at_ms` minus a 60 s overlap (two processes write the files, a record can land a
//! few seconds after a later-stamped one), so the shell de-duplicates by id; `banner: false` marks inbox-only
//! records (wrap, journal) that never become a banner; the first call without `since` is "already seen".
//!
//! * Every [`FEED_POLL`] while the terminal is reachable AND its port listener is trusted (never from a
//!   squatter: the guard's verdict must be Trusted, or the guard off by configuration), read-only, 4 s timeout.
//!   A failing feed (an older ui-api without the endpoint) backs off to [`FEED_BACKOFF`], logged once per state.
//! * First start (no cursor file): everything the feed returns is marked seen and NOTHING is announced, so old
//!   events are never replayed. The cursor (`notify-feed.json`: `since` + the ids seen inside the overlap)
//!   survives restarts; events that happened while the app was closed are announced on the next start only
//!   when they are at most [`MAX_AGE`] old (older ones are counted in the log, never shown).
//! * Throttling and coalescing like `shell_notify`: the same app-wide limiter (20 banners a minute, shared with
//!   the pages' own notifications), at most [`MAX_PER_POLL`] banners per poll (the newest; the rest become one
//!   "N more SuryaDhana alerts" banner). Titles and bodies get the `shell_notify` validation (control and bidi
//!   characters removed, length capped).
//! * While the sink works it touches `notify-sink.alive` (config dir, at most once a minute), so the scheduler
//!   can skip its own osascript banner while the app delivers them (master_controller `_app_is_notification_sink`;
//!   osascript stays the fallback when the app is not running or the feed is not served). Round 4b: only while
//!   macOS ALLOWS SuryaDhana's notifications ([`may_claim_sink`]: with them off the app's banners go nowhere, so
//!   the scheduler's own banner must stay on), never for a poll whose banners were all throttled, and the file is
//!   removed when that stops being true and on a clean quit ([`retire_alive`]).
//! * Tolerant parsing: `events` / `notifications` are accepted for `items`, `ts` / `time` for `at`, a number
//!   for `id`; an item without an id or a time is ignored.

use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Manager};
use time::format_description::well_known::Rfc3339;
use time::OffsetDateTime;

use crate::health::{TrustView, UiState};
use crate::policy::{self, MAX_BODY_LEN, MAX_TITLE_LEN};
use crate::Shell;

/// Poll cadence while the feed answers.
pub const FEED_POLL: Duration = Duration::from_secs(15);
/// Poll cadence after [`BACKOFF_AFTER`] failed polls in a row (an older ui-api without the endpoint).
pub const FEED_BACKOFF: Duration = Duration::from_secs(60);
const BACKOFF_AFTER: u32 = 3;
/// The feed endpoint (ui-api).
pub const FEED_PATH: &str = "/api/notifications/feed";
/// Individual banners per poll; the rest are coalesced into one.
pub const MAX_PER_POLL: usize = 3;
/// Events older than this when the shell first sees them are not announced (catch-up after downtime).
pub const MAX_AGE: Duration = Duration::from_secs(30 * 60);
/// Seen ids are kept while their event is this much older than the cursor at most (the server's overlap is
/// 60 s; the margin covers a clock step).
const SEEN_KEEP_MS: i64 = 10 * 60 * 1000;
/// Seen ids kept at most (newest first).
const SEEN_MAX: usize = 1000;
/// The cursor file (config dir; the self-test's temp dir in self-test mode).
pub const CURSOR_FILE: &str = "notify-feed.json";
/// The "the app delivers the stack's notifications" heartbeat file (config dir).
pub const ALIVE_FILE: &str = "notify-sink.alive";
const ALIVE_EVERY: Duration = Duration::from_secs(60);

/// One feed event.
#[derive(Debug, Clone, PartialEq)]
pub struct FeedItem {
    pub id: String,
    pub at_ms: i64,
    pub kind: String,
    pub title: String,
    pub body: String,
    /// false for inbox-only records (wrap, journal): marked seen, never a banner.
    pub banner: bool,
}

/// One feed answer.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct FeedPage {
    pub items: Vec<FeedItem>,
    /// The `since` for the next poll (the server's newest `at_ms` minus its overlap).
    pub next_since: Option<i64>,
    /// The server's clock (epoch ms).
    pub server_ms: Option<i64>,
}

fn str_of<'a>(o: &'a serde_json::Map<String, Value>, keys: &[&str]) -> Option<&'a str> {
    keys.iter().find_map(|k| o.get(*k).and_then(Value::as_str))
}

fn ms_of(v: Option<&Value>) -> Option<i64> {
    v.and_then(|v| v.as_i64().or_else(|| v.as_f64().map(|f| f as i64)))
}

/// Pure: parse a feed answer (None when it is not a feed at all).
pub fn parse_feed(v: &Value) -> Option<FeedPage> {
    let o = v.as_object()?;
    let arr = ["items", "events", "notifications"]
        .iter()
        .find_map(|k| o.get(*k).and_then(Value::as_array))?;
    let items = arr
        .iter()
        .filter_map(|it| {
            let it = it.as_object()?;
            let id = match it.get("id")? {
                Value::String(s) if !s.trim().is_empty() && s.len() <= 128 => s.trim().to_string(),
                Value::Number(n) => n.to_string(),
                _ => return None,
            };
            let at_ms = ms_of(it.get("at_ms")).or_else(|| {
                str_of(it, &["at", "ts", "time"])
                    .and_then(|s| OffsetDateTime::parse(s.trim(), &Rfc3339).ok())
                    .map(|t| (t.unix_timestamp_nanos() / 1_000_000) as i64)
            })?;
            Some(FeedItem {
                id,
                at_ms,
                kind: str_of(it, &["kind", "type"]).unwrap_or("alert").to_string(),
                title: str_of(it, &["title"]).unwrap_or("").to_string(),
                body: str_of(it, &["body", "message"]).unwrap_or("").to_string(),
                banner: it.get("banner").and_then(Value::as_bool).unwrap_or(true),
            })
        })
        .collect();
    Some(FeedPage {
        items,
        next_since: ms_of(o.get("next_since")),
        server_ms: ms_of(o.get("server_time_ms")),
    })
}

/// The persisted cursor: where to read from, and the ids already seen inside the server's overlap.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct Cursor {
    /// `since` for the next poll (epoch ms).
    #[serde(default)]
    pub since: Option<i64>,
    /// (id, at_ms) of events already handled, newest first, bounded.
    #[serde(default)]
    pub seen: Vec<(String, i64)>,
    #[serde(default)]
    pub updated: String,
}

impl Cursor {
    /// None when there is no (readable) cursor: a first start.
    pub fn load(path: &Path) -> Option<Cursor> {
        let text = std::fs::read_to_string(path).ok()?;
        serde_json::from_str::<Cursor>(&text).ok().filter(|c| c.since.is_some())
    }

    pub fn save(&self, path: &Path) -> std::io::Result<()> {
        crate::config::write_atomic(path, &(serde_json::to_string(self).unwrap_or_default() + "\n"))
    }

    /// Was the event with this id handled already?
    pub fn has(&self, id: &str) -> bool {
        self.seen.iter().any(|(s, _)| s == id)
    }
}

/// What one poll announces.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Plan {
    /// Individual banners, oldest first.
    pub post: Vec<FeedItem>,
    /// New events folded into one summary banner (titles, oldest first).
    pub coalesced: Vec<String>,
    /// New events older than [`MAX_AGE`] (never shown).
    pub skipped_old: usize,
    /// New inbox-only events (`banner: false`; never shown).
    pub skipped_inbox: usize,
    /// The cursor after this poll (None: forget it, the next poll re-baselines without announcing).
    pub cursor: Option<Cursor>,
    /// The server's clock is far behind the cursor (clock stepped back, data restored): re-baseline.
    pub reset: bool,
}

fn merged_cursor(old: Option<&Cursor>, page: &FeedPage) -> Cursor {
    let since = match (old.and_then(|c| c.since), page.next_since) {
        (Some(a), Some(b)) => Some(a.max(b)),
        (a, b) => b.or(a),
    };
    let mut seen: Vec<(String, i64)> = page.items.iter().map(|i| (i.id.clone(), i.at_ms)).collect();
    if let Some(c) = old {
        for (id, at) in &c.seen {
            if !seen.iter().any(|(s, _)| s == id) {
                seen.push((id.clone(), *at));
            }
        }
    }
    let floor = since.unwrap_or(i64::MIN).saturating_sub(SEEN_KEEP_MS);
    seen.retain(|(_, at)| *at >= floor);
    seen.sort_by(|a, b| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0)));
    seen.truncate(SEEN_MAX);
    Cursor {
        since,
        seen,
        updated: String::new(),
    }
}

/// Pure: decide what to announce for `page` given the stored cursor (None = first start) at `now_ms`.
pub fn plan(page: &FeedPage, cursor: Option<&Cursor>, now_ms: i64) -> Plan {
    let Some(old) = cursor else {
        // first start: everything returned counts as seen, nothing is announced (never replay old events)
        return Plan {
            cursor: Some(merged_cursor(None, page)),
            ..Plan::default()
        };
    };
    let server_now = page.server_ms.unwrap_or(now_ms);
    if old.since.map(|s| server_now + 120_000 < s).unwrap_or(false) {
        return Plan {
            reset: true,
            cursor: None,
            ..Plan::default()
        };
    }
    let mut fresh: Vec<&FeedItem> = page.items.iter().filter(|i| !old.has(&i.id)).collect();
    fresh.sort_by(|a, b| a.at_ms.cmp(&b.at_ms).then_with(|| a.id.cmp(&b.id)));
    fresh.dedup_by(|a, b| a.id == b.id);
    let max_age = MAX_AGE.as_millis() as i64;
    let mut out = Plan {
        cursor: Some(merged_cursor(Some(old), page)),
        ..Plan::default()
    };
    let mut recent = vec![];
    for i in fresh {
        if !i.banner {
            out.skipped_inbox += 1;
        } else if server_now - i.at_ms > max_age {
            out.skipped_old += 1;
        } else {
            recent.push(i);
        }
    }
    if recent.len() <= MAX_PER_POLL {
        out.post = recent.into_iter().cloned().collect();
    } else {
        // the newest MAX_PER_POLL - 1 individually, everything before them in one summary banner
        let split = recent.len() - (MAX_PER_POLL - 1);
        out.coalesced = recent[..split].iter().map(|i| i.title.clone()).collect();
        out.post = recent[split..].iter().map(|i| (*i).clone()).collect();
    }
    out
}

/// Pure: `text` cut to `max` characters (an ellipsis marks the cut).
pub fn clip(text: &str, max: usize) -> String {
    if text.chars().count() <= max {
        return text.to_string();
    }
    let mut s: String = text.chars().take(max.saturating_sub(1)).collect();
    s.push('…');
    s
}

/// Pure: the banner (title, body) for one event, with `shell_notify`'s validation applied.
pub fn banner(item: &FeedItem) -> (String, String) {
    let title = if item.title.trim().is_empty() {
        format!("SuryaDhana {}", item.kind)
    } else {
        item.title.clone()
    };
    let title = policy::validate_plain_text(&clip(&title, MAX_TITLE_LEN), MAX_TITLE_LEN, "title").unwrap_or_default();
    let body = policy::validate_body_text(&clip(&item.body, MAX_BODY_LEN), MAX_BODY_LEN).unwrap_or_default();
    (title, body)
}

/// Pure: the summary banner for coalesced events.
pub fn summary_banner(titles: &[String]) -> (String, String) {
    let n = titles.len();
    let title = format!("{n} more SuryaDhana alert{}", if n == 1 { "" } else { "s" });
    let list: Vec<String> = titles
        .iter()
        .map(|t| clip(t.trim(), 60))
        .filter(|t| !t.is_empty())
        .collect();
    let body = policy::validate_body_text(&clip(&list.join(" · "), 400), MAX_BODY_LEN).unwrap_or_default();
    (title, body)
}

/// Pure: may the shell read the feed now? Only from a reachable terminal whose port listener is trusted (or
/// whose guard is off by configuration): a squatter must never be able to post SuryaDhana banners.
pub fn may_poll(ui_state: UiState, trust: &TrustView) -> bool {
    ui_state == UiState::Ready && matches!(trust, TrustView::Trusted(_) | TrustView::Off)
}

/// Where the feed state lives.
#[derive(Debug, Clone)]
pub struct FeedPaths {
    pub cursor: PathBuf,
    /// None in self-test (the scheduler must never see a self-test as the sink).
    pub alive: Option<PathBuf>,
}

/// Announce one poll's plan (shared limiter with `shell_notify`). Returns how many banners went out.
fn announce(app: &AppHandle, shell: &Shell, p: &Plan) -> usize {
    let mut shown = 0;
    let mut banners: Vec<(String, String)> = vec![];
    if !p.coalesced.is_empty() {
        banners.push(summary_banner(&p.coalesced));
    }
    banners.extend(p.post.iter().map(banner));
    for (title, body) in banners {
        if title.is_empty() {
            continue;
        }
        let allowed = shell
            .ui_notify_limiter
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .allow(Instant::now());
        if !allowed {
            log::info!("[feed] banner throttled (20 a minute, shared with the pages): {title}");
            continue;
        }
        shell.notify(app, &title, &body);
        shown += 1;
    }
    shown
}

/// Pure (round 4b): may this poll claim "the app delivers the stack's banners" (touch `notify-sink.alive`)? Only
/// while macOS reports the app's notifications as allowed (`auth` = the last read; unknown = no), and not when
/// this poll had banners to show and the shared limiter let none of them out.
pub fn may_claim_sink(auth: Option<crate::macos::NotifAuth>, wanted: usize, shown: usize) -> bool {
    auth == Some(crate::macos::NotifAuth::Authorized) && !(wanted > 0 && shown == 0)
}

/// Remove the sink heartbeat (round 4b): the scheduler's own banner applies again at once.
pub fn retire_alive(path: &Path) {
    match std::fs::remove_file(path) {
        Ok(()) => log::info!("[feed] no longer the banner sink: removed {}", path.display()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
        Err(e) => log::debug!("[feed] could not remove {}: {e}", path.display()),
    }
}

fn touch_alive(path: &Path) {
    let text = format!(
        "{{\"pid\":{},\"at\":\"{}\"}}\n",
        std::process::id(),
        crate::health::now_iso()
    );
    if let Err(e) = crate::config::write_atomic(path, &text) {
        log::debug!("[feed] could not write {}: {e}", path.display());
    }
}

fn now_ms() -> i64 {
    (OffsetDateTime::now_utc().unix_timestamp_nanos() / 1_000_000) as i64
}

/// Start the feed poller (runs for the app's lifetime).
pub fn spawn(app: AppHandle, paths: FeedPaths) {
    tauri::async_runtime::spawn(async move {
        let mut state = PollState {
            cursor: Cursor::load(&paths.cursor),
            ..PollState::default()
        };
        if state.cursor.is_none() {
            log::info!(
                "[feed] first start: the stack's notification feed is followed from now on (nothing old is replayed)"
            );
        }
        tokio::time::sleep(Duration::from_secs(2)).await;
        loop {
            let wait = poll_once(&app, &paths, &mut state).await;
            tokio::time::sleep(wait).await;
        }
    });
}

#[derive(Debug, Default)]
struct PollState {
    cursor: Option<Cursor>,
    failures: u32,
    last_state: Option<String>,
    alive_at: Option<Instant>,
    /// The heartbeat was removed because notifications are not allowed (removed once, not every poll).
    retired: bool,
}

async fn poll_once(app: &AppHandle, paths: &FeedPaths, st: &mut PollState) -> Duration {
    let shell = app.state::<Shell>();
    let snap = shell.health.snapshot();
    if !may_poll(snap.ui_state, &snap.trust) {
        return Duration::from_secs(5);
    }
    let Ok(mut url) = shell.cfg.ui_url.join(FEED_PATH) else {
        return FEED_BACKOFF;
    };
    if let Some(since) = st.cursor.as_ref().and_then(|c| c.since) {
        url.query_pairs_mut().append_pair("since", &since.to_string());
    }
    let res = shell.health.get_json_status(&url, Duration::from_secs(4)).await;
    let page = match &res {
        Ok((200, Some(v))) => parse_feed(v),
        _ => None,
    };
    let Some(page) = page else {
        st.failures += 1;
        let state = match res {
            Ok((code, _)) => format!("HTTP {code}"),
            Err(e) => e.describe().to_string(),
        };
        if st.last_state.as_deref() != Some(state.as_str()) {
            log::warn!("[feed] {FEED_PATH} unavailable ({state}); retrying (the in-page inbox still has every event)");
            st.last_state = Some(state);
        }
        return if st.failures >= BACKOFF_AFTER {
            FEED_BACKOFF
        } else {
            FEED_POLL
        };
    };
    if st.last_state.as_deref() != Some("ok") {
        log::info!("[feed] following {FEED_PATH} (every {} s)", FEED_POLL.as_secs());
        st.last_state = Some("ok".into());
    }
    st.failures = 0;
    let p = plan(&page, st.cursor.as_ref(), now_ms());
    let wanted = p.post.len() + usize::from(!p.coalesced.is_empty());
    let shown = announce(app, &shell, &p);
    if shown > 0 || p.skipped_old > 0 || p.reset {
        log::info!(
            "[feed] {shown} banner(s) for {} new event(s){}{}{}",
            p.post.len() + p.coalesced.len(),
            if p.skipped_old > 0 {
                format!(
                    "; {} older than {} min not shown",
                    p.skipped_old,
                    MAX_AGE.as_secs() / 60
                )
            } else {
                String::new()
            },
            if p.skipped_inbox > 0 {
                format!("; {} inbox-only", p.skipped_inbox)
            } else {
                String::new()
            },
            if p.reset {
                "; the server's clock is behind the cursor: re-baselining"
            } else {
                ""
            }
        );
    }
    let changed = match (&p.cursor, &st.cursor) {
        (Some(a), Some(b)) => a.since != b.since || a.seen != b.seen,
        (None, None) => false,
        _ => true,
    };
    if changed {
        match &p.cursor {
            Some(c) => {
                let mut c = c.clone();
                c.updated = crate::health::now_iso();
                if let Err(e) = c.save(&paths.cursor) {
                    log::warn!("[feed] could not save the cursor {}: {e}", paths.cursor.display());
                }
                st.cursor = Some(c);
            }
            None => {
                let _ = std::fs::remove_file(&paths.cursor);
                st.cursor = None;
            }
        }
    }
    if let Some(alive) = &paths.alive {
        let auth = *shell.notif_auth.lock().unwrap_or_else(|e| e.into_inner());
        if may_claim_sink(auth, wanted, shown) {
            if st.alive_at.map(|t| t.elapsed() >= ALIVE_EVERY).unwrap_or(true) {
                touch_alive(alive);
                st.alive_at = Some(Instant::now());
            }
        } else if auth != Some(crate::macos::NotifAuth::Authorized) && (st.alive_at.is_some() || !st.retired) {
            // notifications off (or not known to be on): this app cannot show the banners, so it must not keep
            // the scheduler's own banner switched off
            retire_alive(alive);
            st.alive_at = None;
            st.retired = true;
        }
    }
    FEED_POLL
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const NOW: i64 = 1_792_993_200_000; // Mon 26 Oct 2026 11:10 IST

    fn item(id: &str, at_ms: i64, title: &str) -> Value {
        json!({"id": id, "at": "2026-10-26T11:00:00+05:30", "at_ms": at_ms, "kind": "price", "title": title,
               "body": "b", "source": "scheduler", "banner": true, "tab": "watch"})
    }

    fn page(items: Vec<Value>, next_since: i64) -> FeedPage {
        parse_feed(&json!({"items": items, "count": 0, "truncated": false, "since": null,
                           "next_since": next_since, "server_time_ms": NOW}))
        .unwrap()
    }

    #[test]
    fn parses_the_f3_api_contract_and_tolerates_variants() {
        let v = json!({"items": [item("h-0123456789abcdef", NOW - 5_000, "SuryaDhana price alert"),
                                 {"id": 7, "ts": "2026-10-26T11:01:00+05:30", "type": "filing", "title": "INFY", "message": "m"},
                                 {"id": "n-x", "kind": "wrap", "title": "Market wrap", "body": "w", "at_ms": NOW, "banner": false},
                                 {"title": "no id: ignored", "at_ms": NOW},
                                 {"id": "n-no-time", "title": "no time: ignored"}],
                       "next_since": NOW - 65_000, "server_time_ms": NOW});
        let p = parse_feed(&v).unwrap();
        assert_eq!(p.items.len(), 3);
        assert_eq!(p.items[0].id, "h-0123456789abcdef");
        assert_eq!(p.items[1].id, "7");
        assert_eq!(p.items[1].at_ms, 1_792_992_660_000, "11:01 IST from the RFC 3339 time");
        assert_eq!((p.items[1].kind.as_str(), p.items[1].body.as_str()), ("filing", "m"));
        assert!(!p.items[2].banner);
        assert_eq!((p.next_since, p.server_ms), (Some(NOW - 65_000), Some(NOW)));
        assert!(parse_feed(&json!({"detail": "Not Found"})).is_none());
        assert!(parse_feed(&json!([1, 2])).is_none());
    }

    /// A real answer of ui-api's routers/notifications.py (F3-API, 25 Oct; 3 items, bodies cut).
    const F3_API_SAMPLE: &str = r#"{"items": [{"id": "n-b945edc0c5f0c83b", "at": "2026-10-23T21:00:07+05:30", "at_ms": 1792769407000, "kind": "wrap", "title": "Market wrap 2026-10-23", "body": "NIFTY -0.39% · breadth 147/1,255 · FII +", "source": "scheduler", "banner": false, "tab": "wrap"}, {"id": "n-8dc013bff1ddeb22", "at": "2026-10-23T20:10:00+05:30", "at_ms": 1792766400000, "kind": "journal", "title": "Weekly journal 2026-W43", "body": "Weekly decision journal — 2026-W43 (19 O", "source": "scheduler", "banner": false, "tab": "alerts"}, {"id": "n-5c42c1a27761c5b7", "at": "2026-10-23T15:40:01+05:30", "at_ms": 1792750201000, "kind": "close", "title": "SuryaDhana · closing note", "body": "NIFTY 22,600 (-0.39%) · NIFTY 500 breadt", "source": "scheduler", "banner": true, "tab": "brief"}], "count": 5, "truncated": true, "since": null, "next_since": 1792769347000, "server_time_ms": 1792930668462}"#;

    #[test]
    fn the_real_f3_api_answer_parses_and_a_first_start_shows_nothing() {
        let v: Value = serde_json::from_str(F3_API_SAMPLE).unwrap();
        let p = parse_feed(&v).unwrap();
        assert_eq!(p.items.len(), 3);
        assert!(p
            .items
            .iter()
            .all(|i| i.id.starts_with("n-") && i.at_ms > 1_700_000_000_000));
        assert_eq!(
            p.items.iter().map(|i| i.banner).collect::<Vec<_>>(),
            vec![false, false, true],
            "wrap and journal are inbox-only"
        );
        assert!(p.next_since.is_some() && p.server_ms.is_some());
        let plan0 = plan(&p, None, p.server_ms.unwrap());
        assert!(plan0.post.is_empty());
        let c = plan0.cursor.unwrap();
        assert_eq!(c.since, p.next_since);
        // the same answer again (inclusive since + overlap): nothing new
        assert!(plan(&p, Some(&c), p.server_ms.unwrap()).post.is_empty());
    }

    #[test]
    fn first_start_never_replays_and_the_overlap_never_repeats_a_banner() {
        // first start: two events (one of them just now) are only marked seen
        let first = page(
            vec![
                item("n-a", NOW - 3_600_000, "old"),
                item("n-b", NOW - 10_000, "just now"),
            ],
            NOW - 70_000,
        );
        let p = plan(&first, None, NOW);
        assert!(p.post.is_empty() && p.coalesced.is_empty(), "{p:?}");
        let c = p.cursor.unwrap();
        assert_eq!(c.since, Some(NOW - 70_000));
        assert!(c.has("n-b"));
        // the next poll (since = NOW - 70 s, inclusive) returns n-b again (overlap) plus a new event: only the new
        // one is announced
        let next = page(
            vec![
                item("n-c", NOW + 5_000, "TCS above 4,000"),
                item("n-b", NOW - 10_000, "just now"),
            ],
            NOW - 55_000,
        );
        let p = plan(&next, Some(&c), NOW + 6_000);
        assert_eq!(p.post.iter().map(|i| i.id.as_str()).collect::<Vec<_>>(), vec!["n-c"]);
        let c2 = p.cursor.unwrap();
        assert_eq!(c2.since, Some(NOW - 55_000));
        // and the poll after that (same overlap) announces nothing
        let p = plan(&next, Some(&c2), NOW + 20_000);
        assert!(p.post.is_empty(), "{p:?}");
        // the cursor file round trip (a restart resumes from it)
        let dir = tempfile::tempdir().unwrap();
        let f = dir.path().join(CURSOR_FILE);
        assert_eq!(Cursor::load(&f), None);
        c2.save(&f).unwrap();
        assert_eq!(Cursor::load(&f).unwrap().since, Some(NOW - 55_000));
        assert!(Cursor::load(&f).unwrap().has("n-c"));
        std::fs::write(&f, "{broken").unwrap();
        assert_eq!(
            Cursor::load(&f),
            None,
            "an unreadable cursor is a first start (never a replay)"
        );
        // an empty first answer still yields a cursor once the server says where it is
        let empty = page(vec![], NOW);
        assert_eq!(plan(&empty, None, NOW).cursor.unwrap().since, Some(NOW));
    }

    #[test]
    fn catch_up_skips_old_and_inbox_only_events_and_coalesces_bursts() {
        let c = Cursor {
            since: Some(NOW - 12 * 3_600_000),
            seen: vec![],
            updated: String::new(),
        };
        // the app was closed overnight: last night's events are older than 30 min; the wrap is inbox-only
        let mut wrap = item("n-wrap", NOW - 60_000, "Market wrap");
        wrap["banner"] = json!(false);
        let p = plan(
            &page(
                vec![
                    item("n-1", NOW - 11 * 3_600_000, "pre-open"),
                    wrap,
                    item("n-2", NOW - 300_000, "TCS above 4,000"),
                ],
                NOW - 120_000,
            ),
            Some(&c),
            NOW,
        );
        assert_eq!((p.skipped_old, p.skipped_inbox), (1, 1));
        assert_eq!(p.post.iter().map(|i| i.id.as_str()).collect::<Vec<_>>(), vec!["n-2"]);
        // a burst of 7 alerts in one poll: the newest 2 individually, the other 5 in one summary banner
        let items: Vec<Value> = (1..=7)
            .map(|i| item(&format!("h-{i}"), NOW - 60_000 + i * 1000, &format!("alert {i}")))
            .collect();
        let p = plan(&page(items, NOW), Some(&c), NOW);
        assert_eq!(
            p.post.iter().map(|i| i.id.as_str()).collect::<Vec<_>>(),
            vec!["h-6", "h-7"]
        );
        assert_eq!(p.coalesced.len(), 5);
        assert!(p.post.len() + usize::from(!p.coalesced.is_empty()) <= MAX_PER_POLL);
        let (t, b) = summary_banner(&p.coalesced);
        assert_eq!(t, "5 more SuryaDhana alerts");
        assert!(b.starts_with("alert 1 · alert 2"), "{b}");
        // the server's clock is far behind the cursor (stepped back / data restored): forget the cursor, the next
        // poll re-baselines without announcing anything
        let future = Cursor {
            since: Some(NOW + 3_600_000),
            ..c.clone()
        };
        let p = plan(&page(vec![item("x", NOW, "x")], NOW), Some(&future), NOW);
        assert!(p.reset && p.cursor.is_none() && p.post.is_empty(), "{p:?}");
        // duplicates in one answer are announced once
        let dup = page(vec![item("d", NOW, "a"), item("d", NOW, "a")], NOW);
        assert_eq!(plan(&dup, Some(&c), NOW).post.len(), 1);
    }

    #[test]
    fn the_seen_set_is_bounded_by_time_and_count() {
        let old: Vec<(String, i64)> = (0..5000).map(|i| (format!("o-{i}"), NOW - 3_600_000 - i)).collect();
        let c = Cursor {
            since: Some(NOW - 3_600_000),
            seen: old,
            updated: String::new(),
        };
        let p = plan(&page(vec![item("n", NOW, "n")], NOW - 60_000), Some(&c), NOW);
        let c = p.cursor.unwrap();
        assert!(c.seen.len() <= SEEN_MAX, "{}", c.seen.len());
        assert!(c.has("n"), "the newest are kept");
        assert!(
            c.seen.iter().all(|(_, at)| *at >= NOW - 60_000 - SEEN_KEEP_MS),
            "ids far older than the cursor are dropped"
        );
    }

    #[test]
    fn banners_get_shell_notify_validation_and_only_trusted_ports_are_read() {
        let it = FeedItem {
            id: "x".into(),
            at_ms: NOW,
            kind: "price".into(),
            title: format!("TCS\u{202e}above{}", "x".repeat(300)),
            body: "line1\nline2\u{0007}".into(),
            banner: true,
        };
        let (t, b) = banner(&it);
        assert!(t.chars().count() <= MAX_TITLE_LEN && !t.contains('\u{202e}'), "{t}");
        assert!(t.ends_with('…'));
        assert_eq!(b, "line1\nline2");
        let (t, _) = banner(&FeedItem {
            title: "  ".into(),
            ..it.clone()
        });
        assert_eq!(t, "SuryaDhana price");
        // a squatter (refused / unverifiable / inconclusive) or an unreachable terminal is never read
        assert!(may_poll(UiState::Ready, &TrustView::Trusted("pid 1".into())));
        assert!(may_poll(UiState::Ready, &TrustView::Off));
        assert!(!may_poll(UiState::Ready, &TrustView::Unknown("x".into())));
        assert!(!may_poll(UiState::Untrusted, &TrustView::Foreign("x".into())));
        assert!(!may_poll(UiState::Unverifiable, &TrustView::Unverifiable("x".into())));
        assert!(!may_poll(UiState::ApiDown, &TrustView::Unchecked));
        assert_eq!(clip("abc", 3), "abc");
        assert_eq!(clip("abcd", 3), "ab…");
    }

    #[test]
    fn the_sink_is_claimed_only_while_banners_can_show() {
        use crate::macos::NotifAuth;
        // round 4b (round-3 check, minor): with SuryaDhana's notifications off the app shows nothing, so it must
        // not tell the scheduler to drop its own banner
        assert!(
            may_claim_sink(Some(NotifAuth::Authorized), 0, 0),
            "a quiet poll keeps the claim"
        );
        assert!(may_claim_sink(Some(NotifAuth::Authorized), 2, 1));
        assert!(!may_claim_sink(Some(NotifAuth::Denied), 0, 0));
        assert!(!may_claim_sink(Some(NotifAuth::NotDetermined), 0, 0));
        assert!(!may_claim_sink(None, 0, 0), "unknown is not 'allowed'");
        assert!(
            !may_claim_sink(Some(NotifAuth::Authorized), 3, 0),
            "every banner throttled"
        );
        // retire_alive removes the file and tolerates a missing one
        let dir = tempfile::tempdir().unwrap();
        let f = dir.path().join(ALIVE_FILE);
        touch_alive(&f);
        assert!(f.exists());
        retire_alive(&f);
        assert!(!f.exists());
        retire_alive(&f);
    }
}
