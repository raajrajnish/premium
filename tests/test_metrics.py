import pandas as pd
import pytest

from premium.metrics import buy_and_hold, max_drawdown_pct, monthly_returns_pct, scorecard

CAP = 100_000.0


def s(values, dates):
    return pd.Series(values, index=pd.to_datetime(dates), dtype=float)


def test_max_drawdown_by_hand():
    # equity 100k → 110k → 99k → 120k : peak 110k, trough 99k → −10%
    eq = pd.Series([110_000.0, 99_000.0, 120_000.0])
    assert max_drawdown_pct(eq, CAP) == pytest.approx(-10.0)


def test_monthly_returns_compound_on_start_of_month_equity():
    p = s([10_000, -5_500], ["2024-01-15", "2024-02-10"])
    m = monthly_returns_pct(p, CAP)
    assert m.iloc[0] == pytest.approx(10.0) and m.iloc[1] == pytest.approx(-5.0)   # −5,500 on 110,000


def test_scorecard_by_hand():
    p = s([10_000, -11_000, 21_000, -1_000, 2_000, 4_000],
          ["2024-01-10", "2024-02-10", "2024-03-10", "2024-04-10", "2024-05-10", "2025-01-10"])
    sc = scorecard(p, CAP)
    assert sc.trades == 6 and sc.total_return_pct == pytest.approx(25.0)
    assert sc.max_drawdown_pct == pytest.approx(-10.0)                 # 110k → 99k
    assert sc.worst_trade_pct == pytest.approx(-11.0)
    assert sc.worst_5_consecutive_pct == pytest.approx(15.0)            # windows: +21k and +15k → worst +15k
    assert sc.negative_months_pct == pytest.approx(100 * 2 / 6, abs=0.1)
    years = (pd.Timestamp("2025-01-10") - pd.Timestamp("2024-01-10")).days / 365.25
    assert sc.cagr_pct == pytest.approx((1.25 ** (1 / years) - 1) * 100, abs=0.01)
    assert sc.calmar == pytest.approx(round(sc.cagr_pct / 10.0, 2))


def test_buy_and_hold_benchmark():
    c = s([100.0, 110.0, 99.0, 121.0], ["2024-01-01", "2024-06-01", "2024-09-01", "2025-01-01"])
    sc = buy_and_hold(c, CAP)
    assert sc.total_return_pct == pytest.approx(21.0) and sc.max_drawdown_pct == pytest.approx(-10.0)


def test_empty():
    assert scorecard(pd.Series(dtype=float), CAP).trades == 0
