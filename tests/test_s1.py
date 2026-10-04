import pytest

from premium.costs import order_cost
from premium.s1 import STRUCTURES, Leg, half_spread, leg_pnl, legs_for, r50


def test_order_cost_by_hand():
    # ₹10,000 sell: brokerage 20 + exch 3.503 + SEBI 0.01 + STT 15 + GST 18% of 23.513
    assert order_cost("SELL", 100.0, 100) == pytest.approx(20 + 3.503 + 0.01 + 15 + 0.18 * 23.513)
    assert order_cost("BUY", 100.0, 100) == pytest.approx(20 + 3.503 + 0.01 + 0.3 + 0.18 * 23.513)


def test_strikes_for_each_structure():
    s1a, s1b, s1c = STRUCTURES
    assert [(lg.side, lg.strike, lg.direction) for lg in legs_for(s1a, 24_010.0)] == [
        ("CE", 24000, -1), ("PE", 24000, -1), ("CE", 24250, +1), ("PE", 23750, +1)]   # ATM fly, wings ±1% → 240 → r50
    b = legs_for(s1b, 24_000.0)
    assert [lg.strike for lg in b] == [24200, 23800, 24350, 23650]                    # ±0.75% (180→r50) / ±1.5% (360)
    c = legs_for(s1c, 24_000.0)
    assert [lg.strike for lg in c] == [24250, 23750, 24500, 23500]                     # ±1% / ±2%
    assert r50(24_024.9) == 24000 and r50(24_025.1) == 24050


def test_half_spread_floors():
    assert half_spread(400.0, True) == pytest.approx(1.0) and half_spread(20.0, True) == 0.25
    assert half_spread(400.0, False) == pytest.approx(0.6) and half_spread(20.0, False) == 0.10


def test_short_leg_pnl_by_hand():
    leg = Leg("CE", 24000, -1)                    # sold at 100, bought back at 40, half-spread 1 each side
    gross = -1 * ((40 + 1) - (100 - 1)) * 65      # = +58 × 65
    charges = order_cost("SELL", 99.0, 65) + order_cost("BUY", 41.0, 65)
    assert leg_pnl(leg, 100.0, 40.0, 1.0, 1.0) == pytest.approx(gross - charges)
    wing = Leg("CE", 24250, +1)                   # bought at 10, expired at 0.05
    assert leg_pnl(wing, 10.0, 0.05, 0.25, 0.25) < 0
    assert leg_pnl(leg, 100.0, 40.0, 1.0, 1.0, 2.0) < leg_pnl(leg, 100.0, 40.0, 1.0, 1.0)   # 2× costs is worse
