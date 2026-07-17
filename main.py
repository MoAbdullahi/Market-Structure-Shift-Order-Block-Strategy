"""Configuration and execution entry point.

Usage:
    python main.py                          # run all configured instruments
    python main.py --symbols EURUSD XAUUSD  # subset
    python main.py --config config/config.yaml --start 2023-01-01 --end 2024-01-01

Outputs (per run, under reports/<timestamp>/):
    <SYMBOL>_metrics.json   full analytics
    <SYMBOL>_trades.csv     one row per closed trade
    <SYMBOL>_equity.csv     mark-to-market equity curve (M5 resolution)
    summary.json / summary.txt  combined overview
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from engine.analytics import compute_metrics
from engine.backtester import Backtester
from engine.execution import CostModel
from engine.strategy import StrategyParams

PROJECT_DIR = Path(__file__).resolve().parent


def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def build_params(cfg: dict) -> StrategyParams:
    ind = cfg["indicator"]
    ent = cfg["entry"]
    rsk = cfg["risk"]
    ses = cfg["session"]
    return StrategyParams(
        atr_period_htf=ind["atr_period_htf"],
        atr_period_ltf=ind["atr_period_ltf"],
        min_atr_ratio=ind["min_atr_ratio"],
        stop_buffer_atr=ind["stop_buffer_atr"],
        ob_pricing=ent["ob_pricing"],
        pending_lifetime=ent["pending_lifetime"],
        mss_lookback=ent["mss_lookback"],
        reference_candle_count=ent["reference_candle_count"],
        partial_fractions=tuple(rsk["partial_fractions"]),
        first_rr=rsk["first_rr"],
        second_rr=rsk["second_rr"],
        intrabar_priority=rsk["intrabar_priority"],
        move_stop_to_breakeven_after=rsk["move_stop_to_breakeven_after"],
        trail_stop_to_1r_after=rsk["trail_stop_to_1r_after"],
        risk_pct=rsk["risk_pct"],
        min_r_cost_multiple=rsk.get("min_r_cost_multiple", 0.0),
        session_enabled=ses["enabled"],
        session_windows=tuple(tuple(w) for w in ses["windows"]),
        news_blackouts=tuple(tuple(w) for w in ses["news_blackouts"]),
        strong_filter=ses["strong_filter"],
        pd_filter=ses["pd_filter"],
    )


def load_m5(data_dir: Path, symbol: str, start=None, end=None) -> pd.DataFrame:
    df = pd.read_parquet(data_dir / f"{symbol}_M5.parquet")
    df = df.sort_index()
    if start:
        df = df.loc[pd.Timestamp(start, tz="UTC") :]
    if end:
        df = df.loc[: pd.Timestamp(end, tz="UTC")]
    return df


def trades_to_frame(trades) -> pd.DataFrame:
    rows = []
    for t in trades:
        rows.append(
            {
                "symbol": t.symbol,
                "direction": t.direction,
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "entry_raw": t.entry_raw,
                "entry_fill": t.entry_fill,
                "stop_initial": t.stop_initial,
                "target": t.target,
                "r_dist": t.r_dist,
                "qty": t.qty,
                "risk_amount": t.risk_amount,
                "net_pnl": t.net_pnl,
                "realized_r": t.realized_r,
                "bars_in_trade": t.bars_in_trade,
                "commission": t.commission_paid,
                "spread_cost": t.spread_cost,
                "slippage_cost": t.slippage_cost,
                "n_legs": len(t.legs),
                "exit_reasons": "|".join(leg.reason for leg in t.legs),
            }
        )
    return pd.DataFrame(rows)


def run(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CRT + MSS + Order Block backtester")
    parser.add_argument("--config", default=str(PROJECT_DIR / "config" / "config.yaml"))
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)

    cfg = load_config(Path(args.config))
    params = build_params(cfg)
    data_dir = PROJECT_DIR / cfg["data"]["dir"]
    symbols = args.symbols or cfg["data"]["instruments"]
    start = args.start or cfg["data"].get("start")
    end = args.end or cfg["data"].get("end")
    initial_equity = cfg["execution"]["initial_equity"]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = (
        Path(args.output) if args.output else PROJECT_DIR / cfg["output"]["dir"] / stamp
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "run": stamp,
        "start": start,
        "end": end,
        "params": vars(params) | {},
        "symbols": {},
    }

    for symbol in symbols:
        cost_cfg = cfg["execution"]["instruments"][symbol]
        cost_model = CostModel(
            spread=cost_cfg["spread"],
            slippage=cost_cfg["slippage"],
            commission_per_unit_side=cost_cfg["commission_per_unit_side"],
            tick_size=cost_cfg["tick_size"],
        )
        m5 = load_m5(data_dir, symbol, start, end)
        print(
            f"[{symbol}] {len(m5)} M5 bars {m5.index[0]} -> {m5.index[-1]} ... ",
            end="",
            flush=True,
        )

        result = Backtester(symbol, m5, params, cost_model, initial_equity).run()
        metrics = compute_metrics(result)

        with open(out_dir / f"{symbol}_metrics.json", "w", encoding="utf-8") as fh:
            json.dump(metrics, fh, indent=2, default=str)
        trades_to_frame(result.trades).to_csv(
            out_dir / f"{symbol}_trades.csv", index=False
        )
        result.equity.to_csv(out_dir / f"{symbol}_equity.csv")

        tm = metrics["trade_metrics"]
        em = metrics.get("equity_metrics", {})
        summary["symbols"][symbol] = {
            "trades": tm.get("total_trades", 0),
            "win_rate": round(tm.get("win_rate", 0.0), 4)
            if tm.get("total_trades")
            else 0.0,
            "expectancy_r": round(tm.get("expectancy_r", 0.0), 4)
            if tm.get("total_trades")
            else 0.0,
            "profit_factor": tm.get("profit_factor"),
            "net_profit": round(em.get("net_profit", 0.0), 2),
            "max_drawdown": round(em.get("max_drawdown", 0.0), 2),
            "sharpe": round(em.get("sharpe_ratio", 0.0), 3),
        }
        print(
            f"trades={tm.get('total_trades', 0)} "
            f"win_rate={summary['symbols'][symbol]['win_rate']} "
            f"exp_R={summary['symbols'][symbol]['expectancy_r']} "
            f"net={summary['symbols'][symbol]['net_profit']}"
        )

    with open(out_dir / "summary.json", "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)

    lines = [
        "CRT + Market Structure Shift + Order Block — backtest summary",
        f"run: {stamp}  window: {start or 'data start'} -> {end or 'data end'}",
        "",
        f"{'symbol':<8} {'trades':>7} {'win%':>7} {'expR':>8} {'PF':>7} {'net':>12} {'maxDD':>12} {'sharpe':>7}",
    ]
    for sym, s in summary["symbols"].items():
        pf = s["profit_factor"]
        pf_str = (
            f"{pf:.2f}"
            if isinstance(pf, (int, float)) and pf != float("inf")
            else "inf"
        )
        lines.append(
            f"{sym:<8} {s['trades']:>7} {s['win_rate'] * 100:>6.2f}% {s['expectancy_r']:>8.3f} "
            f"{pf_str:>7} {s['net_profit']:>12.2f} {s['max_drawdown']:>12.2f} {s['sharpe']:>7.3f}"
        )
    text = "\n".join(lines)
    with open(out_dir / "summary.txt", "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print("\n" + text)
    print(f"\nreports written to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
