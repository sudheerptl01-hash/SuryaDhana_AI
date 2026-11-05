//! Native macOS menu bar and the menu/tray action dispatcher.
//!
//! App (About with the build id, Settings… ⌘, = the app's settings file config.json with what each key
//! does, Launch at Login ✓, Services, Hide, Hide Others, Show All, Quit ⌘Q) · File (New Window ⌘N, Open
//! Current Page in New Window ⌥⌘N, Show Latest Download ⌥⌘L, Print… ⌘P, Close Window ⌘W) · Edit (predefined
//! Undo/Redo/Cut/Copy/Paste/Select All: REQUIRED, otherwise ⌘C/⌘V do not reach inputs in WKWebView) ·
//! View (Reload ⌘R, Actual Size ⌘0, Zoom In ⌘=, Zoom Out ⌘-: per window, saved, published to the page
//! as `{type:'zoom'}`; Enter Full Screen ⌃⌘F, Developer Tools only in a `--features devtools` build with
//! config.devtools) · Go (Back ⌘[, Forward ⌘], GO Bar…, ⌘1..⌘9 = the UI's ALT+1..9 pages, then all 42 pages
//! in 6 groups) · Window (Minimize, Zoom, Bring All to Front) · Help (Keyboard Shortcuts, logs, runbook,
//! System page).
//!
//! ⌘K is deliberately NOT an accelerator: the terminal UI already handles ⌘K / Ctrl+K itself. ⌘F is NOT one
//! either (round 4b, R9): with no menu item claiming it, WKWebView hands the key to the page, whose find bar
//! takes it (Enter Full Screen is ⌃⌘F). The self-test reads the real menu bar to prove both.
//!
//! Menu ids are actions (`go:<tab>`, `app:new-window`, …); tray ids use the same scheme with a `tray:`
//! prefix so one dispatcher serves both.

use tauri::menu::{
    AboutMetadataBuilder, CheckMenuItem, CheckMenuItemBuilder, Menu, MenuBuilder, MenuEvent, MenuItem, MenuItemBuilder,
    MenuItemKind, SubmenuBuilder,
};
use tauri::{AppHandle, Manager, Wry};

use crate::autostart;
use crate::pages::{self, Group};
use crate::windows;

/// Menu actions (parsed from menu item ids).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Action {
    Goto(String),
    CommandBar,
    NewWindow,
    /// ⌥⌘N: the focused window's exact page (tab, stock deep link, filters) in a new window.
    DuplicateWindow,
    OpenTerminal,
    Back,
    Forward,
    /// Help ▸ Keyboard Shortcuts.
    Shortcuts,
    Reload,
    ZoomReset,
    ZoomIn,
    ZoomOut,
    DevTools,
    ToggleAutostart,
    StartStack,
    StopStack,
    OpenAppLogs,
    OpenStackLogs,
    Runbook,
    /// Settings… (⌘,): the app's settings file (config.json), explained first in a native dialog.
    Settings,
    /// Reveal the latest file saved into Downloads in Finder.
    RevealDownload,
    /// File ▸ Print… (⌘P, round 4b R9): the focused terminal window through WebKit's print panel.
    Print,
    /// Tray: System Settings › Notifications at SuryaDhana (shown only while macOS has them off; a click).
    NotificationSettings,
    Quit,
}

/// Parse a menu id (`tray:` prefix allowed). Unknown ids (predefined items) -> None.
pub fn parse_action(id: &str) -> Option<Action> {
    let id = id.strip_prefix("tray:").unwrap_or(id);
    if let Some(tab) = id.strip_prefix("go:").filter(|t| !matches!(*t, "back" | "forward")) {
        return pages::is_valid_tab(tab).then(|| Action::Goto(tab.to_string()));
    }
    Some(match id {
        "app:command-bar" => Action::CommandBar,
        "app:new-window" => Action::NewWindow,
        "app:duplicate-window" => Action::DuplicateWindow,
        "go:back" => Action::Back,
        "go:forward" => Action::Forward,
        "help:shortcuts" => Action::Shortcuts,
        "app:open-terminal" => Action::OpenTerminal,
        "view:reload" => Action::Reload,
        "view:zoom-reset" => Action::ZoomReset,
        "view:zoom-in" => Action::ZoomIn,
        "view:zoom-out" => Action::ZoomOut,
        "view:devtools" => Action::DevTools,
        "app:autostart" => Action::ToggleAutostart,
        "stack:start" => Action::StartStack,
        "stack:stop" => Action::StopStack,
        "help:app-logs" => Action::OpenAppLogs,
        "help:stack-logs" => Action::OpenStackLogs,
        "help:runbook" => Action::Runbook,
        "app:settings" => Action::Settings,
        "app:latest-download" => Action::RevealDownload,
        "app:print" => Action::Print,
        "app:notification-settings" => Action::NotificationSettings,
        "app:quit" => Action::Quit,
        _ => return None,
    })
}

