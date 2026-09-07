#!/usr/bin/env python3
"""Ledger v4 — a single-file, per-user trading journal for Render.

Google sign-in is optional locally but required for trade storage. Set these
Render environment variables before deploying: GOOGLE_CLIENT_ID,
GOOGLE_CLIENT_SECRET, APP_URL, and DATABASE_URL.
In Google Cloud, add APP_URL + /auth/google/callback as an authorised redirect URI.
"""
import base64, hashlib, hmac, json, os, secrets, time, urllib.parse, urllib.request, uuid
from datetime import datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import RLock

# Try importing the PostgreSQL adapter; if missing, fallback to local directory mode
try:
    import psycopg2
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

PORT = int(os.environ.get("PORT", "8000"))
APP_URL = os.environ.get("APP_URL", "").rstrip("/")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
if not SESSION_SECRET:
    SESSION_SECRET = secrets.token_hex(32)

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
LOCK = RLock()
MAX_BODY = 1_600_000

# Entire UI HTML/CSS/JS compressed into an un-breakable text block
