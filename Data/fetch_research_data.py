"""
CRT + ICT PD Array Research — Data Acquisition
================================================
Fetches M15 OHLCV data from Dukascopy for 6 instruments, 2022-05-12 to 2026-05-12.
Stores as Parquet, runs quality checks, prints a summary report.

Usage:
    pip install dukascopy-python pandas pyarrow
    python fetch_research_data.py

Output:
    ./data/m15/<INSTRUMENT>_M15.parquet
    ./data/m15/_quality_report.csv
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import dukascopy_python
from dukascopy_python import (
    fetch,
    INTERVAL_MIN_15,
    OFFER_SIDE_BID,
    instruments,
)

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------

START_DATE = datetime(2022, 5, 12, tzinfo=timezone.utc)
END_DATE   = datetime(2026, 5, 12, tzinfo=timezone.utc)

OUTPUT_DIR = Path("./data/m15")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Maps our internal name -> (Dukascopy constant, FTMO MT5 symbol reference)
# IMPORTANT: Verify FTMO symbols in your MT5 Market Watch — they may differ.
INSTRUMENTS = {
    "EURUSD": (instruments.INSTRUMENT_FX_MAJORS_EUR_USD,   "EURUSD"),
    "GBPUSD": (instruments.INSTRUMENT_FX_MAJORS_GBP_USD,   "GBPUSD"),
    "USDJPY": (instruments.INSTRUMENT_FX_MAJORS_USD_JPY,   "USDJPY"),
    "XAUUSD": (instruments.INSTRUMENT_FX_METALS_XAU_USD,   "XAUUSD"),
    "NAS100": (instruments.INSTRUMENT_IDX_AMERICA_E_NQ_100, "US100.cash"),
    "US30":   (instruments.INSTRUMENT_IDX_AMERICA_E_D_J_IND, "US30.cash"),
}

# ----------------------------------------------------------------------------
# Fetch
# ----------------------------------------------------------------------------

def fetch_instrument(name: str, duka_symbol: str) -> pd.DataFrame:
    """Fetch full M15 history for one instrument."""
    print(f"[{name}] Fetching {duka_symbol} ...", flush=True)
    t0 = time.time()
    df = fetch(
        instrument=duka_symbol,
        interval=INTERVAL_MIN_15,
        offer_side=OFFER_SIDE_BID,
        start=START_DATE,
        end=END_DATE,
    )
    # Normalize
    df.index = pd.to_datetime(df.index, utc=True)
    df.index.name = "timestamp"
    df.columns = [c.lower() for c in df.columns]
    # Drop weekend rows just in case (Dukascopy usually does this already)
    df = df[~df.index.dayofweek.isin([5, 6]) | (df.index.dayofweek == 6) & (df.index.hour >= 22)]
    elapsed = time.time() - t0
    print(f"[{name}]   -> {len(df):,} bars in {elapsed:.1f}s", flush=True)
    return df


# ----------------------------------------------------------------------------
# Quality checks
# ----------------------------------------------------------------------------

def quality_check(name: str, df: pd.DataFrame) -> dict:
    """Return a quality report dict for one instrument."""
    rep: dict = {
        "instrument": name,
        "rows": len(df),
        "start": df.index.min(),
        "end":   df.index.max(),
        "duplicate_timestamps": int(df.index.duplicated().sum()),
        "nan_rows": int(df.isna().any(axis=1).sum()),
    }

    # Detect gaps. Expected M15 cadence = 15 min. Weekend gaps ~ 47-50 hours
    # (Fri close to Sun open). Anything > 30 min and < 40 hours on a weekday
    # is suspect and worth a look.
    deltas = df.index.to_series().diff().dt.total_seconds().div(60)
    suspect = deltas[(deltas > 30) & (deltas < 40 * 60)]
    rep["suspect_intra_gaps"] = int(len(suspect))
    rep["max_gap_minutes"] = float(deltas.max()) if len(deltas) else 0.0

    # Basic sanity: high >= max(open, close), low <= min(open, close)
    bad_high = (df["high"] < df[["open", "close"]].max(axis=1)).sum()
    bad_low  = (df["low"]  > df[["open", "close"]].min(axis=1)).sum()
    rep["bad_high_rows"] = int(bad_high)
    rep["bad_low_rows"]  = int(bad_low)

    # Zero-range bars (sign of stitched/missing data)
    rep["zero_range_bars"] = int(((df["high"] - df["low"]) == 0).sum())

    return rep


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main() -> int:
    print(f"Range: {START_DATE.isoformat()} -> {END_DATE.isoformat()}")
    print(f"Output: {OUTPUT_DIR.resolve()}\n")

    reports: list[dict] = []
    failures = 0

    for name, (duka_symbol, ftmo_symbol) in INSTRUMENTS.items():
        try:
            df = fetch_instrument(name, duka_symbol)
            if df.empty:
                raise RuntimeError("Empty dataframe returned")
            out_path = OUTPUT_DIR / f"{name}_M15.parquet"
            df.to_parquet(out_path, compression="zstd")

            rep = quality_check(name, df)
            rep["status"] = "OK"
            rep["file"] = str(out_path)
            rep["ftmo_symbol_ref"] = ftmo_symbol
            print(f"[{name}]   saved -> {out_path}")
        except Exception as e:
            failures += 1
            rep = {
                "instrument": name,
                "status": "FAIL",
                "error": f"{type(e).__name__}: {e}",
                "ftmo_symbol_ref": ftmo_symbol,
            }
            print(f"[{name}]   FAILED: {e}", file=sys.stderr)
        reports.append(rep)
        print()

    # Persist report
    rep_df = pd.DataFrame(reports)
    rep_path = OUTPUT_DIR / "_quality_report.csv"
    rep_df.to_csv(rep_path, index=False)

    print("=" * 80)
    print("QUALITY REPORT")
    print("=" * 80)
    # Pretty print
    with pd.option_context(
        "display.max_columns", None,
        "display.width", 200,
        "display.max_colwidth", 40,
    ):
        print(rep_df.to_string(index=False))
    print(f"\nReport saved -> {rep_path}")
    print(f"\nSummary: {len(reports) - failures}/{len(reports)} succeeded.")

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
