# Trade Explorer — Visual Interface Guide

## Full Dashboard Layout

```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃  ₹ TRADE EXPLORER                                    v1.0 PREMIUM ANALYTICS   ┃
┃  367 trades · 206 wins · +1.29% avg return                                   ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃                                                                                ┃
┃   ┌──────────────────┐    ┌───────────────────────────────────────────────┐  ┃
┃   │   FILTERS        │    │  CALENDAR HEATMAP — Trade Performance by Date  │  ┃
┃   │                  │    │                                                │  ┃
┃   │ 📅 Date Range    │    │   Su Mo Tu We Th Fr Sa  [Darker = Better ↓]   │  ┃
┃   │ [2026-05-01]     │    │                                                │  ┃
┃   │ [2026-05-23]     │    │ [🟢][🟢][🟢][🟢][🟨][🟨][🟨] 3W 0L +1.8%   │  ┃
┃   │                  │    │ [🟨][🟨][🟨][🟧][🟧][🟧][🟥] 1W 2L -0.3%   │  ┃
┃   │ 🔍 Ticker        │    │ [🟢][🟢][🟨][🟨][🟩][🟩][🟩] 2W 1L +2.1%   │  ┃
┃   │ [Search...]      │    │ [🟨][🟩][🟩][🟩][🟨][🟨][🟩] 4W 1L +1.5%   │  ┃
┃   │                  │    │ [🟩][🟩][🟩][⬜][⬜][🟥][🟧] 2W 1L +0.9%   │  ┃
┃   │ 📊 Return Range  │    │ [🟥][🟥][🟧][🟧][🟨][🟨][🟨] 0W 2L -1.2%   │  ┃
┃   │ [-100%] [+100%] │    │ [🟩][🟩][🟩][🟩][🟩][🟥][🟥] 3W 1L +1.7%   │  ┃
┃   │                  │    │                                                │  ┃
┃   │ ✓ Winning Only   │    └───────────────────────────────────────────────┘  ┃
┃   │                  │                                                       ┃
┃   │ ───────────────  │                                                       ┃
┃   │ SECTORS          │                                                       ┃
┃   │ ───────────────  │                                                       ┃
┃   │ ✓ Banking (45)   │    ┌───────────────────────────────────────────────┐  ┃
┃   │   ├─ HDFC Bank   │    │ TRADE LIST — Sortable & Expandable             │  ┃
┃   │   ├─ ICICI Bank  │    │                                                │  ┃
┃   │   └─ SBIN Axis   │    │ Date  ▼│ Ticker  │ Entry  │ Exit   │ Return  │  ┃
┃   │ Energy (18)      │    │────────────────────────────────────────────────│  ┃
┃   │   ├─ RELIANCE    │    │ 05-15  │ ACUATAS │ ₹2731  │ ₹2951  │ +8.06% │  ┃
┃   │   └─ ADANIPOWER  │    │        │ Entry: ₹2731 | Exit: ₹2951 | ✓ WIN  │  ┃
┃   │ IT (32)          │    │────────────────────────────────────────────────│  ┃
┃   │   ├─ TCS         │    │ 05-14  │ RELIANCE│ ₹2500  │ ₹2480  │ -0.80% │  ┃
┃   │   ├─ INFY        │    │        │ Entry: ₹2500 | Exit: ₹2480 | ✗ LOSS │  ┃
┃   │   └─ WIPRO       │    │────────────────────────────────────────────────│  ┃
┃   │ Auto (12)        │    │ 05-13  │ TCS     │ ₹3400  │ ₹3552  │ +4.47% │  ┃
┃   │ FMCG (8)         │    │        │ Entry: ₹3400 | Exit: ₹3552 | ✓ WIN  │  ┃
┃   │                  │    │─────────────────────────────────────────────── │  ┃
┃   │                  │    │ [← Prev] Page 1 of 19 [Next →]                │  ┃
┃   │                  │    └───────────────────────────────────────────────┘  ┃
┃   │                  │                                                       ┃
┃   └──────────────────┘                                                       ┃
┃                                                                                ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃ SUMMARY STATISTICS                                                             ┃
┃ ┌─────────────────┬─────────────────┬──────────────────┬────────────────────┐ ┃
┃ │ Total Trades    │ Win Rate        │ Avg Return       │ Total Return       │ ┃
┃ │      367        │      56.1%      │     +1.29%       │      +474.3%       │ ┃
┃ └─────────────────┴─────────────────┴──────────────────┴────────────────────┘ ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

LEGEND:
🟢 Emerald   = +2% avg return (best days)
🟩 Green     = +0.5-2% avg return
🟨 Yellow    = -0.5 to +0.5% avg return
🟧 Orange    = -0.5 to -1% avg return
🟥 Red       = < -1% avg return (worst days)
⬜ Gray      = No trades

COLOR CODING:
✓ WIN        = Green text / Green left border
✗ LOSS       = Red text / Red left border
```

