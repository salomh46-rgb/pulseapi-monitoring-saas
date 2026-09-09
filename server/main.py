import asyncio
import time
import os
import sqlite3
import httpx
import re
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl

from server.self_heal.analyzer import analyze_incident
from server.self_heal.github_pr import create_self_healing_pr

app = FastAPI(
    title="PulseFix — Self-Healing API Monitoring SaaS",
    version="2.0.0",
    description="Autonomous API & Server Monitoring Engine that Diagnoses 500s from Git Diffs and Creates Pull Requests"
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
            github_repo TEXT,
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
            stack_trace TEXT,
            root_cause TEXT,
            target_file TEXT,
            fix_diff TEXT,
            pr_url TEXT,
            confidence REAL,
            status TEXT DEFAULT 'TRIGGERED',
            started_at TEXT,
            resolved_at TEXT,
            FOREIGN KEY (monitor_id) REFERENCES monitors(id) ON DELETE CASCADE
        )
    """)
    
    # Check and add any missing columns safely
    cur.execute("PRAGMA table_info(monitors)")
    mon_cols = [r[1] for r in cur.fetchall()]
    if "github_repo" not in mon_cols:
        cur.execute("ALTER TABLE monitors ADD COLUMN github_repo TEXT")

    cur.execute("PRAGMA table_info(incidents)")
    inc_cols = [r[1] for r in cur.fetchall()]
    for col, ctype in [
        ("stack_trace", "TEXT"),
        ("root_cause", "TEXT"),
        ("target_file", "TEXT"),
        ("fix_diff", "TEXT"),
        ("pr_url", "TEXT"),
        ("confidence", "REAL"),
        ("status", "TEXT DEFAULT 'TRIGGERED'")
    ]:
        if col not in inc_cols:
            cur.execute(f"ALTER TABLE incidents ADD COLUMN {col} {ctype}")

    conn.commit()
    conn.close()

init_db()

class MonitorCreate(BaseModel):
    name: str
    url: str
    method: str = "GET"
    interval_sec: int = 30
    telegram_chat_id: Optional[str] = None
    github_repo: Optional[str] = "salomh46-rgb/pulseapi-demo"

class IncidentReport(BaseModel):
    service_name: str
    error_message: str
    stack_trace: str
    github_repo: Optional[str] = "salomh46-rgb/pulseapi-demo"
    recent_diff: Optional[str] = None
    telegram_chat_id: Optional[str] = None

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

# Autonomous Self-Healing Pipeline
async def process_self_healing(incident_id: int):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT i.*, m.name as service_name, m.github_repo, m.telegram_chat_id
        FROM incidents i
        LEFT JOIN monitors m ON i.monitor_id = m.id
        WHERE i.id = ?
    """, (incident_id,))
    inc = cur.fetchone()
    if not inc:
        conn.close()
        return

    stack_trace = inc["stack_trace"] or inc["cause"] or "HTTP 500 Internal Server Error"
    service_name = inc["service_name"] or "Core API"
    repo = inc["github_repo"] or "salomh46-rgb/pulseapi-demo"
    chat_id = inc["telegram_chat_id"]

    # 1. AI Root Cause Analysis
    cur.execute("UPDATE incidents SET status = 'ANALYZING' WHERE id = ?", (incident_id,))
    conn.commit()

    analysis = await analyze_incident(
        error_payload=stack_trace,
        service_name=service_name
    )

    root_cause = analysis.get("root_cause", "Uncaught exception in controller.")
    target_file = analysis.get("target_file", "server/app.py")
    patch = analysis.get("suggested_patch", "")
    confidence = analysis.get("confidence", 0.9)

    # 2. Open GitHub Self-Healing Pull Request
    pr_result = await create_self_healing_pr(
        repo=repo,
        incident_id=incident_id,
        patch_diff=patch,
        root_cause=root_cause,
        target_file=target_file
    )

    pr_url = pr_result.get("pr_url", "")
    pr_status = pr_result.get("status", "PR_OPENED")

    cur.execute("""
        UPDATE incidents 
        SET root_cause = ?, target_file = ?, fix_diff = ?, pr_url = ?, confidence = ?, status = ?
        WHERE id = ?
    """, (root_cause, target_file, patch, pr_url, confidence, pr_status, incident_id))
    conn.commit()
    conn.close()

    # 3. Rich Telegram Alert Dispatch
    if chat_id:
        tg_msg = f"""🚨 <b>PulseFix Incident #{incident_id} Diagnosed!</b>

• <b>Service:</b> {service_name}
• <b>Status:</b> DOWN (Self-Healing Active)

🧠 <b>Root Cause Analysis:</b>
{root_cause}

📁 <b>Target File:</b> <code>{target_file}</code> (Confidence: {int(confidence * 100)}%)

🛠️ <b>Autonomous GitHub Fix:</b>
<a href="{pr_url}">🚀 View & Merge Pull Request</a>"""
        asyncio.create_task(send_telegram_alert(chat_id, tg_msg))

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
    resp_text = ""
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            res = await client.request(method, url)
            status_code = res.status_code
            latency = (time.perf_counter() - start) * 1000
            if status_code >= 400:
                is_up = 0
                resp_text = res.text[:500]
    except Exception as e:
        latency = (time.perf_counter() - start) * 1000
        is_up = 0
        status_code = 500
        resp_text = str(e)

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
    uptime = round((sum(r[0] for r in recent_logs) / len(recent_logs)) * 100, 2) if recent_logs else 100.0

    incident_id_to_heal = None

    # Incident state transitions
    if prev_status == "UP" and new_status == "DOWN":
        error_msg = f"HTTP {status_code} ({resp_text or 'Connection Error'})"
        cur.execute("""
            INSERT INTO incidents (monitor_id, cause, stack_trace, started_at, status) 
            VALUES (?, ?, ?, ?, 'TRIGGERED')
        """, (monitor_id, error_msg, resp_text or error_msg, now_iso))
        incident_id_to_heal = cur.lastrowid

    elif prev_status == "DOWN" and new_status == "UP":
        cur.execute("UPDATE incidents SET resolved_at = ?, status = 'RESOLVED' WHERE monitor_id = ? AND resolved_at IS NULL",
                    (now_iso, monitor_id))
        if chat_id:
            msg = f"✅ <b>PulseFix: Service Restored!</b>\n\n• <b>Service:</b> {mon['name']}\n• <b>URL:</b> {url}\n• <b>Status:</b> UP ({round(latency, 1)}ms)\n• <b>Time:</b> {now_iso}"
            asyncio.create_task(send_telegram_alert(chat_id, msg))

    cur.execute("""
        UPDATE monitors 
        SET status = ?, last_latency_ms = ?, uptime_pct = ?, last_checked = ?
        WHERE id = ?
    """, (new_status, round(latency, 2), uptime, now_iso, monitor_id))

    conn.commit()
    conn.close()

    if incident_id_to_heal:
        asyncio.create_task(process_self_healing(incident_id_to_heal))

