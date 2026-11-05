//! Menu-bar item: template sun icon + live NIFTY title, and a status/action menu.
//!
//! ```text
//!  ☀ NIFTY 22,600.0 ▼0.39% · closed     (live: no suffix; data-service down / frozen quote: "NIFTY — stale")
//!    ui-api :8010 — up, 2 ms           (disabled status lines)
//!    data-service :8001 — up, 1 ms
//!    master-controller :8008 — up, 1 ms
//!    ICICI — expired: send /login in Telegram   (round 4b: "ICICI — unreachable (network)" during an outage)
//!    Desk NAV ₹5,02,085  +0.42%
//!    UI build 20261024-…               (or: no UI release — ./start-local.sh build-ui; "· port not verified")
//!    Notifications are off — System Settings › Notifications › SuryaDhana   (only while macOS has them off;
//!                                      a click opens that pane, nothing else ever does)
//!    ─────────
//!    Open Terminal · New Window · Go ▸ · Show Latest Download · ─ · Start Stack (disabled while all 3 are
//!    up) · Stop Stack… · Open Logs · Launch at Login ✓ · Relaunch after a crash: on (login item | crash
//!    guard) / off (why) · ─ · SuryaDhana 1.0.0 · <build id> · Quit
//! ```

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tauri::image::Image;

use tauri::menu::{CheckMenuItem, CheckMenuItemBuilder, Menu, MenuBuilder, MenuItem, MenuItemBuilder, SubmenuBuilder};
use tauri::tray::{TrayIcon, TrayIconBuilder};
use tauri::{AppHandle, Wry};

use crate::autostart;
use crate::health::{group_thousands, tray_title_for, Desk, IciciView, QuoteState, Snapshot, Svc, TrustView, UiState};
use crate::pages;

/// Tray icon id.
pub const TRAY_ID: &str = "suryadhana";

/// The tray's notification hint (round 4b): shown only while macOS reports SuryaDhana's notifications as denied.
pub const NOTIF_HINT_TEXT: &str = "Notifications are off — System Settings › Notifications › SuryaDhana";
/// Where the hint goes: right after the six status lines (ui-api, data-service, master-controller, ICICI, Desk,
/// UI build).
pub const NOTIF_HINT_POS: usize = 6;

/// Handles to update the tray in place. Cheap to clone (every handle is reference-counted): callers clone
/// them out of `Shell::tray` and drop the lock BEFORE touching the menu, because a menu/tray call from a
/// non-main thread blocks until the main thread runs it, and the main thread may be waiting for that lock.
#[derive(Clone)]
pub struct TrayHandles {
    pub tray: TrayIcon<Wry>,
    pub ui: MenuItem<Wry>,
    pub ds: MenuItem<Wry>,
    pub mc: MenuItem<Wry>,
    pub icici: MenuItem<Wry>,
    pub desk: MenuItem<Wry>,
    pub build: MenuItem<Wry>,
    pub autostart: CheckMenuItem<Wry>,
    /// Round 3: who relaunches this copy after a crash (login item / crash guard / off, and why).
    pub supervision: MenuItem<Wry>,
    pub start: MenuItem<Wry>,
    pub latest_download: MenuItem<Wry>,
    /// The title last set (shared by clones).
    pub last_title: std::sync::Arc<std::sync::Mutex<String>>,
    /// Round 4b: the tray menu itself (the notification hint is inserted / removed), the hint item, and whether
    /// it is in the menu now (shared by clones).
    pub menu: Menu<Wry>,
    pub notif_hint: MenuItem<Wry>,
    pub notif_hint_shown: Arc<AtomicBool>,
}

fn status_line(app: &AppHandle, id: &str) -> tauri::Result<MenuItem<Wry>> {
    MenuItemBuilder::with_id(format!("tray:status:{id}"), "…")
        .enabled(false)
        .build(app)
}

