"""U3 paper watcher (docs/U3_README.md): regime-aware strategies S-FADE, S-TREND and S-LAST, with the P8 risk layer,
run as MAIN plus "minus one" ablation variants. Reads the recorder read-only; writes only premium/data/u3/.
PAPER ONLY. Every poll replays the day deterministically.
Usage: uv run python scripts/u3_watch.py [--day YYYY-MM-DD] [--once]
"""

import argparse
import json
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

import pandas as pd
import u3_context as cx
import u3_core as core

VERSION = "v0.1"
LOT, CHARGES = 65, 1.5
SIG_START, SIG_END, HARD = time(10, 15), time(14, 30), time(15, 10)
LOSS_CAP, MAX_TRADES, LOSS_STREAK, STREAK_PAUSE = -2000, 6, 3, timedelta(minutes=30)
SAFETY_LOSS = 0.25


@dataclass(frozen=True)
class Var:
    name: str
    ofi: bool = True
    gamma: bool = True
    inplay: bool = True
    iv: bool = True
    tod: bool = True
    risk: bool = True


VARIANTS = [Var("MAIN"), Var("noOFI", ofi=False), Var("noGAMMA", gamma=False), Var("noINPLAY", inplay=False),
            Var("noIV", iv=False), Var("noTOD", tod=False), Var("noRISK", risk=False)]


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
    target: float | None = None
    stop: float | None = None
    trail_pts: float | None = None
    best_spot: float = 0.0
    peak_bid: float = 0.0
    worst_bid: float = 1e9
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

    def risk_block(self, ts: datetime) -> str | None:
        if not self.variant.risk:
            return None
        if self.day_pnl <= LOSS_CAP:
            return "daily loss cap"
        if len(self.trades) >= MAX_TRADES:
            return "max trades"
        if self.pause_until is not None and ts < self.pause_until:
            return "pause after 3 losses"
        return None


def atm_key(spot: float, d: int, fno: dict[str, float]) -> str | None:
    side = "CE" if d > 0 else "PE"
    strike = int(round(spot / 50) * 50)
    keys = sorted(k for k in fno if (m := core.OPT.match(k)) and int(m.group(2)) == strike and m.group(3) == side)
    return keys[0] if keys else None


