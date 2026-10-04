"""S3 trend-following engine (rules: docs/studies/2026-10-04_S3_trend_following.md, implementation notes there).

Conventions:
- Each market is a daily series of returns `r` plus the bar's high/low as a fraction of the close.
  Signals use a synthetic price index C = cumprod(1 + r), so spot, futures and stitched series look alike.
- The direction is decided at close t and traded at close t+1, so the weight decided at t earns r from t+2 on.
- Weight = direction × min(target_vol / σ60, cap) / N, where N = markets warmed up on that date.
- Costs: |Δweight| × side_cost on the trade day, plus a roll round trip (2 × side_cost × |weight|) on each
  market's first trading day of a month.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

TARGET_VOL = 0.10
LEV_CAP = 2.0
RULES = ("T1", "T2", "T3")


@dataclass(frozen=True)
class Market:
    name: str
    bars: pd.DataFrame        # index: date; columns r, hi, lo (hi/lo = high/close, low/close of the bar)
    side_cost: float          # fraction of notional per side (charges + slippage)


def atr_pct(bars: pd.DataFrame, n: int = 20) -> pd.Series:
    """ATR(n) as a fraction of the close, from returns and high/low fractions (true range uses the prev close)."""
    prev = 1.0 / (1.0 + bars["r"])                       # previous close relative to today's close
    tr = pd.concat([bars["hi"] - bars["lo"], (bars["hi"] - prev).abs(), (bars["lo"] - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def directions(rule: str, bars: pd.DataFrame) -> pd.Series:
    """Target direction (+1/0/−1) decided at each close, with the 2×ATR(20) stop for T1/T2."""
    c = (1.0 + bars["r"]).cumprod()
    atr = atr_pct(bars) * c
    out = np.zeros(len(c))
    if rule == "T3":
        ret12 = c / c.shift(252) - 1.0
        month_end = pd.Series(c.index, index=c.index).dt.to_period("M")
        last = month_end != month_end.shift(-1)
        d = 0.0
        for i in range(len(c)):
            if last.iloc[i] and not np.isnan(ret12.iloc[i]):
                d = float(np.sign(ret12.iloc[i]))
            out[i] = d
        return pd.Series(out, index=c.index)

    if rule == "T1":
        hi55, lo55 = c.shift(1).rolling(55).max(), c.shift(1).rolling(55).min()
        hi20, lo20 = c.shift(1).rolling(20).max(), c.shift(1).rolling(20).min()
        long_sig, short_sig = (c > hi55).to_numpy(), (c < lo55).to_numpy()
    elif rule == "T2":
        diff = c.rolling(50).mean() - c.rolling(200).mean()
        s = pd.Series(np.sign(diff), index=diff.index)
        cross = (s != s.shift(1)) & diff.notna() & diff.shift(1).notna()
        long_sig, short_sig = ((s > 0) & cross).to_numpy(), ((s < 0) & cross).to_numpy()
        trend = s.fillna(0).to_numpy()
    else:
        raise ValueError(rule)

    d, entry, stop_dist, started = 0.0, 0.0, 0.0, False
    cv, av = c.to_numpy(), atr.to_numpy()
    for i in range(len(cv)):
        if np.isnan(av[i]):
            out[i] = 0.0
            continue
        if rule == "T2" and not started and trend[i] != 0:   # first warm day: take the prevailing trend
            started, d, entry, stop_dist = True, float(trend[i]), cv[i], 2.0 * av[i]
        else:
            stopped = d != 0 and (cv[i] - entry) * d <= -stop_dist          # hard stop: flat until a fresh signal
            channel = rule == "T1" and ((d > 0 and cv[i] < lo20.iloc[i]) or (d < 0 and cv[i] > hi20.iloc[i]))
            if stopped or channel:
                d = 0.0
        if long_sig[i] and d <= 0:
            d, entry, stop_dist = 1.0, cv[i], 2.0 * av[i]
        elif short_sig[i] and d >= 0:
            d, entry, stop_dist = -1.0, cv[i], 2.0 * av[i]
        out[i] = d
    return pd.Series(out, index=c.index)


@dataclass(frozen=True)
class Run:
    daily: pd.Series          # portfolio return per day after costs (fraction of capital)
    gross: pd.Series          # before costs
    weights: pd.DataFrame     # executed weights (already /N)
    entries: pd.Series        # count of new non-zero directions per market


def run(rule: str, markets: list[Market], cost_mult: float = 1.0) -> Run:
    cal = sorted(set().union(*[m.bars.index for m in markets]))
    idx = pd.DatetimeIndex(cal)
    dirs, sizes, rets, side = {}, {}, {}, {}
    for m in markets:
        b = m.bars.copy()
        b.index = pd.DatetimeIndex(b.index)
        dr = directions(rule, b)
        vol = b["r"].rolling(60).std() * np.sqrt(252)
        warm = vol.notna() & (b["r"].expanding().count() >= 260)
        size = (TARGET_VOL / vol).clip(upper=LEV_CAP).where(warm)
        dirs[m.name] = dr.reindex(idx).ffill().fillna(0.0)
        sizes[m.name] = size.reindex(idx).ffill()
        rets[m.name] = b["r"].reindex(idx).fillna(0.0)
        side[m.name] = m.side_cost * cost_mult
    D, S, R = pd.DataFrame(dirs), pd.DataFrame(sizes), pd.DataFrame(rets)
    n = S.notna().sum(axis=1).replace(0, np.nan)
    target = (D * S.fillna(0.0)).div(n, axis=0).fillna(0.0)       # decided at close t
    w = target.shift(1).fillna(0.0)                                # executed at close t+1
    gross = (w.shift(1).fillna(0.0) * R).sum(axis=1)               # earns from t+2
    sc = pd.Series(side)
    trade_cost = (w.diff().abs().fillna(w.abs()) * sc).sum(axis=1)
    months = pd.Series(idx.to_period("M"), index=idx)
    first_of_month = months != months.shift(1)
    roll_cost = (w.shift(1).fillna(0.0).abs() * 2 * sc).sum(axis=1).where(first_of_month, 0.0)
    entries = ((D != 0) & (D.shift(1) != D) & S.notna()).sum()
    return Run(daily=gross - trade_cost - roll_cost, gross=gross, weights=w, entries=entries)


__all__ = ["Market", "Run", "RULES", "atr_pct", "directions", "run"]
