# ruff: noqa: E501  (embedded HTML/JS page)
"""U1 dashboard (separate from the Nifty system's UI): http://127.0.0.1:8760
Reads only premium/data/u1/ (written by scripts/u1_watch.py). Standard library only; local machine only.
"""

import csv
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "u1"
PORT = 8760


def all_trades() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in sorted(DATA.glob("*_trades.csv")):
        with f.open(encoding="utf-8") as fh:
            out += list(csv.DictReader(fh))
    return out


def stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    p = [float(t["pnl_lot"]) for t in trades if t.get("pnl_lot") not in (None, "")]
    wins, losses = [x for x in p if x > 0], [x for x in p if x <= 0]
    streak = worst = 0.0
    for x in p:
        streak = streak + x if x < 0 else 0.0
        worst = min(worst, streak)
    eq, peak, mdd = 0.0, 0.0, 0.0
    for x in p:
        eq += x
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    days = sorted({t["date"] for t in trades})
    return {"trades": len(p), "days": len(days), "total": round(sum(p)), "avg": round(sum(p) / len(p)) if p else 0,
            "win_rate": round(100 * len(wins) / len(p), 1) if p else None,
            "pf": round(sum(wins) / -sum(losses), 2) if losses and sum(losses) < 0 else None,
            "worst_streak": round(worst), "max_dd": round(mdd),
            "equity": [round(v) for v in _cum(p)]}


