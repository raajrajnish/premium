"""U2 paper watcher: Gate 1 (checklist) + Gate 2 / in-trade health engine, MAIN plus shadow variants.
Rules: docs/U2_README.md. Reads the recorder read-only; writes only premium/data/u2/. PAPER ONLY.
Every poll replays the day deterministically, so a restart gives the same result.
Usage: uv run python scripts/u2_watch.py [--day YYYY-MM-DD] [--once]
"""

import argparse
import json
import subprocess
import sys
import time as _time
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import u2_core as core
import u2_health as hl

VERSION = "v0.2"
LOT, CHARGES = 65, 1.5
SIG_START, SIG_END, ENTRY_END, HARD = time(9, 45), time(14, 30), time(14, 35), time(15, 10)


@dataclass(frozen=True)
class Config:
    name: str
    enter_hold: int = 30          # s of POSITIVE needed to enter
    exit_hold: int = 20           # s of NEGATIVE needed to exit
    breath: float = 0.25          # share of the peak gain the trail may give back
    skip_hold: int = 20           # s of NEGATIVE while waiting → skip
    wait_max: int = 300           # s to wait for confirmation
    max_loss: float = 0.20        # option −20% → exit
    noprog_swings: float = 6.0    # no progress for this many swing periods (only when not in profit)
    max_unprofitable: int = 1200  # s without being in profit → exit
    news: bool = False            # v0.2: apply the news/event rules (README §10); MAIN only logs them


VARIANTS = [Config("MAIN"), Config("E15", enter_hold=15), Config("E45", enter_hold=45), Config("E60", enter_hold=60),
            Config("X10", exit_hold=10), Config("X30", exit_hold=30), Config("X45", exit_hold=45),
            Config("B20", breath=0.20), Config("B33", breath=0.33), Config("NEWS", news=True)]
GAP_LARGE, BIAS_CONF, AGAINST_HOLD, VIX_Z, VIX_PAUSE = 0.5, 0.5, 45, 3.0, timedelta(minutes=5)


@dataclass
class News:
    """Morning context card + live opening gap (README §10). Built once per replay; deterministic."""
    card: dict[str, Any]
    open_px: float | None
    gap_pct: float | None
    windows: list[tuple[datetime, datetime, datetime, str]]
    bias_dir: int

    def in_window(self, ts: datetime) -> str | None:
        return next((n for a, b, _, n in self.windows if a <= ts <= b), None)

    def event_soon(self, ts: datetime) -> bool:
        return any(timedelta(0) <= t - ts <= timedelta(minutes=2) for _, _, t, _ in self.windows)

    def flags(self, ts: datetime, d: int, vix_guard: bool) -> dict[str, Any]:
        g = self.gap_pct
        return {"event_window": self.in_window(ts) or "", "vix_guard": vix_guard,
                "gap_pct": None if g is None else round(g, 2),
                "gap_with": "none" if g is None or abs(g) < GAP_LARGE else ("with" if g * d > 0 else "against"),
                "bias": self.card.get("bias", "unknown"),
                "bias_with": "n/a" if self.bias_dir == 0 else ("with" if self.bias_dir == d else "against")}


def load_news(feed: core.Feed) -> News:
    f = core.OUT / f"{feed.day}_morning.json"
    card = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    open_px = next((float(i["NSE_NIFTY"]) for ts, i, _ in feed.ltp if ts.time() >= time(9, 15)), None)
    pc = card.get("prev_close")
    gap = (open_px / pc - 1) * 100 if open_px and pc else None
    wins = []
    for w in card.get("event_windows", []):
        t = datetime.combine(feed.day, datetime.strptime(w["time"], "%H:%M").time())
        wins.append((t - timedelta(minutes=10), t + timedelta(minutes=15), t, w["name"]))
    conf = card.get("confidence") or 0
    bias = card.get("bias", "unknown")
    bdir = (1 if bias == "positive" else -1 if bias == "negative" else 0) if conf >= BIAS_CONF else 0
    return News(card=card, open_px=open_px, gap_pct=gap, windows=wins, bias_dir=bdir)


