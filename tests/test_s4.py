import numpy as np
import pandas as pd

from premium.s4 import BUY_COST, simulate


def frame(n_days: int = 320, n: int = 12) -> pd.DataFrame:
    idx = pd.bdate_range("2010-01-01", periods=n_days)
    rng = np.random.default_rng(0)
    r = pd.DataFrame(rng.normal(0, 0.01, (n_days, n)), index=idx, columns=[f"S{i}" for i in range(n)])
    r["S0"] = 0.004                    # steady winner, low vol
    r["S1"] = rng.normal(0, 0.05, n_days)  # very volatile
    return r


def test_momentum_holds_winner_and_lowvol_avoids_volatile() -> None:
    r = frame()
    f1 = simulate(r, "F1")
    f2 = simulate(r, "F2")
    h1 = [h for h in f1.holdings.values() if h]       # rebalances before the 273-day warm-up hold nothing
    h2 = [h for h in f2.holdings.values() if h]
    assert h1 and h2
    assert all("S0" in h for h in h1) and all("S1" not in h for h in h2)
    assert all(len(h) == 10 for h in h1)


def test_no_trades_before_history_and_regime_off_is_cash() -> None:
    r = frame()
    off = pd.Series(False, index=r.index)
    res = simulate(r, "F1", regime=off)
    assert all(h == [] for h in res.holdings.values())
    assert res.equity.iloc[-1] == 1.0                 # all cash, no cost


def test_entry_cost_charged_once_and_one_day_lag() -> None:
    r = frame()
    r[:] = 0.0
    res = simulate(r, "EW")
    first = min(d for d, h in res.holdings.items() if h)
    assert res.equity.loc[first] == 1 - BUY_COST     # full entry at one-way buy cost
    assert res.equity.iloc[-1] < 1 - BUY_COST + 1e-12  # later rebalances cost nothing with zero drift
