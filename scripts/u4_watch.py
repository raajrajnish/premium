"""U4 paper watcher (docs/U4_README.md): S-FLOW (order flow + micro-price + Hawkes agree) and S-SPREAD (Nifty vs
heavyweights Kalman dislocation), thesis-break / Chandelier / half-life / loss-cut exits, MAIN + threshold variants.
Reads the recorder read-only; writes only premium/data/u4/. PAPER ONLY. Every poll replays the day deterministically.
Usage: uv run python scripts/u4_watch.py [--day YYYY-MM-DD] [--once]
"""

import argparse
import bisect
import csv
import json
import math
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd
import u4_core as core
import u4_features as fx

VERSION = "v0.1"
LOT, CHARGES = 65, 1.5
SIG_START, SIG_END, HARD = time(9, 45), time(14, 30), time(15, 10)
LOSS_CAP, MAX_TRADES, LOSS_STREAK, STREAK_PAUSE = -2000, 8, 3, timedelta(minutes=30)
SAFETY_LOSS = 0.25


@dataclass(frozen=True)
class Var:
    name: str
    flow_z: float = 2.5
    spread_z: float = 2.0


VARIANTS = [Var("MAIN"), Var("FLOW-z2", flow_z=2.0), Var("FLOW-z3", flow_z=3.0),
            Var("SPREAD-1.5", spread_z=1.5), Var("SPREAD-2.5", spread_z=2.5)]


@dataclass
class Pos:
    strat: str
    d: int
    key: str
    px0: float
    t0: datetime
    spot0: float
    hard: time
    info: dict[str, Any]
    chand: float
    loss_cut: float
    max_min: float
    best_spot: float
    peak_bid: float
    worst_bid: float
    break_since: datetime | None = None
    last_bid: float | None = None


@dataclass
class Book:
    variant: Var
    strat: str
    trades: list[dict[str, Any]] = field(default_factory=list)
    pos: Pos | None = None
    day_pnl: float = 0.0
    streak: int = 0
    pause_until: datetime | None = None
    last_break: datetime | None = None

    def risk_block(self, ts: datetime) -> str | None:
        if self.day_pnl <= LOSS_CAP:
            return "daily loss cap"
        if len(self.trades) >= MAX_TRADES:
            return "max trades"
        if self.pause_until is not None and ts < self.pause_until:
            return "pause after 3 losses"
        return None