@dataclass
class Pos:
    d: int
    key: str
    px0: float
    t0: datetime
    spot0: float
    sig_min: str
    cls: str
    h0: float
    hard: time
    peak_bid: float
    worst_bid: float
    cusum: hl.Cusum
    floor: float | None = None
    tightened: bool = False
    below_since: datetime | None = None
    last_pos_health: datetime | None = None
    last_bid: float | None = None
    flags: dict[str, Any] = field(default_factory=dict)


@dataclass
class Engine:
    cfg: Config
    trades: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    pos: Pos | None = None
    wait: dict[str, Any] | None = None


def run_day(feed: core.Feed, h: hl.Health, news: News | None = None) -> list[Engine]:
    news = news or load_news(feed)
    vix_until: datetime | None = None
    tk = h.ticks
    ms = h.minutes.set_index("done") if len(h.minutes) else h.minutes
    pend = h.pendulum
    engines = [Engine(c) for c in VARIANTS]
    state = {e.cfg.name: {"since": None, "state": "NEUTRAL"} for e in engines}   # held-time tracking per side
    held: dict[int, dict[str, Any]] = {1: {"state": None, "since": None}, -1: {"state": None, "since": None}}
    prev_ts = None
    done_iter = iter(sorted(ms.index)) if len(ms) else iter([])
    next_done = next(done_iter, None)
    for ts, idx, fno in feed.ltp:
        if ts not in tk.index:
            continue
        row = tk.loc[ts]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[-1]
        hup = float(row["health"])
        if float(row.get("z_vix", 0.0)) <= -VIX_Z:            # VIX jumped sharply within 60 s
            vix_until = ts + VIX_PAUSE
        vix_guard = vix_until is not None and ts < vix_until
        # held time of each side's state
        for d in (1, -1):
            st = hl.state_of(d * hup)
            if held[d]["state"] != st:
                held[d] = {"state": st, "since": ts}
        minute = None
        while next_done is not None and ts >= next_done:
            minute = ms.loc[next_done]
            next_done = next(done_iter, None)
        gap = prev_ts is not None and (ts - prev_ts).total_seconds() > 60
        prev_ts = ts
        spot = float(idx["NSE_NIFTY"])
        sig_sd = float(h.tick_sigma.get(ts, 1.0)) if ts in h.tick_sigma.index else 1.0
        sw = pend[pend.index <= ts].iloc[-1] if len(pend) and (pend.index <= ts).any() else None
        swing_pts = float(sw.swing_pts) if sw is not None else 8.0
        swing_secs = float(sw.swing_secs) if sw is not None else 90.0
        for e in engines:
            c = e.cfg
            if e.pos is not None:
                if c.news and (news.event_soon(ts) or vix_guard):  # tighten before an event / on a VIX jump
                    e.pos.tightened = True
                _manage(e, feed, ts, fno, spot, hup, held, minute, gap, sig_sd, swing_pts, swing_secs)
                continue
            # new Gate-1 signal at a completed minute
            if minute is not None and minute["sig"] is not None:
                sig = minute["sig"]
                if SIG_START <= pd.Timestamp(minute["minute"]).time() <= SIG_END:
                    d = int(sig["dir"])
                    if e.wait is not None and e.wait["d"] != d:
                        e.decisions.append(e.wait | {"decision": "SKIP", "why": "opposite signal", "at": ts})
                        e.wait = None
                    if e.wait is None:
                        w0 = {"d": d, "side": sig["side"], "signal": sig["minute"], "cls": sig["class"],
                              "conf": sig["confirmations"], "start": ts, "h_signal": round(d * hup, 2),
                              **news.flags(ts, d, vix_guard)}
                        if c.news and w0["gap_pct"] is not None and abs(w0["gap_pct"]) >= GAP_LARGE \
                                and ts.time() < time(10, 0):
                            e.decisions.append(w0 | {"decision": "SKIP", "why": "large gap: before 10:00", "at": ts})
                        else:
                            e.wait = w0
            if e.wait is None:
                continue
            w, d = e.wait, e.wait["d"]
            hs = held[d]
            why = None
            blocked = c.news and (news.in_window(ts) is not None or vix_guard)   # wait, but don't enter
            hold = AGAINST_HOLD if (c.news and news.bias_dir not in (0, d)) else c.enter_hold
            if minute is not None:
                comp = minute["up"] if d > 0 else minute["dn"]
                if not (comp["vwap"] and comp["ema_order"] and comp["ema_slope"]):
                    why = "trend broke"
                elif comp["confirmations"] >= 4 and comp["volume"] and ts.time() <= ENTRY_END and not blocked:
                    _enter(e, feed, ts, fno, spot, hup, "re-confirmation", news.flags(ts, d, vix_guard))
                    continue
            if why is None and hs["state"] == "NEGATIVE" and (ts - hs["since"]).total_seconds() >= c.skip_hold:
                why = "health negative"
            if why is None and (ts - w["start"]).total_seconds() > c.wait_max:
                why = "expired"
            if why is None and ts.time() > ENTRY_END:
                why = "entry window closed"
            if why:
                e.decisions.append(w | {"decision": "SKIP", "why": why, "at": ts})
                e.wait = None
                continue
            if not blocked and hs["state"] == "POSITIVE" and (ts - hs["since"]).total_seconds() >= hold:
                _enter(e, feed, ts, fno, spot, hup, f"health positive {hold}s", news.flags(ts, d, vix_guard))
    for e in engines:                                        # day ended with a wait still open
        if e.wait is not None:
            e.decisions.append(e.wait | {"decision": "WAITING", "why": "", "at": None})
    _ = state
    return engines


