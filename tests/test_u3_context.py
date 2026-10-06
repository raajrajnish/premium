import sys
from datetime import datetime, time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import u3_context as cx  # noqa: E402
import u3_core as core  # noqa: E402


def test_day_type_rules() -> None:
    ib = (22600.0, 22500.0)                        # range 100 → trend needs ≥ 25 pts beyond the IB
    assert cx.day_type(22630, 22700, 22650, ib, -1e9, inplay=False) == "TREND-UP"           # negative gamma
    assert cx.day_type(22630, 22700, 22650, ib, +1e9, inplay=False) == "MIXED"  # positive gamma, not in play
    assert cx.day_type(22630, 22700, 22650, ib, +1e9, inplay=True) == "TREND-UP"
    assert cx.day_type(22470, 22400, 22450, ib, -1e9, inplay=False) == "TREND-DOWN"
    assert cx.day_type(22550, 22600, 22580, ib, +1e9, inplay=False) == "RANGE"
    assert cx.day_type(22550, 22600, 22580, ib, -1e9, inplay=False) == "MIXED"
    assert cx.day_type(22550, 22600, 22580, ib, -1e9, inplay=False, use_gamma=False) == "RANGE"   # noGAMMA
    assert cx.day_type(22550, 22600, 22580, None, -1e9, inplay=True) == "UNKNOWN"


def test_zone_and_option_cost() -> None:
    assert [cx.zone(time(h, m)) for h, m in ((9, 30), (10, 30), (12, 0), (14, 0), (14, 50))] == \
        ["OPEN", "MID", "LULL", "LATE", "CLOSE"]
    assert abs(cx.option_cost_pts(37.5, 10) - (1.0 + 2.0) / 0.5) < 1e-9   # 37.5/375*10 = 1.0 decay + 2.0 costs


def test_ofi_sign_follows_buying_pressure() -> None:
    f = core.Feed.__new__(core.Feed)
    f.futq = []
    t0 = datetime(2026, 10, 7, 10, 0)
    bid = 22500.0
    for k in range(120):                            # bids keep rising with size: buying pressure
        bid += 0.5
        f.futq.append((t0 + pd.Timedelta(seconds=10 * k), bid, 500.0, bid + 1, 100.0, 5000.0, 2000.0))
    o = cx.ofi_frame(f)
    assert o.depth_imb.iloc[-1] > 0
    assert o.ofi_z.dropna().size > 0
