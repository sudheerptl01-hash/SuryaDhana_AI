"""Generate ml/report/community_calibration.html: "How good is good enough?".

A management page on what the internet reports for ML stock prediction, how good is good
enough, and where SuryaDhana sits. It is a renderer, not an analysis:

* narrative, tables and verdicts are parsed at run time from
  ml/research/community/COMMUNITY_CALIBRATION.md (the lead's synthesis) and ml/GOALS.md, and
  rendered in their order with their hedges;
* every external number that exists in one of the three evidence files
  (ml/research/community/{reddit_forums,youtube_quora_media,competitions_platforms}.json) is
  read from that file, and the Markdown's copies are checked against it: where they disagree
  the page shows the JSON value and the run prints the discrepancy;
* SuryaDhana's rank IC (with its Newey-West t and positive months) is read from
  ml/results/scale5y/scale5y_summary.json; its other five-year numbers come from the two
  Markdown files and are cross-checked against that summary;
* derived numbers (Sheppard hit rates, cost arithmetic, grade counts) are computed here.

Output: one self-contained HTML file (inline CSS, SVG and the pilot's tooltip script; no
external resources), byte-for-byte deterministic. Reads JSON and Markdown only.

Run:  cd /home/user/SuryaDhana_AI && python3 -m ml.make_community_report
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from statistics import NormalDist

ROOT = Path(__file__).resolve().parent                     # ml/
COMM = ROOT / "research" / "community"
CAL_MD = COMM / "COMMUNITY_CALIBRATION.md"
GOALS_MD = ROOT / "GOALS.md"
SUMMARY_JSON = ROOT / "results" / "scale5y" / "scale5y_summary.json"
PILOT_HTML = ROOT / "report" / "index.html"                # design-system reference only
OUT = ROOT / "report" / "community_calibration.html"

RD, YT, CP = "reddit_forums", "youtube_quora_media", "competitions_platforms"
STREAM_KEYS = (RD, YT, CP)

# ============================================================== small helpers


def esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def inline(s: str) -> str:
    """The inline Markdown these notes use: `code` and **bold** (text is escaped first)."""
    s = esc(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)


def plain(s: str) -> str:
    return re.sub(r"\*\*|`", "", s)


def unnumber(title: str) -> str:
    """'2.1 The loud genre' -> 'The loud genre' (the page has its own numbering)."""
    return re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", title)


def lin(v, d0, d1, p0, p1):
    return p0 + (v - d0) / (d1 - d0) * (p1 - p0)


def num(s: str) -> float:
    return float(s.replace("−", "-").replace(",", "").replace("+", ""))


def fnum(v: float, d: int = 2) -> str:
    """Shortest faithful rendering: 87.6 -> '87.6', 98.0 -> '98', 50.75 -> '50.75', 500 -> '500'."""
    s = f"{v:.{d}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def sgn(v: float, d: int = 1) -> str:
    """Signed number with a typographic minus: +7.0, −0.7."""
    return f"{v:+.{d}f}".replace("-", "−")


def hit(ic: float) -> float:
    """Sheppard: P(sign agreement) for jointly normal forecast and return, in percent."""
    return 100 * (0.5 + math.asin(ic) / math.pi)


def ic_for(hit_pct: float) -> float:
    return math.sin(math.pi * (hit_pct / 100 - 0.5))


NUM_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve".split())}
ORDINALS = {w: i for i, w in enumerate(
    "zeroth first second third fourth fifth sixth seventh eighth ninth tenth".split())}


# =========================================================== Markdown parser


def split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def parse_md(text: str) -> list[dict]:
    """Parse the Markdown subset the program notes use into sections of blocks:
    ("p", text) | ("ul", [items]) | ("ol", [items]) | ("table", {"head", "rows"}).
    Headings open sections; '---' rules are dropped; inline markup stays raw."""
    secs: list[dict] = [{"level": 0, "title": "", "blocks": []}]
    lines = text.splitlines()
    i, n = 0, len(lines)
    para: list[str] = []

    def flush() -> None:
        if para:
            secs[-1]["blocks"].append(("p", " ".join(para)))
            para.clear()

    while i < n:
        raw = lines[i]
        s = raw.strip()
        h = re.match(r"(#{1,6})\s+(.*)", s)
        if h:
            flush()
            secs.append({"level": len(h.group(1)), "title": h.group(2).strip(), "blocks": []})
            i += 1
        elif s == "---":
            flush()
            i += 1
        elif s.startswith("|"):
            flush()
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            if len(rows) < 2 or not all(re.fullmatch(r":?-{3,}:?", c) for c in rows[1]):
                raise SystemExit(f"malformed Markdown table starting {rows[0]}")
            secs[-1]["blocks"].append(("table", {"head": rows[0], "rows": rows[2:]}))
        elif raw.startswith("- "):
            flush()
            items: list[str] = []
            while i < n and (lines[i].startswith("- ")
                             or (items and lines[i].startswith("  ") and lines[i].strip())):
                if lines[i].startswith("- "):
                    items.append(lines[i][2:].strip())
                else:
                    items[-1] += " " + lines[i].strip()
                i += 1
            secs[-1]["blocks"].append(("ul", items))
        elif re.match(r"\d+\.\s", raw):
            flush()
            items = []
            while i < n:
                m = re.match(r"\d+\.\s+(.*)", lines[i])
                if m:
                    items.append(m.group(1).strip())
                elif items and lines[i].startswith("   ") and lines[i].strip():
                    items[-1] += " " + lines[i].strip()
                else:
                    break
                i += 1
            secs[-1]["blocks"].append(("ol", items))
        elif not s:
            flush()
            i += 1
        else:
            para.append(s)
            i += 1
    flush()
    return secs


def sec(secs: list[dict], prefix: str) -> dict:
    hits = [s for s in secs if s["title"].startswith(prefix)]
    if len(hits) != 1:
        raise SystemExit(f"expected one Markdown section starting {prefix!r}, found {len(hits)}")
    return hits[0]


def blocks(s: dict, kind: str) -> list:
    return [b for k, b in s["blocks"] if k == kind]


def para(s: dict, prefix: str) -> str:
    for k, b in s["blocks"]:
        if k == "p" and plain(b).startswith(prefix):
            return b
    raise SystemExit(f"no paragraph starting {prefix!r} in section {s['title']!r}")


def trow(table: dict, prefix: str) -> list[str]:
    hits = [r for r in table["rows"] if plain(r[0]).startswith(prefix)]
    if len(hits) != 1:
        raise SystemExit(f"expected one table row starting {prefix!r}, found {len(hits)}")
    return hits[0]


def grab(pat: str, text: str, what: str):
    m = re.search(pat, text)
    if not m:
        raise SystemExit(f"could not read {what}: {pat!r} not found in {plain(text)[:160]!r}")
    g = [num(x) for x in m.groups()]
    return g[0] if len(g) == 1 else g


# ===================================================== discrepancy machinery

DISCREPANCIES: list[str] = []      # Markdown vs evidence JSON (page shows the JSON value)
PROGRAM_NOTES: list[str] = []      # Markdown vs scale5y_summary.json (reported only)


def note(msg: str, bucket: list[str] = DISCREPANCIES) -> None:
    if msg not in bucket:
        bucket.append(msg)


def fmt_like(md_num: str, v: float) -> str:
    if "," in md_num:
        return f"{v:,.0f}"
    d = len(md_num.split(".", 1)[1]) if "." in md_num else 0
    return f"{v:.{d}f}"


def check(where: str, text: str, pat: str, v: float, group: int = 1) -> str:
    """Compare the number pat captures in Markdown text with evidence value v at the
    Markdown's precision; on disagreement return the text carrying the JSON value."""
    m = re.search(pat, text)
    if not m:
        raise SystemExit(f"[{where}] Markdown pattern {pat!r} not found in {plain(text)[:160]!r}")
    md = m.group(group)
    js = fmt_like(md, v)
    if js != md:
        note(f"{where}: Markdown {md}, evidence JSON {fnum(v, 5)}; page shows {js}")
        return text[:m.start(group)] + js + text[m.end(group):]
    return text


def check_word(where: str, text: str, pat: str, v: float, words: dict) -> str:
    m = re.search(pat, text)
    if not m:
        raise SystemExit(f"[{where}] Markdown pattern {pat!r} not found")
    if words.get(m.group(1).lower()) != int(v):
        note(f"{where}: Markdown '{m.group(1)}', evidence JSON {v:g}")
    return text


def checks(where: str, text: str, items: list[tuple]) -> str:
    for pat, v in items:
        text = check(where, text, pat, v)
    return text


def agree(where: str, md_value: str, value: float) -> None:
    """Program numbers: Markdown vs scale5y_summary.json, reported, not patched."""
    js = fmt_like(md_value, value)
    if js != md_value:
        note(f"{where}: Markdown {md_value}, scale5y_summary.json {fnum(value, 5)}", PROGRAM_NOTES)


# ======================================================================= inputs

CAL = parse_md(CAL_MD.read_text())
GOALS = parse_md(GOALS_MD.read_text())
SUMMARY = json.loads(SUMMARY_JSON.read_text())


def load_evidence() -> dict[str, list[dict]]:
    ev: dict[str, list[dict]] = {}
    for key in STREAM_KEYS:
        rows = json.loads((COMM / f"{key}.json").read_text())
        out = []
        for i, e in enumerate(rows):
            e = dict(e)
            e["_stream"], e["_n"] = key, i + 1
            e["_claim"] = e["claimed_value"] if "claimed_value" in e else e["value"]
            e["_notes"] = e["method_notes"] if "method_notes" in e else e["what_it_means"]
            out.append(e)
        ev[key] = out
    return ev


EV = load_evidence()
ALL = [e for k in STREAM_KEYS for e in EV[k]]


def area_name(key: str) -> str:
    """'Area A: Reddit and forums', from the narrative's own **From:** line."""
    head = (COMM / f"{key}.md").read_text().split("\n\n", 2)[1]
    m = re.search(r"area ([ABC])\W+([^)·]+?)\)", head)
    if not m:
        raise SystemExit(f"no 'area X' label in {key}.md")
    desc = m.group(2).strip()
    return f"Area {m.group(1)}: {desc[0].upper()}{desc[1:]}"


AREAS = {k: area_name(k) for k in STREAM_KEYS}


def E(stream: str, prefix: str) -> dict:
    hits = [e for e in EV[stream] if e["title"].startswith(prefix)]
    if len(hits) != 1:
        raise SystemExit(f"{stream}: title prefix {prefix!r} matched {len(hits)} entries")
    return hits[0]


def jv(e: dict, pat: str, field: str = "_claim"):
    m = re.search(pat, e[field])
    if not m:
        raise SystemExit(f"{e['_stream']} #{e['_n']} ({e['title'][:40]}): {pat!r} not in {field}")
    g = [num(x) for x in m.groups()]
    return g[0] if len(g) == 1 else g


def views(e: dict) -> int | None:
    m = re.match(r"([\d,]+) views", e.get("views_or_reach", ""))
    return int(m.group(1).replace(",", "")) if m else None


def grade_counts(rows: list[dict]) -> dict[str, int]:
    return {g: sum(1 for e in rows if e["credibility"] == g) for g in "ABC"}


# ============================================================ evidence numbers

X: dict = {}
e_compsci = E(YT, "Stock Price Prediction Using Python & Machine Learning")
e_siraj = E(YT, "How to Predict Stock Prices Easily")
e_krish = E(YT, "Stock Price Prediction And Forecasting Using Stacked LSTM")
e_debunk = E(YT, "LSTM Top Mistake In Price Movement Predictions")
for k, e in (("compsci", e_compsci), ("siraj", e_siraj), ("krish", e_krish), ("debunk", e_debunk)):
    X["views_" + k] = views(e)
X["views_date"] = re.search(r"on (\d{4}-\d\d-\d\d)", e_compsci["views_or_reach"]).group(1)
e_flovik = E(YT, "How (not) to use Machine Learning for time series forecasting: Avoiding")
X["r2_flovik"] = jv(e_flovik, r"R² = (0\.\d+)")
e_aungsi = E(YT, "LSTMs in Price Prediction")
X["r2_aungsi"] = jv(e_aungsi, r"R² (0\.\d+)")
e_gulati = E(YT, "The Verdict: What 14 Models")
X["gulati_models"] = jv(e_gulati, r"beat all (\d+) models")
X["gulati_rank"] = jv(e_gulati, r"LSTM ranked (\d+)th")
e_twitter = E(RD, "Twitter Mood Predicts")
X["twitter_acc"] = jv(e_twitter, r"(\d+\.\d+)%")
X["twitter_days"] = jv(e_twitter, r"about (\d+) trading days", "_notes")
e_pyprog = E(RD, "Stock Prediction Over 90 Percent Accuracy")
X["pyprog_acc"] = jv(e_pyprog, r"over (\d+)%")
e_raja = E(YT, "Using Supervised Machine Learning Models")
X["raja_long"] = jv(e_raja, r"about (\d+)% at 40-60 days")
X["raja_tuned"], X["raja_window"] = jv(e_raja, r"(\d+\.\d+)% at a tuned (\d+)-day window")
e_etwin = E(RD, "Targets on Machine Learning approach")
X["et_win"] = jv(e_etwin, r"(\d+)% win-rate")
X["et_million"] = jv(e_etwin, r"over (\d+) million strategies", "_notes")
e_saka = E(YT, "Guide to Long Short Term Memory")
X["saka_acc"] = jv(e_saka, r"accuracy (\d+\.\d+)%")
X["saka_stocks"] = jv(e_saka, r"of (\d+) stocks")
e_3012 = E(RD, "is end of 2024 quantopian")
X["r30"], X["r120"] = jv(e_3012, r"(\d+)-(\d+)% monthly")
e_mercer = E(CP, "Institutional Investor: Medallion")
e_mercer_x = E(YT, "Mercer 50.75% quote")
X["mercer"] = jv(e_mercer, r"(\d+\.\d+)% of trades")
e_manahl = E(CP, "IBTimes: Man AHL")
e_news = E(YT, "'They saw the future")
X["news_hit"] = jv(e_news, r"called direction (\d+\.\d+)%")
X["news_bust"] = jv(e_news, r"about (\d+)% went bust")
e_nifty = E(YT, "How to Forecast Stock Index Movement")
X["nifty_lo"] = jv(e_nifty, r"ARIMA direction (\d+)%")
X["nifty_hi"] = jv(e_nifty, r"classifiers about (\d+)%")
X["nifty_train"] = jv(e_nifty, r"models about (\d+)% \(training")
e_qlab = E(YT, "Information Coefficient (IC)")
X["ql_real"] = jv(e_qlab, r"IC about (0\.\d+)-(0\.\d+) = real signal")
X["ql_strong"] = jv(e_qlab, r"(0\.\d+)-(0\.\d+) = strong, rare")
X["ql_susp"] = jv(e_qlab, r"above (0\.\d+) = suspicious")
e_numsig = E(RD, "What is good models for numerai signals?")
X["num_live"] = sorted(num(v) for v in re.findall(r"Corr (0\.\d+)", e_numsig["_claim"]))
X["num_best"] = jv(e_numsig, r"corr (0\.\d+) at the best", "quote")
X["num_rounds"] = jv(e_numsig, r"about (\d+) rounds")
e_sr9 = E(RD, "sharpe ratio (page 9)")
X["et_sr_lo"], X["et_sr_hi"] = jv(e_sr9, r"(\d\.\d)-(\d\.\d) realistic")
e_sr8 = E(RD, "sharpe ratio (page 8)")
X["et_sr3"] = jv(e_sr8, r"Sharpe above (\d) with capacity")
X["et_years"] = jv(e_sr8, r"more than (\d) years of record")
e_carver = E(YT, "How fast should we trade?")
X["carver_sr"] = jv(e_carver, r"Sharpe of about (0\.\d+) per instrument")
CARVER_DIV = {"HALF": 2, "THIRD": 3, "QUARTER": 4}[re.search(r"ONE (\w+) OF YOUR", e_carver["quote"]).group(1)]
e_sysb = E(YT, "What Drives the Performance of Machine Learning Factor")
X["ml_ls_hi"], X["ml_ls_lo"] = jv(e_sysb, r"from (\d\.\d+)%/month .* to (\d\.\d+)%/month")
e_chan = E(YT, "Ernest Chan [QTS Capital Management]")
e_hnlin = E(RD, "Comment in 'Fitting to Noise or Nothing at All")
e_etedge = E(RD, 'What is an "edge"? (page 5)')
e_ldp_sin = E(YT, "Backtest overfitting. This is quants' original sin.")
e_ldp_wf = E(YT, "A walk-forward backtest is not an experiment")
e_hnkeras = E(RD, "Using a Keras Long Short-Term Memory Model")
e_hn51 = E(RD, "Comment on 'Investing Returns on the S&P500'")
e_msci = E(CP, "Converting Scores into Alphas")
X["msci_good"] = jv(e_msci, r"'good' IC (0\.\d+)")
X["msci_vgood"] = jv(e_msci, r"'very good' IC (0\.\d+)")
e_m6t = E(CP, "M6 paper: IC tiers")
X["m6_mod"], X["m6_good"], X["m6_exc"] = jv(e_m6t, r"(0\.\d+) Moderate; (0\.\d+) Good; (0\.\d+) Exceptional")
e_qlib = E(CP, "Benchmarks README: CSI300 Alpha158")
X["qlib_ic"] = jv(e_qlib, r"LightGBM Alpha158: IC (0\.\d+)")
X["qlib_icir"] = jv(e_qlib, r"ICIR (0\.\d+)")
X["qlib_ric"] = jv(e_qlib, r"Rank IC (0\.\d+)")
X["qlib_ret"] = jv(e_qlib, r"ann\. return (0\.\d+)")
X["qlib_ir"] = jv(e_qlib, r"(?<![A-Za-z])IR (\d\.\d+)")
X["qlib_linear"] = jv(e_qlib, r"Linear IC (0\.\d+)")
e_qcfg = E(CP, "LightGBM Alpha158 workflow config")
X["qlib_open"], X["qlib_close"] = jv(e_qcfg, r"open cost (\d+) bps, close cost (\d+) bps")
e_numex = E(CP, "Forum (Numerai team post): Better LGBM params")
X["num_val_sharpe"] = jv(e_numex, r"Correlation Sharpe of (\d+(?:\.\d+)?) on validation")
e_numlive = E(CP, "GitHub (user): 40-target LightGBM")
X["num_live_corr"] = jv(e_numlive, r"CORR (0\.\d+)")
X["num_live_sharpe"] = jv(e_numlive, r"Sharpe (\d\.\d+)")
e_gres = E(CP, "G-Research Crypto Forecasting")
X["gres"] = jv(e_gres, r"1st (0\.\d+)")
e_ubi = E(CP, "Ubiquant Market Prediction: final leaderboard")
X["ubi"] = jv(e_ubi, r"1st K I Y (0\.\d+)")
e_jpx = E(CP, "JPX Tokyo Stock Exchange Prediction: winners'")
X["jpx"] = jv(e_jpx, r"1st (0\.\d+)")
X["jpx_ann"] = jv(e_jpx, r"= (\d\.\d+) annualised", "_notes")
X["jpx_n"] = jv(e_jpx, r"([\d,]+) zero-skill entries", "_notes")
e_m6 = E(CP, "The M6 forecasting competition")
X["m6_teams"] = jv(e_m6, r"Of (\d+) global-leaderboard teams")
X["m6_beat"] = jv(e_m6, r"\((\d+\.\d)%\) built better portfolios")
X["m6_months"] = jv(e_m6, r"in all (\d+) months")
e_qpn_ic = E(CP, "Forum: How to accept/reject alpha factors?")
X["qpn_ic"], X["qpn_p"] = jv(e_qpn_ic, r"Mean IC > (0\.\d+) with p < (0\.\d+)")
X["qpn_sharpe"] = jv(e_qpn_ic, r"'Q Sharpe' >= (\d)")
e_qpn_888 = E(CP, "All That Glitters")
X["qpn_n"], X["qpn_r2"] = jv(e_qpn_888, r"(\d+) algorithms; R-squared < (0\.\d+)")
e_qc = E(CP, "Forum: Are filters required for alpha market")
X["qc_psr"] = jv(e_qc, r"PSR > (\d+)% required")
X["qc_pass"], X["qc_n"], X["qc_pct"] = jv(e_qc, r"(\d+) of (\d+) listed alphas \((\d+\.\d+)%\)")
e_wq = E(CP, "Third-party review: BRAIN consultant")
X["wq_sharpe"] = jv(e_wq, r"Sharpe > (\d\.\d+)")
X["wq_fit"] = jv(e_wq, r"fitness > (\d\.\d+)")
X["wq_to_lo"], X["wq_to_hi"] = jv(e_wq, r"turnover (\d+)%-(\d+)%")
e_wqfit = E(CP, "GitHub documentation of the BRAIN simulator")
e_iqc = E(CP, "IQC 2023 participant write-up")
X["iqc_tested"], X["iqc_sub"], X["iqc_pct"] = jv(e_iqc, r"([\d,]+) alphas tested, (\d+) submitted \((\d\.\d)%\)")
e_paper = E(RD, "Paper trading (page 2)")
X["paper_months"] = jv(e_paper, r"^(\d+) months")
e_trades = E(RD, "how much trades for validate")
X["trades_lo"], X["trades_hi"] = jv(e_trades, r"(\d+)-(\d+) trades a year")
e_dsr = E(CP, "Advances in Quantitative Meta-Strategies")
X["dsr_sr"], X["dsr_n"], X["dsr"] = jv(e_dsr, r"SR (\d\.\d+) after N = (\d+) trials.*DSR = (0\.\d+)")
e_numone = E(CP, "Blog: JPMorgan secures")
X["numone_sharpe"] = jv(e_numone, r"Sharpe (\d\.\d+)")
e_streak = E(RD, "Zerodha streak brokerage issue")
X["streak_pre"], X["streak_post"] = jv(e_streak, r"\+(\d+\.\d)% before costs, -(\d+\.\d)% after costs")
e_numval = E(RD, "What is a good sharpe ratio and validation correlation?")
X["nv_corr"], X["nv_sharpe"] = jv(e_numval, r"CORR (0\.\d+), Sharpe (\d+) \(")
e_hn130 = E(RD, "I've reproduced 130 research papers")
X["hn130_pct"] = jv(e_hn130, r"at most (\d+)% of such papers")
X["hn130_58"] = jv(e_hn130, r"'may yield (\d+)% accuracy'")
X["hn130_who"] = re.search(r"(\w+) estimates at most", e_hn130["_claim"]).group(1)
e_d65 = E(RD, "Daily NSE Bhavcopy delivery")
X["d65"], X["d65_turn"] = jv(e_d65, r"delivery above (\d+)% and turnover above Rs (\d+) crore")
e_d60 = E(RD, "When stock deliverable quantity is increasing")
X["d60"] = jv(e_d60, r"above (\d+)% sustained")
X["d60_sessions"] = NUM_WORDS[re.search(r"for at least (\w+) sessions", e_d60["_claim"]).group(1)]
e_btst = E(RD, "How Deliverable volume helps")
e_spike = E(YT, "Delivery Percentage in Stocks")
X["spike_healthy"] = jv(e_spike, r"delivery above (\d+)% is 'healthy'")
e_sebi = E(CP, "PR 22/2024")
X["sebi_loss"] = jv(e_sebi, r"(\d+)% of over 1 crore")
X["sebi_fpi"] = jv(e_sebi, r"(\d+)% of FPI profits")
e_algotest = E(CP, "Algo Trading India (2026) blog")
X["algotest"] = jv(e_algotest, r"(\d+)% of AlgoTest users")
e_zsub = E(YT, "SEBI Algo Trading Changes")
X["ops"] = jv(e_zsub, r"above (\d+) orders/second")
e_tqna_sebi = E(RD, "Preparing to comply with SEBI's retail algo rules")
e_kite1 = E(RD, "new sebi rules")
e_zc = E(YT, "Charges: equity delivery")

