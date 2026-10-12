"""Web API tests on synthetic fixtures (no network, no real keys)."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from dealscope.api import server
from dealscope.config import Settings


@pytest.fixture()
def client(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, dealscope_db_path=tmp_path / "api.sqlite3")
    monkeypatch.setattr(server, "_settings", lambda: settings)
    monkeypatch.setattr("dealscope.agent.orchestrator.time.sleep", lambda s: None, raising=False)
    return TestClient(server.app)


def wait_done(client, case_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        view = client.get(f"/api/cases/{case_id}").json()
        if not view["running"] and view["status_label"] != "Not started":
            return view
        time.sleep(0.1)
    raise AssertionError("case did not finish")


def test_status_without_keys(client):
    body = client.get("/api/status").json()
    assert body["live_available"] is False
    assert {p["key"] for p in body["providers"]} == {"crustdata", "llm", "neatlogs", "jobs_pricing"}


def test_synthetic_case_produces_plain_language_view(client):
    scenarios = client.get("/api/scenarios").json()
    a = next(s for s in scenarios if s["id"] == "scenario_a")
    r = client.post(
        "/api/cases",
        json={
            "target_domain": a["target_domain"],
            "competitor_domains": a["competitor_domains"],
            "deal_thesis": a["deal_thesis"],
            "mode": "synthetic",
            "scenario_id": "scenario_a",
        },
    )
    assert r.status_code == 200
    view = wait_done(client, r.json()["case_id"])
    assert view["synthetic"] and view["status_label"] == "Complete"
    assert view["assessment"]["headline"] and view["assessment"]["explainer"]
    assert len(view["signals"]) == 5 and all(s["finding"] for s in view["signals"])
    assert not any("_" in s["finding"] for s in view["signals"]), "raw reason codes leaked into finding text"
    assert view["steps"] and any(s["actor"] in ("Rule-based planner", "AI planner") for s in view["steps"])
    assert view["companies"] and view["jobs"] and view["people"]
    assert view["verification"]["published"] > 0
    assert client.get(f"/api/cases/{view['case_id']}/report.md").status_code == 200
    items = client.get("/api/cases").json()
    assert items[0]["case_id"] == view["case_id"]


def test_failure_then_resume_via_api(client):
    a = next(s for s in client.get("/api/scenarios").json() if s["id"] == "scenario_b")
    r = client.post(
        "/api/cases",
        json={
            "target_domain": a["target_domain"],
            "competitor_domains": a["competitor_domains"],
            "deal_thesis": a["deal_thesis"],
            "mode": "synthetic",
            "scenario_id": "scenario_b",
            "fault_id": "retry_exhausted",
        },
    )
    cid = r.json()["case_id"]
    view = wait_done(client, cid)
    assert view["can_resume"] and view["status_label"].startswith("Partial")
    assert any(s["kind"] == "retry" for s in view["steps"])
    assert client.post(f"/api/cases/{cid}/resume").status_code == 200
    time.sleep(0.2)
    view = wait_done(client, cid)
    assert view["status_label"] == "Complete"
    assert any(s["kind"] == "resume" for s in view["steps"])


def test_validation_errors_are_readable(client):
    r = client.post(
        "/api/cases",
        json={
            "target_domain": "localhost",
            "competitor_domains": ["a.example", "b.example"],
            "deal_thesis": "Expand the platform",
            "mode": "synthetic",
        },
    )
    assert r.status_code == 422 and "local" in r.json()["detail"]


def test_live_requires_key(client):
    r = client.post(
        "/api/cases",
        json={
            "target_domain": "acme.example",
            "competitor_domains": ["a.example", "b.example"],
            "deal_thesis": "Expand the platform",
            "mode": "live",
        },
    )
    assert r.status_code == 400
    assert client.post("/api/identity-check", json={"domains": ["acme.example"]}).status_code == 400


def test_evidence_route_blocks_traversal(client):
    r = client.get("/api/evidence/..%2F..%2F.env")
    assert r.status_code == 404 and "CRUSTDATA" not in r.text
    assert client.get("/api/does-not-exist").status_code == 404
    assert client.get("/api/evidence/cfo-ai/assumptions.md").status_code == 404  # only images/pdf served
