#!/usr/bin/env python
"""
Gold data dictionary generator — renders ``docs/GOLD_DATA_DICTIONARY.md`` from the GOLD program's source catalog.

    python scripts/gold_data_dictionary.py                 # write docs/GOLD_DATA_DICTIONARY.md
    python scripts/gold_data_dictionary.py --check         # exit 1 when the committed doc is out of date
    python scripts/gold_data_dictionary.py --stdout        # print the rendered markdown

Inputs (read-only):
  * ``reports/gold_program/SOURCES.md`` — one ``### <id> · <title>`` entry per source with a ``**Verdict:**`` line
    (PUBLISH-CORE | PUBLISH-CONTEXT | LINK-ONLY | DO-NOT-PUBLISH), the §10 derived-metrics table, the §11 evidence
    ledger and the §12 cadence map. Every verdict in the rendered dictionary is copied verbatim from this file, so the
    document can never disagree with the research verdicts (PLAN §h T14).
  * ``services/data-service/gold/catalog_seed.py`` — the data-service catalog seed (owned by builder B1). When the file
    exists its ``series_id`` rows are rendered as the "Catalog series" section; when it does not, the dictionary says so
    and is generated from SOURCES.md alone.

The output is a pure function of the input bytes: no wall-clock time, no environment, sorted wherever a set is walked.
``scripts/tests/test_gold_data_dictionary.py`` asserts the determinism, the verdict counts and the committed copy.
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "reports" / "gold_program" / "SOURCES.md"
SEED_PATH = ROOT / "services" / "data-service" / "gold" / "catalog_seed.py"
OUT_PATH = ROOT / "docs" / "GOLD_DATA_DICTIONARY.md"

VERDICTS: tuple[str, ...] = ("PUBLISH-CORE", "PUBLISH-CONTEXT", "LINK-ONLY", "DO-NOT-PUBLISH")
VERDICT_MEANING: dict[str, str] = {
    "PUBLISH-CORE": "ingested into DuckDB (or computed) and shown on the GOLD page's primary panels",
    "PUBLISH-CONTEXT": "ingested and shown inside its section or a details drawer, always with the `context` badge; never on WEI/BRF",
    "LINK-ONLY": "a labelled link button to the publisher's page; nothing is fetched by the stack",
    "DO-NOT-PUBLISH": "not fetched, not shown (dead, blocked by terms, no gold content, or shown to be noise)",
}
# Hosts the stack must never fetch (PLAN §0.1 #6, §c.6; enforced on the code by test T8). A PUBLISH-* entry whose
# "Get it" line names one of these is a dictionary error, not a judgement call.
FORBIDDEN_HOSTS: tuple[str, ...] = (
    "www.cmegroup.com", "mcxindia.com", "kitco.com", "prices.lbma.org.uk", "stooq.com", "goldprice.org", "investing.com",
)

# Bold labels that start a field inside an entry bullet. Anything else in bold (``**only**``, ``**PASS as description:**``)
# is prose and stays inside the field it appears in.
_LABEL_RULES: tuple[tuple[str, str], ...] = (
    (r"^Publisher / URL$", "get"),
    (r"^URLs?$", "get"),
    (r"^Access$", "access"),
    (r"^Access reality.*$", "access"),
    (r"^Verified.*$", "verified"),
    (r"^Frequency.*$", "published"),
    (r"^Key fields$", "key_fields"),
    (r"^.*[Tt]raps.*$", "traps"),
    (r"^Terms$", "terms"),
    (r"^\[B\]$", "beginner"),
    (r"^\[P\]$", "pro"),
    (r"^Pros use it$", "pros"),
    (r"^Evidence.*$", "evidence"),
    (r"^In app today$", "in_app"),
    (r"^Consolidation$", "consolidation"),
    (r"^Verdict$", "verdict"),
    (r"^Catalog$", "catalog"),
    (r"^Dropped.*$", "verdict"),
)
_FIELD_ORDER: tuple[tuple[str, str], ...] = (
    ("get", "Get it"),
    ("access", "Access"),
    ("verified", "Verified"),
    ("published", "Published"),
    ("key_fields", "Key fields"),
    ("traps", "Traps"),
    ("terms", "Terms"),
    ("beginner", "Beginner"),
    ("pro", "Pro"),
    ("pros", "Pros use it"),
    ("evidence", "Evidence"),
    ("in_app", "In the terminal today"),
    ("consolidation", "After phase 2"),
    ("verdict", "Verdict"),
    ("catalog", "Catalog"),
    ("notes", "Notes"),
)

_ENTRY_RE = re.compile(r"^### (?P<id>[A-Z]\d+) · (?P<title>.+?)\s*$")
_SECTION_RE = re.compile(r"^## (?P<letter>[A-Z])\. (?P<title>.+?)\s*$")
_BOLD_RE = re.compile(r"\*\*(?P<label>[^*\n]+?)\*\*")
_VERDICT_RE = re.compile(r"\*\*Verdict:\*\*\s*(?P<verdict>[A-Z-]+)")
_COUNTS_RE = re.compile(
    r"PUBLISH-CORE \*\*(\d+)\*\* · PUBLISH-CONTEXT \*\*(\d+)\*\* · LINK-ONLY \*\*(\d+)\*\* · DO-NOT-PUBLISH \*\*(\d+)\*\* — \*\*(\d+) entries\*\*"
)
_METRIC_COUNTS_RE = re.compile(
    r"Derived metrics \(§10, (\d+) rows\):\s*PUBLISH-CORE (\d+) · PUBLISH-CONTEXT (\d+) · LINK-ONLY (\d+) · DO-NOT-PUBLISH (\d+)"
)
_VERIFIED_ON_RE = re.compile(r"verified live on \*\*([^*]+)\*\*")
_METRIC_ROW_RE = re.compile(r"^\| (?P<id>M\d+) \| (?P<metric>[^|]*) \| (?P<formula>[^|]*) \| (?P<cadence>[^|]*) \| "
                            r"(?P<evidence>[^|]*) \| (?P<verdict>[^|]*) \|\s*$")


@dataclass
class Entry:
    """One ``### <id> · <title>`` block of SOURCES.md, split into labelled fields."""

    id: str
    title: str
    section: str
    question: str = ""
    fields: dict[str, list[str]] = field(default_factory=dict)

    @property
    def verdict(self) -> str:
        """The verdict word of the entry's ``**Verdict:**`` field (raises when the entry has none)."""
        for text in self.fields.get("verdict", []):
            match = re.match(r"\s*(?P<v>[A-Z-]+)", text)
            if match and match.group("v") in VERDICTS:
                return match.group("v")
        raise ValueError(f"{self.id}: no verdict line (every SOURCES.md entry must carry **Verdict:** <verdict>)")

    @property
    def verdict_text(self) -> str:
        """The full verdict sentence (verdict word plus the reason), verbatim."""
        return " · ".join(t.strip() for t in self.fields.get("verdict", []))

    def get_hosts(self) -> list[str]:
        """Hostnames named in the entry's URL fields (sorted, unique)."""
        hosts: set[str] = set()
        for text in self.fields.get("get", []):
            for match in re.finditer(r"(?:https?|ftp)://([^/\s`)\]>]+)", text):
                hosts.add(match.group(1).lower())
        return sorted(hosts)