# statutory delivery costs, computed from the Zerodha schedule in the JSON (bps per side)
_z = e_zc["_claim"]
if not re.search(r"brokerage zero", _z):
    raise SystemExit("Zerodha schedule no longer says brokerage zero; revisit the cost table")
COST = {
    "brokerage": 0.0,
    "stt": jv(e_zc, r"STT (\d+(?:\.\d+)?)% on buy and sell") * 100,
    "nse": jv(e_zc, r"NSE transaction (\d+(?:\.\d+)?)%") * 100,
    "sebi": jv(e_zc, r"SEBI Rs (\d+)/crore") / 1e7 * 1e4,
    "stamp": jv(e_zc, r"stamp (\d+(?:\.\d+)?)% on buy") * 100,
    "gst_rate": jv(e_zc, r"GST (\d+)% on \(brokerage \+ SEBI \+ transaction\)") / 100,
    "dp_fee": jv(e_zc, r"DP Rs (\d+(?:\.\d+)?) per scrip on sell"),
}
COST["gst"] = COST["gst_rate"] * (COST["brokerage"] + COST["sebi"] + COST["nse"])
COST["side"] = COST["stt"] + COST["nse"] + COST["sebi"] + COST["gst"]          # each side
COST["avg_side"] = COST["side"] + COST["stamp"] / 2                             # stamp averaged

# ============================================================= program numbers

P: dict = {}
_ric = SUMMARY["rank_ic"]["nested_lgbm"]
P["ic"] = _ric["cv_mean_ic"]
P["ic_t"] = _ric["cv_nw_t_lag20"]
P["ic_pos"], P["ic_n"] = (int(x) for x in _ric["cv_months_ic_positive"].split("/"))
P["ic3"] = f"{P['ic']:.3f}"
P["hit"] = hit(P["ic"])

_stand = blocks(sec(GOALS, "Where the program stands"), "table")[0]


def stand(prefix: str) -> str:
    return trow(_stand, prefix)[1]


P["auc_all"], P["auc_nested"] = grab(r"(0\.\d+) / (0\.\d+)", stand("AUC, LightGBM"), "AUC")
P["auc_lo"], P["auc_hi"] = grab(r"\[(0\.\d+), (0\.\d+)\]", stand("AUC, LightGBM"), "AUC CI")
P["m_nested"], P["m_ens"] = grab(r"(\d+)% \(nested LightGBM\), (\d+)% \(rank ensemble\)",
                                 stand("Months with AUC"), "months above 0.50")
P["worst"] = grab(r"(0\.\d+)", stand("Worst month"), "worst month")
P["single_hi"], P["single_lo"], P["ens"] = grab(
    r"single models ([−-]\d+\.\d)% to ([−-]\d+\.\d)% a year; rank ensemble \+(\d+\.\d)% a year",
    stand("Long-only top decile"), "portfolio excess")
P["ir"], P["ir_lo"], P["ir_hi"] = grab(r"IR (\d\.\d+) \[(\d\.\d+), (\d\.\d+)\]",
                                       stand("Long-only top decile"), "ensemble IR")
P["dsr_ens"], P["dsr_liq"], P["dsr_ls"] = grab(
    r"(0\.\d+) \(ensemble top decile\), (0\.\d+) \(ensemble liquid book\), (0\.\d+) \(ensemble long-short\)",
    stand("Deflated Sharpe"), "DSR")
P["N"] = grab(r"N = (\d+) trials", "".join(trow(_stand, "Deflated Sharpe")), "trial count")
P["gates_lgbm"], P["gates_n"], P["gates_ens"], _gn2 = grab(r"(\d) of (\d) \(LightGBM\), (\d) of (\d) \(ensemble\)",
                                                          stand("Pre-registered gates"), "gates")
P["stab_single"] = P["ic_t"] / math.sqrt(P["ic_n"])
P["stab_ens"] = NormalDist().inv_cdf(P["m_ens"] / 100)

_s3 = sec(CAL, "3. ")
_ladder_tbl, _metric_tbl = blocks(_s3, "table")[:2]
_net = trow(_metric_tbl, "Net economics")[1]
P["ens_months"], P["ens_months_n"] = grab(r"(\d+) of (\d+) months", _net, "ensemble months")
_sig = trow(_metric_tbl, "Significance")[1]
P["psr"] = grab(r"PSR (0\.\d+)", _sig, "PSR")
_cost = trow(_metric_tbl, "Cost drag")
P["cost_bps"], P["turnover"], P["window"], P["costs"], P["gross_md"] = grab(
    r"at (\d+) bps per side and (\d+)% turnover per (\d+) sessions, costs are about (\d+\.\d)% a year "
    r"against about (\d+\.\d)% gross active", _cost[1], "cost drag")
P["per10"], P["net_lo"], P["bps_lo"], P["net_hi"], P["bps_hi"] = grab(
    r"about (\d\.\d)% a year \(\+(\d+\.\d)% at (\d+) bps, \+(\d+\.\d)% at (\d+) bps\)", _cost[3],
    "cost sensitivity")
P["gross"] = P["ens"] + P["costs"]
P["live_months"] = grab(r"(\d+) months live", trow(_metric_tbl, "Track record")[1], "live record")
P["years_needed"], P["ir_needed"] = grab(r"about (\d+) years at IR (\d\.\d+)", trow(_metric_tbl, "Track record")[3],
                                         "years to PSR 95%")
P["date"] = re.search(r"\*\*Date:\*\* (\d{4}-\d\d-\d\d)", CAL_MD.read_text()).group(1)

# Markdown vs scale5y_summary.json: rank IC is page-sourced from the JSON; the rest is reported
_goal_ic = stand("Rank IC per date")
for _pat, _val in ((r"\+(0\.\d+)", P["ic"]), (r"t (\d\.\d)", P["ic_t"])):
    _m = re.search(_pat, _goal_ic)
    if fmt_like(_m.group(1), _val) != _m.group(1):
        note(f"GOALS rank IC row: Markdown {_m.group(1)}, scale5y_summary.json {_val:.4f}; page uses the JSON",
             PROGRAM_NOTES)
if not re.search(rf"positive in {P['ic_pos']} of {P['ic_n']} months", _goal_ic):
    note("GOALS rank IC row: positive-months count differs from scale5y_summary.json", PROGRAM_NOTES)
if fmt_like("52.1", P["hit"]) != re.search(r"about (\d+\.\d)%", stand("Directional hit rate")).group(1):
    note("GOALS hit-rate row differs from Sheppard on the JSON IC", PROGRAM_NOTES)
_lg, _bs, _pf = SUMMARY["league"], SUMMARY["bootstrap"]["models"], SUMMARY["portfolio_headline"]
agree("AUC nested", f"{P['auc_nested']:.4f}", _bs["nested_lgbm"]["cv_auc_mean"])
agree("AUC CI low", f"{P['auc_lo']:.4f}", _bs["nested_lgbm"]["cv_mean_ci95"][0])
agree("AUC CI high", f"{P['auc_hi']:.4f}", _bs["nested_lgbm"]["cv_mean_ci95"][1])
agree("AUC all features", f"{P['auc_all']:.4f}", _lg["all51"]["cv_auc_mean"])
agree("months >= 0.50 nested", f"{P['m_nested']:.0f}", 100 * _lg["nested_lgbm"]["pct_folds_ge_050"])
agree("months >= 0.50 ensemble", f"{P['m_ens']:.0f}", 100 * _lg["nested_ensemble_rank"]["pct_folds_ge_050"])
agree("worst month", f"{P['worst']:.3f}", _lg["nested_lgbm"]["worst_fold_auc"])
agree("ensemble excess", f"{P['ens']:.1f}", 100 * _pf["nested_ensemble_rank|top_decile"]["excess_vs_ew_20bps"])
agree("ensemble DSR", f"{P['dsr_ens']:.3f}", _pf["nested_ensemble_rank|top_decile"]["dsr"])
agree("liquid DSR", f"{P['dsr_liq']:.3f}", _pf["nested_ensemble_rank|liq_top_decile"]["dsr"])
agree("long-short DSR", f"{P['dsr_ls']:.3f}", _pf["nested_ensemble_rank|ls_decile"]["dsr"])
agree("ensemble PSR", f"{P['psr']:.2f}", _pf["nested_ensemble_rank|top_decile"]["psr"])
agree("ensemble turnover", f"{P['turnover']:.0f}", 100 * _pf["nested_ensemble_rank|top_decile"]["turnover"])
agree("trial count", f"{P['N']:.0f}", SUMMARY["dsr_trials"]["N_headline"])
if _pf["nested_ensemble_rank|top_decile"]["months_positive"] != f"{P['ens_months']:.0f}/{P['ens_months_n']:.0f}":
    note("ensemble positive months differ from scale5y_summary.json", PROGRAM_NOTES)
_single = [100 * _pf[f"nested_lgbm|{b}"]["excess_vs_ew_20bps"] for b in ("top_decile", "liq_top_decile")]
agree("single-model excess (best)", f"{abs(P['single_hi']):.1f}", abs(max(_single)))
agree("single-model excess (worst)", f"{abs(P['single_lo']):.1f}", abs(min(_single)))
if abs(P["gross"] - P["gross_md"]) > 0.05:
    note(f"cost drag: net {P['ens']} + costs {P['costs']} != gross {P['gross_md']}", PROGRAM_NOTES)

# =========================================== Markdown text, checked and patched


def fix_ic(where: str, text: str) -> str:
    """SuryaDhana's IC in the notes must equal the summary JSON (rounded to 3 dp)."""
    def sub(m):
        if m.group(2) != P["ic3"]:
            note(f"{where}: Markdown IC {m.group(2)}, scale5y_summary.json {P['ic']:.4f}; page shows {P['ic3']}",
                 PROGRAM_NOTES)
        return m.group(1) + P["ic3"]
    return re.sub(r"((?:rank IC|IC) \+?)(0\.06\d)\b", sub, text)


_head = CAL[1]
NOTE_ON_NUMBERS = fix_ic("CAL note on numbers", para(_head, "Note on numbers."))
_s1 = sec(CAL, "1. ")
GENRE_LEAD = para(_s1, "What people online report")
LOUD, QUIET = blocks(_s1, "ul")[0][:2]
LOUD = checks("§1 loud genre", LOUD, [
    (r"\((\d\.\d+) million, ", X["views_compsci"] / 1e6),
    (r"million, (\d\.\d+) million and", X["views_siraj"] / 1e6),
    (r"and (\d\.\d+) million views", X["views_krish"] / 1e6),
    (r"R² (0\.\d+) on a \*\*pure random walk", X["r2_flovik"]),
    (r"LSTM with R² (0\.\d+)", X["r2_aungsi"]),
    (r"a (\d+)-model comparison", X["gulati_models"]),
    (r"(\d+\.\d)% on about \d+ test days", X["twitter_acc"]),
    (r"on about (\d+) test days", X["twitter_days"]),
    (r"(\d+)% training accuracy from label leakage", X["pyprog_acc"]),
    (r"(\d+)% at a 40-to-60-day horizon", X["raja_long"]),
])
LOUD = check_word("§1 loud genre", LOUD, r"the LSTM ranks (\w+)", X["gulati_rank"], ORDINALS)
LOUD_LO, LOUD_HI = grab(r"reports (\d+)% to (\d+)% \"accuracy\"", LOUD, "loud-genre accuracy range")
QUIET = checks("§1 quiet genre", QUIET, [
    (r"right (\d+\.\d+) percent", X["mercer"]),
    (r"called direction (\d+\.\d)% of the time", X["news_hit"]),
    (r"and (\d+)% went bust", X["news_bust"]),
    (r"accuracy was (\d+) to \d+% behind", X["nifty_lo"]),
    (r"accuracy was \d+ to (\d+)% behind", X["nifty_hi"]),
    (r"behind an (\d+)% training", X["nifty_train"]),
    (r"bands: (0\.\d+) to", X["ql_real"][0]),
    (r"bands: 0\.\d+ to (0\.\d+) is", X["ql_real"][1]),
    (r"(0\.\d+) to 0\.\d+ \"strong", X["ql_strong"][0]),
    (r"0\.\d+ to (0\.\d+) \"strong", X["ql_strong"][1]),
    (r"above (0\.\d+) \"suspicious", X["ql_susp"]),
    (r"correlations of (0\.\d+) to", X["num_live"][0]),
    (r"correlations of 0\.\d+ to (0\.\d+)", X["num_live"][-1]),
    (r"with (0\.\d+) \"at the best", X["num_best"]),
    (r"lore: (\d) to \d \"realistic", X["et_sr_lo"]),
    (r"lore: \d to (\d) \"realistic", X["et_sr_hi"]),
    (r"above (\d) \"super hard", X["et_sr3"]),
    (r"Sharpe of about (0\.\d+) per instrument", X["carver_sr"]),
    (r"fall from (\d\.\d+)% to", X["ml_ls_hi"]),
    (r"to (\d\.\d+)% a month", X["ml_ls_lo"]),
])

BENCH = blocks(_s1, "table")[0]
_b = trow(BENCH, "MSCI Barra")
_b[1] = checks("§1 benchmarks, MSCI", _b[1], [(r"IC (0\.\d+) \"good", X["msci_good"]),
                                               (r"(0\.\d+) \"very good", X["msci_vgood"])])
_b = trow(BENCH, "M6 competition organisers")
_b[1] = checks("§1 benchmarks, M6 tiers", _b[1], [(r"IC (0\.\d+) moderate", X["m6_mod"]),
                                                   (r"(0\.\d+) good", X["m6_good"]),
                                                   (r"(0\.\d+) exceptional", X["m6_exc"])])
_b = trow(BENCH, "Microsoft Qlib")
_b[1] = checks("§1 benchmarks, Qlib", _b[1], [
    (r"^IC (0\.\d+)", X["qlib_ic"]), (r"ICIR (0\.\d+)", X["qlib_icir"]), (r"rank IC (0\.\d+)", X["qlib_ric"]),
    (r"(\d+\.\d)% a year excess", 100 * X["qlib_ret"]), (r"IR (\d\.\d+), net", X["qlib_ir"]),
    (r"net of (\d+)/", X["qlib_open"]), (r"net of \d+/(\d+) bps", X["qlib_close"])])
_b = trow(BENCH, "Numerai")
_b[1] = checks("§1 benchmarks, Numerai", _b[1], [
    (r"live CORR (0\.\d+) to", X["num_live"][0]), (r"live CORR 0\.\d+ to (0\.\d+)", X["num_live"][-1]),
    (r"correlation Sharpe (\d+(?:\.\d+)?) on validation", X["num_val_sharpe"]),
    (r"participant's (\d\.\d+)", X["num_live_sharpe"])])
_b = trow(BENCH, "Kaggle, live-scored")
_b[1] = checks("§1 benchmarks, Kaggle", _b[1], [
    (r"live correlation (0\.\d+)", X["gres"]), (r"Ubiquant winner (0\.\d+)", X["ubi"]),
    (r"daily Sharpe (0\.\d+)", X["jpx"]), (r"about (\d+) annualised", X["jpx_ann"]),
    (r"among ([\d,]+) entrants", X["jpx_n"])])
_b = trow(BENCH, "M6 (")
_b[0] = check("§1 benchmarks, M6", _b[0], r"\((\d+) teams", X["m6_teams"])
_b[0] = check("§1 benchmarks, M6", _b[0], r"(\d+) live months", X["m6_months"])
_b[1] = check("§1 benchmarks, M6", _b[1], r"(\d+\.\d)% beat", X["m6_beat"])
_b = trow(BENCH, "Quantopian")
_b[1] = checks("§1 benchmarks, Quantopian", _b[1], [
    (r"mean IC > (0\.\d+)", X["qpn_ic"]), (r"p < (0\.\d+)", X["qpn_p"]),
    (r"Q Sharpe of (\d)", X["qpn_sharpe"]), (r"R² < (0\.\d+)", X["qpn_r2"]),
    (r"across (\d+) algorithms", X["qpn_n"])])
_b = trow(BENCH, "QuantConnect")
_b[1] = checks("§1 benchmarks, QuantConnect", _b[1], [
    (r"\) [≥>] (\d+)%", X["qc_psr"]), (r"only (\d+) of", X["qc_pass"]), (r"of (\d+) strategies", X["qc_n"]),
    (r"\((\d+\.\d)%\) passed", X["qc_pct"])])
_b = trow(BENCH, "WorldQuant BRAIN")
_b[1] = checks("§1 benchmarks, WorldQuant", _b[1], [
    (r"Sharpe > (\d\.\d+)", X["wq_sharpe"]), (r"fitness > (\d)", X["wq_fit"]),
    (r"turnover (\d+)% to", X["wq_to_lo"]), (r"to (\d+)%;", X["wq_to_hi"]),
    (r"submitted (\d+) of", X["iqc_sub"]), (r"of ([\d,]+) alphas", X["iqc_tested"]),
    (r"\((\d\.\d)%\)", X["iqc_pct"])])
_b = trow(BENCH, "Forums on track record")
_b[1] = checks("§1 benchmarks, track record", _b[1], [
    (r"^(\d+) months of paper", X["paper_months"]), (r"more than (\d) years", X["et_years"]),
    (r"(\d+) to \d+ trades", X["trades_lo"]), (r"\d+ to (\d+) trades", X["trades_hi"])])

def fix_qc(where: str, text: str) -> str:
    """QuantConnect's bar is 'PSR > 80% required' in the JSON; the notes write ≥."""
    if not re.search(r"PSR > \d+% required", e_qc["_claim"]):
        return text
    new = re.sub(r"(QuantConnect[^|;]*?PSR\((?:true )?(?:Sharpe|SR) > 1\)) ≥ (\d+%)", r"\1 > \2", text)
    if new != text:
        note(f"{where}: QuantConnect PSR bar written '≥ {X['qc_psr']:.0f}%'; evidence JSON says "
             f"'PSR > {X['qc_psr']:.0f}% required'; page shows >")
    return new


