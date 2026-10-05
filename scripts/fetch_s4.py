"""S4 data: Yahoo daily (close + adjusted close) for the Nifty 50 universe into premium's OWN data/s4.duckdb.

Universe = the stock symbols with daily candles in premium's snapshot, minus BSE (not a Nifty 50 member; it was
added by the Nifty system's stock pilot). Plus ^NSEI and NIFTYBEES.NS. Public chart API, personal research only.
"""

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "s4.duckdb"
SNAP = ROOT / "data" / "market.duckdb"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
NOT_STOCKS = {"NSE-NIFTY", "NSE-BANKNIFTY", "NSE-INDIAVIX", "NSE-BSE"}


def universe() -> list[str]:
    s = duckdb.connect(str(SNAP), read_only=True)
    rows = s.execute("SELECT DISTINCT symbol FROM candles WHERE interval='1day' AND symbol NOT LIKE '%-CE' "
                     "AND symbol NOT LIKE '%-PE' AND symbol NOT LIKE '%FUT' ORDER BY 1").fetchall()
    s.close()
    return [r[0][4:] for r in rows if r[0] not in NOT_STOCKS]


def fetch(sym: str) -> pd.DataFrame:
    p1, p2 = int(datetime(2005, 1, 1).timestamp()), int(datetime.now().timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}"
           f"?period1={p1}&period2={p2}&interval=1d&events=div%2Csplit")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 (fixed https URL)
        j = json.load(r)["chart"]["result"][0]
    if "timestamp" not in j:
        return pd.DataFrame()
    q = j["indicators"]["quote"][0]
    adj = (j["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
    # Yahoo timestamps are market open in UTC; +5:30 gives the IST trading date
    d = (pd.to_datetime(j["timestamp"], unit="s") + pd.Timedelta(hours=5, minutes=30)).date
    t = pd.DataFrame({"symbol": sym, "d": d, "close": q["close"], "adjclose": adj, "volume": q["volume"]})
    return t.dropna(subset=["close", "adjclose"]).drop_duplicates(["symbol", "d"], keep="last")


def main() -> None:
    c = duckdb.connect(str(DB))
    c.execute("""CREATE TABLE IF NOT EXISTS daily (symbol VARCHAR, d DATE, close DOUBLE, adjclose DOUBLE,
                 volume DOUBLE, PRIMARY KEY (symbol, d))""")
    names = [f"{u}.NS" for u in universe()] + ["^NSEI", "NIFTYBEES.NS"]
    missing = []
    for s in names:
        try:
            t = fetch(s)
        except Exception as e:  # report and continue
            print(f"{s:16s} ERROR {type(e).__name__}: {str(e)[:60]}")
            missing.append(s)
            continue
        if t.empty:
            print(f"{s:16s} no data")
            missing.append(s)
            continue
        c.execute("DELETE FROM daily WHERE symbol=?", [s])
        c.register("t", t)
        c.execute("INSERT INTO daily SELECT * FROM t")
        c.unregister("t")
        print(f"{s:16s} {len(t):5d} rows {t.d.min()} → {t.d.max()}")
        time.sleep(0.8)
    print(f"\n{len(names) - len(missing)}/{len(names)} downloaded; missing: {missing or 'none'}")


if __name__ == "__main__":
    main()
