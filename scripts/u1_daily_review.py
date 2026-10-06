"""U1 daily review: the same facts, computed the same way, every day (used by the /u1-daily-review skill).

Outputs
  docs/u1_daily/<day>.md         facts per trade (narrative sections are written afterwards, per the skill)
  data/u1/reviews/<day>.json     tags + hypothesis outcomes per trade
  docs/U1_HYPOTHESES.md          running scoreboard of every hypothesis across all reviewed days

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

ROOT = Path(__file__).resolve().parents[1]
DOCS, REVIEWS = ROOT / "docs" / "u1_daily", ROOT / "data" / "u1" / "reviews"
MODELS = ("EC0", "EC1", "EC2", "EC2P")
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
        md.append("\n| Model | Exit | Reason | ₹ | Best while open | Worst while open |\n|---|---|---|---|---|---|")
        for m in models:
            pm = per_model[m]
            md.append(
                f"| {LABEL[m]} | {pm['exit']} | {pm['reason']} | **{fmt(pm['pnl'])}** | {fmt(pm['best'])} | "
                f"{fmt(pm['worst'])} |"
            )
        md.append("\n*Starred columns are direction-adjusted (+ = in the trade's favour).*\n")
        md.append(md_table(rows))
        md.append("\n**Auto tags:** " + "; ".join(f"{k}: {', '.join(v) or '—'}" for k, v in tags.items()))
        md.append(
            "\n**Hypotheses:** "
            + (", ".join(f"{k} = {v if not isinstance(v, dict) else v}" for k, v in h.items()) or "none applicable")
        )
        md.append("\n### Narrative (written per the /u1-daily-review skill)\n\n_TODO_\n")
        pend.append(n + 1)
    # header + summary
    head = [
        f"# U1 daily review: {day} ({ver})\n",
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
    head.append("\n## Day summary (written per the skill)\n\n_TODO_\n")
    body = "\n".join(head + md)
    return body, {"day": str(day), "version": ver, "trades": out_trades, "pending_narratives": pend}


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
    print(f"review: {out}\njson: {REVIEWS / f'{day}.json'}\nscoreboard: {ROOT / 'docs' / 'U1_HYPOTHESES.md'}")
    print(f"trades reviewed: {len(js['trades'])}; narratives to write: {js['pending_narratives']}")


if __name__ == "__main__":
    main()