_b = trow(BENCH, "QuantConnect")
_b[1] = fix_qc("§1 benchmarks, QuantConnect", "QuantConnect " + _b[1])[len("QuantConnect "):]
WHERE_SITS = fix_ic("§1 where SuryaDhana sits", para(_s1, "Where SuryaDhana sits."))
VERDICT = re.search(r"\*\*Verdict: (.+?)\*\*", WHERE_SITS).group(1)

# §2 genre tables
_s21, _s22 = sec(CAL, "2.1 "), sec(CAL, "2.2 ")
LOUD_TBL = blocks(_s21, "table")[0]
WHY_WRONG = checks("§2.1 why wrong", para(_s21, "Why these numbers are wrong"),
                   [(r"score R² (0\.\d+) on a random walk", X["r2_flovik"])])
QUIET_TBL = blocks(_s22, "table")[0]
CONSENSUS = para(_s22, "Consensus.")

_r = trow(LOUD_TBL, "\"Near-perfect\"")
_r[2] = check("§2.1 reach", _r[2], r"([\d,]+) views", X["views_compsci"])
_r = trow(LOUD_TBL, "\"Predict the closing")
_r[2] = check("§2.1 reach", _r[2], r"([\d,]+) views", X["views_siraj"])
_r = trow(LOUD_TBL, "Stacked-LSTM")
_r[2] = check("§2.1 reach", _r[2], r"([\d,]+) views", X["views_krish"])
_r = trow(LOUD_TBL, "\"Average forecasting")
_r[0] = checks("§2.1 Medium claim", _r[0], [(r"is (\d+\.\d)%", X["saka_acc"]), (r"\((\d+) stocks", X["saka_stocks"])])
_r = trow(LOUD_TBL, "87.6%")
_r[0] = check("§2.1 Twitter mood", _r[0], r"^(\d+\.\d)%", X["twitter_acc"])
_r[3] = check("§2.1 Twitter mood", _r[3], r"about (\d+) test days", X["twitter_days"])
_r = trow(LOUD_TBL, "\"over 98%")
_r[0] = check("§2.1 pythonprogramming", _r[0], r"over (\d+)%", X["pyprog_acc"])
_r = trow(LOUD_TBL, "75% win-rate")
_r[0] = check("§2.1 Elite Trader", _r[0], r"^(\d+)%", X["et_win"])
_r[3] = check("§2.1 Elite Trader", _r[3], r"over (\d+) million", X["et_million"])
_r = trow(LOUD_TBL, "70.29%")
_r[0] = checks("§2.1 LinkedIn", _r[0], [(r"^(\d+\.\d+)%", X["raja_tuned"]), (r"a (\d+)-day window", X["raja_window"])])
_r = trow(LOUD_TBL, "Monthly returns")
_r[0] = checks("§2.1 monthly returns", _r[0], [(r"of (\d+)% to", X["r30"]), (r"to (\d+)%", X["r120"])])
if e_3012["platform"] not in _r[1]:
    _fixed = f"{e_3012['platform']} comment ({e_3012['community']}; unverified, snippet only)"
    note(f"§2.1 'Monthly returns of {X['r30']:.0f}% to {X['r120']:.0f}%': Markdown says '{_r[1]}', but the "
         f"evidence entry is {e_3012['platform']} {e_3012['community']} (search snippet of a mirror); page says so")
    _r[1] = _fixed

_r = trow(QUIET_TBL, "\"We're right")
_r[0] = check("§2.2 Mercer", _r[0], r"right (\d+\.\d+) percent", X["mercer"])
_r[2] = check("§2.2 Mercer", _r[2], r"(\d+\.\d+)% hit rate", X["mercer"])
_r = trow(QUIET_TBL, "Students with tomorrow")
_r[0] = checks("§2.2 newspaper", _r[0], [(r"direction (\d+\.\d)%", X["news_hit"]), (r"about (\d+)% went", X["news_bust"])])
_r[2] = check("§2.2 newspaper", _r[2], r"(\d+\.\d)%", X["news_hit"])
_r = trow(QUIET_TBL, "Nifty 50 next-day")
_r[0] = checks("§2.2 Nifty", _r[0], [(r"(\d+)% training", X["nifty_train"]), (r"(\d+) to \d+% on test", X["nifty_lo"]),
                                     (r"\d+ to (\d+)% on test", X["nifty_hi"])])
_r = trow(QUIET_TBL, "\"IC 0.04")
_r[0] = checks("§2.2 QuanterLab", _r[0], [(r"IC (0\.\d+) to", X["ql_real"][0]), (r"to (0\.\d+) = real", X["ql_real"][1]),
                                          (r"(0\.\d+) to 0\.\d+ strong", X["ql_strong"][0]),
                                          (r"(0\.\d+) strong, rare", X["ql_strong"][1]),
                                          (r"above (0\.\d+) suspicious", X["ql_susp"])])
_r = trow(QUIET_TBL, "Live Numerai models")
_r[0] = checks("§2.2 Numerai", _r[0], [(r"models: (0\.\d+) to", X["num_live"][0]), (r"to (0\.\d+);", X["num_live"][-1]),
                                       (r"corr (0\.\d+) at the best", X["num_best"])])
_r = trow(QUIET_TBL, "Plan on an expected Sharpe")
_r[0] = check("§2.2 Carver", _r[0], r"about (0\.\d+) per", X["carver_sr"])
_r = trow(QUIET_TBL, "Nonlinear ML long-short")
_r[0] = checks("§2.2 Esakia and Goltz", _r[0], [(r"from (\d\.\d+)%", X["ml_ls_hi"]), (r"to (\d\.\d+)% a month", X["ml_ls_lo"])])

# rows of the genre and benchmark tables -> their evidence entries (title prefixes)
SRC_LOUD = {
    "\"Near-perfect\"": [e_compsci], "\"Predict the closing": [e_siraj], "Stacked-LSTM": [e_krish],
    "\"Average forecasting": [e_saka], "\"99% accuracy\"": [E(YT, "Nestle Stock"), E(YT, "NVIDIA Stock")],
    "87.6%": [e_twitter], "\"over 98%": [e_pyprog], "75% win-rate": [e_etwin], "70.29%": [e_raja],
    "Monthly returns": [e_3012],
}
SRC_QUIET = {
    "\"We're right": [e_mercer, e_mercer_x], "\"It's slightly": [e_manahl], "Students with tomorrow": [e_news],
    "Nifty 50 next-day": [e_nifty], "\"IC 0.04": [e_qlab], "Live Numerai models": [e_numsig],
    "\"A ratio somewhere": [e_sr9], "\"A consistent Sharpe": [e_sr8], "Plan on an expected Sharpe": [e_carver],
    "Nonlinear ML long-short": [e_sysb], "Direct ML prediction": [e_chan], "\"With this amount of noise": [e_hnlin],
    "\"Edge is how far": [e_etedge], "\"The purpose of backtesting": [e_ldp_sin, e_ldp_wf],
    "\"At least you should show": [e_hnkeras, e_hn51],
}
SRC_BENCH = {
    "MSCI Barra": [e_msci], "M6 competition organisers": [e_m6t], "Microsoft Qlib": [e_qlib, e_qcfg],
    "Numerai": [e_numsig, e_numex, e_numlive], "Kaggle, live-scored": [e_gres, e_ubi, e_jpx], "M6 (": [e_m6],
    "Quantopian": [e_qpn_ic, e_qpn_888], "QuantConnect": [e_qc], "WorldQuant BRAIN": [e_wq, e_wqfit, e_iqc],
    "Forums on track record": [e_paper, e_sr8, e_trades],
}


def sources_for(mapping: dict, first_cell: str) -> list[dict]:
    for k, v in mapping.items():
        if plain(first_cell).startswith(plain(k)):
            return v
    return []


QUIET_TITLE = _s22["title"]
_quiet_c = [e for r in QUIET_TBL["rows"] for e in sources_for(SRC_QUIET, r[0]) if e["credibility"] not in "AB"]
if "graded A or B" in QUIET_TITLE and _quiet_c:
    _n_words = list(NUM_WORDS)[len(_quiet_c)] if len(_quiet_c) < len(NUM_WORDS) else str(len(_quiet_c))
    QUIET_TITLE = QUIET_TITLE.replace(
        "(graded A or B)", f"(graded A or B, except {_n_words} quote{'s' if len(_quiet_c) > 1 else ''} from a "
                           f"C-graded thread)")
    for e in _quiet_c:
        note(f"§2.2 is headed 'graded A or B', but the Hacker News quote row includes {e['platform']} "
             f"'{e['title'][:48]}…', graded {e['credibility']} in {e['_stream']}.json (#{e['_n']}); heading qualified")
_loud_not_c = [e for r in LOUD_TBL["rows"] for e in sources_for(SRC_LOUD, r[0]) if e["credibility"] != "C"]
for e in _loud_not_c:
    note(f"§2.1 'all graded C' includes {e['title'][:48]} graded {e['credibility']}")

# §3 ladder: implied hit rates are computed from each rung's IC bounds


def implied_hits(ic_cell: str) -> str:
    c = plain(ic_cell)
    m = re.search(r"(\d\.\d+) to (\d\.\d+)", c)
    if m:
        return f"{hit(num(m.group(1))):.1f} to {hit(num(m.group(2))):.1f}%"
    m = re.search(r"<\s*(\d\.\d+)", c)
    if m:
        return f"≤ {hit(num(m.group(1))):.1f}%"
    m = re.search(r"≥\s*(\d\.\d+)", c)
    if m:
        return f"≥ {hit(num(m.group(1))):.1f}%"
    raise SystemExit(f"cannot read IC bounds from ladder cell {c!r}")


for _r in _ladder_tbl["rows"]:
    _calc = implied_hits(_r[1])
    _md_nums, _calc_nums = re.findall(r"\d+(?:\.\d+)?", _r[2]), re.findall(r"\d+\.\d", _calc)
    for _a, _b2 in zip(_md_nums, _calc_nums):
        if fmt_like(_a, num(_b2)) != _a:
            note(f"§3 ladder rung '{plain(_r[0])}': Markdown implied hit rate {_r[2]}, Sheppard on its IC "
                 f"bounds gives {_calc}; page shows the computed value")
            break
    _r[2] = _calc
    _r[5] = fix_ic("§3 ladder", _r[5])

_r = trow(_metric_tbl, "Rank IC per date")
_r[1] = fix_ic("§3 metric table", _r[1])
_r[2] = checks("§3 metric table, IC band", _r[2], [
    (r"MSCI good (0\.\d+)", X["msci_good"]), (r"Qlib LightGBM (0\.\d+) to", X["qlib_ic"]),
    (r"Qlib LightGBM 0\.\d+ to (0\.\d+)", X["qlib_ric"]), (r"Numerai live (0\.\d+) to", X["num_live"][0]),
    (r"Numerai live 0\.\d+ to (0\.\d+)", X["num_live"][-1]), (r"winners (0\.\d+) \(crypto", X["gres"]),
    (r"to (0\.\d+) \(fund", X["ubi"])])
_r = trow(_metric_tbl, "IC stability")
_r[1] = checks("§3 metric table, stability", _r[1], [(r"about (\d\.\d) per month", P["stab_single"]),
                                                       (r"about (\d\.\d) implied", P["stab_ens"])])
_r[2] = checks("§3 metric table, stability band", _r[2], [
    (r"Numerai live (\d\.\d+)", X["num_live_sharpe"]), (r"validation (\d+);", X["num_val_sharpe"]),
    (r"ICIR (0\.\d+)", X["qlib_icir"])])
_r = trow(_metric_tbl, "Hit rate")
_r[2] = checks("§3 metric table, hit-rate band", _r[2], [
    (r"Mercer (\d+\.\d+)%", X["mercer"]), (r"experiment (\d+\.\d)%", X["news_hit"]),
    (r"next-day (\d+) to", X["nifty_lo"]), (r"next-day \d+ to (\d+)%", X["nifty_hi"]),
    (r"\"(\d+)%\" quoted", X["hn130_58"])])
_r = trow(_metric_tbl, "Net economics")
_r[2] = checks("§3 metric table, economics band", _r[2], [
    (r"Qlib LightGBM (\d+\.\d)% a year", 100 * X["qlib_ret"]), (r"at IR (\d\.\d+) net", X["qlib_ir"]),
    (r"long-short (\d\.\d+)% a month", X["ml_ls_lo"])])
_r = trow(_metric_tbl, "Significance")
_r[2] = fix_qc("§3 metric table, significance", _r[2])
_r[2] = checks("§3 metric table, significance band", _r[2], [
    (r"\) [≥>] (\d+)%, ", X["qc_psr"]), (r"(\d+\.\d)% pass", X["qc_pct"]),
    (r"example DSR (0\.\d+)", X["dsr"]), (r"at N = (\d+);", X["dsr_n"])])
_r = trow(_metric_tbl, "Track record")
_r[2] = checks("§3 metric table, track-record band", _r[2], [
    (r"folk minimum (\d+) months", X["paper_months"]), (r"allocators > (\d) years", X["et_years"])])
_r = trow(_metric_tbl, "Linear vs nonlinear")
_r[2] = checks("§3 metric table, linear vs nonlinear", _r[2], [
    (r"linear (0\.\d+) vs", X["qlib_linear"]), (r"vs LightGBM (0\.\d+)", X["qlib_ic"])])
LADDER_INTRO = para(_s3, "The competition stream derived")
RUNG = {}
for _r in _ladder_tbl["rows"]:
    _sd = plain(_r[5]).lower()
    if "rank ensemble sits here" in _sd:
        RUNG["ens"] = plain(_r[0]).split(".")[0]
    elif "single models" in _sd and "sit here" in _sd:
        RUNG["single"] = plain(_r[0]).split(".")[0]
if set(RUNG) != {"ens", "single"}:
    raise SystemExit("ladder table no longer says where the ensemble and single models sit")
METRIC_TBL = _metric_tbl
LADDER_TBL = _ladder_tbl

# §4 failure modes
FAIL_TBL = blocks(sec(CAL, "4. "), "table")[0]
_r = trow(FAIL_TBL, "Tiny test windows")
_r[1] = check("§4 tiny windows", _r[1], r"(\d+\.\d)% on \d+ days", X["twitter_acc"])
_r[1] = check("§4 tiny windows", _r[1], r"on (\d+) days", X["twitter_days"])
_r = trow(FAIL_TBL, "Multiple testing")
_r[1] = checks("§4 multiple testing", _r[1], [(r"over (\d+) million", X["et_million"]), (r"R² < (0\.\d+)", X["qpn_r2"])])
_r = trow(FAIL_TBL, "Costs ignored")
_r[1] = checks("§4 costs", _r[1], [(r"\+(\d+\.\d)% to", X["streak_pre"]), (r"to −(\d+\.\d)%", X["streak_post"])])
_r = trow(FAIL_TBL, "Training-accuracy headlines")
_r[1] = checks("§4 training accuracy", _r[1], [(r"Nifty (\d+)% train", X["nifty_train"]), (r"vs (\d+)% test", X["nifty_lo"])])
_r = trow(FAIL_TBL, "Validation overfit")
_r[1] = checks("§4 validation overfit", _r[1], [(r"CORR (0\.\d+) with", X["nv_corr"]), (r"Sharpe (\d+)$", X["nv_sharpe"])])
_r = trow(FAIL_TBL, "Label leakage")
_r[1] = check("§4 label leakage", _r[1], r"(\d+)% training accuracy", X["pyprog_acc"])

# §5 India
INDIA = blocks(sec(CAL, "5. "), "ul")[0]
INDIA[0] = checks("§5 delivery", INDIA[0], [
    (r"delivery above (\d+)% with turnover", X["d65"]), (r"turnover above ₹(\d+) crore", X["d65_turn"]),
    (r"above (\d+)% for \w+ sessions", X["d60"]), (r"large caps above (\d+)%", X["spike_healthy"])])
INDIA[0] = check_word("§5 delivery", INDIA[0], r"for (\w+) sessions", X["d60_sessions"], NUM_WORDS)
INDIA[1] = checks("§5 Indian ML content", INDIA[1], [
    (r"The (\d\.\d+)-million-view", X["views_krish"] / 1e6), (r"reports (\d+) to \d+%", X["nifty_lo"]),
    (r"\d+ to (\d+)% on test", X["nifty_hi"]), (r"behind (\d+)% training", X["nifty_train"])])
INDIA[2] = checks("§5 costs", INDIA[2], [
    (r"about (\d+\.\d) bps per side", COST["side"]), (r"plus (\d+\.\d) bps stamp", COST["stamp"]),
    (r"STT (\d+\.\d+)% each way", COST["stt"] / 100), (r"from \+(\d+\.\d)% to", X["streak_pre"]),
    (r"to −(\d+\.\d)% once", X["streak_post"])])
_left = re.search(r"leaves (\d+) to (\d+) bps", INDIA[2])
if _left and not (num(_left.group(1)) <= 20 - COST["avg_side"] <= num(_left.group(2))):
    note(f"§5 costs: 20 bps leaves {20 - COST['avg_side']:.1f} bps per side on average, outside "
         f"'{_left.group(0)}'")
INDIA[3] = checks("§5 regulation", INDIA[3], [
    (r"above (\d+) orders per second", X["ops"]), (r"(\d+)% of individual F&O", X["sebi_loss"]),
    (r"and (\d+)% of foreign-investor", X["sebi_fpi"])])
INDIA[4] = check("§5 platforms", INDIA[4], r"\"(\d+)% of users", X["algotest"])

# §6 coverage, §7 changes
COVER = blocks(sec(CAL, "6. "), "ul")[0]
_gc = grade_counts(ALL)
COVER[2] = checks("§6 grade counts", COVER[2], [
    (r"Of (\d+) entries", len(ALL)), (r"(\d+) are graded A", _gc["A"]), (r"(\d+) B and", _gc["B"]),
    (r"and (\d+) C;", _gc["C"])])
COVER[1] = check_word("§6 YouTube", COVER[1], r"and (\w+) exact view counts",
                      sum(1 for e in EV[YT] if views(e)), NUM_WORDS)
_m130 = re.search(r"where the author estimates at most (\d+)% hold up", COVER[0])
if _m130:
    COVER[0] = check("§6 Reddit", COVER[0], r"estimates at most (\d+)%", X["hn130_pct"])
    COVER[0] = COVER[0].replace("where the author estimates", f"where a commenter ({X['hn130_who']}) estimates")
    note(f"§6: 'the author estimates at most {X['hn130_pct']:.0f}% hold up', but in {RD}.json "
         f"#{e_hn130['_n']} the {X['hn130_pct']:.0f}% estimate is commenter {X['hn130_who']}'s (the author claimed "
         f"every paper failed, #{E(RD, 'I' + chr(39) + 've reproduced 130+')['_n']}); page attributes it to the commenter")
CHANGES = blocks(sec(CAL, "7. "), "ol")[0]

# GOALS.md
G_INTRO = blocks(GOALS[1], "p")[1]
G_LADDER_INTRO = blocks(sec(GOALS, "The ladder"), "p")[0]
STAGES = [s for s in GOALS if s["level"] == 3 and s["title"].startswith("Stage ")]
for s in STAGES:
    for t in blocks(s, "table"):
        for r in t["rows"]:
            for j in range(1, len(r)):
                r[j] = fix_qc(f"GOALS {s['title'][:7]}", fix_ic(f"GOALS {s['title'][:7]}", r[j]))
_s0 = blocks(STAGES[0], "table")[0]
_r = trow(_s0, "Rank IC per date")
_r[3] = checks("GOALS stage 0, IC anchor", _r[3], [
    (r"'good' IC as (0\.\d+)", X["msci_good"]), (r"'very good' IC as (0\.\d+)", X["msci_vgood"]),
    (r"tiers are (0\.\d+) moderate", X["m6_mod"]), (r"(0\.\d+) good, 0", X["m6_good"]),
    (r"(0\.\d+) exceptional", X["m6_exc"]), (r"above (0\.\d+) at p", X["qpn_ic"]), (r"p < (0\.\d+)", X["qpn_p"])])
_r = trow(_s0, "Null and leakage tests")
_r[3] = checks("GOALS stage 0, leakage anchor", _r[3], [
    (r"implies a (\d+\.\d)% hit rate", hit(num(re.search(r"An IC of (0\.\d+)", _r[3]).group(1)))),
    (r"and 0\.\d+ implies (\d+\.\d)%", hit(num(re.search(r"and (0\.\d+) implies", _r[3]).group(1)))),
    (r"a (\d\.\d+)-million-view", X["views_compsci"] / 1e6), (r"R² (0\.\d+) on a pure", X["r2_flovik"]),
    (r"(\d+\.\d)% direction on", X["twitter_acc"]), (r"about (\d+) test days", X["twitter_days"]),
    (r"(\d+)% training accuracy", X["pyprog_acc"])])
_far = re.search(r"far above (\d+)% implies IC above (0\.\d+)", _r[3])
if _far and ic_for(num(_far.group(1))) < num(_far.group(2)) - 0.01:
    note("GOALS stage 0: the '55% implies IC above 0.15' rule does not follow from Sheppard")