@dataclass
class Sources:
    """Everything the dictionary needs from SOURCES.md."""

    verified_on: str
    sections: list[tuple[str, str, str]]           # (letter, title, preamble)
    entries: list[Entry]
    declared_counts: dict[str, int]                 # from §1, including "entries"
    declared_metric_counts: dict[str, int]          # from §1, including "rows"
    questions_table: list[str]                      # §0 table lines, verbatim
    metrics_table: list[str]                        # §10 table lines, verbatim
    evidence_table: list[str]                       # §11 table lines, verbatim
    cadence_table: list[str]                        # §12 table lines, verbatim

    def counts(self) -> dict[str, int]:
        """Verdict counts over the parsed entries (plus the entry total)."""
        out = {v: 0 for v in VERDICTS}
        for entry in self.entries:
            out[entry.verdict] += 1
        out["entries"] = len(self.entries)
        return out

    def metric_rows(self) -> list[dict[str, str]]:
        """The §10 rows as dicts with the verdict word split out."""
        rows: list[dict[str, str]] = []
        for line in self.metrics_table:
            match = _METRIC_ROW_RE.match(line)
            if not match:
                continue
            row = {k: v.strip() for k, v in match.groupdict().items()}
            word = row["verdict"].split()[0] if row["verdict"] else ""
            row["verdict_word"] = word if word in VERDICTS else "UNKNOWN"
            rows.append(row)
        return rows

    def metric_counts(self) -> dict[str, int]:
        """Verdict counts over the §10 derived-metric rows (plus the row total)."""
        out = {v: 0 for v in VERDICTS}
        rows = self.metric_rows()
        for row in rows:
            if row["verdict_word"] in out:
                out[row["verdict_word"]] += 1
        out["rows"] = len(rows)
        return out


