#!/usr/bin/env python3
"""Ledger v4 — a single-file, per-user trading journal for Render + Neon Postgres.

Trades are stored in a Neon (or any managed Postgres) database via DATABASE_URL,
so data survives Render restarts, sleeps, and redeploys on the free tier —
nothing gets wiped when the app spins down and wakes back up.

Required Render environment variables:
  DATABASE_URL          — Neon connection string (Neon dashboard -> Connection Details)
  GOOGLE_CLIENT_ID       — Google Cloud OAuth client ID
  GOOGLE_CLIENT_SECRET   — Google Cloud OAuth client secret
  SESSION_SECRET         — any long random string, used to sign login sessions
  APP_URL                — your Render app's public URL, e.g. https://ledger-xxxx.onrender.com

In Google Cloud Console, add APP_URL + /auth/google/callback as an authorised
redirect URI on the OAuth client.

You can inspect or edit trades directly any time from the Neon dashboard's
SQL Editor (Tables -> trades), independent of what Render is doing.
"""
import base64, hashlib, hmac, json, os, secrets, sys, time, urllib.error, urllib.parse, urllib.request, uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import RLock

# Render captures stdout through a pipe, not a terminal, so Python's default
# buffering can silently hold log lines back indefinitely on a long-running
# server. Force line buffering so every print() shows up immediately.
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

PORT = int(os.environ.get("PORT", "8000"))
APP_URL = os.environ.get("APP_URL", "").strip().rstrip("/")
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
SESSION_SECRET = os.environ.get("SESSION_SECRET", "").strip()
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
LOCK = RLock()
MAX_BODY = 1_600_000

_POOL = None


def get_pool():
    global _POOL
    if _POOL is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set.")
        _POOL = ThreadedConnectionPool(1, 10, DATABASE_URL, sslmode="require")
    return _POOL


def init_db():
    if not DATABASE_URL:
        print("WARNING: DATABASE_URL not set - trades will fail to save. Add your Neon connection string in Render's environment variables.", flush=True)
        return
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    user_email TEXT NOT NULL,
                    trade_date TEXT,
                    type TEXT,
                    symbol TEXT,
                    pnl NUMERIC,
                    setup TEXT,
                    side TEXT,
                    entry TEXT,
                    exit_price TEXT,
                    rr TEXT,
                    notes TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_trades_user_email ON trades (user_email)")
        conn.commit()
        print("Neon database ready: trades table checked/created.", flush=True)
    finally:
        pool.putconn(conn)


def db_load_trades(email):
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, trade_date AS date, type, symbol, pnl, setup, side, entry, "
                "exit_price AS exit, rr, notes FROM trades "
                "WHERE user_email = %s ORDER BY created_at DESC",
                (email,),
            )
            rows = cur.fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["pnl"] = float(d["pnl"]) if d["pnl"] is not None else 0.0
            result.append(d)
        return result
    finally:
        pool.putconn(conn)


def db_insert_trade(email, trade):
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO trades (id, user_email, trade_date, type, symbol, pnl, setup, "
                "side, entry, exit_price, rr, notes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    trade["id"], email, trade["date"], trade["type"], trade["symbol"],
                    trade["pnl"], trade["setup"], trade["side"], trade["entry"],
                    trade["exit"], trade["rr"], trade["notes"],
                ),
            )
        conn.commit()
    finally:
        pool.putconn(conn)


def db_update_trade(email, trade_id, trade):
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE trades SET trade_date=%s, type=%s, symbol=%s, pnl=%s, setup=%s, "
                "side=%s, entry=%s, exit_price=%s, rr=%s, notes=%s "
                "WHERE id=%s AND user_email=%s",
                (
                    trade["date"], trade["type"], trade["symbol"], trade["pnl"],
                    trade["setup"], trade["side"], trade["entry"], trade["exit"],
                    trade["rr"], trade["notes"], trade_id, email,
                ),
            )
            updated = cur.rowcount > 0
        conn.commit()
        return updated
    finally:
        pool.putconn(conn)


def db_delete_trade(email, trade_id):
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM trades WHERE id=%s AND user_email=%s", (trade_id, email))
        conn.commit()
    finally:
        pool.putconn(conn)


