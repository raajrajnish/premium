"""U1 multi-confirmation setup: PAPER-only live watcher (rules: docs/studies/2026-10-05_U1_multi_confirmation.md).

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
OPT = re.compile(r"NSE_NIFTY(\d\d[A-Z0-9]\d\d)(\d{5})(CE|PE)$")


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
    return b


def evaluate(b: pd.DataFrame, i: int, feed: Feed) -> dict[str, Any] | None:
    """Layers 1–2 at completed bar i; returns the record (with confirmations) or None."""
    if i < 26:
        return None
    r, p, p5 = b.iloc[i], b.iloc[i - 1], b.iloc[i - 5]
    prev5 = b.iloc[i - 5:i]
    res = {}
    for d in (1, -1):
        trend = (d * (r.fpx - r.vwap) > 0 and d * (r.ema9 - r.ema21) > 0 and d * (r.ema9 - p.ema9) > 0)
        band = (r.close > r.bb_up) if d > 0 else (r.close < r.bb_lo)
        brk = (r.close > prev5.high.max()) if d > 0 else (r.close < prev5.low.min())
        trig = (band and r.bw > p5.bw) or brk
        if trend and trig:
            res[d] = (band and r.bw > p5.bw, brk)
    if len(res) != 1:
        return None
    d = next(iter(res))
    b3 = b.iloc[i - 3]
    strength = (60 <= r.rsi <= 80 and r.macdh > 0 and r.macdh > p.macdh) if d > 0 else \
               (20 <= r.rsi <= 40 and r.macdh < 0 and r.macdh < p.macdh)
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
    return {"minute": b.index[i].strftime("%H:%M"), "side": "CALL" if d > 0 else "PUT", "dir": d,
            "close": round(float(r.close), 2), "trigger_band": bool(res[d][0]), "trigger_break": bool(res[d][1]),
            "rsi": round(float(r.rsi), 1), "macd_hist": round(float(r.macdh), 2),
            "fvol_x": round(float(r.fvol / r.fvol_avg20), 2) if r.fvol_avg20 else None,
            **conf, "confirmations": sum(conf.values()), "sig_low": float(r.low), "sig_high": float(r.high)}


def run_day(feed: Feed) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    b = minute_frame(feed)
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
        rec = evaluate(b, completed_i, feed)
        if rec is None:
            continue
        rec["taken"] = False
        rec["why_not"] = ""
        if rec["confirmations"] < 3:
            rec["why_not"] = "confirmations<3"
        elif len(trades) >= MAX_TRADES:
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
                pos = {"date": str(feed.day), "signal_min": rec["minute"], "side": rec["side"], "key": key,
                       "confirmations": rec["confirmations"], "entry": ts.strftime("%H:%M:%S"),
                       "entry_px": round(px, 2), "nifty": spot, "dir": rec["dir"], "entry_dt": ts,
                       "stop": rec["sig_low"] if rec["dir"] > 0 else rec["sig_high"],
                       "fill": "ask" if q else "ltp+0.5"}
                rec["taken"] = True
        signals.append(rec)
    return signals, trades


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=str(date.today()))
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    day = date.fromisoformat(a.day)
    OUT.mkdir(parents=True, exist_ok=True)
    feed = Feed(day)
    shown = 0
    print(f"U1 paper watcher for {day} (PAPER ONLY; reads the recorder read-only). Entries {START}–{LAST_ENTRY}.")
    while True:
        feed.update()
        if feed.ltp:
            sig, tr = run_day(feed)
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