def run_day(feed: core.Feed, ctx: cx.Context) -> tuple[list[Book], list[dict[str, Any]], list[dict[str, Any]]]:
    b, tk = ctx.minutes, ctx.ticks
    books = {(v.name, s): Book(v, s) for v in VARIANTS for s in ("FADE", "TREND")}
    books[("MAIN", "LAST")] = Book(VARIANTS[0], "LAST")
    decisions: list[dict[str, Any]] = []
    context_rows: list[dict[str, Any]] = []
    hard = time(14, 45) if ctx.expiry_today else HARD
    regime: dict[str, str] = {v.name: "UNKNOWN" for v in VARIANTS}
    done_min: pd.Timestamp | None = None
    prev_ts: datetime | None = None
    last_done = False
    for ts, idx, fno in feed.ltp:
        spot = float(idx["NSE_NIFTY"])
        m = pd.Timestamp(ts.replace(second=0, microsecond=0))
        ci = None
        if done_min is None or m > done_min:
            pm = m - timedelta(minutes=1)
            if pm in b.index and (done_min is None or pm > done_min):
                ci = b.index.get_loc(pm)
                done_min = pm
        gap = prev_ts is not None and (ts - prev_ts).total_seconds() > 60
        prev_ts = ts
        row = tk.loc[ts] if ts in tk.index else None
        if isinstance(row, pd.DataFrame):
            row = row.iloc[-1]
        ofi_z = float(row["ofi_z"]) if row is not None and row["ofi_z"] == row["ofi_z"] else 0.0
        gex = float(row["gex"]) if row is not None and row["gex"] == row["gex"] else None
        theta = float(row["atm_theta"]) if row is not None and row["atm_theta"] == row["atm_theta"] else None
        iv = float(row["atm_iv"]) if row is not None and row["atm_iv"] == row["atm_iv"] else None
        # ---------------- exits (every tick)
        for bk in books.values():
            if bk.pos is not None:
                _manage(bk, feed, ts, fno, spot, gap, hard, ci, b, regime)
        if ci is None:
            continue
        r = b.iloc[ci]
        bt = b.index[ci].time()
        swing, swing_s = cx.pendulum(tk, ts)
        inplay = ctx.inplay(bt)
        ib = ctx.ib if bt >= cx.IB_END else None
        for v in VARIANTS:
            regime[v.name] = cx.day_type(r.close, r.fpx, r.vwap, ib, gex, inplay if v.inplay else True, v.gamma)
        context_rows.append({"min": b.index[ci].strftime("%H:%M"), "close": round(r.close, 2),
                             "day_type": regime["MAIN"], "gex_bn": None if gex is None else round(gex / 1e9, 2),
                             "call_wall": row["call_wall"] if row is not None else None,
                             "put_wall": row["put_wall"] if row is not None else None,
                             "magnet": row["magnet"] if row is not None else None, "ofi_z": round(ofi_z, 2),
                             "inplay": inplay, "zone": cx.zone(bt), "swing_pts": round(swing, 1),
                             "ib_high": ib[0] if ib else None, "ib_low": ib[1] if ib else None})
        if not (SIG_START <= bt <= SIG_END):
            continue
        base = {"min": b.index[ci].strftime("%H:%M"), "gex_bn": None if gex is None else round(gex / 1e9, 2),
                "ofi_z": round(ofi_z, 2), "inplay": inplay, "zone": cx.zone(bt), "swing": round(swing, 1)}
        for v in VARIANTS:
            dt = regime[v.name]
            # ---------- S-FADE
            bk = books[(v.name, "FADE")]
            fade_ok = dt == "RANGE" or (v.gamma and dt == "MIXED" and gex is not None and gex > 0)
            if fade_ok and r.sd20 and r.sd20 == r.sd20:
                z = (r.close - r.mean20) / r.sd20
                if abs(z) >= 2:
                    ext = 1 if z > 0 else -1
                    d = -ext
                    dist = abs(r.close - r.mean20)
                    need = cx.option_cost_pts(theta, 10)
                    why = None
                    if bk.pos is not None:
                        why = "already in a trade"
                    elif v.ofi and ofi_z * ext > 0:
                        why = "OFI still pushing the extreme"
                    elif v.iv and dist < need:
                        why = f"move {dist:.1f} < option cost {need:.1f} pts"
                    else:
                        why = bk.risk_block(ts)
                    info = base | {"variant": v.name, "strat": "FADE", "regime": dt,
                                   "side": "CALL" if d > 0 else "PUT",
                                   "z": round(z, 2), "expected_pts": round(dist, 1), "need_pts": round(need, 1),
                                   "implied10": round(cx.implied_move(spot, iv, 10), 1)}
                    if why is None and _open(bk, feed, ts, fno, spot, d, hard, info,
                                             target=float(r.mean20), stop=float(r.close) + ext * swing):
                        decisions.append(info | {"decision": "ENTER"})
                    elif why is not None and v.name == "MAIN":
                        decisions.append(info | {"decision": "SKIP", "why": why})
            # ---------- S-TREND
            bk = books[(v.name, "TREND")]
            if dt in ("TREND-UP", "TREND-DOWN") and ci >= 4:
                d = 1 if dt == "TREND-UP" else -1
                prev3 = b.iloc[ci - 3:ci]
                pull = bool(((prev3.low <= prev3.ema20 + 0.25 * swing).any()) if d > 0
                            else ((prev3.high >= prev3.ema20 - 0.25 * swing).any()))
                resume = bool((r.close > b.high.iloc[ci - 1]) if d > 0 else (r.close < b.low.iloc[ci - 1]))
                if pull and resume:
                    need = cx.option_cost_pts(theta, 30)
                    exp_pts = 2 * swing
                    why = None
                    if bk.pos is not None:
                        why = "already in a trade"
                    elif v.tod and cx.zone(bt) == "LULL":
                        why = "midday lull"
                    elif v.inplay and not inplay:
                        why = "not an in-play day"
                    elif v.ofi and ofi_z * d < 0:
                        why = "OFI against"
                    elif v.iv and exp_pts < need:
                        why = f"expected {exp_pts:.1f} < option cost {need:.1f} pts"
                    else:
                        why = bk.risk_block(ts)
                    info = base | {"variant": v.name, "strat": "TREND", "regime": dt,
                                   "side": "CALL" if d > 0 else "PUT",
                                   "expected_pts": round(exp_pts, 1), "need_pts": round(need, 1),
                                   "implied30": round(cx.implied_move(spot, iv, 30), 1)}
                    if why is None and _open(bk, feed, ts, fno, spot, d, hard, info, trail=1.5 * swing):
                        decisions.append(info | {"decision": "ENTER"})
                    elif why is not None and v.name == "MAIN":
                        decisions.append(info | {"decision": "SKIP", "why": why})
        # ---------- S-LAST (MAIN only): once, at the first completed minute at/after 14:45
        if not last_done and bt >= time(14, 44):
            last_done = True
            bk = books[("MAIN", "LAST")]
            open_px = next((float(i["NSE_NIFTY"]) for t_, i, _ in feed.ltp if t_.time() >= time(9, 15)), None)
            p945 = next((float(i["NSE_NIFTY"]) for t_, i, _ in feed.ltp if t_.time() >= time(9, 45)), None)
            info = {"min": b.index[ci].strftime("%H:%M"), "variant": "MAIN", "strat": "LAST", "inplay": inplay}
            if ctx.expiry_today:
                decisions.append(info | {"decision": "SKIP", "why": "expiry day (hard exit 14:45)"})
            elif open_px and p945:
                r1 = p945 / open_px - 1
                info |= {"first_half_hour_pct": round(r1 * 100, 3)}
                if abs(r1) >= 0.001:
                    d = 1 if r1 > 0 else -1
                    info |= {"side": "CALL" if d > 0 else "PUT", "regime": regime["MAIN"]}
                    if _open(bk, feed, ts, fno, spot, d, hard, info):
                        decisions.append(info | {"decision": "ENTER"})
                else:
                    decisions.append(info | {"decision": "SKIP", "why": "first half-hour move < 0.10%"})
    return list(books.values()), decisions, context_rows


