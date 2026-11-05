# SuryaDhana Terminal — Design System Audit + Live Design Review
14 Oct 2026, 21:36 IST · audit-only (fix loop skipped: dirty tree, no-commit session) · target http://localhost:3000 (Next prod) · classifier: **APP UI** (data-dense trader workspace) · evidence: `reports/production_review/screenshots/` (mirrored with this report to `~/.gstack/projects/SuryaDhana_AI/designs/design-audit-20261014/`)

**Design Score: B+** · **AI Slop Score: A** — "hand-built terminal identity; nothing from the template bin."
One line for a PR: *Design review found 15 findings (4 high) — the system is real and consistently applied, but 597 hardcoded hex values, missing tabular numerals, and one floating overlay that sits on top of live charts keep it from an A.*

---

## Phase 1 — First Impression (BRIEF, first-impression.png)

I'm looking at a black screen with an orange MARKETS tape, three status LEDs (DATA · DB · ICICI), a clock, and a red **0/4 RISK-OFF** that my eye hits first. Second, the amber **CRASH FILTER ON** banner inside YOUR BOOK. Third, the green/red results list under THIS WEEK. Those are exactly the three things a trader should see after the close: regime, what my book is doing about it, what just reported. The hierarchy is telling the truth.

- The site communicates **"a working trading operation, not a dashboard demo."**
- I notice **every panel carries its provenance** ("NSE EOD 2026-10-14", "scan 2026-10-13", "last 24 h") — rare, and the single most Bloomberg-like trait here.
- First 3 things my eye goes to: **0/4 RISK-OFF → CRASH FILTER banner → RESULTS REACTING TODAY.** Intended? Yes.
- One word: **operational.**

**Page-Area Test:** MARKET / YOUR BOOK / MARKET TODAY / THIS WEEK / NEWS SCANNER / HEADLINES / SYSTEM / GOLD OPEN — all nameable in under 2 seconds. PASS. The only unnamable strip: the second row of GO chips ("NEW SINCE YOUR LAST VISIT") reads as a chip soup until you spot its label.

---

## Phase 2 — Design System Extraction (rendered) vs the kit (source)

**Rendered reality** (via browse JS):
- **Fonts (3):** JetBrains Mono (workhorse), Chakra Petch (display), Tailwind's system-ui stack leaking through on wrapper nodes. ≤3 ✓; the system-ui leak never carries visible text I could find — acceptable.
- **Palette:** coherent 8-accent dark system — bg #05070A family, text #D6DBE4, muted #6F7A8E/#475063, amber #FFB000, red #FF4D5E, green #16D98A, cyan #39C6FF, violet #B58BFF. <12 non-grays ✓. One stray: pure `rgb(255,255,255)` nodes (should be T.bright #F2F5FA).
- **Type scale:** dominant sizes 13 / 11.5 / 11 / 10 px — deliberate terminal density (Bloomberg idiom), accepted as the documented APP-UI deviation from the 16px web rule. **29+27 elements at 9–9.5px are below even that floor.**
- **Headings:** H3 12px/700 only — the terminal uses panel headers, not a heading scale. Fine for an app UI; no skipped-level issues apply.
- **Touch targets:** 123 interactive elements under 44px (desktop terminal — acceptable; matters if mobile is ever a real surface).
- **`font-variant-numeric: tabular-nums`: 6 elements in the whole app.** For a trading terminal this is the single most consequential typography miss — price columns breathe as digits change width.
- **Perf baseline (BRIEF):** TTFB 1ms · load 825ms · zero console errors on all six audited pages.

**The kit (source):** `ui/components/news/format.ts` exports `T` — 19 tokens + formatters, used **2,413 times** across components (T.dim 370, T.amber 344, T.muted 331, T.green 304, T.red 263 …). A real, heavily-adopted system.

### Design-System Audit (per /design-system)

**Components reviewed:** 73 top-level + kit | **Issues found:** 15 | **Score: 72/100**

#### Naming Consistency
| Issue | Components | Recommendation |
|-------|------------|----------------|
| The design system lives in `ui/components/news/format.ts` — the app-wide kit is named after one feature | every T.* consumer | Move to `ui/lib/terminal.ts`; re-export from the old path for one release |
| Three ambers in production: token `#ffb000`, literal `#FFB200` (17×), Tailwind `#f59e0b` (43×) | QuantKPICard, BacktestPanel, StockDetailModal + 20 more | One token; the two literals are drift, not intent |
| Tailwind palette leaking beside kit colors: `#8b5cf6` (18×) vs T.violet, `#14b8a6` (11×) vs T.cyan, `#475569`/`#6f7a8e` greys | Backtest/ML-era components | Codemod to tokens (top 20 hex cover ~400 of 597 instances) |

