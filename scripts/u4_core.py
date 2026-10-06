"""U4 core: U4's OWN copy of the live feed reader, 1-min indicators and the checklist (taken 2026-10-06 from
U3's core), so that changes to U1–U3 never change U4. Rules: docs/U4_README.md.
Has the futures book, chain gamma/IV and (U4) option top-5 depth. Reads the recorder's files read-only."""

import bisect
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT.parent / "suzlon" / "data" / "raw"
OUT = ROOT / "data" / "u4"
LOT, CHARGES = 65, 1.5
START, LAST_ENTRY, HARD = time(9, 45), time(14, 30), time(15, 10)
MAX_TRADES, PAUSE_MIN, TIME_STOP_MIN = 4, 5, 15
# TESTING PHASE (owner, 2026-10-05): the daily trade cap is OFF from this moment on (README §4).
# Signals before it keep the cap, so the morning's recorded trades stay unchanged.
CAP_OFF_FROM: datetime | None = datetime(2026, 10, 5, 11, 25)
V3_FROM = date(2026, 10, 6)
MONTH = {**{str(i): i for i in range(1, 10)}, "O": 10, "N": 11, "D": 12}
WALL_RANGE, ROOM_OK, SPREAD_OK = 300, 25.0, 1.0
OPT = re.compile(r"NSE_NIFTY(\d\d[A-Z0-9]\d\d)(\d{5})(CE|PE)$")


def version(day: date) -> str:
    return "v3" if day >= V3_FROM else "v1"


def expiry_of(key: str) -> date | None:
    """Weekly option key NSE_NIFTY26O0622550CE → 2026-10-06 (month code 1–9, O, N, D)."""
    m = OPT.match(key)
    if not m:
        return None
    s = m.group(1)
    try:
        return date(2000 + int(s[:2]), MONTH[s[2]], int(s[3:5]))
    except (KeyError, ValueError):
        return None