# Web & API Endpoints
@app.get("/")
def root(request: Request):
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        base_dir = os.path.dirname(os.path.dirname(__file__))
        client_html = os.path.join(base_dir, "client", "index.html")
        if os.path.exists(client_html):
            return FileResponse(client_html, media_type="text/html")
        root_html = os.path.join(base_dir, "index.html")
        if os.path.exists(root_html):
            return FileResponse(root_html, media_type="text/html")

    return {
        "service": "PulseFix Self-Healing SaaS Engine",
        "status": "OPERATIONAL",
        "version": "2.0.0",
        "ai_sre": "ACTIVE",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/dashboard", response_class=FileResponse)
def dashboard():
    base_dir = os.path.dirname(os.path.dirname(__file__))
    client_html = os.path.join(base_dir, "client", "index.html")
    if os.path.exists(client_html):
        return FileResponse(client_html, media_type="text/html")
    return FileResponse(os.path.join(base_dir, "index.html"), media_type="text/html")

@app.get("/api/health")
def api_health():
    return {
        "service": "PulseFix Self-Healing SaaS Engine",
        "status": "OPERATIONAL",
        "version": "2.0.0",
        "ai_sre": "ACTIVE",
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
        INSERT INTO monitors (name, url, method, interval_sec, telegram_chat_id, github_repo, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (mon.name, mon.url, mon.method, mon.interval_sec, mon.telegram_chat_id, mon.github_repo, now_iso))
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

@app.get("/api/incidents")
def get_incidents():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("""
        SELECT i.*, m.name as monitor_name, m.url as monitor_url
        FROM incidents i
        LEFT JOIN monitors m ON i.monitor_id = m.id
        ORDER BY i.id DESC LIMIT 20
    """)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

@app.post("/api/incidents/report")
async def report_incident(report: IncidentReport, bg: BackgroundTasks):
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    cur.execute("""
        INSERT INTO incidents (cause, stack_trace, started_at, status)
        VALUES (?, ?, ?, 'TRIGGERED')
    """, (f"Crash: {report.error_message}", report.stack_trace, now_iso))
    inc_id = cur.lastrowid
    conn.commit()
    conn.close()

    bg.add_task(process_self_healing, inc_id)
    return {
        "incident_id": inc_id,
        "status": "PROCESSING_SELF_HEAL",
        "service": report.service_name
    }

@app.post("/api/incidents/{incident_id}/self-heal")
async def trigger_manual_self_heal(incident_id: int):
    await process_self_healing(incident_id)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,))
    row = dict(cur.fetchone())
    conn.close()
    return row

@app.post("/api/simulation/trigger-500")
async def simulate_500_incident(bg: BackgroundTasks):
    simulated_trace = """Traceback (most recent call last):
  File "server/services/checkout.py", line 48, in process_payment
    order_id = payload['order_id']
KeyError: 'order_id'
"""
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    cur.execute("""
        INSERT INTO incidents (cause, stack_trace, started_at, status)
        VALUES (?, ?, ?, 'TRIGGERED')
    """, ("HTTP 500: KeyError 'order_id' in Checkout API", simulated_trace, now_iso))
    inc_id = cur.lastrowid
    conn.commit()
    conn.close()

    bg.add_task(process_self_healing, inc_id)
    return {
        "message": "Simulated 500 Incident Injected!",
        "incident_id": inc_id,
        "error": "KeyError: 'order_id' in server/services/checkout.py:L48",
        "self_healing": "TRIGGERED"
    }

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
    if any(m["status"] == "DOWN" for m in monitors) or len(active_incidents) > 0:
        overall = "DEGRADED_PERFORMANCE"

    return {
        "system_status": overall,
        "monitors": monitors,
        "active_incidents_count": len(active_incidents),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