def grouped(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Stats per rule version, and per entry class within each version (README §11: never mixed)."""
    out: dict[str, Any] = {}
    for t in trades:
        t.setdefault("version", "v1")
    for v in sorted({t["version"] for t in trades}):
        tv = [t for t in trades if t["version"] == v]
        out[v] = {"all": stats(tv), "by_class": {k: stats([t for t in tv if (t.get("class") or "-") == k])
                                                 for k in sorted({t.get("class") or "-" for t in tv})}}
    return out


def _cum(p: list[float]) -> list[float]:
    out, s = [], 0.0
    for x in p:
        s += x
        out.append(s)
    return out


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>U1 Paper Setup</title>
<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
<style>
:root{--bg:#0f1115;--card:#171a21;--ink:#e6e8ee;--mute:#8a90a0;--ok:#22c55e;--bad:#ef4444;--warn:#f59e0b;--line:#262b36}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,Segoe UI,sans-serif}
header{padding:14px 18px;border-bottom:1px solid var(--line);display:flex;gap:16px;align-items:baseline;flex-wrap:wrap}
h1{font-size:18px;margin:0} .tag{font-size:12px;color:var(--mute)} .paper{background:#3b2f0b;color:#fcd34d;padding:2px 8px;border-radius:10px;font-size:12px}
main{display:grid;grid-template-columns:2fr 1fr;gap:14px;padding:14px 18px} @media(max-width:900px){main{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.card h2{font-size:13px;margin:0 0 8px;color:var(--mute);text-transform:uppercase;letter-spacing:.04em}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.kpi b{display:block;font-size:20px}.kpi span{color:var(--mute);font-size:12px}
.pos{color:var(--ok)}.neg{color:var(--bad)} table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:4px 6px;border-bottom:1px solid var(--line);text-align:left} th{color:var(--mute);font-weight:500}
.chk{display:grid;grid-template-columns:1fr 1fr;gap:10px}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
.y{background:var(--ok)}.n{background:#3a3f4b} #chart{height:380px} .stale{color:var(--warn)}
</style></head><body>
<header><h1>U1 · multi-confirmation setup</h1><span class="paper">PAPER ONLY</span>
<span class="tag" id="meta">loading…</span></header>
<main>
<div>
 <div class="card"><h2>Nifty 1-min · EMA 9 / 21 · Bollinger 20,2 · U1 entries/exits</h2><div id="chart"></div></div>
 <div class="card" style="margin-top:14px"><h2>Today's trades</h2><table id="trades"></table></div>
 <div class="card" style="margin-top:14px"><h2>Recent signals (trend + trigger held)</h2><table id="signals"></table></div>
</div>
<div>
 <div class="card"><h2>Open position</h2><div id="open">—</div></div>
 <div class="card" style="margin-top:14px"><h2>Checklist · last completed minute <span id="chkmin"></span></h2><div class="chk" id="chk"></div></div>
 <div class="card" style="margin-top:14px"><h2>All-time · current rule version <span id="ver"></span></h2><div class="kpis" id="kpis"></div>
  <div class="tag" id="goal" style="margin-top:8px"></div><table id="bycls" style="margin-top:8px"></table></div>
</div>
</main>
<script>
const fmt=v=>v==null?'—':(v>0?'+':'')+'₹'+Math.round(v).toLocaleString('en-IN');
const cls=v=>v>0?'pos':v<0?'neg':'';
let chart,candle,e9,e21,bu,bl;
function initChart(){chart=LightweightCharts.createChart(document.getElementById('chart'),{layout:{background:{color:'#171a21'},textColor:'#c9cdd6'},
 grid:{vertLines:{color:'#20242d'},horzLines:{color:'#20242d'}},timeScale:{timeVisible:true,secondsVisible:false},rightPriceScale:{borderColor:'#262b36'}});
 candle=chart.addCandlestickSeries({upColor:'#22c55e',downColor:'#ef4444',borderVisible:false,wickUpColor:'#22c55e',wickDownColor:'#ef4444'});
 e9=chart.addLineSeries({color:'#60a5fa',lineWidth:1});e21=chart.addLineSeries({color:'#f59e0b',lineWidth:1});
 bu=chart.addLineSeries({color:'#6b7280',lineWidth:1,lineStyle:2});bl=chart.addLineSeries({color:'#6b7280',lineWidth:1,lineStyle:2});
 new ResizeObserver(()=>chart.applyOptions({width:document.getElementById('chart').clientWidth})).observe(document.getElementById('chart'));}
const IST=19800; const tsec=(day,hms)=>Math.floor(new Date(day+'T'+hms+'+05:30').getTime()/1000)+IST;
const line=(bars,k)=>bars.filter(b=>b[k]!=null).map(b=>({time:b.t,value:b[k]}));
async function tick(){
 let s,a; try{[s,a]=await Promise.all([fetch('/api/state').then(r=>r.json()),fetch('/api/stats').then(r=>r.json())]);}catch(e){document.getElementById('meta').innerHTML='<span class="stale">dashboard cannot read data</span>';return;}
 const age=(Date.now()-new Date(s.updated).getTime())/1000;
 document.getElementById('meta').innerHTML=`${s.day} · Nifty ${s.nifty??'—'} · VIX ${s.vix??'—'} · feed ${s.feed_ts?.slice(11)} `+(age>90?'<span class="stale">· watcher not updating ('+Math.round(age)+'s)</span>':'· live');
 if(!chart)initChart();
 candle.setData(s.bars.map(b=>({time:b.t,open:b.o,high:b.h,low:b.l,close:b.c})));
 e9.setData(line(s.bars,'ema9'));e21.setData(line(s.bars,'ema21'));bu.setData(line(s.bars,'bb_up'));bl.setData(line(s.bars,'bb_lo'));
 const mk=[];const m=t=>Math.floor(tsec(s.day,t)/60)*60;
 for(const t of s.trades){mk.push({time:m(t.entry),position:t.side=='CALL'?'belowBar':'aboveBar',color:t.side=='CALL'?'#22c55e':'#ef4444',shape:t.side=='CALL'?'arrowUp':'arrowDown',text:t.side});
  mk.push({time:m(t.exit),position:'inBar',color:t.pnl_lot>0?'#22c55e':'#ef4444',shape:'circle',text:fmt(t.pnl_lot)});}
 if(s.open)mk.push({time:m(s.open.entry),position:s.open.side=='CALL'?'belowBar':'aboveBar',color:'#fcd34d',shape:s.open.side=='CALL'?'arrowUp':'arrowDown',text:s.open.side+' open'});
 mk.sort((x,y)=>x.time-y.time);candle.setMarkers(mk);
 document.getElementById('open').innerHTML=s.open?`<b>${s.open.side}</b> ${s.open.key.replace('NSE_','')}<br>entry ${s.open.entry} @ ₹${s.open.entry_px} (${s.open.confirmations}/5)<br>mark ₹${s.open.mark??'—'} · stop Nifty ${s.open.stop}<br><b class="${cls(s.open.unreal_lot)}" style="font-size:20px">${fmt(s.open.unreal_lot)}</b> /lot (after costs)`:'No open trade';
 const c=s.checklist;document.getElementById('chkmin').textContent=c?c.minute:'(warming up — needs ~27 min of data)';
 const tf=s.trend_tf||'1-min';const rows=[['Above/below VWAP','vwap'],[`EMA 9 vs 21 (${tf})`,'ema_order'],[`EMA 9 slope (${tf})`,'ema_slope'],['Trigger: band breakout','trigger_band'],['Trigger: 5-min break','trigger_break'],['Strength RSI+MACD','strength'],['Volume surge','volume'],['Heavyweights','heavyweights'],['VIX','vix'],['Options OI','oi']];
 document.getElementById('chk').innerHTML=c?['CALL','PUT'].map(sd=>`<div><b>${sd}</b> · ${c[sd].confirmations}/5${c[sd].trend&&c[sd].trigger?' · <span class="pos">setup live</span>':''}<br>`+rows.map(([n,k])=>`<div><span class="dot ${c[sd][k]?'y':'n'}"></span>${n}</div>`).join('')+'</div>').join(''):'';
 const tr=s.trades;document.getElementById('trades').innerHTML=tr.length?'<tr><th>Side</th><th>Entry</th><th>Exit</th><th>Why</th><th>₹/lot</th></tr>'+tr.map(t=>`<tr><td>${t.side} ${t.class||''} ${t.confirmations}/5</td><td>${t.entry} @ ${t.entry_px}</td><td>${t.exit} @ ${t.exit_px}</td><td>${t.reason}</td><td class="${cls(+t.pnl_lot)}">${fmt(+t.pnl_lot)}</td></tr>`).join(''):'<tr><td>No closed trades yet today</td></tr>';
 const sg=s.signals.slice().reverse();document.getElementById('signals').innerHTML=sg.length?'<tr><th>Min</th><th>Side</th><th>Conf</th><th>Taken</th></tr>'+sg.map(x=>`<tr><td>${x.minute}</td><td>${x.side} ${x.class||''}</td><td>${x.confirmations}/5</td><td>${x.taken?'yes':(x.why_not||'no')}</td></tr>`).join(''):'<tr><td>None yet</td></tr>';
 document.getElementById('kpis').innerHTML=[['Trades',a.trades],['Total',fmt(a.total)],['Avg/trade',fmt(a.avg)],['Win %',a.win_rate??'—'],['Profit factor',a.pf??'—'],['Worst streak',fmt(a.worst_streak)],['Max drawdown',fmt(a.max_dd)],['Days',a.days]].map(([n,v])=>`<div class="kpi"><b>${v}</b><span>${n}</span></div>`).join('');
 document.getElementById('ver').textContent=a.version+(s.version&&s.version!==a.version?' (today runs '+s.version+')':'');
 const g=(a.groups||{})[a.version];document.getElementById('bycls').innerHTML=g?'<tr><th>Class</th><th>Trades</th><th>Avg</th><th>Win %</th><th>Total</th></tr>'+Object.entries(g.by_class).map(([k,v])=>`<tr><td>${k}</td><td>${v.trades}</td><td class="${cls(v.avg)}">${fmt(v.avg)}</td><td>${v.win_rate??'—'}</td><td class="${cls(v.total)}">${fmt(v.total)}</td></tr>`).join(''):'';
 document.getElementById('goal').textContent=`Testing phase: no trade cap and no pass/fail thresholds; collecting trades for analysis (${a.trades} so far in ${a.version}).`;
}
tick();setInterval(tick,5000);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def _send(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/state":
            f = DATA / "state.json"
            self._send(f.read_bytes() if f.exists() else b'{"bars":[],"trades":[],"signals":[]}', "application/json")
        elif self.path == "/api/stats":
            tr = all_trades()
            cur = max((t.get("version") or "v1" for t in tr), default="v1")
            body = stats([t for t in tr if (t.get("version") or "v1") == cur]) | {"version": cur,
                                                                                   "groups": grouped(tr)}
            self._send(json.dumps(body).encode(), "application/json")
        elif self.path in ("/", "/index.html"):
            self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def log_message(self, *_: Any) -> None:
        pass


if __name__ == "__main__":
    print(f"U1 dashboard on http://127.0.0.1:{PORT}  (PAPER ONLY; reads premium/data/u1)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
