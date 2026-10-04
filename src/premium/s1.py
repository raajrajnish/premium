"""S1: defined-risk option selling on Nifty weekly options (spec: docs/studies/2026-10-04_S1_defined_risk_selling.md).
Paper research only. Rules copied from the pre-declaration; nothing is tuned.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd

from premium.costs import order_cost
from premium.data import Snapshot, option_symbol

LOT = 65
EXIT_BAR = time(15, 9)       # the bar that closes at 15:10


@dataclass(frozen=True)
class Structure:
    id: str
    entry_time: time
    short_pct: float          # 0 = ATM (iron butterfly)
    wing_pct: float
    days_before_expiry: int   # 0 = enter on expiry day, 1 = previous trading day


STRUCTURES = (
    Structure("S1a", time(13, 30), 0.0, 0.010, 0),
    Structure("S1b", time(9, 30), 0.0075, 0.015, 0),
    Structure("S1c", time(14, 30), 0.010, 0.020, 1),
)


@dataclass(frozen=True)
class Leg:
    side: str                 # CE / PE
    strike: int
    direction: int            # +1 bought (wing), −1 sold (short)


def r50(x: float) -> int:
    return int(round(x / 50) * 50)


def legs_for(s: Structure, spot: float) -> list[Leg]:
    sc, sp = r50(spot * (1 + s.short_pct)), r50(spot * (1 - s.short_pct))
    wc, wp = r50(spot * (1 + s.wing_pct)), r50(spot * (1 - s.wing_pct))
    return [Leg("CE", sc, -1), Leg("PE", sp, -1), Leg("CE", wc, +1), Leg("PE", wp, +1)]


def half_spread(price: float, expiry_day: bool) -> float:
    return max(0.0025 * price, 0.25) if expiry_day else max(0.0015 * price, 0.10)


def leg_pnl(leg: Leg, p_open: float, p_close: float, hs_open: float, hs_close: float, mult: float = 1.0) -> float:
    """Net ₹ for one leg (1 lot): spread paid on both sides, charges on both orders; mult scales both (2× costs)."""
    d = leg.direction
    open_fill = p_open + d * hs_open * mult
    close_fill = p_close - d * hs_close * mult
    gross = d * (close_fill - open_fill) * LOT
    charges = order_cost("BUY" if d > 0 else "SELL", open_fill, LOT) + order_cost("SELL" if d > 0 else "BUY",
                                                                                close_fill, LOT)
    return gross - charges * mult


def bar_open_at(df: pd.DataFrame, t: datetime, within_min: int = 3) -> float | None:
    s = df[df["ts"] >= pd.Timestamp(t)]
    if s.empty or (s["ts"].iloc[0] - pd.Timestamp(t)) > timedelta(minutes=within_min):
        return None
    return float(s["open"].iloc[0])


def bar_close_at(df: pd.DataFrame, t: datetime, within_min: int = 3) -> float | None:
    s = df[df["ts"] <= pd.Timestamp(t)]
    if s.empty or (pd.Timestamp(t) - s["ts"].iloc[-1]) > timedelta(minutes=within_min):
        return None
    return float(s["close"].iloc[-1])


def spot_before(idx_day: pd.DataFrame, t: time) -> float | None:
    s = idx_day[idx_day["ts"].dt.time < t]
    return float(s["close"].iloc[-1]) if len(s) else None


def eligible(snap: Snapshot, start: date, end: date) -> Iterator[tuple[Structure, date, date]]:
    """(structure, entry day, expiry) for every expiry in [start, end]."""
    days = sorted(set(pd.to_datetime(snap.con.execute(
        "SELECT DISTINCT CAST(ts AS DATE) FROM candles WHERE symbol='NSE-NIFTY' AND interval='1minute'").df()
        .iloc[:, 0]).dt.date))
    for exp in snap.expiries("NIFTY"):
        if not (start <= exp <= end) or exp not in days:
            continue
        i = days.index(exp)
        for s in STRUCTURES:
            if i - s.days_before_expiry >= 0:
                yield s, days[i - s.days_before_expiry], exp


def simulate(snap: Snapshot, s: Structure, entry_day: date, exp: date) -> dict[str, Any]:
    """One position. Returns a row with status OK or SKIP_<reason> (never filled from missing data)."""
    row: dict[str, Any] = {"structure": s.id, "entry_day": entry_day, "expiry": exp}
    idx = snap.candles("NSE-NIFTY", "1minute", datetime.combine(entry_day, time(9, 15)),
                       datetime.combine(entry_day, time(15, 30)))
    spot = spot_before(idx, s.entry_time)
    if spot is None:
        return row | {"status": "SKIP_NO_SPOT"}
    legs = legs_for(s, spot)
    t_in, t_out = datetime.combine(entry_day, s.entry_time), datetime.combine(exp, EXIT_BAR)
    prices: list[tuple[float, float]] = []
    for leg in legs:
        sym = option_symbol("NIFTY", exp, leg.strike, leg.side)
        df = snap.candles(sym, "1minute", datetime.combine(entry_day, time(9, 15)), datetime.combine(exp, time(15, 30)))
        po, pc = bar_open_at(df, t_in), bar_close_at(df, t_out)
        if po is None or pc is None:
            return row | {"status": f"SKIP_NO_DATA_{leg.side}{leg.strike}", "spot": spot}
        prices.append((po, pc))
    exp_idx = idx if exp == entry_day else snap.candles("NSE-NIFTY", "1minute", datetime.combine(exp, time(9, 15)),
                                                        datetime.combine(exp, time(15, 30)))
    spot_out = bar_close_at(exp_idx, t_out)
    credit = sum(-leg.direction * po for leg, (po, _) in zip(legs, prices, strict=True))
    width = max(legs[2].strike - legs[0].strike, legs[1].strike - legs[3].strike)
    max_loss = (width - credit) * LOT
    hs_in = [half_spread(po, s.days_before_expiry == 0) for _, (po, _) in zip(legs, prices, strict=True)]
    hs_out = [half_spread(pc, True) for _, (_, pc) in zip(legs, prices, strict=True)]
    net = sum(leg_pnl(leg, po, pc, hi, ho) for leg, (po, pc), hi, ho in zip(legs, prices, hs_in, hs_out, strict=True))
    net2 = sum(leg_pnl(leg, po, pc, hi, ho, 2.0)
               for leg, (po, pc), hi, ho in zip(legs, prices, hs_in, hs_out, strict=True))
    return row | {"status": "OK", "spot": spot, "spot_exit": spot_out,
                  "move_pct": None if spot_out is None else round((spot_out / spot - 1) * 100, 3),
                  "strikes": "/".join(f"{lg.direction:+d}{lg.side}{lg.strike}" for lg in legs),
                  "credit_pts": round(credit, 2), "width_pts": width, "max_loss_inr": round(max_loss, 0),
                  "margin_inr": round(max_loss * 1.1, 0), "net_inr": round(net, 1), "net2_inr": round(net2, 1),
                  "exit_ts": t_out}
