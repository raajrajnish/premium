"""The one scorecard every premium approach is judged on (docs/DESIGN.md: "How every approach is judged")."""

import math
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Scorecard:
    start: str
    end: str
    trades: int
    total_return_pct: float
    cagr_pct: float
    max_drawdown_pct: float
    calmar: float | None
    worst_month_pct: float
    negative_months_pct: float
    sharpe_monthly: float | None
    worst_trade_pct: float
    worst_5_consecutive_pct: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def equity_curve(pnl: pd.Series, capital: float) -> pd.Series:
    """pnl: ₹ per trade, indexed by exit date (sorted). Returns equity after each trade."""
    return capital + pnl.sort_index().cumsum()


def max_drawdown_pct(equity: pd.Series, capital: float) -> float:
    eq = pd.concat([pd.Series([capital]), equity.reset_index(drop=True)], ignore_index=True)
    peak = eq.cummax()
    return float(((eq / peak) - 1).min() * 100)


def monthly_returns_pct(pnl: pd.Series, capital: float) -> pd.Series:
    """Month-by-month % return on start-of-month equity (pnl indexed by exit timestamps)."""
    p = pnl.sort_index()
    by_month = p.groupby(pd.to_datetime(p.index).to_period("M")).sum()
    out, eq = [], capital
    for v in by_month:
        out.append(v / eq * 100)
        eq += v
    return pd.Series(out, index=by_month.index, dtype=float)


def scorecard(pnl: pd.Series, capital: float) -> Scorecard:
    """pnl: ₹ per closed trade indexed by exit date/timestamp; capital: starting ₹ (no compounding of size)."""
    p = pnl.dropna().sort_index()
    if p.empty:
        return Scorecard("", "", 0, 0.0, 0.0, 0.0, None, 0.0, 0.0, None, 0.0, 0.0)
    idx = pd.to_datetime(p.index)
    years = max((idx.max() - idx.min()).days / 365.25, 1 / 365.25)
    eq = equity_curve(p, capital)
    total = (eq.iloc[-1] / capital - 1) * 100
    cagr = ((eq.iloc[-1] / capital) ** (1 / years) - 1) * 100 if eq.iloc[-1] > 0 else -100.0
    mdd = max_drawdown_pct(eq, capital)
    m = monthly_returns_pct(p, capital)
    sharpe = float(m.mean() / m.std() * math.sqrt(12)) if len(m) >= 3 and m.std() > 0 else None
    worst5 = float(p.rolling(5).sum().min() / capital * 100) if len(p) >= 5 else float(p.sum() / capital * 100)
    return Scorecard(
        start=str(idx.min().date()), end=str(idx.max().date()), trades=len(p), total_return_pct=round(total, 2),
        cagr_pct=round(cagr, 2), max_drawdown_pct=round(mdd, 2),
        calmar=round(cagr / abs(mdd), 2) if mdd < 0 else None, worst_month_pct=round(float(m.min()), 2),
        negative_months_pct=round(float((m < 0).mean() * 100), 1),
        sharpe_monthly=round(sharpe, 2) if sharpe is not None else None,
        worst_trade_pct=round(float(p.min() / capital * 100), 2), worst_5_consecutive_pct=round(worst5, 2))


def buy_and_hold(closes: pd.Series, capital: float) -> Scorecard:
    """Benchmark: invest `capital` at the first close, mark to market daily (closes indexed by date)."""
    c = closes.dropna().sort_index()
    pnl = (c / c.iloc[0] * capital - capital).diff().fillna(0.0)
    pnl.index = c.index
    return scorecard(pnl[pnl.index > c.index[0]], capital) if len(c) > 1 else scorecard(pd.Series(dtype=float),
                                                                                         capital)


__all__ = ["Scorecard", "scorecard", "buy_and_hold", "max_drawdown_pct", "monthly_returns_pct", "np"]