def _enter(e: Engine, feed: core.Feed, ts: datetime, fno: dict[str, float], spot: float, hup: float,
           how: str, flags: dict[str, Any] | None = None) -> None:
    w, d = e.wait, e.wait["d"]
    side = "CE" if d > 0 else "PE"
    strike = int(round(spot / 50) * 50)
    keys = sorted(k for k in fno if (mm := core.OPT.match(k)) and int(mm.group(2)) == strike and mm.group(3) == side)
    if not keys:
        e.decisions.append(w | {"decision": "SKIP", "why": "no ATM option price", "at": ts})
        e.wait = None
        return
    key = keys[0]
    q = feed.quote(key, ts)
    px = q[1] if q else float(fno[key]) + 0.5
    exp = core.expiry_of(key)
    e.pos = Pos(d=d, key=key, px0=px, t0=ts, spot0=spot, sig_min=w["signal"], cls=w["cls"], h0=round(d * hup, 2),
                hard=time(14, 45) if exp == feed.day else HARD, peak_bid=px, worst_bid=px, cusum=hl.Cusum(d),
                flags=flags or {})
    e.decisions.append(w | {"decision": "ENTER", "why": how, "at": ts,
                            "waited_s": int((ts - w["start"]).total_seconds())})
    e.wait = None