#### Token Coverage
| Category | Defined | Hardcoded Values Found |
|----------|---------|------------------------|
| Colors | 16 color tokens, 2,413 usages | **597 hex literals** in ui/components + ui/app |
| Spacing | none (no scale tokens) | inline px everywhere; census: 6px(129) 4(125) 8(113) 10(87) 12(68) **3(36) 5(26) 7(17)** — off-scale values in bold |
| Typography | 2 family tokens | sizes inline per component (9–13px); no size tokens; tabular-nums ×6 |
| Motion | none | transitions sparse/none (reads static; see Motion grade) |

#### Component Completeness (10 core)
| Component | States | Variants | Docs | Score |
|-----------|--------|----------|------|-------|
| Panel/Section header (bar+title+actions) | ✅ | ✅ | ❌ | 8/10 |
| Data table (per-page implementations) | ⚠️ sort ✓, loading ⚠️, tabular ❌ | ✅ | ❌ | 6/10 |
| Chips/badges (ASM, RESULTS, DIVIDEND, regime) | ✅ semantic ✓ | ✅ | ❌ | 8/10 |
| Tab strip + number keys | ✅ active ✓ | ✅ | ❌ | 7/10 (labels truncate: "ML E…") |
| GO command bar | ✅ kbd ✓ hints ✓ | ✅ | ❌ | 8/10 (no recall/history UI) |
| Stock window (modal) | ⚠️ alert-mode z-fight | ✅ 6 tabs | ❌ | 6/10 |
| Charts (intraday, candle+SMA) | ✅ | ✅ | ❌ | 8/10 |
| Alerts editor (inline strip) | ⚠️ overlap, placeholder-as-label | ⚠️ no move-% (bot has it) | ❌ | 5/10 |
| Bell/inbox + toasts | ✅ (inferred) | — | ❌ | 6/10 |
| Loading/empty/error | empty ✅ (22 files, WATCH is model quality) · skeletons **3/73** · error 64/73 | — | ❌ | 6/10 |

No `DESIGN.md` exists. **Offer:** I can lock the extracted system (tokens, type sizes, spacing scale, panel anatomy, chip semantics) into `DESIGN.md` as the baseline — say the word.

---

## Phase 3 — Page Audits (six deep)