_r = trow(_s0, "AUC on a cross-sectional")
_r[3] = check("GOALS stage 0, Qlib anchor", _r[3], r"Qlib LightGBM IC (0\.\d+)", X["qlib_ic"])
_s1t = blocks(STAGES[1], "table")[0]
_r = trow(_s1t, "Net excess")
_r[3] = checks("GOALS stage 1, excess anchor", _r[3], [
    (r"earns (\d+\.\d)% a year", 100 * X["qlib_ret"]), (r"at IR (\d\.\d+) net", X["qlib_ir"]),
    (r"net of (\d+)/", X["qlib_open"]), (r"/(\d+) bps", X["qlib_close"]), (r"Q Sharpe of (\d)", X["qpn_sharpe"]),
    (r"only (\d+\.\d)% of", X["m6_beat"]), (r"of (\d+) teams", X["m6_teams"]), (r"over (\d+) months", X["m6_months"])])
_r = trow(_s1t, "Fold floor")
_r[3] = checks("GOALS stage 1, fold-floor anchor", _r[3], [
    (r"Sharpe (\d\.\d+), Numerai", X["num_live_sharpe"]), (r"model (\d+) on validation", X["num_val_sharpe"])])
_r = trow(_s1t, "Cost headroom")
_r[3] = check("GOALS stage 1, cost anchor", _r[3], r"charges ≈ (\d+) bps per side", COST["avg_side"])
_s2t = blocks(STAGES[2], "table")[0]
_r = trow(_s2t, "Probabilistic Sharpe")
_r[3] = checks("GOALS stage 2, PSR anchor", _r[3], [
    (r"\) [≥>] (\d+)%", X["qc_psr"]), (r"only (\d+) of", X["qc_pass"]), (r"of (\d+) strategies", X["qc_n"]),
    (r"\((\d+\.\d)%\)", X["qc_pct"]), (r"below (0\.\d+) across", X["qpn_r2"]), (r"across (\d+) algorithms", X["qpn_n"])])
_r = trow(_s2t, "Deflated Sharpe")
_r[3] = checks("GOALS stage 2, DSR anchor", _r[3], [
    (r"Sharpe > (\d\.\d+)", X["wq_sharpe"]), (r"fitness > (\d)", X["wq_fit"]), (r"turnover (\d+)% to", X["wq_to_lo"]),
    (r"to (\d+)%;", X["wq_to_hi"]), (r"Sharpe (\d\.\d) over", X["dsr_sr"]), (r"with (\d+) trials", X["dsr_n"]),
    (r"DSR (0\.\d+)$", X["dsr"])])
_s3t = blocks(STAGES[3], "table")[0]
_r = trow(_s3t, "Live Sharpe")
_r[2] = checks("GOALS stage 3, anchor", _r[2], [
    (r"Sharpe (\d\.\d+) for 2024", X["numone_sharpe"]), (r"a (\d+\.\d+)% hit rate", X["mercer"]),
    (r"gross Sharpe of (\d\.\d+)", X["jpx_ann"]), (r"of ([\d,]+) entrants", X["jpx_n"])])
G_POSITION = fix_ic("GOALS position", para(sec(GOALS, "Position on the external ladder"), "The community"))
G_PLAIN = [fix_ic("GOALS plain words", t) for t in blocks(sec(GOALS, "What \"good enough\" means"), "ul")[0]]
G_NOT = blocks(sec(GOALS, "Not goals"), "ul")[0]
G_NOT[0] = checks("GOALS not goals", G_NOT[0], [
    (r"\((\d\.\d+) to \d\.\d+ million", X["views_krish"] / 1e6), (r"to (\d\.\d+) million views", X["views_compsci"] / 1e6)])
for _row in _stand["rows"]:
    _row[1] = fix_ic("GOALS where the program stands", _row[1])
    _row[0] = fix_ic("GOALS where the program stands", _row[0])

# ============================================== Chart B: every accuracy claim

ACC_METRIC = re.compile(r"accuracy|hit rate|win rate", re.I)
SKIP_CLAUSE = re.compile(
    r"\?|question|hypothetical|return|drawdown|\bDD\b|lost money|went bust|averaged|\b\d+ of \d+\b", re.I)
RANGE_PCT = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d+)?)\s*[-–]\s*(\d{1,3}(?:\.\d+)?)\s*%")
PCT = re.compile(r"(?<![\w.+\-–])(\d{1,3}(?:\.\d+)?)\s*%")
ACC_DEC = re.compile(r"accuracy\s+(0\.\d+)", re.I)
R2 = re.compile(r"R(?:²|\^2)\s*=?\s*(0\.\d+)|(0\.\d+)\s*R(?:²|\^2)")


def eligible(e: dict) -> bool:
    return e.get("task") in ("direction", "price level") or bool(ACC_METRIC.search(e.get("metric", "")))


def parse_claims(e: dict) -> list[dict]:
    """Tolerant parse of an entry's claimed value into accuracy numbers (percent).

    Clauses are split on ';' and ', '. Clauses that are questions or hypotheticals, money or
    drawdown outcomes, or counts ('468 of 501') are not accuracy claims; a percentage that is the
    premise of a question title is not a claim either. R² is read as R² x 100."""
    premise = set()
    if e["title"].rstrip().endswith("?"):
        premise = {num(x) for x in re.findall(r"(\d{1,3}(?:\.\d+)?)\s*%", e["title"])}
    out = []
    for semi in re.split(r";\s*", e["_claim"]):
        train = bool(re.search(r"training", semi, re.I))
        for clause in re.split(r",\s+", semi):
            if SKIP_CLAUSE.search(clause):
                continue
            found: list[tuple[float, str]] = []
            for m in RANGE_PCT.finditer(clause):
                found += [(num(m.group(1)), "pct"), (num(m.group(2)), "pct")]
            found += [(num(m.group(1)), "pct") for m in PCT.finditer(clause)]
            found += [(100 * num(m.group(1)), "acc") for m in ACC_DEC.finditer(clause)]
            found += [(100 * num(m.group(1) or m.group(2)), "r2") for m in R2.finditer(clause)]
            for v, kind in found:
                if 0 < v <= 100 and not (kind == "pct" and v in premise):
                    out.append({"v": v, "kind": kind, "clause": clause.strip(), "train": train, "e": e,
                                "lane": "price" if e.get("task") == "price level" else "direction",
                                "grade": e["credibility"]})
    return out


CANDIDATES = [e for e in ALL if eligible(e)]
DOTS: list[dict] = []
SKIPPED: list[dict] = []
for _e in CANDIDATES:
    _c = parse_claims(_e)
    (DOTS.extend(_c) if _c else SKIPPED.append(_e))


def fmt_claim(d: dict) -> str:
    return f"R² {fnum(d['v'] / 100, 3)}" if d["kind"] == "r2" else f"{fnum(d['v'])}%"


# Direct labels for Chart B: (stream, title prefix, dot filter, text, placement, dx, dy). Values in the
# text come from the dots; everything else is in the table view. Placement: l/r beside the group,
# a/as/ae above the row (centre/start/end), b/bs/be below it.
B_LABELS = [
    (CP, "Institutional Investor: Medallion", None, "Mercer (Renaissance) {v}", "bs", 0, 0),
    (YT, "Mercer 50.75% quote", None, "Mercer (Renaissance) {v}", "bs", 0, 0),
    (YT, "'They saw the future", None, "students with tomorrow’s paper {v}", "bs", -10, 13),
    (YT, "How to Forecast Stock Index Movement", lambda d: not d["train"], "Nifty next-day, test {v}", "as", 0, 0),
    (YT, "How to Forecast Stock Index Movement", lambda d: d["train"], "Nifty next-day, training {v}", "a", 0, 0),
    (RD, "Twitter Mood Predicts", None, "{v} on about " + fnum(X["twitter_days"]) + " test days", "a", 0, 0),
    (RD, "Stock Prediction Over 90 Percent", lambda d: d["train"], "{v}: label leak, training data", "be", 0, 0),
    (RD, "Targets on Machine Learning approach", None, "{v} win-rate filter", "b", 0, 0),
    (YT, "How (not) to use Machine Learning for time series forecasting: Avoiding", None,
     "{v} on a random walk", "l", 0, 0),
    (YT, "LSTMs in Price Prediction", None, "{v}: “a sophisticated moving average”", "ae", 0, 0),
    (YT, "Guide to Long Short Term Memory", None, "{v} “forecasting accuracy”", "l", 0, 0),
    (YT, "Nestle Stock Price Prediction", None, "Kaggle titles: {v}", "ae", 0, 0),
    (YT, "NVIDIA Stock Price Prediction", None, "Kaggle titles: {v}", "ae", 0, 0),
]

# =================================================================== SVG bits

GRADE_VAR = {"A": "var(--s3)", "B": "var(--s4)", "C": "var(--neg)"}


def svg_open(w: int, h: int, label: str) -> str:
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{esc(label)}">'
            f'<title>{esc(label)}</title>')


def hbar(xa: float, xb: float, y: float, h: float, fill: str, r: float = 4.0, tip: str = "") -> str:
    """Horizontal bar, square at the baseline, 4px rounded data end."""
    w = xb - xa
    if w <= 0.5:
        return ""
    r = min(r, w, h / 2)
    t = f' data-tip="{esc(tip)}"' if tip else ""
    return (f'<path{t} d="M{xa:.1f},{y:.1f}H{xb - r:.1f}Q{xb:.1f},{y:.1f} {xb:.1f},{y + r:.1f}'
            f'V{y + h - r:.1f}Q{xb:.1f},{y + h:.1f} {xb - r:.1f},{y + h:.1f}H{xa:.1f}Z" fill="{fill}"/>')


def tw(s: str, size: float) -> float:
    return len(s) * size * 0.56


def compact(v: float) -> str:
    if v >= 1e6:
        return fnum(v / 1e6, 1) + "M"
    if v >= 1e3:
        return fnum(v / 1e3, 0) + "K"
    return fnum(v, 0)


# ---------------------------------------------------------------- Chart A


def reach_data() -> list[dict]:
    vids = [{"e": e, "views": views(e), "kind": "debunk" if e["task"] == "commentary" else "hype"}
            for e in EV[YT] if views(e)]
    vids.sort(key=lambda v: (v["kind"] != "hype", -v["views"]))
    return vids


def chart_reach(narrow: bool = False) -> str:
    vids = reach_data()
    if narrow:
        W, x0, x1, top, rowh, bh, by, vy = 340, 4, 236, 16, 54, 20, 20, 35
    else:
        W, x0, x1, top, rowh, bh, by, vy = 880, 10, 700, 22, 64, 22, 24, 40
    yb = top + rowh * len(vids)
    H = yb + 44
    step = 500_000
    dmax = step * math.ceil(max(v["views"] for v in vids) / step)

    def sx(v): return lin(v, 0, dmax, x0, x1)
    o = [svg_open(W, H, "Views of the most-viewed price-level tutorials and of the most-viewed debunk")]
    for t in range(0, dmax + 1, step):
        o.append(f'<line x1="{sx(t):.1f}" y1="{top - 4}" x2="{sx(t):.1f}" y2="{yb}" class="grid"/>'
                 f'<text x="{sx(t):.1f}" y="{yb + 17}" class="ax" text-anchor="{"start" if t == 0 else "middle"}">'
                 f'{compact(t)}</text>')
    o.append(f'<line x1="{x0}" y1="{yb}" x2="{x1}" y2="{yb}" class="axisln"/>'
             f'<text x="{x0}" y="{yb + 36}" class="ax">views on each watch page, read {X["views_date"]}</text>')
    for i, v in enumerate(vids):
        e, y = v["e"], top + rowh * i
        title = "" if narrow else f' · “{esc(e["title"])}”'
        o.append(f'<text x="{x0}" y="{y + 14}" class="lbl"><tspan class="lbl-em">{esc(e["author_or_channel"])}'
                 f'</tspan> · {esc(e["date"][:4])}{title}</text>')
        tip = f'{v["views"]:,} views · {e["author_or_channel"]} · grade {e["credibility"]} · {e["task"]}'
        o.append(hbar(x0, sx(v["views"]), y + by, bh, GRADE_VAR[e["credibility"]], tip=tip))
        o.append(f'<text x="{sx(v["views"]) + 7:.1f}" y="{y + vy}" class="val">{v["views"]:,}</text>')
    o.append("</svg>")
    return "".join(o)


# ---------------------------------------------------------------- Chart B


def chart_claims() -> str:
    W = 880
    x0, x1 = 186, 858                 # 50% .. 100%
    gx0, gx1 = 128, 172               # gutter for claims below 50%

    def sx(v): return lin(v, 50, 100, x0, x1)
    lanes = (("direction", "Directional accuracy or hit rate", 52, (84, 140, 196)),
             ("price", "Price-level “accuracy”: price level, not prediction", 252, (286, 342, 398)))
    yc = {(ln, g): ys[k] for ln, _, _, ys in lanes for k, g in enumerate("ABC")}
    axis_y = 428
    H = axis_y + 46
    top_y = yc[("direction", "A")] - 20
    o = [svg_open(W, H, f"Every directional or price-level accuracy claim in the evidence files on a 50 to 100% "
                        f"axis, by credibility grade, with SuryaDhana's {P['hit']:.1f}%")]
    o.append(f'<rect x="{gx0}" y="{top_y}" width="{gx1 - gx0}" height="{axis_y - top_y}" rx="6" fill="var(--hm-0)"/>'
             f'<text x="{(gx0 + gx1) / 2:.1f}" y="{top_y + 14}" class="ax" text-anchor="middle">&lt; 50%</text>')
    for t in range(50, 101, 10):
        o.append(f'<line x1="{sx(t):.1f}" y1="{top_y}" x2="{sx(t):.1f}" y2="{axis_y}" class="grid"/>'
                 f'<text x="{sx(t):.1f}" y="{axis_y + 17}" class="ax" text-anchor="middle">{t}%</text>')
    o.append(f'<line x1="{gx0}" y1="{axis_y}" x2="{x1}" y2="{axis_y}" class="axisln"/>'
             f'<text x="{x0}" y="{axis_y + 36}" class="ax">claimed accuracy or hit rate (R² drawn × 100); '
             f'50% is a coin flip</text>')
    for ln, title, ty, ys in lanes:
        for k, g in enumerate("ABC"):
            y = ys[k]
            o.append(f'<line x1="{gx0}" y1="{y}" x2="{x1}" y2="{y}" stroke="var(--grid)" stroke-width="1"/>')
            mark = (f'<circle cx="16" cy="{y}" r="5" fill="var(--surface)" stroke="{GRADE_VAR[g]}" stroke-width="2.2"/>'
                    if ln == "price" else f'<circle cx="16" cy="{y}" r="5" fill="{GRADE_VAR[g]}"/>')
            o.append(f'{mark}<text x="28" y="{y + 4}" class="lbl">grade {g}</text>')
            if not any(d["lane"] == ln and d["grade"] == g for d in DOTS):
                o.append(f'<text x="{x0 + 52}" y="{y + 4}" class="ax halo">no parsed claim</text>')
    xs = sx(P["hit"])
    o.append(f'<line x1="{xs:.1f}" y1="28" x2="{xs:.1f}" y2="{axis_y}" stroke="var(--accent)" stroke-width="2"/>'
             f'<text x="{xs + 6:.1f}" y="22" class="anno accent">SuryaDhana {P["hit"]:.1f}% '
             f'<tspan class="ax">(implied by rank IC {P["ic3"]}, Sheppard)</tspan></text>')
    for ln, title, ty, ys in lanes:
        o.append(f'<text x="8" y="{ty}" class="colh halo">{esc(title)}</text>')
    # place dots: beeswarm inside each grade row; claims below 50% go to the gutter, in value order
    order = sorted(DOTS, key=lambda d: (d["lane"], d["grade"], d["v"], d["e"]["_stream"], d["e"]["_n"]))
    below = [d for d in order if d["v"] < 50]
    below.sort(key=lambda d: (d["v"], d["e"]["_stream"], d["e"]["_n"]))
    for k, d in enumerate(below):
        d["x"] = gx0 + (k + 1) * (gx1 - gx0) / (len(below) + 1)
    placed: dict = {}
    for d in order:
        if d["v"] >= 50:
            d["x"] = sx(d["v"])
        rk = (d["lane"], d["grade"])
        prev = placed.setdefault(rk, [])
        slot = 0
        for slot in (0, -1, 1, -2, 2):
            if all(abs(d["x"] - px) >= 10 or ps != slot for px, ps in prev):
                break
        prev.append((d["x"], slot))
        d["y"] = yc[rk] + slot * 11
    for d in order:
        e, g = d["e"], d["grade"]
        tip = (f'{fmt_claim(d)} · grade {g} · {e["platform"]} · {e["title"]} · '
               f'{"price level, not prediction" if d["lane"] == "price" else "direction"}')
        if d["lane"] == "price":
            m = (f'<circle cx="{d["x"]:.1f}" cy="{d["y"]:.1f}" r="4.5" fill="var(--surface)" '
                 f'stroke="{GRADE_VAR[g]}" stroke-width="2.2"/>')
        else:
            m = (f'<circle cx="{d["x"]:.1f}" cy="{d["y"]:.1f}" r="4.5" fill="{GRADE_VAR[g]}" '
                 f'stroke="var(--surface)" stroke-width="2"/>')
        o.append(f'<g data-tip="{esc(tip)}"><circle cx="{d["x"]:.1f}" cy="{d["y"]:.1f}" r="11" '
                 f'fill="transparent"/>{m}</g>')
    groups: dict = {}
    for stream, prefix, filt, text, pos, dx, dy in B_LABELS:
        for d in order:
            if d["e"]["_stream"] == stream and d["e"]["title"].startswith(prefix) and (filt is None or filt(d)):
                groups.setdefault((text, pos, d["lane"], d["grade"], dx, dy), []).append(d)
    for (text, pos, ln, g, dx, dy), ds in groups.items():
        vals = sorted({(d["v"], d["kind"]) for d in ds})
        if len(vals) == 2 and all(k == "pct" for _, k in vals) and len({d["e"]["_n"] for d in ds}) == 1:
            vtxt = f"{fnum(vals[0][0])}–{fnum(vals[1][0])}%"
        else:
            vtxt = " and ".join(fmt_claim({"v": v, "kind": k}) for v, k in vals)
        label = text.format(v=vtxt)
        xa, xb = min(d["x"] for d in ds), max(d["x"] for d in ds)
        ymid = sum(d["y"] for d in ds) / len(ds)
        row_y = yc[(ln, g)]
        if pos == "l":
            x, y, anc = xa - 9, ymid + 4, "end"
        elif pos == "r":
            x, y, anc = xb + 9, ymid + 4, "start"
        elif pos in ("a", "as", "ae"):
            y = row_y - 19
            x, anc = {"a": ((xa + xb) / 2, "middle"), "as": (xa - 4, "start"), "ae": (xb + 4, "end")}[pos]
        else:
            y = row_y + 28
            x, anc = {"b": ((xa + xb) / 2, "middle"), "bs": (xa - 4, "start"), "be": (xb + 4, "end")}[pos]
        o.append(f'<text x="{x + dx:.1f}" y="{y + dy:.1f}" class="slbl halo" text-anchor="{anc}">{esc(label)}</text>')
    o.append("</svg>")
    return "".join(o)


B_SHORT = {
    "Mercer (Renaissance) {v}": "Mercer {v}",
    "students with tomorrow’s paper {v}": "newspaper test {v}",
    "Nifty next-day, test {v}": "Nifty test {v}",
    "Nifty next-day, training {v}": "Nifty training {v}",
    "{v}: label leak, training data": "{v}: label leak",
    "{v} on a random walk": "{v}, random walk",
    "{v}: “a sophisticated moving average”": "{v}: “moving average”",
    "{v} “forecasting accuracy”": "{v} price “accuracy”",
    "Kaggle titles: {v}": "Kaggle: {v}",
}


def resolve(ys: list[float], gap: float, lo: float, hi: float) -> list[float]:
    """Nudge label positions apart (min gap), keeping order, within [lo, hi] (the pilot's helper)."""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    pos = [ys[i] for i in order]
    for k in range(1, len(pos)):
        pos[k] = max(pos[k], pos[k - 1] + gap)
    over = pos[-1] - hi if pos else 0
    if over > 0:
        pos = [p - over for p in pos]
        for k in range(len(pos) - 2, -1, -1):
            pos[k] = min(pos[k], pos[k + 1] - gap)
        pos = [max(p, lo) for p in pos]
    out = [0.0] * len(ys)
    for k, i in enumerate(order):
        out[i] = pos[k]
    return out


