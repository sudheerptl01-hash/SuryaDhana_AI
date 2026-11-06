//! The 43 terminal pages (function codes) known to the shell.
//!
//! Source of truth: `ui/app/page.tsx` -> `COMMAND_PAGES` (id, code, label; same order here) and the
//! `tabList` order that drives the UI's ALT+1..9 shortcuts (mirrored by the shell's Cmd+1..9). Since the page review of
//! 5 Nov 2026 (M37) that is the trader's day: BRF WTCH CHRT OMON OSTR DERV MOV EVTS ALRT (Cmd+1..9), RSK on ALT+0.
//! A QA test (scripts/desktop_qa) parses this file and diffs it against page.tsx, so keep it a plain
//! array of struct literals with string literals, one page per line.
//!
//! `shortcut`: 1..=9 = the Cmd+N / ALT+N page (tabList position), 0 = none.
//!
//! Gold program (26 Oct 2026, reports/gold_program/PLAN.md Appendix A): the 43rd page `gold` / `GOLD`
//! ("Gold terminal") sits after MCXG in the Derivatives & Gold group with no Cmd digit (the nine Cmd+1..9
//! pages are unchanged), and CMDT's label drops "· Gold desk" (PLAN §b: the pre-open desk moved to GOLD).

/// Native Go-menu group a page is listed under.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Group {
    Markets,
    Equities,
    DerivativesGold,
    PortfolioRisk,
    ResearchData,
    System,
}

impl Group {
    /// All groups in Go-menu order.
    pub const ALL: [Group; 6] = [
        Group::Markets,
        Group::Equities,
        Group::DerivativesGold,
        Group::PortfolioRisk,
        Group::ResearchData,
        Group::System,
    ];

    /// Submenu title.
    pub fn title(self) -> &'static str {
        match self {
            Group::Markets => "Markets",
            Group::Equities => "Equities",
            Group::DerivativesGold => "Derivatives & Gold",
            Group::PortfolioRisk => "Portfolio & Risk",
            Group::ResearchData => "Research & Data",
            Group::System => "System",
        }
    }
}

/// One terminal page.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Page {
    pub id: &'static str,
    pub code: &'static str,
    pub label: &'static str,
    pub group: Group,
    pub shortcut: u8,
}

pub const PAGE_COUNT: usize = 43;