def _manage(e: Engine, feed: core.Feed, ts: datetime, fno: dict[str, float], spot: float, hup: float,
            held: dict[int, dict[str, Any]], minute: pd.Series | None, gap: bool, sig_sd: float,
            swing_pts: float, swing_secs: float) -> None:
    p, c = e.pos, e.cfg
    assert p is not None
    q = feed.quote(p.key, ts)
    last = fno.get(p.key)
    bid = q[0] if q else (float(last) - 0.5 if last is not None else None)
    alarm = p.cusum.update(spot, sig_sd, swing_pts)
    hd = p.d * hup
    if hl.state_of(hd) == "POSITIVE":
        p.last_pos_health = ts
    reason, px = None, bid
    el = (ts - p.t0).total_seconds()
    swing_opt = 0.5 * swing_pts
    if gap:
        reason, px = "feed lost", p.last_bid
    elif ts.time() >= p.hard:
        reason = "hard"
    if bid is not None:
        p.peak_bid, p.worst_bid = max(p.peak_bid, bid), min(p.worst_bid, bid)
        pnl_u = bid - p.px0 - CHARGES
        peak_gain = p.peak_bid - p.px0
        if reason is None and bid <= p.px0 * (1 - c.max_loss):
            reason = "max loss"
        if reason is None and minute is not None:                     # opposite side, at a 1-min close
            oc = minute["dn"] if p.d > 0 else minute["up"]
            if oc["trend"] and oc["trigger"] and oc["confirmations"] >= 3:
                reason = "opposite valid"
            elif oc["ema_order"] and oc["ema_slope"]:
                if bid / p.px0 - 1 <= 0.10:
                    reason = "opposite trend"
                else:
                    p.floor = max(p.floor or 0.0, p.px0 + 0.75 * peak_gain)
                    p.tightened = True
            elif oc["trigger"]:
                p.tightened = True
                if pnl_u > 0:
                    p.floor = max(p.floor or 0.0, p.px0 + CHARGES)
        hs = held[p.d]
        if reason is None and hs["state"] == "NEGATIVE" and (ts - hs["since"]).total_seconds() >= c.exit_hold \
                and hs["since"] >= p.t0:
            reason = "health negative"
        if reason is None and alarm:
            reason = "cusum alarm"
        if reason is None and minute is not None and pnl_u > 0 and hd < 0 and p.last_pos_health is not None \
                and (ts - p.last_pos_health).total_seconds() <= 120 and \
                (minute["exh_up"] if p.d > 0 else minute["exh_dn"]):
            reason = "exhaustion"
        if reason is None and peak_gain >= max(swing_opt, 3.0):       # profit trail
            breath = min(c.breath, 0.15) if p.tightened else c.breath
            fl = max(p.px0 + CHARGES, p.peak_bid - max(swing_opt, breath * peak_gain))
            p.floor = max(p.floor or 0.0, fl)
        if reason is None and p.floor is not None:
            if bid < p.floor:
                p.below_since = p.below_since or ts
                if (ts - p.below_since).total_seconds() >= 10:
                    reason = "trail"
            else:
                p.below_since = None
        if reason is None and pnl_u <= 0:                              # time rules only when NOT in profit
            if el >= c.noprog_swings * swing_secs and peak_gain < swing_opt:
                reason = "no progress"
            elif el >= c.max_unprofitable:
                reason = "20 min not in profit"
        p.last_bid = bid
    if reason and px is not None:
        pnl = round((px - p.px0 - CHARGES) * LOT)
        e.trades.append({"variant": c.name, "date": str(feed.day), "side": "CALL" if p.d > 0 else "PUT",
                         "class": p.cls, "signal_min": p.sig_min, "key": p.key, "entry": p.t0.strftime("%H:%M:%S"),
                         "entry_px": round(p.px0, 2), "health_entry": p.h0, "exit": ts.strftime("%H:%M:%S"),
                         "exit_px": round(px, 2), "reason": reason, "health_exit": round(hd, 2),
                         "mins": round(el / 60, 1), "best_lot": round((p.peak_bid - p.px0 - CHARGES) * LOT),
                         "worst_lot": round((p.worst_bid - p.px0 - CHARGES) * LOT), "pnl_lot": pnl,
                         **{f"news_{k}": v for k, v in p.flags.items()}})
        e.pos = None


