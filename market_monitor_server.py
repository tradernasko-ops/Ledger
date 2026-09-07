#!/usr/bin/env python3
"""Ledger v3 — a single-file, per-user trading journal for Render.

Google sign-in is optional locally but required for trade storage. Set these
Render environment variables before deploying: GOOGLE_CLIENT_ID,
GOOGLE_CLIENT_SECRET, APP_URL, and DATA_DIR (persistent disk mount path).
In Google Cloud, add APP_URL + /auth/google/callback as an authorised redirect URI.
"""
import base64, hashlib, hmac, json, os, secrets, time, urllib.parse, urllib.request, uuid
from datetime import datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock

PORT = int(os.environ.get("PORT", "8000"))
APP_URL = os.environ.get("APP_URL", "").rstrip("/")
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
USERS_DIR = DATA_DIR / "users"
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
LOCK = RLock()
MAX_BODY = 1_600_000

PAGE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Ledger</title>
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
</style></head><body><header><div class="brand">Ledger <i>v4</i></div><nav><button class="active" onclick="show('dashboard')">Dashboard</button><button onclick="show('journal')">Journal</button><button onclick="show('settings')">Settings</button></nav></header><main class="wrap">
<section class="page active" id="dashboard"><div class="hero"><div><h1>Your trading dashboard</h1><p class="muted" id="dashSub">Sign in to see your personal journal.</p></div><button class="primary" onclick="openTrade()">+ Log trade</button></div><div class="grid"><div class="card"><div class="label">Net P&amp;L</div><div id="net" class="value">—</div></div><div class="card"><div class="label">Trades</div><div id="count" class="value">—</div></div><div class="card"><div class="label">Win rate</div><div id="winrate" class="value">—</div></div><div class="card"><div class="label">Profit factor</div><div id="factor" class="value">—</div></div></div><div class="card section"><div class="label">Equity curve</div><div class="chart" id="chart"></div></div><div class="card section"><div class="label">Recent trades</div><div id="recent"></div></div></section>
<section class="page" id="journal"><div class="hero"><div><h1>Trade journal</h1><p class="muted">Search and review your saved trades.</p></div><button class="primary" onclick="openTrade()">+ Log trade</button></div><div class="toolbar"><input id="search" placeholder="Search symbol" oninput="render()"><select id="result" onchange="render()"><option value="">All results</option><option value="win">Winners</option><option value="loss">Losers</option></select><button onclick="downloadCsv()">Export CSV</button></div><div class="card trades"><div id="journalList"></div></div></section>
<section class="page" id="settings"><div class="settings"><div class="hero"><div><h1>Settings</h1><p class="muted">Your journal is private to your signed-in account.</p></div></div><div class="card"><div class="label">Account</div><div id="account" class="notice">Checking sign-in…</div></div><div class="card section"><div class="label">Storage</div><p class="muted">Trades are stored separately for each Google account in your Render persistent disk.</p><p class="muted">To keep them through deploys, attach a Render Persistent Disk and set <code>DATA_DIR</code> to its mount path.</p></div><div class="card section"><div class="label">Google login setup</div><p class="muted">Set <code>GOOGLE_CLIENT_ID</code>, <code>GOOGLE_CLIENT_SECRET</code>, <code>SESSION_SECRET</code>, and <code>APP_URL</code> in Render. In Google Cloud Console, add <code id="redirect"></code> as an authorized redirect URI.</p></div></div></section>
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
(async()=>{try{let d=await api('/api/me');me=d.user;if(me)trades=(await api('/api/trades')).trades}catch(e){}render()})();
</script></body></html>'''

def ensure_dirs(): USERS_DIR.mkdir(parents=True, exist_ok=True)
def cookie_value(headers, name):
    c = SimpleCookie(); c.load(headers.get('Cookie', '')); return c[name].value if name in c else None
def session_for(handler):
    raw = cookie_value(handler.headers, 'ledger_session')
    if not raw or '.' not in raw or not SESSION_SECRET: return None
    payload, sig = raw.rsplit('.', 1); expected = hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected): return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
        return data if data.get('exp', 0) > time.time() else None
    except Exception: return None
def signed_session(user):
    data = {'email': user['email'], 'name': user['name'], 'exp': time.time()+60*60*24*14}
    payload = base64.urlsafe_b64encode(json.dumps(data,separators=(',',':')).encode()).decode().rstrip('=')
    return payload + '.' + hmac.new(SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()
def user_file(user): return USERS_DIR / (hashlib.sha256(user['email'].lower().encode()).hexdigest()+'.json')
def load_trades(user):
    try:
        with user_file(user).open(encoding='utf8') as f: return json.load(f)
    except (OSError, json.JSONDecodeError): return []
def save_trades(user, trades):
    ensure_dirs(); target=user_file(user); temp=target.with_suffix('.tmp')
    with temp.open('w',encoding='utf8') as f: json.dump(trades,f,ensure_ascii=False,separators=(',',':'))
    os.replace(temp,target)
def clean_trade(d):
    try: pnl=round(float(d.get('pnl',0)),2)
    except (ValueError,TypeError): raise ValueError('P&L must be a number.')
    symbol=str(d.get('symbol','')).strip().upper()[:16]
    if not symbol: raise ValueError('Symbol is required.')
    return {'date':str(d.get('date',''))[:10], 'type':str(d.get('type','stock'))[:15], 'symbol':symbol,'pnl':pnl,'setup':str(d.get('setup','')).strip()[:80],'side':str(d.get('side','Long'))[:10],'entry':str(d.get('entry','')).strip()[:30],'exit':str(d.get('exit','')).strip()[:30],'rr':str(d.get('rr','')).strip()[:20],'notes':str(d.get('notes','')).strip()[:2000]}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send_json(self, obj, status=200, cookie=None):
        b=json.dumps(obj).encode(); self.send_response(status); self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.security(cookie);self.end_headers();self.wfile.write(b)
    def send_html(self):
        b=PAGE.encode();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(b)));self.security();self.end_headers();self.wfile.write(b)
    def security(self,cookie=None):
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');self.send_header('Referrer-Policy','strict-origin-when-cross-origin');self.send_header('Cache-Control','no-store')
        if cookie:self.send_header('Set-Cookie',cookie)
    def redirect(self,url,cookie=None): self.send_response(302);self.send_header('Location',url);self.security(cookie);self.end_headers()
    def body(self):
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n>MAX_BODY: raise ValueError('Request too large.')
            return json.loads(self.rfile.read(n or 2).decode())
        except Exception as e: raise ValueError('Invalid request data.') from e
    def require_user(self):
        u=session_for(self)
        if not u: self.send_json({'error':'Sign in with Google first.'},401); return None
        return u
    def do_GET(self):
        path=urllib.parse.urlparse(self.path).path
        if path=='/': return self.send_html()
        if path=='/api/me':
            u=session_for(self); return self.send_json({'user': {'email':u['email'],'name':u['name']} if u else None})
        if path=='/api/trades':
            if (u:=self.require_user()):
                with LOCK: self.send_json({'trades':load_trades(u)})
            return
        if path=='/auth/google':
            if not (APP_URL and GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and SESSION_SECRET): return self.redirect('/?auth=configuration-needed')
            state=secrets.token_urlsafe(24); q=urllib.parse.urlencode({'client_id':GOOGLE_CLIENT_ID,'redirect_uri':APP_URL+'/auth/google/callback','response_type':'code','scope':'openid email profile','state':state,'prompt':'select_account'})
            return self.redirect('https://accounts.google.com/o/oauth2/v2/auth?'+q, f'google_state={state}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=600')
        if path=='/auth/google/callback':
            q=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query); state=q.get('state',[''])[0]
            if not state or state!=cookie_value(self.headers,'google_state') or not q.get('code'): return self.redirect('/?auth=failed')
            try:
                data=urllib.parse.urlencode({'code':q['code'][0],'client_id':GOOGLE_CLIENT_ID,'client_secret':GOOGLE_CLIENT_SECRET,'redirect_uri':APP_URL+'/auth/google/callback','grant_type':'authorization_code'}).encode()
                token=json.loads(urllib.request.urlopen(urllib.request.Request('https://oauth2.googleapis.com/token',data=data,headers={'Content-Type':'application/x-www-form-urlencoded'}),timeout=10).read())
                info=json.loads(urllib.request.urlopen(urllib.request.Request('https://openidconnect.googleapis.com/v1/userinfo',headers={'Authorization':'Bearer '+token['access_token']}),timeout=10).read())
                if not info.get('email_verified'): raise ValueError('Google email not verified')
                u={'email':info['email'],'name':info.get('name') or info['email'].split('@')[0]}; return self.redirect('/',f'ledger_session={signed_session(u)}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=1209600')
            except Exception: return self.redirect('/?auth=failed')
        if path=='/auth/logout': return self.redirect('/', 'ledger_session=; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=0')
        self.send_error(404)
    def do_POST(self): self.write_trade('new')
    def do_PUT(self): self.write_trade('edit')
    def do_DELETE(self):
        if not (u:=self.require_user()): return
        tid=self.path.rsplit('/',1)[-1]
        with LOCK:
            t=[x for x in load_trades(u) if x.get('id')!=tid];save_trades(u,t);self.send_json({'trades':t})
    def write_trade(self,action):
        if not self.path.startswith('/api/trades'): self.send_error(404);return
        if not (u:=self.require_user()): return
        try: d=clean_trade(self.body())
        except ValueError as e: self.send_json({'error':str(e)},400);return
        with LOCK:
            trades=load_trades(u)
            if action=='new': d['id']=uuid.uuid4().hex;trades.insert(0,d)
            else:
                tid=self.path.rsplit('/',1)[-1];d['id']=tid
                if not any(x.get('id')==tid for x in trades): self.send_json({'error':'Trade not found.'},404);return
                trades=[d if x.get('id')==tid else x for x in trades]
            save_trades(u,trades);self.send_json({'trades':trades})
def main():
    if not SESSION_SECRET: print('WARNING: Set SESSION_SECRET before enabling login.')
    ensure_dirs(); print(f'Ledger v3 running on port {PORT}'); ThreadingHTTPServer(('0.0.0.0',PORT),Handler).serve_forever()
if __name__=='__main__': main()
