"""Optimization framework (Implementation Task Report §6 / Deliverables).

Every strategy parameter exposed in config/config.yaml can be searched.

Modes:
    grid         exhaustive search over `optimization.space`
    random       `optimization.n_random` uniform samples from the space
    walkforward  rolling train/test windows; the best parameter set on each
                 train window (by `optimization.objective`) is evaluated on
                 the following unseen test window
    montecarlo   bootstrap resampling of the realized R-series of a run to
                 estimate the distribution of outcomes and drawdowns

Bayesian optimization can be plugged in by sampling `space` with any external
optimizer and calling `evaluate()` — the objective function is exposed here.

Usage:
    python optimize.py --mode grid --symbols EURUSD
    python optimize.py --mode walkforward --symbols XAUUSD
    python optimize.py --mode montecarlo --symbols US30
"""

import argparse
import copy
import itertools
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from engine.analytics import compute_metrics
from engine.backtester import Backtester
from engine.execution import CostModel
from main import PROJECT_DIR, build_params, load_config, load_m5


# --------------------------------------------------------------------- #
def apply_overrides(cfg: dict, overrides: dict) -> dict:
    """Apply {'section.key': value} overrides to a copy of the config."""
    out = copy.deepcopy(cfg)
    for dotted, value in overrides.items():
        node = out
        keys = dotted.split(".")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
    return out


def evaluate(symbol: str, cfg: dict, m5: pd.DataFrame) -> dict:
    """Objective function: run one backtest, return flat result metrics."""
    params = build_params(cfg)
    cc = cfg["execution"]["instruments"][symbol]
    cost_model = CostModel(
        spread=cc["spread"],
        slippage=cc["slippage"],
        commission_per_unit_side=cc["commission_per_unit_side"],
        tick_size=cc["tick_size"],
    )
    result = Backtester(
        symbol, m5, params, cost_model, cfg["execution"]["initial_equity"]
    ).run()
    metrics = compute_metrics(result)
    tm = metrics["trade_metrics"]
    em = metrics.get("equity_metrics", {})
    return {
        "trades": tm.get("total_trades", 0),
        "win_rate": tm.get("win_rate", 0.0) if tm.get("total_trades") else 0.0,
        "expectancy_r": tm.get("expectancy_r", 0.0) if tm.get("total_trades") else 0.0,
        "profit_factor": tm.get("profit_factor", 0.0)
        if tm.get("total_trades")
        else 0.0,
        "net_profit": em.get("net_profit", 0.0),
        "max_drawdown": em.get("max_drawdown", 0.0),
        "sharpe": em.get("sharpe_ratio", 0.0),
        "_result": result,
    }


def combos_from_space(space: dict, mode: str, n_random: int, seed: int = 1):
    keys = list(space.keys())
    if mode == "grid":
        for values in itertools.product(*(space[k] for k in keys)):
            yield dict(zip(keys, values))
    else:
        rng = random.Random(seed)
        for _ in range(n_random):
            yield {k: rng.choice(space[k]) for k in keys}


# --------------------------------------------------------------------- #
def run_search(cfg, symbols, data_dir, start, end, mode, out_dir):
    opt = cfg["optimization"]
    rows = []
    for symbol in symbols:
        m5 = load_m5(data_dir, symbol, start, end)
        for overrides in combos_from_space(opt["space"], mode, opt.get("n_random", 50)):
            res = evaluate(symbol, apply_overrides(cfg, overrides), m5)
            res.pop("_result")
            rows.append({"symbol": symbol, **overrides, **res})
            print(
                f"[{symbol}] {overrides} -> trades={rows[-1]['trades']} "
                f"expR={rows[-1]['expectancy_r']:.4f} net={rows[-1]['net_profit']:.2f}"
            )
    df = pd.DataFrame(rows).sort_values(
        opt.get("objective", "expectancy_r"), ascending=False
    )
    df.to_csv(out_dir / "search_results.csv", index=False)
    print(f"\nresults -> {out_dir / 'search_results.csv'}")
    return df


