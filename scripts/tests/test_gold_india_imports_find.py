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