/// Handles kept to update check marks / enabled states later (cloned out of `Shell::menu` before use:
/// see `tray::TrayHandles`).
#[derive(Clone)]
pub struct MenuHandles {
    pub autostart: CheckMenuItem<Wry>,
    pub latest_download: MenuItem<Wry>,
}

/// Help ▸ Keyboard Shortcuts (the native app's keys; the terminal's own keys are in its GO bar help).
pub const SHORTCUTS: &[(&str, &str)] = &[
    ("⌘K", "GO bar (type a function code or a ticker)"),
    ("⌘1 – ⌘9", "pages BRF, WTCH, … (same as Alt+1 – Alt+9 in a browser)"),
    ("⌘[  /  ⌘]", "back / forward through this window's pages"),
    ("⌘N", "new window on the same page"),
    ("⌥⌘N", "open the current page (with its stock) in a new window"),
    (
        "⌘W",
        "close the window (the main window hides; SuryaDhana stays in the menu bar)",
    ),
    ("⌘=  ⌘-  ⌘0", "zoom in / out / actual size (per window, remembered)"),
    ("⌘R", "reload the window"),
    ("⌃⌘F", "full screen"),
    ("⌥⌘L", "show the latest download in Finder"),
    ("⌘P", "print the page (the window's own print panel)"),
    ("⌘,", "settings (config.json)"),
    ("⌘Q", "quit (the stack keeps running)"),
    ("Esc", "close the stock window / GO bar (terminal)"),
];

/// The text of Help ▸ Keyboard Shortcuts.
pub fn shortcuts_text() -> String {
    SHORTCUTS
        .iter()
        .map(|(k, what)| format!("{k}\t{what}"))
        .collect::<Vec<_>>()
        .join("\n")
}

