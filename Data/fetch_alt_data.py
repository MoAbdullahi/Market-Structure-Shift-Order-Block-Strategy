"""Fetch ALTERNATE-SOURCE history from histdata.com for independent
verification of the Dukascopy-based results.

Source: histdata.com free ASCII M1 bars (timestamps in EST = UTC-5, fixed,
no DST — shifted to UTC here). M1 is resampled to M15.

Instruments: the 4 FX pairs + XAUUSD plus histdata's NSXUSD index CFD
(NASDAQ 100 -> NAS100). histdata does not carry the Dow Jones 30, so US30
has no alternate source and is excluded here.

Usage:  python Data/fetch_alt_data.py
Output: Data/ALT/M15/<INSTRUMENT>_M15.parquet (+ _quality_report.csv)
"""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pandas as pd
from histdata import download_hist_data
from histdata.api import Platform, TimeFrame

OUTPUT_DIR = Path(__file__).resolve().parent / "ALT" / "M15"
CACHE_DIR = Path(__file__).resolve().parent / "ALT" / "_m1_zips"

YEARS = [2022, 2023, 2024, 2025]
MONTHS_2026 = range(1, 8)  # request what exists; missing months are skipped

SYMBOLS = {
    "EURUSD": "eurusd",
    "GBPUSD": "gbpusd",
    "USDJPY": "usdjpy",
    "XAUUSD": "xauusd",
    "NAS100": "nsxusd",
}

# histdata documents its timestamps as "EST no DST", but empirical alignment
# against Dukascopy UTC bars shows winter data aligns at UTC-5 and summer data
# at UTC-4 — i.e. US Eastern time WITH DST. Localize accordingly.
SOURCE_TZ = "America/New_York"


def parse_zip(path: str) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        csv_name = next(n for n in z.namelist() if n.endswith(".csv"))
        raw = z.read(csv_name)
    df = pd.read_csv(
        io.BytesIO(raw),
        sep=";",
        header=None,
        names=["ts", "open", "high", "low", "close", "volume"],
    )
    idx = (
        pd.DatetimeIndex(pd.to_datetime(df["ts"], format="%Y%m%d %H%M%S"))
        .tz_localize(SOURCE_TZ, ambiguous="NaT", nonexistent="NaT")
        .tz_convert("UTC")
    )
    df = df.drop(columns="ts")
    df.index = idx
    df.index.name = "timestamp"
    df = df[df.index.notna()]  # drop DST-transition ambiguous rows, if any
    return df


def _cached(zip_name: str) -> str | None:
    p = CACHE_DIR / zip_name
    return str(p) if p.exists() and p.stat().st_size > 0 else None


def fetch_symbol(name: str, pair: str) -> pd.DataFrame:
    frames = []
    for year in YEARS:
        p = _cached(f"DAT_ASCII_{pair.upper()}_M1_{year}.zip") or download_hist_data(
            year=year,
            pair=pair,
            platform=Platform.GENERIC_ASCII,
            time_frame=TimeFrame.ONE_MINUTE,
            output_directory=str(CACHE_DIR),
        )
        frames.append(parse_zip(p))
        print(f"  {year}: {len(frames[-1]):,} M1 bars")
    for month in MONTHS_2026:
        try:
            p = _cached(
                f"DAT_ASCII_{pair.upper()}_M1_2026{month:02d}.zip"
            ) or download_hist_data(
                year=2026,
                month=month,
                pair=pair,
                platform=Platform.GENERIC_ASCII,
                time_frame=TimeFrame.ONE_MINUTE,
                output_directory=str(CACHE_DIR),
            )
            frames.append(parse_zip(p))
            print(f"  2026-{month:02d}: {len(frames[-1]):,} M1 bars")
        except Exception as e:  # noqa: BLE001 — month not published yet
            print(f"  2026-{month:02d}: unavailable ({type(e).__name__})")
    m1 = pd.concat(frames).sort_index()
    m1 = m1[~m1.index.duplicated(keep="first")]
    m15 = (
        m1.resample("15min")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna(subset=["open", "high", "low", "close"])
    )
    return m15


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    reports, failures = [], 0
    for name, pair in SYMBOLS.items():
        print(f"[{name}] fetching histdata '{pair}' ...", flush=True)
        try:
            m15 = fetch_symbol(name, pair)
            out = OUTPUT_DIR / f"{name}_M15.parquet"
            m15.to_parquet(out, compression="zstd")
            reports.append(
                {
                    "instrument": name,
                    "status": "OK",
                    "rows": len(m15),
                    "start": m15.index.min(),
                    "end": m15.index.max(),
                    "bad_high": int(
                        (m15["high"] < m15[["open", "close"]].max(axis=1)).sum()
                    ),
                    "bad_low": int(
                        (m15["low"] > m15[["open", "close"]].min(axis=1)).sum()
                    ),
                }
            )
            print(f"[{name}] saved {len(m15):,} M15 bars -> {out}\n")
        except Exception as e:  # noqa: BLE001
            failures += 1
            reports.append({"instrument": name, "status": "FAIL", "error": str(e)})
            print(f"[{name}] FAILED: {e}\n", file=sys.stderr)
    rep = pd.DataFrame(reports)
    rep.to_csv(OUTPUT_DIR / "_quality_report.csv", index=False)
    print(rep.to_string(index=False))
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