# ─────────────────────────────────────────── parsing ───────────────────────────────────────────

def _label_kind(label: str) -> str | None:
    """The field a bold token opens, or None when the token is prose (``**only**``, ``**Verified only via …**``)."""
    text = label.strip()
    if text not in ("[B]", "[P]") and not text.endswith(":"):
        return None
    text = text.removesuffix(":")
    for pattern, kind in _LABEL_RULES:
        if re.match(pattern, text):
            return kind
    return None


def _split_bullet(bullet: str) -> list[tuple[str, str]]:
    """Split one ``- **Label:** text · **Label:** text`` bullet into (kind, text) pairs."""
    pairs: list[tuple[str, str]] = []
    cursor = 0
    kind: str | None = None
    for match in _BOLD_RE.finditer(bullet):
        this_kind = _label_kind(match.group("label"))
        if this_kind is None:
            continue
        if kind is not None:
            pairs.append((kind, bullet[cursor:match.start()].strip(" ·")))
        elif bullet[:match.start()].strip(" ·"):
            pairs.append(("notes", bullet[:match.start()].strip(" ·")))
        kind, cursor = this_kind, match.end()
    if kind is not None:
        pairs.append((kind, bullet[cursor:].strip(" ·")))
    elif bullet.strip():
        pairs.append(("notes", bullet.strip()))
    return [(k, t) for k, t in pairs if t]


def _table_block(lines: list[str], heading_prefix: str) -> list[str]:
    """The first markdown table under the heading that starts with ``heading_prefix`` (verbatim lines)."""
    out: list[str] = []
    inside = False
    for line in lines:
        if line.startswith(heading_prefix):
            inside = True
            continue
        if inside and line.startswith("|"):
            out.append(line.rstrip())
        elif inside and out and not line.startswith("|"):
            break
    return out


