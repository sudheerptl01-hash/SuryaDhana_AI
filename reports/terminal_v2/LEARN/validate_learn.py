#!/usr/bin/env python
"""Validate the Terminal v2 LEARN assets (``glossary.json``, ``tooltips.json``) against the rules and the code that ships.

    python reports/terminal_v2/LEARN/validate_learn.py             # check only (exit 1 on any defect)
    python reports/terminal_v2/LEARN/validate_learn.py --write     # rebuild both JSON files from build_assets.py first
    python reports/terminal_v2/LEARN/validate_learn.py --selftest  # negative controls: every synthetic defect must be caught

Checks (each failure is one line; all are reported):
  1. The JSON files are byte-identical to what ``build_assets.py`` renders (the module is the source; never hand-edit).
  2. glossary.json: unique terms; every ``see_also`` resolves and is never the term itself; ``aliases`` are strings, unique
     across the glossary and never another term's name; ``start_here`` and ``required`` name existing terms, no repeats;
     ``long`` is never a copy of ``short``.
  3. Every ``short``, ``long`` and tooltip value is ONE line of at most 200 characters (PLAN 1.6 / B5 brief).
  4. The required entries exist (PLAN 1.6: IV rank vs percentile, constant-maturity IV, the put-call-parity forward, 25Δ skew,
     Parkinson / Yang-Zhang, FOVOLT, SPAN vs exposure margin, points attribution and its residual, hysteresis, delta-equivalent
     OI, MWPL), and "IV rank" and "IV percentile" each name the other as "Not the …" so the two are never confused.
  5. No direction words in any glossary or tooltip text (PLAN §0.1: context is never bullish/bearish; nothing implies a
     trade): bullish, bearish, buy, sell, long/short build-up, short covering, long unwinding, go long/short, overbought,
     oversold, breakout, upside, downside, outperform, rally, "will rise/fall", … and the bare words long/short (the
     exchange's "short-option minimum" is the one allowed phrase); no ``signal`` badge claim; no composite score.
  6. Every non-panel tooltip key is a stored column (a ``name TYPE`` in the v2 DDL) or a quoted payload field in the v2
     packages / routers (read as text, never imported); a tooltip nobody can render is a defect.
  7. Panel tooltips (``page.panel``) use a known page or sub-view prefix and ``panels`` lists exactly the dotted keys.
  8. Code facts the copy quotes still hold in the code (model_version, the 6.5 % rate, the 252-session window, the
     hysteresis ratios, the 25-point MAE flag, FOVOLT's λ, the 3 % ITM band, the 0.5 % parity tolerance, the 4.8× heuristic).
  9. A bundled copy under ``ui/`` (any ``tooltips.json`` / ``glossary.json`` whose ``agent`` is ``B5-DOCS``) equals this one.
Pure stdlib; read-only unless --write.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
GLOSSARY = HERE / "glossary.json"
TOOLTIPS = HERE / "tooltips.json"
MAX_LEN = 200
DS = ROOT / "services" / "data-service"
ROUTERS = ROOT / "services" / "ui-api" / "routers"
CODE_DIRS: tuple[Path, ...] = (DS / "fo_iv", DS / "index_drivers", DS / "data_health")
CODE_FILES: tuple[Path, ...] = (DS / "nse_positions.py", ROUTERS / "derivatives.py", ROUTERS / "markets.py",
                                ROUTERS / "data_health.py", ROUTERS / "options_strategy.py")
UI_ROOT = ROOT / "ui"
UI_SKIP = ("node_modules", ".next", "dist", "out")
PANEL_PAGES: frozenset[str] = frozenset({"omon", "vol", "evts", "des", "memb", "mov", "desk", "ostr", "data", "derv", "brf", "sys"})
_DDL_TYPES = "DOUBLE|VARCHAR|DATE|TIMESTAMP|TIMESTAMPTZ|INTEGER|BIGINT|BOOLEAN|INT|TEXT|SMALLINT|REAL|FLOAT"

# Direction vocabulary (PLAN §0.1). Word-bounded, case-insensitive. ALLOWED_PHRASES are removed before the scan.
DIRECTION_PATTERNS: tuple[str, ...] = (
    r"bullish", r"bearish", r"buy(s|ing)?", r"sell(s|ing)?", r"sold", r"overbought", r"oversold", r"break(out|down)s?",
    r"upside", r"downside", r"up-?trend", r"down-?trend", r"out-?perform\w*", r"under-?perform\w*", r"rall(y|ies)",
    r"long", r"short", r"short[- ]covering", r"long[- ]unwinding", r"(will|should|likely to|expected to)\s+(rise|fall|go up|go down)",
    r"price target", r"support level", r"resistance", r"go (long|short)",
)
ALLOWED_PHRASES: tuple[str, ...] = ("short-option minimum",)
_DIRECTION_RE = re.compile(r"\b(" + "|".join(DIRECTION_PATTERNS) + r")\b", re.IGNORECASE)
_FORBIDDEN_CLAIMS = re.compile(r"(badge\s+`?signal`?\s*(:|=)|\bcomposite score\b(?! ?\.| exists)|\bN of 7\b)", re.IGNORECASE)

# (label, text that must appear in the LEARN copy, code file, regex that must match in it)
CODE_FACTS: tuple[tuple[str, str, Path, str], ...] = (
    ("model_version", "b76-pcp-v1", DS / "fo_iv" / "black76.py", r'MODEL_VERSION\s*=\s*"b76-pcp-v1"'),
    ("rate 6.5 %", "6.5 %", DS / "fo_iv" / "iv_eod.py", r"DEFAULT_R\s*=\s*0\.065\b"),
    ("252-session window", "252 sessions", DS / "fo_iv" / "iv_eod.py", r"RANK_WINDOW\s*=\s*252\b"),
    ("parity tolerance 0.5 %", "0.5 %", DS / "fo_iv" / "iv_eod.py", r"PCP_FUTURE_TOL\s*=\s*0\.005\b"),
    ("ITM band 3 %", "3 % ITM", DS / "fo_iv" / "black76.py", r"ITM_BAND\s*=\s*0\.03\b"),
    ("hysteresis 1.3× / 5", "1.3×", DS / "index_drivers" / "compute.py", r"20:\s*\(1\.3,\s*5\)"),
    ("hysteresis 1.2× / 5", "1.2×", DS / "index_drivers" / "compute.py", r"60:\s*\(1\.2,\s*5\)"),
    ("MAE flag 25 pts", "25 points", DS / "index_drivers" / "reads.py", r"MAE_DEGRADED\s*=\s*25(\.0)?\b"),
    ("FOVOLT λ 0.995", "λ = 0.995", DS / "fo_iv" / "catalog_seed.py", r"λ 0\.995"),
    ("Yang-Zhang k", "0.34 ÷ (1.34", DS / "fo_iv" / "realised.py", r"0\.34\s*/\s*\(1\.34"),
    ("Parkinson 4 ln 2", "4 ln 2", DS / "fo_iv" / "realised.py", r"4\.0\s*\*\s*math\.log\(2\.0\)"),
    ("heuristic 4.8×", "4.8×", ROUTERS / "options_strategy.py", r"HEURISTIC_ERROR_FACTOR\s*=\s*4\.8\b"),
    ("parity forward", "F = K + (C − P)·e^{rT}", DS / "fo_iv" / "black76.py", r"return k \+ \(call_px - put_px\) \* math\.exp\(r \* t\)"),
)


def load_builder(path: Path = HERE / "build_assets.py") -> ModuleType:
    spec = importlib.util.spec_from_file_location("v2_learn_build_assets", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ─────────────────────────────────────────── checks (pure) ───────────────────────────────────────────

def check_lines(where: str, text: str) -> list[str]:
    out: list[str] = []
    if "\n" in text or "\r" in text:
        out.append(f"{where}: not a single line")
    if len(text) > MAX_LEN:
        out.append(f"{where}: {len(text)} chars > {MAX_LEN}")
    return out


def direction_words(text: str) -> list[str]:
    cleaned = text
    for phrase in ALLOWED_PHRASES:
        cleaned = re.sub(re.escape(phrase), " ", cleaned, flags=re.IGNORECASE)
    return sorted({m.group(0).lower() for m in _DIRECTION_RE.finditer(cleaned)})


def check_text_rules(where: str, text: str) -> list[str]:
    out = check_lines(where, text)
    words = direction_words(text)
    if words:
        out.append(f"{where}: direction words {words}")
    if _FORBIDDEN_CLAIMS.search(text):
        out.append(f"{where}: claims a signal badge / composite score")
    return out


def check_glossary(doc: dict[str, Any], required: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    terms = doc.get("terms") or []
    names = [str(t.get("term", "")) for t in terms]
    if len(set(names)) != len(names):
        out.append("glossary: duplicate terms " + str(sorted({n for n in names if names.count(n) > 1})))
    have = set(names)
    lower_names = {n.lower() for n in names}
    seen_alias: dict[str, str] = {}
    for t in terms:
        name = str(t.get("term", ""))
        short, long_ = str(t.get("short", "")), str(t.get("long", ""))
        if not short:
            out.append(f"glossary[{name}]: empty short")
        out += check_text_rules(f"glossary[{name}].short", short)
        if long_:
            out += check_text_rules(f"glossary[{name}].long", long_)
            if long_.strip() == short.strip():
                out.append(f"glossary[{name}]: long is a copy of short (leave it empty)")
        for s in t.get("see_also") or []:
            if s == name:
                out.append(f"glossary[{name}]: see_also names itself")
            elif s not in have:
                out.append(f"glossary[{name}]: see_also {s!r} is not a term")
        aliases = t.get("aliases") or []
        if not isinstance(aliases, list) or not all(isinstance(a, str) and a.strip() for a in aliases):
            out.append(f"glossary[{name}]: aliases must be non-empty strings")
            continue
        for a in aliases:
            key = a.strip().lower()
            if key == name.lower() or (key in lower_names and key != name.lower()):
                out.append(f"glossary[{name}]: alias {a!r} is a term's name")
            if key in seen_alias and seen_alias[key] != name:
                out.append(f"glossary[{name}]: alias {a!r} also used by {seen_alias[key]!r}")
            seen_alias.setdefault(key, name)
    for field in ("start_here", "required"):
        lst = doc.get(field) or []
        if len(set(lst)) != len(lst):
            out.append(f"glossary: {field} repeats a term")
        for s in lst:
            if s not in have:
                out.append(f"glossary: {field} names {s!r}, not a term")
    for r in required:
        if r not in have:
            out.append(f"glossary: required entry {r!r} missing (PLAN 1.6)")
    by_name = {str(t.get("term")): t for t in terms}
    for a, b in (("IV rank", "percentile"), ("IV percentile", "rank")):
        if a in by_name and f"not the {b}" not in str(by_name[a].get("short", "")).lower():
            out.append(f"glossary[{a}]: short must say 'Not the {b}' (rank vs percentile, PLAN 0.6 / G9)")
    if doc.get("count") != len(terms):
        out.append(f"glossary: count {doc.get('count')} != {len(terms)} terms")
    return out


def check_tooltips(doc: dict[str, Any]) -> list[str]:
    out: list[str] = []
    tips: dict[str, str] = doc.get("tooltips") or {}
    for k, v in tips.items():
        out += check_text_rules(f"tooltips[{k}]", str(v))
        if "." in k and k.split(".", 1)[0] not in PANEL_PAGES:
            out.append(f"tooltips[{k}]: unknown page prefix (known: {', '.join(sorted(PANEL_PAGES))})")
    panels = sorted(k for k in tips if "." in k)
    if list(doc.get("panels") or []) != panels:
        out.append("tooltips: `panels` is not exactly the sorted dotted keys")
    if doc.get("count") != len(tips):
        out.append(f"tooltips: count {doc.get('count')} != {len(tips)}")
    return out


def code_text(dirs: tuple[Path, ...] = CODE_DIRS, files: tuple[Path, ...] = CODE_FILES) -> str:
    parts: list[str] = []
    for d in dirs:
        parts += [p.read_text(encoding="utf-8") for p in sorted(d.glob("*.py"))] if d.is_dir() else []
    parts += [f.read_text(encoding="utf-8") for f in files if f.is_file()]
    return "\n".join(parts)


def missing_keys(keys: list[str], text: str) -> list[str]:
    """Non-panel keys that appear neither quoted (a payload / column name) nor as a DDL column in ``text``."""
    miss: list[str] = []
    for k in keys:
        if "." in k:
            continue
        esc = re.escape(k)
        pat = re.compile(r"""(["'])""" + esc + r"\1|\b" + esc + r"\s+(" + _DDL_TYPES + r")\b")
        if not pat.search(text):
            miss.append(k)
    return miss


def check_code_facts(copy_text: str, facts: tuple[tuple[str, str, Path, str], ...] = CODE_FACTS) -> list[str]:
    out: list[str] = []
    for label, needle, path, regex in facts:
        if needle not in copy_text:
            out.append(f"fact {label!r}: the LEARN copy no longer quotes {needle!r} (drop the fact or restore the text)")
        if not path.is_file():
            out.append(f"fact {label!r}: {_rel(path)} is missing")
        elif not re.search(regex, path.read_text(encoding="utf-8")):
            out.append(f"fact {label!r}: {_rel(path)} no longer matches {regex!r}; the copy is stale")
    return out


def bundled_copies(ui_root: Path = UI_ROOT) -> list[Path]:
    found: list[Path] = []
    if not ui_root.is_dir():
        return found
    for name in ("tooltips.json", "glossary.json"):
        for p in sorted(ui_root.rglob(name)):
            if any(part in UI_SKIP for part in p.relative_to(ui_root).parts):
                continue
            try:
                if json.loads(p.read_text(encoding="utf-8")).get("agent") == "B5-DOCS":
                    found.append(p)
            except (ValueError, AttributeError):
                continue
    return found


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


def check_bundled(glossary: dict[str, Any], tooltips: dict[str, Any], copies: list[Path]) -> list[str]:
    out: list[str] = []
    for p in copies:
        want = tooltips if p.name == "tooltips.json" else glossary
        if json.loads(p.read_text(encoding="utf-8")) != want:
            out.append(f"{_rel(p)}: bundled copy differs from reports/terminal_v2/LEARN/{p.name} (copy it again)")
    return out


# ─────────────────────────────────────────── driver ───────────────────────────────────────────

def validate(write: bool = False) -> list[str]:
    builder = load_builder()
    glossary, tooltips = builder.build()
    rendered = {GLOSSARY: builder.dumps(glossary), TOOLTIPS: builder.dumps(tooltips)}
    if write:
        for path, text in rendered.items():
            path.write_text(text, encoding="utf-8")
    defects: list[str] = []
    for path, text in rendered.items():
        if not path.exists():
            defects.append(f"{path.name}: missing (run with --write)")
        elif path.read_text(encoding="utf-8") != text:
            defects.append(f"{path.name}: differs from build_assets.py (run with --write; never hand-edit)")
    defects += check_glossary(glossary, tuple(builder.REQUIRED_TERMS))
    defects += check_tooltips(tooltips)
    missing = missing_keys(sorted(tooltips["tooltips"]), code_text())
    defects += [f"tooltips[{k}]: no stored column or payload field of that name in the v2 code" for k in missing]
    copy_text = " ".join([t["short"] + " " + t["long"] for t in glossary["terms"]] + list(tooltips["tooltips"].values()))
    defects += check_code_facts(copy_text)
    defects += check_bundled(glossary, tooltips, bundled_copies())
    return defects


def selftest() -> list[str]:
    """Negative controls: each synthetic defect must be reported; a clean minimal document must pass."""
    failures: list[str] = []
    good_terms = [{"term": "IV rank", "short": "Range position of IV. Not the percentile.", "long": "", "see_also": ["IV percentile"], "aliases": ["IVR"]},
                  {"term": "IV percentile", "short": "Share of days below. Not the rank.", "long": "Fixture 60.", "see_also": ["IV rank"], "aliases": ["IVP"]}]
    good = {"count": 2, "start_here": ["IV rank"], "required": ["IV rank"], "terms": good_terms}
    if check_glossary(good, ("IV rank", "IV percentile")):
        failures.append(f"clean glossary reported {check_glossary(good, ('IV rank', 'IV percentile'))}")

    def mutated(**over: Any) -> dict[str, Any]:
        terms = [dict(t) for t in good_terms]
        terms[0].update(over)
        return {**good, "terms": terms}

    cases: dict[str, dict[str, Any]] = {
        "too long": mutated(short="x" * 201 + " Not the percentile."),
        "two lines": mutated(short="line one\nline two. Not the percentile."),
        "bullish": mutated(short="A bullish reading. Not the percentile."),
        "long build-up": mutated(long="Price up with OI up is a long build-up."),
        "buy": mutated(long="Traders buy when it is low."),
        "will rise": mutated(long="IV will rise into results."),
        "dangling see_also": mutated(see_also=["nope"]),
        "self see_also": mutated(see_also=["IV rank"]),
        "alias is a term": mutated(aliases=["IV percentile"]),
        "long copies short": mutated(long="Range position of IV. Not the percentile."),
        "rank lacks 'Not the percentile'": mutated(short="Range position of IV."),
        "signal badge claim": mutated(long="Its badge `signal`: a forecast."),
    }
    for name, doc in cases.items():
        if not check_glossary(doc, ("IV rank", "IV percentile")):
            failures.append(f"defect {name!r} was not reported")
    if not check_glossary({**good, "terms": good_terms[1:]}, ("IV rank",)):
        failures.append("missing required entry was not reported")
    if direction_words("SPAN adds a short-option minimum"):
        failures.append("the allowed phrase 'short-option minimum' was flagged")
    tips_ok = {"count": 2, "panels": ["omon.chain"], "tooltips": {"iv30_cm": "CM IV.", "omon.chain": "Chain."}}
    if check_tooltips(tips_ok):
        failures.append(f"clean tooltips reported {check_tooltips(tips_ok)}")
    for name, bad in {"unknown page": {**tips_ok, "panels": ["zzz.chain"], "tooltips": {"iv30_cm": "x", "zzz.chain": "y"}},
                      "panels mismatch": {**tips_ok, "panels": []},
                      "count mismatch": {**tips_ok, "count": 5},
                      "sell in tooltip": {**tips_ok, "tooltips": {"iv30_cm": "Sell when high.", "omon.chain": "Chain."}}}.items():
        if not check_tooltips(bad):
            failures.append(f"tooltip defect {name!r} was not reported")
    code = 'CREATE TABLE t (iv30_cm DOUBLE, r DOUBLE)\nreturn {"pcr": 1}'
    if missing_keys(["iv30_cm", "r", "pcr", "omon.chain"], code):
        failures.append("present keys were reported missing")
    if missing_keys(["not_a_field"], code) != ["not_a_field"]:
        failures.append("an absent key was not reported")
    fake = ROOT / "reports" / "terminal_v2" / "LEARN" / "validate_learn.py"
    if not check_code_facts("nothing quoted", (("x", "needle", fake, r"impossible-regex-\d{40}"),)):
        failures.append("a stale code fact was not reported")
    return failures


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--write", action="store_true", help="rebuild glossary.json and tooltips.json from build_assets.py first")
    ap.add_argument("--selftest", action="store_true", help="run the negative controls, then exit")
    args = ap.parse_args(argv)
    if args.selftest:
        failures = selftest()
        for f in failures:
            print("FAIL", f)
        print("selftest ok: every synthetic defect is reported" if not failures else f"{len(failures)} selftest failure(s)")
        return 1 if failures else 0
    defects = validate(write=args.write)
    for d in defects:
        print("DEFECT", d)
    if defects:
        print(f"{len(defects)} defect(s)")
        return 1
    g = json.loads(GLOSSARY.read_text(encoding="utf-8"))
    t = json.loads(TOOLTIPS.read_text(encoding="utf-8"))
    print(f"ok: {g['count']} terms ({len(g['required'])} required), {t['count']} tooltips ({len(t['panels'])} panels); "
          f"every key in the code, no direction words, all ≤ {MAX_LEN} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