---

## Color Reference

### Heatmap Intensity Scale

```
Best Days:           Good Days:           Neutral:             Bad Days:           Worst Days:
═════════            ═════════            ═══════              ════════            ══════════
🟢 Emerald           🟩 Light Green       🟨 Amber             🟧 Orange           🟥 Rose Red
+2% to +5%           +0.5% to +2%         -0.5% to +0.5%       -0.5% to -1%        -1% to -5%

Examples:
🟢 🟢 🟢             🟩 🟩 🟨             🟨 🟨 🟨             🟧 🟧 🟧             🟥 🟥 🟥
3W 0L +2.8%          2W 1L +1.2%          1W 1L +0.2%          0W 2L -0.8%          0W 3L -2.1%
```

---

## Interactive Elements

### 1. Sector Sidebar (Click to Expand/Filter)

```
SECTORS
───────────────────────
✓ Banking (45)           ← Currently selected (gold)
  ├─ HDFC Bank           ← Show top stocks
  ├─ ICICI Bank
  ├─ SBIN
  ├─ Axis Bank
  └─ +40 more

Energy (18)              ← Available sectors
IT (32)
Auto (12)
FMCG (8)
```

**Interaction**:
- Click sector name → Filter results to that sector
- Click again → Remove filter (show all)
- Expand arrow → Show top 5 stocks in sector
- Highlighted in amber when selected

### 2. Filter Panel (Real-time Updates)

```
FILTERS
───────────────────────
📅 Date Range
   From: [2026-05-01]   ← Pick start date
   To:   [2026-05-23]   ← Pick end date
   
🔍 Ticker Search
   [Search RELIANCE...] ← Type partial match
   
📊 Return Range
   Min: [-100%] [%]     ← Losing trades
   Max: [+100%] [%]     ← Winning trades
   
✓ Winning Only          ← Toggle checkbox
   Checked = show only wins
```

**Behavior**:
- All updates are real-time
- Calendar, list, and stats update instantly
- No manual "Apply" button needed

### 3. Calendar Heatmap

```
           Su  Mo  Tu  We  Th  Fr  Sa
           ──  ──  ──  ──  ──  ──  ──
Week 1:  [🟢][🟢][🟢][🟨][🟨][🟧][🟥]   3W 2L 1L | +1.2%
Week 2:  [🟩][🟩][⬜][⬜][🟨][🟨][🟨]   2W 0L 0L | +0.8%
Week 3:  [🟢][🟢][🟢][🟢][🟢][🟩][🟨]   5W 0L 1L | +2.1%
Week 4:  [🟩][🟧][🟧][🟥][🟥][🟥][⬜]   1W 3L 1L | -1.5%

Each square = 1 day
Hover to see: "2W 0L +1.8%"
```

**Features**:
- Responsive grid layout
- Hover tooltip with details
- Click date to jump to trades
- Scroll for longer date ranges

### 4. Trade List (Expandable Rows)

```
Normal Row:
┌─────────────────────────────────────────────────────────────┐
│ 05-15  │ ACUATAS │ ₹2731  │ ₹2951  │ +8.06%  │ ✓ WIN      │
└─────────────────────────────────────────────────────────────┘
         ↑ Click to expand

Expanded Row:
┌─────────────────────────────────────────────────────────────┐
│ 05-15  │ ACUATAS │ ₹2731  │ ₹2951  │ +8.06%  │ ✓ WIN      │
├─────────────────────────────────────────────────────────────┤
│  Entry Price: ₹2731.00  │  Exit Price: ₹2951.00            │
│  Return: +8.06%         │  Status: WINNING TRADE           │
└─────────────────────────────────────────────────────────────┘
```

---

## Sorting Controls

### Column Headers (Clickable)

```
Date ▼     │ Ticker    │ Entry  │ Exit   │ Return  │ Result
────────────────────────────────────────────────────────────
  ▼ = Descending (Z-A, high-to-low)
  ▲ = Ascending (A-Z, low-to-high)
  
Click header again to toggle direction.

Examples:
────────────────────────────────────────────────────────────
Date ▼     → Most recent trades first
Ticker ▲   → Alphabetical (A-Z)
Return ▼   → Best returns first
Entry ▲    → Cheapest entry prices first
```

