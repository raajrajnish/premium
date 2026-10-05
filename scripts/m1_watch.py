"""M1 burst-follow: PAPER-only forward watcher on today's live recording (read-only; never places orders).

Rule (declared 2026-10-05 09:40, before any data after that time was seen):
  window 09:45–14:30 entries; one trade at a time; 5-minute pause after an exit.
  signal: last 3 completed 1-min Nifty closes all move the same way AND |3-minute move| >= 15 pts.
  entry : ATM (nearest 50) CE for up / PE for down, nearest expiry, at the first live price after the signal.
  exit  : option +8 (target) | option -5 (stop) | a 1-min close against the trade | 5 minutes | 15:10.
  cost  : ₹3 per unit round trip; lot 65.
Reads the Nifty system's recorder file read-only; writes only premium/data/m1/<day>_trades.csv.

Usage: python scripts/m1_watch.py [--day YYYY-MM-DD] [--start 09:45] [--once]
"""

import argparse
import json
import re
import time as _time
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT.parent / "suzlon" / "data" / "raw"
OUT = ROOT / "data" / "m1"
LOT, COST = 65, 3.0
TARGET, STOP, MAX_MIN, MIN_MOVE = 8.0, 5.0, 5, 15.0
OPT = re.compile(r"NSE_NIFTY(\d\d[A-Z0-9]\d\d)(\d{5})(CE|PE)$")


def ticks(day: date) -> list[tuple[datetime, float, dict[str, float]]]:
    out = []
    p = RAW / f"date={day}" / "ltp.jsonl"
    with p.open(encoding="utf-8") as f:
        for line in f:
            try:
                j = json.loads(line)
            except ValueError:
                continue                      # a line still being written
            n = (j.get("index") or {}).get("NSE_NIFTY")
            if n:
                out.append((datetime.fromisoformat(j["recv_ts"]).replace(tzinfo=None), float(n), j.get("fno") or {}))
    return out


def simulate(day: date, start: time, end_entry: time = time(14, 30), hard: time = time(15, 10)) -> list[dict[str, object]]:
    tk = ticks(day)
    closes: list[tuple[datetime, float]] = []           # completed minute closes
    cur_min, last_px = None, None
    pos: dict[str, object] | None = None
    trades: list[dict[str, object]] = []
    pause_until = datetime.combine(day, time(0))
    for ts, px, fno in tk:
        m = ts.replace(second=0, microsecond=0)
        completed = False
        if cur_min is not None and m > cur_min and last_px is not None:
            closes.append((cur_min, last_px))
            completed = True
        cur_min, last_px = m, px
        if pos is not None:
            opx = fno.get(str(pos["key"]))
            if opx is None:
                continue
            reason = None
            if opx >= float(pos["entry_px"]) + TARGET:  # type: ignore[arg-type]
                reason = "target"
            elif opx <= float(pos["entry_px"]) - STOP:  # type: ignore[arg-type]
                reason = "stop"
            elif completed and len(closes) >= 2 and (closes[-1][1] - closes[-2][1]) * float(pos["dir"]) < 0:  # type: ignore[arg-type]
                reason = "against"
            elif ts - pos["entry_ts"] >= timedelta(minutes=MAX_MIN):  # type: ignore[operator]
                reason = "time"
            elif ts.time() >= hard:
                reason = "15:10"
            if reason:
                pnl = opx - float(pos["entry_px"]) - COST  # type: ignore[arg-type]
                trades.append({**pos, "exit_ts": ts.strftime("%H:%M:%S"), "exit_px": opx, "reason": reason,
                               "pnl_per_unit": round(pnl, 2), "pnl_lot": round(pnl * LOT, 0)})
                trades[-1]["entry_ts"] = pos["entry_ts"].strftime("%H:%M:%S")  # type: ignore[union-attr]
                pos, pause_until = None, ts + timedelta(minutes=5)
            continue
        if not completed or len(closes) < 4 or ts < pause_until:
            continue
        if not (start <= closes[-1][0].time() and ts.time() <= end_entry):
            continue
        c = [x[1] for x in closes[-4:]]
        steps = [c[1] - c[0], c[2] - c[1], c[3] - c[2]]
        move = c[3] - c[0]
        if abs(move) < MIN_MOVE or not (all(s > 0 for s in steps) or all(s < 0 for s in steps)):
            continue
        d = 1 if move > 0 else -1
        strike = int(round(px / 50) * 50)
        side = "CE" if d > 0 else "PE"
        keys = [k for k in fno if (mm := OPT.match(k)) and int(mm.group(2)) == strike and mm.group(3) == side]
        if not keys:
            continue
        key = sorted(keys)[0]
        pos = {"signal_min": closes[-1][0].strftime("%H:%M"), "dir": d, "nifty": px, "move3": round(move, 1),
               "key": key, "entry_ts": ts, "entry_px": fno[key]}
    return trades


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=str(date.today()))
    ap.add_argument("--start", default="09:45")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    day, start = date.fromisoformat(a.day), time.fromisoformat(a.start)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{day}_trades{'' if a.start == '09:45' else '_from' + a.start.replace(':', '')}.csv"
    seen = -1
    while True:
        tr = simulate(day, start)
        if len(tr) != seen:
            pd.DataFrame(tr).to_csv(out, index=False)
            for t in tr[max(seen, 0):]:
                print(f"{t['entry_ts']} {'CALL' if t['dir'] == 1 else 'PUT '} {t['key']} @ {t['entry_px']} → "
                      f"{t['exit_ts']} @ {t['exit_px']} ({t['reason']}) = ₹{t['pnl_lot']}/lot", flush=True)
            seen = len(tr)
        if a.once or datetime.now().time() >= time(15, 12):
            tot = sum(float(t["pnl_lot"]) for t in tr)  # type: ignore[arg-type]
            print(f"{day}: {len(tr)} trades, total ₹{tot:.0f}/lot → {out}")
            break
        _time.sleep(20)


if __name__ == "__main__":
    main()
