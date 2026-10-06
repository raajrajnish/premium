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
DATA_U2 = ROOT / "data" / "u2"          # U2 panel (additive; docs/U2_README.md)
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


MODELS = ("EC0", "EC1", "EC2", "EC2P")


def challengers(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Per exit model, on the same entries (README §7). v1 rows only have EC0 (= pnl_lot)."""
    out: dict[str, Any] = {}
    for m in MODELS:
        rows = [dict(t, pnl_lot=t.get(f"{m}_pnl") if m != "EC0" else (t.get("EC0_pnl") or t.get("pnl_lot")))
                for t in trades]
        rows = [r for r in rows if r["pnl_lot"] not in (None, "")]
        if rows:
            out[m] = stats(rows)
    return out


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


def u2_stats() -> dict[str, Any]:
    """U2 MAIN all-time stats, per-variant all-time totals, and U1-vs-U2 per day (same days)."""
    rows: list[dict[str, Any]] = []
    for f in sorted(DATA_U2.glob("*_trades.csv")):
        with f.open(encoding="utf-8") as fh:
            rows += list(csv.DictReader(fh))
    main = [r for r in rows if r.get("variant") == "MAIN"]
    variants: dict[str, Any] = {}
    for r in rows:
        v = variants.setdefault(r["variant"], {"trades": 0, "total": 0, "wins": 0})
        x = float(r["pnl_lot"])
        v["trades"] += 1
        v["total"] += round(x)
        v["wins"] += int(x > 0)
    days = sorted({r["date"] for r in rows})
    u1 = all_trades()
    vs = []
    for d in days:
        row: dict[str, Any] = {"day": d, "U2": round(sum(float(r["pnl_lot"]) for r in main if r["date"] == d))}
        for m in MODELS:
            vals = [t.get(f"{m}_pnl") if m != "EC0" else (t.get("EC0_pnl") or t.get("pnl_lot")) for t in u1
                    if t.get("date") == d]
            vals = [float(v) for v in vals if v not in (None, "")]
            row[m] = round(sum(vals)) if vals else None
        vs.append(row)
    return {"main": stats(main), "variants": variants, "vs": vs}


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
 <div class="card" style="margin-top:14px"><h2>Exit challengers · same entries</h2><table id="chal"></table>
  <div class="tag" style="margin-top:6px">EC0 champion · EC1 Nifty-points rulebook · EC2 owner's 20/15/25 · EC2+ EC2 with 5 additions</div></div>
 <div class="card" style="margin-top:14px"><h2>All-time · current rule version <span id="ver"></span></h2><div class="kpis" id="kpis"></div>
  <div class="tag" id="goal" style="margin-top:8px"></div><table id="bycls" style="margin-top:8px"></table></div>
</div>
</main>
<header style="border-top:1px solid var(--line)"><h1>U2 · health engine</h1><span class="paper">PAPER ONLY</span>
<span class="tag" id="u2meta">loading…</span></header>
<main>
<div>
 <div class="card"><h2>Live health (smoothed, 15 s) · + favours CALL, − favours PUT</h2><div id="u2chart" style="height:180px"></div></div>
 <div class="card" style="margin-top:14px"><h2>Entry decisions (MAIN)</h2><table id="u2dec"></table></div>
 <div class="card" style="margin-top:14px"><h2>U2 trades today (MAIN)</h2><table id="u2tr"></table></div>
</div>
<div>
 <div class="card"><h2>Morning context (news & events)</h2><div id="u2morning">—</div></div>
 <div class="card" style="margin-top:14px"><h2>Engine status</h2><div id="u2status">—</div></div>
 <div class="card" style="margin-top:14px"><h2>Health by side</h2><div class="chk" id="u2side"></div><div class="tag" id="u2pend" style="margin-top:6px"></div></div>
 <div class="card" style="margin-top:14px"><h2>Variants today</h2><table id="u2var"></table></div>
 <div class="card" style="margin-top:14px"><h2>U1 vs U2 by day (₹/lot)</h2><table id="u2vs"></table><div class="tag" id="u2all" style="margin-top:6px"></div></div>
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
 document.getElementById('open').innerHTML=s.open?`<b>${s.open.side}</b> ${s.open.key.replace('NSE_','')}<br>entry ${s.open.entry} @ ₹${s.open.entry_px} (${s.open.confirmations}/5)<br>mark ₹${s.open.mark??'—'} · stop Nifty ${s.open.stop}<br><b class="${cls(s.open.unreal_lot)}" style="font-size:20px">${fmt(s.open.unreal_lot)}</b> /lot (after costs)`+(s.open.legs&&s.open.legs.length>1?'<table style="margin-top:6px">'+s.open.legs.map(l=>`<tr><td>${l.model.replace('EC2P','EC2+')}</td><td>${l.open?'open':l.reason}</td><td class="${cls(l.pnl)}">${fmt(l.pnl)}</td></tr>`).join('')+'</table>':''):'No open trade';
 const c=s.checklist;document.getElementById('chkmin').textContent=c?c.minute:'(warming up — needs ~27 min of data)';
 const tf=s.trend_tf||'1-min';const rows=[['Above/below VWAP','vwap'],[`EMA 9 vs 21 (${tf})`,'ema_order'],[`EMA 9 slope (${tf})`,'ema_slope'],['Trigger: band breakout','trigger_band'],['Trigger: 5-min break','trigger_break'],['Strength RSI+MACD','strength'],['Volume surge','volume'],['Heavyweights','heavyweights'],['VIX','vix'],['Options OI','oi']];
 document.getElementById('chk').innerHTML=c?['CALL','PUT'].map(sd=>`<div><b>${sd}</b> · ${c[sd].confirmations}/5${c[sd].trend&&c[sd].trigger?' · <span class="pos">setup live</span>':''}<br>`+rows.map(([n,k])=>`<div><span class="dot ${c[sd][k]?'y':'n'}"></span>${n}</div>`).join('')+'</div>').join(''):'';
 const tr=s.trades;document.getElementById('trades').innerHTML=tr.length?(tr[0]&&tr[0].EC1_pnl!=null?'<tr><th>Side</th><th>Entry</th><th>EC0</th><th>EC1</th><th>EC2</th><th>EC2+</th></tr>'+tr.map(t=>`<tr><td>${t.side} ${t.class||''} q${t.quality??''}</td><td>${t.entry} @ ${t.entry_px}</td>`+['EC0','EC1','EC2','EC2P'].map(m=>`<td class="${cls(+t[m+'_pnl'])}" title="${t[m+'_reason']} at ${t[m+'_exit']}">${fmt(+t[m+'_pnl'])}</td>`).join('')+'</tr>').join(''):'<tr><th>Side</th><th>Entry</th><th>Exit</th><th>Why</th><th>₹/lot</th></tr>'+tr.map(t=>`<tr><td>${t.side} ${t.class||''} ${t.confirmations}/5</td><td>${t.entry} @ ${t.entry_px}</td><td>${t.exit} @ ${t.exit_px}</td><td>${t.reason}</td><td class="${cls(+t.pnl_lot)}">${fmt(+t.pnl_lot)}</td></tr>`).join('')):'<tr><td>No closed trades yet today</td></tr>';
 const sg=s.signals.slice().reverse();document.getElementById('signals').innerHTML=sg.length?'<tr><th>Min</th><th>Side</th><th>Conf</th><th>Taken</th></tr>'+sg.map(x=>`<tr><td>${x.minute}</td><td>${x.side} ${x.class||''}</td><td>${x.confirmations}/5</td><td>${x.taken?'yes':(x.why_not||'no')}</td></tr>`).join(''):'<tr><td>None yet</td></tr>';
 document.getElementById('kpis').innerHTML=[['Trades',a.trades],['Total',fmt(a.total)],['Avg/trade',fmt(a.avg)],['Win %',a.win_rate??'—'],['Profit factor',a.pf??'—'],['Worst streak',fmt(a.worst_streak)],['Max drawdown',fmt(a.max_dd)],['Days',a.days]].map(([n,v])=>`<div class="kpi"><b>${v}</b><span>${n}</span></div>`).join('');
 const ch=a.challengers||{};document.getElementById('chal').innerHTML='<tr><th>Model</th><th>Trades</th><th>Total</th><th>Avg</th><th>Win %</th><th>Worst streak</th></tr>'+Object.entries(ch).map(([k,v])=>`<tr><td>${k.replace('EC2P','EC2+')}</td><td>${v.trades}</td><td class="${cls(v.total)}">${fmt(v.total)}</td><td class="${cls(v.avg)}">${fmt(v.avg)}</td><td>${v.win_rate??'—'}</td><td class="neg">${fmt(v.worst_streak)}</td></tr>`).join('');
 document.getElementById('ver').textContent=a.version+(s.version&&s.version!==a.version?' (today runs '+s.version+')':'');
 const g=(a.groups||{})[a.version];document.getElementById('bycls').innerHTML=g?'<tr><th>Class</th><th>Trades</th><th>Avg</th><th>Win %</th><th>Total</th></tr>'+Object.entries(g.by_class).map(([k,v])=>`<tr><td>${k}</td><td>${v.trades}</td><td class="${cls(v.avg)}">${fmt(v.avg)}</td><td>${v.win_rate??'—'}</td><td class="${cls(v.total)}">${fmt(v.total)}</td></tr>`).join(''):'';
 document.getElementById('goal').textContent=`Testing phase: no trade cap and no pass/fail thresholds; collecting trades for analysis (${a.trades} so far in ${a.version}).`;
}
let u2c,u2l;
async function tick2(){
 let s,a;try{[s,a]=await Promise.all([fetch('/api/u2/state').then(r=>r.json()),fetch('/api/u2/stats').then(r=>r.json())]);}catch(e){return;}
 if(!s||!s.day){document.getElementById('u2meta').textContent='U2 watcher not running yet';return;}
 const age=(Date.now()-new Date(s.updated).getTime())/1000;
 document.getElementById('u2meta').innerHTML=`${s.day} · ${s.version} · feed ${s.feed_ts?.slice(11)} `+(age>90?'<span class="stale">· watcher not updating ('+Math.round(age)+'s)</span>':'· live');
 if(!u2c){u2c=LightweightCharts.createChart(document.getElementById('u2chart'),{layout:{background:{color:'#171a21'},textColor:'#c9cdd6'},grid:{vertLines:{color:'#20242d'},horzLines:{color:'#20242d'}},timeScale:{timeVisible:true}});
  u2l=u2c.addBaselineSeries({baseValue:{type:'price',price:0},topLineColor:'#22c55e',bottomLineColor:'#ef4444',topFillColor1:'rgba(34,197,94,.25)',bottomFillColor2:'rgba(239,68,68,.25)'});
  new ResizeObserver(()=>u2c.applyOptions({width:document.getElementById('u2chart').clientWidth})).observe(document.getElementById('u2chart'));}
 u2l.setData((s.health_series||[]).map(x=>({time:x.t,value:x.v})));
 const mo=s.morning||{};document.getElementById('u2morning').innerHTML=`Bias: <b class="${mo.bias==='positive'?'pos':mo.bias==='negative'?'neg':''}">${mo.bias||'unknown'}</b>${mo.confidence!=null?' ('+Math.round(mo.confidence*100)+'%)':''} · event risk <b>${mo.event_risk||'none'}</b><br>Gap: ${mo.gap_pct!=null?(mo.gap_pct>0?'+':'')+mo.gap_pct+'%':'—'} (prev close ${mo.prev_close??'—'}, open ${mo.open??'—'})`+((mo.windows||[]).length?'<br>No-entry windows (NEWS): '+mo.windows.map(w=>`${w.from}–${w.to} ${w.name}`).join('; '):'')+(mo.in_window_now?`<br><span class="neg">Now inside: ${mo.in_window_now}</span>`:'')+((mo.headlines||[]).length?'<ul style="margin:6px 0 0 16px;padding:0">'+mo.headlines.map(h=>`<li>${h}</li>`).join('')+'</ul>':'')+(mo.llm_error?`<div class="tag">news read: ${mo.llm_error}</div>`:'');
 const st=s.status||{};document.getElementById('u2status').innerHTML=st.mode==='in trade'?`<b>${st.side}</b> ${st.key.replace('NSE_','')}<br>entry ${st.entry} @ ₹${st.entry_px} · bid ₹${st.bid??'—'}<br>floor ${st.floor??'—'}${st.tightened?' (tightened)':''} · best ${fmt(st.best_lot)}<br><b class="${cls(st.pnl_lot)}" style="font-size:20px">${fmt(st.pnl_lot)}</b> /lot`:st.mode==='waiting'?`<b>WAITING</b> for ${st.side} (signal ${st.signal}, ${st.class}) · ${st.waiting_s}s`:'Idle: watching for a Gate-1 signal';
 document.getElementById('u2side').innerHTML=['CALL','PUT'].map(k=>{const x=(s.side||{})[k]||{};return `<div><b>${k}</b> · <span class="${x.state==='POSITIVE'?'pos':x.state==='NEGATIVE'?'neg':''}">${x.state||'—'}</span> ${x.health??''} (${x.held_s??0}s)<br>`+(x.plus||[]).map(t=>`<div class="pos">${t}</div>`).join('')+(x.minus||[]).map(t=>`<div class="neg">${t}</div>`).join('')+'</div>';}).join('');
 document.getElementById('u2pend').textContent=s.pendulum?`Pendulum: swing ≈ ${s.pendulum.swing_pts} pts every ≈ ${s.pendulum.swing_secs}s (last 30 min)`:'';
 const dec=(s.decisions||[]).slice().reverse();document.getElementById('u2dec').innerHTML=dec.length?'<tr><th>Signal</th><th>Side</th><th>Decision</th><th>Why</th><th>At</th></tr>'+dec.map(x=>`<tr><td>${x.signal}</td><td>${x.side} ${x.cls||''}</td><td class="${x.decision==='ENTER'?'pos':x.decision==='SKIP'?'neg':''}">${x.decision}${x.waited_s!=null?' +'+x.waited_s+'s':''}</td><td>${x.why||''}</td><td>${x.at||''}</td></tr>`).join(''):'<tr><td>No signals yet</td></tr>';
 const tr=s.trades||[];document.getElementById('u2tr').innerHTML=tr.length?'<tr><th>Side</th><th>Entry</th><th>Exit</th><th>Why</th><th>Best</th><th>₹/lot</th></tr>'+tr.map(t=>`<tr><td>${t.side}</td><td>${t.entry} @ ${t.entry_px}</td><td>${t.exit} @ ${t.exit_px}</td><td>${t.reason}</td><td>${fmt(t.best_lot)}</td><td class="${cls(t.pnl_lot)}">${fmt(t.pnl_lot)}</td></tr>`).join(''):'<tr><td>No U2 trades yet today</td></tr>';
 document.getElementById('u2var').innerHTML='<tr><th>Variant</th><th>Trades</th><th>Wins</th><th>Total</th></tr>'+(s.variants||[]).map(v=>`<tr><td>${v.variant}${v.open?' •':''}</td><td>${v.trades}</td><td>${v.wins}</td><td class="${cls(v.total)}">${fmt(v.total)}</td></tr>`).join('');
 document.getElementById('u2vs').innerHTML='<tr><th>Day</th><th>EC0</th><th>EC1</th><th>EC2</th><th>EC2+</th><th>U2</th></tr>'+(a.vs||[]).map(r=>`<tr><td>${r.day}</td>`+['EC0','EC1','EC2','EC2P','U2'].map(k=>`<td class="${cls(r[k])}">${fmt(r[k])}</td>`).join('')+'</tr>').join('');
 const m=a.main||{};document.getElementById('u2all').textContent=`U2 MAIN all-time: ${m.trades||0} trades, ${fmt(m.total)} total, win ${m.win_rate??'—'}%`;
}
tick();setInterval(tick,5000);tick2();setInterval(tick2,5000);
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
            cur_tr = [t for t in tr if (t.get("version") or "v1") == cur]
            body = stats(cur_tr) | {"version": cur, "groups": grouped(tr), "challengers": challengers(cur_tr)}
            self._send(json.dumps(body).encode(), "application/json")
        elif self.path == "/api/u2/state":
            f = DATA_U2 / "state.json"
            self._send(f.read_bytes() if f.exists() else b"{}", "application/json")
        elif self.path == "/api/u2/stats":
            self._send(json.dumps(u2_stats()).encode(), "application/json")
        elif self.path in ("/", "/index.html"):
            self._send(PAGE.encode("utf-8"), "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def log_message(self, *_: Any) -> None:
        pass


if __name__ == "__main__":
    print(f"U1 dashboard on http://127.0.0.1:{PORT}  (PAPER ONLY; reads premium/data/u1)")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
