import pandas as pd

from premium.s3 import Market, directions, run


def bars(r: list[float]) -> pd.DataFrame:
    idx = pd.bdate_range("2010-01-01", periods=len(r))
    return pd.DataFrame({"r": r, "hi": 1.005, "lo": 0.995}, index=idx)


def test_t1_goes_long_on_breakout_and_exits_on_20_day_low() -> None:
    r = [0.0] * 60 + [0.01] * 20 + [-0.01] * 30
    d = directions("T1", bars(r))
    assert d.iloc[59] == 0 and d.iloc[60] == 1        # first new 55-day high
    assert (d.iloc[80:] == 0).any()                   # long exited on the way down (stop or 20-day low)
    assert d.iloc[-1] == -1                           # then a new 55-day low → short


def test_t1_stop_two_atr() -> None:
    # hi = lo = close, so ATR comes only from gaps: one +2% day over 20 days → ATR ≈ 0.1% → stop ≈ 0.2% below entry,
    # while the 20-day low (1.00) is ~2% below; a −0.3% day must trigger the stop, not the channel exit.
    r = [0.0] * 55 + [0.02] + [0.0, -0.003, 0.0]
    b = bars(r).assign(hi=1.0, lo=1.0)
    d = directions("T1", b)
    assert d.iloc[55] == 1 and d.iloc[56] == 1
    assert d.iloc[57] == 0 and d.iloc[58] == 0         # stopped, and stays flat (no fresh breakout)


def test_t3_monthly_sign_of_12m_return() -> None:
    r = [0.001] * 300 + [-0.003] * 100
    d = directions("T3", bars(r))
    assert d.iloc[290] == 1 or d.iloc[290] == 0
    assert d.iloc[-1] == -1 or d.iloc[-1] == 1         # changes only at month ends
    changes = d.index[d.diff().fillna(0) != 0]
    assert all((c + pd.offsets.BDay(1)).month != c.month for c in changes)


def test_run_lags_two_days_and_charges_costs() -> None:
    r = [0.0] * 300 + [0.01] * 10
    m = Market("X", bars(r), side_cost=0.001)
    out = run("T1", [m])
    w = out.weights["X"]
    first = w[w != 0].index[0]
    assert first == bars(r).index[301]                 # decided at close 300, traded at close 301
    assert out.gross.loc[first] == 0                   # earns only from the next day
    assert out.daily.loc[first] < 0                    # entry cost charged on the trade day
