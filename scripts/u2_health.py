"""U2 health engine (docs/U2_README.md §3): factors on every live price, normalised against their own last 30 minutes,
combined into one smoothed health score per side, plus the live pendulum and the in-trade CUSUM alarm.
Pure functions over U2's own Feed; deterministic for a given recording."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd
import u2_core as core

Z_WIN, CLIP, HALF_LIFE = "30min", 3.0, "15s"
THETA = 0.30                                   # POSITIVE ≥ +θ, NEGATIVE ≤ −θ (v0.1 starting value)
CONT = ["mom30", "mom60", "speed", "heavy", "vix", "volume", "book", "vwap", "oi"]
WEIGHTS = {**{k: 1.0 for k in CONT}, "trend": 2.0, "trigger": 1.0}
NAMES = {"mom30": "momentum 30s", "mom60": "momentum 60s", "speed": "trend speed", "heavy": "heavyweights",
         "vix": "VIX", "volume": "volume push", "book": "order book", "vwap": "futures vs VWAP", "oi": "options OI",
         "trend": "trend structure", "trigger": "trigger"}


def _lag(s: pd.Series, secs: int) -> pd.Series:
    """Value of s at (t − secs), as of the last observation at or before that time."""
    shifted = pd.Series(s.to_numpy(), index=s.index + pd.Timedelta(seconds=secs))
    return shifted.reindex(s.index, method="ffill")


def _asof(src: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
    src = src[~src.index.duplicated(keep="last")].sort_index()
    return src.reindex(src.index.union(idx)).ffill().reindex(idx)


def alpha_beta(x: np.ndarray, t: np.ndarray, alpha: float = 0.3, beta: float = 0.02) -> np.ndarray:
    """Kalman-style alpha–beta tracker: smoothed velocity of Nifty in pts/min (t in seconds)."""
    lvl, vel = x[0], 0.0
    out = np.zeros(len(x))
    for k in range(1, len(x)):
        dt = max(t[k] - t[k - 1], 1e-3)
        pred = lvl + vel * dt
        r = x[k] - pred
        lvl = pred + alpha * r
        vel = vel + beta * r / dt
        out[k] = vel * 60
    return out


def minute_structure(feed: core.Feed, b: pd.DataFrame) -> pd.DataFrame:
    """Per completed 1-min bar: Gate-1 components for both sides, the signal side, and exhaustion signs."""
    rows = []
    for i in range(len(b) - 1):                # the last bar is still forming
        if i < 26:
            continue
        cu, cd = core.components(b, i, feed, 1), core.components(b, i, feed, -1)
        sig = core.evaluate(b, i, feed)
        r, b3 = b.iloc[i], b.iloc[i - 3]
        vol_x = float(r.fvol / r.fvol_avg20) if r.fvol_avg20 else np.nan
        hi5, lo5 = b.high.iloc[i - 5:i].max(), b.low.iloc[i - 5:i].min()
        exh = {}
        for d in (1, -1):
            rsi_d = r.rsi if d > 0 else 100 - r.rsi
            against = sum(d * (r[x] - b3[x]) < 0 for x in ("bn", "hdfc", "icici")) >= 2
            newext = (r.high > hi5) if d > 0 else (r.low < lo5)
            exh[d] = bool(rsi_d > 80 or against or (vol_x >= 2.5 and not newext))
        rows.append({"minute": b.index[i], "done": b.index[i] + timedelta(minutes=1), "i": i,
                     "up": cu, "dn": cd, "sig": sig if (sig and sig["confirmations"] >= 3) else None,
                     "exh_up": exh[1], "exh_dn": exh[-1]})
    return pd.DataFrame(rows)


def oi_shift(feed: core.Feed, b: pd.DataFrame, ms: pd.DataFrame) -> pd.Series:
    vals = []
    for _, m in ms.iterrows():
        now, then = feed.oi_at(m.done), feed.oi_at(m.done - timedelta(minutes=5))
        atm = int(round(b.close.iloc[m.i] / 50) * 50)
        v = np.nan
        if now and then and atm in now and atm in then:
            v = ((now[atm][1] - then[atm][1]) - (now[atm][0] - then[atm][0])) / 1000
        vals.append(v)
    return pd.Series(vals, index=pd.DatetimeIndex(ms.done))


@dataclass
class Health:
    ticks: pd.DataFrame          # per live price: raw, z, health_up (raw), health (smoothed, + = good for CALL)
    minutes: pd.DataFrame        # per completed minute: components, signal, exhaustion
    pendulum: pd.DataFrame       # per completed minute: swing pts, swing secs (last 30 min)
    tick_sigma: pd.Series        # std of tick-to-tick Nifty changes over the last 30 min


def build(feed: core.Feed) -> Health:
    t = pd.DataFrame([{"ts": ts, "nifty": i.get("NSE_NIFTY"), "bn": i.get("NSE_BANKNIFTY"),
                       "hdfc": i.get("NSE_HDFCBANK"), "icici": i.get("NSE_ICICIBANK"), "vix": i.get("NSE_INDIAVIX")}
                      for ts, i, _ in feed.ltp]).drop_duplicates("ts", keep="last").set_index("ts").ffill()
    idx = pd.DatetimeIndex(t.index)
    b = core.minute_frame(feed)
    ms = minute_structure(feed, b)
    raw = pd.DataFrame(index=idx)
    raw["mom30"] = t.nifty - _lag(t.nifty, 30)
    raw["mom60"] = t.nifty - _lag(t.nifty, 60)
    secs = (idx - idx[0]).total_seconds().to_numpy()
    raw["speed"] = alpha_beta(t.nifty.to_numpy(), secs)
    raw["heavy"] = sum((t[c] / _lag(t[c], 60) - 1) * 1e4 for c in ("bn", "hdfc", "icici"))
    raw["vix"] = -(t.vix - _lag(t.vix, 60))
    if feed.fut:
        f = pd.DataFrame(feed.fut, columns=["ts", "px", "cum"]).drop_duplicates("ts", keep="last").set_index("ts")
        cum = _asof(f.cum, idx)
        v60 = (cum - _lag(cum, 60)).clip(lower=0)
        avg = v60.rolling(Z_WIN, min_periods=10).mean()
        raw["volume"] = (v60 / avg.replace(0, np.nan) - 1) * np.sign(raw["mom60"])
        vw = b["vwap"].copy()
        vw.index = vw.index + timedelta(minutes=1)          # VWAP of a completed minute
        gap = _asof(f.px, idx) - _asof(vw, idx)
        raw["vwap"] = gap - _lag(gap, 60)
    else:
        raw["volume"] = raw["vwap"] = np.nan
    if feed.fut_ob:
        o = pd.DataFrame(feed.fut_ob, columns=["ts", "tb", "ts_q"]).drop_duplicates("ts", keep="last").set_index("ts")
        lr = np.log(o.tb / o.ts_q)
        lr_t = _asof(lr, idx)
        raw["book"] = lr_t - lr_t.rolling(Z_WIN, min_periods=10).mean()
    else:
        raw["book"] = np.nan
    raw["oi"] = _asof(oi_shift(feed, b, ms), idx) if len(ms) else np.nan
    if len(ms):
        keys = ("vwap", "ema_order", "ema_slope")
        recs = ms.to_dict("records")
        tr = pd.Series([(sum(m["up"][k] for k in keys) - sum(m["dn"][k] for k in keys)) / 3 for m in recs],
                       index=pd.DatetimeIndex(ms.done))
        tg = pd.Series([int(m["up"]["trigger"]) - int(m["dn"]["trigger"]) for m in ms.to_dict("records")],
                       index=pd.DatetimeIndex(ms.done))
        raw["trend"], raw["trigger"] = _asof(tr, idx).fillna(0.0), _asof(tg, idx).fillna(0.0)
    else:
        raw["trend"] = raw["trigger"] = 0.0
    z = pd.DataFrame(index=idx)
    for k in CONT:
        m = raw[k].rolling(Z_WIN, min_periods=30).mean()
        s = raw[k].rolling(Z_WIN, min_periods=30).std().replace(0, np.nan)
        z[k] = ((raw[k] - m) / s).clip(-CLIP, CLIP).fillna(0.0)
    z["trend"], z["trigger"] = raw["trend"], raw["trigger"]
    wsum = sum(WEIGHTS.values())
    hu = sum(WEIGHTS[k] * z[k] for k in WEIGHTS) / wsum
    sm = hu.ewm(halflife=pd.Timedelta(HALF_LIFE), times=idx).mean()
    ticks = pd.concat([t, raw.add_prefix("raw_"), z.add_prefix("z_")], axis=1)
    ticks["health_up_raw"], ticks["health"] = hu, sm
    dn = t.nifty.diff()
    sigma = dn.rolling(Z_WIN, min_periods=30).std().bfill().fillna(1.0)
    # pendulum per completed minute (last 30 min of ticks, 6-pt turning points)
    pend = []
    for _, m in ms.iterrows():
        w = t.nifty[(idx > m.done - timedelta(minutes=30)) & (idx <= m.done)]
        piv = zigzag(w.to_numpy(), w.index, 6.0) if len(w) > 5 else []
        sizes = [abs(b2[1] - a[1]) for a, b2 in zip(piv, piv[1:], strict=False)]
        durs = [(b2[0] - a[0]).total_seconds() for a, b2 in zip(piv, piv[1:], strict=False)]
        pend.append({"done": m.done, "swing_pts": float(np.mean(sizes)) if sizes else 8.0,
                     "swing_secs": float(np.mean(durs)) if durs else 90.0})
    pdf = pd.DataFrame(pend).set_index("done") if pend else pd.DataFrame(columns=["swing_pts", "swing_secs"])
    return Health(ticks=ticks, minutes=ms, pendulum=pdf, tick_sigma=sigma)


def zigzag(x: np.ndarray, ts: Any, th: float) -> list[tuple[Any, float]]:
    """Turning points: a turn is confirmed once price reverses by th from the running extreme."""
    piv, d, ext = [(ts[0], float(x[0]))], 0, (ts[0], float(x[0]))
    for t_, v in zip(ts, x, strict=False):
        v = float(v)
        if d == 0:
            if abs(v - piv[0][1]) >= th:
                d, ext = (1 if v > piv[0][1] else -1), (t_, v)
        elif d == 1:
            if v >= ext[1]:
                ext = (t_, v)
            elif ext[1] - v >= th:
                piv.append(ext)
                d, ext = -1, (t_, v)
        else:
            if v <= ext[1]:
                ext = (t_, v)
            elif v - ext[1] >= th:
                piv.append(ext)
                d, ext = 1, (t_, v)
    piv.append(ext)
    return piv


def state_of(h: float) -> str:
    return "POSITIVE" if h >= THETA else ("NEGATIVE" if h <= -THETA else "NEUTRAL")


def top_factors(z_row: pd.Series, d: int, n: int = 3) -> tuple[list[str], list[str]]:
    contrib = {k: d * WEIGHTS[k] * float(z_row[f"z_{k}"]) for k in WEIGHTS}
    s = sorted(contrib.items(), key=lambda kv: kv[1])
    plus = [f"+ {NAMES[k]}" for k, v in reversed(s) if v > 0.05][:n]
    minus = [f"− {NAMES[k]}" for k, v in s if v < -0.05][:n]
    return plus, minus


class Cusum:
    """One-sided CUSUM on adverse Nifty tick moves (README §3): alarm at max(5σ, one live swing)."""

    def __init__(self, d: int, k: float = 0.5, h: float = 5.0) -> None:
        self.d, self.k, self.h, self.s, self.last = d, k, h, 0.0, None

    def update(self, nifty: float, sigma: float, swing_pts: float = 0.0) -> bool:
        """Alarm level = max(5σ, one live swing): a normal swing against us must never trigger it."""
        if self.last is not None:
            adverse = -self.d * (nifty - self.last)
            self.s = max(0.0, self.s + adverse - self.k * sigma)
        self.last = nifty
        return self.s >= max(self.h * sigma, swing_pts)