/// Build the application menu.
pub fn build(app: &AppHandle, devtools: bool, autostart: autostart::State) -> tauri::Result<(Menu<Wry>, MenuHandles)> {
    let pkg = app.package_info();
    // two different binaries never look alike: the build id carries sha, dirty flag, source hash and time
    let about = AboutMetadataBuilder::new()
        .name(Some("SuryaDhana"))
        .version(Some(pkg.version.to_string()))
        .short_version(Some(crate::BUILD_ID))
        .comments(Some("NSE + MCX research and paper-trading terminal. PAPER ONLY."))
        .copyright(Some("SuryaDhana AI"))
        .build();
    let autostart_item = CheckMenuItemBuilder::with_id("app:autostart", autostart.menu_text())
        .checked(autostart.checked())
        .build(app)?;
    let latest_download = MenuItemBuilder::with_id("app:latest-download", "Show Latest Download")
        .accelerator("Alt+CmdOrCtrl+L")
        .enabled(false)
        .build(app)?;

    let app_menu = SubmenuBuilder::new(app, "SuryaDhana")
        .about_with_text("About SuryaDhana", Some(about))
        .separator()
        .item(
            &MenuItemBuilder::with_id("app:settings", "Settings…")
                .accelerator("CmdOrCtrl+,")
                .build(app)?,
        )
        .separator()
        .item(&autostart_item)
        .separator()
        .services()
        .separator()
        .hide_with_text("Hide SuryaDhana")
        .hide_others()
        .show_all()
        .separator()
        .item(
            &MenuItemBuilder::with_id("app:quit", "Quit SuryaDhana")
                .accelerator("CmdOrCtrl+Q")
                .build(app)?,
        )
        .build()?;

    let file = SubmenuBuilder::new(app, "File")
        .item(
            &MenuItemBuilder::with_id("app:new-window", "New Window")
                .accelerator("CmdOrCtrl+N")
                .build(app)?,
        )
        .item(
            &MenuItemBuilder::with_id("app:duplicate-window", "Open Current Page in New Window")
                .accelerator("Alt+CmdOrCtrl+N")
                .build(app)?,
        )
        .separator()
        .item(&latest_download)
        .separator()
        .item(
            &MenuItemBuilder::with_id("app:print", "Print…")
                .accelerator("CmdOrCtrl+P")
                .build(app)?,
        )
        .separator()
        .close_window_with_text("Close Window")
        .build()?;

    let edit = SubmenuBuilder::new(app, "Edit")
        .undo()
        .redo()
        .separator()
        .cut()
        .copy()
        .paste()
        .select_all()
        .build()?;

    let mut view = SubmenuBuilder::new(app, "View")
        .item(
            &MenuItemBuilder::with_id("view:reload", "Reload")
                .accelerator("CmdOrCtrl+R")
                .build(app)?,
        )
        .separator()
        .item(
            &MenuItemBuilder::with_id("view:zoom-reset", "Actual Size")
                .accelerator("CmdOrCtrl+0")
                .build(app)?,
        )
        .item(
            &MenuItemBuilder::with_id("view:zoom-in", "Zoom In")
                .accelerator("CmdOrCtrl+=")
                .build(app)?,
        )
        .item(
            &MenuItemBuilder::with_id("view:zoom-out", "Zoom Out")
                .accelerator("CmdOrCtrl+-")
                .build(app)?,
        )
        .separator()
        .fullscreen_with_text("Enter Full Screen");
    if devtools && cfg!(feature = "devtools") {
        view = view.separator().item(
            &MenuItemBuilder::with_id("view:devtools", "Developer Tools")
                .accelerator("Alt+CmdOrCtrl+I")
                .build(app)?,
        );
    }
    let view = view.build()?;

    let mut go = SubmenuBuilder::new(app, "Go")
        .item(
            &MenuItemBuilder::with_id("go:back", "Back")
                .accelerator("CmdOrCtrl+[")
                .build(app)?,
        )
        .item(
            &MenuItemBuilder::with_id("go:forward", "Forward")
                .accelerator("CmdOrCtrl+]")
                .build(app)?,
        )
        .separator()
        .item(&MenuItemBuilder::with_id("app:command-bar", "GO Bar…   (⌘K in the terminal)").build(app)?)
        .separator();
    for p in pages::shortcut_pages() {
        go = go.item(
            &MenuItemBuilder::with_id(format!("go:{}", p.id), format!("{}  ·  {}", p.code, p.label))
                .accelerator(format!("CmdOrCtrl+{}", p.shortcut))
                .build(app)?,
        );
    }
    go = go.separator();
    for g in Group::ALL {
        let mut sub = SubmenuBuilder::new(app, g.title());
        for p in pages::pages_in(g) {
            sub = sub.text(format!("go:{}", p.id), format!("{}  ·  {}", p.code, p.label));
        }
        go = go.item(&sub.build()?);
    }
    let go = go.build()?;

    let window = SubmenuBuilder::new(app, "Window")
        .minimize()
        .maximize_with_text("Zoom")
        .separator()
        .bring_all_to_front()
        .build()?;

    let help = SubmenuBuilder::new(app, "Help")
        .item(&MenuItemBuilder::with_id("help:shortcuts", "Keyboard Shortcuts").build(app)?)
        .separator()
        .item(&MenuItemBuilder::with_id("go:system", "System page (SYS)").build(app)?)
        .item(&MenuItemBuilder::with_id("help:runbook", "Runbook (restore & outages)").build(app)?)
        .separator()
        .item(&MenuItemBuilder::with_id("help:stack-logs", "Open Stack Logs Folder").build(app)?)
        .item(&MenuItemBuilder::with_id("help:app-logs", "Open App Logs Folder").build(app)?)
        .build()?;

    let menu = MenuBuilder::new(app)
        .items(&[&app_menu, &file, &edit, &view, &go, &window, &help])
        .build()?;
    #[cfg(target_os = "macos")]
    {
        let _ = window.set_as_windows_menu_for_nsapp();
        let _ = help.set_as_help_menu_for_nsapp();
    }
    Ok((
        menu,
        MenuHandles {
            autostart: autostart_item,
            latest_download,
        },
    ))
}

