"""U4 S-SPREAD on 1-minute history (protocol: docs/studies/2026-10-07_U4_spread_history.md). Read-only on the snapshot.
Usage: uv run python scripts/u4_spread_history.py"""

import math
from datetime import date, time, timedelta

import duckdb
import numpy as np
import pandas as pd
import u4_features as fx

ROOT = fx.core.ROOT
con = duckdb.connect(str(ROOT / "data" / "market.duckdb"), read_only=True)
LOT, COST = 65, 2.5
DELTA_1M = 6e-9
EXPS = [r[0] for r in con.execute("select distinct expiry from contracts where underlying='NIFTY' and kind='CE' "
                                  "and expiry >= '2026-07-01' order by 1").fetchall()]


def load(sym: str, a: str = "2026-07-01", b: str = "2026-09-30") -> pd.DataFrame:
    t = con.execute("select ts, open, high, low, close from candles where symbol=? and interval='1minute' "
                    "and ts >= ? and ts < ? order by ts", [sym, a, b]).df()
    t["ts"] = pd.to_datetime(t.ts).dt.tz_localize(None)
    return t.set_index("ts")


def zs_hl(spread: pd.Series) -> tuple[pd.Series, pd.Series]:
    m, sd = spread.rolling(60, min_periods=30).mean(), spread.rolling(60, min_periods=30).std()
    z = ((spread - m) / sd.replace(0, np.nan)).clip(-6, 6)
    vals, hl = spread.to_numpy(), []
    for k in range(len(vals)):
        w = vals[max(0, k - 60):k + 1]
        w = w[~np.isnan(w)]
        if len(w) < 30:
            hl.append(np.nan)
            continue
        a, b_ = w[:-1] - w[:-1].mean(), w[1:] - w[1:].mean()
        phi = float((a * b_).sum() / (a * a).sum()) if (a * a).sum() > 0 else 0.0
        hl.append(-math.log(2) / math.log(phi) if 0 < phi < 1 else np.nan)
    return z, pd.Series(hl, index=spread.index)