/// Build the tray. The icon is a monochrome template (macOS recolours it for the menu bar theme).
pub fn build(app: &AppHandle, autostart: autostart::State, show_title: bool) -> tauri::Result<TrayHandles> {
    let ui = status_line(app, "ui")?;
    let ds = status_line(app, "ds")?;
    let mc = status_line(app, "mc")?;
    let icici = status_line(app, "icici")?;
    let desk = status_line(app, "desk")?;
    let build = status_line(app, "build")?;
    let autostart_item = CheckMenuItemBuilder::with_id("tray:app:autostart", autostart.menu_text())
        .checked(autostart.checked())
        .build(app)?;
    let supervision = status_line(app, "supervision")?;
    let start = MenuItemBuilder::with_id("tray:stack:start", "Start Stack").build(app)?;
    let latest_download = MenuItemBuilder::with_id("tray:app:latest-download", "Show Latest Download")
        .enabled(false)
        .build(app)?;
    // enabled: a click on it (and only that) opens System Settings › Notifications at SuryaDhana
    let notif_hint = MenuItemBuilder::with_id("tray:app:notification-settings", NOTIF_HINT_TEXT).build(app)?;

    let mut go = SubmenuBuilder::new(app, "Go");
    for id in pages::TRAY_PAGES {
        if let Some(p) = pages::by_id(id) {
            go = go.text(format!("tray:go:{}", p.id), format!("{}  ·  {}", p.code, p.label));
        }
    }
    let go = go.build()?;

    let menu = MenuBuilder::new(app)
        .items(&[&ui, &ds, &mc, &icici, &desk, &build])
        .separator()
        .item(&MenuItemBuilder::with_id("tray:app:open-terminal", "Open Terminal").build(app)?)
        .item(&MenuItemBuilder::with_id("tray:app:new-window", "New Window").build(app)?)
        .item(&go)
        .item(&latest_download)
        .separator()
        .item(&start)
        .item(&MenuItemBuilder::with_id("tray:stack:stop", "Stop Stack…").build(app)?)
        .item(&MenuItemBuilder::with_id("tray:help:stack-logs", "Open Logs").build(app)?)
        .item(&autostart_item)
        .item(&supervision)
        .separator()
        .item(
            &MenuItemBuilder::with_id("tray:status:version", version_line())
                .enabled(false)
                .build(app)?,
        )
        .item(&MenuItemBuilder::with_id("tray:app:quit", "Quit SuryaDhana").build(app)?)
        .build()?;

    let icon = Image::from_bytes(include_bytes!("../icons/tray/tray-icon@2x.png"))?;
    let title = if show_title {
        tray_title_for(None, QuoteState::None)
    } else {
        String::new()
    };
    let tray = TrayIconBuilder::with_id(TRAY_ID)
        .icon(icon)
        .icon_as_template(true)
        .title(&title)
        .tooltip("SuryaDhana Terminal")
        .menu(&menu)
        .show_menu_on_left_click(true)
        .build(app)?;
    let handles = TrayHandles {
        tray,
        ui,
        ds,
        mc,
        icici,
        desk,
        build,
        autostart: autostart_item,
        supervision,
        start,
        latest_download,
        last_title: std::sync::Arc::new(std::sync::Mutex::new(title)),
        menu,
        notif_hint,
        notif_hint_shown: Arc::new(AtomicBool::new(false)),
    };
    Ok(handles)
}

/// Pure: should the notification hint be in the menu? Only for a definite "denied" (None = unknown: a timed-out
/// or unavailable check changes nothing, so the line never flickers).
pub fn notif_hint_wanted(auth: Option<crate::macos::NotifAuth>, shown: bool) -> bool {
    match auth {
        Some(a) => a == crate::macos::NotifAuth::Denied,
        None => shown,
    }
}

/// Show or remove the notification hint line (round 4b). A passive menu line, never a dialog or a banner:
/// macOS cannot show a banner to say banners are off, and System Settings opens only on a click of the line.
pub fn set_notif_hint(h: &TrayHandles, on: bool) {
    if h.notif_hint_shown.load(Ordering::SeqCst) == on {
        return;
    }
    let res = if on {
        h.menu.insert(&h.notif_hint, NOTIF_HINT_POS)
    } else {
        h.menu.remove(&h.notif_hint)
    };
    match res {
        Ok(()) => h.notif_hint_shown.store(on, Ordering::SeqCst),
        Err(e) => log::warn!("[tray] notification hint: {e}"),
    }
}