def _open(bk: Book, feed: core.Feed, ts: datetime, fno: dict[str, float], spot: float, d: int, hard: time,
          info: dict[str, Any], target: float | None = None, stop: float | None = None,
          trail: float | None = None) -> bool:
    key = atm_key(spot, d, fno)
    if key is None:
        return False
    q = feed.quote(key, ts)
    px = q[1] if q else float(fno[key]) + 0.5
    bk.pos = Pos(strat=bk.strat, d=d, key=key, px0=px, t0=ts, spot0=spot, hard=hard, info=info, target=target,
                 stop=stop, trail_pts=trail, best_spot=spot, peak_bid=px, worst_bid=px)
    return True


def _manage(bk: Book, feed: core.Feed, ts: datetime, fno: dict[str, float], spot: float, gap: bool, hard: time,
            ci: int | None, b: pd.DataFrame, regime: dict[str, str]) -> None:
    p = bk.pos
    assert p is not None
    bid = core.mark(feed, p.key, ts, fno)
    el = (ts - p.t0).total_seconds() / 60
    reason, px = None, bid
    if gap:
        reason, px = "feed lost", p.last_bid
    elif ts.time() >= hard:
        reason = "hard"
    if bid is not None:
        p.peak_bid, p.worst_bid = max(p.peak_bid, bid), min(p.worst_bid, bid)
        if reason is None and bid <= p.px0 * (1 - SAFETY_LOSS):
            reason = "max loss −25%"
    p.best_spot = max(p.best_spot, spot) if p.d > 0 else min(p.best_spot, spot)
    if reason is None and p.strat == "FADE":
        if p.target is not None and p.d * (spot - p.target) >= 0:
            reason = "target (mean)"
        elif p.stop is not None and -p.d * (spot - p.stop) >= 0:
            reason = "stop (one swing further)"
        elif el >= 10:
            reason = "time 10 min"
    elif reason is None and p.strat == "TREND":
        if p.trail_pts is not None and p.d * (p.best_spot - spot) >= p.trail_pts:
            reason = "trail 1.5 swings"
        elif ci is not None and regime[bk.variant.name] != ("TREND-UP" if p.d > 0 else "TREND-DOWN"):
            reason = "regime change"
        elif el >= 60:
            reason = "time 60 min"
    if bid is not None:
        p.last_bid = bid
    if reason and px is not None:
        pnl = round((px - p.px0 - CHARGES) * LOT)
        bk.trades.append(p.info | {"date": str(feed.day), "variant": bk.variant.name, "strat": p.strat, "key": p.key,
                                   "entry": p.t0.strftime("%H:%M:%S"), "entry_px": round(p.px0, 2),
                                   "exit": ts.strftime("%H:%M:%S"), "exit_px": round(px, 2), "reason": reason,
                                   "mins": round(el, 1), "best_lot": round((p.peak_bid - p.px0 - CHARGES) * LOT),
                                   "worst_lot": round((p.worst_bid - p.px0 - CHARGES) * LOT), "pnl_lot": pnl})
        bk.day_pnl += pnl
        bk.streak = bk.streak + 1 if pnl <= 0 else 0
        if bk.streak >= LOSS_STREAK:
            bk.pause_until, bk.streak = ts + STREAK_PAUSE, 0
        bk.pos = None


