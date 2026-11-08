#!/usr/bin/env python
"""Find India's monthly gold-import figure in the government's own press releases, and propose the entry command.

Why this exists (SOURCES.md F14). The figure has no machine-readable feed: the trade portal is a web form with no
download, and RBI answers an automated XLSX download with a captcha (both probed 8 Nov 2026). What IS reachable is PIB,
the government's press agency: its RSS listing and release pages answer a plain client with HTTP 200 and no captcha, and
the Commerce Ministry's monthly trade release states the gold figure in prose.

So this script automates the GATHERING and stops there:

    python scripts/gold_india_imports_find.py            # look for the newest trade release and read the figure

It prints the release it found, the figure it read, and the exact `gold_india_imports.py` command to store it. It never
writes to the store, because a number parsed out of prose can be wrong in ways a plausibility check cannot catch (a
revised figure, a quarter instead of a month, silver in the same sentence), and a wrong point-in-time row is worse than
a missing one. You read the sentence it quotes, then run the command — or correct it.

Exit codes: 0 a figure was found and a command printed · 2 the release was found but no figure could be read (the link
is printed, so you can read it yourself) · 3 no trade release found in the window · 4 the network refused us.
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx

IST = timezone(timedelta(hours=5, minutes=30))
# PIB only. Read-only, official, public; no key, no form, no captcha (probed 8 Nov 2026).
RSS = "https://www.pib.gov.in/RssMain.aspx?ModId=6&Lang=1&Regid=3"
RELEASE = "https://pib.gov.in/PressReleaseIframePage.aspx?PRID={prid}"
UA = "SuryaDhana-research/1.0 (personal research; contact via the repository)"
PACE_S = 1.2            # one request at a time, spaced: a press site owes us nothing
MAX_RELEASES = 4        # never crawl: at most the few candidate titles

# The monthly release is titled around trade/exports/imports. Deliberately broad: a missed title costs a manual look,
# a wrong one costs nothing (the figure regex then finds nothing and we print the link).
TITLE_HINTS = ("trade", "export", "import", "व्यापार", "commerce", "merchandise")
# "gold imports ... US$ 4.2 billion" / "gold imports at USD 1.80 bn" / "import of gold ... $ 2.3 billion"
# `SAME_SENTENCE` spans anything EXCEPT a sentence boundary (a period followed by whitespace), so a decimal like
# "4.8 per cent" does not break the span while "Gold demand was strong. Silver imports were US$ 5 bn" still cannot
# lend its number to the word "gold" in the previous sentence. A plain [^.] would reject every decimal in between.
SAME_SENTENCE = r"(?:(?!\.\s)[\s\S])"
FIGURE_RE = re.compile(
    r"gold" + SAME_SENTENCE + r"{0,120}?(?:US\$|USD|\$)\s*([0-9]+(?:\.[0-9]+)?)\s*(billion|bn|million|mn)\b"
    r"|(?:US\$|USD|\$)\s*([0-9]+(?:\.[0-9]+)?)\s*(billion|bn|million|mn)\b" + SAME_SENTENCE + r"{0,60}?gold",
    re.IGNORECASE)


def get(client: httpx.Client, url: str) -> str:
    """One paced GET. Raises httpx.HTTPError, which the caller turns into exit 4."""
    time.sleep(PACE_S)
    r = client.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=30)
    r.raise_for_status()
    return r.text


def feed_items(xml: str) -> list[tuple[str, str]]:
    """(title, PRID) per item, newest first as PIB serves them."""
    out = []
    for block in re.findall(r"<item>(.*?)</item>", xml, re.DOTALL | re.IGNORECASE):
        t = re.search(r"<title>(.*?)</title>", block, re.DOTALL | re.IGNORECASE)
        p = re.search(r"PRID=(\d+)", block)
        if t and p:
            out.append((html.unescape(re.sub(r"<[^>]+>", "", t.group(1))).strip(), p.group(1)))
    return out


def page_text(raw: str) -> str:
    """Visible text only: scripts and styles carry no figures and plenty of digits."""
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def find_figure(text: str) -> tuple[float, str] | None:
    """The first gold+currency figure, normalised to US$ billions, with the sentence it came from."""
    m = FIGURE_RE.search(text)
    if not m:
        return None
    val, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    usd_bn = float(val) / 1000 if unit.lower() in ("million", "mn") else float(val)
    start = max(0, m.start() - 160)
    return usd_bn, text[start:m.end() + 160].strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Find India's monthly gold-import figure in PIB releases.")
    ap.add_argument("--month", default=None, help="the month to propose (YYYY-MM); default: last month")
    ap.add_argument("--max-releases", type=int, default=MAX_RELEASES, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    today = datetime.now(IST).date()
    month = a.month or (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")

    try:
        with httpx.Client() as client:
            items = feed_items(get(client, RSS))
            if not items:
                print("PIB's feed returned no items — read the release yourself: https://pib.gov.in")
                return 3
            cands = [(t, p) for t, p in items if any(h in t.lower() for h in TITLE_HINTS)][:a.max_releases]
            print(f"PIB feed: {len(items)} releases, {len(cands)} look like trade releases")
            if not cands:
                print("  none mentions trade/exports/imports yet — the monthly release lands around the 15th.")
                print("  Check by hand: https://pib.gov.in  (ministry: Commerce and Industry)")
                return 3
            for title, prid in cands:
                text = page_text(get(client, RELEASE.format(prid=prid)))
                hit = find_figure(text)
                link = RELEASE.format(prid=prid)
                print(f"\n  {title[:96]}\n  {link}")
                if hit:
                    usd_bn, sentence = hit
                    print(f'\n  read: "…{sentence[:300]}…"')
                    print(f"\n  → US${usd_bn:g} bn. Check that sentence says GOLD, the month {month}, and not silver,")
                    print("    then store it:\n")
                    print(f"      python scripts/gold_india_imports.py --month {month} --usd-bn {usd_bn:g} \\")
                    print(f'          --source "PIB PRID {prid}"')
                    return 0
                print("    (no gold figure in this release)")
            print("\nFound trade releases but no gold figure in them — open the links above and read it yourself,")
            print(f"then: python scripts/gold_india_imports.py --month {month} --usd-bn <figure>")
            return 2
    except httpx.HTTPError as exc:
        print(f"PIB did not answer ({type(exc).__name__}) — try later, or read it at https://pib.gov.in")
        return 4


if __name__ == "__main__":
    sys.exit(main())
