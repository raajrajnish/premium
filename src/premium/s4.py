"""S4 monthly factor portfolios (rules: docs/studies/2026-10-05_S4_factor_investing.md).

Input: `rets` = daily total returns (DataFrame, index = trading dates, one column per stock; NaN = not listed).
Ranked on the close of each month's last trading day; traded at the next day's close; held weights drift with
prices between rebalances; costs on the traded weight only.
"""

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

TOP_N = 10
MIN_HISTORY = 273
BUY_COST, SELL_COST = 0.0030, 0.0040

Selector = Callable[[pd.DataFrame, int], list[str]]


def eligible(rets: pd.DataFrame, i: int) -> list[str]:
    hist = rets.iloc[: i + 1]
    n = hist.notna().sum()
    return [s for s in rets.columns if n[s] >= MIN_HISTORY and not np.isnan(rets.iloc[i][s])]


def momentum_score(rets: pd.DataFrame, i: int, names: list[str]) -> pd.Series:
    """12-1 momentum: return from 252 to 21 trading days ago."""
    w = rets[names].iloc[i - 251: i - 20]
    return (1 + w.fillna(0)).prod() - 1


def vol_score(rets: pd.DataFrame, i: int, names: list[str]) -> pd.Series:
    return rets[names].iloc[i - 251: i + 1].std()


def pick(kind: str) -> Selector:
    def sel(rets: pd.DataFrame, i: int) -> list[str]:
        names = eligible(rets, i)
        if kind == "EW":
            return names
        if len(names) <= TOP_N:
            return names
        mom, vol = momentum_score(rets, i, names), vol_score(rets, i, names)
        if kind == "F1":
            score = mom.rank(ascending=False)
        elif kind == "F2":
            score = vol.rank(ascending=True)
        elif kind == "F3":
            score = (mom.rank(ascending=False) + vol.rank(ascending=True)) / 2
        else:
            raise ValueError(kind)
        return list(score.sort_values(kind="mergesort").index[:TOP_N])
    return sel


@dataclass(frozen=True)
class Result:
    equity: pd.Series          # compounding equity (start = 1.0)
    holdings: dict[pd.Timestamp, list[str]]
    turnover: float            # average one-way turnover per rebalance
    contrib: pd.Series         # cumulative contribution (sum of weight × return) per stock


def simulate(rets: pd.DataFrame, kind: str, regime: pd.Series | None = None, cost_mult: float = 1.0) -> Result:
    """regime: boolean Series (True = risk-on) evaluated on ranking days; False → 100% cash next month."""
    sel = pick(kind)
    dates = pd.DatetimeIndex(rets.index)
    month = pd.Series(dates.to_period("M"), index=dates)
    rank_days = [i for i in range(len(dates) - 1) if month.iloc[i] != month.iloc[i + 1]]
    trade_on = {i + 1: i for i in rank_days}
    w = pd.Series(0.0, index=rets.columns)
    eq, out = 1.0, []
    holdings: dict[pd.Timestamp, list[str]] = {}
    turns: list[float] = []
    contrib = pd.Series(0.0, index=rets.columns)
    r0 = rets.fillna(0.0)
    for t in range(len(dates)):
        r = r0.iloc[t]
        # positions held from the previous close earn today's return; weights drift
        gross = float((w * r).sum())
        contrib += w * r
        val = w * (1 + r)
        tot = float(val.sum()) + (1.0 - float(w.sum()))       # invested value + cash
        eq *= 1 + gross
        w = val / tot if tot > 0 else w * 0
        if t in trade_on:                                     # trade at today's close on last ranking
            i = trade_on[t]
            on = True if regime is None else bool(regime.iloc[i])
            names = sel(rets, i) if on else []
            target = pd.Series(0.0, index=rets.columns)
            if names:
                target[names] = 1.0 / len(names)
            d = target - w
            cost = float(d.clip(lower=0).sum() * BUY_COST + (-d).clip(lower=0).sum() * SELL_COST) * cost_mult
            eq *= 1 - cost
            turns.append(float(d.abs().sum() / 2))
            holdings[dates[t]] = names
            w = target
        out.append(eq)
    return Result(pd.Series(out, index=dates), holdings, float(np.mean(turns)) if turns else 0.0, contrib)


__all__ = ["Result", "simulate", "pick", "eligible", "TOP_N"]
