"""U3 live context (docs/U3_README.md §2): order-flow imbalance (P2), dealer-gamma regime and walls (P3),
in-play day (P4), initial balance + day type (P1), time-of-day zone (P6), implied move (P5), pendulum.
Pure functions over U3's own Feed; deterministic for a given recording."""

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import numpy as np
import pandas as pd
import u3_core as core

U2_CARD = core.ROOT / "data" / "u2"
IB_END = time(10, 15)
GAP_INPLAY, OPENVOL_X = 0.5, 1.5
TREND_EXT = 0.25                          # beyond the IB by ≥ 25% of the IB range
MIN_PER_YEAR = 252 * 375
_openvol_cache: dict[str, float | None] = {}


def zone(t: time) -> str:
    if t < time(10, 15):
        return "OPEN"
    if t < time(11, 30):
        return "MID"
    if t < time(13, 30):
        return "LULL"
    if t < time(14, 45):
        return "LATE"
    return "CLOSE"


def zigzag(x: np.ndarray, ts: Any, th: float) -> list[tuple[Any, float]]:
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


def ofi_frame(feed: core.Feed) -> pd.DataFrame:
    """Cont–Kukanov–Stoikov best-level OFI on futures quotes; 60-s sum ÷ mean top-of-book depth; z vs 30 min.
    Plus top-5 depth imbalance."""
    if len(feed.futq) < 5:
        return pd.DataFrame(columns=["ofi_z", "depth_imb"])
    q = pd.DataFrame(feed.futq, columns=["ts", "bid", "bq", "ask", "aq", "b5", "s5"]).drop_duplicates("ts", keep="last")
    q = q.set_index("ts").sort_index()
    pb, pbq, pa, paq = q.bid.shift(), q.bq.shift(), q.ask.shift(), q.aq.shift()
    e = ((q.bid >= pb) * q.bq - (q.bid <= pb) * pbq - (q.ask <= pa) * q.aq + (q.ask >= pa) * paq).fillna(0.0)
    depth = ((q.bq + q.aq) / 2).rolling("30min", min_periods=5).mean().replace(0, np.nan)
    ofi = e.rolling("60s").sum() / depth
    z = (ofi - ofi.rolling("30min", min_periods=10).mean()) / ofi.rolling("30min", min_periods=10).std()
    imb = (q.b5 - q.s5) / (q.b5 + q.s5).replace(0, np.nan)
    return pd.DataFrame({"ofi_z": z.clip(-3, 3), "depth_imb": imb})


def gamma_frame(feed: core.Feed) -> pd.DataFrame:
    rows = []
    for ts, spot, g in feed.chain_g:
        if not g:
            continue
        gex = sum((v[2] * v[0] - v[3] * v[1]) for v in g.values()) * spot * spot * 0.01
        above = {k: v[0] for k, v in g.items() if k > spot}
        below = {k: v[1] for k, v in g.items() if k < spot}
        magnet = max(g, key=lambda k: (g[k][2] * g[k][0] + g[k][3] * g[k][1]))
        atm = min(g, key=lambda k: abs(k - spot))
        iv = (g[atm][4] + g[atm][5]) / 2 if (g[atm][4] and g[atm][5]) else (g[atm][4] or g[atm][5])
        th = (abs(g[atm][6]) + abs(g[atm][7])) / 2 if len(g[atm]) > 7 else float("nan")
        rows.append({"ts": ts, "gex": gex, "call_wall": max(above, key=lambda k: above[k]) if above else None,
                     "put_wall": max(below, key=lambda k: below[k]) if below else None, "magnet": magnet,
                     "atm_iv": iv, "atm_theta": th})
    return pd.DataFrame(rows).set_index("ts") if rows else pd.DataFrame(
        columns=["gex", "call_wall", "put_wall", "magnet", "atm_iv", "atm_theta"])


def implied_move(spot: float, iv_pct: float | None, minutes: float) -> float:
    if not iv_pct:
        return float("nan")
    return spot * iv_pct / 100 * math.sqrt(minutes / MIN_PER_YEAR)


def option_cost_pts(theta_per_day: float | None, minutes: float, charges: float = 1.5, spread: float = 0.5,
                    delta: float = 0.5) -> float:
    """P5 option-cost gate (README §3): Nifty points needed to pay the option's decay over the hold + costs."""
    th = theta_per_day if theta_per_day and theta_per_day == theta_per_day else 0.0
    return (th * minutes / 375 + charges + spread) / delta


def opening_volume(day: date) -> float | None:
    """Futures volume 09:15–09:30 on a recorded day (cumulative volume difference)."""
    key = str(day)
    if key in _openvol_cache:
        return _openvol_cache[key]
    f = core.RAW / f"date={day}" / "quotes.jsonl"
    v0 = v1 = None
    if f.exists():
        with f.open(encoding="utf-8") as fh:
            for line in fh:
                if "FUT" not in line:
                    continue
                try:
                    j = json.loads(line)
                except ValueError:
                    continue
                if not str(j.get("symbol", "")).startswith("NIFTY") or j.get("volume") is None:
                    continue
                t = j["recv_ts"][11:19]
                if t >= "09:15:00" and v0 is None:
                    v0 = float(j["volume"])
                if t <= "09:30:00":
                    v1 = float(j["volume"])
                elif v0 is not None:
                    break
    out = (v1 - v0) if (v0 is not None and v1 is not None and v1 >= v0) else None
    if day < date.today():                   # only completed days are cached
        _openvol_cache[key] = out
    return out