def chart_claims_narrow() -> str:
    """Phone layout of Chart B: the same claims on a vertical 50-100% axis, grade as the column."""
    W, H = 340, 600
    y_top, y_bot, gut_y = 76, 532, 552

    def sy(v): return lin(v, 50, 100, y_bot, y_top)
    cols = {("direction", "A"): 50, ("direction", "B"): 70, ("direction", "C"): 90,
            ("price", "A"): 124, ("price", "B"): 144, ("price", "C"): 164}
    lab_x, gl0, gl1 = 186, 38, 176
    o = [svg_open(W, H, f"Every directional or price-level accuracy claim in the evidence files on a vertical 50 to "
                        f"100% axis, by credibility grade, with SuryaDhana's {P['hit']:.1f}%")]
    o.append(f'<text x="70" y="16" class="colh" text-anchor="middle">Direction</text>'
             f'<text x="144" y="16" class="colh" text-anchor="middle">Price level</text>'
             f'<text x="144" y="30" class="slbl" text-anchor="middle">not prediction</text>')
    for (ln, g), x in cols.items():
        dot = (f'<circle cx="{x}" cy="46" r="4" fill="var(--surface)" stroke="{GRADE_VAR[g]}" stroke-width="2"/>'
               if ln == "price" else f'<circle cx="{x}" cy="46" r="4" fill="{GRADE_VAR[g]}"/>')
        o.append(f'{dot}<text x="{x}" y="62" class="slbl-em" text-anchor="middle">{g}</text>')
    for t in range(50, 101, 10):
        o.append(f'<line x1="{gl0}" y1="{sy(t):.1f}" x2="{gl1}" y2="{sy(t):.1f}" class="grid"/>'
                 f'<text x="{gl0 - 4}" y="{sy(t) + 4:.1f}" class="ax" text-anchor="end">{t}%</text>')
    o.append(f'<rect x="{gl0}" y="{gut_y - 11}" width="{gl1 - gl0}" height="22" rx="5" fill="var(--hm-0)"/>'
             f'<text x="{gl0 - 4}" y="{gut_y + 4}" class="ax" text-anchor="end">&lt;50</text>'
             f'<text x="8" y="{H - 10}" class="ax">claimed accuracy or hit rate; R² × 100</text>')
    order = sorted(DOTS, key=lambda d: (d["lane"], d["grade"], d["v"], d["e"]["_stream"], d["e"]["_n"]))
    placed: dict = {}
    for d in order:
        ck = (d["lane"], d["grade"])
        y = sy(d["v"]) if d["v"] >= 50 else gut_y
        prev = placed.setdefault(ck, [])
        slot = 0
        for slot in (0, -1, 1, -2, 2, -3, 3):
            if all(abs(y - py) >= 8 or ps != slot for py, ps in prev):
                break
        prev.append((y, slot))
        d["nx"], d["ny"] = cols[ck] + slot * 8, y
    xs_line = sy(P["hit"])
    o.append(f'<line x1="{gl0}" y1="{xs_line:.1f}" x2="{gl1}" y2="{xs_line:.1f}" stroke="var(--accent)" '
             f'stroke-width="2"/>')
    for d in order:
        e, g = d["e"], d["grade"]
        tip = f'{fmt_claim(d)} · grade {g} · {e["platform"]} · {e["title"]}'
        if d["lane"] == "price":
            m = (f'<circle cx="{d["nx"]:.1f}" cy="{d["ny"]:.1f}" r="3.6" fill="var(--surface)" '
                 f'stroke="{GRADE_VAR[g]}" stroke-width="2"/>')
        else:
            m = (f'<circle cx="{d["nx"]:.1f}" cy="{d["ny"]:.1f}" r="3.6" fill="{GRADE_VAR[g]}" '
                 f'stroke="var(--surface)" stroke-width="1.5"/>')
        o.append(f'<g data-tip="{esc(tip)}"><circle cx="{d["nx"]:.1f}" cy="{d["ny"]:.1f}" r="9" '
                 f'fill="transparent"/>{m}</g>')
    groups: dict = {}
    for stream, prefix, filt, text, pos, dx, dy in B_LABELS:
        for d in order:
            if d["e"]["_stream"] == stream and d["e"]["title"].startswith(prefix) and (filt is None or filt(d)):
                groups.setdefault(B_SHORT.get(text, text), []).append(d)
    labels = []
    for text, ds in groups.items():
        vals = sorted({(d["v"], d["kind"]) for d in ds})
        if len(vals) == 2 and all(k == "pct" for _, k in vals) and len({d["e"]["_n"] for d in ds}) == 1:
            vtxt = f"{fnum(vals[0][0])}–{fnum(vals[1][0])}%"
        else:
            vtxt = ", ".join(fmt_claim({"v": v, "kind": k}) for v, k in vals)
        labels.append({"text": text.format(v=vtxt), "y": sum(d["ny"] for d in ds) / len(ds),
                       "x": max(d["nx"] for d in ds), "cls": "slbl"})
    labels.append({"text": f"SuryaDhana {P['hit']:.1f}%", "y": xs_line, "x": gl1, "cls": "anno accent"})
    ys = resolve([lb["y"] + 4 for lb in labels], 13, y_top - 6, gut_y + 8)
    for lb, ly in zip(labels, ys):
        o.append(f'<line x1="{lb["x"] + 5:.1f}" y1="{lb["y"]:.1f}" x2="{lab_x - 4}" y2="{ly - 4:.1f}" '
                 f'stroke="var(--axisc)" stroke-width="1"/>'
                 f'<text x="{lab_x}" y="{ly:.1f}" class="{lb["cls"]}" style="font-size:10.5px">{esc(lb["text"])}</text>')
    o.append("</svg>")
    return "".join(o)


# ---------------------------------------------------------------- Chart C


def chart_ic() -> str:
    W, x0, x1, dmax = 880, 232, 858, 0.16

    def sx(v): return lin(v, 0, dmax, x0, x1)
    rows = [("Numerai live models", "real money, neutralised targets"),
            ("Kaggle winners, live-scored", "forward tests, no costs"),
            ("Qlib reference LightGBM", "open benchmark, CSI300"),
            ("MSCI Barra", "industry rule of thumb"),
            ("M6 organisers", "IC tiers assumed for portfolios"),
            ("QuanterLab IC bands", "practitioner explainer")]
    top, rowh = 64, 46
    ys = [top + rowh * k for k in range(len(rows))]
    axis_y = ys[-1] + 30
    H = axis_y + 48
    o = [svg_open(W, H, f"Information-coefficient benchmarks from 0 to {fnum(dmax, 2)} with SuryaDhana's rank IC "
                        f"{P['ic3']}")]
    for t in range(0, 17, 2):
        v = t / 100
        o.append(f'<line x1="{sx(v):.1f}" y1="{top - 24}" x2="{sx(v):.1f}" y2="{axis_y}" class="grid"/>'
                 f'<text x="{sx(v):.1f}" y="{axis_y + 17}" class="ax" text-anchor="middle">'
                 f'{f"{v:.2f}" if t else "0"}</text>')
    o.append(f'<line x1="{x0}" y1="{axis_y}" x2="{x1}" y2="{axis_y}" class="axisln"/>'
             f'<text x="{x0}" y="{axis_y + 36}" class="ax">information coefficient: rank correlation of forecast '
             f'and return per date</text>')
    for (name, sub), y in zip(rows, ys):
        o.append(f'<text x="8" y="{y - 1}" class="lbl-em">{esc(name)}</text>'
                 f'<text x="8" y="{y + 13}" class="slbl">{esc(sub)}</text>')

    def dot(v, y, e, tip):
        return (f'<g data-tip="{esc(tip)} · grade {e["credibility"]}"><circle cx="{sx(v):.1f}" cy="{y}" r="11" '
                f'fill="transparent"/><circle cx="{sx(v):.1f}" cy="{y}" r="5.5" fill="{GRADE_VAR[e["credibility"]]}" '
                f'stroke="var(--surface)" stroke-width="2"/></g>')

    def band(lo, hi, y, e, tip, op=".34"):
        return (f'<rect data-tip="{esc(tip)} · grade {e["credibility"]}" x="{sx(lo):.1f}" y="{y - 8}" '
                f'width="{sx(hi) - sx(lo):.1f}" height="16" rx="4" fill="{GRADE_VAR[e["credibility"]]}" '
                f'fill-opacity="{op}"/>')

    def tick(v, y, e, label, tip):
        return (f'<g data-tip="{esc(tip)} · grade {e["credibility"]}"><rect x="{sx(v) - 2:.1f}" y="{y - 9}" '
                f'width="4" height="18" rx="2" fill="{GRADE_VAR[e["credibility"]]}"/>'
                f'<text x="{sx(v):.1f}" y="{y - 14}" class="slbl halo" text-anchor="middle">{esc(label)}</text></g>')

    def text(x, y, s, anc="start"):
        return f'<text x="{x:.1f}" y="{y + 4}" class="slbl halo" text-anchor="{anc}">{esc(s)}</text>'
    lo, hi = X["num_live"][0], X["num_live"][-1]
    o.append(band(lo, hi, ys[0], e_numsig, f"Numerai Signals live models {fnum(lo, 4)}–{fnum(hi, 4)}"))
    o.append(text(sx(hi) + 8, ys[0], f"{fnum(lo, 3)}–{fnum(hi, 3)} live CORR"))
    o.append(dot(X["gres"], ys[1], e_gres, f"G-Research crypto winner {fnum(X['gres'], 4)}"))
    o.append(text(sx(X["gres"]) - 10, ys[1], f"G-Research crypto {fnum(X['gres'], 4)}", "end"))
    o.append(dot(X["ubi"], ys[1], e_ubi, f"Ubiquant winner {fnum(X['ubi'], 6)}"))
    o.append(text(sx(X["ubi"]) - 10, ys[1], f"Ubiquant {fnum(X['ubi'], 3)} (fund features)", "end"))
    o.append(dot(X["qlib_ic"], ys[2], e_qlib, f"Qlib LightGBM IC {fnum(X['qlib_ic'], 4)}"))
    o.append(dot(X["qlib_ric"], ys[2], e_qlib, f"Qlib LightGBM rank IC {fnum(X['qlib_ric'], 4)}"))
    o.append(text(sx(X["qlib_ic"]) - 12, ys[2],
                  f"IC {fnum(X['qlib_ic'], 4)} · rank IC {fnum(X['qlib_ric'], 4)}", "end"))
    for v, lab in ((X["msci_good"], "good"), (X["msci_vgood"], "very good")):
        o.append(tick(v, ys[3], e_msci, f"{lab} {v:.2f}", f"MSCI Barra “{lab}” IC {v:.2f}"))
    for v, lab in ((X["m6_mod"], "moderate"), (X["m6_good"], "good"), (X["m6_exc"], "exceptional")):
        o.append(tick(v, ys[4], e_m6t, f"{lab} {v:.2f}", f"M6 organisers “{lab}” IC {v:.2f}"))
    for (lo, hi), lab in ((X["ql_real"], "real signal"), (X["ql_strong"], "strong, rare")):
        o.append(band(lo, hi, ys[5], e_qlab, f"QuanterLab: {fnum(lo, 2)}–{fnum(hi, 2)} {lab}"))
        o.append(f'<text x="{sx((lo + hi) / 2):.1f}" y="{ys[5] + 4}" class="slbl" text-anchor="middle">'
                 f'{esc(lab)}</text>')
    o.append(band(X["ql_susp"], dmax, ys[5], e_qlab, f"QuanterLab: above {fnum(X['ql_susp'], 2)} suspicious", ".6"))
    o.append(f'<text x="{x1:.1f}" y="{ys[5] - 14}" class="slbl halo" text-anchor="end">above '
             f'{X["ql_susp"]:.2f}: “suspicious”</text>')
    xs = sx(P["ic"])
    o.append(f'<line x1="{xs:.1f}" y1="{top - 30}" x2="{xs:.1f}" y2="{axis_y}" stroke="var(--accent)" stroke-width="2"/>'
             f'<text x="{xs + 6:.1f}" y="{top - 36}" class="anno accent">SuryaDhana {P["ic3"]} '
             f'<tspan class="ax">nested LightGBM, Newey-West t {P["ic_t"]:.1f}</tspan></text>')
    o.append("</svg>")
    return "".join(o)


def chart_ic_narrow() -> str:
    """Phone layout of Chart C: each row's name above its strip, marker labels below."""
    W, x0, x1, dmax = 340, 12, 328, 0.16

    def sx(v): return lin(v, 0, dmax, x0, x1)
    rows = [("Numerai live models", "neutralised targets"), ("Kaggle winners", "live-scored"),
            ("Qlib LightGBM", "CSI300"), ("MSCI Barra", "rule of thumb"), ("M6 organisers", "assumed tiers"),
            ("QuanterLab", "IC bands")]
    top, rowh = 74, 58
    ys = [top + rowh * k for k in range(len(rows))]
    axis_y = ys[-1] + 34
    H = axis_y + 40
    o = [svg_open(W, H, f"Information-coefficient benchmarks from 0 to {fnum(dmax, 2)} with SuryaDhana's rank IC "
                        f"{P['ic3']}")]
    for t in range(0, 17, 4):
        v = t / 100
        o.append(f'<line x1="{sx(v):.1f}" y1="{top - 40}" x2="{sx(v):.1f}" y2="{axis_y}" class="grid"/>'
                 f'<text x="{sx(v):.1f}" y="{axis_y + 16}" class="ax" text-anchor="{"start" if t == 0 else "middle"}">'
                 f'{f"{v:.2f}" if t else "0"}</text>')
    o.append(f'<line x1="{x0}" y1="{axis_y}" x2="{x1}" y2="{axis_y}" class="axisln"/>'
             f'<text x="{x0}" y="{axis_y + 33}" class="ax">rank IC per date</text>')
    for (name, sub), y in zip(rows, ys):
        o.append(f'<text x="{x0}" y="{y - 17}" class="lbl-em halo">{esc(name)} '
                 f'<tspan class="slbl" style="font-weight:400">{esc(sub)}</tspan></text>')

    def mark(kind, v, y, e, tip, v2=None):
        g = GRADE_VAR[e["credibility"]]
        t = f' data-tip="{esc(tip)} · grade {e["credibility"]}"'
        if kind == "dot":
            return (f'<g{t}><circle cx="{sx(v):.1f}" cy="{y}" r="10" fill="transparent"/>'
                    f'<circle cx="{sx(v):.1f}" cy="{y}" r="5" fill="{g}" stroke="var(--surface)" stroke-width="2"/></g>')
        if kind == "tick":
            return f'<rect{t} x="{sx(v) - 2:.1f}" y="{y - 8}" width="4" height="16" rx="2" fill="{g}"/>'
        return (f'<rect{t} x="{sx(v):.1f}" y="{y - 7}" width="{sx(v2) - sx(v):.1f}" height="14" rx="4" fill="{g}" '
                f'fill-opacity="{".6" if v2 == dmax else ".34"}"/>')

    def lab(x, y, s, anc="middle"):
        return f'<text x="{x:.1f}" y="{y + 19}" class="slbl halo" text-anchor="{anc}">{esc(s)}</text>'
    lo, hi = X["num_live"][0], X["num_live"][-1]
    o.append(mark("band", lo, ys[0], e_numsig, f"Numerai Signals live models {fnum(lo, 4)}–{fnum(hi, 4)}", hi))
    o.append(lab(sx(lo), ys[0], f"{fnum(lo, 3)}–{fnum(hi, 3)}", "start"))
    o.append(mark("dot", X["gres"], ys[1], e_gres, f"G-Research crypto winner {fnum(X['gres'], 4)}"))
    o.append(lab(sx(X["gres"]), ys[1], f"G-Research {fnum(X['gres'], 4)}"))
    o.append(mark("dot", X["ubi"], ys[1], e_ubi, f"Ubiquant winner {fnum(X['ubi'], 6)}"))
    o.append(lab(sx(X["ubi"]), ys[1], f"Ubiquant {fnum(X['ubi'], 3)}"))
    o.append(mark("dot", X["qlib_ic"], ys[2], e_qlib, f"Qlib LightGBM IC {fnum(X['qlib_ic'], 4)}"))
    o.append(mark("dot", X["qlib_ric"], ys[2], e_qlib, f"Qlib LightGBM rank IC {fnum(X['qlib_ric'], 4)}"))
    o.append(lab(x0, ys[2], f"IC {fnum(X['qlib_ic'], 4)}, rank {fnum(X['qlib_ric'], 4)}", "start"))
    for k, (v, name) in enumerate(((X["msci_good"], "good"), (X["msci_vgood"], "very good"))):
        o.append(mark("tick", v, ys[3], e_msci, f"MSCI Barra “{name}” IC {v:.2f}"))
        o.append(lab(sx(v) - 5 if k == 0 else sx(v), ys[3], f"{name} {v:.2f}", "end" if k == 0 else "middle"))
    m6 = ((X["m6_mod"], "moderate", "end", -5), (X["m6_good"], "good", "end", -5), (X["m6_exc"], "exceptional", "end", 2))
    for v, name, anc, dx in m6:
        o.append(mark("tick", v, ys[4], e_m6t, f"M6 organisers “{name}” IC {v:.2f}"))
        o.append(lab(min(sx(v) + dx, x1), ys[4], f"{name} {v:.2f}", anc))
    for (lo, hi), name in ((X["ql_real"], "real"), (X["ql_strong"], "strong, rare")):
        o.append(mark("band", lo, ys[5], e_qlab, f"QuanterLab: {fnum(lo, 2)}–{fnum(hi, 2)} {name}", hi))
        o.append(f'<text x="{(sx(lo) + sx(hi)) / 2:.1f}" y="{ys[5] + 4}" class="slbl" text-anchor="middle">'
                 f'{esc(name)}</text>')
    o.append(mark("band", X["ql_susp"], ys[5], e_qlab, f"QuanterLab: above {X['ql_susp']:.2f} suspicious", dmax))
    o.append(lab(x1, ys[5], f"> {X['ql_susp']:.2f} “suspicious”", "end"))
    xs = sx(P["ic"])
    o.append(f'<line x1="{xs:.1f}" y1="{top - 50}" x2="{xs:.1f}" y2="{axis_y}" stroke="var(--accent)" stroke-width="2"/>'
             f'<text x="{xs + 5:.1f}" y="{top - 54}" class="anno accent">SuryaDhana {P["ic3"]} '
             f'<tspan class="ax">t {P["ic_t"]:.1f}</tspan></text>')
    o.append("</svg>")
    return "".join(o)


# ---------------------------------------------------------------- Chart D