#[rustfmt::skip]
pub const PAGES: [Page; PAGE_COUNT] = [
    Page { id: "brief", code: "BRF", label: "Morning brief", group: Group::Markets, shortcut: 1 },
    Page { id: "watch", code: "WTCH", label: "Watch monitor", group: Group::Markets, shortcut: 2 },
    Page { id: "charts", code: "CHRT", label: "Chart studio", group: Group::Markets, shortcut: 3 },
    Page { id: "world", code: "WEI", label: "World markets", group: Group::Markets, shortcut: 0 },
    Page { id: "eco", code: "ECO", label: "Economic calendar", group: Group::Markets, shortcut: 0 },
    Page { id: "memb", code: "MEMB", label: "Index members", group: Group::Markets, shortcut: 0 },
    Page { id: "seag", code: "SEAG", label: "Seasonality", group: Group::Markets, shortcut: 0 },
    Page { id: "preopen", code: "PRE", label: "Pre-open auction", group: Group::Markets, shortcut: 0 },
    Page { id: "movers", code: "MOV", label: "Live movers", group: Group::Markets, shortcut: 7 },
    Page { id: "filings", code: "CF", label: "Company filings", group: Group::Equities, shortcut: 0 },
    Page { id: "options", code: "OMON", label: "Option monitor", group: Group::DerivativesGold, shortcut: 4 },
    Page { id: "derivatives", code: "DERV", label: "Derivatives desk", group: Group::DerivativesGold, shortcut: 6 },
    Page { id: "ostrategy", code: "OSTR", label: "Options strategies", group: Group::DerivativesGold, shortcut: 5 },
    Page { id: "deals", code: "DEAL", label: "Block & bulk deals", group: Group::Equities, shortcut: 0 },
    Page { id: "margin", code: "MRGN", label: "Margin monitor", group: Group::Equities, shortcut: 0 },
    Page { id: "screen", code: "FUND", label: "Fundamentals screener", group: Group::Equities, shortcut: 0 },
    Page { id: "alerts", code: "ALRT", label: "Alerts", group: Group::PortfolioRisk, shortcut: 9 },
    Page { id: "holders", code: "HDS", label: "Ownership shifts", group: Group::Equities, shortcut: 0 },
    Page { id: "insiders", code: "INSD", label: "Insider monitor", group: Group::Equities, shortcut: 0 },
    Page { id: "ipo", code: "IPO", label: "IPO monitor", group: Group::Equities, shortcut: 0 },
    Page { id: "wrap", code: "WRAP", label: "Daily market wrap", group: Group::Markets, shortcut: 0 },
    Page { id: "compare", code: "COMP", label: "Compare stocks", group: Group::Equities, shortcut: 0 },
    Page { id: "desk", code: "DESK", label: "Decision Desk", group: Group::PortfolioRisk, shortcut: 0 },
    Page { id: "markets", code: "MKT", label: "Market Monitor", group: Group::Markets, shortcut: 0 },
    Page { id: "events", code: "EVTS", label: "Corporate calendar", group: Group::Markets, shortcut: 8 },
    Page { id: "overview", code: "OVRV", label: "Overview", group: Group::ResearchData, shortcut: 0 },
    Page { id: "stocks", code: "EQS", label: "Stocks / screener", group: Group::Equities, shortcut: 0 },
    Page { id: "backtest", code: "BTST", label: "Backtest lab", group: Group::PortfolioRisk, shortcut: 0 },
    Page { id: "positions", code: "PORT", label: "Portfolio", group: Group::PortfolioRisk, shortcut: 0 },
    Page { id: "broker", code: "BRKR", label: "Broker (ICICI)", group: Group::PortfolioRisk, shortcut: 0 },
    Page { id: "pipeline", code: "PIPE", label: "Pipeline / watchlist", group: Group::System, shortcut: 0 },
    Page { id: "scanner", code: "LWSC", label: "LW scanner", group: Group::Equities, shortcut: 0 },
    Page { id: "discovery", code: "ALFA", label: "Alpha discovery", group: Group::ResearchData, shortcut: 0 },
    Page { id: "commodity", code: "CMDT", label: "Commodities", group: Group::DerivativesGold, shortcut: 0 },
    Page { id: "mcxgold", code: "MCXG", label: "MCX gold desk", group: Group::DerivativesGold, shortcut: 0 },
    Page { id: "gold", code: "GOLD", label: "Gold terminal", group: Group::DerivativesGold, shortcut: 0 },
    Page { id: "glassbox", code: "GBOX", label: "Glass-Box studio", group: Group::ResearchData, shortcut: 0 },
    Page { id: "mlengine", code: "MLEN", label: "ML engine", group: Group::ResearchData, shortcut: 0 },
    Page { id: "explorer", code: "DEXP", label: "Data explorer", group: Group::ResearchData, shortcut: 0 },
    Page { id: "warehouse", code: "WHSE", label: "Warehouse health", group: Group::ResearchData, shortcut: 0 },
    Page { id: "research", code: "RSCH", label: "Research library", group: Group::ResearchData, shortcut: 0 },
    Page { id: "risk", code: "RSK", label: "Risk dashboard", group: Group::PortfolioRisk, shortcut: 0 },
    Page { id: "system", code: "SYS", label: "System telemetry", group: Group::System, shortcut: 0 },
];

/// The landing page (the UI's default view).
pub const DEFAULT_TAB: &str = "brief";

/// Key pages offered in the tray's Go submenu (Cmd+1..9 pages plus risk and system).
#[rustfmt::skip]
pub const TRAY_PAGES: [&str; 11] = [
    "brief", "watch", "charts", "options", "ostrategy", "derivatives", "movers", "events", "alerts", "risk", "system",
];

/// Look a page up by its tab id.
pub fn by_id(id: &str) -> Option<&'static Page> {
    PAGES.iter().find(|p| p.id == id)
}

/// True iff `id` is one of the 43 tab ids.
pub fn is_valid_tab(id: &str) -> bool {
    by_id(id).is_some()
}