def run_walkforward(cfg, symbols, data_dir, start, end, out_dir):
    opt = cfg["optimization"]
    wf = opt["walkforward"]
    objective = opt.get("objective", "expectancy_r")
    rows = []
    for symbol in symbols:
        m5 = load_m5(data_dir, symbol, start, end)
        t0, t1 = m5.index[0], m5.index[-1]
        train_len = pd.DateOffset(months=wf["train_months"])
        test_len = pd.DateOffset(months=wf["test_months"])
        window_start = t0
        w = 0
        while window_start + train_len + test_len <= t1 + pd.Timedelta(days=1):
            train_end = window_start + train_len
            test_end = train_end + test_len
            train_df = m5.loc[window_start:train_end]
            test_df = m5.loc[train_end:test_end]

            best_overrides, best_score = None, -np.inf
            for overrides in combos_from_space(opt["space"], "grid", 0):
                res = evaluate(symbol, apply_overrides(cfg, overrides), train_df)
                if res[objective] > best_score:
                    best_score, best_overrides = res[objective], overrides

            test_res = evaluate(symbol, apply_overrides(cfg, best_overrides), test_df)
            test_res.pop("_result")
            rows.append(
                {
                    "symbol": symbol,
                    "window": w,
                    "train_start": str(window_start.date()),
                    "test_start": str(train_end.date()),
                    "test_end": str(test_end.date()),
                    "best_params": json.dumps(best_overrides),
                    "train_score": best_score,
                    **{f"test_{k}": v for k, v in test_res.items()},
                }
            )
            print(
                f"[{symbol}] window {w}: {best_overrides} "
                f"train_{objective}={best_score:.4f} test_{objective}={test_res[objective]:.4f}"
            )
            window_start = window_start + test_len
            w += 1
    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "walkforward_results.csv", index=False)
    print(f"\nresults -> {out_dir / 'walkforward_results.csv'}")
    return df


def run_montecarlo(cfg, symbols, data_dir, start, end, out_dir):
    mc = cfg["optimization"].get("montecarlo", {})
    n_paths = mc.get("n_paths", 10000)
    rng = np.random.default_rng(7)
    rows = []
    for symbol in symbols:
        m5 = load_m5(data_dir, symbol, start, end)
        res = evaluate(symbol, cfg, m5)
        trades = res.pop("_result").trades
        rs = np.array([t.realized_r for t in trades])
        if len(rs) == 0:
            print(f"[{symbol}] no trades; skipping")
            continue
        totals, maxdds = np.empty(n_paths), np.empty(n_paths)
        for i in range(n_paths):
            path = rng.choice(rs, size=len(rs), replace=True)
            eq = np.cumsum(path)
            peak = np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
            maxdds[i] = float(np.max(peak - eq))
            totals[i] = float(eq[-1])
        row = {
            "symbol": symbol,
            "n_trades": len(rs),
            "expectancy_r": float(rs.mean()),
            "total_R_p5": float(np.percentile(totals, 5)),
            "total_R_p50": float(np.percentile(totals, 50)),
            "total_R_p95": float(np.percentile(totals, 95)),
            "maxDD_R_p50": float(np.percentile(maxdds, 50)),
            "maxDD_R_p95": float(np.percentile(maxdds, 95)),
            "maxDD_R_p99": float(np.percentile(maxdds, 99)),
            "prob_total_R_negative": float((totals < 0).mean()),
        }
        rows.append(row)
        print(f"[{symbol}] {row}")
    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "montecarlo_results.csv", index=False)
    print(f"\nresults -> {out_dir / 'montecarlo_results.csv'}")
    return df


# --------------------------------------------------------------------- #
def run(argv=None) -> int:
    parser = argparse.ArgumentParser(description="CRT strategy optimization")
    parser.add_argument("--config", default=str(PROJECT_DIR / "config" / "config.yaml"))
    parser.add_argument(
        "--mode",
        choices=["grid", "random", "walkforward", "montecarlo"],
        default="grid",
    )
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    args = parser.parse_args(argv)

    cfg = load_config(Path(args.config))
    data_dir = PROJECT_DIR / cfg["data"]["dir"]
    symbols = args.symbols or cfg["data"]["instruments"]
    start = args.start or cfg["data"].get("start")
    end = args.end or cfg["data"].get("end")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_DIR / cfg["output"]["dir"] / f"opt_{args.mode}_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.mode in ("grid", "random"):
        run_search(cfg, symbols, data_dir, start, end, args.mode, out_dir)
    elif args.mode == "walkforward":
        run_walkforward(cfg, symbols, data_dir, start, end, out_dir)
    else:
        run_montecarlo(cfg, symbols, data_dir, start, end, out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(run())