def chart_sheppard(narrow: bool = False) -> str:
    if narrow:
        W, H, x0, x1, y0, y1 = 340, 384, 42, 320, 30, 330
    else:
        W, H, x0, x1, y0, y1 = 720, 404, 64, 700, 40, 344
    ic_max, h_lo, h_hi = 0.20, 50, 57

    def Xs(ic): return lin(ic, 0, ic_max, x0, x1)

    def Ys(h): return lin(h, h_lo, h_hi, y1, y0)
    o = [svg_open(W, H, "Hit rate implied by the information coefficient, Sheppard's formula, with community anchors "
                        "and SuryaDhana")]
    zx = Xs(X["ql_susp"])
    o.append(f'<rect x="{zx:.1f}" y="{y0}" width="{Xs(ic_max) - zx:.1f}" height="{y1 - y0}" fill="var(--hm-n1)"/>'
             f'<text x="{Xs(ic_max) - 6:.1f}" y="{y1 - 24}" class="slbl-em" text-anchor="end">IC above '
             f'{X["ql_susp"]:.2f}:</text>'
             f'<text x="{Xs(ic_max) - 6:.1f}" y="{y1 - 10}" class="slbl" text-anchor="end">“suspicious”'
             f'{"" if narrow else " (QuanterLab)"}</text>')
    for t in range(0, 21, 5):
        v = t / 100
        o.append(f'<line x1="{Xs(v):.1f}" y1="{y0}" x2="{Xs(v):.1f}" y2="{y1}" class="grid"/>'
                 f'<text x="{Xs(v):.1f}" y="{y1 + 17}" class="ax" text-anchor="middle">{f"{v:.2f}" if t else "0"}</text>')
    for h in range(h_lo, h_hi + 1):
        o.append(f'<line x1="{x0}" y1="{Ys(h):.1f}" x2="{x1}" y2="{Ys(h):.1f}" class="grid"/>'
                 f'<text x="{x0 - 6}" y="{Ys(h) + 4:.1f}" class="ax" text-anchor="end">{h}%</text>')
    cap = "rank IC; curve ½ + arcsin(IC)/π" if narrow else \
        "information coefficient (IC); curve: hit rate = ½ + arcsin(IC)/π"
    o.append(f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" class="axisln"/>'
             f'<text x="{x0}" y="{y1 + 36}" class="ax">{cap}</text>')
    pts = " ".join(f"{Xs(i / 1000):.1f},{Ys(hit(i / 1000)):.1f}" for i in range(0, int(ic_max * 1000) + 1, 2))
    o.append(f'<polyline points="{pts}" fill="none" stroke="var(--ink2)" stroke-width="2" stroke-linejoin="round"/>')
    big = ic_for(LOUD_LO)
    if narrow:
        o.append(f'<text x="{x0 + 8}" y="{y0 + 18}" class="slbl-em">{fnum(LOUD_LO)}% would need IC {fnum(big, 2)},</text>'
                 f'<text x="{x0 + 8}" y="{y0 + 32}" class="slbl">about {big / ic_max:.0f} × this chart’s width</text>')
    else:
        o.append(f'<text x="{x0 + 10}" y="{y0 + 20}" class="slbl-em">{fnum(LOUD_LO)}% “accuracy” would need IC '
                 f'{fnum(big, 2)}</text>'
                 f'<text x="{x0 + 10}" y="{y0 + 36}" class="slbl">far off this chart: about {big / ic_max:.0f} times '
                 f'its width</text>')

    def point(h, g, label, dx, dy, anc, tip, r=5.5):
        x, y = Xs(ic_for(h)), Ys(h)
        return (f'<g data-tip="{esc(tip)}"><circle cx="{x:.1f}" cy="{y:.1f}" r="11" fill="transparent"/>'
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{g}" stroke="var(--surface)" stroke-width="2"/></g>'
                f'<text x="{x + dx:.1f}" y="{y + dy:.1f}" class="slbl halo" text-anchor="{anc}">{esc(label)}</text>')
    gm, gn, gf = (GRADE_VAR[e["credibility"]] for e in (e_mercer, e_news, e_nifty))
    mer = "Mercer" if narrow else "Mercer (Renaissance)"
    news = "newspaper test" if narrow else "students with tomorrow’s paper"
    o.append(point(X["mercer"], gm, f"{mer} {fnum(X['mercer'])}%", 9, 15, "start",
                   f"Mercer {X['mercer']}% → IC {ic_for(X['mercer']):.3f}"))
    o.append(point(X["news_hit"], gn, f"{news} {fnum(X['news_hit'])}%", 9, 15, "start",
                   f"newspaper experiment {X['news_hit']}% → IC {ic_for(X['news_hit']):.3f}"))
    lo, hi = X["nifty_lo"], X["nifty_hi"]
    seg = " ".join(f"{Xs(ic_for(lo + (hi - lo) * k / 20)):.1f},{Ys(lo + (hi - lo) * k / 20):.1f}" for k in range(21))
    nif = "Nifty test" if narrow else "Nifty next-day test"
    o.append(f'<polyline data-tip="Nifty next-day test {fnum(lo)}–{fnum(hi)}% → IC {ic_for(lo):.3f}–{ic_for(hi):.3f}" '
             f'points="{seg}" fill="none" stroke="{gf}" stroke-width="{6 if narrow else 7}" stroke-linecap="round"/>'
             f'<text x="{Xs(ic_for(lo)) - 8:.1f}" y="{Ys(lo) - 14:.1f}" class="slbl halo" text-anchor="end">'
             f'{nif} {fnum(lo)}–{fnum(hi)}%</text>')
    x, y = Xs(P["ic"]), Ys(P["hit"])
    tail = "" if narrow else f" at rank IC {P['ic3']}"
    o.append(f'<g data-tip="SuryaDhana rank IC {P["ic"]:.4f} → {P["hit"]:.2f}%"><circle cx="{x:.1f}" cy="{y:.1f}" '
             f'r="12" fill="transparent"/><circle cx="{x:.1f}" cy="{y:.1f}" r="{6 if narrow else 7}" '
             f'fill="var(--accent)" stroke="var(--surface)" stroke-width="2"/></g>'
             f'<text x="{x + 11:.1f}" y="{y + 17:.1f}" class="anno accent halo">SuryaDhana {P["hit"]:.1f}%{tail}</text>')
    o.append("</svg>")
    return "".join(o)


# ---------------------------------------------------------------- Chart E


def cost_levels() -> list[dict]:
    lv = [(P["bps_lo"], P["net_lo"]), (P["cost_bps"], P["ens"]), (P["bps_hi"], P["net_hi"])]
    return [{"bps": b, "net": n, "costs": P["gross"] - n, "share": (P["gross"] - n) / P["gross"]} for b, n in lv]


def chart_costs(narrow: bool = False) -> str:
    lv = cost_levels()
    dmax = 2 * math.ceil(P["gross"] / 2)
    if narrow:
        W, x0, x1, top, rowh = 340, 4, 196, 58, 66
    else:
        W, x0, x1, top, rowh = 880, 190, 690, 50, 52
    axis_y = top + rowh * len(lv) - (2 if narrow else 8)
    H = axis_y + 44

    def Xc(v): return lin(v, 0, dmax, x0, x1)
    o = [svg_open(W, H, f"Gross active return of about {P['gross']:.1f}% a year split into costs and net excess at "
                        f"10, 20 and 40 bps per side, with Carver's one-third limit")]
    for t in range(0, int(dmax) + 1, 4 if narrow else 2):
        o.append(f'<line x1="{Xc(t):.1f}" y1="{top - 14}" x2="{Xc(t):.1f}" y2="{axis_y}" class="grid"/>'
                 f'<text x="{Xc(t):.1f}" y="{axis_y + 17}" class="ax" text-anchor="{"start" if t == 0 else "middle"}">'
                 f'{t}%</text>')
    cap = ("% a year vs the equal-weight universe" if narrow else
           "% a year, long-only top decile of the rank ensemble, vs the equal-weight universe")
    o.append(f'<line x1="{x0}" y1="{axis_y}" x2="{x1}" y2="{axis_y}" class="axisln"/>'
             f'<text x="{x0}" y="{axis_y + 36}" class="ax">{cap}</text>')
    for i, d in enumerate(lv):
        y = top + rowh * i + (16 if narrow else 0)
        base = d["bps"] == P["cost_bps"]
        name = f'{d["bps"]:.0f} bps per side'
        sub = "base case" if base else ("stress" if d["bps"] > P["cost_bps"] else "sensitivity")
        if narrow:
            o.append(f'<text x="{x0}" y="{y - 6}" class="{"lbl-em" if base else "lbl"} halo">{name} '
                     f'<tspan class="slbl">· {sub}</tspan></text>')
        else:
            o.append(f'<text x="{x0 - 12}" y="{y + 9}" class="{"lbl-em" if base else "lbl"}" text-anchor="end">{name}'
                     f'</text><text x="{x0 - 12}" y="{y + 24}" class="slbl" text-anchor="end">{sub}</text>')
        xc = Xc(d["costs"])
        o.append(f'<rect data-tip="costs {d["costs"]:.1f}% a year at {d["bps"]:.0f} bps" x="{x0}" y="{y}" '
                 f'width="{xc - x0 - 1:.1f}" height="22" fill="var(--neg)"/>')
        o.append(hbar(xc + 1, Xc(P["gross"]), y, 22, "var(--pos)",
                      tip=f'net +{d["net"]:.1f}% a year at {d["bps"]:.0f} bps'))
        share = f'{100 * d["share"]:.0f}%' if narrow else f'{100 * d["share"]:.0f}% of gross'
        o.append(f'<text x="{Xc(P["gross"]) + 8:.1f}" y="{y + 9}" class="val">net +{d["net"]:.1f}%</text>'
                 f'<text x="{Xc(P["gross"]) + 8:.1f}" y="{y + 23}" class="slbl">costs {d["costs"]:.1f}% · {share}</text>')
    xl = Xc(P["gross"] / CARVER_DIV)
    frac = {2: "½", 3: "⅓", 4: "¼"}[CARVER_DIV]
    lab = (f"Carver: costs ≤ {frac} ({P['gross'] / CARVER_DIV:.1f}% a year here)" if narrow else
           f"Carver: costs ≤ {frac} of pre-cost return ({P['gross'] / CARVER_DIV:.1f}% a year here)")
    o.append(f'<line x1="{xl:.1f}" y1="{top - 18}" x2="{xl:.1f}" y2="{axis_y}" stroke="var(--ink)" stroke-width="1.6" '
             f'stroke-dasharray="5 4"/><text x="{xl - 4 if narrow else xl + 6:.1f}" y="{top - 24}" class="slbl-em" '
             f'text-anchor="{"start" if not narrow else "start"}">{lab}</text>')
    o.append("</svg>")
    return "".join(o)


# ================================================================ HTML pieces


def gchip(e: dict) -> str:
    g = e["credibility"]
    return (f'<a class="g g{g}" href="{esc(e["url"])}" title="{esc(e["platform"] + ": " + e["title"])}" '
            f'rel="noopener"><i></i>{g}</a>')


def gtag(g: str) -> str:
    return f'<span class="g g{g}"><i></i>{g}</span>'


STATUS_CLS = {"met": "met", "partial": "partial", "not met": "not", "not applicable": "na", "fixed": "met",
              "in place": "met", "open": "partial"}


def chip(status: str) -> str:
    return f'<span class="st {STATUS_CLS[status]}"><i></i>{esc(status)}</span>'


def md_table(tbl: dict, cls: str = "rt", src: dict | None = None, bold_first: bool = True,
             cells=None) -> str:
    head = list(tbl["head"]) + (["Sources"] if src is not None else [])
    o = [f'<div class="tblwrap"><table class="{cls}"><thead><tr>']
    o += [f"<th>{inline(h)}</th>" for h in head]
    o.append("</tr></thead><tbody>")
    for r in tbl["rows"]:
        o.append("<tr>")
        for j, c in enumerate(r):
            body = inline(c) if c else '<span class="dim2">—</span>'
            if cells:
                body = cells(r, j, body)
            lab = esc(plain(tbl["head"][j]).split(" (")[0])
            o.append(f'<td data-label="{lab}"{" class=" + chr(34) + "first" + chr(34) if j == 0 and bold_first else ""}>'
                     f'{body}</td>')
        if src is not None:
            es = sources_for(src, r[0])
            o.append(f'<td data-label="Sources" class="srcs-c">{"".join(gchip(e) for e in es) or "—"}</td>')
        o.append("</tr>")
    o.append("</tbody></table></div>")
    return "".join(o)


def row_status(cell: str) -> str:
    t = plain(cell).lower()
    if re.search(r":\s*met\b", t) and "not met" in t:
        return "partial"
    if re.search(r"\bnot met\b|not yet|not done|\bneeds about\b", t):
        return "not met"
    m = re.fullmatch(r"(\d+) of (\d+)", t.strip())
    if m:
        return "met" if m.group(1) == m.group(2) else "not met"
    if re.search(r":\s*met\b|all pass", t):
        return "met"
    return "partial"


def fm_status(cell: str) -> str:
    t = plain(cell).lower()
    if t.startswith("not applicable"):
        return "not applicable"
    if "found and fixed" in t:
        return "fixed"
    if re.search(r"\bopen\b|weak link", t):
        return "open"
    return "in place"


def ladder_html() -> str:
    rungs = []
    for r in LADDER_TBL["rows"]:
        m = re.match(r"(\d)\.\s*(.*)", plain(r[0]))
        rungs.append({"n": int(m.group(1)), "name": m.group(2), "ic": r[1], "hit": r[2], "econ": r[3],
                      "track": r[4], "sd": r[5]})
    o = ['<div class="ladder">']
    for g in sorted(rungs, key=lambda g: -g["n"]):
        sd = plain(g["sd"]).lower()
        cls, marker = "", ""
        if "rank ensemble sits here" in sd:
            cls, marker = " here", '<span class="mk ens">◆ rank ensemble</span>'
        elif "single models" in sd and "sit here" in sd:
            cls, marker = " single", '<span class="mk single">● single models</span>'
        elif sd.startswith("not reached"):
            cls, marker = " next", '<span class="mk nr">not reached</span>'
        sd_html = inline(g["sd"])
        if sd.startswith("not reached"):
            reasons = re.split(r";\s*", re.sub(r"^\*\*not reached\*\*:\s*", "", g["sd"]))
            sd_html = ('<b>Not reached.</b><ul class="why">' + "".join(f"<li>{inline(x)}</li>" for x in reasons)
                       + "</ul>")
        crit = [("IC (level, stability)", g["ic"]), ("Implied hit rate", g["hit"]),
                ("Economics after costs", g["econ"]), ("Track record", g["track"])]
        o.append(f'<div class="rung{cls}"><div class="rail"><span class="rnum">{g["n"]}</span></div>'
                 f'<div class="rbody"><div class="rh"><h3>{esc(g["name"])}</h3>{marker}</div><div class="crit">'
                 + "".join(f'<div><div class="k">{esc(k)}</div><div class="v">{inline(v) if v else "—"}</div></div>'
                           for k, v in crit)
                 + f'</div><div class="sd"><span class="k">SuryaDhana</span> {sd_html}</div></div></div>')
    o.append("</div>")
    return "".join(o)


def stage_cards() -> str:
    o = ['<div class="stages">']
    for s in STAGES:
        m = re.match(r"Stage (\d): (.*?) \(status: \*\*(.+?)\*\*\)", s["title"])
        n, name, status = m.group(1), m.group(2), m.group(3)
        st_cls = "not" if status.startswith("not") else "met"
        desc = "".join(f"<p>{inline(p)}</p>" for p in blocks(s, "p"))
        tbl = blocks(s, "table")[0]
        has_sd = any(plain(h) == "SuryaDhana" for h in tbl["head"])

        def cells(r, j, body, tbl=tbl):
            if plain(tbl["head"][j]) == "SuryaDhana":
                return f'{chip(row_status(r[j]))}<div class="sdv">{body}</div>'
            return body
        note_html = ("" if has_sd else '<p class="cap">GOALS.md gives no per-criterion status for this stage; the '
                     'stage as a whole is not met.</p>')
        o.append(f'<article class="stage"><div class="sh"><div><div class="sk">Stage {n}</div>'
                 f'<h3>{esc(name[0].upper() + name[1:])}</h3></div>'
                 f'<span class="st {st_cls}"><i></i>{esc(status)}</span></div>{desc}'
                 f'{md_table(tbl, "rt crit-t", cells=cells)}{note_html}</article>')
    o.append("</div>")
    return "".join(o)


def failure_table() -> str:
    def cells(r, j, body):
        if j == 2:
            return f'{chip(fm_status(r[2]))}<div class="sdv">{body}</div>'
        return body
    return md_table(FAIL_TBL, "rt", cells=cells)


def cost_table() -> str:
    clauses = [c.strip() for c in re.split(r";\s*", re.sub(r"^Equity delivery:\s*", "", e_zc["_claim"]))]
    bps = {"brokerage": COST["brokerage"], "STT": COST["stt"], "NSE": COST["nse"], "SEBI": COST["sebi"],
           "stamp": COST["stamp"], "GST": COST["gst"], "DP": None}
    side = {"brokerage": "each side", "STT": "each side", "NSE": "each side", "SEBI": "each side",
            "stamp": "buys only", "GST": "each side", "DP": "sells, per scrip"}
    o = ['<div class="tblwrap"><table class="rt costs"><thead><tr><th>Charge (Zerodha schedule, as captured)</th>'
         '<th>Applies</th><th>bps per side (computed)</th></tr></thead><tbody>']
    for c in clauses:
        key = next(k for k in bps if c.startswith(k))
        v = bps[key]
        vtxt = "fixed fee, not a rate" if v is None else f"{v:.3f}".rstrip("0").rstrip(".") if v else "0"
        o.append(f'<tr><td data-label="Charge">{esc(c)}</td><td data-label="Applies">{side[key]}</td>'
                 f'<td data-label="bps per side" class="numc">{vtxt}</td></tr>')
    o.append(f'<tr class="tot"><td data-label="Charge">Statutory total (STT + NSE + SEBI + GST)</td>'
             f'<td data-label="Applies">each side</td><td data-label="bps per side" class="numc">{COST["side"]:.2f}</td></tr>'
             f'<tr class="tot"><td data-label="Charge">plus stamp duty</td><td data-label="Applies">buys only</td>'
             f'<td data-label="bps per side" class="numc">{COST["stamp"]:.1f}</td></tr>'
             f'<tr><td data-label="Charge">Left for spread and impact inside the program’s {P["cost_bps"]:.0f} bps base '
             f'case (stamp averaged over both sides)</td><td data-label="Applies">average side</td>'
             f'<td data-label="bps per side" class="numc">{P["cost_bps"] - COST["avg_side"]:.1f}</td></tr>')
    o.append("</tbody></table></div>")
    return "".join(o)


def vmark(e: dict) -> str:
    if "verification" in e:
        return e["verification"]
    if e["_stream"] == RD:
        return "unverified (snippet only)" if e["method_notes"].lower().startswith("unverified (snippet only)") else ""
    cr = e["credibility_reason"]
    m = re.match(r"(unverified \(snippet only\)[^;:.]*)", cr, re.I)
    if m:
        return m.group(1)[0].lower() + m.group(1)[1:]
    parts = []
    if re.search(r"fetched|extracted and read", cr, re.I):
        parts.append("fetched")
    if re.search(r"snippet", cr + " " + e["value"], re.I):
        parts.append("some values from search snippets")
    return "; ".join(parts)


def vclass(mark: str) -> str:
    t = mark.lower()
    if t.startswith("unverified"):
        return "vu"
    if t.startswith("partly") or "snippet" in t:
        return "vp"
    return "vv"


def source_item(e: dict) -> str:
    mark = vmark(e)
    who = e.get("author_or_channel") or e.get("community") or ""
    meta = " · ".join(x for x in (e["platform"], who, e["date"]) if x)
    q = e["quote"].strip()
    quote = (f"<blockquote>{esc(q)}</blockquote>" if q and q.lower() != "none"
             else '<p class="noq">No verbatim quote captured.</p>')
    mk = f' <span class="vm {vclass(mark)}">{esc(mark)}</span>' if mark else ""
    return (f'<li class="src"><div class="srch">{gtag(e["credibility"])}<b>{esc(e["title"])}</b></div>'
            f'<div class="srcm">#{e["_n"]} · {esc(meta)}{mk}</div>{quote}'
            f'<a class="srcu" href="{esc(e["url"])}" rel="noopener">{esc(e["url"])}</a></li>')


def sources_html() -> str:
    o = []
    for key in STREAM_KEYS:
        rows = EV[key]
        gc = grade_counts(rows)
        groups: dict[str, list[dict]] = {}
        for e in rows:
            groups.setdefault(e["platform"], []).append(e)
        o.append(f'<details class="srcd"><summary>{esc(AREAS[key])} <span class="dim2">· {len(rows)} entries · '
                 f'{gc["A"]} A · {gc["B"]} B · {gc["C"]} C · {key}.json</span></summary>')
        for plat, es in groups.items():
            o.append(f'<h4 class="srcp">{esc(plat)} <span class="dim2">· {len(es)}</span></h4><ul class="srcl">')
            o += [source_item(e) for e in es]
            o.append("</ul>")
        o.append("</details>")
    return "".join(o)


def coverage_table() -> str:
    o = ['<div class="tblwrap"><table class="plain cov"><thead><tr><th>Stream</th><th>A</th><th>B</th><th>C</th>'
         '<th>Entries</th><th>Snippet only</th></tr></thead><tbody>']
    tot = {"A": 0, "B": 0, "C": 0, "n": 0, "s": 0}
    for key in STREAM_KEYS:
        rows = EV[key]
        gc = grade_counts(rows)
        s = sum(1 for e in rows if vclass(vmark(e)) == "vu")
        for g in "ABC":
            tot[g] += gc[g]
        tot["n"] += len(rows)
        tot["s"] += s
        o.append(f'<tr><td>{esc(AREAS[key])}</td><td>{gc["A"]}</td><td>{gc["B"]}</td><td>{gc["C"]}</td>'
                 f'<td><b>{len(rows)}</b></td><td>{s}</td></tr>')
    o.append(f'<tr class="tot"><td>All three files</td><td>{tot["A"]}</td><td>{tot["B"]}</td><td>{tot["C"]}</td>'
             f'<td><b>{tot["n"]}</b></td><td>{tot["s"]}</td></tr></tbody></table></div>')
    return "".join(o)


def details_table(summary: str, head: list[str], rows: list[list[str]]) -> str:
    o = [f'<details class="tv"><summary>{esc(summary)}</summary><div class="tblwrap"><table class="rt tvt"><thead><tr>']
    o += [f"<th>{esc(h)}</th>" for h in head]
    o.append("</tr></thead><tbody>")
    for r in rows:
        o.append("<tr>" + "".join(f'<td data-label="{esc(h)}">{c}</td>' for h, c in zip(head, r)) + "</tr>")
    o.append("</tbody></table></div></details>")
    return "".join(o)


def link(e: dict) -> str:
    return f'<a href="{esc(e["url"])}" rel="noopener">{esc(e["title"])}</a>'


# ===================================================================== CSS/JS

