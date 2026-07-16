"""Performance analytics (Required Improvements 5).

Computes the trade, equity, risk, and execution metric groups specified in
the Implementation Task Report from a BacktestResult.
"""

import math

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def compute_metrics(result) -> dict:
    trades = result.trades
    equity = result.equity
    counters = result.counters

    metrics = {
        "symbol": result.symbol,
        "initial_equity": result.initial_equity,
    }
    metrics["trade_metrics"] = _trade_metrics(trades)
    metrics["equity_metrics"] = _equity_metrics(equity, result.initial_equity)
    metrics["risk_metrics"] = _risk_metrics(trades)
    metrics["execution_metrics"] = _execution_metrics(trades, counters)
    return metrics


# --------------------------------------------------------------------- #
def _trade_metrics(trades) -> dict:
    n = len(trades)
    if n == 0:
        return {"total_trades": 0}

    pnls = np.array([t.net_pnl for t in trades])
    rs = np.array([t.realized_r for t in trades])
    wins = pnls > 0
    losses = pnls <= 0
    n_win = int(wins.sum())
    n_loss = int(losses.sum())

    holding = [t.exit_time - t.entry_time for t in trades if t.exit_time is not None]
    bars = [t.bars_in_trade for t in trades]

    gross_profit = float(pnls[wins].sum()) if n_win else 0.0
    gross_loss = float(pnls[losses].sum()) if n_loss else 0.0

    return {
        "total_trades": n,
        "winning_trades": n_win,
        "losing_trades": n_loss,
        "win_rate": n_win / n,
        "average_win": float(pnls[wins].mean()) if n_win else 0.0,
        "average_loss": float(pnls[losses].mean()) if n_loss else 0.0,
        "average_r": float(rs.mean()),
        "largest_win": float(pnls.max()),
        "largest_loss": float(pnls.min()),
        "expectancy_r": float(rs.mean()),
        "expectancy_currency": float(pnls.mean()),
        "profit_factor": (gross_profit / abs(gross_loss))
        if gross_loss < 0
        else math.inf,
        "average_holding_time": str(sum(holding, pd.Timedelta(0)) / len(holding))
        if holding
        else None,
        "maximum_holding_time": str(max(holding)) if holding else None,
        "average_bars_in_trade": float(np.mean(bars)) if bars else 0.0,
    }


# --------------------------------------------------------------------- #
def _equity_metrics(equity: pd.Series, initial_equity: float) -> dict:
    if equity is None or len(equity) == 0:
        return {}

    net_profit = float(equity.iloc[-1] - initial_equity)
    returns_series = equity.pct_change().fillna(0.0)

    # profits split
    diffs = equity.diff().dropna()
    gross_profit = float(diffs[diffs > 0].sum())
    gross_loss = float(diffs[diffs < 0].sum())

    # drawdown
    peak = equity.cummax()
    dd = equity - peak
    dd_pct = dd / peak
    max_dd = float(-dd.min())
    max_dd_pct = float(-dd_pct.min())

    # longest drawdown duration (time between a peak and its recovery)
    at_peak = equity >= peak
    dd_duration = pd.Timedelta(0)
    start = None
    for ts, is_peak in at_peak.items():
        if is_peak:
            if start is not None:
                dd_duration = max(dd_duration, ts - start)
                start = None
        elif start is None:
            start = ts
    if start is not None:
        dd_duration = max(dd_duration, equity.index[-1] - start)

    daily = equity.resample("1D").last().dropna()
    daily_ret = daily.pct_change().dropna()
    sharpe = _annualized_ratio(daily_ret, daily_ret.std(ddof=1))
    downside = daily_ret[daily_ret < 0].std(ddof=1)
    sortino = _annualized_ratio(daily_ret, downside)

    monthly = equity.resample("1ME").last().pct_change().dropna()
    yearly = equity.resample("1YE").last().pct_change().dropna()

    return {
        "net_profit": net_profit,
        "net_profit_pct": net_profit / initial_equity,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "max_drawdown": max_dd,
        "max_drawdown_pct": max_dd_pct,
        "drawdown_duration": str(dd_duration),
        "return_over_drawdown": (net_profit / max_dd) if max_dd > 0 else math.inf,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "recovery_factor": (net_profit / max_dd) if max_dd > 0 else math.inf,
        "monthly_returns": {str(k.date()): float(v) for k, v in monthly.items()},
        "yearly_returns": {str(k.year): float(v) for k, v in yearly.items()},
    }


def _annualized_ratio(daily_ret: pd.Series, denom) -> float:
    if len(daily_ret) < 2 or denom is None or not np.isfinite(denom) or denom == 0:
        return 0.0
    return float(daily_ret.mean() / denom * math.sqrt(TRADING_DAYS_PER_YEAR))


# --------------------------------------------------------------------- #
def _risk_metrics(trades) -> dict:
    if not trades:
        return {}

    pnls = [t.net_pnl for t in trades]
    max_consec_wins = max_consec_losses = cur_w = cur_l = 0
    for pnl in pnls:
        if pnl > 0:
            cur_w += 1
            cur_l = 0
        else:
            cur_l += 1
            cur_w = 0
        max_consec_wins = max(max_consec_wins, cur_w)
        max_consec_losses = max(max_consec_losses, cur_l)

    risks = [t.risk_amount for t in trades]
    rewards = [t.net_pnl for t in trades if t.net_pnl > 0]
    stop_dists = [abs(t.entry_raw - t.stop_initial) for t in trades]
    target_dists = [abs(t.target - t.entry_raw) for t in trades]
    nominal_rr = [td / sd for td, sd in zip(target_dists, stop_dists) if sd > 0]

    return {
        "max_consecutive_losses": max_consec_losses,
        "max_consecutive_wins": max_consec_wins,
        "average_risk": float(np.mean(risks)),
        "average_reward": float(np.mean(rewards)) if rewards else 0.0,
        "average_rr": float(np.mean(nominal_rr)) if nominal_rr else 0.0,
        "average_stop_distance": float(np.mean(stop_dists)),
        "average_target_distance": float(np.mean(target_dists)),
    }


# --------------------------------------------------------------------- #
def _execution_metrics(trades, counters) -> dict:
    n = len(trades)
    total_commission = sum(t.commission_paid for t in trades)
    total_spread = sum(t.spread_cost for t in trades)
    total_slippage = sum(t.slippage_cost for t in trades)
    out = {
        "average_slippage_cost": (total_slippage / n) if n else 0.0,
        "average_spread_cost": (total_spread / n) if n else 0.0,
        "commission_paid": float(total_commission),
        "total_spread_cost": float(total_spread),
        "total_slippage_cost": float(total_slippage),
    }
    if counters is not None:
        out.update(
            {
                "crt_triggers": counters.crt_triggers,
                "canceled_pending_orders": counters.canceled_pending,
                "expired_setups": counters.expired_setups,
                "missed_entries": counters.missed_entries,
                "invalidated_mss": counters.invalidated_mss,
                "session_filtered": counters.session_filtered,
                "entries_filled": counters.entries_filled,
            }
        )
    return out
