"""U1 daily review: the same facts, computed the same way, every day (used by the /u1-daily-review skill).

Outputs
  docs/u1_daily/<day>.md         facts per trade (narrative sections are written afterwards, per the skill)
  data/u1/reviews/<day>.json     tags + hypothesis outcomes per trade
  docs/U1_HYPOTHESES.md          running scoreboard of every hypothesis across all reviewed days
  docs/U2_FACTOR_SCORECARD.md    Q6: live factor scorecard across all reviewed days (which indicator changes lead Nifty)
Covers U1 and, when its files exist, U2 (docs/U2_README.md). Live data only.

Read-only on the recorder files and U1 outputs.
Usage: uv run python scripts/u1_daily_review.py [--day YYYY-MM-DD]
"""

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import u1_watch as u
import u2_core as u2c
import u2_health as u2h

ROOT = Path(__file__).resolve().parents[1]
DOCS, REVIEWS = ROOT / "docs" / "u1_daily", ROOT / "data" / "u1" / "reviews"
MODELS = ("EC0", "EC1", "EC2", "EC2P")
TIME_EXITS = {"time", "F no progress", "G max hold"}
DATA_U2 = ROOT / "data" / "u2"
DATA_U3 = ROOT / "data" / "u3"
DATA_U4 = ROOT / "data" / "u4"
LABEL = {"EC0": "EC0", "EC1": "EC1", "EC2": "EC2", "EC2P": "EC2+"}
HYP = {
    "H1": "Entry right after a burst candle → the option dips below the entry price within 5 min",
    "H2": "Pause, not failure: a dull phase (≤1 confirmation) with the trend intact is later followed by +15 pts",
    "H3": "Re-confirmation (≥4 confirmations + volume ≥1.5× after a dull phase) is followed by ≥ +10 pts within 5 min",
    "H4": "Exhaustion exit (RSI>80, heavyweights turning, or a volume spike without a new high, after +10 pts) "
    "beats EC0's exit",
    "H5": "Early exits (no progress / breakeven / loss limit in the first 6 min) miss a later move worth ≥ ₹500",
    "H6": "Futures buy/sell quantity ratio ≥ 0.70 at entry → GOOD trade (+15 before −12 within 15 min)",
}


def fmt(v: float | None) -> str:
    return "—" if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v:+,.0f}"


def md_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_no minute data_"
    cols = list(rows[0])
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join("" if r[c] is None else str(r[c]) for c in cols) + " |" for r in rows]
    return "\n".join(out)


