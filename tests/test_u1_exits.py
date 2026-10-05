import sys
from datetime import datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from u1_exits import Ctx, Leg, step  # noqa: E402

T0 = datetime(2026, 10, 6, 10, 0, 0)


def ctx(sec: float, spot: float, bid: float, **kw: object) -> Ctx:
    base = {"bar_close": None, "bar_ema9": None, "opposite": False, "feed_gap": False, "hard": time(15, 10),
            "near_exp": False}
    return Ctx(ts=T0 + timedelta(seconds=sec), spot=spot, bid=bid, **(base | kw))  # type: ignore[arg-type]


def leg(model: str, L: float = 0.20) -> Leg:
    return Leg(model=model, dir=1, spot0=22500.0, px0=100.0, t0=T0, stop_c=22490.0, L=L)


def test_ec2_loss_limit_and_lock_in_floor() -> None:
    a = leg("EC2")
    assert step(a, ctx(10, 22500, 81)) is None                 # −19%: inside the 20% loss limit
    assert step(a, ctx(20, 22500, 79.9)) == "loss limit"
    b = leg("EC2")
    for s, px in ((10, 110), (20, 130), (30, 140)):             # peak +40% → floor 75% of 40% = +30%
        assert step(b, ctx(s, 22520, px)) is None
    assert step(b, ctx(40, 22520, 131)) is None
    assert step(b, ctx(50, 22520, 129.5)) == "floor"


def test_ec2_lock_in_never_below_15() -> None:
    a = leg("EC2")
    step(a, ctx(10, 22510, 116))                               # peak +16% → floor max(15%, 12%) = 15%
    assert step(a, ctx(20, 22510, 115.5)) is None
    assert step(a, ctx(30, 22510, 114.9)) == "floor"


def test_ec2plus_breakeven_and_10s_confirmation() -> None:
    a = leg("EC2P", L=0.10)
    step(a, ctx(10, 22510, 109))                               # +9% → loss level moves to +1.5%
    assert step(a, ctx(20, 22505, 101)) is None                # below the level, confirmation starts
    assert step(a, ctx(25, 22505, 101)) is None                # 5 s
    assert step(a, ctx(31, 22505, 101)) == "breakeven"         # ≥ 10 s


def test_ec1_breakeven_after_plus_six_and_stop() -> None:
    a = leg("EC1")
    assert step(a, ctx(10, 22507, 104)) is None                # +7 pts → stop moves to entry
    assert step(a, ctx(20, 22499.5, 99)) == "C breakeven"
    b = leg("EC1")
    assert step(b, ctx(10, 22488, 95)) == "A stop"              # −12 pts


def test_ec0_signal_candle_stop() -> None:
    a = leg("EC0")
    assert step(a, ctx(10, 22495, 98)) is None
    assert step(a, ctx(20, 22489, 96)) == "stop"
