#!/usr/bin/env python
"""Validate the GOLD › LEARN assets against the build plan, and assemble CURRICULUM.md from its parts.

    python reports/gold_program/G-EDU/validate_learn.py            # check only (exit 1 on any defect)
    python reports/gold_program/G-EDU/validate_learn.py --write    # rebuild glossary.json, tooltips.json, CURRICULUM.md first

Checks (each failure is one line, all are reported):
  1. glossary.json: every `see_also` resolves to a term, no self reference, `short` ≤ 200 chars and single-line.
  2. tooltips.json: every value ≤ 200 chars and single-line; `panels` lists exactly the dotted keys.
  3. every panel id in PLAN.md §a.2–a.9 (``h.*``, ``d.*``, ``w.*``, ``m.*``, ``p.*``, ``ph.*``, ``mc.*``, ``c.*``) has a tooltip,
     and every panel tooltip names a panel that PLAN.md still has.
  4. CURRICULUM.md is byte-identical to the concatenation of ``parts/*.md`` (the parts are the source).
  5. CURRICULUM.md Part 8: every ``8.x.y`` heading carries its PLAN panel id(s) or an explicit non-GOLD home (MCXG / WEI / BRF /
     CMDT / ECO), per PLAN Appendix B; the health-verdict rule table exists and ends "describes, does not predict".
  6. The duty is the dated 15 % everywhere it is stated as current (no "in force since 24 Jul 2024" / "at 6%" ladder left),
     the CBIC caveat is present, and the glossary + tooltips agree.
  7. Labelling rules (PLAN §f): the words "bullish"/"bearish" never describe a context metric in Part 8 micro-copy; no
     "consider half size" advice; no composite "score".
  8. CURRICULUM.md §8.4 (the health-verdict rule table) matches ``HEALTH_RULES`` in services/ui-api/routers/gold.py, read
     with ``ast`` (never imported): the same rule_ids, each row naming the rule's ``series_id`` and its ``threshold`` dict
     verbatim (``no threshold`` when the rule has none). The code is the source; the table follows it.
  9. Every non-panel tooltip key is referenced by name in a ui/ source file (components, lib, app; tests excluded): a
     tooltip nobody renders is retired (build_glossary.py RETIRED_FIELD_KEYS), not kept.
 10. (wave 1c) glossary.json `aliases`: a list of strings per term, each unique across the glossary and never a term's
     own name; `start_here` names existing terms, no repeats; `long` is never a copy of `short` (empty instead).
 11. (wave 1c) Every `## n.m` section of Parts 0–8 carries at least one `**[B]**` paragraph (the beginner layer is
     never empty: C-BEGINNER-9); a `**[P]**` may prefix a Part 8 micro-copy heading (`**[P]** **8.2.2 …**`).
Pure stdlib; read-only unless --write. `--selftest` runs checks 10–11 on synthetic inputs with negative controls.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PLAN = HERE.parent / "PLAN.md"
CURRICULUM = HERE / "CURRICULUM.md"
PARTS_DIR = HERE / "parts"
GLOSSARY = HERE / "glossary.json"
TOOLTIPS = HERE / "tooltips.json"
MAX_LEN = 200
PANEL_PREFIXES = ("h", "d", "w", "m", "p", "ph", "mc", "c")
_PANEL_ID_RE = re.compile(r"`((?:h|d|w|m|p|ph|mc|c)\.[a-z0-9]+(?:\.[a-z0-9]+)*)`")
_PART8_HEADING_RE = re.compile(r"^(?:\*\*\[P\]\*\* )?\*\*(8\.[12]\.\d+) ")
_SECTION_RE = re.compile(r"^## (\d+(?:\.\d+)?) ")
_LAYER_RE = re.compile(r"^\*\*\[(B|P|APP)\]\*\*")
NON_GOLD_HOMES = ("MCXG", "WEI", "BRF", "CMDT", "ECO")
STALE_DUTY = (
    "in force since 24 Jul 2024",
    "6% from 24 Jul 2024 (cut from 15%)",
    "at 6%   (BCD 5% + AIDC 1%",
    "6% since 24 Jul 2024 as of this document",
    "duty-paid at 6%",
)
ROOT = HERE.parents[2]
GOLD_ROUTER = ROOT / "services" / "ui-api" / "routers" / "gold.py"
UI_DIRS = (ROOT / "ui" / "components", ROOT / "ui" / "lib", ROOT / "ui" / "app")
_RULE_ROW_RE = re.compile(r"^\| (H[0-9][^ |]*) \|")


def plan_panel_ids(text: str) -> list[str]:
    """Panel ids from the first column of the PLAN §a.2–a.9 tables (sorted, unique)."""
    ids: set[str] = set()
    inside = False
    for line in text.splitlines():
        if line.startswith("### a."):
            inside = line[4:].split()[0] not in ("a.1", "a.10")
            continue
        if line.startswith(("## ", "### ")):
            inside = False
        if inside and line.startswith("| `"):
            first = line.split("|")[1].strip()
            match = _PANEL_ID_RE.match(first)
            if match:
                ids.add(match.group(1))
    return sorted(ids)


def assemble_curriculum() -> str:
    parts = sorted(PARTS_DIR.glob("*.md"))
    return "".join(p.read_text(encoding="utf-8") for p in parts)


def health_rules_from_source(path: Path = GOLD_ROUTER) -> list[dict[str, object]]:
    """``HEALTH_RULES`` from routers/gold.py without importing it: ``rule_id`` / ``clause`` / ``series_id`` / ``threshold``
    per rule. A ``Name`` value resolves through the module's string constants (``COT_SERIES_ID``); an f-string ``rule`` is
    recorded as None. Raises ValueError when the list is not there."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    consts: dict[str, str] = {}
    rules_node: ast.expr | None = None
    for node in tree.body:
        target: str | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        if target is None or value is None:
            continue
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            consts[target] = value.value
        if target == "HEALTH_RULES":
            rules_node = value
    if rules_node is None:
        raise ValueError(f"{path}: HEALTH_RULES not found")
    if not isinstance(rules_node, ast.List):
        raise TypeError(f"{path}: HEALTH_RULES is not a list literal")
    rules: list[dict[str, object]] = []
    for elt in rules_node.elts:
        if not isinstance(elt, ast.Dict):
            continue
        rule: dict[str, object] = {}
        for key, value in zip(elt.keys, elt.values):
            if not isinstance(key, ast.Constant):
                continue
            if isinstance(value, ast.Constant):
                rule[str(key.value)] = value.value
            elif isinstance(value, ast.Name):
                rule[str(key.value)] = consts.get(value.id, value.id)
            elif isinstance(value, ast.Dict):
                rule[str(key.value)] = ast.literal_eval(value)
            else:
                rule[str(key.value)] = None
        rules.append(rule)
    return rules