def write_state(feed: core.Feed, ctx: cx.Context, books: list[Book], decisions: list[dict[str, Any]],
                context_rows: list[dict[str, Any]]) -> None:
    ts, idx, fno = feed.ltp[-1]
    last = context_rows[-1] if context_rows else {}
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
        v = variants.setdefault(bk.variant.name, {"variant": bk.variant.name})
        v[bk.strat] = {"trades": len(bk.trades), "total": int(sum(t["pnl_lot"] for t in bk.trades))}
        v["total"] = v.get("total", 0) + v[bk.strat]["total"]
    state = {"updated": datetime.now().isoformat(timespec="seconds"), "feed_ts": ts.isoformat(timespec="seconds"),
             "day": str(feed.day), "version": VERSION, "context": last,
             "ib": ctx.ib, "gap_pct": ctx.gap_pct, "openvol_x": ctx.openvol_x, "expiry_today": ctx.expiry_today,
             "status": status, "decisions": decisions[-25:],
             "trades": [t for bk in books if bk.variant.name == "MAIN" for t in bk.trades],
             "variants": list(variants.values())}
    tmp = core.OUT / "state.tmp"
    tmp.write_text(json.dumps(state, default=str), encoding="utf-8")
    tmp.replace(core.OUT / "state.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=str(date.today()))
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    day = date.fromisoformat(a.day)
    core.OUT.mkdir(parents=True, exist_ok=True)
    feed = core.Feed(day)
    print(f"U3 {VERSION} paper watcher for {day} (PAPER ONLY; reads the recorder read-only). Rules: docs/U3_README.md")
    books: list[Book] = []
    shown = 0
    while True:
        feed.update()
        if len(feed.ltp) > 50:
            ctx = cx.build(feed)
            books, decisions, crow = run_day(feed, ctx)
            write_state(feed, ctx, books, decisions, crow)
            pd.DataFrame([t for bk in books for t in bk.trades]).to_csv(core.OUT / f"{day}_trades.csv", index=False)
            pd.DataFrame(decisions).to_csv(core.OUT / f"{day}_decisions.csv", index=False)
            pd.DataFrame(crow).to_csv(core.OUT / f"{day}_context.csv", index=False)
            main_tr = [t for bk in books if bk.variant.name == "MAIN" for t in bk.trades]
            for t in sorted(main_tr, key=lambda x: x["entry"])[shown:]:
                print(f"{t['strat']:5s} {t['entry']} {t.get('side', '')} {t['key']} @ {t['entry_px']} → {t['exit']} "
                      f"@ {t['exit_px']} [{t['reason']}] = ₹{t['pnl_lot']}/lot (best {t['best_lot']})", flush=True)
            shown = len(main_tr)
        if a.once or datetime.now().time() >= time(15, 12):
            for bk in books:
                if bk.trades or bk.variant.name == "MAIN":
                    print(f"{bk.variant.name:8s} {bk.strat:5s}: {len(bk.trades):2d} trades, "
                          f"₹{sum(t['pnl_lot'] for t in bk.trades):+,}")
            break
        _time.sleep(20)


if __name__ == "__main__":
    main()
