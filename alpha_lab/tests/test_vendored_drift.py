"""The vendored copies in alpha_lab/lib must match their origins byte for byte (ORIGINS.md)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAIRS = [("alpha_lab/lib/" + f, "shared/" + f) for f in
         ("nse_panel.py", "trading_costs.py", "momentum.py", "xs_labels.py", "deal_filters.py")]


def test_vendored_files_match_their_origins():
    drift = [a for a, b in PAIRS if (ROOT / a).read_bytes() != (ROOT / b).read_bytes()]
    assert drift == [], f"vendored copies differ from origin: {drift} — re-copy or record the fork in ORIGINS.md"