def glossary_defects(glossary: dict) -> list[str]:
    """Check 10: aliases, start_here and long-vs-short on a parsed glossary.json (pure; used by --selftest)."""
    out: list[str] = []
    terms = [str(t.get("term", "")) for t in glossary.get("terms", [])]
    names = {t.lower() for t in terms} | {t.lower().split(" (")[0] for t in terms}
    seen: dict[str, str] = {}
    for t in glossary.get("terms", []):
        term = str(t.get("term", ""))
        aliases = t.get("aliases")
        if not isinstance(aliases, list) or any(not isinstance(a, str) or not a.strip() or "\n" in a for a in aliases):
            out.append(f"glossary: {term!r} aliases must be a list of non-empty one-line strings")
            continue
        for a in aliases:
            key = a.strip().lower()
            if key in names:
                out.append(f"glossary: alias {a!r} of {term!r} equals a term name")
            if key in seen:
                out.append(f"glossary: alias {a!r} used by both {seen[key]!r} and {term!r}")
            seen[key] = term
        if t.get("long") and t.get("long") == t.get("short"):
            out.append(f"glossary: {term!r} long repeats short (leave long empty instead)")
    start = glossary.get("start_here")
    if not isinstance(start, list) or not start:
        out.append("glossary: start_here must be a non-empty list of terms")
    else:
        if len(start) != len(set(start)):
            out.append("glossary: start_here repeats a term")
        for pinned in start:
            if pinned not in terms:
                out.append(f"glossary: start_here {pinned!r} is not a term")
    return out