PAGE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#07112a"><meta name="mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"><link rel="manifest" href="/manifest.webmanifest"><link rel="apple-touch-icon" href="/icon.svg"><title>Ledger</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#0a1022;color:#eaf0ff;font:15px Inter,system-ui,sans-serif}header{height:66px;padding:0 5vw;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #223052;background:#0d1630;position:sticky;top:0;z-index:5}.brand{font-weight:800;font-size:21px;letter-spacing:.4px}.brand i{color:#5eead4;font-style:normal}nav{display:flex;gap:8px}button,.button{border:0;border-radius:9px;padding:10px 14px;background:#1c2a4a;color:#eaf0ff;font:inherit;cursor:pointer;text-decoration:none;display:inline-block}.primary{background:#19b997;color:#061714;font-weight:700}.danger{color:#ff9c9c;background:#402030}.muted{color:#9ba8c7}.wrap{max-width:1180px;margin:auto;padding:28px 5vw}.page{display:none}.page.active{display:block}.hero{display:flex;align-items:center;justify-content:space-between;margin:8px 0 25px}.hero h1{margin:0;font-size:27px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.card{background:#101b36;border:1px solid #243456;border-radius:14px;padding:18px}.label{color:#9ba8c7;font-size:12px;text-transform:uppercase;letter-spacing:.8px}.value{font-size:26px;font-weight:750;margin-top:7px}.pos{color:#55dfad}.neg{color:#ff8989}.chart{height:180px;margin-top:16px}.chart svg{width:100%;height:100%}.section{margin-top:22px}.toolbar{display:flex;gap:8px;flex-wrap:wrap;margin:13px 0}.toolbar input,.toolbar select,input,select,textarea{background:#0a132a;border:1px solid #2a3c62;border-radius:8px;padding:10px;color:#edf3ff;font:inherit}textarea{width:100%;min-height:80px}.trades{overflow:auto}.trade{display:grid;grid-template-columns:1.1fr .8fr 1fr .9fr .7fr;gap:12px;align-items:center;padding:14px;border-top:1px solid #223052}.trade:first-child{border:0}.symbol{font-weight:750}.empty{padding:32px;text-align:center;color:#9ba8c7}.modal{display:none;position:fixed;inset:0;background:#0009;z-index:10;padding:25px;overflow:auto}.modal.open{display:flex;align-items:center;justify-content:center}.dialog{width:min(620px,100%);background:#101b36;border:1px solid #31466e;border-radius:15px;padding:22px}.formgrid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.formgrid label{display:grid;gap:6px;color:#b8c4e3}.full{grid-column:1/-1}.settings{max-width:700px}.account{display:flex;align-items:center;gap:15px}.avatar{width:45px;height:45px;border-radius:50%;background:#263b64;display:grid;place-items:center;font-weight:800}.notice{padding:13px;border-radius:9px;background:#152747;color:#bdcff5;margin:14px 0}.footer-actions{display:flex;justify-content:flex-end;gap:9px;margin-top:16px}@media(max-width:700px){.grid{grid-template-columns:repeat(2,1fr)}.trade{grid-template-columns:1fr 1fr}.trade .hide-mobile{display:none}.formgrid{grid-template-columns:1fr}header{padding:0 15px}.wrap{padding:22px 15px}.hero{align-items:flex-start;gap:15px}.value{font-size:22px}}
/* Ledger v4 visual layer */
@keyframes floatOrb{0%,100%{transform:translate3d(0,0,0) scale(1)}50%{transform:translate3d(4vw,3vh,0) scale(1.12)}}
@keyframes riseIn{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}
@keyframes shimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}
:root{--ink:#eaf6ff;--muted:#9eb3cc;--surface:rgba(14,27,57,.72);--stroke:rgba(147,203,255,.16);--cyan:#6ef2e0;--violet:#9a8cff;--pink:#fa78c4}
body{min-height:100vh;background:#050b1b;color:var(--ink);letter-spacing:.01em;overflow-x:hidden}
body:before,body:after{content:"";position:fixed;z-index:-1;width:48vw;height:48vw;border-radius:50%;filter:blur(40px);opacity:.26;pointer-events:none;animation:floatOrb 15s ease-in-out infinite}
body:before{background:#2a44d4;top:-23vw;left:-14vw}body:after{background:#057c8c;right:-17vw;bottom:-24vw;animation-delay:-7s}
header{height:76px;background:rgba(5,12,31,.62);backdrop-filter:blur(22px);border-color:var(--stroke);box-shadow:0 12px 35px rgba(0,0,0,.16)}
.brand{display:flex;align-items:center;gap:10px;font-size:23px;letter-spacing:-.7px}.brand:before{content:"↗";display:grid;place-items:center;width:31px;height:31px;border-radius:10px;color:#021c24;background:linear-gradient(135deg,var(--cyan),#55a9ff);box-shadow:0 5px 17px #46e7d466;font-weight:900}.brand i{font-size:11px;padding:4px 7px;border:1px solid #6ef2e044;background:#6ef2e01a;border-radius:99px;letter-spacing:.4px}
nav{padding:5px;border:1px solid var(--stroke);border-radius:13px;background:#07102799;gap:3px}nav button{border-radius:9px;background:transparent;color:#9eb3cc;padding:8px 12px;font-size:13px;transition:.22s ease}nav button:hover,nav button.active{background:linear-gradient(135deg,#192d5a,#1b3e5e);color:#eaffff;box-shadow:0 4px 18px #0004}
.wrap{max-width:1240px;padding-top:38px}.page.active{animation:riseIn .4s cubic-bezier(.2,.8,.2,1)}.hero{margin:0 0 29px}.hero h1{font-size:clamp(28px,4vw,40px);letter-spacing:-1.5px;background:linear-gradient(100deg,#fff 10%,#9cddff 55%,#7ff4de);background-size:200% auto;-webkit-background-clip:text;background-clip:text;color:transparent;animation:shimmer 7s linear infinite}.hero p{font-size:15px;margin-top:8px}
.primary{position:relative;overflow:hidden;background:linear-gradient(135deg,var(--cyan),#57aaff);border:1px solid #b6fff466;box-shadow:0 9px 25px #27cdb444;transition:transform .2s,box-shadow .2s}.primary:hover{transform:translateY(-2px);box-shadow:0 14px 32px #27cdb466}.primary:after{content:"";position:absolute;inset:0;background:linear-gradient(110deg,transparent 30%,#fff8 50%,transparent 70%);transform:translateX(-120%);transition:.5s}.primary:hover:after{transform:translateX(120%)}
.card{position:relative;overflow:hidden;background:linear-gradient(145deg,rgba(22,39,78,.84),rgba(8,18,43,.79));border-color:var(--stroke);box-shadow:0 15px 34px rgba(0,0,0,.14);border-radius:18px;transition:transform .25s ease,border-color .25s ease,box-shadow .25s ease}.card:hover{transform:translateY(-4px);border-color:#78e7e047;box-shadow:0 23px 44px rgba(0,0,0,.24)}.card:before{content:"";position:absolute;inset:0 0 auto;height:1px;background:linear-gradient(90deg,transparent,#88f6ec99,transparent)}.grid .card:nth-child(2):before{background:linear-gradient(90deg,transparent,#9b8dff99,transparent)}.grid .card:nth-child(3):before{background:linear-gradient(90deg,transparent,#74baff99,transparent)}.grid .card:nth-child(4):before{background:linear-gradient(90deg,transparent,#f779c899,transparent)}
.label{font-weight:700;color:#9eb3cc;letter-spacing:1.15px}.value{font-size:30px;letter-spacing:-1.2px}.pos{color:#72f4c3}.neg{color:#ff91a5}.muted{color:var(--muted)}
.section{margin-top:19px}.chart{padding-top:8px}.trade{transition:background .2s,transform .2s;border-color:var(--stroke)}.trade:hover{background:#7ee4ff0b;transform:translateX(3px)}.symbol{letter-spacing:.2px}.trades{padding:3px 9px}.toolbar input,.toolbar select,input,select,textarea{border-color:var(--stroke);background:#07122bd1;transition:border-color .2s,box-shadow .2s}.toolbar input:focus,.toolbar select:focus,input:focus,select:focus,textarea:focus{outline:none;border-color:#67e9dcaa;box-shadow:0 0 0 3px #67e9dc16}.button,button:not(.primary){border:1px solid var(--stroke);background:#122348;transition:.2s}.button:hover,button:not(.primary):hover{border-color:#78e7e066;background:#1b3567}.danger{background:#3e1c35!important;border-color:#ff91a540!important}.modal{backdrop-filter:blur(12px)}.dialog{background:linear-gradient(145deg,#17274f,#09142d);border-color:#78e7e052;box-shadow:0 30px 90px #000b;border-radius:22px;animation:riseIn .27s ease}.dialog h2{margin-top:0;letter-spacing:-.7px}.notice{background:linear-gradient(110deg,#12315a,#152449);border:1px solid var(--stroke);border-radius:13px}code{color:#76f3dd;background:#071128;padding:2px 5px;border-radius:5px}
@media(max-width:700px){header{height:66px}.brand:before{width:27px;height:27px}.brand{font-size:20px}.brand i{display:none}nav button{font-size:0;padding:9px 10px}nav button:after{font-size:15px}nav button:nth-child(1):after{content:'◫'}nav button:nth-child(2):after{content:'≡'}nav button:nth-child(3):after{content:'⚙'}}
.market-pulse{position:absolute;left:50%;transform:translateX(-50%);display:flex;align-items:center;gap:9px;color:#aabed9;font-size:11px;letter-spacing:1px;text-transform:uppercase}.market-pulse:before{content:"";width:7px;height:7px;border-radius:99px;background:#6ef2e0;box-shadow:0 0 0 5px #6ef2e018,0 0 14px #6ef2e0;animation:pulseDot 1.9s ease-in-out infinite}@keyframes pulseDot{50%{box-shadow:0 0 0 9px #6ef2e000,0 0 18px #6ef2e0}}.market-pulse b{color:#6ef2e0;font-weight:800}
.terminal-kicker{display:inline-flex;gap:8px;align-items:center;padding:6px 10px;border-radius:99px;border:1px solid #6ef2e03b;background:#6ef2e00d;color:#8bf8e8;font-size:11px;font-weight:800;letter-spacing:1.1px;text-transform:uppercase;margin-bottom:12px}.terminal-kicker:before{content:"";height:6px;width:6px;border-radius:50%;background:#70f7c8;box-shadow:0 0 10px #70f7c8}.hero h1{margin-top:0}.grid .card{min-height:138px;padding:20px}.grid .card .label{display:flex;align-items:center;gap:8px}.grid .card .label:before{display:grid;place-items:center;width:25px;height:25px;border-radius:8px;background:#6ef2e015;color:#77f6e4;font-size:14px}.grid .card:nth-child(1) .label:before{content:"↗"}.grid .card:nth-child(2) .label:before{content:"◫";color:#a89cff;background:#a89cff16}.grid .card:nth-child(3) .label:before{content:"◎";color:#81c5ff;background:#81c5ff16}.grid .card:nth-child(4) .label:before{content:"◇";color:#fd8ccf;background:#fd8ccf16}.grid .card .value{margin-top:14px}.grid .card:after{content:"";position:absolute;width:90px;height:90px;border:1px solid currentColor;border-radius:50%;right:-40px;bottom:-48px;opacity:.09}.grid .card:nth-child(1){color:#6ef2e0}.grid .card:nth-child(2){color:#a89cff}.grid .card:nth-child(3){color:#81c5ff}.grid .card:nth-child(4){color:#fd8ccf}.grid .card .label,.grid .card .value{color:inherit}.grid .card .label{color:#b8c9df}.grid .card .value.pos,.grid .card .value.neg{color:inherit}.section>.label{display:flex;align-items:center;gap:9px;font-size:12px}.section>.label:after{content:"";height:1px;flex:1;background:linear-gradient(90deg,#75f2e047,transparent)}#chart{position:relative;background:radial-gradient(ellipse at 50% 100%,#3ac8bd14,transparent 65%);border-radius:12px}.trade .symbol:before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;background:#75f3dd;box-shadow:0 0 10px #75f3dd;margin-right:8px}.trade:nth-child(odd) .symbol:before{background:#a99bff;box-shadow:0 0 10px #a99bff}.empty{border:1px dashed #7fc7ff2b;border-radius:12px;margin:8px;background:#07112966}.account .avatar{background:linear-gradient(135deg,#74eede,#6999ff);color:#06132a;box-shadow:0 6px 17px #62dfff42}.settings .card{padding:22px}.footer-actions{padding-top:4px}@media(max-width:780px){.market-pulse{display:none}.grid .card{min-height:122px}}
</style></head><body><header><div class="brand">Ledger <i>v4</i></div><div class="market-pulse"><b>● Live</b> &nbsp; Personal trading terminal</div><nav><button class="active" onclick="show('dashboard')">Dashboard</button><button onclick="show('journal')">Journal</button><button onclick="show('settings')">Settings</button><button id="installBtn" hidden onclick="installApp()">Install</button></nav></header><main class="wrap">
<section class="page active" id="dashboard"><div class="hero"><div><div class="terminal-kicker">Performance overview</div><h1>Your trading dashboard</h1><p class="muted" id="dashSub">Sign in to see your personal journal.</p></div><button class="primary" onclick="openTrade()">+ Log trade</button></div><div class="grid"><div class="card"><div class="label">Net P&amp;L</div><div id="net" class="value">—</div></div><div class="card"><div class="label">Trades</div><div id="count" class="value">—</div></div><div class="card"><div class="label">Win rate</div><div id="winrate" class="value">—</div></div><div class="card"><div class="label">Profit factor</div><div id="factor" class="value">—</div></div></div><div class="card section"><div class="label">Equity curve</div><div class="chart" id="chart"></div></div><div class="card section"><div class="label">Recent trades</div><div id="recent"></div></div></section>
<section class="page" id="journal"><div class="hero"><div><h1>Trade journal</h1><p class="muted">Search and review your saved trades.</p></div><button class="primary" onclick="openTrade()">+ Log trade</button></div><div class="toolbar"><input id="search" placeholder="Search symbol" oninput="render()"><select id="result" onchange="render()"><option value="">All results</option><option value="win">Winners</option><option value="loss">Losers</option></select><button onclick="downloadCsv()">Export CSV</button></div><div class="card trades"><div id="journalList"></div></div></section>
<section class="page" id="settings"><div class="settings"><div class="hero"><div><h1>Settings</h1><p class="muted">Your journal is private to your signed-in account.</p></div></div><div class="card"><div class="label">Account</div><div id="account" class="notice">Checking sign-in…</div></div><div class="card section"><div class="label">Storage</div><p class="muted">Trades are stored in a Neon Postgres database, scoped to your Google account — they persist across Render restarts, sleeps, and redeploys.</p><p class="muted">Set <code>DATABASE_URL</code> in Render to your Neon connection string to enable saving. You can also browse or edit rows directly in Neon's SQL Editor at any time.</p></div><div class="card section"><div class="label">Google login setup</div><p class="muted">Set <code>GOOGLE_CLIENT_ID</code>, <code>GOOGLE_CLIENT_SECRET</code>, <code>SESSION_SECRET</code>, and <code>APP_URL</code> in Render. In Google Cloud Console, add <code id="redirect"></code> as an authorized redirect URI.</p></div></div></section>
</main><div class="modal" id="modal"><div class="dialog"><h2 id="formTitle">Log a trade</h2><div class="formgrid"><label>Date<input id="date" type="date"></label><label>Market<select id="type"><option>stock</option><option>forex</option><option>crypto</option><option>future</option><option>index</option></select></label><label>Symbol<input id="symbol" placeholder="AAPL" maxlength="16"></label><label>P&amp;L<input id="pnl" type="number" step="0.01" placeholder="125.50"></label><label>Setup<input id="setup" placeholder="Breakout"></label><label>Side<select id="side"><option>Long</option><option>Short</option></select></label><label>Entry<input id="entry" placeholder="Price"></label><label>Exit<input id="exit" placeholder="Price"></label><label>R:R<input id="rr" placeholder="2.5"></label><label class="full">Notes<textarea id="notes" placeholder="What did you see? What will you repeat or improve?"></textarea></label></div><div id="formMsg" class="muted"></div><div class="footer-actions"><button onclick="closeTrade()">Cancel</button><button class="primary" onclick="saveTrade()">Save trade</button></div></div></div>
<script>
let trades=[],me=null,editing=null;const $=id=>document.getElementById(id);$('redirect').textContent=location.origin+'/auth/google/callback';
async function api(url,opt={}){const r=await fetch(url,opt);if(!r.ok)throw new Error((await r.json().catch(()=>({}))).error||'Request failed');return r.json()}
function money(x){return (x>=0?'+$':'-$')+Math.abs(x).toFixed(2)}function esc(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function show(id){document.querySelectorAll('.page').forEach(x=>x.classList.toggle('active',x.id===id));document.querySelectorAll('nav button').forEach(x=>x.classList.toggle('active',x.textContent.trim().toLowerCase()===id));render()}
function filtered(){let s=$('search').value.trim().toUpperCase(),r=$('result').value;return trades.filter(t=>(!s||t.symbol.includes(s))&&(!r||(r==='win'?t.pnl>0:t.pnl<0)))}
function rows(list,actions=false){if(!list.length)return '<div class="empty">No trades yet. Log your first trade when you are ready.</div>';return list.map(t=>`<div class="trade"><div><div class="symbol">${esc(t.symbol)}</div><div class="muted">${esc(t.date)} · ${esc(t.side||'')}</div></div><div class="hide-mobile">${esc(t.type)}</div><div class="hide-mobile">${esc(t.setup||'—')}</div><div class="${t.pnl>0?'pos':t.pnl<0?'neg':''}">${money(t.pnl)}</div><div>${actions?`<button onclick="editTrade('${t.id}')">Edit</button> <button class="danger" onclick="removeTrade('${t.id}')">Delete</button>`:''}</div></div>`).join('')}
function stats(){let n=trades.length,w=trades.filter(t=>t.pnl>0),l=trades.filter(t=>t.pnl<0),net=trades.reduce((a,t)=>a+t.pnl,0),gp=w.reduce((a,t)=>a+t.pnl,0),gl=Math.abs(l.reduce((a,t)=>a+t.pnl,0));return{n,w,l,net,pf:gl?gp/gl:(gp?'∞':0)}}
function draw(){let a=[...trades].reverse(),v=0,pts=[0,...a.map(t=>v+=t.pnl)],min=Math.min(0,...pts),max=Math.max(0,...pts),range=max-min||1,w=600,h=160;let p=pts.map((x,i)=>`${i*(w/(pts.length-1||1))},${h-10-(x-min)/range*(h-24)}`).join(' ');$('chart').innerHTML=trades.length?`<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><line x1="0" x2="${w}" y1="${h-10-(0-min)/range*(h-24)}" y2="${h-10-(0-min)/range*(h-24)}" stroke="#425578"/><polyline fill="none" stroke="${v>=0?'#55dfad':'#ff8989'}" stroke-width="3" points="${p}"/></svg>`:'<div class="empty">Your equity curve will appear here.</div>'}
function render(){let s=stats();$('net').textContent=money(s.net);$('net').className='value '+(s.net>0?'pos':s.net<0?'neg':'');$('count').textContent=s.n;$('winrate').textContent=s.n?Math.round(s.w.length/s.n*100)+'%':'—';$('factor').textContent=s.pf==='∞'?'∞':s.pf.toFixed(2);$('dashSub').textContent=me?'Private journal for '+me.name:'Sign in to create your personal journal.';$('recent').innerHTML=rows(trades.slice(0,5));$('journalList').innerHTML=rows(filtered(),true);draw();let a=$('account');a.innerHTML=me?`<div class="account"><div class="avatar">${esc(me.name[0])}</div><div><strong>${esc(me.name)}</strong><br><span class="muted">${esc(me.email)}</span></div><div style="margin-left:auto"><a class="button" href="/auth/logout">Sign out</a></div></div>`:`<strong>You are not signed in.</strong><p class="muted">Sign in with Google to save and access your trades from your account.</p><a class="button primary" href="/auth/google">Continue with Google</a>`}
function openTrade(){if(!me){show('settings');return}editing=null;$('formTitle').textContent='Log a trade';['symbol','pnl','setup','entry','exit','rr','notes'].forEach(k=>$(k).value='');$('date').value=new Date().toISOString().slice(0,10);$('type').value='stock';$('side').value='Long';$('formMsg').textContent='';$('modal').classList.add('open')};function closeTrade(){$('modal').classList.remove('open')}
function editTrade(id){let t=trades.find(x=>x.id===id);if(!t)return;editing=id;$('formTitle').textContent='Edit trade';for(let k of ['date','type','symbol','pnl','setup','side','entry','exit','rr','notes'])$(k).value=t[k]??'';$('modal').classList.add('open')}
async function saveTrade(){let x={date:$('date').value,type:$('type').value,symbol:$('symbol').value,pnl:$('pnl').value,setup:$('setup').value,side:$('side').value,entry:$('entry').value,exit:$('exit').value,rr:$('rr').value,notes:$('notes').value};if(!x.symbol.trim())return $('formMsg').textContent='Please enter a symbol.';try{let d=await api(editing?'/api/trades/'+editing:'/api/trades',{method:editing?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(x)});trades=d.trades;closeTrade();render()}catch(e){$('formMsg').textContent=e.message}}
async function removeTrade(id){if(!confirm('Delete this trade?'))return;try{trades=(await api('/api/trades/'+id,{method:'DELETE'})).trades;render()}catch(e){alert(e.message)}}
function downloadCsv(){let r=filtered();if(!r.length)return;let heads=['date','type','symbol','side','pnl','setup','entry','exit','rr','notes'];let csv=[heads,...r.map(t=>heads.map(h=>JSON.stringify(t[h]??'')))].map(x=>x.join(',')).join('\n');let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download='ledger-trades.csv';a.click()}
(function(){let installEvent;const button=$('installBtn');window.addEventListener('beforeinstallprompt',e=>{e.preventDefault();installEvent=e;button.hidden=false});window.installApp=async()=>{if(!installEvent)return;installEvent.prompt();await installEvent.userChoice;installEvent=null;button.hidden=true};window.addEventListener('appinstalled',()=>button.hidden=true);if('serviceWorker'in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{})})();
(async()=>{let p=new URLSearchParams(location.search);let authErr=p.get('auth');if(authErr){let msg={configuration_needed:'Google sign-in is not fully configured yet (missing APP_URL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, or SESSION_SECRET).',state_mismatch:'Sign-in session expired or the state cookie was blocked. Try again, and make sure cookies are allowed.',token_exchange_failed:'Google rejected the sign-in exchange. This usually means the redirect URI in Google Cloud does not exactly match APP_URL, or the client secret is wrong.',google_http_error:'Google returned an error during sign-in. Check Render logs for the exact response.',exception:'Something unexpected went wrong during sign-in. Check Render logs for details.'}[authErr]||('Sign-in failed: '+authErr);let el=document.createElement('div');el.className='notice';el.style.cssText='position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:99;max-width:90vw;background:#3e1c1c;border:1px solid #ff91a5;color:#ffd7dd';el.textContent=msg;document.body.appendChild(el);history.replaceState({},'',location.pathname)}try{let d=await api('/api/me');me=d.user;if(me)trades=(await api('/api/trades')).trades}catch(e){}render()})();
</script></body></html>'''


def cookie_value(headers, name):
    c = SimpleCookie()
    c.load(headers.get('Cookie', ''))
    return c[name].value if name in c else None


def session_for(handler):
    raw = cookie_value(handler.headers, 'ledger_session')
    if not raw or '.' not in raw or not SESSION_SECRET:
        return None
    payload, sig = raw.rsplit('.', 1)
    expected = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        return data if data.get('exp', 0) > time.time() else None
    except Exception:
        return None


def signed_session(user):
    data = {'email': user['email'], 'name': user['name'], 'exp': time.time() + 60 * 60 * 24 * 14}
    payload = base64.urlsafe_b64encode(json.dumps(data, separators=(',', ':')).encode()).decode().rstrip('=')
    return payload + '.' + hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def clean_trade(d):
    try:
        pnl = round(float(d.get('pnl', 0)), 2)
    except (ValueError, TypeError):
        raise ValueError('P&L must be a number.')
    symbol = str(d.get('symbol', '')).strip().upper()[:16]
    if not symbol:
        raise ValueError('Symbol is required.')
    return {
        'date': str(d.get('date', ''))[:10],
        'type': str(d.get('type', 'stock'))[:15],
        'symbol': symbol,
        'pnl': pnl,
        'setup': str(d.get('setup', '')).strip()[:80],
        'side': str(d.get('side', 'Long'))[:10],
        'entry': str(d.get('entry', '')).strip()[:30],
        'exit': str(d.get('exit', '')).strip()[:30],
        'rr': str(d.get('rr', '')).strip()[:20],
        'notes': str(d.get('notes', '')).strip()[:2000],
    }


MANIFEST = json.dumps({
    'name': 'Ledger — Trade Journal', 'short_name': 'Ledger', 'start_url': '/', 'display': 'standalone',
    'background_color': '#07112a', 'theme_color': '#07112a',
    'icons': [{'src': '/icon.svg', 'sizes': 'any', 'type': 'image/svg+xml', 'purpose': 'any maskable'}],
})
ICON_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#6ef2e0"/><stop offset="1" stop-color="#599cff"/></linearGradient></defs><rect width="512" height="512" rx="112" fill="#07112a"/><rect x="47" y="47" width="418" height="418" rx="84" fill="url(#g)"/><path d="M130 342l82-102 58 54 108-137" fill="none" stroke="#06152b" stroke-linecap="round" stroke-linejoin="round" stroke-width="38"/><path d="M330 157h48v48" fill="none" stroke="#06152b" stroke-linecap="round" stroke-linejoin="round" stroke-width="38"/></svg>'''
SERVICE_WORKER = """const CACHE='ledger-v4';self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(['/','/manifest.webmanifest','/icon.svg']))));self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));self.addEventListener('fetch',e=>{if(e.request.method==='GET'&&new URL(e.request.url).origin===location.origin&&new URL(e.request.url).pathname==='/')e.respondWith(fetch(e.request).catch(()=>caches.match('/')))});"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send_json(self, obj, status=200, cookie=None):
        b = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(b)))
        self.security(cookie)
        self.end_headers()
        self.wfile.write(b)

    def send_html(self):
        b = PAGE.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(b)))
        self.security()
        self.end_headers()
        self.wfile.write(b)

    def send_asset(self, body, content_type):
        b = body.encode()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'public, max-age=86400')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(b)

    def security(self, cookie=None):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'strict-origin-when-cross-origin')
        self.send_header('Cache-Control', 'no-store')
        if cookie:
            self.send_header('Set-Cookie', cookie)

    def redirect(self, url, cookie=None):
        self.send_response(302)
        self.send_header('Location', url)
        self.security(cookie)
        self.end_headers()

    def body(self):
        try:
            n = int(self.headers.get('Content-Length', '0'))
            if n > MAX_BODY:
                raise ValueError('Request too large.')
            return json.loads(self.rfile.read(n or 2).decode())
        except Exception as e:
            raise ValueError('Invalid request data.') from e

    def require_user(self):
        u = session_for(self)
        if not u:
            self.send_json({'error': 'Sign in with Google first.'}, 401)
            return None
        return u

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == '/':
            return self.send_html()
        if path == '/manifest.webmanifest':
            return self.send_asset(MANIFEST, 'application/manifest+json; charset=utf-8')
        if path == '/icon.svg':
            return self.send_asset(ICON_SVG, 'image/svg+xml; charset=utf-8')
        if path == '/sw.js':
            return self.send_asset(SERVICE_WORKER, 'application/javascript; charset=utf-8')
        if path == '/api/me':
            u = session_for(self)
            return self.send_json({'user': {'email': u['email'], 'name': u['name']} if u else None})
        if path == '/api/trades':
            if (u := self.require_user()):
                with LOCK:
                    try:
                        self.send_json({'trades': db_load_trades(u['email'])})
                    except Exception:
                        self.send_json({'error': 'Database not reachable. Check DATABASE_URL.'}, 500)
            return
        if path == '/auth/google':
            if not (APP_URL and GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and SESSION_SECRET):
                return self.redirect('/?auth=configuration_needed')
            state = secrets.token_urlsafe(24)
            q = urllib.parse.urlencode({
                'client_id': GOOGLE_CLIENT_ID, 'redirect_uri': APP_URL + '/auth/google/callback',
                'response_type': 'code', 'scope': 'openid email profile', 'state': state,
                'prompt': 'select_account',
            })
            return self.redirect(
                'https://accounts.google.com/o/oauth2/v2/auth?' + q,
                f'google_state={state}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=600',
            )
        if path == '/auth/google/callback':
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            state = q.get('state', [''])[0]
            if not state or state != cookie_value(self.headers, 'google_state'):
                print('OAuth callback: state mismatch or missing. Got state=%r, cookie=%r' % (
                    state, cookie_value(self.headers, 'google_state')), flush=True)
                return self.redirect('/?auth=state_mismatch')
            if not q.get('code'):
                print('OAuth callback: no code in query string. Full query: %r' % q, flush=True)
                err = q.get('error', ['no_code'])[0]
                return self.redirect('/?auth=' + urllib.parse.quote(err))
            try:
                data = urllib.parse.urlencode({
                    'code': q['code'][0], 'client_id': GOOGLE_CLIENT_ID, 'client_secret': GOOGLE_CLIENT_SECRET,
                    'redirect_uri': APP_URL + '/auth/google/callback', 'grant_type': 'authorization_code',
                }).encode()
                token = json.loads(urllib.request.urlopen(
                    urllib.request.Request(
                        'https://oauth2.googleapis.com/token', data=data,
                        headers={'Content-Type': 'application/x-www-form-urlencoded'},
                    ), timeout=10
                ).read())
                if 'access_token' not in token:
                    print('OAuth callback: token exchange failed, response: %r' % token, flush=True)
                    return self.redirect('/?auth=token_exchange_failed')
                info = json.loads(urllib.request.urlopen(
                    urllib.request.Request(
                        'https://openidconnect.googleapis.com/v1/userinfo',
                        headers={'Authorization': 'Bearer ' + token['access_token']},
                    ), timeout=10
                ).read())
                if not info.get('email_verified'):
                    print('OAuth callback: email not verified, userinfo: %r' % info, flush=True)
                    raise ValueError('Google email not verified')
                u = {'email': info['email'], 'name': info.get('name') or info['email'].split('@')[0]}
                return self.redirect(
                    '/', f'ledger_session={signed_session(u)}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=1209600'
                )
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors='replace')
                print('OAuth callback: HTTPError from Google: %s %s -- body: %s' % (e.code, e.reason, body), flush=True)
                return self.redirect('/?auth=google_http_error')
            except Exception as e:
                print('OAuth callback: unexpected exception: %r' % e, flush=True)
                return self.redirect('/?auth=exception')
        if path == '/auth/logout':
            return self.redirect('/', 'ledger_session=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0')
        self.send_error(404)

    def do_POST(self):
        self.write_trade('new')

    def do_PUT(self):
        self.write_trade('edit')

    def do_DELETE(self):
        if not (u := self.require_user()):
            return
        tid = self.path.rsplit('/', 1)[-1]
        with LOCK:
            try:
                db_delete_trade(u['email'], tid)
                self.send_json({'trades': db_load_trades(u['email'])})
            except Exception:
                self.send_json({'error': 'Database not reachable. Check DATABASE_URL.'}, 500)

    def write_trade(self, action):
        if not self.path.startswith('/api/trades'):
            self.send_error(404)
            return
        if not (u := self.require_user()):
            return
        try:
            d = clean_trade(self.body())
        except ValueError as e:
            self.send_json({'error': str(e)}, 400)
            return
        with LOCK:
            try:
                if action == 'new':
                    d['id'] = uuid.uuid4().hex
                    db_insert_trade(u['email'], d)
                else:
                    tid = self.path.rsplit('/', 1)[-1]
                    updated = db_update_trade(u['email'], tid, d)
                    if not updated:
                        self.send_json({'error': 'Trade not found.'}, 404)
                        return
                self.send_json({'trades': db_load_trades(u['email'])})
            except Exception:
                self.send_json({'error': 'Database not reachable. Check DATABASE_URL.'}, 500)


def main():
    if not SESSION_SECRET:
        print('WARNING: Set SESSION_SECRET before enabling login.', flush=True)
    try:
        init_db()
    except Exception as e:
        print(f'WARNING: could not initialize Neon database on startup: {e}', flush=True)
    print(f'Ledger v4 running on port {PORT}', flush=True)
    print(
        'CONFIG CHECK -- APP_URL=%r | GOOGLE_CLIENT_ID: first6=%r last10=%r len=%d | '
        'GOOGLE_CLIENT_SECRET: first6=%r last6=%r len=%d | SESSION_SECRET set: %s | DATABASE_URL set: %s'
        % (
            APP_URL,
            GOOGLE_CLIENT_ID[:6] if GOOGLE_CLIENT_ID else '(empty)',
            GOOGLE_CLIENT_ID[-10:] if GOOGLE_CLIENT_ID else '(empty)',
            len(GOOGLE_CLIENT_ID),
            GOOGLE_CLIENT_SECRET[:6] if GOOGLE_CLIENT_SECRET else '(empty)',
            GOOGLE_CLIENT_SECRET[-6:] if GOOGLE_CLIENT_SECRET else '(empty)',
            len(GOOGLE_CLIENT_SECRET),
            bool(SESSION_SECRET),
            bool(DATABASE_URL),
        ),
        flush=True,
    )
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()


if __name__ == '__main__':
    main()