def past_trades(day: date) -> dict[str, list[float]]:
    """Completed MAIN trades of previous live days, per strategy (for the logged Kelly estimate)."""
    out: dict[str, list[float]] = {"FLOW": [], "SPREAD": []}
    for f in sorted(core.OUT.glob("*_trades.csv")):
        if f.name[:10] >= str(day):
            continue
        with f.open(encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("variant") == "MAIN" and r.get("strat") in out:
                    out[r["strat"]].append(float(r["pnl_lot"]))
    return out


def kelly(pnls: list[float]) -> float | None:
    if len(pnls) < 5:
        return None
    w = [x for x in pnls if x > 0]
    lo = [-x for x in pnls if x <= 0]
    if not w or not lo:
        return None
    p, payoff = len(w) / len(pnls), (sum(w) / len(w)) / (sum(lo) / len(lo))
    return 0.25 * (p - (1 - p) / payoff)


def option_micro(feed: core.Feed, key: str, ts: datetime) -> float | None:
    q = feed.quote(key, ts)
    book = feed.optbook.get(key)
    if not q or not book:
        return None
    i = bisect.bisect_right([b[0] for b in book], ts) - 1
    if i < 0:
        return None
    _, b5, s5 = book[i]
    return fx.micro_price(q[0], b5, q[1], s5)


def atm_key(spot: float, d: int, fno: dict[str, float]) -> str | None:
    side = "CE" if d > 0 else "PE"
    strike = int(round(spot / 50) * 50)
    keys = sorted(k for k in fno if (m := core.OPT.match(k)) and int(m.group(2)) == strike and m.group(3) == side)
    return keys[0] if keys else None


def run_day(feed: core.Feed, F: fx.Features) -> tuple[list[Book], list[dict[str, Any]]]:
    tk = F.ticks
    books = {(v.name, s): Book(v, s) for v in VARIANTS for s in ("FLOW", "SPREAD")}
    decisions: list[dict[str, Any]] = []
    hist = past_trades(feed.day)
    exp_today = False
    if feed.ltp:
        keys = [k for k in feed.ltp[-1][2] if core.OPT.match(k)]
        exps = sorted({e for e in (core.expiry_of(k) for k in keys) if e})
        exp_today = bool(exps) and exps[0] == feed.day
    hard = time(14, 45) if exp_today else HARD
    sig_hist: list[float] = []
    prev_ts: datetime | None = None
    last_sig_log: dict[tuple[str, int], datetime] = {}
    for ts, idx, fno in feed.ltp:
        if ts not in tk.index:
            continue
        row = tk.loc[ts]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[-1]
        spot = float(idx["NSE_NIFTY"])
        gap = prev_ts is not None and (ts - prev_ts).total_seconds() > 60
        prev_ts = ts
        f = {k: (float(row[k]) if row[k] == row[k] else None) for k in
             ("mlofi_z", "book_z", "lean_z", "casc_up", "casc_dn", "lam_up", "lam_dn", "spread_z", "half_life",
              "sigma1m")}
        sig1 = f["sigma1m"] or 4.0
        sig_hist.append(sig1)
        for bk in books.values():
            if bk.pos is not None:
                _manage(bk, feed, ts, fno, spot, gap, f)
        if not (SIG_START <= ts.time() <= SIG_END):
            continue
        vol_ratio = sig1 / float(pd.Series(sig_hist).median())
        for v in VARIANTS:
            # ---------- S-FLOW
            bk = books[(v.name, "FLOW")]
            if bk.pos is None and f["mlofi_z"] is not None and f["lean_z"] is not None and f["casc_up"] is not None:
                for d in (1, -1):
                    casc, other = (f["casc_up"], f["casc_dn"]) if d > 0 else (f["casc_dn"], f["casc_up"])
                    lam_s, lam_o = (f["lam_up"], f["lam_dn"]) if d > 0 else (f["lam_dn"], f["lam_up"])
                    if d * f["mlofi_z"] >= v.flow_z and d * f["lean_z"] >= 1 and casc >= 2 and lam_s > lam_o \
                            and d * (f["book_z"] or 0) >= 0:
                        _try(bk, feed, ts, fno, spot, d, hard, decisions, last_sig_log, hist, vol_ratio, f, sig1,
                             max_min=10.0)
                        break
            # ---------- S-SPREAD
            bk = books[(v.name, "SPREAD")]
            z, hl = f["spread_z"], f["half_life"]
            if bk.pos is None and z is not None and hl is not None and abs(z) >= v.spread_z and hl <= 15 and \
                    (bk.last_break is None or ts - bk.last_break > timedelta(minutes=5)):
                d = -1 if z > 0 else 1
                _try(bk, feed, ts, fno, spot, d, hard, decisions, last_sig_log, hist, vol_ratio, f, sig1,
                     max_min=min(20.0, max(5.0, 2 * hl)))
    return list(books.values()), decisions


def _try(bk: Book, feed: core.Feed, ts: datetime, fno: dict[str, float], spot: float, d: int, hard: time,
         decisions: list[dict[str, Any]], last_log: dict[tuple[str, int], datetime], hist: dict[str, list[float]],
         vol_ratio: float, f: dict[str, Any], sig1: float, max_min: float) -> None:
    v = bk.variant
    info = {"variant": v.name, "strat": bk.strat, "side": "CALL" if d > 0 else "PUT", "time": ts.strftime("%H:%M:%S"),
            **{k: (round(x, 2) if isinstance(x, float) else x) for k, x in f.items()}}
    why = bk.risk_block(ts)
    key = atm_key(spot, d, fno) if why is None else None
    if why is None and key is None:
        why = "no ATM option price"
    if why is not None:
        k = (f"{v.name}/{bk.strat}", d)
        if v.name == "MAIN" and (k not in last_log or ts - last_log[k] > timedelta(minutes=2)):
            decisions.append(info | {"decision": "SKIP", "why": why})
            last_log[k] = ts
        return
    assert key is not None
    q = feed.quote(key, ts)
    px = q[1] if q else float(fno[key]) + 0.5
    mic = option_micro(feed, key, ts)
    pnls = hist[bk.strat] + [t["pnl_lot"] for t in bk.trades]
    kf = kelly(pnls)
    would = 1 if (kf is None or kf <= 0 or vol_ratio > 1.5) else min(3, 1 + int(kf / 0.05))
    chand = 3 * sig1
    info |= {"entry_slippage": round(px - mic, 2) if mic is not None else None,
             "kelly_f": None if kf is None else round(kf, 3), "would_lots": would,
             "vol_ratio": round(vol_ratio, 2), "chandelier_pts": round(chand, 1)}
    bk.pos = Pos(strat=bk.strat, d=d, key=key, px0=px, t0=ts, spot0=spot, hard=hard, info=info, chand=chand,
                 loss_cut=2 * sig1 * math.sqrt(5), max_min=max_min, best_spot=spot, peak_bid=px, worst_bid=px)
    if v.name == "MAIN":
        decisions.append(info | {"decision": "ENTER"})


def _manage(bk: Book, feed: core.Feed, ts: datetime, fno: dict[str, float], spot: float, gap: bool,
            f: dict[str, Any]) -> None:
    p = bk.pos
    assert p is not None
    bid = core.mark(feed, p.key, ts, fno)
    el = (ts - p.t0).total_seconds() / 60
    p.best_spot = max(p.best_spot, spot) if p.d > 0 else min(p.best_spot, spot)
    reason, px = None, bid
    if gap:
        reason, px = "feed lost", p.last_bid
    elif ts.time() >= p.hard:
        reason = "hard"
    if bid is not None:
        p.peak_bid, p.worst_bid = max(p.peak_bid, bid), min(p.worst_bid, bid)
    in_profit = bid is not None and bid - p.px0 - CHARGES > 0
    if reason is None and bid is not None and bid <= p.px0 * (1 - SAFETY_LOSS):
        reason = "max loss −25%"
    if reason is None and -p.d * (spot - p.spot0) >= p.loss_cut:
        reason = "loss cut (2σ, 5 min)"
    if reason is None and p.d * (p.best_spot - spot) >= p.chand and p.d * (p.best_spot - p.spot0) > 0:
        reason = "Chandelier (3σ from best)"
    if reason is None and p.strat == "FLOW":
        oz = f["mlofi_z"]
        opp_casc = (f["casc_dn"] if p.d > 0 else f["casc_up"]) or 0
        lam_o, lam_s = (f["lam_dn"], f["lam_up"]) if p.d > 0 else (f["lam_up"], f["lam_dn"])
        flow_broke = oz is not None and p.d * oz <= -1.5
        if flow_broke:
            p.break_since = p.break_since or ts
        else:
            p.break_since = None
        if p.break_since is not None and ts - p.break_since >= timedelta(seconds=20):
            reason = "thesis break: order flow reversed"
        elif opp_casc >= 2 and (lam_o or 0) > (lam_s or 0):
            reason = "thesis break: opposite cascade"
        elif el >= p.max_min and not in_profit:
            reason = "time 10 min (not in profit)"
    elif reason is None and p.strat == "SPREAD":
        z = f["spread_z"]
        if z is not None and abs(z) <= 0.5:
            reason = "target: back to fair value"
        elif z is not None and -p.d * z >= 3.5:
            reason = "thesis break: dislocation widened"
            bk.last_break = ts
        elif el >= p.max_min:
            reason = f"time (2× half-life, {p.max_min:.0f} min)"
    if bid is not None:
        p.last_bid = bid
    if reason and px is not None:
        pnl = round((px - p.px0 - CHARGES) * LOT)
        bk.trades.append(p.info | {"date": str(feed.day), "key": p.key, "entry": p.t0.strftime("%H:%M:%S"),
                                   "entry_px": round(p.px0, 2), "exit": ts.strftime("%H:%M:%S"),
                                   "exit_px": round(px, 2), "reason": reason, "mins": round(el, 1),
                                   "best_lot": round((p.peak_bid - p.px0 - CHARGES) * LOT),
                                   "worst_lot": round((p.worst_bid - p.px0 - CHARGES) * LOT), "pnl_lot": pnl})
        bk.day_pnl += pnl
        bk.streak = bk.streak + 1 if pnl <= 0 else 0
        if bk.streak >= LOSS_STREAK:
            bk.pause_until, bk.streak = ts + STREAK_PAUSE, 0
        bk.pos = None


def write_state(feed: core.Feed, F: fx.Features, books: list[Book], decisions: list[dict[str, Any]]) -> None:
    ts, idx, fno = feed.ltp[-1]
    last = F.ticks.iloc[-1]

    def g(k: str) -> float | None:
        v = last.get(k)
        return None if v is None or v != v else round(float(v), 2)

    status = {}
    for bk in books:
        if bk.variant.name != "MAIN":
            continue
        if bk.pos is None:
            status[bk.strat] = {"mode": "idle", "trades": len(bk.trades), "day_pnl": round(bk.day_pnl),
                                "blocked": bk.risk_block(ts)}
        else:
            p = bk.pos
            bid = core.mark(feed, p.key, ts, fno)
            status[bk.strat] = {"mode": "in trade", "side": "CALL" if p.d > 0 else "PUT", "key": p.key,
                                "entry": p.t0.strftime("%H:%M:%S"), "entry_px": round(p.px0, 2), "bid": bid,
                                "pnl_lot": round((bid - p.px0 - CHARGES) * LOT) if bid is not None else None,
                                "trades": len(bk.trades), "day_pnl": round(bk.day_pnl)}
    variants: dict[str, dict[str, Any]] = {}
    for bk in books:
        v = variants.setdefault(bk.variant.name, {"variant": bk.variant.name, "total": 0})
        v[bk.strat] = {"trades": len(bk.trades), "total": int(sum(t["pnl_lot"] for t in bk.trades))}
        v["total"] += v[bk.strat]["total"]
    state = {"updated": datetime.now().isoformat(timespec="seconds"), "feed_ts": ts.isoformat(timespec="seconds"),
             "day": str(feed.day), "version": VERSION,
             "features": {k: g(k) for k in ("mlofi_z", "book_z", "lean_z", "casc_up", "casc_dn", "spread_z",
                                            "half_life", "sigma1m")},
             "hawkes": {s: {k: round(F.hawkes[s][k], 4) for k in ("mu", "alpha", "beta", "n")} for s in ("up", "down")},
             "status": status, "decisions": decisions[-25:],
             "trades": [t for bk in books if bk.variant.name == "MAIN" for t in bk.trades],
             "variants": list(variants.values())}
    tmp = core.OUT / "state.tmp"
    tmp.write_text(json.dumps(state, default=str), encoding="utf-8")
    tmp.replace(core.OUT / "state.json")


def minute_features(F: fx.Features) -> pd.DataFrame:
    cols = ["nifty", "mlofi_z", "book_z", "lean_z", "casc_up", "casc_dn", "spread_z", "half_life", "sigma1m"]
    m = F.ticks[cols].resample("1min").last().dropna(subset=["nifty"])
    m["hawkes_dir"] = (F.ticks["lam_up"] / F.ticks["lam_dn"]).apply(math.log).resample("1min").last()
    return m.round(4)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=str(date.today()))
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    day = date.fromisoformat(a.day)
    core.OUT.mkdir(parents=True, exist_ok=True)
    feed = core.Feed(day)
    print(f"U4 {VERSION} paper watcher for {day} (PAPER ONLY; reads the recorder read-only). Rules: docs/U4_README.md")
    books: list[Book] = []
    shown = 0
    while True:
        feed.update()
        if len(feed.ltp) > 50:
            F = fx.build(feed)
            books, decisions = run_day(feed, F)
            write_state(feed, F, books, decisions)
            pd.DataFrame([t for bk in books for t in bk.trades]).to_csv(core.OUT / f"{day}_trades.csv", index=False)
            pd.DataFrame(decisions).to_csv(core.OUT / f"{day}_decisions.csv", index=False)
            minute_features(F).to_csv(core.OUT / f"{day}_features.csv")
            main_tr = sorted((t for bk in books if bk.variant.name == "MAIN" for t in bk.trades),
                             key=lambda x: x["entry"])
            for t in main_tr[shown:]:
                print(f"{t['strat']:6s} {t['entry']} {t['side']} {t['key']} @ {t['entry_px']} → {t['exit']} @ "
                      f"{t['exit_px']} [{t['reason']}] = ₹{t['pnl_lot']}/lot (best {t['best_lot']})", flush=True)
            shown = len(main_tr)
        if a.once or datetime.now().time() >= time(15, 12):
            for bk in books:
                print(f"{bk.variant.name:10s} {bk.strat:6s}: {len(bk.trades):2d} trades, "
                      f"₹{sum(t['pnl_lot'] for t in bk.trades):+,}")
            break
        _time.sleep(20)


if __name__ == "__main__":
    main()