def parse_sources(text: str) -> Sources:
    """Parse SOURCES.md. Raises ``ValueError`` on a structural defect (missing verdict, no counts line)."""
    lines = text.splitlines()
    verified = _VERIFIED_ON_RE.search(text)
    counts_match = _COUNTS_RE.search(text)
    metric_counts_match = _METRIC_COUNTS_RE.search(text)
    if not counts_match or not metric_counts_match:
        raise ValueError("SOURCES.md §1 counts line not found (PUBLISH-CORE **n** · … — **n entries** / Derived metrics (§10, n rows))")
    declared = dict(zip(("PUBLISH-CORE", "PUBLISH-CONTEXT", "LINK-ONLY", "DO-NOT-PUBLISH", "entries"),
                        (int(x) for x in counts_match.groups())))
    declared_metrics = dict(zip(("rows", "PUBLISH-CORE", "PUBLISH-CONTEXT", "LINK-ONLY", "DO-NOT-PUBLISH"),
                                (int(x) for x in metric_counts_match.groups())))

    sections: list[tuple[str, str, str]] = []
    entries: list[Entry] = []
    current_section: str | None = None
    preamble: list[str] = []
    entry: Entry | None = None
    bullet: list[str] = []

    def flush_bullet() -> None:
        if entry is not None and bullet:
            for kind, piece in _split_bullet(" ".join(s.strip() for s in bullet)):
                entry.fields.setdefault(kind, []).append(piece)
        bullet.clear()

    def flush_section_preamble() -> None:
        nonlocal preamble
        if current_section is not None and sections and sections[-1][0] == current_section and not sections[-1][2]:
            sections[-1] = (sections[-1][0], sections[-1][1], "\n".join(preamble).strip())
        preamble = []

    for raw in lines:
        line = raw.rstrip()
        if line.startswith("## 10. "):
            flush_bullet()
            flush_section_preamble()
            break
        section_match = _SECTION_RE.match(line)
        if section_match:
            flush_bullet()
            flush_section_preamble()
            entry = None
            current_section = section_match.group("letter")
            sections.append((current_section, section_match.group("title"), ""))
            continue
        if current_section is None:
            continue
        entry_match = _ENTRY_RE.match(line)
        if entry_match:
            flush_bullet()
            if entry is None:
                flush_section_preamble()
            entry = Entry(id=entry_match.group("id"), title=entry_match.group("title"), section=current_section)
            entries.append(entry)
            continue
        if entry is None:
            if line.strip() and not line.startswith("---"):
                preamble.append(line)
            continue
        if line.startswith("- "):
            flush_bullet()
            bullet.append(line[2:])
        elif line.startswith("  ") and bullet:
            bullet.append(line)
        elif line.startswith("*") and line.endswith("*") and not entry.question and not bullet:
            entry.question = line.strip("*").strip()
        else:
            flush_bullet()

    for e in entries:
        e.verdict  # noqa: B018  (raises when an entry has no verdict line)

    return Sources(
        verified_on=verified.group(1).strip() if verified else "an unrecorded date",
        sections=sections,
        entries=entries,
        declared_counts=declared,
        declared_metric_counts=declared_metrics,
        questions_table=_table_block(lines, "## 0. "),
        metrics_table=_table_block(lines, "## 10. "),
        evidence_table=_table_block(lines, "## 11. "),
        cadence_table=_table_block(lines, "## 12. "),
    )


