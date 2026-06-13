#!/usr/bin/env python3
"""Phase 5 (D1) — index_membership + delistings schema + honest snapshot load.

Closes the *wiring* half of D1: the `index_membership` and `delistings` tables
are ABSENT from `data/market.duckdb`, so the G2 survivorship mechanism in
`services/ui-api/routers/analytics.py` (`_load_membership_intervals`,
`_attach_membership`, `_delisting_map`) falls back to the full survivor universe
and honestly reports `membership_pit=False`.

This script creates BOTH tables in the EXACT shape those consumers query:

    index_membership(ticker, index_name, effective_from DATE, effective_to DATE NULL)
        -- NULL effective_to == still a member (analytics maps it to +inf).
        -- queried with: WHERE (? IS NULL OR index_name = ?)

    delistings(ticker, delist_date DATE, delist_return_pct DOUBLE)
        -- consumed by _delisting_map; missing return -> -100% (full wipe-out).

HONESTY CONTRACT (per BILLIONAIRE_SCALE_AUDIT.md D1 + Phase 5):
  * index_membership is loaded SNAPSHOT-ONLY. We have a *current* NIFTY500
    constituent list (data/NSE_1500.csv, `index == 'NIFTY500'`) but NO honest
    free source for historical add/drop (reconstitution) dates. So every loaded
    interval gets:
        effective_from = a single conservative `--effective-from` anchor date
        effective_to   = NULL (still a member)
    This is NOT point-in-time history. We do NOT fabricate per-name join dates.
    Because every interval opens at the same anchor and never closes, the merge_asof
    as-of join in `_attach_membership` will mark `membership_pit=True` mechanically
    — which would OVERSTATE the honesty. To keep G2 truthful we therefore DO NOT
    load membership by default unless `--load-membership` is passed, and when it is,
    we stamp `_snapshot_only=1` rows and print a loud banner so the operator (and the
    README) records that this is a survivor snapshot, not reconstitution history.
    membership_pit at the engine remains a *mechanical* flag; the survivorship
    banner driven by `delist_by_ticker` is the load-bearing honesty signal and it
    stays LIVE because `delistings` is empty.

  * delistings is created EMPTY. Free NSE delisting history *with delisting
    returns* (the final traded price / scheme consideration vs prior close) is not
    reliably obtainable without a paid/official NSE corporate-actions feed or a
    bhavcopy-archive crawl of delisting circulars. We refuse to fabricate returns
    (a wrong -100% or +0% would silently bias every CAGR). The table is wired and
    ready; the survivorship haircut flag stays LIVE until real rows land.

USAGE:
    # create both tables empty + wired (default — keeps every honesty flag truthful):
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/backfill_index_membership.py \
        --db data/market.duckdb

    # ALSO load the NIFTY500 current snapshot (clearly snapshot-only, NOT PIT):
    ... --load-membership --index NIFTY500 --effective-from 2021-05-17
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

# pandas >= 3.0 infers a `str` dtype duckdb 1.1.1 cannot scan; opt back to object.
try:
    pd.set_option("future.infer_string", False)
except Exception:  # pragma: no cover
    pass

try:
    import duckdb
except ImportError:  # pragma: no cover
    print("FATAL: duckdb not importable", file=sys.stderr)
    raise


# Shapes are an EXACT match for the analytics.py consumers. effective_to is
# nullable (NULL == open interval). We add a non-load-bearing `_snapshot_only`
# audit column so a future PIT backfill can distinguish real reconstitution
# intervals from this snapshot seed. analytics.py SELECTs explicit columns, so the
# extra column is harmless to the consumer.
DDL_INDEX_MEMBERSHIP = """
CREATE TABLE IF NOT EXISTS index_membership (
    ticker          VARCHAR NOT NULL,
    index_name      VARCHAR NOT NULL,
    effective_from  DATE    NOT NULL,
    effective_to    DATE,
    _snapshot_only  BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (ticker, index_name, effective_from)
);
"""

DDL_DELISTINGS = """
CREATE TABLE IF NOT EXISTS delistings (
    ticker             VARCHAR NOT NULL,
    delist_date        DATE    NOT NULL,
    delist_return_pct  DOUBLE,
    PRIMARY KEY (ticker, delist_date)
);
"""


def _count(con, table: str) -> int:
    try:
        return int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except Exception:
        return 0


def load_snapshot_membership(
    con,
    universe_csv: Path,
    index_name: str,
    effective_from: date,
) -> int:
    """Load a current-constituent snapshot as open intervals (effective_to=NULL).

    SNAPSHOT-ONLY: every row shares the same `effective_from` anchor and a NULL
    close. This is NOT reconstitution history. Vectorised; no row loops.
    """
    df = pd.read_csv(universe_csv)
    if "ticker" not in df.columns or "index" not in df.columns:
        raise ValueError(
            f"{universe_csv} needs 'ticker' and 'index' columns; got {list(df.columns)}"
        )
    sub = df[df["index"].astype(str).str.upper() == index_name.upper()].copy()
    if sub.empty:
        print(f"  [warn] no rows in {universe_csv} with index == {index_name!r}; nothing loaded.")
        return 0

    out = pd.DataFrame(
        {
            "ticker": sub["ticker"].astype(str).str.strip().str.upper(),
            "index_name": index_name.upper(),
            "effective_from": pd.Timestamp(effective_from),
            "effective_to": pd.NaT,  # open interval -> NULL in DuckDB
            "_snapshot_only": True,
        }
    ).drop_duplicates(subset=["ticker", "index_name", "effective_from"])

    # Force datetime64 dtype on the date columns (an all-NaT column would otherwise
    # be object/float and break the CAST AS DATE on register).
    out["effective_from"] = pd.to_datetime(out["effective_from"])
    out["effective_to"] = pd.to_datetime(out["effective_to"])

    con.register("mem_stage", out)
    con.execute(
        """
        INSERT OR REPLACE INTO index_membership
        SELECT ticker, index_name, CAST(effective_from AS DATE),
               CAST(effective_to AS DATE), _snapshot_only
        FROM mem_stage
        """
    )
    con.unregister("mem_stage")
    return len(out)


def run(
    db_path: str,
    universe_csv: str,
    load_membership: bool,
    index_name: str,
    effective_from: date,
) -> dict:
    try:
        con = duckdb.connect(db_path, read_only=False)
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(
            f"ABORT: cannot acquire DuckDB write lock on {db_path} "
            f"(is data-service running?): {exc}"
        )
    report: dict = {}
    try:
        con.execute(DDL_INDEX_MEMBERSHIP)
        con.execute(DDL_DELISTINGS)
        report["index_membership_before"] = _count(con, "index_membership")
        report["delistings_before"] = _count(con, "delistings")

        loaded = 0
        if load_membership:
            loaded = load_snapshot_membership(
                con, Path(universe_csv), index_name, effective_from
            )
        report["membership_loaded"] = loaded
        report["index_membership_after"] = _count(con, "index_membership")
        report["delistings_after"] = _count(con, "delistings")  # stays 0 — honest
    finally:
        con.close()
    return report


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Phase 5 (D1) index_membership + delistings schema/snapshot loader"
    )
    ap.add_argument("--db", default="data/market.duckdb")
    ap.add_argument("--universe", default="data/NSE_1500.csv")
    ap.add_argument(
        "--load-membership",
        action="store_true",
        help="load the current index snapshot (SNAPSHOT-ONLY, not PIT history)",
    )
    ap.add_argument("--index", default="NIFTY500", help="index_name to load from the CSV")
    ap.add_argument(
        "--effective-from",
        default="2021-05-17",
        help="anchor effective_from for the snapshot (default = OHLCV span start)",
    )
    args = ap.parse_args()

    eff = date.fromisoformat(args.effective_from)
    report = run(
        db_path=args.db,
        universe_csv=args.universe,
        load_membership=args.load_membership,
        index_name=args.index,
        effective_from=eff,
    )

    print("\n" + "=" * 64)
    print("INDEX_MEMBERSHIP / DELISTINGS SCHEMA + LOAD REPORT")
    print("=" * 64)
    print(f"  index_membership: {report['index_membership_before']:>6} -> {report['index_membership_after']:>6}")
    print(f"    snapshot rows loaded     : {report['membership_loaded']}")
    print(f"  delistings      : {report['delistings_before']:>6} -> {report['delistings_after']:>6}  (intentionally EMPTY)")
    print("=" * 64)
    if args.load_membership and report["membership_loaded"]:
        print(
            "  HONESTY: index_membership is a CURRENT-SNAPSHOT (effective_to=NULL, single\n"
            "           anchor effective_from). This is NOT point-in-time reconstitution\n"
            "           history. The survivorship haircut banner stays LIVE because\n"
            "           `delistings` is empty (no honest free source for delisting returns)."
        )
    else:
        print(
            "  HONESTY: both tables created + WIRED but unloaded. Survivorship haircut\n"
            "           flag remains LIVE. See scripts/PHASE5_DATA_BACKFILL.md."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
