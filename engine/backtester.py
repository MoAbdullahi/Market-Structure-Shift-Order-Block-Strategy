"""Event-driven simulation engine.

Bias-free multi-timeframe synchronization (Required Improvements 1):

The loop is driven by completed M5 candles in chronological order. H1
candles are aggregated from M5 data; the `h1_completed` event for hour H
fires only when the first M5 bar of a LATER hour arrives — i.e. strictly
after every constituent M5 bar of hour H has closed. The CRT signal is
evaluated at that moment, and M5 scanning starts with that same first M5
candle after the H1 close (it becomes MSS reference candle #1 once it
closes).

Indicator series (ATR) are precomputed but strictly causal — the value at
bar i is only consumed at or after bar i's close.

Equity accounting: mark-to-market per M5 close; position size is set at
fill time from realized equity (percent-risk sizing).
"""

from dataclasses import dataclass, field

import pandas as pd

from . import indicators
from .execution import CostModel
from .strategy import CrtStrategy, StrategyParams


@dataclass
class BacktestResult:
    symbol: str
    params: StrategyParams
    cost_model: CostModel
    initial_equity: float
    trades: list = field(default_factory=list)
    counters: object = None
    equity: pd.Series = None  # mark-to-market equity, indexed by M5 close time

    @property
    def final_equity(self) -> float:
        return float(self.equity.iloc[-1]) if len(self.equity) else self.initial_equity


class Backtester:
    def __init__(
        self,
        symbol: str,
        m5: pd.DataFrame,
        params: StrategyParams,
        cost_model: CostModel,
        initial_equity: float = 100_000.0,
    ):
        if not m5.index.is_monotonic_increasing:
            m5 = m5.sort_index()
        self.symbol = symbol
        self.m5 = m5
        self.params = params
        self.cost_model = cost_model
        self.initial_equity = initial_equity

    def run(self) -> BacktestResult:
        m5 = self.m5
        p = self.params

        atr_ltf = indicators.atr(m5, p.atr_period_ltf).to_numpy()

        # Completed-H1 aggregation (hours with no M5 data simply don't exist).
        h1 = (
            m5.resample("1h")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
            .dropna()
        )
        h1_atr = indicators.atr(h1, p.atr_period_htf)
        h1_pos = {ts: i for i, ts in enumerate(h1.index)}

        strategy = CrtStrategy(self.symbol, p, self.cost_model)

        hours = m5.index.floor("h")
        closes = m5["close"].to_numpy()
        one_hour = pd.Timedelta(hours=1)

        base_equity = self.initial_equity
        n_recorded = 0
        equity_vals = []

        prev_hour = None
        last_candle = None
        last_ts = None

        for i, candle in enumerate(m5.itertuples()):
            ts = candle.Index
            hour = hours[i]

            # --- H1 completion event: fires BEFORE this bar is processed ---
            if prev_hour is not None and hour != prev_hour:
                pos = h1_pos[prev_hour]
                if pos >= 1:
                    strategy.on_h1_close(
                        prev_candle=h1.iloc[pos - 1],
                        cur_candle=h1.iloc[pos],
                        prev_atr=float(h1_atr.iloc[pos - 1]),
                        close_time=prev_hour + one_hour,
                    )
            prev_hour = hour

            # --- intrabar: pending order fills, stop/target management ---
            strategy.on_m5_intrabar(candle, ts, equity=base_equity)

            # --- candle close: MSS tracking / OB placement ---
            strategy.on_m5_close(candle, ts, float(atr_ltf[i]))

            # --- realize equity for trades closed this bar ---
            new_trades = strategy.closed_trades[n_recorded:]
            for t in new_trades:
                base_equity += t.net_pnl
            n_recorded = len(strategy.closed_trades)

            # --- mark-to-market equity ---
            mtm = base_equity
            if strategy.active_trade is not None:
                t = strategy.active_trade
                mtm += t.net_pnl + t.unrealized_pnl(closes[i])
            equity_vals.append(mtm)

            last_candle, last_ts = candle, ts

        if last_candle is not None:
            strategy.finalize(last_candle, last_ts)
            for t in strategy.closed_trades[n_recorded:]:
                base_equity += t.net_pnl
            if equity_vals:
                equity_vals[-1] = base_equity

        return BacktestResult(
            symbol=self.symbol,
            params=p,
            cost_model=self.cost_model,
            initial_equity=self.initial_equity,
            trades=list(strategy.closed_trades),
            counters=strategy.counters,
            equity=pd.Series(
                equity_vals, index=m5.index[: len(equity_vals)], name="equity"
            ),
        )