def sections_without_b(curriculum: str) -> list[str]:
    """Check 11: the `## n.m` sections before Part 9 whose body has no `**[B]**` paragraph (pure; used by --selftest)."""
    body = curriculum.split("# PART 9", 1)[0]
    missing: list[str] = []
    current: str | None = None
    has_b = False
    fence = False

    def close() -> None:
        if current is not None and not has_b:
            missing.append(current)

    for line in body.splitlines():
        if line.startswith("```"):
            fence = not fence
        if fence:
            continue
        if line.startswith("# "):
            close()
            current, has_b = None, False
            continue
        match = _SECTION_RE.match(line)
        if match:
            close()
            current, has_b = match.group(1), False
            continue
        layer = _LAYER_RE.match(line.strip())
        if current is not None and layer and layer.group(1) == "B":
            has_b = True
    close()
    return missing


def selftest() -> list[str]:
    """Negative controls for checks 10–11: each synthetic defect must be reported, the clean inputs must pass."""
    failures: list[str] = []
    spot: dict[str, Any] = {"term": "spot", "short": "a", "long": "", "aliases": ["XAU"]}
    basis: dict[str, Any] = {"term": "basis (x)", "short": "b", "long": "c", "aliases": []}
    clean: dict[str, Any] = {"start_here": ["spot"], "terms": [spot, basis]}
    if glossary_defects(clean):
        failures.append(f"selftest: clean glossary reported {glossary_defects(clean)}")
    cases = {
        "alias equals a term": {**clean, "terms": [{**spot, "aliases": ["basis"]}, basis]},
        "alias used twice": {**clean, "terms": [{**spot, "aliases": ["x"]}, {**basis, "aliases": ["X"]}]},
        "long repeats short": {**clean, "terms": [{**spot, "long": "a"}, basis]},
        "start_here unknown": {**clean, "start_here": ["nope"]},
        "start_here repeats": {**clean, "start_here": ["spot", "spot"]},
        "aliases not a list": {**clean, "terms": [{**spot, "aliases": "XAU"}, basis]},
    }
    for name, bad in cases.items():
        if not glossary_defects(bad):
            failures.append(f"selftest: glossary defect {name!r} was not reported")
    good_md = "# T\n\n## 1.1 A\n\n**[B]** x\n\n**[P]** y\n\n## 1.2 B\n\n**[P]** z\n**[B]** w\n\n# PART 9\n\n## 9.1 no b here\n"
    if sections_without_b(good_md):
        failures.append(f"selftest: clean curriculum reported {sections_without_b(good_md)}")
    bad_md = "# T\n\n## 2.5 A\n\nplain\n\n**[P]** y\n\n## 2.6 B\n\n**[B]** ok\n\n```\n**[B]** inside a fence does not count\n```\n\n## 2.7 C\n\n```\n**[B]** fenced\n```\n"
    if sections_without_b(bad_md) != ["2.5", "2.7"]:
        failures.append(f"selftest: expected ['2.5', '2.7'], got {sections_without_b(bad_md)}")
    return failures