/// The Cmd+1..9 pages, ordered by shortcut digit.
pub fn shortcut_pages() -> Vec<&'static Page> {
    let mut v: Vec<&'static Page> = PAGES.iter().filter(|p| p.shortcut > 0).collect();
    v.sort_by_key(|p| p.shortcut);
    v
}

/// Pages of one Go-menu group, in COMMAND_PAGES order.
pub fn pages_in(group: Group) -> impl Iterator<Item = &'static Page> {
    PAGES.iter().filter(move |p| p.group == group)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    #[test]
    fn exactly_43_unique_ids_and_codes() {
        assert_eq!(PAGES.len(), 43);
        assert_eq!(PAGES.len(), PAGE_COUNT);
        let ids: HashSet<_> = PAGES.iter().map(|p| p.id).collect();
        let codes: HashSet<_> = PAGES.iter().map(|p| p.code).collect();
        assert_eq!(ids.len(), 43, "duplicate tab id");
        assert_eq!(codes.len(), 43, "duplicate function code");
        for p in PAGES.iter() {
            assert!(!p.label.is_empty());
            assert!(
                p.id.chars().all(|c| c.is_ascii_lowercase()),
                "id {} must be [a-z]+",
                p.id
            );
            assert!(
                p.code.chars().all(|c| c.is_ascii_uppercase()),
                "code {} must be [A-Z]+",
                p.code
            );
        }
    }

    #[test]
    fn shortcuts_are_1_to_9_in_ui_tablist_order() {
        let s: Vec<&str> = shortcut_pages().iter().map(|p| p.id).collect();
        // ui/app/page.tsx tabList[0..9] (ALT+1..9)
        assert_eq!(
            s,
            [
                "brief",
                "watch",
                "charts",
                "options",
                "ostrategy",
                "derivatives",
                "movers",
                "events",
                "alerts"
            ]
        );
        let digits: Vec<u8> = shortcut_pages().iter().map(|p| p.shortcut).collect();
        assert_eq!(digits, (1..=9).collect::<Vec<u8>>());
    }

    #[test]
    fn every_page_is_in_exactly_one_group_and_groups_cover_43() {
        let total: usize = Group::ALL.iter().map(|g| pages_in(*g).count()).sum();
        assert_eq!(total, 43);
        for g in Group::ALL {
            assert!(pages_in(g).count() > 0, "empty group {:?}", g);
        }
    }

    #[test]
    fn gold_page_is_the_43rd_in_the_gold_group_without_a_cmd_digit() {
        // Gold program (PLAN Appendix A): id/code/label fixed by the PM; next to CMDT/MCXG; no Cmd+N.
        let gold = by_id("gold").expect("the GOLD page is registered");
        assert_eq!((gold.code, gold.label), ("GOLD", "Gold terminal"));
        assert_eq!(gold.group, Group::DerivativesGold);
        assert_eq!(gold.shortcut, 0, "GOLD must not take a Cmd+1..9 digit");
        let order: Vec<&str> = pages_in(Group::DerivativesGold).map(|p| p.id).collect();
        let i = order
            .iter()
            .position(|id| *id == "mcxgold")
            .expect("MCXG in the gold group");
        assert_eq!(order.get(i + 1), Some(&"gold"), "GOLD sits right after MCXG");
        // The pre-open desk left CMDT (PLAN §b): its label no longer mentions a gold desk.
        let cmdt = by_id("commodity").expect("CMDT");
        assert!(
            !cmdt.label.to_lowercase().contains("gold"),
            "CMDT label still mentions gold: {}",
            cmdt.label
        );
        assert!(
            !is_valid_tab("GOLD"),
            "tab ids are lowercase; GOLD is the function code"
        );
    }

    #[test]
    fn tray_pages_and_default_are_valid() {
        assert!(is_valid_tab(DEFAULT_TAB));
        for t in TRAY_PAGES {
            assert!(is_valid_tab(t), "{t}");
        }
        assert!(!is_valid_tab("Brief"));
        assert!(!is_valid_tab("brief "));
        assert!(!is_valid_tab(""));
        assert!(!is_valid_tab("../system"));
    }
}