def write_state(feed: core.Feed, h: hl.Health, engines: list[Engine]) -> None:
    tk = h.ticks
    last = tk.iloc[-1]
    ts, idx, fno = feed.ltp[-1]
    hup = float(last["health"])
    side = {}
    for d, name in ((1, "CALL"), (-1, "PUT")):
        st = hl.state_of(d * hup)
        since = ts
        for t_, v in zip(reversed(tk.index), reversed(tk.health.to_numpy()), strict=False):
            if hl.state_of(d * v) != st:
                break
            since = t_
        plus, minus = hl.top_factors(last, d)
        side[name] = {"health": round(d * hup, 2), "state": st, "held_s": int((ts - since).total_seconds()),
                      "plus": plus, "minus": minus}
    main = engines[0]
    status: dict[str, Any] = {"mode": "idle"}
    if main.wait is not None:
        w = main.wait
        status = {"mode": "waiting", "side": w["side"], "signal": w["signal"], "class": w["cls"],
                  "waiting_s": int((ts - w["start"]).total_seconds())}
    elif main.pos is not None:
        p = main.pos
        q = feed.quote(p.key, ts)
        lp = fno.get(p.key)
        bid = q[0] if q else (float(lp) - 0.5 if lp is not None else None)
        status = {"mode": "in trade", "side": "CALL" if p.d > 0 else "PUT", "key": p.key,
                  "entry": p.t0.strftime("%H:%M:%S"),
                  "entry_px": round(p.px0, 2), "bid": bid, "floor": round(p.floor, 2) if p.floor else None,
                  "tightened": p.tightened,
                  "pnl_lot": round((bid - p.px0 - CHARGES) * LOT) if bid is not None else None,
                  "best_lot": round((p.peak_bid - p.px0 - CHARGES) * LOT)}
    pend = h.pendulum.iloc[-1] if len(h.pendulum) else None
    nw = load_news(feed)
    card = nw.card
    morning = {"built_at": card.get("built_at"), "bias": card.get("bias", "unknown"),
               "confidence": card.get("confidence"),
               "event_risk": card.get("event_risk", "none"), "windows": card.get("event_windows", []),
               "headlines": card.get("headlines", [])[:5], "global": card.get("global_cues", {}),
               "summary": card.get("summary", ""), "llm_error": card.get("llm_error"),
               "prev_close": card.get("prev_close"), "open": nw.open_px,
               "gap_pct": None if nw.gap_pct is None else round(nw.gap_pct, 2),
               "in_window_now": nw.in_window(ts) or "", "vix_z_now": round(float(last.get("z_vix", 0.0)), 2)}
    spark = tk.health.resample("1min").last().dropna().tail(120)
    state = {"updated": datetime.now().isoformat(timespec="seconds"), "feed_ts": ts.isoformat(timespec="seconds"),
             "day": str(feed.day), "version": VERSION, "side": side, "status": status, "morning": morning,
             "pendulum": {"swing_pts": round(float(pend.swing_pts), 1), "swing_secs": round(float(pend.swing_secs))}
             if pend is not None else None,
             "health_series": [{"t": int(pd.Timestamp(t).timestamp()), "v": round(float(v), 3)}
                               for t, v in spark.items()],
             "decisions": [_ser(x) for x in main.decisions[-25:]],
             "trades": main.trades,
             "variants": [{"variant": e.cfg.name, "trades": len(e.trades),
                           "total": int(sum(t["pnl_lot"] for t in e.trades)),
                           "wins": sum(1 for t in e.trades if t["pnl_lot"] > 0),
                           "open": e.pos is not None} for e in engines]}
    tmp = core.OUT / "state.tmp"
    tmp.write_text(json.dumps(state, default=str), encoding="utf-8")
    tmp.replace(core.OUT / "state.json")


def _ser(x: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in x.items():
        if isinstance(v, datetime):
            out[k] = v.strftime("%H:%M:%S")
        elif k == "start":
            continue
        else:
            out[k] = v
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=str(date.today()))
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()
    day = date.fromisoformat(a.day)
    core.OUT.mkdir(parents=True, exist_ok=True)
    feed = core.Feed(day)
    shown = 0
    print(f"U2 {VERSION} paper watcher for {day} (PAPER ONLY; reads the recorder read-only). Rules: docs/U2_README.md")
    engines: list[Engine] = []
    card_started = False
    while True:
        card_file = core.OUT / f"{day}_morning.json"
        if not card_started and not card_file.exists() and not a.once and day == date.today():
            # one background build; the card is frozen once written (README §10)
            subprocess.Popen([sys.executable, str(Path(__file__).with_name("u2_morning.py")), "--day", str(day)])  # noqa: S603
            card_started = True
        feed.update()
        if len(feed.ltp) > 50:
            h = hl.build(feed)
            engines = run_day(feed, h)
            write_state(feed, h, engines)
            pd.DataFrame([t for e in engines for t in e.trades]).to_csv(core.OUT / f"{day}_trades.csv", index=False)
            pd.DataFrame([_ser(x) | {"variant": e.cfg.name} for e in engines for x in e.decisions]).to_csv(
                core.OUT / f"{day}_decisions.csv", index=False)
            for t in engines[0].trades[shown:]:
                print(f"{t['entry']} {t['side']} {t['key']} @ {t['entry_px']} → {t['exit']} @ {t['exit_px']} "
                      f"[{t['reason']}] = ₹{t['pnl_lot']}/lot (best {t['best_lot']})", flush=True)
            shown = len(engines[0].trades)
        if a.once or datetime.now().time() >= time(15, 12):
            for e in engines:
                print(f"{e.cfg.name:5s}: {len(e.trades):2d} trades, total ₹{sum(t['pnl_lot'] for t in e.trades):+,}")
            break
        _time.sleep(20)


if __name__ == "__main__":
    main()
