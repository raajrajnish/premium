"""U1 multi-confirmation setup: PAPER-only live watcher. Rules: docs/U1_README.md (single source of truth).
v1 (2026-10-05): trend on 1-min candles. v2 (from 2026-10-06): trend on 3-min candles; classes K1–K4 and safety
checks are logged on every signal (logging only; they never change a decision).

Reads the Nifty system's recorder files READ-ONLY (incrementally) and writes only premium/data/u1/.
Every poll replays the whole day deterministically from the parsed data, so a restart gives the same result.
Usage: python scripts/u1_watch.py [--day YYYY-MM-DD] [--once]
"""

import argparse
import bisect
import json
import re
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT.parent / "suzlon" / "data" / "raw"
OUT = ROOT / "data" / "u1"
LOT, CHARGES = 65, 1.5
START, LAST_ENTRY, HARD = time(9, 45), time(14, 30), time(15, 10)
MAX_TRADES, PAUSE_MIN, TIME_STOP_MIN = 4, 5, 15
# TESTING PHASE (owner, 2026-10-05): the daily trade cap is OFF from this moment on (README §4).
# Signals before it keep the cap, so the morning's recorded trades stay unchanged.
CAP_OFF_FROM: datetime | None = datetime(2026, 10, 5, 11, 25)
V2_FROM = date(2026, 10, 6)
WALL_RANGE, ROOM_OK, SPREAD_OK = 300, 25.0, 1.0
OPT = re.compile(r"NSE_NIFTY(\d\d[A-Z0-9]\d\d)(\d{5})(CE|PE)$")


def version(day: date) -> str:
    return "v2" if day >= V2_FROM else "v1"


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
    quotes: dict[str, tuple[list[datetime], list[tuple[float, float]]]] = field(default_factory=dict)
    chain: list[tuple[datetime, dict[int, tuple[float, float]]]] = field(default_factory=list)  # strike→(CE OI, PE OI)

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
            elif j.get("bid") and j.get("ask"):
                ts_list, vals = self.quotes.setdefault("NSE_" + s, ([], []))
                ts_list.append(ts_of(j))
                vals.append((float(j["bid"]), float(j["ask"])))
        for j in self.t_c.read():
            oi = {}
            for k, v in (j.get("strikes") or {}).items():
                ce, pe = (v.get("CE") or {}).get("open_interest"), (v.get("PE") or {}).get("open_interest")
                if ce is not None and pe is not None:
                    oi[int(float(k))] = (float(ce), float(pe))
            self.chain.append((ts_of(j), oi))

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


def components(b: pd.DataFrame, i: int, feed: Feed, d: int, ver: str = "v1") -> dict[str, Any]:
    """Every U1 condition for direction d (+1 CALL, -1 PUT) at completed bar i (needs i >= 26).
    v2: EMA order and slope come from completed 3-min candles; everything else is unchanged."""
    r, p, p5, b3 = b.iloc[i], b.iloc[i - 1], b.iloc[i - 5], b.iloc[i - 3]
    prev5 = b.iloc[i - 5:i]
    above_vwap = bool(d * (r.fpx - r.vwap) > 0)
    if ver == "v2":
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


def evaluate(b: pd.DataFrame, i: int, feed: Feed, ver: str = "v1") -> dict[str, Any] | None:
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


def run_day(feed: Feed) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    b = minute_frame(feed)
    ver = version(feed.day)
    signals: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    pos: dict[str, Any] | None = None
    pause = datetime.combine(feed.day, time(0))
    done_min: pd.Timestamp | None = None
    for ts, idx, fno in feed.ltp:
        m = pd.Timestamp(ts.replace(second=0, microsecond=0))
        completed_i = None
        if done_min is None or m > done_min:
            prev = m - timedelta(minutes=1)
            if prev in b.index and (done_min is None or prev > done_min):
                completed_i = b.index.get_loc(prev)
            done_min = m - timedelta(minutes=1) if completed_i is not None else done_min
        spot = float(idx["NSE_NIFTY"])
        if pos is not None:
            reason = None
            if pos["dir"] * (spot - pos["stop"]) < 0:
                reason = "stop"
            elif completed_i is not None and pos["dir"] * (b.iloc[completed_i].close - b.iloc[completed_i].ema9) < 0:
                reason = "trail"
            elif ts - pos["entry_dt"] >= timedelta(minutes=TIME_STOP_MIN):
                reason = "time"
            elif ts.time() >= HARD:
                reason = "15:10"
            if reason:
                q = feed.quote(pos["key"], ts)
                last = fno.get(pos["key"])
                if q is None and last is None:
                    continue
                px = q[0] if q else float(last) - 0.5
                pnl = px - pos["entry_px"] - CHARGES
                trades.append({k: v for k, v in pos.items() if k not in ("entry_dt", "dir")} |
                              {"exit": ts.strftime("%H:%M:%S"), "exit_px": round(px, 2), "reason": reason,
                               "pnl_per_unit": round(pnl, 2), "pnl_lot": round(pnl * LOT)})
                pos, pause = None, ts + timedelta(minutes=PAUSE_MIN)
            continue
        if completed_i is None:
            continue
        bar_t = b.index[completed_i].time()
        if not (START <= bar_t <= LAST_ENTRY):
            continue
        rec = evaluate(b, completed_i, feed, ver)
        if rec is None:
            continue
        rec["taken"] = False
        rec["why_not"] = ""
        side_k = "CE" if rec["dir"] > 0 else "PE"
        atm = int(round(spot / 50) * 50)
        atm_keys = sorted(k for k in fno if (mm := OPT.match(k)) and int(mm.group(2)) == atm and mm.group(3) == side_k)
        sq = feed.quote(atm_keys[0], ts) if atm_keys else None
        rec["spread"] = round(sq[1] - sq[0], 2) if sq else None
        rec["spread_ok"] = None if sq is None else (sq[1] - sq[0]) <= SPREAD_OK
        if rec["confirmations"] < 3:
            rec["why_not"] = "confirmations<3"
        elif len(trades) >= MAX_TRADES and (CAP_OFF_FROM is None or ts < CAP_OFF_FROM):
            rec["why_not"] = "max trades"
        elif ts < pause:
            rec["why_not"] = "pause"
        else:
            side = "CE" if rec["dir"] > 0 else "PE"
            strike = int(round(spot / 50) * 50)
            keys = sorted(k for k in fno if (mm := OPT.match(k)) and int(mm.group(2)) == strike and mm.group(3) == side)
            if not keys:
                rec["why_not"] = "no ATM option price"
            else:
                key = keys[0]
                q = feed.quote(key, ts)
                px = q[1] if q else float(fno[key]) + 0.5
                pos = {"date": str(feed.day), "version": ver, "class": rec["class"], "signal_min": rec["minute"],
                       "side": rec["side"], "key": key, "room_pts": rec["room_pts"], "room_ok": rec["room_ok"],
                       "spread": rec["spread"], "spread_ok": rec["spread_ok"],
                       "confirmations": rec["confirmations"], "entry": ts.strftime("%H:%M:%S"),
                       "entry_px": round(px, 2), "nifty": spot, "dir": rec["dir"], "entry_dt": ts,
                       "stop": rec["sig_low"] if rec["dir"] > 0 else rec["sig_high"],
                       "fill": "ask" if q else "ltp+0.5"}
                rec["taken"] = True
        signals.append(rec)
    return signals, trades, pos