/// Distinct tab ids reachable from the Go menu's group submenus (self-test: must be 42), plus
/// whether the Edit menu carries the predefined clipboard items.
pub fn introspect(menu: &Menu<Wry>) -> (usize, bool, usize) {
    let mut tabs = std::collections::BTreeSet::new();
    let mut edit_ok = false;
    let mut shortcut_items = 0usize;
    for item in menu.items().unwrap_or_default() {
        if let MenuItemKind::Submenu(sub) = item {
            let title = sub.text().unwrap_or_default();
            let items = sub.items().unwrap_or_default();
            if title == "Go" {
                for it in &items {
                    match it {
                        MenuItemKind::MenuItem(mi)
                            if mi.id().0.starts_with("go:")
                                && !matches!(mi.id().0.as_str(), "go:back" | "go:forward") =>
                        {
                            shortcut_items += 1
                        }
                        MenuItemKind::Submenu(group) => {
                            for gi in group.items().unwrap_or_default() {
                                if let MenuItemKind::MenuItem(mi) = gi {
                                    if let Some(t) = mi.id().0.strip_prefix("go:") {
                                        tabs.insert(t.to_string());
                                    }
                                }
                            }
                        }
                        _ => {}
                    }
                }
            }
            if title == "Edit" {
                let texts: Vec<String> = items
                    .iter()
                    .filter_map(|i| match i {
                        MenuItemKind::Predefined(p) => p.text().ok(),
                        _ => None,
                    })
                    .collect();
                edit_ok = ["Copy", "Paste", "Cut", "Select All"]
                    .iter()
                    .all(|w| texts.iter().any(|t| t.contains(w)));
            }
        }
    }
    (tabs.len(), edit_ok, shortcut_items)
}

/// Global menu + tray event handler.
pub fn on_menu_event(app: &AppHandle, event: MenuEvent) {
    let Some(action) = parse_action(&event.id().0) else {
        return;
    };
    dispatch(app, action);
}