### BRIEF (first-impression.png) — Trunk test: PASS 6/6
Site ID ✓ (SURYADHANA ▸ BRIEF) · page chip ✓ · sections ✓ · options ✓ · you-are-here ✓ (amber tab #1) · search ✓ (⌕ GO + "/" hint in footer).
- [F-012, polish] Tape's last item truncates ("GOLD 4,1…"); "ML E…" tab label truncated at 1280px.
- [F-001, HIGH] NEWS SCANNER floating pill (bottom-right) overlaps content when panels are tall.
- Microcopy is exemplary: zero happy talk — **this page has ~2,600 visible words and I count 0% filler**; every line is a number or a pointer. "NEEDS YOU 3" with HOW TO FIX is the correct error-surfacing pattern.

### WATCH (watch.png) — Trunk test: PASS
- **Model empty state** (warm line + three concrete actions). KPI zeros + em-dashes honest.
- [F-015, MEDIUM — Bloomberg lens] Footnote admits "Yahoo ~1 minute delayed; ICICI live quotes… on the Broker tab" while an ICICI session is connected. A trader's watchlist is the one place that must be live: promote source to a per-panel `LIVE/DELAYED·60s` chip and prefer Breeze when connected.

### DESK (desk.png) — Trunk test: PASS
- [F-001, HIGH] News pill sits **on top of the Book-vs-NIFTY chart** — data hidden behind chrome on the page where the money lives.
- [F-014, polish] Watchlist LAST column clips ("₹311.7…", "₹2,717.0…") — give the column `min-width` + tabular-nums.
- RULES panel (owner-approved date), charges line, "describes the basket, not a forecast" caption: honest-by-design, keep.
- KPI "BOOK VALUE" carries a tab-style amber underline but isn't a tab [polish].

### MARKETS (markets.png) — Trunk test: PASS
- The flagship. Market map, breadth year, valuation chips, rotation quadrant, participant futures — true terminal density, properly grouped; squint test holds (color blocks = sections).
- [F-011-adjacent, MEDIUM] Industry-rotation scatter is a 9px-label hairball in the left half; show labels on hover/leaders only.
- Valuation table: percentile chips excellent; this is the panel to steal patterns from.

### Stock window / GO flow (stock-tcs.png, alert-editor.png)
- "/" → `TCS` → Enter → full window in ~1s with candle+4 SMAs, range switcher, Profile/Data/Chart/HP/SEAG tabs, PIN/WATCHLIST/ALERT/TRADINGVIEW/YAHOO actions, dividend chip. **This is the magic moment** — Bloomberg's `TCS <GO>` equivalent, and it works.
- [F-004, HIGH] ALERT mode: the inline strip (`ALERT TCS [above ₹][below ₹][SET][×]`) **renders over the price/“+ WATCHLIST” chips** — z-fight, text-through-text (alert-editor.png, top-left). Conditional-render the action row away while alert mode is open (`StockDetailModal.tsx`).
- [F-008, MEDIUM] `above ₹ / below ₹` are placeholder-as-label inputs; tiny ✕ close target; no `move %` option though the Telegram bot supports it — parity gap.
- [F-006, MEDIUM] Modal is a floating card with no dimmed backdrop; page behind stays full-contrast and scroll-competes.

### RSCH (research.png) — Trunk test: PARTIAL (4/6 — inside a long doc you lose "where am I/what are siblings")
- [F-011, MEDIUM] Opening a study renders the **entire** markdown + tables inline → a ~50,000-px page; heavy scroll, sticky overlays glitch across it. Collapse sections by default / paginate the doc pane.

---

## Phase 4 — Interaction Flows (goodwill meter, start 70)

**Flow A: "what moved today → open it → set an alert"** (narrated)
I land on BRIEF; MOV chip is visible in the morning row (+5, obvious path). I press "/" — the GO bar focuses instantly with placeholder guidance (+5). I type TCS, Enter; window opens <1s with the chart already ranged (+10, saves steps). I click ALERT; an inline strip appears — compact, but it collides with the price chip and I hesitate parsing above-vs-below boxes with no labels (−5, ambiguous choice; −5, sloppy overlap). I don't save (audit rule) and ESC out — first ESC closes the strip, second the window: predictable (+5). **Flow A: 75 → healthy.**

**Flow B: keyboard navigation** — number keys 1–0 switch tabs, footer advertises ALT+1..8 / SHIFT+N / ? / ESC; GO accepts page codes (WEI/ECO/MOV…) and tickers. Trader-grade. (+10 would apply but meter capped per flow; recorded qualitatively.)

```
Goodwill: 70 ███████████████░░░░░
  GO bar + instant stock window     +20
  Alert-strip overlap + bare inputs −10
  News pill over charts             −5
  FINAL ≈ 75/100 — healthy; the drains are all fixable chrome
```

---

## Phase 5 — Cross-Page Consistency: **A**
Header/tape/tab-strip/footer identical on all six pages; panel anatomy (left bar + CAPS title + muted meta + action chevrons) never varies; semantic colors never flip (green=up everywhere); telegraphic-caps tone uniform. One-off styling exists mainly in Backtest/ML-era components (the Tailwind-hex set) — visible as slightly different ambers/violets if you look for them (F-003).

---

## Phase 6 — Bloomberg-Trader Lens (what the terminal still lacks, UI layer)

| Bloomberg has | SuryaDhana today | Gap / recommendation |
|---|---|---|
| Sub-100ms panel interactions | Tab/GO switches feel instant; chart modals ~1s | ✓ keep; prefetch stock-window data on hover to shave the 1s |
| **Live** quotes everywhere, source-labelled | ICICI live exists but WATCH runs 60s Yahoo; provenance in footnotes | F-015: per-panel LIVE/DELAYED chip; Breeze-first when connected |
| Tabular numerals, fixed-width columns | mono font but tabular-nums ×6 | F-002: one CSS line in the kit table style |
| Command **recall** (recent functions) | GO has codes, no history | add ↑-history + "recent" chips under GO |
| Function chaining (`TCS GP <GO>` …) | GO takes `TCS HP` already (seen in chips) | document + autocomplete chains; it's 80% built |
| Panel linking (A-group: click ticker → all panels follow) | Stock window is modal-only | later: optional "linked mode" where WATCH selection drives EVTS/NEWS panels |
| Multi-window | single window | out of scope now; note for a pop-out chart v2 |
| Alerts parity across surfaces | UI has above/below; bot adds move% | F-008: add move% to the inline editor |
| Stale-data alarms | DataHealthBar + NEEDS-YOU exist ✓ | extend chip to every data panel (as-of is already there — color it when stale) |

Density verdict: BRIEF/DESK/MARKETS sit at genuine terminal density **without** noise — the empty-state and provenance discipline is better than most professional products. The misses are mechanical (numerals, overlays, hex drift), not conceptual.

---

## Findings Register

| ID | Impact | Category | Finding (evidence) | Fix |
|---|---|---|---|---|
| F-001 | HIGH | Hierarchy/Z | News pill overlays charts on DESK/MARKETS/modal (desk.png, markets.png) | Dock into footer bar right slot; auto-collapse to 🔔 when a panel intersects |
| F-002 | HIGH | Typography | tabular-nums on 6 elements only | Kit-level `fontVariantNumeric:'tabular-nums'` for all numeric cells |
| F-003 | HIGH | Color system | 597 hex literals; 3 ambers, 2 violets/teals (grep census in Phase 2) | Move kit to `ui/lib/terminal.ts`; codemod top-20 hexes → tokens |
| F-004 | HIGH | Interaction | Alert strip z-fights price/watchlist chips (alert-editor.png) | Hide action row while alert mode open (`StockDetailModal.tsx`) |
| F-005 | MED | Typography | 56 elements at 9–9.5px | Floor at 10px |
| F-006 | MED | Responsive | Stock modal stays floating card at 375px; no backdrop dim (brief-mobile.png) | Full-screen sheet <768px; `rgba(5,7,10,.7)` backdrop always |
| F-007 | MED | States | Skeletons in 3/73 components | Kit Skeleton; adopt in 10 heaviest panels |
| F-008 | MED | A11y/parity | aria in 11/73; placeholder-as-label alert inputs; no move-% | Labels above inputs; add move%; aria-label icon buttons |
| F-009 | MED | Naming | Kit lives in `components/news/format.ts` | Relocate + re-export |
| F-010 | MED | Spacing | Off-scale 3/5/6/7px beside 4/8/12 | Adopt 4px scale in kit constants |
| F-011 | MED | Content/perf | RSCH renders whole studies inline (research.png) | Collapsed sections / doc pagination |
| F-012 | POLISH | Layout | Tape truncation; "ML E…" tab label | Priority-trim tape; shorten label "ML" |
| F-013 | POLISH | Color | Pure #FFF nodes | Use T.bright |
| F-014 | POLISH | Tables | DESK LAST column clips | min-width + F-002 |
| F-015 | MED | Bloomberg lens | WATCH on 60s Yahoo while ICICI live connected | LIVE/DELAYED chip + Breeze-first quotes |

**Quick Wins (<30 min each):** F-002 (one kit line + cell class), F-004 (conditional render), F-013, F-014, F-012-tab-label.
**Deferred (fix loop skipped this session):** all 15 — F-001…F-015 ranked above; nothing requires structural rework.

## Grades
| Category | Grade | Driver |
|---|---|---|
| Visual Hierarchy & Composition | B | F-001 (else A) |
| Typography | B− | F-002 high, F-005 |
| Color & Contrast | B | F-003 (contrast itself passes AA on sampled pairs) |
| Spacing & Layout | B+ | F-010, F-014 |
| Interaction States | B− | F-004, F-007 |
| Responsive | B | stacking genuinely redesigns; F-006 |
| Motion & Animation | C+ | essentially static; no purposeful motion, nothing broken |
| Content & Microcopy | **A** | zero happy talk; provenance everywhere; model empty states |
| AI Slop | **A** | none of the 11 blacklist patterns |
| Performance as Design | A− | 825ms load, clean console; RSCH weight |

**CLAUDE SUBAGENT (design consistency, source pass) [single-model]:** spacing is per-component inline px (no scale constants anywhere in ui/lib); ONE color system exists but three ambers prove copy-paste drift (`QuantKPICard.tsx`, `BacktestPanel.tsx`, `StockDetailModal.tsx` carry `#f59e0b`/`#FFB200` beside `T.amber` imports); breakpoints are ad-hoc `repeat(auto-fit,minmax(…))` per component (23×) with no shared constants — works, undocumented; a11y attributes appear in only 11/73 components (ErrorCatcher/LoadingOverlay fine, tables bare). Verdict: the system is real and loved in 80% of the code; the 2025-era Backtest/ML components predate the kit and are the drift pocket.
