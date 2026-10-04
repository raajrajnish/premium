"""S3 data download into premium's OWN database data/s3.duckdb (never the snapshot, never the Nifty system).

  --step yahoo : Yahoo Finance daily (public chart API) for the S3 markets, 2005 → today.
  --step groww : expired monthly NIFTY / BANKNIFTY futures from Groww (READ-ONLY candles), 2021-01 → 2026-09.
                 Monthly expiry = the last weekday in the month that returns data (tries the last 8 weekdays,
                 latest first), which absorbs Thursday/Wednesday/Tuesday rule changes and holiday shifts.
Token (groww step): GROWW_ACCESS_TOKEN from the environment, else read-only from ../suzlon/.env; never printed.
"""

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "s3.duckdb"
YAHOO = ["GC=F", "SI=F", "CL=F", "HG=F", "NG=F", "INR=X", "^NSEI", "^NSEBANK"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def con() -> duckdb.DuckDBPyConnection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = duckdb.connect(str(DB))
    c.execute("""CREATE TABLE IF NOT EXISTS yahoo_daily (symbol VARCHAR, d DATE, open DOUBLE, high DOUBLE,
                 low DOUBLE, close DOUBLE, volume DOUBLE, PRIMARY KEY (symbol, d))""")
    c.execute("""CREATE TABLE IF NOT EXISTS fut_daily (underlying VARCHAR, expiry DATE, d DATE, open DOUBLE,
                 high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, PRIMARY KEY (underlying, expiry, d))""")
    return c


def yahoo() -> None:
    c = con()
    p1 = int(datetime(2005, 1, 1).timestamp())
    p2 = int(datetime.now().timestamp())
    for s in YAHOO:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(s)}"
               f"?period1={p1}&period2={p2}&interval=1d")
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (fixed https URL)
            j = json.load(r)["chart"]["result"][0]
        q = j["indicators"]["quote"][0]
        t = pd.DataFrame({"symbol": s, "d": pd.to_datetime(j["timestamp"], unit="s").date,
                          "open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"],
                          "volume": q["volume"]}).dropna(subset=["close"]).drop_duplicates(["symbol", "d"], keep="last")
        c.execute("DELETE FROM yahoo_daily WHERE symbol = ?", [s])
        c.register("t", t)
        c.execute("INSERT INTO yahoo_daily SELECT * FROM t")
        c.unregister("t")
        print(f"{s:10s} {len(t):5d} rows  {t.d.min()} → {t.d.max()}  last close {t.close.iloc[-1]:.2f}")
        time.sleep(1.0)


def token() -> str:
    t = os.environ.get("GROWW_ACCESS_TOKEN")
    if not t:
        from dotenv import dotenv_values
        t = dotenv_values(ROOT.parent / "suzlon" / ".env").get("GROWW_ACCESS_TOKEN")
    if not t:
        sys.exit("No Groww token found.")
    return str(t)


def groww(start: date, end: date) -> None:
    from growwapi import GrowwAPI
    g = GrowwAPI(token())
    c = con()

    def candles(sym: str, a: date, b: date) -> list[list[object]]:
        for attempt in range(3):
            try:
                r = g.get_historical_candles(exchange=g.EXCHANGE_NSE, segment=g.SEGMENT_FNO, groww_symbol=sym,
                                             start_time=f"{a} 00:00:00", end_time=f"{b} 23:59:59",
                                             candle_interval=g.CANDLE_INTERVAL_DAY, timeout=30)
                return list((r or {}).get("candles") or [])
            except Exception as e:  # rate limit / transient: retry, then report
                if attempt == 2:
                    print(f"   {sym}: {type(e).__name__}: {str(e)[:80]}")
                time.sleep(2.0 * (attempt + 1))
            finally:
                time.sleep(0.35)
        return []

    m = date(start.year, start.month, 1)
    while m <= end:
        nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        for u in ("NIFTY", "BANKNIFTY"):
            done = c.execute("SELECT count(*) FROM fut_daily WHERE underlying=? AND expiry>=? AND expiry<?",
                             [u, m, nxt]).fetchone()
            if done and done[0] > 0:
                continue
            hit = None
            d = nxt - timedelta(days=1)
            tried = 0
            while tried < 8 and d >= m:
                if d.weekday() < 5:
                    tried += 1
                    cs = candles(f"NSE-{u}-{d:%d%b%y}-FUT", d - timedelta(days=100), d)
                    if cs:
                        hit = (d, cs)
                        break
                d -= timedelta(days=1)
            if not hit:
                print(f"{u:9s} {m:%Y-%m}: NO CONTRACT FOUND")
                continue
            exp, cs = hit
            t = pd.DataFrame([r[:6] for r in cs], columns=["ts", "open", "high", "low", "close", "volume"])
            t["d"] = pd.to_datetime(t.ts.astype(str).str[:10]).dt.date
            t = t.assign(underlying=u, expiry=exp)[["underlying", "expiry", "d", "open", "high", "low", "close",
                                                      "volume"]].drop_duplicates(["d"], keep="last")
            c.register("t", t)
            c.execute("INSERT INTO fut_daily SELECT * FROM t")
            c.unregister("t")
            print(f"{u:9s} expiry {exp}: {len(t):3d} days {t.d.min()} → {t.d.max()}")
        m = nxt


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", choices=["yahoo", "groww"], required=True)
    ap.add_argument("--start", default="2020-11-01")
    ap.add_argument("--end", default="2026-10-31")
    a = ap.parse_args()
    if a.step == "yahoo":
        yahoo()
    else:
        groww(date.fromisoformat(a.start), date.fromisoformat(a.end))
