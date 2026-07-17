"""Fetch NEW out-of-sample M15 data (after 2026-05-12) for the forward test
of the M15 setup. Companion to fetch_research_data.py (same source/normalization),
with a fresh date range and a separate output folder so the original research
data is never touched.

Start is set to 2026-05-01 to give indicator warm-up and an overlap window for
cross-validating against the research data; the forward test itself only
counts trades entered after 2026-05-12.

Usage:  python Data/fetch_oos_data.py
Output: Data/OOS/M15/<INSTRUMENT>_M15.parquet (+ _quality_report.csv)
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dukascopy_python import INTERVAL_MIN_15, OFFER_SIDE_BID, fetch, instruments

START_DATE = datetime(2026, 5, 1, tzinfo=timezone.utc)
END_DATE = datetime(2026, 7, 17, tzinfo=timezone.utc)

OUTPUT_DIR = Path(__file__).resolve().parent / "OOS" / "M15"

INSTRUMENTS = {
    "EURUSD": instruments.INSTRUMENT_FX_MAJORS_EUR_USD,
    "GBPUSD": instruments.INSTRUMENT_FX_MAJORS_GBP_USD,
    "USDJPY": instruments.INSTRUMENT_FX_MAJORS_USD_JPY,
    "XAUUSD": instruments.INSTRUMENT_FX_METALS_XAU_USD,
    "NAS100": instruments.INSTRUMENT_IDX_AMERICA_E_NQ_100,
    "US30": instruments.INSTRUMENT_IDX_AMERICA_E_D_J_IND,
}


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Range: {START_DATE.isoformat()} -> {END_DATE.isoformat()}")
    print(f"Output: {OUTPUT_DIR}\n")
    reports, failures = [], 0

    for name, duka_symbol in INSTRUMENTS.items():
        try:
            t0 = time.time()
            print(f"[{name}] fetching ...", flush=True)
            df = fetch(
                instrument=duka_symbol,
                interval=INTERVAL_MIN_15,
                offer_side=OFFER_SIDE_BID,
                start=START_DATE,
                end=END_DATE,
            )
            if df is None or df.empty:
                raise RuntimeError("empty dataframe returned")
            df.index = pd.to_datetime(df.index, utc=True)
            df.index.name = "timestamp"
            df.columns = [c.lower() for c in df.columns]
            df = df.sort_index()
            out = OUTPUT_DIR / f"{name}_M15.parquet"
            df.to_parquet(out, compression="zstd")
            reports.append(
                {
                    "instrument": name,
                    "status": "OK",
                    "rows": len(df),
                    "start": df.index.min(),
                    "end": df.index.max(),
                    "nan_rows": int(df.isna().any(axis=1).sum()),
                    "dup_ts": int(df.index.duplicated().sum()),
                    "bad_high": int(
                        (df["high"] < df[["open", "close"]].max(axis=1)).sum()
                    ),
                    "bad_low": int(
                        (df["low"] > df[["open", "close"]].min(axis=1)).sum()
                    ),
                }
            )
            print(f"[{name}]   {len(df):,} bars in {time.time() - t0:.1f}s -> {out}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            reports.append({"instrument": name, "status": "FAIL", "error": str(e)})
            print(f"[{name}]   FAILED: {e}", file=sys.stderr)

    rep = pd.DataFrame(reports)
    rep.to_csv(OUTPUT_DIR / "_quality_report.csv", index=False)
    print("\n" + rep.to_string(index=False))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
