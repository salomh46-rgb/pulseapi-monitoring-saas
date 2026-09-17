import pytest
import os
import sqlite3
from fastapi.testclient import TestClient
from server.main import app, DB_FILE, init_db
from server.self_heal.analyzer import heuristic_analysis

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_clean_db():
    init_db()
    yield

def test_heuristic_analyzer_keyerror():
    sample_trace = """Traceback (most recent call last):
  File "server/services/checkout.py", line 48, in process_payment
    order_id = payload['order_id']
KeyError: 'order_id'
"""
    res = heuristic_analysis(sample_trace)
    assert "order_id" in res["root_cause"]
    assert res["target_file"] == "server/services/checkout.py"
    assert res["faulty_line"] == 48
    assert "diff --git" not in res["suggested_patch"] or "--- a/" in res["suggested_patch"]
    assert res["confidence"] > 0.8

def test_trigger_simulated_500():
    res = client.post("/api/simulation/trigger-500")
    assert res.status_code == 200
    data = res.json()
    assert data["self_healing"] == "TRIGGERED"
    assert "incident_id" in data
    inc_id = data["incident_id"]

    # Trigger manual process to resolve synchronously in test
    heal_res = client.post(f"/api/incidents/{inc_id}/self-heal")
    assert heal_res.status_code == 200
    inc_data = heal_res.json()
    assert inc_data["status"] in ("PR_OPENED", "SIMULATED_PR")
    assert "order_id" in inc_data["root_cause"]
    assert inc_data["target_file"] == "server/services/checkout.py"
    assert inc_data["pr_url"] is not None

def test_report_external_incident():
    payload = {
        "service_name": "Auth Microservice",
        "error_message": "User session token invalid",
        "stack_trace": """Traceback (most recent call last):
  File "auth/jwt.py", line 95, in verify_token
    user = db.get_user(token['sub'])
TypeError: 'NoneType' object is not subscriptable
""",
        "github_repo": "salomh46-rgb/auth-service"
    }
    res = client.post("/api/incidents/report", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "PROCESSING_SELF_HEAL"
    assert data["service"] == "Auth Microservice"

def test_get_incidents_list():
    res = client.get("/api/incidents")
    assert res.status_code == 200
    incidents = res.json()
    assert isinstance(incidents, list)