/// Execute an action (menu, tray, boot page).
pub fn dispatch(app: &AppHandle, action: Action) {
    match action {
        Action::Goto(tab) => windows::goto(app, &tab),
        Action::CommandBar => windows::command_bar(app),
        Action::NewWindow => {
            // ⌘N opens the page the focused window shows (else the landing page)
            let tab = app
                .get_webview_window(&windows::focused_label(app))
                .and_then(|w| windows::webview_url(&w))
                .and_then(|u| u.query().and_then(|q| windows::tab_of(&format!("?{q}"))))
                .unwrap_or(pages::DEFAULT_TAB);
            let target = windows::tab_target(tab);
            if let Err(e) = windows::open_new_terminal(app, &target) {
                // the standard Mac answer to "cannot do that now" (not a notification)
                log::warn!("[window] new window refused: {e}");
                crate::macos::beep();
            }
        }
        Action::DuplicateWindow => {
            let target = windows::current_target(app, &windows::focused_label(app))
                .unwrap_or_else(|| windows::tab_target(pages::DEFAULT_TAB));
            if let Err(e) = windows::open_new_terminal(app, &target) {
                log::warn!("[window] new window refused: {e}");
                crate::macos::beep();
            }
        }
        Action::Back => windows::history(app, true),
        Action::Forward => windows::history(app, false),
        Action::Shortcuts => crate::show_shortcuts(app),
        Action::OpenTerminal => windows::show_window(app, windows::MAIN),
        Action::Reload => windows::reload(app),
        Action::ZoomReset => windows::zoom(app, None),
        Action::ZoomIn => windows::zoom(app, Some(0.1)),
        Action::ZoomOut => windows::zoom(app, Some(-0.1)),
        Action::DevTools =>
        {
            #[cfg(feature = "devtools")]
            if app.state::<crate::Shell>().cfg.devtools {
                if let Some(w) = app.get_webview_window(&windows::focused_label(app)) {
                    w.open_devtools();
                }
            }
        }
        Action::ToggleAutostart => crate::toggle_autostart(app),
        Action::StartStack => crate::stack_start_action(app),
        Action::StopStack => crate::stack_stop_action(app),
        Action::OpenAppLogs => crate::open_folder(app, crate::LogsTarget::App),
        Action::OpenStackLogs => crate::open_folder(app, crate::LogsTarget::Stack),
        Action::Runbook => crate::open_runbook(app),
        Action::Settings => crate::open_settings(app),
        Action::RevealDownload => crate::reveal_latest_download(app),
        Action::Print => {
            if let Err(why) = windows::print(app) {
                // the standard Mac answer to "nothing to print here" (boot page, hidden window, a sheet already up)
                log::info!("[print] not printed: {why}");
                crate::macos::beep();
            }
        }
        Action::NotificationSettings => crate::open_notification_settings(app),
        Action::Quit => crate::quit(app),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_actions_and_rejects_unknown() {
        assert_eq!(parse_action("go:desk"), Some(Action::Goto("desk".into())));
        assert_eq!(parse_action("tray:go:risk"), Some(Action::Goto("risk".into())));
        assert_eq!(parse_action("go:nope"), None);
        assert_eq!(parse_action("tray:stack:stop"), Some(Action::StopStack));
        assert_eq!(parse_action("app:quit"), Some(Action::Quit));
        assert_eq!(parse_action("app:command-bar"), Some(Action::CommandBar));
        assert_eq!(parse_action("tray:status:ui"), None);
        assert_eq!(parse_action(""), None);
        assert_eq!(parse_action("app:settings"), Some(Action::Settings));
        assert_eq!(parse_action("tray:app:latest-download"), Some(Action::RevealDownload));
        // wave 2: history, duplicate window, shortcuts (never mistaken for page ids)
        assert_eq!(parse_action("go:back"), Some(Action::Back));
        assert_eq!(parse_action("go:forward"), Some(Action::Forward));
        assert_eq!(parse_action("app:duplicate-window"), Some(Action::DuplicateWindow));
        assert_eq!(parse_action("help:shortcuts"), Some(Action::Shortcuts));
        // round 4b: Print… (⌘P) and the tray's notification-settings line
        assert_eq!(parse_action("app:print"), Some(Action::Print));
        assert_eq!(
            parse_action("tray:app:notification-settings"),
            Some(Action::NotificationSettings)
        );
        assert!(!crate::pages::is_valid_tab("back") && !crate::pages::is_valid_tab("forward"));
    }

    #[test]
    fn shortcut_list_names_the_cmd_keys() {
        let t = shortcuts_text();
        for k in [
            "⌘K",
            "⌘1 – ⌘9",
            "⌘[",
            "⌘]",
            "⌘N",
            "⌥⌘N",
            "⌘W",
            "⌘=",
            "⌘0",
            "⌘,",
            "⌘P",
            "⌘Q",
            "Esc",
        ] {
            assert!(t.contains(k), "{k} missing from:\n{t}");
        }
        assert!(!t.contains("Alt+1 …"), "the desktop list teaches ⌘ keys first");
    }

    /// Every accelerator the shell declares (menu.rs + tray.rs sources), normalised to (modifiers, key).
    fn declared_accelerators() -> Vec<(String, String)> {
        let mut out = vec![];
        for src in [include_str!("menu.rs"), include_str!("tray.rs")] {
            let code = src.split("#[cfg(test)]").next().unwrap_or_default();
            for part in code.split(".accelerator(").skip(1) {
                let arg = part.split(')').next().unwrap_or_default();
                let lit = if let Some(rest) = arg.strip_prefix("format!(") {
                    // `format!("CmdOrCtrl+{}", p.shortcut)`: the Go menu's ⌘1–⌘9
                    rest.trim_start_matches('"')
                        .split('"')
                        .next()
                        .unwrap_or_default()
                        .replace("{}", "1")
                } else {
                    arg.trim().trim_matches('"').to_string()
                };
                let mut mods: Vec<String> = lit.split('+').map(|t| t.to_ascii_lowercase()).collect();
                let key = mods.pop().unwrap_or_default();
                mods.sort();
                out.push((mods.join("+"), key));
            }
        }
        out
    }

    #[test]
    fn cmd_f_stays_free_for_the_page_and_cmd_p_prints() {
        let acc = declared_accelerators();
        assert!(acc.len() >= 12, "{acc:?}");
        // R9: no menu or tray item takes plain ⌘F (the page's find bar gets it); ⌃⌘F is the predefined full screen
        for (mods, key) in &acc {
            let cmd_only = mods == "cmdorctrl" || mods == "cmd" || mods == "command" || mods == "super";
            assert!(!(cmd_only && key == "f"), "⌘F is bound by a menu item: {mods}+{key}");
        }
        assert!(acc.contains(&("cmdorctrl".into(), "p".into())), "⌘P = Print…: {acc:?}");
        // every declared accelerator is unique
        let mut seen = std::collections::BTreeSet::new();
        for a in &acc {
            if a.1 != "1" {
                assert!(seen.insert(a.clone()), "accelerator declared twice: {a:?}");
            }
        }
    }
}