def main() -> None:
    N = load("NSE-NIFTY")
    H = {k: load(s)["close"] for k, s in (("bn", "NSE-BANKNIFTY"), ("hdfc", "NSE-HDFCBANK"), ("icici", "NSE-ICICIBANK"))}
    trades = []
    for day, b in N.groupby(N.index.date):
        b = b[(b.index.time >= time(9, 15)) & (b.index.time <= time(15, 29))].copy()
        if len(b) < 300:
            continue
        g = pd.DataFrame({"nifty": b.close, **{k: s.reindex(b.index).ffill() for k, s in H.items()}}).dropna()
        if len(g) < 300:
            continue
        ks = fx.kalman_spread(g, delta=DELTA_1M)
        sp = ks.spread.copy()
        sp.iloc[:15] = np.nan                                     # settle (first 15 min)
        z, hl = zs_hl(sp)
        exp = next((e for e in EXPS if e >= day), None)
        hard = time(14, 45) if exp == day else time(15, 10)
        sig = {m: fx.yang_zhang_sigma1m(b.close, m) for m in b.index}
        day_pnl, n_tr, streak, pause_until, last_break = 0.0, 0, 0, None, None
        i = 0
        idx = b.index
        while i < len(idx) - 2:
            t = idx[i]
            zi, hli = z.get(t, np.nan), hl.get(t, np.nan)
            ok_time = time(9, 45) <= t.time() <= time(14, 30)
            blocked = day_pnl <= -2000 or n_tr >= 8 or (pause_until is not None and t < pause_until) or \
                (last_break is not None and t - last_break <= timedelta(minutes=5))
            if not (ok_time and not blocked and zi == zi and hli == hli and abs(zi) >= 2.0 and hli <= 15):
                i += 1
                continue
            d = -1 if zi > 0 else 1
            strike = int(round(b.close.iloc[i] / 50) * 50)
            sym = f"NSE-NIFTY-{exp:%d%b%y}-{strike}-{'CE' if d > 0 else 'PE'}" if exp else None
            if sym is None:
                i += 1
                continue
            t_in = idx[i + 1]
            o = load(sym, str(t_in), str(t_in + timedelta(minutes=25))).reindex(idx[i + 1:i + 26]).ffill()
            if o.empty or o.open.isna().iloc[0]:
                i += 1
                continue
            e_opt, e_spot = float(o.open.iloc[0]), float(b.open.iloc[i + 1])
            s1 = sig.get(t, np.nan)
            s1 = s1 if s1 == s1 and s1 > 0 else 4.0
            chand, cut = 3 * s1, 2 * s1 * math.sqrt(5)
            max_min = min(20.0, max(5.0, 2 * hli))
            best, px, why, j_exit = e_spot, None, None, None
            for k in range(len(o)):
                j = i + 1 + k
                if j >= len(idx):
                    break
                tt = idx[j]
                hi, lo, cl = b.high.iloc[j], b.low.iloc[j], b.close.iloc[j]
                adverse = (e_spot - lo) if d > 0 else (hi - e_spot)
                if tt.time() >= hard:
                    px, why = o.close.iloc[k], "hard"
                elif o.low.iloc[k] <= e_opt * 0.75:
                    px, why = e_opt * 0.75, "max loss −25%"
                elif adverse >= cut:
                    px, why = o.close.iloc[k], "loss cut"
                elif d * (best - (lo if d > 0 else hi)) >= chand and d * (best - e_spot) > 0:
                    px, why = o.close.iloc[k], "Chandelier"
                else:
                    zz = z.get(tt, np.nan)
                    if zz == zz and abs(zz) <= 0.5:
                        px, why = o.close.iloc[k], "target"
                    elif zz == zz and -d * zz >= 3.5:
                        px, why = o.close.iloc[k], "thesis break"
                        last_break = tt
                    elif k + 1 >= max_min:
                        px, why = o.close.iloc[k], "time"
                best = max(best, hi) if d > 0 else min(best, lo)
                if why:
                    j_exit = j
                    break
            if why is None:
                px, why, j_exit = o.close.iloc[-1], "end", i + len(o)
            pnl = (float(px) - e_opt - COST) * LOT
            trades.append({"day": day, "month": day.strftime("%Y-%m"), "entry": t_in.strftime("%H:%M"), "side": d,
                           "z": round(zi, 2), "hl": round(hli, 1), "reason": why, "pnl": round(pnl),
                           "gross": round(pnl + COST * LOT)})
            day_pnl += pnl
            n_tr += 1
            streak = streak + 1 if pnl <= 0 else 0
            if streak >= 3:
                pause_until, streak = idx[min(j_exit, len(idx) - 1)] + timedelta(minutes=30), 0
            i = (j_exit or i) + 1
    t = pd.DataFrame(trades)
    out = ROOT / "data" / "results"
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / "u4_spread_history_trades.csv", index=False)
    if t.empty:
        print("no trades")
        return

    def summ(g: pd.DataFrame) -> dict[str, object]:
        w, lo = g[g.pnl > 0].pnl, -g[g.pnl <= 0].pnl
        payoff = (w.mean() / lo.mean()) if len(w) and len(lo) else float("nan")
        p = len(w) / len(g)
        return {"trades": len(g), "win%": round(100 * p), "avg ₹": round(g.pnl.mean()), "avg gross ₹": round(g.gross.mean()),
                "total ₹": round(g.pnl.sum()), "payoff": round(payoff, 2),
                "PF": round(w.sum() / lo.sum(), 2) if lo.sum() > 0 else None,
                "worst day ₹": round(g.groupby("day").pnl.sum().min()),
                "qKelly": round(0.25 * (p - (1 - p) / payoff), 3) if payoff == payoff else None}

    rows = [{"period": "ALL", **summ(t)}] + [{"period": m, **summ(g)} for m, g in t.groupby("month")]
    pd.set_option("display.width", 200)
    print(pd.DataFrame(rows).to_string(index=False))
    print("\nexit reasons:", t.reason.value_counts().to_dict())
    print("trades/day:", round(len(t) / t.day.nunique(), 1), "over", t.day.nunique(), "days")


if __name__ == "__main__":
    main()