CSS = """
/* Tokens, type and patterns shared with the pilot report (ml/report/index.html):
   serif prose, sans headings and data, mono for code. Page-specific rules follow. */
:root{
  --bg:#f9f9f7; --surface:#fcfcfb; --ink:#161513; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axisc:#c3c2b7; --border:rgba(11,11,11,.10);
  --accent:#9a5b00; --accent-soft:rgba(154,91,0,.10);
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4; --s6:#008300; --s7:#6250d6;
  --pos:#2a78d6; --neg:#e34948; --good:#006300; --bad:#b32e2e;
  --hm-n3:#f4b6b5; --hm-n2:#f8cfce; --hm-n1:#fbe4e3; --hm-0:#f0efec;
  --hm-p1:#ddecfb; --hm-p2:#bcd6f7; --hm-p3:#9ec5f4; --hm-p4:#6da7ec;
  --serif:Charter,"Iowan Old Style","Source Serif 4",Georgia,"Times New Roman",serif;
  --sans:system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0d0d0d; --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axisc:#383835; --border:rgba(255,255,255,.12);
    --accent:#e8a33d; --accent-soft:rgba(232,163,61,.12);
    --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; --s6:#008300; --s7:#9085e9;
    --pos:#3987e5; --neg:#e66767; --good:#0ca30c; --bad:#e66767;
    --hm-n3:#7e2a29; --hm-n2:#5d2423; --hm-n1:#402020; --hm-0:#262624;
    --hm-p1:#1a2c45; --hm-p2:#17395f; --hm-p3:#1c4d8c; --hm-p4:#2a6cc0;
    color-scheme:dark;
  }
}
:root[data-theme="dark"]{
  --bg:#0d0d0d; --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axisc:#383835; --border:rgba(255,255,255,.12);
  --accent:#e8a33d; --accent-soft:rgba(232,163,61,.12);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; --s6:#008300; --s7:#9085e9;
  --pos:#3987e5; --neg:#e66767; --good:#0ca30c; --bad:#e66767;
  --hm-n3:#7e2a29; --hm-n2:#5d2423; --hm-n1:#402020; --hm-0:#262624;
  --hm-p1:#1a2c45; --hm-p2:#17395f; --hm-p3:#1c4d8c; --hm-p4:#2a6cc0;
  color-scheme:dark;
}
*{box-sizing:border-box}
html{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16.5px/1.55 var(--serif);
  -webkit-text-size-adjust:100%}
.wrap{max-width:1072px;margin-inline:auto;
  padding-left:max(16px,env(safe-area-inset-left,0px));
  padding-right:max(16px,env(safe-area-inset-right,0px));
  padding-block:0 56px}
h1,h2,h3,h4{font-family:var(--sans);line-height:1.15;text-wrap:balance;margin:0}
p{margin:.55em 0;max-width:72ch}
a{color:var(--accent)}
b,strong{font-weight:700}
.num,td,th{font-variant-numeric:tabular-nums}

/* hero */
.hero{padding-block:44px 8px}
.eyebrow{font:600 12px/1 var(--sans);letter-spacing:.14em;text-transform:uppercase;color:var(--accent)}
.hero h1{font-size:clamp(30px,5.4vw,46px);font-weight:800;letter-spacing:-.02em;margin:.25em 0 .2em}
.hero .sub{color:var(--ink2);font-size:17px;max-width:76ch}
.verdict{margin-top:20px;border:1px solid var(--border);border-left:4px solid var(--accent);
  background:var(--surface);border-radius:10px;padding:16px 18px}
.verdict .vhead{font:700 13px/1 var(--sans);letter-spacing:.1em;text-transform:uppercase;color:var(--accent)}
.verdict p{font-family:var(--sans);font-size:17.5px;font-weight:600;margin:.4em 0 .5em;max-width:none}
.badges{display:flex;flex-wrap:wrap;gap:8px;font-family:var(--sans);font-size:13px}
.badge{border:1px solid var(--border);border-radius:999px;padding:4px 11px;color:var(--ink2);background:var(--bg)}
.badge b{color:var(--ink)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin-top:14px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.tile .v{font:700 30px/1.1 var(--sans);letter-spacing:-.01em}
.tile .k{font:600 12px/1.3 var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--ink2);margin-top:6px}
.tile .d{font:400 13px/1.45 var(--sans);color:var(--muted);margin-top:6px}

/* sections */
section{margin-top:44px}
.sec-eyebrow{font:700 12px/1 var(--sans);letter-spacing:.14em;color:var(--accent);text-transform:uppercase}
section>h2{font-size:clamp(21px,3.2vw,27px);font-weight:750;letter-spacing:-.015em;margin:.3em 0 .35em}
.lede{color:var(--ink2)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;margin-top:14px}
.card .cap{font:400 13px/1.5 var(--sans);color:var(--muted);margin:10px 4px 2px;max-width:none}
figure{margin:0}
svg{display:block;width:100%;height:auto}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.scroll .wide-svg{min-width:720px}

/* svg type */
svg text{font-family:var(--sans)}
.ax{font-size:12px;fill:var(--muted)}
.ax-s{font-size:10.5px}
.lbl{font-size:12.5px;fill:var(--ink2)}
.val{font-size:12.5px;font-weight:600;fill:var(--ink2)}
.colh{font-size:13px;font-weight:700;fill:var(--ink)}
.slbl{font-size:10.8px;fill:var(--ink2)}
.slbl-em{font-size:11.5px;font-weight:700;fill:var(--ink)}
.lbl-em{font-size:12.5px;font-weight:700;fill:var(--ink)}
.anno{font-size:12.5px;font-weight:700;fill:var(--s1)}
.accent{fill:var(--accent)}
.grid{stroke:var(--grid);stroke-width:1}
.axisln{stroke:var(--axisc);stroke-width:1.2}
.halo{paint-order:stroke;stroke:var(--surface);stroke-width:4px;stroke-linejoin:round}

/* tables */
table{border-collapse:collapse;width:100%;font-family:var(--sans);font-size:13.8px}
th,td{padding:7.5px 10px;text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
thead th{font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);
  border-bottom:1.5px solid var(--axisc);cursor:default}
tbody tr{border-bottom:1px solid var(--grid)}
tbody tr:last-child{border-bottom:none}
.dim2{color:var(--muted);font-weight:400}
table.plain thead th{cursor:default}

/* legends, panels, details, footer */
.legend{list-style:none;display:flex;flex-wrap:wrap;gap:6px 16px;margin:10px 0 0;padding:0;font:13px var(--sans)}
.legend li{display:flex;align-items:center;gap:7px;color:var(--ink2)}
.chip{width:14px;height:14px;border-radius:4px;flex:none}
.dot{width:12px;height:12px;border-radius:50%;flex:none}
.dot.hollow{background:var(--surface);border:2px solid var(--muted)}
.lkey{width:18px;height:0;border-top:2px solid var(--accent);flex:none}
.lkey.dash{border-top:2px dashed var(--ink)}
.cols2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;margin-top:14px}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.panel h3{font-size:15.5px;margin-bottom:6px}
.panel p,.panel li{font-size:14.5px}
.kv{display:flex;flex-wrap:wrap;gap:6px 14px;font:13px var(--sans);color:var(--ink2);margin-top:8px}
.kv b{color:var(--ink)}
ol.lims,ul.lims{padding-left:20px;margin:8px 0}
.lims li{margin:8px 0;font-size:15.5px;max-width:78ch}
details{margin-top:12px}
summary{cursor:pointer;font:600 14px var(--sans);color:var(--accent);padding:4px 0}
footer{margin-top:52px;border-top:1px solid var(--grid);padding-top:14px;
  font:12.5px/1.6 var(--sans);color:var(--muted)}
footer code{font-family:var(--mono)}
#tip{position:fixed;z-index:50;max-width:320px;background:var(--ink);color:var(--bg);
  font:12.5px/1.45 var(--sans);padding:7px 10px;border-radius:7px;pointer-events:none;
  opacity:0;transform:translateY(3px);transition:opacity .12s;white-space:normal}
#tip.on{opacity:.97}
[data-tip]{cursor:default}
@media (prefers-reduced-motion:reduce){*{transition:none !important}}

/* ---- this page ---- */
code{font-family:var(--mono);font-size:.86em;background:var(--bg);border:1px solid var(--border);
  border-radius:4px;padding:0 4px;overflow-wrap:anywhere}
.hero .date{font:600 13px/1.4 var(--sans);color:var(--muted);margin-top:2px}
.verdict .body{font:15px/1.6 var(--serif);font-weight:400;color:var(--ink2);margin:.6em 0;max-width:none}
.fineprint{font:13px/1.55 var(--sans);color:var(--muted);margin-top:12px;max-width:none}
.tile .v small{font-size:16px;font-weight:600;color:var(--muted)}
h3.sub3{font-size:17px;margin-top:26px}
.genres{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:12px;margin-top:14px}
.gpanel{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;min-width:0}
.gpanel.loud{border-top:4px solid var(--neg)}
.gpanel.quiet{border-top:4px solid var(--s3)}
.gpanel .gk{font:700 12px/1 var(--sans);letter-spacing:.12em;text-transform:uppercase;color:var(--ink2)}
.gpanel p{font-size:15px;max-width:none}
.figs{list-style:none;margin:10px 0 2px;padding:0;display:flex;flex-wrap:wrap;gap:6px}
.figs li{font:13px/1.35 var(--sans);background:var(--bg);border:1px solid var(--border);border-radius:8px;
  padding:5px 9px;color:var(--ink2)}
.figs li b{color:var(--ink)}
.g{display:inline-flex;align-items:center;gap:5px;font:700 11.5px/1 var(--sans);color:var(--ink);
  border:1px solid var(--border);border-radius:999px;padding:4px 8px 4px 6px;background:var(--surface);
  white-space:nowrap;text-decoration:none;vertical-align:middle}
.g i{width:9px;height:9px;border-radius:50%;flex:none}
.gA i{background:var(--s3)} .gB i{background:var(--s4)} .gC i{background:var(--neg)}
a.g{min-height:24px;min-width:34px;justify-content:center}
a.g:hover,a.g:focus-visible{border-color:var(--accent);outline:none}
.srcs-c{display:flex;flex-wrap:wrap;gap:4px}
.st{display:inline-flex;align-items:center;gap:6px;font:700 11px/1 var(--sans);letter-spacing:.06em;
  text-transform:uppercase;border-radius:999px;padding:5px 10px 5px 8px;color:var(--ink);white-space:nowrap}
.st i{width:8px;height:8px;border-radius:50%;flex:none}
.st.met{background:color-mix(in srgb,var(--s3) 18%,var(--surface))} .st.met i{background:var(--s3)}
.st.partial{background:var(--accent-soft)} .st.partial i{background:var(--s4)}
.st.not{background:var(--hm-n1)} .st.not i{background:var(--neg)}
.st.na{background:var(--bg);border:1px solid var(--border)} .st.na i{background:var(--muted)}
.sdv{margin-top:6px}
.tblwrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table.rt{font-size:13.5px}
table.rt th,table.rt td{white-space:normal;text-align:left;vertical-align:top;line-height:1.45}
table.rt td.first{font-weight:650;color:var(--ink);min-width:140px}
table.rt td{color:var(--ink2);min-width:120px}
table.rt td b{color:var(--ink)}
table.rt tr.tot td,table.plain tr.tot td{font-weight:700;color:var(--ink);border-top:1.5px solid var(--axisc)}
table.rt td.numc{text-align:right;white-space:nowrap;color:var(--ink);font-weight:600}
table.costs td:first-child{min-width:220px}
table.cov td:first-child,table.cov th:first-child{white-space:normal;min-width:180px}
table.tvt{font-size:13px}
table.tvt td{min-width:0}
table.tvt td:first-child{white-space:nowrap;color:var(--ink);font-weight:600}
.tv summary{font-size:13px}
.ladder{margin-top:16px;display:grid;gap:12px}
.rung{display:grid;grid-template-columns:52px minmax(0,1fr);gap:0 12px}
.rung .rail{position:relative;display:flex;justify-content:center}
.rung .rail::before{content:"";position:absolute;top:-12px;bottom:-12px;left:50%;width:3px;margin-left:-1.5px;
  background:var(--axisc)}
.rung:first-child .rail::before{top:18px}
.rung:last-child .rail::before{bottom:calc(100% - 18px)}
.rung .rnum{position:relative;z-index:1;margin-top:10px;width:38px;height:38px;border-radius:50%;
  background:var(--surface);border:2px solid var(--axisc);font:800 16px/34px var(--sans);text-align:center;
  color:var(--ink2)}
.rung .rbody{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px;min-width:0}
.rung.here .rnum{border-color:var(--accent);color:var(--accent)}
.rung.here .rbody{border-color:var(--accent);box-shadow:inset 4px 0 0 var(--accent)}
.rung.single .rnum{border-color:var(--s1);color:var(--s1)}
.rung.single .rbody{box-shadow:inset 4px 0 0 var(--s1)}
.rung.next .rbody{border-style:dashed}
.rung .rh{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;justify-content:space-between}
.rung h3{font-size:16px}
.mk{font:700 12px/1 var(--sans);border-radius:999px;padding:6px 11px;white-space:nowrap}
.mk.ens{background:var(--accent-soft);color:var(--accent)}
.mk.single{background:var(--hm-p1);color:var(--s1)}
.mk.nr{background:var(--hm-n1);color:var(--bad)}
.crit{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,190px),1fr));gap:8px 16px;margin-top:10px;
  font-family:var(--sans)}
.k{font:600 10.5px/1.25 var(--sans);letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}
.crit .v{font-size:13.5px;line-height:1.4;color:var(--ink);margin-top:2px}
.sd{margin-top:10px;padding-top:9px;border-top:1px solid var(--grid);font:14px/1.5 var(--sans);color:var(--ink2)}
.sd .k{margin-right:6px}
.sd b{color:var(--ink)}
ul.why{margin:4px 0 0;padding-left:18px}
ul.why li{margin:3px 0}
.stages{display:grid;gap:14px;margin-top:14px}
.stage{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;min-width:0}
.stage .sh{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;justify-content:space-between}
.stage .sk{font:700 11.5px/1 var(--sans);letter-spacing:.12em;text-transform:uppercase;color:var(--accent)}
.stage h3{font-size:18px;margin-top:4px}
.stage>p{font-size:15px;color:var(--ink2);max-width:none}
.stage .st{font-size:11.5px}
table.crit-t td:nth-child(3){min-width:170px}
.plainw ul{padding-left:20px}
.plainw li{margin:8px 0;font-size:15.5px;max-width:78ch}
.quotes{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:12px;margin-top:12px}
table code{white-space:nowrap;overflow-wrap:normal}
.stage .cap{font:400 13px/1.5 var(--sans);color:var(--muted);margin:10px 4px 2px;max-width:none}
.quotes .panel p{font-family:var(--sans);font-size:13px;color:var(--muted);margin:.4em 0 0}
blockquote{margin:6px 0;padding:2px 0 2px 12px;border-left:3px solid var(--grid);font-style:italic;
  color:var(--ink2);overflow-wrap:anywhere}
.srcd{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:8px 14px;margin-top:10px}
.srcd>summary{font-size:14.5px}
.srcp{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--ink2);margin:16px 0 4px}
ul.srcl{list-style:none;margin:0;padding:0}
.src{padding:10px 0;border-top:1px solid var(--grid)}
.srch{display:flex;gap:8px;align-items:flex-start;font-family:var(--sans);font-size:14.5px}
.srch b{line-height:1.35;overflow-wrap:anywhere}
.srcm{font:12.5px/1.5 var(--sans);color:var(--muted);margin:4px 0 2px;overflow-wrap:anywhere}
.vm{display:inline-block;border-radius:999px;padding:1px 8px;font-weight:600;border:1px solid var(--border)}
.vm.vv{color:var(--ink2)} .vm.vp{color:var(--accent)} .vm.vu{color:var(--bad)}
.noq{font:italic 13px var(--sans);color:var(--muted);margin:4px 0}
.srcu{font:12px/1.4 var(--mono);overflow-wrap:anywhere;word-break:break-all}
.figwrap{margin-inline:auto}
.scroll .w-a{min-width:640px} .scroll .w-b{min-width:760px} .scroll .w-c{min-width:760px}
.scroll .w-d{min-width:600px} .scroll .w-e{min-width:640px}
.vn{display:none}
@media (max-width:640px){
  .vw{display:none}
  .vn{display:block;max-width:440px;margin-inline:auto}
  table.rt thead{display:none}
  table.rt,table.rt tbody,table.rt tr,table.rt td{display:block;width:100%}
  table.rt tr{padding:10px 0}
  table.rt td{padding:3px 2px;min-width:0}
  table.rt td::before{content:attr(data-label);display:block;font:600 10.5px/1.3 var(--sans);letter-spacing:.07em;
    text-transform:uppercase;color:var(--muted);margin-bottom:2px}
  table.rt td.numc{text-align:left}
  table.costs td:first-child,table.crit-t td:nth-child(3){min-width:0}
  .rung{grid-template-columns:40px minmax(0,1fr);gap:0 8px}
  .rung .rnum{width:32px;height:32px;font-size:14px;line-height:28px}
}
@media (max-width:480px){
  .hero{padding-top:30px}
  th,td{padding:6px 7px}
  .tile .v{font-size:25px}
}
"""

JS = """
(function(){
  // shared tooltip (the pilot report's) ----------------------------------------
  var tip=document.getElementById('tip');
  function show(e,t){tip.textContent=t;tip.classList.add('on');move(e);}
  function move(e){
    var x=e.clientX+14,y=e.clientY+14,r=tip.getBoundingClientRect();
    if(x+r.width>window.innerWidth-8)x=e.clientX-r.width-10;
    if(y+r.height>window.innerHeight-8)y=e.clientY-r.height-10;
    tip.style.left=x+'px';tip.style.top=y+'px';}
  function hide(){tip.classList.remove('on');}
  document.addEventListener('pointerover',function(e){
    var el=e.target.closest('[data-tip]');if(el)show(e,el.getAttribute('data-tip'));});
  document.addEventListener('pointermove',function(e){
    if(tip.classList.contains('on'))move(e);
    if(!e.target.closest('[data-tip]'))hide();});
  document.addEventListener('pointerdown',function(e){
    var el=e.target.closest('[data-tip]');
    if(el){show(e,el.getAttribute('data-tip'));setTimeout(hide,2600);}});
})();
"""


def pilot_tokens_match() -> bool:
    """The :root token block must equal the pilot's (design system reuse, verbatim)."""
    if not PILOT_HTML.exists():
        return True
    pilot = re.search(r":root\{.*?\n\}", PILOT_HTML.read_text(), re.S)
    mine = re.search(r":root\{.*?\n\}", CSS, re.S)
    return bool(pilot and mine and pilot.group(0) == mine.group(0))


# ==================================================================== assembly


def card(inner: str, cap: str = "", cls: str = "") -> str:
    return f'<div class="card {cls}">{inner}' + (f'<p class="cap">{cap}</p>' if cap else "") + "</div>"


def svg_card(wide: str, narrow: str, wcls: str, maxw: int, legend: str = "", cap: str = "", table: str = "") -> str:
    """A chart card: the wide SVG (scrolls inside the card if the screen is narrower than its minimum) and a
    phone layout of the same data, swapped by a media query; caption and table view below."""
    return card(f'{legend}<div class="vw scroll"><div class="figwrap {wcls}" style="max-width:{maxw}px">{wide}</div>'
                f'</div><div class="vn">{narrow}</div>'
                f'{"<p class=cap>" + cap + "</p>" if cap else ""}{table}')