def _normalise_row(item: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in sorted(item):
        value = item[key]
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        out[key] = "" if value is None else value
    return out


def _import_seed_rows(path: Path) -> list[dict[str, Any]]:
    """Load the seed as a standalone module (never its package) and return ``build_rows()`` / ``ROWS`` / ``SEED``."""
    spec = importlib.util.spec_from_file_location(f"_gold_catalog_seed_{path.stem}", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"no loader for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    builder = getattr(module, "build_rows", None)
    raw = builder() if callable(builder) else getattr(module, "ROWS", None) or getattr(module, "SEED", None) or []
    return [_normalise_row(r) for r in raw if isinstance(r, dict) and "series_id" in r]


def load_seed(path: Path | None) -> tuple[str, list[dict[str, Any]]]:
    """Read the data-service catalog seed: ``ast`` literals first (no code runs); else a guarded import of that one file.

    Returns a human-readable status and the rows found (every dict with a ``series_id`` key, sorted by id). A missing,
    unparseable or crashing seed never breaks the docs build: the status says what happened and zero rows are rendered.
    """
    if path is None or not path.exists():
        return "absent", []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:  # pragma: no cover - defensive: a broken seed must not break the docs build
        return f"unparseable ({exc.msg} at line {exc.lineno})", []
    rows: list[dict[str, Any]] = []
    names: list[str] = []
    has_builder = False
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "build_rows":
            has_builder = True
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        target = node.targets[0] if isinstance(node, ast.Assign) else node.target
        if isinstance(target, ast.Name):
            names.append(target.id)
        if node.value is None:
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError, TypeError):
            continue
        for item in _walk_literals(value):
            if isinstance(item, dict) and "series_id" in item:
                rows.append(_normalise_row(item))
    how = "literal rows"
    if not rows and has_builder:
        try:
            rows = _import_seed_rows(path)
            how = "build_rows()"
        except Exception as exc:  # noqa: BLE001 - any failure in B1's module is reported, never propagated
            return f"present but could not be loaded ({type(exc).__name__}: {exc})", []
    rows.sort(key=lambda r: str(r.get("series_id")))
    if rows:
        return f"present ({len(rows)} series rows via {how})", rows
    return f"present but no `series_id` rows recognised (top-level names: {', '.join(names) or 'none'})", []


_RANK = {v: i for i, v in enumerate(VERDICTS[::-1])}   # DO-NOT-PUBLISH 0 … PUBLISH-CORE 3


def seed_disagreements(sources: Sources, rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Seed rows whose verdict is looser (upgrades: a defect) or stricter (downgrades: allowed, listed) than their entry."""
    by_id = {e.id: e for e in sources.entries}
    upgrades: list[str] = []
    downgrades: list[str] = []
    for row in rows:
        entry = by_id.get(str(row.get("source_entry", "")))
        verdict = str(row.get("verdict", ""))
        if entry is None or verdict not in _RANK:
            continue
        if _RANK[verdict] > _RANK[entry.verdict]:
            upgrades.append(f"`{row['series_id']}` is {verdict} but its source {entry.id} is {entry.verdict}")
        elif _RANK[verdict] < _RANK[entry.verdict]:
            downgrades.append(f"`{row['series_id']}` {verdict} (source {entry.id} {entry.verdict})")
    return upgrades, downgrades


def _walk_literals(value: Any):
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from _walk_literals(v)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for v in (sorted(value, key=repr) if isinstance(value, (set, frozenset)) else value):
            yield from _walk_literals(v)


# ─────────────────────────────────────────── rendering ───────────────────────────────────────────

def _md_cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _render_entry(entry: Entry) -> list[str]:
    out = [f"### {entry.id} · {entry.title}"]
    if entry.question:
        out.append(f"*{entry.question}*")
    out.append("")
    for kind, label in _FIELD_ORDER:
        texts = entry.fields.get(kind)
        if not texts:
            continue
        out.append(f"- **{label}:** {' · '.join(texts)}")
    out.append("")
    return out


def _render_seed(status: str, rows: list[dict[str, Any]], seed_path: Path | None) -> list[str]:
    shown = seed_path.relative_to(ROOT).as_posix() if seed_path and seed_path.is_relative_to(ROOT) else "services/data-service/gold/catalog_seed.py"
    out = ["## Catalog series (`gold_series_catalog` seed)", ""]
    if not rows:
        out += [
            (f"Catalog seed `{shown}`: **{status}** at generation time, so this dictionary was generated from SOURCES.md alone. "
             "The series ids the page needs on day one are listed in PLAN.md §c.2; once the seed lands, re-run "
             "`scripts/gold_data_dictionary.py` and this section fills itself (the generator reads `ast` literals first; otherwise "
             "`build_rows()` is imported from that one file)."),
            "",
        ]
        return out
    present = {k for r in rows for k in r}
    columns = [c for c in ("series_id", "name", "source_entry", "freq", "unit", "verdict", "badge", "max_age_days", "ingest_job",
                           "publish_time_ist") if c in present] or sorted(present)
    by_verdict: dict[str, int] = {}
    for row in rows:
        by_verdict[str(row.get("verdict", "?"))] = by_verdict.get(str(row.get("verdict", "?")), 0) + 1
    out += [
        (f"Catalog seed `{shown}`: {status}. Verdicts: " + " · ".join(f"{k} {by_verdict[k]}" for k in sorted(by_verdict)) +
         ". Every row's `source_entry` points at the SOURCES.md entry below; a row may be stricter than its entry, never looser "
         "(an upgrade is listed below as a defect; `--strict` refuses it). Badges: " +
         " · ".join(f"{b} {sum(1 for r in rows if r.get('badge') == b)}" for b in ("signal", "context", "arithmetic", "heuristic")) + "."),
        "", "| " + " | ".join(columns) + " |", "|" + "---|" * len(columns),
    ]
    for row in rows:
        out.append("| " + " | ".join(_md_cell(row.get(c, "")) for c in columns) + " |")
    out.append("")
    return out


def render(sources: Sources, seed_status: str = "absent", seed_rows: list[dict[str, Any]] | None = None,
           seed_path: Path | None = None, strict: bool = False) -> str:
    """Render the dictionary markdown. Pure: the same inputs always give the same bytes.

    A seed row looser than its SOURCES.md entry is a labelling defect (PLAN §f.2): it is listed in the document under
    a "defect" heading so the two never silently disagree, and raises when ``strict`` is set (the CI gate once B1's seed
    is reconciled).
    """
    seed_rows = seed_rows or []
    counts = sources.counts()
    metric_counts = sources.metric_counts()
    if {k: counts[k] for k in VERDICTS} != {k: sources.declared_counts[k] for k in VERDICTS} or counts["entries"] != sources.declared_counts["entries"]:
        raise ValueError(f"SOURCES.md §1 declares {sources.declared_counts} but the entries parse as {counts}; fix SOURCES.md §1 first")
    if {k: metric_counts[k] for k in VERDICTS} != {k: sources.declared_metric_counts[k] for k in VERDICTS} \
            or metric_counts["rows"] != sources.declared_metric_counts["rows"]:
        raise ValueError(f"SOURCES.md §1 declares derived metrics {sources.declared_metric_counts} but §10 parses as {metric_counts}")
    for entry in sources.entries:
        if entry.verdict.startswith("PUBLISH"):
            bad = [h for h in entry.get_hosts() if any(h == f or h.endswith("." + f) for f in FORBIDDEN_HOSTS)]
            if bad:
                raise ValueError(f"{entry.id} is {entry.verdict} but names a forbidden host {bad} (PLAN §c.6)")

    upgrades, downgrades = seed_disagreements(sources, seed_rows)
    if upgrades and strict:
        raise ValueError("catalog seed is looser than SOURCES.md (PLAN §f.2): " + "; ".join(upgrades))

    by_verdict: dict[str, list[Entry]] = {v: [] for v in VERDICTS}
    for entry in sources.entries:
        by_verdict[entry.verdict].append(entry)

    out: list[str] = [
        "# Gold free-data dictionary",
        "",
        (f"Every free source behind the GOLD page, verified live on {sources.verified_on} by the GOLD program's research agents "
         "and synthesised in `reports/gold_program/SOURCES.md` (every verdict here is copied from that file verbatim). "
         "Style follows `docs/NSE_DATA_DICTIONARY.md`; the build plan is `reports/gold_program/PLAN.md`; the study verdicts the "
         "badges rest on are in `reports/gold_program/G-STUDY/FINDINGS.md` and `reports/gold_program/FINDINGS.md`."),
        "",
        ("**Generated** by `scripts/gold_data_dictionary.py` — do not edit by hand; edit SOURCES.md (or the catalog seed) and re-run. "
         "`--check` fails when this file is stale, and `scripts/tests/test_gold_data_dictionary.py` runs that check."),
        "",
        "## Your questions, answered by dataset",
        "",
        *sources.questions_table,
        "",
        "## Verdicts and badges",
        "",
        "**Verdict** (per source): the owner's gate — \"will it be useful to refer to the data? if yes then only publish\".",
        "",
        "| Verdict | Meaning in the terminal | Sources | Derived metrics (§10) |",
        "|---|---|---|---|",
    ]
    for v in VERDICTS:
        out.append(f"| **{v}** | {VERDICT_MEANING[v]} | {counts[v]} | {metric_counts[v]} |")
    out += [
        f"| **total** | | {counts['entries']} | {metric_counts['rows']} |",
        "",
        ("**Badge** (per metric, PLAN §f): `signal` — a pre-registered study PASSED as a forecast in both halves after costs "
         "(**none today**); `context` — PASS as a description or context-only (the COT strip, every health gauge, every "
         "premium and flow); `arithmetic` — an identity, cost or spec that makes no claim about the future (fair value, landed "
         "cost, carry, tick value, the KGX split); `heuristic` — a house rule without evidence (the ₹300 chase limit, the "
         "headline risk count). A number with no catalog row is not rendered. Context metrics are never coloured bullish or "
         "bearish, nothing gold feeds the Decision Desk or the paper ticket's price, and the health verdict ends \"describes, "
         "does not predict\"."),
        "",
        "**PUBLISH-CORE sources:** " + ", ".join(e.id for e in by_verdict["PUBLISH-CORE"]) + ".",
        "",
        "**Never fetched by the stack:** " + ", ".join(f"`{h}`" for h in FORBIDDEN_HOSTS) +
        " (PLAN §c.6; the allowlist test T8 enforces it on the code, this generator refuses a PUBLISH-* entry that names one).",
        "",
    ]
    out += _render_seed(seed_status, seed_rows, seed_path)
    if upgrades:
        out += [("**Seed rows looser than their source entry — a defect to fix in the seed (PLAN §f.2: the SOURCES.md verdict "
                 "is the published one):** " + "; ".join(upgrades)), ""]
    if downgrades:
        out += ["Seed rows stricter than their source entry (allowed; listed so the difference is deliberate): " + "; ".join(downgrades), ""]

    for letter, title, preamble in sources.sections:
        out += [f"## {letter}. {title}", ""]
        if preamble:
            out += [preamble, ""]
        for entry in (e for e in sources.entries if e.section == letter):
            out += _render_entry(entry)

    out += ["## 10. Derived metrics (what the terminal computes; verdict and badge)", "",
            ("Notation: `L/S/X` long/short/spread per group; `OI`; `F1,F2` consecutive futures; `G` gold USD; `INR` USD/INR; "
             "`d` duty rate; 31.1034768 g/oz; MCX ₹/10 g."), "",
            *sources.metrics_table, "",
            "## 11. Evidence ledger (the study results the badges rest on)", "", *sources.evidence_table, "",
            "## 12. Cadence map (IST) — what arrives when", "", *sources.cadence_table, "",
            "## Index by verdict", ""]
    for v in VERDICTS:
        out.append(f"**{v}** ({counts[v]}): " + " · ".join(f"{e.id} {e.title}" for e in by_verdict[v]))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def build(sources_path: Path = SOURCES_PATH, seed_path: Path | None = SEED_PATH, strict: bool = False) -> str:
    """Parse the inputs on disk and render the dictionary."""
    sources = parse_sources(sources_path.read_text(encoding="utf-8"))
    status, rows = load_seed(seed_path)
    return render(sources, status, rows, seed_path, strict=strict)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns the process exit code."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sources", type=Path, default=SOURCES_PATH)
    parser.add_argument("--seed", type=Path, default=SEED_PATH, help="catalog seed module (parsed with ast; may be absent)")
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument("--check", action="store_true", help="exit 1 if --out differs from the rendered text")
    parser.add_argument("--stdout", action="store_true", help="print instead of writing")
    parser.add_argument("--strict", action="store_true", help="fail when a seed row is looser than its SOURCES.md entry")
    args = parser.parse_args(argv)

    try:
        text = build(args.sources, args.seed, strict=args.strict)
    except ValueError as exc:   # SOURCES.md defect, forbidden host, or --strict with a looser seed: one line, exit 1
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    if args.stdout:
        sys.stdout.write(text)
        return 0
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else ""
        if current != text:
            print(f"STALE: {args.out} differs from the rendered dictionary; run scripts/gold_data_dictionary.py", file=sys.stderr)
            return 1
        print(f"ok: {args.out} is current")
        return 0
    args.out.write_text(text, encoding="utf-8")
    seed_status, _ = load_seed(args.seed)
    print(f"wrote {args.out} ({len(text.encode('utf-8'))} bytes; catalog seed {seed_status})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
