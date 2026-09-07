#!/usr/bin/env python3
"""Ledger v4 — a single-file, per-user trading journal for Render.

Google sign-in is optional locally but required for trade storage. Set these
Render environment variables before deploying: GOOGLE_CLIENT_ID,
GOOGLE_CLIENT_SECRET, APP_URL, and DATABASE_URL (Neon PostgreSQL string).
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
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
LOCK = RLock()
MAX_BODY = 1_600_000

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
.section{margin-top:19px}.chart{padding-top:8px}.trade{border-color:var(--stroke)}
</style></head><body>
<header><div class="brand">Ledger <i>v4</i></div><nav><button id="nav-dashboard" class="active">Dashboard</button><button id="nav-journal">Journal</button><button id="nav-settings">Settings</button></nav></header>
<main class="wrap">
<section id="page-dashboard" class="page active"><div class="hero"><div><h1>Performance Workspace</h1><p class="muted">Live monitoring metrics and equity summaries</p></div><button class="primary" id="add-trade-btn">+ Record Trade</button></div><div class="grid"><div class="card"><div class="label">Net Profit</div><div class="value pos" id="stat-profit">$0.00</div></div><div class="card"><div class="label">Win Rate</div><div class="value" id="stat-winrate">0%</div></div><div class="card"><div class="label">Profit Factor</div><div class="value muted" id="stat-factor">0.00</div></div><div class="card"><div class="label">Total Trades</div><div class="value" id="stat-count">0</div></div></div><div class="section card"><div class="label">Equity Curve Graph</div><div class="chart" id="equity-chart"></div></div></section>
<section id="page-journal" class="page"><div class="hero"><div><h1>Trading Journal</h1><p class="muted">Historical audit trail of all manual positions</p></div></div><div class="card trades" id="journal-list"><div class="empty">No closed trades recorded yet.</div></div></section>
