import pytest
import os
import sqlite3
from fastapi.testclient import TestClient
from server.main import app, DB_FILE, init_db

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_clean_db():
    init_db()
    yield

def test_root_endpoint():
    res = client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["service"] == "PulseAPI SaaS Monitoring Engine"
    assert data["status"] == "OPERATIONAL"

def test_create_and_fetch_monitor():
    payload = {
        "name": "Google DNS",
        "url": "https://8.8.8.8",
        "method": "GET",
        "interval_sec": 30,
        "telegram_chat_id": "12345678"
    }
    create_res = client.post("/api/monitors", json=payload)
    assert create_res.status_code == 200
    mon_id = create_res.json()["id"]

    list_res = client.get("/api/monitors")
    assert list_res.status_code == 200
    monitors = list_res.json()
    assert any(m["id"] == mon_id for m in monitors)

def test_public_status_page():
    res = client.get("/api/status-page")
    assert res.status_code == 200
    data = res.json()
    assert "system_status" in data
    assert "monitors" in data