def ui_source_text() -> str:
    """Every .ts / .tsx file under ui/components, ui/lib and ui/app (tests and node_modules excluded), concatenated."""
    chunks: list[str] = []
    for folder in UI_DIRS:
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if path.suffix in (".ts", ".tsx") and "__tests__" not in path.parts and "node_modules" not in path.parts:
                chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def check(write: bool = False) -> list[str]:
    """Run every check; return the list of defects (empty = pass)."""
    errors: list[str] = []
    if write:
        sys.path.insert(0, str(HERE))
        import build_glossary  # local tool; imported only on --write

        build_glossary.main()
        CURRICULUM.write_text(assemble_curriculum(), encoding="utf-8")

    glossary = json.loads(GLOSSARY.read_text(encoding="utf-8"))
    tooltips = json.loads(TOOLTIPS.read_text(encoding="utf-8"))
    plan = PLAN.read_text(encoding="utf-8")
    curriculum = CURRICULUM.read_text(encoding="utf-8")

    # 1. glossary
    terms = [t["term"] for t in glossary["terms"]]
    term_set = set(terms)
    if len(terms) != len(term_set):
        errors.append("glossary: duplicate terms")
    if glossary.get("count") != len(terms):
        errors.append(f"glossary: count {glossary.get('count')} != {len(terms)} terms")
    for t in glossary["terms"]:
        if not (0 < len(t["short"]) <= MAX_LEN) or "\n" in t["short"]:
            errors.append(f"glossary: short of {t['term']!r} is {len(t['short'])} chars / multi-line")
        for ref in t["see_also"]:
            if ref not in term_set:
                errors.append(f"glossary: {t['term']!r} see_also {ref!r} does not resolve")
            if ref == t["term"]:
                errors.append(f"glossary: {t['term']!r} references itself")
    errors.extend(glossary_defects(glossary))                       # 10. aliases, start_here, long ≠ short

    # 2. tooltips
    tips: dict[str, str] = tooltips["tooltips"]
    for key, text in tips.items():
        if not (0 < len(text) <= MAX_LEN) or "\n" in text:
            errors.append(f"tooltips: {key!r} is {len(text)} chars / multi-line")
    dotted = sorted(k for k in tips if "." in k and k.split(".")[0] in PANEL_PREFIXES)
    if tooltips.get("panels") != dotted:
        errors.append("tooltips: `panels` list does not equal the dotted panel keys")
    if tooltips.get("count") != len(tips):
        errors.append(f"tooltips: count {tooltips.get('count')} != {len(tips)}")

    # 3. PLAN panel ids ↔ tooltips
    ids = plan_panel_ids(plan)
    if not ids:
        errors.append("PLAN.md: no panel ids parsed from §a tables")
    for pid in ids:
        if pid not in tips:
            errors.append(f"tooltips: PLAN panel `{pid}` has no tooltip")
    for pid in dotted:
        if pid not in ids:
            errors.append(f"tooltips: panel `{pid}` is not in PLAN.md §a")

    # 4. CURRICULUM == parts
    if curriculum != assemble_curriculum():
        errors.append("CURRICULUM.md differs from the concatenation of parts/*.md (run with --write)")

    # 5. Part 8 rename pass + health rule table
    part8 = curriculum.split("# PART 8", 1)[1].split("# PART 9", 1)[0] if "# PART 8" in curriculum else ""
    if not part8:
        errors.append("CURRICULUM.md: Part 8 not found")
    for line in part8.splitlines():
        match = _PART8_HEADING_RE.match(line)
        if not match:
            continue
        named = _PANEL_ID_RE.findall(line)
        if not named and not any(home in line for home in NON_GOLD_HOMES):
            errors.append(f"CURRICULUM Part 8 heading {match.group(1)} carries no PLAN panel id and no non-GOLD home")
        for pid in named:
            if pid not in ids:
                errors.append(f"CURRICULUM Part 8 heading {match.group(1)} names `{pid}`, which PLAN.md §a does not have")
    if "describes, does not predict" not in part8:
        errors.append("CURRICULUM Part 8: the health-verdict rule table must end 'describes, does not predict'")
    if "## 8.4" not in part8:
        errors.append("CURRICULUM Part 8: §8.4 (health verdict rule table) missing")

    # 6. duty
    for stale in STALE_DUTY:
        if stale in curriculum:
            errors.append(f"CURRICULUM.md still states the old duty as current: {stale!r}")
    for needle, where in (("16/2026-Customs", "CURRICULUM.md"), ("13 May 2026", "CURRICULUM.md")):
        if needle not in curriculum:
            errors.append(f"{where}: dated duty reference {needle!r} missing")
    if "CBIC" not in curriculum:
        errors.append("CURRICULUM.md: the CBIC confirmation caveat is missing")
    duty_terms = {t["term"]: t for t in glossary["terms"]}.get("customs duty (BCD + AIDC)")
    if not duty_terms or "15%" not in duty_terms["short"] or "13 May 2026" not in duty_terms["short"]:
        errors.append("glossary: 'customs duty (BCD + AIDC)' must state 15% since 13 May 2026")
    if "15%" not in tips.get("duty_rate", "") or "16/2026" not in tips.get("duty_rate", ""):
        errors.append("tooltips: duty_rate must state the dated 15% (Notification 16/2026-Customs)")

    # 7. labelling rules in the micro-copy
    lowered = part8.lower()
    for bad in ("consider half size", "composite score", "n of 7"):
        if bad in lowered:
            errors.append(f"CURRICULUM Part 8 contains forbidden wording {bad!r} (PLAN §f)")
    for key, text in tips.items():
        if "bullish" in text.lower() or "bearish" in text.lower():
            errors.append(f"tooltips: {key!r} uses bullish/bearish wording (PLAN §f.3)")
        if "half size" in text.lower():
            errors.append(f"tooltips: {key!r} gives sizing advice (disagreement 14)")

    # 8. §8.4 == HEALTH_RULES in routers/gold.py (the code is the source; the table follows it)
    table = part8.split("## 8.4", 1)[1] if "## 8.4" in part8 else ""
    rows: dict[str, str] = {}
    for line in table.splitlines():
        match = _RULE_ROW_RE.match(line)
        if match:
            rows[match.group(1)] = line
    try:
        rules = health_rules_from_source()
    except (OSError, ValueError, TypeError, SyntaxError) as exc:
        rules = []
        errors.append(f"routers/gold.py: HEALTH_RULES could not be read ({exc})")
    rule_ids = {str(r.get("rule_id")) for r in rules}
    for rule in rules:
        rid = str(rule.get("rule_id"))
        row = rows.get(rid)
        if row is None:
            errors.append(f"CURRICULUM §8.4: HEALTH_RULES {rid} ({rule.get('clause')}) has no table row")
            continue
        sid = rule.get("series_id")
        if sid and f"`{sid}`" not in row:
            errors.append(f"CURRICULUM §8.4: row {rid} must name its series `{sid}`")
        threshold = rule.get("threshold")
        want = f"`{json.dumps(threshold)}`" if isinstance(threshold, dict) else "no threshold"
        if want not in row:
            errors.append(f"CURRICULUM §8.4: row {rid} must carry {want} (routers/gold.py HEALTH_RULES)")
    for rid in rows:
        if rules and rid not in rule_ids:
            errors.append(f"CURRICULUM §8.4: row {rid} is not a rule_id in routers/gold.py HEALTH_RULES")

    # 11. every section of Parts 0–8 has a [B] paragraph (C-BEGINNER-9: the beginner layer is never empty)
    for sid in sections_without_b(curriculum):
        errors.append(f"CURRICULUM §{sid} has no **[B]** paragraph (every section needs its beginner line)")

    # 9. every field tooltip key is referenced by name somewhere under ui/ (the reverse of gold_views.check.ts)
    ui_text = ui_source_text()
    if not ui_text:
        errors.append("ui/: no .ts/.tsx source found (check 9 needs the repo's ui tree)")
    for key in sorted(k for k in tips if k not in dotted):
        if ui_text and not re.search(r"(?<![A-Za-z0-9_])" + re.escape(key) + r"(?![A-Za-z0-9_])", ui_text):
            errors.append(f"tooltips: field key {key!r} is referenced by no ui/ source file (retire it or render it)")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate (and optionally rebuild) the GOLD › LEARN assets.")
    parser.add_argument("--write", action="store_true", help="rebuild glossary.json, tooltips.json and CURRICULUM.md first")
    parser.add_argument("--selftest", action="store_true", help="run checks 10–11 on synthetic inputs with negative controls, then exit")
    args = parser.parse_args(argv)
    if args.selftest:
        failures = selftest()
        for line in failures:
            print("FAIL", line)
        print("selftest ok: checks 10–11 report every synthetic defect and pass the clean inputs" if not failures else f"{len(failures)} selftest failure(s)")
        return 1 if failures else 0
    errors = check(write=args.write)
    for line in errors:
        print("FAIL", line)
    if errors:
        print(f"{len(errors)} defect(s)")
        return 1
    glossary = json.loads(GLOSSARY.read_text(encoding="utf-8"))
    tooltips = json.loads(TOOLTIPS.read_text(encoding="utf-8"))
    n_alias = sum(len(t.get("aliases", [])) for t in glossary["terms"])
    print(f"ok: {glossary['count']} glossary terms ({n_alias} aliases, {len(glossary.get('start_here', []))} start-here), "
          f"{tooltips['count']} tooltips ({len(tooltips['panels'])} panels), "
          f"{len(plan_panel_ids(PLAN.read_text(encoding='utf-8')))} PLAN panel ids, CURRICULUM.md == parts/*.md, "
          f"§8.4 == HEALTH_RULES ({len(health_rules_from_source())} rules), every field tooltip referenced under ui/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