def write_state(feed: Feed, signals: list[dict[str, Any]], trades: list[dict[str, Any]],
                pos: dict[str, Any] | None) -> None:
    """data/u1/state.json for the U1 dashboard: open position (marked at the bid), checklist, recent bars."""
    b = minute_frame(feed)
    ver = version(feed.day)
    ts, idx, fno = feed.ltp[-1]
    complete = b.iloc[:-1]                                   # the last bar is still forming
    check = None
    if len(complete) > 26:
        i = len(complete) - 1
        check = {"minute": complete.index[i].strftime("%H:%M"),
                 "CALL": components(b, i, feed, 1, ver), "PUT": components(b, i, feed, -1, ver)}
    open_pos = None
    if pos is not None:
        q = feed.quote(pos["key"], ts)
        last = fno.get(pos["key"])
        mark = q[0] if q else (float(last) - 0.5 if last is not None else None)
        open_pos = {k: v for k, v in pos.items() if k not in ("entry_dt",)} | {
            "mark": mark, "unreal_lot": round((mark - pos["entry_px"] - CHARGES) * LOT) if mark is not None else None}
    tail = b.tail(120)
    bars = [{"t": int(pd.Timestamp(t).timestamp()), "o": r.open, "h": r.high, "l": r.low, "c": r.close,
             "ema9": r.ema9, "ema21": r.ema21, "bb_up": r.bb_up, "bb_lo": r.bb_lo} for t, r in tail.iterrows()]
    state = {"updated": datetime.now().isoformat(timespec="seconds"), "feed_ts": ts.isoformat(timespec="seconds"),
             "day": str(feed.day), "version": ver, "trend_tf": "3-min" if ver == "v2" else "1-min",
             "nifty": idx.get("NSE_NIFTY"), "vix": idx.get("NSE_INDIAVIX"),
             "open": open_pos, "checklist": check, "trades": trades, "signals": signals[-30:],
             "bars": [{k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in x.items()} for x in bars]}
    tmp = OUT / "state.tmp"
    tmp.write_text(json.dumps(state, default=str), encoding="utf-8")
    tmp.replace(OUT / "state.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=str(date.today()))
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    day = date.fromisoformat(a.day)
    OUT.mkdir(parents=True, exist_ok=True)
    feed = Feed(day)
    shown = 0
    print(f"U1 {version(day)} paper watcher for {day} (PAPER ONLY; reads the recorder read-only). "
          f"Entries {START}–{LAST_ENTRY}. Rules: docs/U1_README.md")
    while True:
        feed.update()
        if feed.ltp:
            sig, tr, pos = run_day(feed)
            write_state(feed, sig, tr, pos)
            pd.DataFrame(sig).to_csv(OUT / f"{day}_signals.csv", index=False)
            pd.DataFrame(tr).to_csv(OUT / f"{day}_trades.csv", index=False)
            for t in tr[shown:]:
                print(f"{t['entry']} {t['side']} {t['key']} @ {t['entry_px']} ({t['confirmations']}/5) → {t['exit']} "
                      f"@ {t['exit_px']} [{t['reason']}] = ₹{t['pnl_lot']}/lot", flush=True)
            shown = len(tr)
        if a.once or datetime.now().time() >= time(15, 12):
            tot = sum(t["pnl_lot"] for t in tr) if feed.ltp else 0
            print(f"{day}: {len(tr) if feed.ltp else 0} trades, total ₹{tot}/lot; files in {OUT}")
            break
        _time.sleep(20)


if __name__ == "__main__":
    main()