def build_html() -> str:
    gc = grade_counts(ALL)
    vids = reach_data()
    hype = [v for v in vids if v["kind"] == "hype"]
    deb = [v for v in vids if v["kind"] == "debunk"]
    lv = cost_levels()
    n_dot_entries = len({(d["e"]["_stream"], d["e"]["_n"]) for d in DOTS})
    n_below = sum(1 for d in DOTS if d["v"] < 50)

    # ---------------------------------------------------------------- hero
    tiles = (
        f'<div class="tile"><div class="v">+{P["ic3"]}</div><div class="k">rank IC per date, nested LightGBM</div>'
        f'<div class="d">Newey-West t {P["ic_t"]:.1f}; positive in {P["ic_pos"]} of {P["ic_n"]} months. '
        f'MSCI’s “good” line is {fnum(X["msci_good"], 2)}.</div></div>'
        f'<div class="tile"><div class="v">{P["hit"]:.1f}%</div><div class="k">hit rate implied by that IC</div>'
        f'<div class="d">Sheppard: ½ + arcsin(IC)/π. Mercer: {fnum(X["mercer"])}%; students with tomorrow’s '
        f'paper: {fnum(X["news_hit"])}%.</div></div>'
        f'<div class="tile"><div class="v">+{P["ens"]:.1f}% <small>a year</small></div>'
        f'<div class="k">rank ensemble top decile vs equal weight</div><div class="d">Net of {P["cost_bps"]:.0f} bps '
        f'per side; IR {P["ir"]:.2f} [{P["ir_lo"]:.2f}, {P["ir_hi"]:.2f}], {P["ens_months"]:.0f} of '
        f'{P["ens_months_n"]:.0f} months. Single models {sgn(P["single_hi"])}% to {sgn(P["single_lo"])}%.'
        f'</div></div>'
        f'<div class="tile"><div class="v">{P["dsr_ens"]:.3f} <small>DSR</small></div>'
        f'<div class="k">deflated Sharpe at N = {P["N"]:.0f} · {P["live_months"]:.0f} months live</div>'
        f'<div class="d">PSR {P["psr"]:.2f} against zero before deflation; the liquid paper book’s DSR is '
        f'{P["dsr_liq"]:.3f}.</div></div>')
    badges = (f'<span class="badge">Signal: <b>rung {RUNG["ens"]}</b> for the rank ensemble, <b>rung '
              f'{RUNG["single"]}</b> for single models</span>'
              f'<span class="badge">Gates passed: <b>{P["gates_lgbm"]:.0f} of {P["gates_n"]:.0f}</b> LightGBM · '
              f'<b>{P["gates_ens"]:.0f} of {P["gates_n"]:.0f}</b> ensemble</span>'
              f'<span class="badge"><b>{len(ALL)}</b> sourced entries · {gc["A"]} A · {gc["B"]} B · {gc["C"]} C</span>')
    hero = f"""
<header class="hero">
  <div class="eyebrow">SuryaDhana · community calibration · NSE EOD universe</div>
  <h1>How good is good enough?</h1>
  <p class="sub">What the internet reports for ML stock prediction, and where SuryaDhana sits</p>
  <div class="date">{P["date"]} · the program lead’s synthesis of three research streams, with the goal ladder</div>
  <div class="verdict">
    <div class="vhead">Verdict · {P["date"]}</div>
    <p>{esc(VERDICT[0].upper() + VERDICT[1:])}</p>
    <p class="body">{inline(WHERE_SITS)}</p>
    <div class="badges">{badges}</div>
  </div>
  <div class="tiles">{tiles}</div>
  <p class="fineprint">{inline(NOTE_ON_NUMBERS)}</p>
</header>"""

    # -------------------------------------------------------- 1 two genres
    loud_figs = (f'<li><b>{fnum(LOUD_LO)} to {fnum(LOUD_HI)}%</b> “accuracy”, all price-level fits</li>'
                 + "".join(f'<li><b>{v["views"]:,}</b> views · {esc(v["e"]["author_or_channel"])}</li>' for v in hype)
                 + "".join(f'<li>best debunk: <b>{v["views"]:,}</b> views · {esc(v["e"]["author_or_channel"])}</li>'
                           for v in deb))
    quiet_figs = (f'<li>Mercer: right <b>{fnum(X["mercer"])}%</b> of the time</li>'
                  f'<li>Man AHL: “{esc(e_manahl["quote"].rstrip("."))}”</li>'
                  f'<li>students with tomorrow’s paper: <b>{fnum(X["news_hit"])}%</b></li>'
                  f'<li>Nifty next-day: <b>{fnum(X["nifty_lo"])} to {fnum(X["nifty_hi"])}%</b> test vs '
                  f'<b>{fnum(X["nifty_train"])}%</b> train</li>'
                  f'<li>IC <b>{fnum(X["ql_real"][0], 2)} to {fnum(X["ql_real"][1], 2)}</b> real · above '
                  f'<b>{fnum(X["ql_susp"], 2)}</b> suspicious</li>'
                  f'<li>Numerai live: <b>{fnum(X["num_live"][0], 3)} to {fnum(X["num_live"][-1], 3)}</b></li>')
    ratio = hype[0]["views"] / deb[0]["views"]
    reach_cap = (f'Views as read from each watch page on {X["views_date"]} ({len(vids)} videos with an exact count in '
                 f'{YT}.json; the others are “unknown”). Bars are coloured by the entry’s credibility grade. Our '
                 f'arithmetic: the most-viewed tutorial has {ratio:.1f} times the views of the debunk.')
    reach_legend = ('<ul class="legend">'
                    f'<li><span class="chip" style="background:var(--neg)"></span>price-level tutorial, grade C</li>'
                    f'<li><span class="chip" style="background:var(--s4)"></span>debunk, grade B</li></ul>')
    reach_tbl = details_table("Table view: reach", ["Views", "Channel", "Video", "Grade", "Task"],
                              [[f'{v["views"]:,}', esc(v["e"]["author_or_channel"]), link(v["e"]),
                                gtag(v["e"]["credibility"]), esc(v["e"]["task"])] for v in vids])
    claims_legend = ('<ul class="legend">'
                     '<li><span class="dot" style="background:var(--s3)"></span>grade A</li>'
                     '<li><span class="dot" style="background:var(--s4)"></span>grade B</li>'
                     '<li><span class="dot" style="background:var(--neg)"></span>grade C</li>'
                     '<li><span class="dot hollow"></span>hollow: price level, not prediction</li>'
                     f'<li><span class="lkey"></span>SuryaDhana {P["hit"]:.1f}%</li></ul>')
    claims_cap = (f'{len(DOTS)} numbers from {n_dot_entries} entries are plotted ({n_below} below 50% sit in the left '
                  f'gutter). Eligible entries are those whose task is “direction” or “price level”, or whose metric '
                  f'names accuracy, hit rate or win rate: {len(CANDIDATES)} of {len(ALL)}. Their claimed values were '
                  f'parsed with a tolerant regex; <b>{len(SKIPPED)} eligible entries were skipped</b> because no '
                  f'accuracy number could be parsed (most say “no number captured”). R² values are drawn × 100. '
                  f'Percentages that are question premises, counts or money outcomes are not accuracy claims and are '
                  f'left out. Grade is the row (the column on a phone); colour repeats it.')
    rows_b = []
    for d in sorted(DOTS, key=lambda d: (d["lane"] != "direction", -d["v"], d["e"]["_stream"], d["e"]["_n"])):
        e = d["e"]
        rows_b.append([fmt_claim(d), "price level" if d["lane"] == "price" else "direction", gtag(d["grade"]),
                       esc(e["platform"]), link(e), esc(d["clause"])])
    claims_tbl = details_table(f"Table view: the {len(DOTS)} plotted numbers", ["Value", "Kind", "Grade", "Platform",
                                                                                   "Entry", "Parsed from"], rows_b)
    skip_tbl = details_table(f"The {len(SKIPPED)} skipped entries", ["Grade", "Platform", "Entry", "Claimed value"],
                             [[gtag(e["credibility"]), esc(e["platform"]), link(e), esc(e["_claim"])]
                              for e in SKIPPED])
    quiet_cap = "Grades are the evidence files’ grades for the entry each statement comes from."
    for e in _quiet_c:
        quiet_cap += (f" The last row also cites {link(e)}, graded {e['credibility']} for its post, not the comment: "
                      f"“{esc(e['credibility_reason'])}”")
    sec1 = f"""
<section id="genres">
  <div class="sec-eyebrow">01 · Two genres</div>
  <h2>{esc(plain(GENRE_LEAD).rstrip("."))}</h2>
  <div class="genres">
    <div class="gpanel loud"><div class="gk">The loud genre</div><p>{inline(LOUD)}</p><ul class="figs">{loud_figs}</ul></div>
    <div class="gpanel quiet"><div class="gk">The quiet genre</div><p>{inline(QUIET)}</p><ul class="figs">{quiet_figs}</ul></div>
  </div>
  <h3 class="sub3">Reach: the hype is watched far more than its correction</h3>
  {svg_card(chart_reach(), chart_reach(True), "w-a", 1000, reach_legend, reach_cap, reach_tbl)}
  <h3 class="sub3">Every accuracy claim in the evidence files, by credibility</h3>
  {svg_card(chart_claims(), chart_claims_narrow(), "w-b", 1000, claims_legend, claims_cap, claims_tbl + skip_tbl)}
  <h3 class="sub3">{esc(unnumber(_s21["title"]))}</h3>
  {card(md_table(LOUD_TBL, src=SRC_LOUD), "Sources: grade chips link to the entries in the evidence files.")}
  <p>{inline(WHY_WRONG)}</p>
  <h3 class="sub3">{esc(unnumber(QUIET_TITLE))}</h3>
  {card(md_table(QUIET_TBL, src=SRC_QUIET), quiet_cap)}
  <p>{inline(CONSENSUS)}</p>
</section>"""

    # ---------------------------------------------------------- 2 what good is
    ic_legend = ('<ul class="legend"><li><span class="dot" style="background:var(--s3)"></span>grade A</li>'
                 '<li><span class="dot" style="background:var(--s4)"></span>grade B</li>'
                 '<li><span class="dot" style="background:var(--neg)"></span>grade C</li>'
                 f'<li><span class="lkey"></span>SuryaDhana {P["ic3"]}</li></ul>')
    ic_cap = (f'Every benchmark value is read from the evidence files: Numerai live band from {RD}.json '
              f'#{e_numsig["_n"]} (Signals models, about {X["num_rounds"]:.0f} rounds); G-Research and Ubiquant winners, '
              f'Qlib, MSCI, M6 '
              f'and QuanterLab from {CP}.json and {YT}.json. Numerai’s targets are neutralised and Ubiquant’s is '
              f'obfuscated, so their levels are not like-for-like with a raw 20-session label. SuryaDhana’s rank IC '
              f'({P["ic"]:.4f}) is read from <code>scale5y_summary.json</code>.')
    ic_rows = [["Numerai live models (Signals)", f'{fnum(X["num_live"][0], 4)} to {fnum(X["num_live"][-1], 4)}',
                gtag(e_numsig["credibility"]), link(e_numsig)],
               ["G-Research crypto winner, live", fnum(X["gres"], 4), gtag(e_gres["credibility"]), link(e_gres)],
               ["Ubiquant winner", fnum(X["ubi"], 6), gtag(e_ubi["credibility"]), link(e_ubi)],
               ["Qlib LightGBM IC · rank IC", f'{fnum(X["qlib_ic"], 4)} · {fnum(X["qlib_ric"], 4)}',
                gtag(e_qlib["credibility"]), link(e_qlib)],
               ["MSCI “good” · “very good”", f'{fnum(X["msci_good"], 2)} · {fnum(X["msci_vgood"], 2)}',
                gtag(e_msci["credibility"]), link(e_msci)],
               ["M6 moderate · good · exceptional",
                f'{fnum(X["m6_mod"], 2)} · {fnum(X["m6_good"], 2)} · {fnum(X["m6_exc"], 2)}',
                gtag(e_m6t["credibility"]), link(e_m6t)],
               ["QuanterLab real · strong · suspicious",
                f'{fnum(X["ql_real"][0], 2)}–{fnum(X["ql_real"][1], 2)} · {fnum(X["ql_strong"][0], 2)}–'
                f'{fnum(X["ql_strong"][1], 2)} · above {fnum(X["ql_susp"], 2)}', gtag(e_qlab["credibility"]),
                link(e_qlab)],
               ["SuryaDhana, nested LightGBM", f'{P["ic"]:.4f} (t {P["ic_t"]:.2f})', "—",
                "<code>ml/results/scale5y/scale5y_summary.json</code>"]]
    ic_tbl = details_table("Table view: IC benchmarks", ["Benchmark", "IC", "Grade", "Source"], ic_rows)
    shep_cap = (f'Curve: Sheppard’s formula for jointly normal forecast and return, the ladder’s own conversion. Each '
                f'hit rate is placed at the IC it implies; Mercer’s {fnum(X["mercer"])}% is a per-trade hit rate and the '
                f'newspaper figure a one-day call, so their position shows the IC each would correspond to, not a '
                f'measured IC. A {fnum(X["nifty_hi"])}% next-day hit rate already implies IC '
                f'{ic_for(X["nifty_hi"]):.3f}, at QuanterLab’s “suspicious” line.')
    shep_rows = [[f'{fnum(h)}%', f'{ic_for(h):.4f}', esc(lbl)] for h, lbl in (
        (X["mercer"], "Mercer (Renaissance), per trade"), (X["news_hit"], "students with tomorrow’s paper"),
        (P["hit"], "SuryaDhana, implied by rank IC"), (X["nifty_lo"], "Nifty next-day test, low"),
        (X["nifty_hi"], "Nifty next-day test, high"), (LOUD_LO, f"a {fnum(LOUD_LO)}% “accuracy” claim"))]
    shep_tbl = details_table("Table view: hit rate and implied IC", ["Hit rate", "Implied IC", "Anchor"], shep_rows)
    sec2 = f"""
<section id="good">
  <div class="sec-eyebrow">02 · What good is</div>
  <h2>{esc(plain(para(_s1, "What the honest benchmarks")).rstrip("."))}</h2>
  {card(md_table(BENCH, src=SRC_BENCH), "From COMMUNITY_CALIBRATION.md §1; each number is checked against the evidence file it comes from. Grade chips link to those entries.")}
  <h3 class="sub3">Information coefficients: where the honest benchmarks sit</h3>
  {svg_card(chart_ic(), chart_ic_narrow(), "w-c", 1000, ic_legend, ic_cap, ic_tbl)}
  <h3 class="sub3">Why a good model is right only about {P["hit"]:.0f}% of the time</h3>
  {svg_card(chart_sheppard(), chart_sheppard(True), "w-d", 820, "", shep_cap, shep_tbl)}
</section>"""

    # ------------------------------------------------------------- 3 ladder
    cost_legend = ('<ul class="legend"><li><span class="chip" style="background:var(--neg)"></span>costs</li>'
                   '<li><span class="chip" style="background:var(--pos)"></span>net excess over equal weight</li>'
                   '<li><span class="lkey dash"></span>Carver’s one-third limit</li></ul>')
    cost_cap = (f'From the metric table’s cost-drag row: net +{P["ens"]:.1f}% plus costs {P["costs"]:.1f}% gives a '
                f'gross active return of {P["gross"]:.1f}% a year at {P["cost_bps"]:.0f} bps per side and '
                f'{P["turnover"]:.0f}% turnover per {P["window"]:.0f} sessions. The {P["bps_lo"]:.0f} and '
                f'{P["bps_hi"]:.0f} bps nets (+{P["net_lo"]:.1f}%, +{P["net_hi"]:.1f}%) are the same row’s; their cost '
                f'bars are gross minus net. '
                f'Carver’s rule: “{esc(e_carver["quote"].capitalize())}”')
    cost_tbl = details_table("Table view: cost sensitivity", ["Cost per side", "Net excess", "Costs", "Gross",
                                                              "Costs / gross"],
                             [[f'{d["bps"]:.0f} bps', f'+{d["net"]:.1f}%', f'{d["costs"]:.1f}%', f'{P["gross"]:.1f}%',
                               f'{100 * d["share"]:.0f}%'] for d in lv])
    sec3 = f"""
<section id="ladder">
  <div class="sec-eyebrow">03 · The ladder</div>
  <h2>{esc(_s3["title"].split(". ", 1)[1])}</h2>
  <p class="lede">{inline(LADDER_INTRO)}</p>
  {ladder_html()}
  <p class="fineprint">Implied hit rates are computed from each rung’s IC bounds with ½ + arcsin(IC)/π.</p>
  <h3 class="sub3">Metric by metric</h3>
  {card(md_table(METRIC_TBL))}
  <h3 class="sub3">Cost drag: exactly at Carver’s one-third limit</h3>
  {svg_card(chart_costs(), chart_costs(True), "w-e", 1000, cost_legend, cost_cap, cost_tbl)}
</section>"""

    # -------------------------------------------------------------- 4 goals
    sec4 = f"""
<section id="goals">
  <div class="sec-eyebrow">04 · The goal ladder</div>
  <h2>{esc(GOALS[1]["title"].split(": ", 1)[0])}: {list(NUM_WORDS)[len(STAGES)]} stages, fixed before the next test</h2>
  <p class="lede">{inline(G_INTRO)}</p>
  <h3 class="sub3">Where the program stands</h3>
  {card(md_table(_stand))}
  <p>{inline(G_LADDER_INTRO)}</p>
  {stage_cards()}
  <h3 class="sub3">Position on the external ladder</h3>
  <p>{inline(G_POSITION)}</p>
  <div class="cols2">
    <div class="panel plainw"><h3>What “good enough” means in plain words</h3><ul>{"".join(f"<li>{inline(t)}</li>" for t in G_PLAIN)}</ul></div>
    <div class="panel plainw"><h3>Not goals</h3><ul>{"".join(f"<li>{inline(t)}</li>" for t in G_NOT)}</ul></div>
  </div>
</section>"""

    # ---------------------------------------------------------- 5 failures
    sec5 = f"""
<section id="failures">
  <div class="sec-eyebrow">05 · Failure modes</div>
  <h2>{esc(sec(CAL, "4. ")["title"].split(". ", 1)[1])}</h2>
  {card(failure_table(), "Status chips read the SuryaDhana column: “not applicable”, “found and fixed”, “open” where the text names an open item or weak link, otherwise “in place”.")}
</section>"""

    # -------------------------------------------------------------- 6 India
    quotes = [(e_d65, e_d65["_claim"]), (e_d60, e_d60["_claim"]), (e_spike, e_spike["_notes"]),
              (e_btst, e_btst["_notes"])]
    qhtml = "".join(f'<div class="panel">{gchip(e)} <b style="font-family:var(--sans);font-size:13.5px">'
                    f'{esc(e["platform"])}, {esc(e["date"][:4])}</b><blockquote>{esc(e["quote"])}</blockquote>'
                    f'<p>{esc(t)}</p></div>' for e, t in quotes)
    india_items = "".join(f"<li>{inline(t)}</li>" for t in INDIA)
    sec6 = f"""
<section id="india">
  <div class="sec-eyebrow">06 · India</div>
  <h2>{esc(sec(CAL, "5. ")["title"].split(". ", 1)[1])}</h2>
  <ul class="lims">{india_items}</ul>
  <h3 class="sub3">Delivery percentage: the folklore, in its own words</h3>
  <div class="quotes">{qhtml}</div>
  <h3 class="sub3">Statutory costs on a delivery trade</h3>
  {card(cost_table(), f"Rates as captured from {link(e_zc)} ({YT}.json #{e_zc['_n']}, grade {e_zc['credibility']}); bps computed here: STT {COST['stt']:.0f} + NSE {COST['nse']:.3f} + SEBI {COST['sebi']:.2f} + GST {COST['gst_rate'] * 100:.0f}% of (brokerage + SEBI + NSE) = {COST['side']:.2f} bps each side, plus {COST['stamp']:.1f} bps stamp duty on buys. Spread and impact are not included.")}
</section>"""

    # ---------------------------------------------------------- 7 coverage
    sec7 = f"""
<section id="coverage">
  <div class="sec-eyebrow">07 · Coverage and limits</div>
  <h2>{esc(sec(CAL, "6. ")["title"].split(". ", 1)[1])}</h2>
  <ul class="lims">{"".join(f"<li>{inline(t)}</li>" for t in COVER)}</ul>
  {card(coverage_table(), "Counted from the three evidence files. “Snippet only” counts entries whose verification mark (the <code>verification</code> field, or the method notes or grade reason) starts “unverified (snippet only)”.")}
</section>"""

    # ----------------------------------------------------------- 8 changes
    sec8 = f"""
<section id="changes">
  <div class="sec-eyebrow">08 · What changes</div>
  <h2>{esc(sec(CAL, "7. ")["title"].split(". ", 1)[1])}</h2>
  <ol class="lims">{"".join(f"<li>{inline(t)}</li>" for t in CHANGES)}</ol>
</section>"""

    # ----------------------------------------------------------- 9 sources
    sec9 = f"""
<section id="sources">
  <div class="sec-eyebrow">09 · Sources</div>
  <h2>All {len(ALL)} entries, by stream and platform</h2>
  <p class="lede">{inline(blocks(sec(CAL, "8. "), "p")[0])}</p>
  {sources_html()}
</section>"""

    foot = f"""
<footer>
  <p>Generated by <code>ml/make_community_report.py</code> from <code>ml/research/community/COMMUNITY_CALIBRATION.md</code>,
  <code>ml/GOALS.md</code>, the three evidence files (<code>{RD}.json</code>, <code>{YT}.json</code>, <code>{CP}.json</code>)
  and, for SuryaDhana’s rank IC, <code>ml/results/scale5y/scale5y_summary.json</code>. Narrative and verdicts are the
  Markdown’s; external numbers are read from the evidence files, and where a Markdown copy disagreed the page shows
  the file’s value. Every URL comes from the evidence files. Quotes are the text the fetch tool extracted; spot-check
  them against the live page before quoting externally. Inline SVG, no external resources.</p>
</footer>"""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>How good is good enough?</title>
<meta name="description" content="What the internet reports for ML stock prediction, how good is good enough, and where SuryaDhana sits.">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
{hero}
{sec1}
{sec2}
{sec3}
{sec4}
{sec5}
{sec6}
{sec7}
{sec8}
{sec9}
{foot}
</div>
<div id="tip" role="status" aria-live="polite"></div>
<script>{JS}</script>
</body>
</html>
"""


def main() -> None:
    html = build_html()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    print(f"wrote {OUT.relative_to(ROOT.parent)} ({len(html):,} bytes)")
    if not pilot_tokens_match():
        print("WARNING: :root tokens differ from ml/report/index.html")
    print(f"chart B: {len(DOTS)} numbers from {len({(d['e']['_stream'], d['e']['_n']) for d in DOTS})} entries "
          f"plotted; {len(SKIPPED)} of {len(CANDIDATES)} eligible entries skipped")
    print(f"\nMarkdown vs evidence JSON ({len(DISCREPANCIES)}):")
    for d in DISCREPANCIES:
        print("  -", d)
    print(f"\nMarkdown vs scale5y_summary.json ({len(PROGRAM_NOTES)}):")
    for d in PROGRAM_NOTES:
        print("  -", d)


if __name__ == "__main__":
    main()