/// `● ui-api :8010 — up, 2 ms` / `○ ui-api :8010 — DOWN` / `○ ui-api :8010 — stopped (paused)` /
/// `◌ ui-api :8010 — NOT RESPONDING (port held, no /health answer)`.
/// No space padding: the menu font is proportional, so aligned columns never line up.
pub fn svc_line(name: &str, port: Option<u16>, s: &Svc, paused: bool, stalled: bool) -> String {
    let port = port.map(|p| format!(" :{p}")).unwrap_or_default();
    match (s.up, s.latency_ms) {
        (true, Some(ms)) => format!("● {name}{port} — up, {ms:.0} ms"),
        (true, None) => format!("● {name}{port} — up"),
        (false, _) if stalled => format!("◌ {name}{port} — NOT RESPONDING (port held, no /health answer)"),
        (false, _) if paused => format!("○ {name}{port} — stopped (paused)"),
        (false, _) => format!("○ {name}{port} — DOWN"),
    }
}

/// Pure: Start Stack can help only when a service is down and NOT merely hung (a hung one holds its port, so
/// `start-local.sh start` skips it; the watchdog's hang rule or `./start-local.sh restart <svc>` recovers it).
pub fn start_useful(up: [bool; 3], stalled: [bool; 3]) -> bool {
    up.iter().zip(stalled).any(|(u, h)| !u && !h)
}

pub fn icici_line(i: IciciView) -> String {
    match i {
        IciciView::Connected => "ICICI — connected".into(),
        IciciView::Expired => "ICICI — expired: send /login in Telegram".into(),
        // round 4b, P4: an ICICI outage is not a login problem (ui-api retries by itself)
        IciciView::Unreachable => "ICICI — unreachable (network)".into(),
        IciciView::Credentials => "ICICI — API key/secret missing or rejected: fix on BRKR".into(),
        IciciView::Unknown => "ICICI — unknown".into(),
    }
}

/// `SuryaDhana 1.0.0 · 0ae66db-dirty-3f2a91c4-20261025T0930Z` (completeness-04: the build id tells two
/// binaries apart).
pub fn version_line() -> String {
    format!("SuryaDhana {} · {}", env!("CARGO_PKG_VERSION"), crate::BUILD_ID)
}

/// The UI-release line of the tray (with the port guard's "not verified" note when its check was
/// inconclusive: the terminal stays open, the menu bar says so).
pub fn build_line(snap: &Snapshot) -> String {
    let line = match (snap.ui_state, &snap.status.ui_build) {
        (UiState::NoRelease, _) => "Terminal UI release missing — ./start-local.sh build-ui".into(),
        (UiState::Untrusted, _) => "Terminal port held by an unexpected process — see the boot page".into(),
        (UiState::Unverifiable, _) => {
            "Terminal port: listener cannot be verified (executable gone) — ./start-local.sh restart ui-api".into()
        }
        (_, Some(b)) => format!("UI build {b}"),
        (UiState::Ready, None) => "UI build (no build-info)".into(),
        (_, None) => format!("Terminal not reachable — {}", snap.ui_detail),
    };
    match (&snap.trust, snap.ui_state) {
        (TrustView::Unknown(_), UiState::Ready) => format!("{line} · port not verified (retrying)"),
        _ => line,
    }
}

/// The tooltip's NIFTY part: live price, the last close with its date while NSE is closed, or stale.
pub fn nifty_tip(snap: &Snapshot) -> String {
    let at = snap
        .quote
        .and_then(|q| q.at)
        .map(|t| {
            let m = t.month().to_string();
            format!(
                " {:02}-{}-{} {:02}:{:02} IST",
                t.day(),
                &m[..m.len().min(3)],
                t.year(),
                t.hour(),
                t.minute()
            )
        })
        .unwrap_or_default();
    match (snap.status.nifty, snap.quote_state) {
        (Some(n), QuoteState::Closed) => format!(
            " · NIFTY {} (market closed; last close{at})",
            group_thousands(n.last, 2)
        ),
        (Some(n), _) => format!(" · NIFTY {}", group_thousands(n.last, 2)),
        (None, QuoteState::Stale) => " · NIFTY quote stale (data-service?)".into(),
        _ => String::new(),
    }
}