class Tail:
    """Parse only complete new lines of a file another process is appending to."""

    def __init__(self, path: Path) -> None:
        self.path, self.pos = path, 0

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open("rb") as f:
            f.seek(self.pos)
            chunk = f.read()
        end = chunk.rfind(b"\n")
        if end < 0:
            return []
        self.pos += end + 1
        out = []
        for line in chunk[:end].decode("utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out


def ts_of(j: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(j["recv_ts"]).replace(tzinfo=None)


@dataclass
class Feed:
    day: date
    ltp: list[tuple[datetime, dict[str, float], dict[str, float]]] = field(default_factory=list)
    fut: list[tuple[datetime, float, float]] = field(default_factory=list)          # ts, price, cum volume
    fut_ob: list[tuple[datetime, float, float]] = field(default_factory=list)       # ts, total buy, total sell
    quotes: dict[str, tuple[list[datetime], list[tuple[float, float]]]] = field(default_factory=dict)
    chain: list[tuple[datetime, dict[int, tuple[float, float]]]] = field(default_factory=list)  # strike→(CE OI, PE OI)
    # U3: futures book (ts, bid, bid_qty, ask, ask_qty, top-5 buy qty, top-5 sell qty)
    futq: list[tuple[datetime, float, float, float, float, float, float]] = field(default_factory=list)
    # U3: chain snapshot (ts, underlying, {strike: (ce_oi, pe_oi, ce_g, pe_g, ce_iv, pe_iv, ce_theta, pe_theta)})
    chain_g: list[tuple[datetime, float, dict[int, tuple[float, ...]]]] = field(default_factory=list)
    # U4: futures 5-level book (ts, [(bid_px, bid_qty)*5], [(ask_px, ask_qty)*5]) for multi-level OFI
    futl: list[tuple[datetime, list[tuple[float, float]], list[tuple[float, float]]]] = field(default_factory=list)
    # U4: option top-5 depth per key: key -> list of (ts, buy5, sell5)
    optbook: dict[str, list[tuple[datetime, float, float]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        d = RAW / f"date={self.day}"
        self.t_ltp, self.t_q, self.t_c = Tail(d / "ltp.jsonl"), Tail(d / "quotes.jsonl"), Tail(d / "chain.jsonl")

    def update(self) -> None:
        for j in self.t_ltp.read():
            if (j.get("index") or {}).get("NSE_NIFTY"):
                self.ltp.append((ts_of(j), j["index"], j.get("fno") or {}))
        for j in self.t_q.read():
            s = j.get("symbol", "")
            if s.endswith("FUT") and s.startswith("NIFTY") and j.get("volume") is not None:
                self.fut.append((ts_of(j), float(j["ltp"]), float(j["volume"])))
                if j.get("total_buy_qty") and j.get("total_sell_qty"):
                    self.fut_ob.append((ts_of(j), float(j["total_buy_qty"]), float(j["total_sell_qty"])))
                if j.get("bid") and j.get("ask"):
                    dp = j.get("depth") or {}
                    b5 = sum(float(x.get("quantity") or 0) for x in dp.get("buy") or [])
                    s5 = sum(float(x.get("quantity") or 0) for x in dp.get("sell") or [])
                    self.futq.append((ts_of(j), float(j["bid"]), float(j.get("bid_qty") or 0), float(j["ask"]),
                                      float(j.get("ask_qty") or 0), b5, s5))
                    lv_b = [(float(x.get("price") or 0), float(x.get("quantity") or 0)) for x in (dp.get("buy") or [])]
                    lv_s = [(float(x.get("price") or 0), float(x.get("quantity") or 0)) for x in (dp.get("sell") or [])]
                    if len(lv_b) == 5 and len(lv_s) == 5:
                        self.futl.append((ts_of(j), lv_b, lv_s))
            elif j.get("bid") and j.get("ask"):
                ts_list, vals = self.quotes.setdefault("NSE_" + s, ([], []))
                ts_list.append(ts_of(j))
                vals.append((float(j["bid"]), float(j["ask"])))
                dp = j.get("depth") or {}
                b5 = sum(float(x.get("quantity") or 0) for x in dp.get("buy") or [])
                s5 = sum(float(x.get("quantity") or 0) for x in dp.get("sell") or [])
                if b5 + s5 > 0:
                    self.optbook.setdefault("NSE_" + s, []).append((ts_of(j), b5, s5))
        for j in self.t_c.read():
            oi = {}
            for k, v in (j.get("strikes") or {}).items():
                ce, pe = (v.get("CE") or {}).get("open_interest"), (v.get("PE") or {}).get("open_interest")
                if ce is not None and pe is not None:
                    oi[int(float(k))] = (float(ce), float(pe))
            self.chain.append((ts_of(j), oi))
            full: dict[int, tuple[float, ...]] = {}
            for k, v in (j.get("strikes") or {}).items():
                ce, pe = v.get("CE") or {}, v.get("PE") or {}
                gc, gp = (ce.get("greeks") or {}), (pe.get("greeks") or {})
                if ce.get("open_interest") is not None and pe.get("open_interest") is not None:
                    full[int(float(k))] = (float(ce["open_interest"]), float(pe["open_interest"]),
                                           float(gc.get("gamma") or 0), float(gp.get("gamma") or 0),
                                           float(gc.get("iv") or 0), float(gp.get("iv") or 0),
                                           float(gc.get("theta") or 0), float(gp.get("theta") or 0))
            if j.get("underlying_ltp"):
                self.chain_g.append((ts_of(j), float(j["underlying_ltp"]), full))

    def quote(self, key: str, at: datetime) -> tuple[float, float] | None:
        q = self.quotes.get(key)
        if not q:
            return None
        i = bisect.bisect_right(q[0], at) - 1
        if i < 0 or at - q[0][i] > timedelta(seconds=60):
            return None
        return q[1][i]

    def oi_at(self, at: datetime) -> dict[int, tuple[float, float]] | None:
        times = [c[0] for c in self.chain]
        i = bisect.bisect_right(times, at) - 1
        return self.chain[i][1] if i >= 0 else None


def minute_frame(feed: Feed) -> pd.DataFrame:
    """1-min bars (spot OHLC + last VIX/BN/HDFC/ICICI) and futures volume / VWAP per completed minute."""
    t = pd.DataFrame([{"ts": ts, "nifty": i.get("NSE_NIFTY"), "vix": i.get("NSE_INDIAVIX"),
                       "bn": i.get("NSE_BANKNIFTY"), "hdfc": i.get("NSE_HDFCBANK"), "icici": i.get("NSE_ICICIBANK")}
                      for ts, i, _ in feed.ltp]).set_index("ts")
    b = t["nifty"].resample("1min").ohlc()
    for c in ("vix", "bn", "hdfc", "icici"):
        b[c] = t[c].resample("1min").last()
    if feed.fut:
        f = pd.DataFrame(feed.fut, columns=["ts", "px", "cum"]).set_index("ts")
        f["dv"] = f["cum"].diff().clip(lower=0).fillna(0.0)
        b["fvol"] = f["dv"].resample("1min").sum()
        b["fpx"] = f["px"].resample("1min").last()
        pv = (f["px"] * f["dv"]).resample("1min").sum().cumsum()
        vv = f["dv"].resample("1min").sum().cumsum()
        b["vwap"] = (pv / vv.replace(0, np.nan)).reindex(b.index).ffill()
    else:
        b["fvol"] = b["fpx"] = b["vwap"] = np.nan
    b = b.dropna(subset=["close"]).ffill()
    c = b["close"]
    b["ema9"], b["ema21"] = c.ewm(span=9, adjust=False).mean(), c.ewm(span=21, adjust=False).mean()
    mid, sd = c.rolling(20).mean(), c.rolling(20).std(ddof=0)
    b["bb_up"], b["bb_lo"], b["bw"] = mid + 2 * sd, mid - 2 * sd, 4 * sd / mid
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 7, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 7, adjust=False).mean()
    b["rsi"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    macd = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    b["macdh"] = macd - macd.ewm(span=9, adjust=False).mean()
    b["fvol_avg20"] = b["fvol"].shift(1).rolling(20).mean()
    c3 = c.resample("3min", origin="start_day", offset="9h15min").last().dropna()
    e9, e21 = c3.ewm(span=9, adjust=False).mean(), c3.ewm(span=21, adjust=False).mean()
    done = c3.index + pd.Timedelta(minutes=2)            # the 1-min bar at whose close the 3-min candle is complete
    f3 = pd.DataFrame({"ema9_3": e9.to_numpy(), "ema21_3": e21.to_numpy(), "ema9_3_prev": e9.shift(1).to_numpy()},
                      index=done)
    f3 = f3[f3.index <= b.index[-1]]
    if len(f3):
        b = b.join(f3.reindex(b.index, method="ffill"))
    else:
        b["ema9_3"] = b["ema21_3"] = b["ema9_3_prev"] = np.nan
    return b


def components(b: pd.DataFrame, i: int, feed: Feed, d: int, ver: str = "v3") -> dict[str, Any]:
    """Every U1 condition for direction d (+1 CALL, -1 PUT) at completed bar i (needs i >= 26).
    v2: EMA order and slope come from completed 3-min candles; everything else is unchanged."""
    r, p, p5, b3 = b.iloc[i], b.iloc[i - 1], b.iloc[i - 5], b.iloc[i - 3]
    prev5 = b.iloc[i - 5:i]
    above_vwap = bool(d * (r.fpx - r.vwap) > 0)
    if ver != "v1":
        ema_order = bool(d * (r.ema9_3 - r.ema21_3) > 0)
        ema_slope = bool(d * (r.ema9_3 - r.ema9_3_prev) > 0)
    else:
        ema_order = bool(d * (r.ema9 - r.ema21) > 0)
        ema_slope = bool(d * (r.ema9 - p.ema9) > 0)
    band = bool(((r.close > r.bb_up) if d > 0 else (r.close < r.bb_lo)) and r.bw > p5.bw)
    brk = bool((r.close > prev5.high.max()) if d > 0 else (r.close < prev5.low.min()))
    if d > 0:
        strength = 60 <= r.rsi <= 80 and r.macdh > 0 and r.macdh > p.macdh
    else:
        strength = 20 <= r.rsi <= 40 and r.macdh < 0 and r.macdh < p.macdh
    volume = bool(r.fvol_avg20 and r.fvol >= 1.5 * r.fvol_avg20)
    heavy = sum(d * (r[c] - b3[c]) > 0 for c in ("bn", "hdfc", "icici")) >= 2
    vix = (r.vix - b3.vix <= 0) if d > 0 else (r.vix - b3.vix >= 0)
    end = b.index[i] + timedelta(minutes=1)
    oi_now, oi_then = feed.oi_at(end), feed.oi_at(end - timedelta(minutes=5))
    atm = int(round(r.close / 50) * 50)
    oi = False
    if oi_now and oi_then and atm in oi_now and atm in oi_then:
        dce, dpe = oi_now[atm][0] - oi_then[atm][0], oi_now[atm][1] - oi_then[atm][1]
        oi = (dce < 0 or dpe > 0) if d > 0 else (dpe < 0 or dce > 0)
    conf = {"strength": bool(strength), "volume": volume, "heavyweights": bool(heavy), "vix": bool(vix),
            "oi": bool(oi)}
    return {"vwap": above_vwap, "ema_order": ema_order, "ema_slope": ema_slope, "trend": above_vwap and ema_order
            and ema_slope, "trigger_band": band, "trigger_break": brk, "trigger": band or brk, **conf,
            "confirmations": sum(conf.values())}


def classify(c: dict[str, Any]) -> str:
    """Entry class from the checklist at entry (README §6); first match wins."""
    if c["trigger_band"] and c["trigger_break"] and c["confirmations"] >= 4:
        return "K1"
    if c["trigger_band"] and c["volume"]:
        return "K2"
    if c["trigger_break"] and c["heavyweights"] and c["vix"]:
        return "K3"
    return "K4"


def room_to_move(b: pd.DataFrame, i: int, feed: Feed, d: int) -> float | None:
    """Distance (pts) to the biggest OI wall in the trade's direction within WALL_RANGE (README §8)."""
    oi = feed.oi_at(b.index[i] + timedelta(minutes=1))
    if not oi:
        return None
    spot = float(b.iloc[i].close)
    if d > 0:
        cand = {k: v[0] for k, v in oi.items() if spot < k <= spot + WALL_RANGE}
    else:
        cand = {k: v[1] for k, v in oi.items() if spot - WALL_RANGE <= k < spot}
    if not cand:
        return None
    wall = max(cand, key=lambda k: cand[k])
    return round(abs(wall - spot), 1)


def evaluate(b: pd.DataFrame, i: int, feed: Feed, ver: str = "v3") -> dict[str, Any] | None:
    """Layers 1–2 at completed bar i; returns the record (with confirmations) or None."""
    if i < 26:
        return None
    comp = {d: components(b, i, feed, d, ver) for d in (1, -1)}
    live = [d for d in (1, -1) if comp[d]["trend"] and comp[d]["trigger"]]
    if len(live) != 1:
        return None
    d = live[0]
    c, r = comp[d], b.iloc[i]
    room = room_to_move(b, i, feed, d)
    return {"minute": b.index[i].strftime("%H:%M"), "version": ver, "side": "CALL" if d > 0 else "PUT", "dir": d,
            "class": classify(c), "room_pts": room, "room_ok": None if room is None else room >= ROOM_OK,
            "close": round(float(r.close), 2), "trigger_band": c["trigger_band"], "trigger_break": c["trigger_break"],
            "rsi": round(float(r.rsi), 1), "macd_hist": round(float(r.macdh), 2),
            "fvol_x": round(float(r.fvol / r.fvol_avg20), 2) if r.fvol_avg20 else None,
            **{k: c[k] for k in ("strength", "volume", "heavyweights", "vix", "oi")},
            "confirmations": c["confirmations"], "sig_low": float(r.low), "sig_high": float(r.high)}


def option_vol(feed: Feed, key: str, t0: datetime) -> float | None:
    """Average absolute 1-min % change of the option's last price over the 10 minutes before t0 (EC2+ rule 2)."""
    times = [x[0] for x in feed.ltp]
    a, z = bisect.bisect_left(times, t0 - timedelta(minutes=10)), bisect.bisect_left(times, t0)
    px = pd.Series({feed.ltp[k][0]: feed.ltp[k][2].get(key) for k in range(a, z)}, dtype=float).dropna()
    if px.empty:
        return None
    m = px.resample("1min").last().dropna()
    return float(m.pct_change().abs().dropna().mean()) if len(m) >= 4 else None


def mark(feed: Feed, key: str, ts: datetime, fno: dict[str, float]) -> float | None:
    q = feed.quote(key, ts)
    if q:
        return q[0]
    last = fno.get(key)
    return float(last) - 0.5 if last is not None else None


