"""U1 challenger exits (docs/U1_README.md §7): EC0 champion, EC1 Nifty-points rulebook, EC2 owner's premium-% trail,
EC2P = EC2 + five additions. Pure decision logic: the watcher feeds one Ctx per live tick to every open Leg."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta

LOT, CHARGES = 65, 1.5
MODELS_V1 = ("EC0",)
MODELS_V3 = ("EC0", "EC1", "EC2", "EC2P")


@dataclass
class Ctx:
    ts: datetime
    spot: float
    bid: float | None              # option mark: bid, or last price − 0.5
    bar_close: float | None        # set only on the tick that completes a 1-min bar
    bar_ema9: float | None
    opposite: bool                 # the other side's checklist fully valid at that completed bar
    feed_gap: bool                 # > 60 s since the previous Nifty price
    hard: time                     # 15:10, or 14:45 on expiry day (EC1/EC2/EC2P)
    near_exp: bool                 # expiry day or the day before


@dataclass
class Leg:
    model: str
    dir: int
    spot0: float
    px0: float
    t0: datetime
    stop_c: float                  # signal-candle stop (EC0)
    L: float = 0.20                # EC2P loss limit (volatility-adjusted at entry)
    peak_pts: float = 0.0
    peak_pct: float = 0.0
    spike: bool = False
    since: datetime | None = None
    opt_bad_since: datetime | None = None
    last_bid: float | None = None
    exit_ts: datetime | None = None
    exit_px: float | None = None
    reason: str | None = None

    @property
    def open(self) -> bool:
        return self.reason is None

    def pnl(self, px: float | None = None) -> int | None:
        p = self.exit_px if px is None else px
        return None if p is None else round((p - self.px0 - CHARGES) * LOT)


def _time_rules(leg: Leg, el: float, c: Ctx) -> str | None:
    noprog, mx = (5, 12) if c.near_exp else (8, 20)
    if el >= noprog and leg.peak_pts < 6:
        return "F no progress"
    if el >= mx:
        return "G max hold"
    return None


def _ec0(leg: Leg, c: Ctx, el: float) -> str | None:
    if leg.dir * (c.spot - leg.stop_c) < 0:
        return "stop"
    if c.bar_close is not None and c.bar_ema9 is not None and leg.dir * (c.bar_close - c.bar_ema9) < 0:
        return "trail"
    if el >= 15:
        return "time"
    if c.ts.time() >= time(15, 10):
        return "15:10"
    return None


def _ec1(leg: Leg, c: Ctx, el: float, gain: float) -> str | None:
    if c.feed_gap:
        return "K feed"
    if c.ts.time() >= c.hard:
        return "J hard"
    if leg.peak_pts >= 15 and el <= 2:
        leg.spike = True
    if c.bid is not None and (c.bid - leg.px0 - CHARGES) * LOT <= -600:
        return "B max loss"
    stop = -12.0 if leg.peak_pts < 6 else 0.0
    if gain <= stop:
        return "A stop" if stop < 0 else "C breakeven"
    if leg.spike and gain <= 0.75 * leg.peak_pts:
        return "E spike lock"
    if leg.peak_pts >= 10 and gain <= 0.5 * leg.peak_pts:
        return "D keep 50%"
    if gain >= 6 and c.bid is not None and c.bid <= leg.px0:
        leg.opt_bad_since = leg.opt_bad_since or c.ts
        if c.ts - leg.opt_bad_since >= timedelta(minutes=2):
            return "H option lag"
    else:
        leg.opt_bad_since = None
    if c.opposite:
        return "I reversal"
    return _time_rules(leg, el, c)


def _ec2(leg: Leg, c: Ctx, el: float, plus: bool) -> str | None:
    if c.feed_gap:
        return "K feed"
    if c.ts.time() >= c.hard:
        return "J hard"
    if c.opposite:
        return "I reversal"
    if c.bid is not None:
        pct = c.bid / leg.px0 - 1
        if plus:
            loss = leg.L / 2 if (el > 5 and leg.peak_pct < 0.08) else leg.L
            lvl = CHARGES / leg.px0 if leg.peak_pct >= 0.08 else -loss
        else:
            lvl = -0.20
        floor = None
        if leg.peak_pct >= 0.15:
            keep = (0.75 if leg.peak_pct < 0.40 else 0.80 if leg.peak_pct < 0.80 else 0.85) if plus else 0.75
            floor = max(0.15, leg.peak_pct * keep)
        breach = pct <= floor if floor is not None else pct <= lvl
        why = "floor" if floor is not None else ("breakeven" if lvl > 0 else "loss limit")
        if plus:
            if breach:
                leg.since = leg.since or c.ts
                if c.ts - leg.since >= timedelta(seconds=10):
                    return why
            else:
                leg.since = None
        elif breach:
            return why
        leg.peak_pct = max(leg.peak_pct, pct)       # peak updated after the check (cautious)
    return _time_rules(leg, el, c)


def step(leg: Leg, c: Ctx) -> str | None:
    """Advance one open leg by one live tick; returns the exit reason, or None to stay in."""
    gain = leg.dir * (c.spot - leg.spot0)
    leg.peak_pts = max(leg.peak_pts, gain)
    el = (c.ts - leg.t0).total_seconds() / 60
    if leg.model == "EC0":
        return _ec0(leg, c, el)
    if leg.model == "EC1":
        return _ec1(leg, c, el, gain)
    return _ec2(leg, c, el, plus=leg.model == "EC2P")