---

## Summary Statistics Footer

```
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┓
┃ Total Trades   ┃ Win Rate       ┃ Avg Return     ┃ Total Return   ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━┩
│      367       │      56.1%     │     +1.29%     │     +474.3%    │
│   (filtered)   │   (win ratio)  │  (per trade)   │  (cumulative)  │
└────────────────┴────────────────┴────────────────┴────────────────┘

All numbers update when filters change.
```

---

## Mobile Responsive

### Desktop (Full Width)
```
[FILTERS][Calendar Heatmap][Trade List]
  240px      60% width        remaining
```

### Tablet (Stacked)
```
[Calendar Heatmap]
[FILTERS]
[Trade List]
```

### Mobile (Collapsed)
```
[FILTERS - Collapsible]
[Calendar Heatmap - Horizontal Scroll]
[Trade List - Vertical Scroll]
```

---

## Visual Design Details

### Fonts & Sizing
```
Title          "₹ TRADE EXPLORER"     24px bold amber gradient
Subtitle       "v1.0 PREMIUM..."      12px gray
Section Header "FILTERS / SECTORS"    12px uppercase amber
Data Numbers   Trade prices/returns    monospace (IBM Plex Mono)
Labels/Text    Descriptions            sans-serif (system font)
```

### Spacing & Layout
```
Container padding:    24px (desktop), 16px (tablet), 8px (mobile)
Section margin:       24px between major sections
Element gap:          8px between items
Border radius:        8px on rounded corners
Line height:          1.5 for readability
```

### Shadows & Depth
```
Card elevation:       subtle drop shadow (2px 4px 8px rgba(0,0,0,0.2))
Hover effect:         light background tint (opacity 0.05)
Active element:       amber/gold highlight with glow
Focus state:          border highlight + slight elevation
```

### Transitions
```
Hover effects:        200ms ease-in-out
Filter changes:       300ms fade-in for updates
Sort animations:      150ms transition
Expand/collapse:      200ms height transition
Hover color:          smooth 150ms transition
```

---

## Interaction Patterns

### On Hover (Interactive Elements)

```
Normal State:
┌─────────────────┐
│ [Button]        │
│ gray bg         │
└─────────────────┘

Hovered State:
┌─────────────────┐
│ [Button]  ← Slightly darker, darker border
│ darker bg       │
└─────────────────┘

Selected State:
┌─────────────────┐
│ [Button]  ← Amber/gold background
│ amber bg        │
└─────────────────┘
```

### On Click (Expandable Rows)

```
Before:
│ 05-15 │ ACUATAS │ ₹2731 │ ₹2951 │ +8.06% │ ✓ WIN │

After (click):
│ 05-15 │ ACUATAS │ ₹2731 │ ₹2951 │ +8.06% │ ✓ WIN │
├──────────────────────────────────────────────────────│
│ Entry: ₹2731  │  Exit: ₹2951  │  Return: +8.06%     │
```

---

## Color Palette

### Primary Colors
```
Background:     Slate-950 (#020617)
Cards:          Slate-800 (#1e293b)
Accent:         Amber-500 (#f59e0b)
Text Primary:   Slate-100 (#f1f5f9)
Text Secondary: Slate-400 (#94a3b8)
```

### Status Colors
```
Winning:    Emerald (#10b981)
Losing:     Rose (#f43f5e)
Neutral:    Amber (#f59e0b)
Info:       Slate (#64748b)
Good:       Green (#22c55e)
Bad:        Red (#dc2626)
```

### Chart Colors
```
Best Day:       Emerald-700 (#047857)
Good Day:       Emerald-600 (#059669)
Okay Day:       Teal-600 (#0d9488)
Weak Day:       Amber-600 (#b45309)
Bad Day:        Orange-600 (#ea580c)
Worst Day:      Rose-700 (#be123c)
No Trades:      Slate-800 (#1e293b)
```

---

## Accessibility Features

✅ **Color Contrast**: All text meets WCAG AA standards (4.5:1 minimum)
✅ **Focus States**: Clear keyboard navigation with visible focus rings
✅ **Semantic HTML**: Proper heading hierarchy and button roles
✅ **Responsive**: Works on all screen sizes down to 320px
✅ **Keyboard Navigation**: Tab through filters, sort, expand trades
✅ **Screen Readers**: Proper ARIA labels and descriptions
✅ **Motion**: Respects `prefers-reduced-motion` setting

---

**All elements combine to create a professional, data-focused analytics dashboard that feels like a high-end trading terminal.**