@dataclass
class Context:
    ticks: pd.DataFrame          # per live price: nifty, ofi_z, depth_imb, gex, walls, atm_iv
    minutes: pd.DataFrame        # per completed minute: OHLC, mean20, sd20, ema20, vwap, fpx, day types per variant
    ib: tuple[float, float] | None
    gap_pct: float | None
    event_high: bool
    openvol_x: float | None
    expiry_today: bool

    def inplay(self, t: time) -> bool:
        if self.gap_pct is not None and abs(self.gap_pct) >= GAP_INPLAY:
            return True
        if self.event_high:
            return True
        return bool(t >= time(9, 30) and self.openvol_x is not None and self.openvol_x >= OPENVOL_X)


def day_type(close: float, fpx: float, vwap: float, ib: tuple[float, float] | None, gex: float | None,
             inplay: bool, use_gamma: bool = True) -> str:
    if ib is None:
        return "UNKNOWN"
    hi, lo = ib
    rng = max(hi - lo, 1.0)
    pos_gex = gex is not None and gex > 0
    neg_gex = gex is not None and gex < 0
    trend_ok = inplay or (use_gamma and neg_gex)
    if close >= hi + TREND_EXT * rng and fpx > vwap and trend_ok:
        return "TREND-UP"
    if close <= lo - TREND_EXT * rng and fpx < vwap and trend_ok:
        return "TREND-DOWN"
    if lo <= close <= hi and (pos_gex or not use_gamma):
        return "RANGE"
    return "MIXED"


def build(feed: core.Feed) -> Context:
    t = pd.DataFrame([{"ts": ts, "nifty": i.get("NSE_NIFTY")} for ts, i, _ in feed.ltp])
    t = t.drop_duplicates("ts", keep="last").set_index("ts")
    idx = pd.DatetimeIndex(t.index)
    of = ofi_frame(feed)
    gm = gamma_frame(feed)
    for col, src in (("ofi_z", of), ("depth_imb", of), ("gex", gm), ("call_wall", gm), ("put_wall", gm),
                     ("magnet", gm), ("atm_iv", gm), ("atm_theta", gm)):
        s = src[col] if col in src.columns and len(src) else pd.Series(dtype=float)
        s = s[~s.index.duplicated(keep="last")].sort_index()
        t[col] = s.reindex(s.index.union(idx)).ffill().reindex(idx) if len(s) else np.nan
    b = core.minute_frame(feed)
    b["mean20"] = b.close.rolling(20).mean()
    b["sd20"] = b.close.rolling(20).std()
    b["ema20"] = b.close.ewm(span=20, adjust=False).mean()
    first = b[b.index.time >= time(9, 15)]
    ib = None
    if len(first) and first.index[-1].time() >= IB_END:
        w = first[first.index.time < IB_END]
        ib = (float(w.high.max()), float(w.low.min())) if len(w) else None
    # gap from U2's morning card (read-only) and the first price at/after 09:15
    card_f = U2_CARD / f"{feed.day}_morning.json"
    card = json.loads(card_f.read_text(encoding="utf-8")) if card_f.exists() else {}
    open_px = next((float(i["NSE_NIFTY"]) for ts, i, _ in feed.ltp if ts.time() >= time(9, 15)), None)
    pc = card.get("prev_close")
    gap = (open_px / pc - 1) * 100 if open_px and pc else None
    prev_days = sorted(p.name[5:] for p in core.RAW.glob("date=*") if p.name[5:] < str(feed.day))[-5:]
    prev_vols = [v for v in (opening_volume(date.fromisoformat(d)) for d in prev_days) if v]
    today_vol = opening_volume(feed.day) if feed.ltp and feed.ltp[-1][0].time() >= time(9, 30) else None
    ovx = today_vol / float(np.mean(prev_vols)) if (today_vol and prev_vols) else None
    exp = None
    if feed.ltp:
        keys = [k for k in feed.ltp[-1][2] if core.OPT.match(k)]
        exps = sorted({e for e in (core.expiry_of(k) for k in keys) if e})
        exp = exps[0] if exps else None
    return Context(ticks=t, minutes=b, ib=ib, gap_pct=gap, event_high=card.get("event_risk") == "high",
                   openvol_x=ovx, expiry_today=exp == feed.day)


def pendulum(ticks: pd.DataFrame, at: datetime) -> tuple[float, float]:
    w = ticks.nifty[(ticks.index > at - timedelta(minutes=30)) & (ticks.index <= at)].dropna()
    if len(w) < 6:
        return 8.0, 90.0
    piv = zigzag(w.to_numpy(), w.index, 6.0)
    sizes = [abs(b2[1] - a[1]) for a, b2 in zip(piv, piv[1:], strict=False)]
    durs = [(b2[0] - a[0]).total_seconds() for a, b2 in zip(piv, piv[1:], strict=False)]
    return (float(np.mean(sizes)) if sizes else 8.0), (float(np.mean(durs)) if durs else 90.0)
