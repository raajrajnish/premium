import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import u2_health as hl  # noqa: E402


def test_zigzag_finds_turns_of_at_least_threshold() -> None:
    x = np.array([0, 3, 8, 10, 7, 3, 1, 4, 9, 12], dtype=float)
    ts = pd.date_range("2026-10-07 10:00", periods=len(x), freq="10s")
    piv = hl.zigzag(x, ts, 6.0)
    assert [p[1] for p in piv] == [0.0, 10.0, 1.0, 12.0]


def test_state_thresholds() -> None:
    assert hl.state_of(0.31) == "POSITIVE" and hl.state_of(-0.31) == "NEGATIVE" and hl.state_of(0.1) == "NEUTRAL"


def test_cusum_ignores_a_normal_swing_but_alarms_on_a_sustained_drift() -> None:
    c = hl.Cusum(d=1)
    assert not any(c.update(22500 - k, 1.0, swing_pts=12.0) for k in range(0, 11))   # −10 pts: inside one swing
    c2 = hl.Cusum(d=1)
    hits = [c2.update(22500 - 2 * k, 1.0, swing_pts=12.0) for k in range(0, 15)]       # −28 pts: sustained drift
    assert any(hits)


def test_alpha_beta_tracks_a_steady_rise() -> None:
    t = np.arange(0, 300, 2.0)
    x = 22500 + 0.1 * t                                        # +6 pts/min
    v = hl.alpha_beta(x, t)
    assert abs(v[-1] - 6.0) < 0.5


def test_top_factors_sign_follows_side() -> None:
    row = pd.Series({f"z_{k}": 0.0 for k in hl.WEIGHTS} | {"z_volume": 2.0, "z_vix": -1.5})
    plus, minus = hl.top_factors(row, 1)
    assert plus[0] == "+ volume push" and minus[0] == "− VIX"
    plus_p, minus_p = hl.top_factors(row, -1)
    assert plus_p[0] == "+ VIX" and minus_p[0] == "− volume push"