def order_book(day: date, symbols: set[str]) -> dict[str, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    with (u.RAW / f"date={day}" / "quotes.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if not any(s in line for s in symbols):
                continue
            try:
                j = json.loads(line)
            except ValueError:
                continue
            s = j.get("symbol", "")
            if s in symbols:
                rows.append(
                    {
                        "ts": datetime.fromisoformat(j["recv_ts"]).replace(tzinfo=None),
                        "sym": s,
                        "tb": j.get("total_buy_qty"),
                        "tsq": j.get("total_sell_qty"),
                    }
                )
    if not rows:
        return {}
    df = pd.DataFrame(rows).set_index("ts")
    return {s: g.resample("1min").last() for s, g in df.groupby("sym")}


def ratio(ob: dict[str, pd.DataFrame], sym: str, m: pd.Timestamp) -> float | None:
    g = ob.get(sym)
    if g is None or m not in g.index or not g.loc[m, "tsq"]:
        return None
    return round(float(g.loc[m, "tb"]) / float(g.loc[m, "tsq"]), 2)


def review(day: date) -> tuple[str, dict[str, Any]]:
    trades = pd.read_csv(u.OUT / f"{day}_trades.csv")
    signals = pd.read_csv(u.OUT / f"{day}_signals.csv")
    feed = u.Feed(day)
    feed.update()
    b = u.minute_frame(feed)
    ver = u.version(day)
    fut_sym = ""
    with (u.RAW / f"date={day}" / "quotes.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if "FUT" in line:
                s = json.loads(line).get("symbol", "")
                if s.startswith("NIFTY") and s.endswith("FUT"):
                    fut_sym = s
                    break
    ob = order_book(day, {fut_sym} | {k[4:] for k in trades.key})
    models = [m for m in MODELS if f"{m}_pnl" in trades.columns and trades[f"{m}_pnl"].notna().any()] or ["EC0"]
    if models == ["EC0"] and "EC0_pnl" not in trades.columns:
        trades["EC0_pnl"], trades["EC0_reason"], trades["EC0_exit"] = trades.pnl_lot, trades.reason, trades.exit
    out_trades: list[dict[str, Any]] = []
    md: list[str] = []
    pend = []
    for n, r in trades.reset_index(drop=True).iterrows():
        d = 1 if r.side == "CALL" else -1
        t0 = datetime.combine(day, datetime.strptime(r.entry, "%H:%M:%S").time())
        exits = {m: datetime.combine(day, datetime.strptime(str(r[f"{m}_exit"]), "%H:%M:%S").time()) for m in models}
        end = min(
            max(max(exits.values()), t0 + timedelta(minutes=20)),
            t0 + timedelta(minutes=30),
            datetime.combine(day, u.HARD),
            feed.ltp[-1][0],
        )
        path = []
        for ts, idx, fno in feed.ltp:
            if t0 <= ts <= end:
                mk = u.mark(feed, r.key, ts, fno)
                if mk is not None:
                    path.append(
                        (ts, d * (float(idx["NSE_NIFTY"]) - r.nifty), (mk - r.entry_px - u.CHARGES) * u.LOT, mk)
                    )
        if len(path) < 3:
            continue
        pts, pnl = np.array([p[1] for p in path]), np.array([p[2] for p in path])
        k_pk, k_lo = int(pnl.argmax()), int(pnl.argmin())
        per_model = {}
        for m in models:
            w = [p for p in path if p[0] <= exits[m]]
            per_model[m] = {
                "exit": str(r[f"{m}_exit"]),
                "reason": str(r[f"{m}_reason"]),
                "pnl": float(r[f"{m}_pnl"]),
                "best": max(p[2] for p in w) if w else None,
                "worst": min(p[2] for p in w) if w else None,
            }
            after = [p[2] for p in path if exits[m] < p[0] <= exits[m] + timedelta(minutes=10)]
            pm = per_model[m]
            pm["after_best"] = max(after) if after else None  # Q4: best P&L in the 10 min after the exit
            pm["kept_pct"] = round(100 * pm["pnl"] / pm["best"]) if pm["best"] and pm["best"] > 0 else None
            pm["time_exit_in_profit"] = bool(pm["reason"] in TIME_EXITS and pm["pnl"] > 0)  # Q3
        # GOOD label: +15 before −12 within 15 min
        good = None
        for ts, g, _, _ in path:
            if ts > t0 + timedelta(minutes=15):
                break
            if g <= -12:
                good = False
                break
            if g >= 15:
                good = True
                break
        good = bool(good) if good is not None else False
        # minute table + tags
        sig_m = pd.Timestamp(datetime.combine(day, datetime.strptime(r.signal_min, "%H:%M").time()))
        mins = pd.date_range(
            sig_m - timedelta(minutes=1), pd.Timestamp(end).floor("1min") - timedelta(minutes=1), freq="1min"
        )
        rows, tags = [], {"dull": [], "failure": [], "reconfirm": [], "exhaustion": []}
        best_close, seen_dull, reached10 = -1e9, False, False
        for m in mins:
            if m not in b.index:
                continue
            i = b.index.get_loc(m)
            if i < 26:
                continue
            c = u.components(b, i, feed, d, ver)
            oc = u.components(b, i, feed, -d, ver)
            row, b3, p1 = b.iloc[i], b.iloc[i - 3], b.iloc[i - 1]
            g_close = d * (row.close - r.nifty)
            rsi_d = row.rsi if d > 0 else 100 - row.rsi
            vol_x = float(row.fvol / row.fvol_avg20) if row.fvol_avg20 else np.nan
            hv_against = sum(d * (row[x] - b3[x]) < 0 for x in ("bn", "hdfc", "icici")) >= 2
            trend_ok = c["vwap"] and c["ema_order"] and c["ema_slope"]
            opp_valid = oc["trend"] and oc["trigger"] and oc["confirmations"] >= 3
            after_entry = m >= sig_m + timedelta(minutes=1)
            tag = []
            if after_entry:
                if not trend_ok or opp_valid:
                    tag.append("FAILURE")
                    tags["failure"].append(m.strftime("%H:%M"))
                elif c["confirmations"] <= 1:
                    tag.append("dull")
                    tags["dull"].append(m.strftime("%H:%M"))
                    seen_dull = True
                if seen_dull and c["confirmations"] >= 4 and vol_x >= 1.5 and "dull" not in tag:
                    tag.append("RE-CONFIRM")
                    tags["reconfirm"].append(m.strftime("%H:%M"))
                reached10 = reached10 or g_close >= 10
                newhigh = g_close > best_close
                if reached10 and (
                    rsi_d > 80 or (hv_against and best_close - g_close <= 5) or (vol_x >= 2.5 and not newhigh)
                ):
                    tag.append("EXHAUSTION")
                    tags["exhaustion"].append(m.strftime("%H:%M"))
                best_close = max(best_close, g_close)
            rows.append(
                {
                    "min": m.strftime("%H:%M"),
                    "Nifty": f"{row.close:,.1f}",
                    "vs entry": f"{g_close:+.1f}",
                    "chg": f"{d * (row.close - p1.close):+.1f}",
                    "trend": "".join("Y" if c[k] else "." for k in ("vwap", "ema_order", "ema_slope")),
                    "trig": ("B" if c["trigger_band"] else ".") + ("5" if c["trigger_break"] else "."),
                    "SVHXO": "".join("Y" if c[k] else "." for k in ("strength", "volume", "heavyweights", "vix", "oi")),
                    "conf": c["confirmations"],
                    "RSI*": round(rsi_d),
                    "vol×": round(vol_x, 1),
                    "fut−VWAP*": round(d * (row.fpx - row.vwap), 1),
                    "BN 3m*": round(d * (row.bn - b3.bn)),
                    "VIX": round(row.vix, 2),
                    "fut B/S": ratio(ob, fut_sym, m),
                    "opt B/S": ratio(ob, r.key[4:], m),
                    "tags": " ".join(tag),
                }
            )
        # hypotheses
        sig_i = b.index.get_loc(sig_m) if sig_m in b.index else None
        burst = False
        if sig_i is not None and sig_i > 21:
            mv = abs(b.close.iloc[sig_i] - b.close.iloc[sig_i - 1])
            burst = bool(mv >= 2 * b.close.diff().abs().iloc[sig_i - 20 : sig_i].mean())
        h: dict[str, Any] = {}
        if burst:
            h["H1"] = bool(any(p[3] < r.entry_px for p in path if p[0] <= t0 + timedelta(minutes=5)))
        if tags["dull"] and (not tags["failure"] or tags["dull"][0] < tags["failure"][0]):
            first_dull = datetime.combine(day, datetime.strptime(tags["dull"][0], "%H:%M").time())
            h["H2"] = bool(any(p[1] >= 15 for p in path if p[0] > first_dull))
        if tags["reconfirm"]:
            rc = pd.Timestamp(datetime.combine(day, datetime.strptime(tags["reconfirm"][0], "%H:%M").time()))
            base = d * (b.loc[rc, "close"] - r.nifty)
            h["H3"] = bool(
                any(p[1] >= base + 10 for p in path if rc + timedelta(minutes=1) <= p[0] <= rc + timedelta(minutes=6))
            )
        exh_val = None
        if tags["exhaustion"]:
            em = datetime.combine(day, datetime.strptime(tags["exhaustion"][0], "%H:%M").time()) + timedelta(minutes=1)
            w = [p for p in path if p[0] >= em]
            if w:
                exh_val = float(w[0][2])
                h["H4"] = bool(exh_val > float(r["EC0_pnl"]))
        missed = []
        for m in models:
            pm = per_model[m]
            if pm["reason"] in ("F no progress", "C breakeven", "breakeven", "loss limit") and exits[
                m
            ] <= t0 + timedelta(minutes=6):
                later = [p[2] for p in path if p[0] > exits[m]]
                if later:
                    missed.append(bool(max(later) - pm["pnl"] >= 500))
        if missed:
            h["H5"] = any(missed)
        fbs = ratio(ob, fut_sym, pd.Timestamp(t0).floor("1min"))
        if fbs is not None:
            h["H6"] = {"ratio": fbs, "high": fbs >= 0.70, "good": good}
        rec = {
            "n": n + 1,
            "side": r.side,
            "class": r["class"],
            "quality": r.get("quality"),
            "entry": r.entry,
            "entry_px": r.entry_px,
            "key": r.key,
            "good": good,
            "burst_entry": burst,
            "peak_pnl": float(pnl[k_pk]),
            "peak_at": path[k_pk][0].strftime("%H:%M:%S"),
            "low_pnl": float(pnl[k_lo]),
            "low_at": path[k_lo][0].strftime("%H:%M:%S"),
            "best_pts": float(pts.max()),
            "worst_pts": float(pts.min()),
            "models": per_model,
            "tags": tags,
            "exhaustion_exit_pnl": exh_val,
            "hypotheses": h,
        }
        out_trades.append(rec)
        # markdown
        md.append(
            f"\n## Trade {n + 1}: {r.side} {r['class']} (quality {r.get('quality')}), signal {r.signal_min}, "
            f"entry {r.entry} @ ₹{r.entry_px} ({r.key.replace('NSE_', '')})\n"
        )
        md.append(
            f"- **Path (to {end:%H:%M}):** peak **₹{fmt(rec['peak_pnl'])}** at {rec['peak_at']}, "
            f"low ₹{fmt(rec['low_pnl'])} at {rec['low_at']}; Nifty best {pts.max():+.1f} / worst {pts.min():+.1f} pts; "
            f"GOOD (+15 before −12 in 15 min): **{'yes' if good else 'no'}**; burst entry: {'yes' if burst else 'no'}"
        )
        md.append(
            "\n| Model | Exit | Reason | ₹ | Best while open | Worst while open | Kept % of its best "
            "| Best ₹ in 10 min after exit | Time exit while in profit? |\n|---|---|---|---|---|---|---|---|---|"
        )
        for m in models:
            pm = per_model[m]
            md.append(
                f"| {LABEL[m]} | {pm['exit']} | {pm['reason']} | **{fmt(pm['pnl'])}** | {fmt(pm['best'])} | "
                f"{fmt(pm['worst'])} | {pm['kept_pct'] if pm['kept_pct'] is not None else '—'}% | "
                f"{fmt(pm['after_best'])} | {'⚠ yes' if pm['time_exit_in_profit'] else 'no'} |"
            )
        md.append("\n*Starred columns are direction-adjusted (+ = in the trade's favour).*\n")
        md.append(md_table(rows))
        md.append("\n**Auto tags:** " + "; ".join(f"{k}: {', '.join(v) or '—'}" for k, v in tags.items()))
        md.append(
            "\n**Hypotheses:** "
            + (", ".join(f"{k} = {v if not isinstance(v, dict) else v}" for k, v in h.items()) or "none applicable")
        )
        md.append("\n### Narrative (Q1–Q5 per the /u1-daily-review skill)\n\n_TODO_\n")
        pend.append(n + 1)
    # header + summary
    head = [
        f"# Daily review: {day} (U1 {ver}; U2 if it ran)\n",
        f"Generated {datetime.now():%Y-%m-%d %H:%M} by `scripts/u1_daily_review.py`. Facts are computed; "
        "narratives follow the skill's fixed questions.\n",
        f"- **Signals:** {len(signals)} (taken {int(signals.taken.sum())}); skipped because: "
        + (", ".join(f"{k} {v}" for k, v in signals[~signals.taken].why_not.fillna("?").value_counts().items()) or "—"),
        f"- **Trades:** {len(out_trades)}\n",
        "| Model | Trades | Total ₹ | Avg ₹ | Wins | Worst ₹ |\n|---|---|---|---|---|---|",
    ]
    for m in models:
        p = trades[f"{m}_pnl"].astype(float)
        head.append(
            f"| {LABEL[m]} | {len(p)} | **{fmt(p.sum())}** | {fmt(p.mean())} | {int((p > 0).sum())} | {fmt(p.min())} |"
        )
    head.append(
        "\n| # | Side | Class | Q | Entry | Peak ₹ (time) | Low ₹ | GOOD | "
        + " | ".join(LABEL[m] for m in models)
        + " |\n|"
        + "---|" * (8 + len(models))
    )
    for t in out_trades:
        head.append(
            f"| {t['n']} | {t['side']} | {t['class']} | {t['quality']} | {t['entry'][:5]} @ {t['entry_px']} | "
            f"{fmt(t['peak_pnl'])} ({t['peak_at'][:5]}) | {fmt(t['low_pnl'])} | {'✅' if t['good'] else '❌'} | "
            + " | ".join(f"{fmt(t['models'][m]['pnl'])} ({t['models'][m]['reason']})" for m in models)
            + " |"
        )
    head += missed_signals(signals, b)
    head += u2_section(day, trades, models)
    head += u3_section(day)
    head += u4_section(day)
    fac = factor_day(day)
    head += factor_md(fac)
    head.append("\n## Day summary (written per the skill)\n\n_TODO_\n")
    body = "\n".join(head + md)
    return body, {"day": str(day), "version": ver, "trades": out_trades, "pending_narratives": pend, "factors": fac}


def missed_signals(signals: pd.DataFrame, b: pd.DataFrame) -> list[str]:
    """Q5: every signal NOT taken, why, and what Nifty did in the next 15 min (in the signal's direction)."""
    out = [
        "\n## Q5. Signals not taken (U1)\n",
        "| Signal | Side | Class | Conf | Why not | Best / worst next 15 min (pts) | +15 before −12? |",
        "|---|---|---|---|---|---|---|",
    ]
    rows = signals[~signals.taken]
    if rows.empty:
        return out + ["| — | | | | | | |"]
    for _, s_ in rows.iterrows():
        d = 1 if s_.side == "CALL" else -1
        m = pd.Timestamp(datetime.combine(b.index[0].date(), datetime.strptime(s_.minute, "%H:%M").time()))
        if m not in b.index:
            continue
        i = b.index.get_loc(m)
        nxt = b.iloc[i + 1 : i + 16]
        c0 = float(b.close.iloc[i])
        fav = (nxt.high - c0) if d > 0 else (c0 - nxt.low)
        adv = (nxt.low - c0) if d > 0 else (c0 - nxt.high)
        good = "—"
        for f_, a_ in zip(fav, adv, strict=False):
            if a_ <= -12:
                good = "no"
                break
            if f_ >= 15:
                good = "yes"
                break
        out.append(
            f"| {s_.minute} | {s_.side} | {s_['class']} | {s_.confirmations} | {s_.why_not} | "
            f"{fav.max():+.0f} / {adv.min():+.0f} | {good} |"
        )
    return out


def u2_section(day: date, u1_trades: pd.DataFrame, models: list[str]) -> list[str]:
    """U2 (health engine): MAIN trades, entry decisions, variants, and U1 vs U2 for the day."""
    tf, dfile = DATA_U2 / f"{day}_trades.csv", DATA_U2 / f"{day}_decisions.csv"
    if not tf.exists():
        return ["\n## U2 (health engine)\n", "_U2 did not run on this day._"]
    t = pd.read_csv(tf)
    dec = pd.read_csv(dfile) if dfile.exists() else pd.DataFrame()
    main = t[t.variant == "MAIN"]
    out = ["\n## U2 (health engine)\n", "| Model | Trades | Total ₹ | Wins |", "|---|---|---|---|"]
    for m in models:
        p = u1_trades[f"{m}_pnl"].astype(float)
        out.append(f"| U1 {LABEL[m]} | {len(p)} | {fmt(p.sum())} | {int((p > 0).sum())} |")
    for v, g in t.groupby("variant", sort=False):
        out.append(
            f"| U2 {v} | {len(g)} | {'**' if v == 'MAIN' else ''}{fmt(g.pnl_lot.sum())}"
            f"{'**' if v == 'MAIN' else ''} | {int((g.pnl_lot > 0).sum())} |"
        )
    if not dec.empty:
        dm = dec[dec.variant == "MAIN"]
        out.append(
            f"\n**U2 MAIN entry decisions:** {len(dm)} signals → "
            + ", ".join(f"{k} {v}" for k, v in dm.decision.value_counts().items())
            + "; skip reasons: "
            + (", ".join(f"{k} {v}" for k, v in dm[dm.decision == "SKIP"].why.value_counts().items()) or "—")
        )
    out += [
        "\n| # | Side | Signal | Entry | Health at entry | Exit (why) | Health at exit | Best ₹ | ₹ |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for k, (_, r) in enumerate(main.iterrows(), 1):
        out.append(
            f"| {k} | {r.side} | {r.signal_min} | {r.entry} @ {r.entry_px} | {r.health_entry:+.2f} | "
            f"{r.exit} ({r.reason}) | {r.health_exit:+.2f} | {fmt(r.best_lot)} | **{fmt(r.pnl_lot)}** |"
        )
    return out + q7_news(day, t)


def u3_section(day: date) -> list[str]:
    """U3 (research regime engine): regime of the day, MAIN trades per strategy, decisions, and the ablation grid."""
    tf, df_, cf = DATA_U3 / f"{day}_trades.csv", DATA_U3 / f"{day}_decisions.csv", DATA_U3 / f"{day}_context.csv"
    out = ["\n## U3 (research regime engine)\n"]
    if not cf.exists():
        return [*out, "_U3 did not run on this day._"]
    c = pd.read_csv(cf)
    t = pd.read_csv(tf) if tf.exists() and tf.stat().st_size > 2 else pd.DataFrame()
    dec = pd.read_csv(df_) if df_.exists() and df_.stat().st_size > 2 else pd.DataFrame()
    share = c.day_type.value_counts(normalize=True).mul(100).round().astype(int)
    out.append("- **Day type (minutes, MAIN):** " + ", ".join(f"{k} {v}%" for k, v in share.items()))
    g = c.gex_bn.dropna()
    if len(g):
        out.append(
            f"- **Dealer gamma:** positive in {100 * (g > 0).mean():.0f}% of minutes "
            f"(median {g.median():+.1f} bn); in-play: {'yes' if c.inplay.any() else 'no'}"
        )
    ibh, ibl = c.ib_high.dropna(), c.ib_low.dropna()
    if len(ibh):
        last = float(c.close.iloc[-1])
        inside = ibl.iloc[-1] <= last <= ibh.iloc[-1]
        out.append(
            f"- **Opening range check:** IB {ibl.iloc[-1]:.0f}–{ibh.iloc[-1]:.0f}; the day closed "
            f"{'inside (range-like)' if inside else 'outside (trend-like)'} at {last:.0f}"
        )
    if not dec.empty:
        dm = dec[dec.variant == "MAIN"]
        out.append(
            "- **MAIN decisions:** "
            + ", ".join(f"{s_} {d_} {n}" for (s_, d_), n in dm.groupby(["strat", "decision"]).size().items())
            + "; skip reasons: "
            + (", ".join(f"{k} {v}" for k, v in dm[dm.decision == "SKIP"].why.value_counts().items()) or "—")
        )
    if t.empty:
        return [*out, "- **Trades:** none in any variant."]
    out += ["\n| Variant | FADE ₹ | TREND ₹ | LAST ₹ | Total ₹ | Trades |", "|---|---|---|---|---|---|"]
    for v, gv in t.groupby("variant", sort=False):
        per = {
            s_: gv[gv.strat == s_].pnl_lot.sum() if (gv.strat == s_).any() else None for s_ in ("FADE", "TREND", "LAST")
        }
        out.append(
            f"| {v} | "
            + " | ".join(fmt(per[k]) for k in ("FADE", "TREND", "LAST"))
            + f" | **{fmt(gv.pnl_lot.sum())}** | {len(gv)} |"
        )
    main = t[t.variant == "MAIN"]
    if len(main):
        out += [
            "\n| # | Strat | Side | Regime | Entry | Exit (why) | Expected / needed pts | Best ₹ | ₹ |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for k, (_, r) in enumerate(main.iterrows(), 1):
            out.append(
                f"| {k} | {r.strat} | {r.get('side', '')} | {r.get('regime', '')} | {r.entry} @ {r.entry_px} | "
                f"{r.exit} ({r.reason}) | {r.get('expected_pts', '')} / {r.get('need_pts', '')} | "
                f"{fmt(r.best_lot)} | **{fmt(r.pnl_lot)}** |"
            )
    return out


def u4_section(day: date) -> list[str]:
    """U4 (microstructure & relative value): variants, MAIN trades with their features, decisions."""
    tf, df_ = DATA_U4 / f"{day}_trades.csv", DATA_U4 / f"{day}_decisions.csv"
    out = ["\n## U4 (microstructure & relative value)\n"]
    hk = DATA_U4 / f"{day}_hawkes.json"
    if hk.exists():
        h = json.loads(hk.read_text(encoding="utf-8"))
        out.append(
            f"- **Hawkes fit** (days {', '.join(h.get('days', []))}):"
            f" up n={h['up']['n']}, decay {1 / h['up']['beta']:.0f}s; "
            f"down n={h['down']['n']}, decay {1 / h['down']['beta']:.0f}s"
        )
    if not tf.exists() or tf.stat().st_size <= 2:
        return [*out, "_U4 did not trade (or did not run) on this day._"]
    t = pd.read_csv(tf)
    dec = pd.read_csv(df_) if df_.exists() and df_.stat().st_size > 2 else pd.DataFrame()
    out += ["| Variant | FLOW ₹ | SPREAD ₹ | Total ₹ | Trades | Wins |", "|---|---|---|---|---|---|"]
    for v, gv in t.groupby("variant", sort=False):
        per = {s_: gv[gv.strat == s_].pnl_lot.sum() if (gv.strat == s_).any() else None for s_ in ("FLOW", "SPREAD")}
        out.append(
            f"| {v} | {fmt(per['FLOW'])} | {fmt(per['SPREAD'])} | **{fmt(gv.pnl_lot.sum())}** | {len(gv)} | "
            f"{int((gv.pnl_lot > 0).sum())} |"
        )
    main = t[t.variant == "MAIN"]
    sp = main[main.strat == "SPREAD"]
    if len(sp):
        tl = sp[sp.reason.str.startswith("target") & (sp.pnl_lot <= 0)]
        out.append(
            f"\n- **SPREAD target reached at a loss:** {len(tl)} of {int(sp.reason.str.startswith('target').sum())} "
            "(the gap closed through the heavyweights moving, not Nifty)"
        )
    if not dec.empty:
        out.append(
            "- **MAIN decisions:** "
            + ", ".join(f"{s_} {d_} {n}" for (s_, d_), n in dec.groupby(["strat", "decision"]).size().items())
        )
    if len(main):
        out += [
            "\n| # | Strat | Side | Entry | OFI z | Lean z | Spread z | Exit (why) "
            "| Slippage | Would-be lots | Best ₹ | ₹ |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for k, (_, r) in enumerate(main.iterrows(), 1):
            out.append(
                f"| {k} | {r.strat} | {r.side} | {r.entry} @ {r.entry_px} | {r.get('mlofi_z', '')} | "
                f"{r.get('lean_z', '')} | {r.get('spread_z', '')} | {r.exit} ({r.reason}) | "
                f"{r.get('entry_slippage', '')} | {r.get('would_lots', '')} | {fmt(r.best_lot)} | "
                f"**{fmt(r.pnl_lot)}** |"
            )
    return out


def q7_news(day: date, t: pd.DataFrame) -> list[str]:
    """Q7: news and events. The morning card, MAIN vs NEWS, and MAIN's trades split by the logged news flags."""
    out = ["\n## Q7. News and events (U2)\n"]
    cf = DATA_U2 / f"{day}_morning.json"
    card = json.loads(cf.read_text(encoding="utf-8")) if cf.exists() else {}
    if not card:
        return [*out, "_No morning card for this day._"]
    wins = "; ".join(f"{w['from']}–{w['to']} {w['name']}" for w in card.get("event_windows", [])) or "none"
    out += [
        f"- **Bias:** {card.get('bias', 'unknown')} (confidence {card.get('confidence')}); "
        f"**event risk:** {card.get('event_risk', 'none')}; **event windows:** {wins}",
        "- **Headlines:** " + (" · ".join(card.get("headlines", [])[:5]) or "—"),
        f"- **News read error:** {card.get('llm_error') or 'none'}",
    ]
    tot = {v: (len(g), g.pnl_lot.sum()) for v, g in t.groupby("variant") if v in ("MAIN", "NEWS")}
    if tot:
        out.append("- **MAIN vs NEWS:** " + "; ".join(f"{v} {n} trades {fmt(s_)}" for v, (n, s_) in tot.items()))
    main = t[t.variant == "MAIN"]
    out += ["\n| MAIN trades split by | Group | Trades | Total ₹ | Wins |", "|---|---|---|---|---|"]
    for col, label in (
        ("news_bias_with", "news bias"),
        ("news_gap_with", "gap direction"),
        ("news_event_window", "event window"),
        ("news_vix_guard", "VIX guard"),
    ):
        if col not in main.columns:
            continue
        g = main[col].fillna("").astype(str).replace({"": "outside" if col == "news_event_window" else "n/a"})
        if col == "news_event_window":
            g = g.where(g == "outside", "inside")
        for k, grp in main.groupby(g):
            out.append(f"| {label} | {k} | {len(grp)} | {fmt(grp.pnl_lot.sum())} | {int((grp.pnl_lot > 0).sum())} |")
    return out


# U4 features (docs/U4_README.md §2) join the same scorecard; value = expected direction ("+" = expect Nifty up)
U4_FEATURES = {
    "u4_mlofi": ("mlofi_z", 1, 1.0),
    "u4_book": ("book_z", 1, 1.0),
    "u4_lean": ("lean_z", 1, 1.0),
    "u4_hawkes": ("hawkes_dir", 1, 0.3),
    "u4_spread": ("spread_z", -1, 1.0),
}
U4_NAMES = {
    "u4_mlofi": "U4 multi-level OFI",
    "u4_book": "U4 option-book pressure",
    "u4_lean": "U4 micro-price lean",
    "u4_hawkes": "U4 Hawkes direction",
    "u4_spread": "U4 Kalman spread (− = rich)",
}
U2_FACTORS = [*u2h.CONT, "trend", "trigger", "health"]
FACTORS = [*U2_FACTORS, *U4_FEATURES]
ALL_NAMES = {**u2h.NAMES, **U4_NAMES}


def factor_day(day: date) -> dict[str, Any]:
    """Q6 for one day: per factor, at each minute end, its value vs Nifty's move over the next 3 minutes.
    Spearman correlation, plus events (z ≥ +1 → expect up; z ≤ −1 → expect down): average move in the expected
    direction and hit rate. Uses U2's health factors (live feed only)."""
    feed = u2c.Feed(day)
    feed.update()
    if len(feed.ltp) < 200:
        return {}
    h = u2h.build(feed)
    tk = h.ticks
    per_min = tk.resample("1min").last().dropna(subset=["nifty"])
    per_min = per_min.between_time("09:30", "15:05")
    nxt = per_min.nifty.shift(-3) - per_min.nifty
    out: dict[str, Any] = {}
    for f in U2_FACTORS:
        col = "health" if f == "health" else f"z_{f}"
        x = per_min[col]
        ok = x.notna() & nxt.notna()
        if ok.sum() < 20:
            continue
        rho = float(x[ok].rank().corr(nxt[ok].rank()))
        th = 0.3 if f in ("health", "trend") else (1.0 if f != "trigger" else 0.5)
        up, dn = ok & (x >= th), ok & (x <= -th)
        moves = list(nxt[up]) + list(-nxt[dn])  # move in the expected direction
        out[f] = {
            "n_min": int(ok.sum()),
            "rho": round(rho, 3),
            "events": len(moves),
            "sum_move": float(np.sum(moves)) if moves else 0.0,
            "hits": int(sum(1 for m_ in moves if m_ > 0)),
            "pos_day": bool(np.mean(moves) > 0) if moves else None,
        }
    ff = DATA_U4 / f"{day}_features.csv"
    if ff.exists():
        fm = pd.read_csv(ff, index_col=0, parse_dates=True).between_time("09:30", "15:05")
        nx = fm.nifty.shift(-3) - fm.nifty
        for k, (col, sign, th) in U4_FEATURES.items():
            if col not in fm.columns:
                continue
            x = sign * fm[col]
            ok = x.notna() & nx.notna()
            if ok.sum() < 20:
                continue
            up, dn = ok & (x >= th), ok & (x <= -th)
            moves = list(nx[up]) + list(-nx[dn])
            out[k] = {
                "n_min": int(ok.sum()),
                "rho": round(float(x[ok].rank().corr(nx[ok].rank())), 3),
                "events": len(moves),
                "sum_move": float(np.sum(moves)) if moves else 0.0,
                "hits": int(sum(1 for m_ in moves if m_ > 0)),
                "pos_day": bool(np.mean(moves) > 0) if moves else None,
            }
    return out


def factor_md(fac: dict[str, Any]) -> list[str]:
    out = [
        "\n## Q6. Live factor scorecard: today\n",
        "*At each minute: the factor's value vs Nifty's move over the next 3 minutes. ρ = Spearman correlation "
        "(+ = the factor points the right way). Events = minutes when the factor was strong (|z| ≥ 1; health/trend "
        "≥ 0.3); move = average Nifty move in the expected direction over the next 3 min.*\n",
        "| Factor | Minutes | ρ | Events | Avg move (pts) | Hit % |",
        "|---|---|---|---|---|---|",
    ]
    for f, v in fac.items():
        avg = v["sum_move"] / v["events"] if v["events"] else None
        hit = f"{100 * v['hits'] / v['events']:.0f}%" if v["events"] else "—"
        out.append(
            f"| {ALL_NAMES.get(f, f)} | {v['n_min']} | {v['rho']:+.2f} | {v['events']} | "
            f"{'—' if avg is None else f'{avg:+.1f}'} | {hit} |"
        )
    return out


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p_ = k / n
    den = 1 + z * z / n
    c = (p_ + z * z / (2 * n)) / den
    w = z * ((p_ * (1 - p_) / n + z * z / (4 * n * n)) ** 0.5) / den
    return (c - w, c + w)


def factor_scorecard() -> str:
    """Q6 across all reviewed live days."""
    agg: dict[str, dict[str, Any]] = {}
    days = []
    for f in sorted(REVIEWS.glob("*.json")):
        j = json.loads(f.read_text(encoding="utf-8"))
        if not j.get("factors"):
            continue
        days.append(j["day"])
        for k, v in j["factors"].items():
            a = agg.setdefault(k, {"events": 0, "hits": 0, "sum": 0.0, "rho": [], "days_pos": 0, "days": 0})
            a["events"] += v["events"]
            a["hits"] += v["hits"]
            a["sum"] += v["sum_move"]
            a["rho"].append(v["rho"])
            if v["pos_day"] is not None:
                a["days"] += 1
                a["days_pos"] += int(v["pos_day"])
    lines = [
        "# U2 live factor scorecard (Q6; auto-generated by `scripts/u1_daily_review.py`)\n",
        f"Live days: {len(days)} ({', '.join(days)})\n",
        "A factor is **reliable** when it has ≥ 30 events over ≥ 5 live days, its hit-rate range stays above 50%, "
        "and it worked on most days separately. Reliable factors become candidate weights for the next U2 "
        "version (owner approval required).\n",
        "| Factor | Events | Avg move next 3 min (pts) | Hit % | 95% range | Days it worked | Avg ρ | Status |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for k in FACTORS:
        if k not in agg:
            continue
        a = agg[k]
        n = a["events"]
        lo, hi = wilson(a["hits"], n)
        status = (
            "collecting"
            if (n < 30 or a["days"] < 5)
            else ("reliable ✅" if lo > 0.5 and a["days_pos"] > a["days"] / 2 else "not reliable")
        )
        lines.append(
            f"| {ALL_NAMES.get(k, k)} | {n} | {a['sum'] / n if n else 0:+.2f} | "
            f"{100 * a['hits'] / n if n else 0:.0f}% | {100 * lo:.0f}–{100 * hi:.0f}% | "
            f"{a['days_pos']}/{a['days']} | {np.mean(a['rho']):+.2f} | {status} |"
        )
    return "\n".join(lines) + "\n"


def scoreboard() -> str:
    allh: dict[str, list[Any]] = {k: [] for k in HYP}
    days = []
    for f in sorted(REVIEWS.glob("*.json")):
        j = json.loads(f.read_text(encoding="utf-8"))
        days.append(j["day"])
        for t in j["trades"]:
            for k, v in t["hypotheses"].items():
                allh[k].append((j["day"], t["n"], v))
    lines = [
        "# U1 hypothesis scoreboard (auto-generated by `scripts/u1_daily_review.py`)\n",
        f"Days reviewed: {len(days)} ({', '.join(days)})\n",
        "A hypothesis becomes a **candidate rule** only after ≥ 15 applicable trades with a clear majority, and "
        "it's adopted only with the owner's approval (a new U1 version in docs/U1_README.md).\n",
        "| # | Hypothesis | Applicable trades | Supported | Share |\n|---|---|---|---|---|",
    ]
    for k, text in HYP.items():
        v = allh[k]
        if k == "H6":
            hi = [x[2]["good"] for x in v if x[2]["high"]]
            lo = [x[2]["good"] for x in v if not x[2]["high"]]
            share = (f"GOOD when ≥0.70: {sum(hi)}/{len(hi)}; when <0.70: {sum(lo)}/{len(lo)}") if v else "—"
            lines.append(f"| {k} | {text} | {len(v)} | — | {share} |")
            continue
        sup = sum(1 for x in v if x[2])
        lines.append(f"| {k} | {text} | {len(v)} | {sup} | {f'{100 * sup / len(v):.0f}%' if v else '—'} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=str(date.today()))
    day = date.fromisoformat(ap.parse_args().day)
    DOCS.mkdir(parents=True, exist_ok=True)
    REVIEWS.mkdir(parents=True, exist_ok=True)
    md, js = review(day)
    out = DOCS / f"{day}.md"
    if out.exists() and "_TODO_" not in out.read_text(encoding="utf-8"):
        out = DOCS / f"{day}_regenerated.md"  # never overwrite a finished, narrated review
    out.write_text(md, encoding="utf-8")
    (REVIEWS / f"{day}.json").write_text(json.dumps(js, indent=1, default=str), encoding="utf-8")
    (ROOT / "docs" / "U1_HYPOTHESES.md").write_text(scoreboard(), encoding="utf-8")
    (ROOT / "docs" / "U2_FACTOR_SCORECARD.md").write_text(factor_scorecard(), encoding="utf-8")
    print(f"review: {out}\njson: {REVIEWS / f'{day}.json'}\nscoreboard: {ROOT / 'docs' / 'U1_HYPOTHESES.md'}")
    print(f"trades reviewed: {len(js['trades'])}; narratives to write: {js['pending_narratives']}")


if __name__ == "__main__":
    main()
