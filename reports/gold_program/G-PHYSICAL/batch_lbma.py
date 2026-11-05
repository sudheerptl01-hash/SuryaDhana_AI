"""Batch 1: LBMA (auction prices JSON, trade data, vault data, Good Delivery) + FRED gold series (keyless CSV)."""
import json
import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from verify import fetch  # noqa: E402

# LBMA price JSON feeds (the public endpoint behind the prices page)
for metal, fn in [("gold_am", "lbma_gold_am.json"), ("gold_pm", "lbma_gold_pm.json"), ("silver", "lbma_silver.json")]:
    rec = fetch(f"LBMA prices JSON {metal}", f"https://prices.lbma.org.uk/json/{metal}.json", save_as=fn)
    if rec.get("status") == 200 and "json" in rec.get("content_type", "") or (rec.get("head", "").startswith("[")):
        try:
            data = json.loads(open(rec["saved"]).read())
            print("   rows:", len(data), "first:", data[0], "last:", data[-1])
        except Exception as exc:  # noqa: BLE001
            print("   parse fail", exc)

# LBMA site pages
fetch("LBMA precious metal prices page", "https://www.lbma.org.uk/prices-and-data/precious-metal-prices", save_as="lbma_prices_page.html")
fetch("LBMA trade data page (LBMA-i)", "https://www.lbma.org.uk/prices-and-data/lbma-trade-data", save_as="lbma_trade_data_page.html")
fetch("LBMA London vault data page", "https://www.lbma.org.uk/prices-and-data/london-vault-data", save_as="lbma_vault_page.html")
fetch("LBMA Good Delivery gold list", "https://www.lbma.org.uk/good-delivery/gold-current-list", save_as="lbma_gd_gold.html")
fetch("LBMA robots.txt", "https://www.lbma.org.uk/robots.txt")
fetch("LBMA prices robots.txt", "https://prices.lbma.org.uk/robots.txt")

# FRED keyless CSV (same path gold_preopen uses for DFII10)
for sid in ["GOLDAMGBD228NLBM", "GOLDPMGBD228NLBM"]:
    rec = fetch(f"FRED {sid} fredgraph.csv", f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd=2025-01-01",
                plain_ua=True, save_as=f"fred_{sid}.csv")
    if rec.get("status") == 200:
        lines = open(rec["saved"]).read().strip().splitlines()
        print("   lines:", len(lines), "first:", lines[:2], "last:", lines[-2:])
    fetch(f"FRED {sid} series page", f"https://fred.stlouisfed.org/series/{sid}", plain_ua=True, save_as=f"fred_{sid}_page.html")