/// Indian-style rupee amount for the NAV line (lakh grouping: 5,02,085).
pub fn inr(v: f64) -> String {
    let n = v.round().abs() as u64;
    let s = n.to_string();
    let out = if s.len() <= 3 {
        s
    } else {
        let (head, last3) = s.split_at(s.len() - 3);
        let mut groups = vec![];
        let mut h = head.to_string();
        while h.len() > 2 {
            let cut = h.len() - 2;
            groups.insert(0, h[cut..].to_string());
            h.truncate(cut);
        }
        if !h.is_empty() {
            groups.insert(0, h);
        }
        format!("{},{}", groups.join(","), last3)
    };
    format!("{}₹{}", if v < 0.0 { "-" } else { "" }, out)
}

pub fn desk_line(d: Option<&Desk>) -> String {
    match d {
        Some(d) => format!("Desk NAV {}  {:+.2}%  ({})", inr(d.nav), d.return_pct, d.date),
        None => "Desk NAV —".into(),
    }
}

/// Refresh every line and the title from a snapshot (call it without holding any shell lock).
pub fn update(h: &TrayHandles, snap: &Snapshot, cfg: &crate::config::Config) {
    let st = &snap.status;
    let paused = |n: &str| snap.stack.is_paused(n);
    let hung = snap.stalled.map(|x| x.is_some());
    let _ = h.ui.set_text(svc_line(
        "ui-api",
        cfg.ui_url.port(),
        &st.ui_api,
        paused("ui-api"),
        hung[0],
    ));
    let _ = h.ds.set_text(svc_line(
        "data-service",
        cfg.data_service_url.port(),
        &st.data_service,
        paused("data-service"),
        hung[1],
    ));
    let _ = h.mc.set_text(svc_line(
        "master-controller",
        cfg.controller_url.port(),
        &st.master_controller,
        paused("master-controller"),
        hung[2],
    ));
    let _ = h.icici.set_text(icici_line(snap.icici_view));
    let _ = h.desk.set_text(desk_line(snap.desk.as_ref()));
    let _ = h.build.set_text(build_line(snap));
    // Start Stack has nothing to do while all three answer (C1-desktop-native-18), nor for a hung one
    let up = [st.ui_api.up, st.data_service.up, st.master_controller.up];
    let _ = h.start.set_enabled(start_useful(up, hung));
    let title = if cfg.nifty_in_menubar {
        tray_title_for(snap.quote.as_ref(), snap.quote_state)
    } else {
        String::new()
    };
    let changed = {
        let mut last = h.last_title.lock().unwrap_or_else(|e| e.into_inner());
        let changed = *last != title;
        if changed {
            last.clone_from(&title);
        }
        changed
    };
    if changed {
        let _ = h.tray.set_title(Some(&title));
    }
    let tip = format!(
        "SuryaDhana — {} of 3 services up{}",
        [st.ui_api.up, st.data_service.up, st.master_controller.up]
            .iter()
            .filter(|u| **u)
            .count(),
        nifty_tip(snap)
    );
    let _ = h.tray.set_tooltip(Some(&tip));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lines_render() {
        let up = Svc {
            up: true,
            latency_ms: Some(1.7),
        };
        let down = Svc {
            up: false,
            latency_ms: None,
        };
        assert_eq!(
            svc_line("ui-api", Some(8010), &up, false, false),
            "● ui-api :8010 — up, 2 ms"
        );
        assert_eq!(
            svc_line("data-service", Some(8001), &down, false, false),
            "○ data-service :8001 — DOWN"
        );
        assert_eq!(
            svc_line("data-service", Some(8001), &down, true, false),
            "○ data-service :8001 — stopped (paused)"
        );
        for l in [
            svc_line("ui-api", Some(8010), &up, false, false),
            icici_line(IciciView::Expired),
            icici_line(IciciView::Unreachable),
            icici_line(IciciView::Credentials),
        ] {
            assert!(!l.contains("  "), "no space-padded columns: {l:?}");
        }
        assert!(icici_line(IciciView::Expired).contains("/login"));
        // round 4b, P4: an outage never says expired or /login
        assert_eq!(icici_line(IciciView::Unreachable), "ICICI — unreachable (network)");
        for v in [IciciView::Unreachable, IciciView::Credentials, IciciView::Unknown] {
            let l = icici_line(v);
            assert!(!l.contains("/login") && !l.contains("expired"), "{l}");
        }
        // a hung service (port held, /health timing out) is named as such, and Start is not offered for it
        assert_eq!(
            svc_line("ui-api", Some(8010), &down, false, true),
            "◌ ui-api :8010 — NOT RESPONDING (port held, no /health answer)"
        );
        assert!(!start_useful([false, true, true], [true, false, false]));
        assert!(start_useful([false, false, true], [true, false, false]));
        assert!(!start_useful([true; 3], [false; 3]));
        assert_eq!(inr(502085.37), "₹5,02,085");
        assert_eq!(inr(999.0), "₹999");
        assert_eq!(inr(12345678.0), "₹1,23,45,678");
        assert_eq!(inr(-1500.0), "-₹1,500");
        let d = Desk {
            nav: 502085.37,
            return_pct: 0.417,
            date: "2026-10-23".into(),
        };
        assert_eq!(desk_line(Some(&d)), "Desk NAV ₹5,02,085  +0.42%  (2026-10-23)");
        assert_eq!(desk_line(None), "Desk NAV —");
    }

    #[test]
    fn build_line_names_the_remedy() {
        let mut snap = Snapshot {
            ui_state: UiState::NoRelease,
            ..Snapshot::default()
        };
        assert!(build_line(&snap).contains("build-ui"));
        snap.ui_state = UiState::Untrusted;
        assert!(build_line(&snap).contains("unexpected process"));
        snap.ui_state = UiState::Unverifiable;
        assert!(build_line(&snap).contains("restart ui-api"), "{}", build_line(&snap));
        snap.ui_state = UiState::Ready;
        snap.status.ui_build = Some("20261025-1".into());
        assert_eq!(build_line(&snap), "UI build 20261025-1");
        // wave 2: an inconclusive port check never closes the terminal; the menu bar says it
        snap.trust = TrustView::Unknown("timed out".into());
        assert_eq!(build_line(&snap), "UI build 20261025-1 · port not verified (retrying)");
        snap.trust = TrustView::Trusted("pid 1".into());
        assert_eq!(build_line(&snap), "UI build 20261025-1");
        assert!(version_line().starts_with(&format!("SuryaDhana {} · ", env!("CARGO_PKG_VERSION"))));
        assert!(version_line().contains(env!("SURYADHANA_BUILD")));
    }

    #[test]
    fn closed_market_tooltip_names_the_session() {
        use crate::health::{parse_nse_time, Nifty, Quote};
        let q = Quote {
            nifty: Nifty {
                last: 22600.0,
                change_pct: -0.39,
            },
            at: parse_nse_time("23-Oct-2026 15:30"),
        };
        let mut snap = Snapshot {
            quote: Some(q),
            quote_state: QuoteState::Closed,
            ..Snapshot::default()
        };
        snap.status.nifty = Some(q.nifty);
        assert_eq!(
            nifty_tip(&snap),
            " · NIFTY 22,600.00 (market closed; last close 23-Oct-2026 15:30 IST)"
        );
        snap.quote_state = QuoteState::Live;
        assert_eq!(nifty_tip(&snap), " · NIFTY 22,600.00");
        snap.status.nifty = None;
        snap.quote_state = QuoteState::Stale;
        assert!(nifty_tip(&snap).contains("stale"));
    }

    #[test]
    fn the_notification_hint_follows_only_a_definite_answer() {
        use crate::macos::NotifAuth;
        assert!(notif_hint_wanted(Some(NotifAuth::Denied), false));
        assert!(!notif_hint_wanted(Some(NotifAuth::Authorized), true));
        assert!(
            !notif_hint_wanted(Some(NotifAuth::NotDetermined), true),
            "not decided yet: macOS will ask"
        );
        // unknown (timed out / not from the bundle): whatever was shown stays
        assert!(notif_hint_wanted(None, true));
        assert!(!notif_hint_wanted(None, false));
        assert!(NOTIF_HINT_TEXT.contains("System Settings › Notifications › SuryaDhana"));
        assert!(matches!(
            crate::menu::parse_action("tray:app:notification-settings"),
            Some(crate::menu::Action::NotificationSettings)
        ));
    }
}
