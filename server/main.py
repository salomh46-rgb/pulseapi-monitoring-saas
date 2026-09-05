import asyncio
import time
import os
import sqlite3
import httpx
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl

app = FastAPI(
    title="PulseAPI Monitoring SaaS Engine",
    version="1.0.0",
    description="High-frequency API/Server Uptime and Latency Monitoring with Telegram Alerts"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_FILE = os.path.join(os.path.dirname(__file__), "pulseapi.db")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS monitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            method TEXT DEFAULT 'GET',
            interval_sec INTEGER DEFAULT 30,
            status TEXT DEFAULT 'UP',
            last_latency_ms REAL DEFAULT 0,
            uptime_pct REAL DEFAULT 100.0,
            last_checked TEXT,
            telegram_chat_id TEXT,
            created_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ping_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            monitor_id INTEGER,
            status_code INTEGER,
            latency_ms REAL,
            is_up INTEGER,
            timestamp TEXT,
            FOREIGN KEY (monitor_id) REFERENCES monitors(id) ON DELETE CASCADE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            monitor_id INTEGER,
            cause TEXT,
            started_at TEXT,
            resolved_at TEXT,
            FOREIGN KEY (monitor_id) REFERENCES monitors(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()

init_db()

class MonitorCreate(BaseModel):
    name: str
    url: str
    method: str = "GET"
    interval_sec: int = 30
    telegram_chat_id: Optional[str] = None

class MonitorResponse(BaseModel):
    id: int
    name: str
    url: str
    method: str
    interval_sec: int
    status: str
    last_latency_ms: float
    uptime_pct: float
    last_checked: Optional[str]
    telegram_chat_id: Optional[str]

# Telegram Alert Service
async def send_telegram_alert(chat_id: str, message: str):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not bot_token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"})
    except Exception as e:
        print(f"Telegram alert error: {e}")

# Async ping single monitor
async def check_monitor(monitor_id: int):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM monitors WHERE id = ?", (monitor_id,))
    mon = cur.fetchone()
    if not mon:
        conn.close()
        return

    url = mon["url"]
    method = mon["method"]
    chat_id = mon["telegram_chat_id"]
    prev_status = mon["status"]

    start = time.perf_counter()
    is_up = 1
    status_code = 0
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            res = await client.request(method, url)
            status_code = res.status_code
            latency = (time.perf_counter() - start) * 1000
            if status_code >= 400:
                is_up = 0
    except Exception as e:
        latency = (time.perf_counter() - start) * 1000
        is_up = 0
        status_code = 500

    now_iso = datetime.now(timezone.utc).isoformat()
    new_status = "UP" if is_up else "DOWN"

    # Insert log
    cur.execute(
        "INSERT INTO ping_logs (monitor_id, status_code, latency_ms, is_up, timestamp) VALUES (?, ?, ?, ?, ?)",
        (monitor_id, status_code, round(latency, 2), is_up, now_iso)
    )

    # Compute uptime percentage over last 50 pings
    cur.execute("SELECT is_up FROM ping_logs WHERE monitor_id = ? ORDER BY id DESC LIMIT 50", (monitor_id,))
    recent_logs = cur.fetchall()
    if recent_logs:
        uptime = round((sum(r[0] for r in recent_logs) / len(recent_logs)) * 100, 2)
    else:
        uptime = 100.0

    # Incident state transitions
    if prev_status == "UP" and new_status == "DOWN":
        cur.execute("INSERT INTO incidents (monitor_id, cause, started_at) VALUES (?, ?, ?)",
                    (monitor_id, f"HTTP {status_code} / Timeout", now_iso))
        if chat_id:
            msg = f"🚨 <b>PulseAPI Alert: Incident Triggered!</b>\n\n• <b>Service:</b> {mon['name']}\n• <b>URL:</b> {url}\n• <b>Status:</b> DOWN (HTTP {status_code})\n• <b>Time:</b> {now_iso}\n\nEngine is actively attempting self-recovery."
            asyncio.create_task(send_telegram_alert(chat_id, msg))

    elif prev_status == "DOWN" and new_status == "UP":
        cur.execute("UPDATE incidents SET resolved_at = ? WHERE monitor_id = ? AND resolved_at IS NULL",
                    (now_iso, monitor_id))
        if chat_id:
            msg = f"✅ <b>PulseAPI Alert: Service Restored!</b>\n\n• <b>Service:</b> {mon['name']}\n• <b>URL:</b> {url}\n• <b>Status:</b> UP ({round(latency, 1)}ms)\n• <b>Time:</b> {now_iso}"
            asyncio.create_task(send_telegram_alert(chat_id, msg))

    cur.execute("""
        UPDATE monitors 
        SET status = ?, last_latency_ms = ?, uptime_pct = ?, last_checked = ?
        WHERE id = ?
    """, (new_status, round(latency, 2), uptime, now_iso, monitor_id))

    conn.commit()
    conn.close()

# API Endpoints
@app.get("/")
def root():
    return {
        "service": "PulseAPI SaaS Monitoring Engine",
        "status": "OPERATIONAL",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/api/monitors", response_model=List[dict])
def get_monitors():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM monitors ORDER BY id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

@app.post("/api/monitors")
async def create_monitor(mon: MonitorCreate, bg: BackgroundTasks):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    cur.execute("""
        INSERT INTO monitors (name, url, method, interval_sec, telegram_chat_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (mon.name, mon.url, mon.method, mon.interval_sec, mon.telegram_chat_id, now_iso))
    mon_id = cur.lastrowid
    conn.commit()
    conn.close()

    bg.add_task(check_monitor, mon_id)
    return {"id": mon_id, "name": mon.name, "url": mon.url, "status": "INITIALIZING"}

@app.delete("/api/monitors/{monitor_id}")
def delete_monitor(monitor_id: int):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("DELETE FROM monitors WHERE id = ?", (monitor_id,))
    cur.execute("DELETE FROM ping_logs WHERE monitor_id = ?", (monitor_id,))
    cur.execute("DELETE FROM incidents WHERE monitor_id = ?", (monitor_id,))
    conn.commit()
    conn.close()
    return {"deleted": monitor_id}

@app.post("/api/monitors/{monitor_id}/ping")
async def ping_now(monitor_id: int):
    await check_monitor(monitor_id)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM monitors WHERE id = ?", (monitor_id,))
    row = dict(cur.fetchone())
    conn.close()
    return row

@app.get("/api/monitors/{monitor_id}/logs")
def get_monitor_logs(monitor_id: int):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM ping_logs WHERE monitor_id = ? ORDER BY id DESC LIMIT 30", (monitor_id,))
    logs = [dict(r) for r in cur.fetchall()]
    conn.close()
    return logs

@app.get("/api/status-page")
def public_status_page():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, name, status, uptime_pct, last_latency_ms FROM monitors")
    monitors = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM incidents WHERE resolved_at IS NULL")
    active_incidents = [dict(r) for r in cur.fetchall()]
    conn.close()

    overall = "ALL_SYSTEMS_OPERATIONAL"
    if any(m["status"] == "DOWN" for m in monitors):
        overall = "DEGRADED_PERFORMANCE"

    return {
        "system_status": overall,
        "monitors": monitors,
        "active_incidents_count": len(active_incidents),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
