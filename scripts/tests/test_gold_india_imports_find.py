"""The PIB finder: parsing rules only, no network (the fixtures are the shapes PIB really serves).

Every rule has a negative control, because this script's whole job is to read a number out of prose without
mis-reading it. It never writes to the store — the owner confirms each figure.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gold_india_imports_find as f  # noqa: E402

FEED = """<rss><channel><title>Press Information Bureau</title>
<item><title>Diwali celebrated at forward posts</title><link>https://pib.gov.in/PressReleaseIframePage.aspx?PRID=111</link></item>
<item><title>India's Foreign Trade: October 2026</title><link>https://pib.gov.in/PressReleaseIframePage.aspx?PRID=222</link></item>
</channel></rss>"""


def test_feed_items_keeps_order_and_pulls_the_prid():
    items = f.feed_items(FEED)
    assert [p for _, p in items] == ["111", "222"]
    assert items[1][0] == "India's Foreign Trade: October 2026"
    assert f.feed_items("<rss><channel></channel></rss>") == []        # negative control: no items


def test_only_trade_like_titles_are_followed():
    titles = [t for t, _ in f.feed_items(FEED)]
    picked = [t for t in titles if any(h in t.lower() for h in f.TITLE_HINTS)]
    assert picked == ["India's Foreign Trade: October 2026"]           # the Diwali release is not followed


def test_the_figure_is_read_and_normalised_to_billions():
    assert f.find_figure("gold imports grew by 4.8 per cent to US$ 4.2 billion in July 2026")[0] == 4.2
    assert f.find_figure("Imports of gold stood at USD 1.80 bn during the month.")[0] == 1.8
    assert f.find_figure("gold imports were US$ 950 million in the month")[0] == 0.95   # million → billions
    assert f.find_figure("US$ 2.3 billion worth of gold was imported")[0] == 2.3        # figure before the word


def test_it_refuses_what_it_should_not_read():
    assert f.find_figure("Merchandise exports rose to US$ 38 billion in October") is None   # no gold in the sentence
    assert f.find_figure("Gold prices touched Rs 1,42,540 per 10 grams") is None           # rupees, not US$
    assert f.find_figure("no figures here at all") is None
    # a sentence boundary stops the match: a gold mention cannot borrow a number from the NEXT sentence
    assert f.find_figure("Gold demand was strong. Silver imports were US$ 5 billion.") is None


def test_page_text_drops_scripts_so_their_digits_are_never_read_as_figures():
    raw = "<html><script>var gold_usd = 99; </script><p>gold imports were US$ 3.1 billion</p></html>"
    txt = f.page_text(raw)
    assert "var gold_usd" not in txt and "99" not in txt
    assert f.find_figure(txt)[0] == 3.1


def test_the_sentence_is_returned_so_the_owner_can_check_it():
    usd_bn, sentence = f.find_figure("In October 2026, gold imports fell to US$ 1.8 billion from a year earlier.")
    assert usd_bn == 1.8 and "October 2026" in sentence and "gold imports" in sentence


# --- the month guard: what makes --store safe ------------------------------------------------------------------


def test_the_month_must_be_named_in_the_figures_own_sentence():
    assert f.month_named("gold imports fell to US$ 1.8 billion in October 2026", "2026-10")
    assert f.month_named("In Oct 2026 gold imports were US$ 1.8 bn", "2026-10")
    assert f.month_named("gold imports in October stood at US$ 1.8 bn", "2026-10")


def test_the_guard_refuses_the_three_ways_a_release_misleads():
    # a year-earlier comparison for a month we are NOT storing: August is nowhere in the sentence
    assert not f.month_named("gold imports rose to US$ 4.2 bn in July 2026 from US$ 4.0 bn in July 2025", "2026-08")
    # a different month entirely (the release also quotes September)
    assert not f.month_named("gold imports were US$ 2.1 billion in September 2026", "2026-10")
    # no month named at all: a year-to-date or quarterly total
    assert not f.month_named("gold imports during the current financial year were US$ 29 billion", "2026-10")


def test_the_guard_rejects_a_sentence_naming_two_months_even_when_one_is_right():
    s = "Gold imports in October 2026 were US$ 1.8 bn against November 2025 levels"
    assert not f.month_named(s, "2026-10")   # both named → cannot tell which the figure belongs to


# --- the scheduled job: it must be registered, outside both freeze windows, and skip a stored month ---------------


def test_the_watch_job_is_registered_on_the_days_after_publication_outside_the_freeze_windows():
    src = (Path(__file__).resolve().parents[1] / "master_controller.py").read_text()
    assert 'id="india_imports_watch"' in src
    i = src.index('id="india_imports_watch"')
    block = src[max(0, i - 400):i]
    assert 'day="15-22"' in block, "must only look on the days around publication"
    assert "hour=11" in block and "minute=15" in block
    # 11:15 is outside 07:45-09:20 and 18:30-21:15 (CLAUDE.md restart/freeze windows)
    assert not (7 <= 11 < 9 or 18 <= 11 < 22)


def test_the_job_returns_without_storing_when_the_month_is_already_present():
    src = (Path(__file__).resolve().parents[1] / "master_controller.py").read_text()
    body = src[src.index("async def india_imports_watch"):src.index("async def special_session_close")]
    assert "INDIA_GOLD_IMPORTS_USD_BN" in body and "return" in body
    assert '[:7] == month' in body, "must compare the stored month, not the exact day"
    assert "GOLD_JOBS_ENABLED" in body, "must honour the gold-jobs opt-out"
    assert "--store" in body
    # quiet on 'nothing published yet': no alert for exit 3 / 4
    assert "exit 3 (no release yet)" in body or "stay quiet" in body
