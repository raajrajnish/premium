import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import u4_features as fx  # noqa: E402
import u4_watch as w  # noqa: E402


def test_micro_price_leans_to_heavier_side() -> None:
    assert fx.micro_price(100.0, 900.0, 101.0, 100.0) > 100.5      # big bid queue → closer to the ask
    assert fx.micro_price(100.0, 100.0, 101.0, 900.0) < 100.5


def test_hawkes_mle_prefers_clustering_for_clustered_events() -> None:
    rng = np.random.default_rng(1)
    clustered = sorted({round(float(c + rng.exponential(2.0)), 2) for c in range(0, 3600, 120) for _ in range(15)})
    uniform = sorted(rng.uniform(0, 3600, len(clustered)).round(2).tolist())
    fc = fx.fit_hawkes([(clustered, 3600.0)])
    fu = fx.fit_hawkes([(uniform, 3600.0)])
    assert fc["n"] > fu["n"]
    assert fc["alpha"] / fc["beta"] < 1                             # stability


def test_kalman_spread_flags_a_dislocation() -> None:
    n = 900
    idx = pd.date_range("2026-10-07 09:15", periods=n, freq="10s")
    rng = np.random.default_rng(0)
    bn = 55000 * np.exp(np.cumsum(rng.normal(0, 2e-4, n)))
    nifty = 22500 * (bn / 55000) ** 0.9 * np.exp(rng.normal(0, 5e-5, n))
    nifty[700:720] *= 1.004                                         # Nifty suddenly rich vs its basket
    g = pd.DataFrame({"nifty": nifty, "bn": bn, "hdfc": bn / 78, "icici": bn / 41}, index=idx)
    ks = fx.kalman_spread(g)
    assert ks.spread_z.iloc[705:720].max() >= 2


def test_yang_zhang_positive_and_kelly_sign() -> None:
    idx = pd.date_range("2026-10-07 10:00", periods=1800, freq="2s")
    rng = np.random.default_rng(3)
    s = pd.Series(22500 + np.cumsum(rng.normal(0, 0.8, len(idx))), index=idx)
    sig = fx.yang_zhang_sigma1m(s, idx[-1])
    assert sig > 0 and math.isfinite(sig)
    assert w.kelly([100, 100, 100, -50, -50, 100]) > 0
    assert w.kelly([-100, -100, -100, 50, 50, -100]) < 0
    assert w.kelly([1, 2]) is None
