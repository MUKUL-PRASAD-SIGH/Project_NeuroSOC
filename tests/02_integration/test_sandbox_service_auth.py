from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import load_service_main

sandbox_main = load_service_main("sandbox-service", "neurosoc_sandbox_main_for_tests")
client = TestClient(sandbox_main.app)


@pytest.fixture(autouse=True)
def _reset_service_token(monkeypatch):
    monkeypatch.setattr(sandbox_main, "SANDBOX_SERVICE_TOKEN", "")
    monkeypatch.setattr(sandbox_main, "APP_ENV", "local")


def test_local_sandbox_startup_allows_unconfigured_service_token():
    sandbox_main._validate_startup_configuration()


@pytest.mark.parametrize("token", ["", "too-short"])
def test_production_sandbox_startup_requires_a_strong_service_token(monkeypatch, token):
    monkeypatch.setattr(sandbox_main, "APP_ENV", "production")
    monkeypatch.setattr(sandbox_main, "SANDBOX_SERVICE_TOKEN", token)

    with pytest.raises(RuntimeError, match="SANDBOX_SERVICE_TOKEN"):
        sandbox_main._validate_startup_configuration()


def test_production_sandbox_startup_accepts_a_32_character_token(monkeypatch):
    monkeypatch.setattr(sandbox_main, "APP_ENV", "production")
    monkeypatch.setattr(sandbox_main, "SANDBOX_SERVICE_TOKEN", "s" * 32)

    sandbox_main._validate_startup_configuration()


def test_shared_sandbox_database_requires_verified_tls(monkeypatch):
    monkeypatch.setattr(sandbox_main, "APP_ENV", "production")
    repository = sandbox_main.SandboxRepository(
        "postgresql://sandbox:secret@db.example.com:5432/neurosoc"
    )

    with pytest.raises(RuntimeError, match="sslmode=verify-full"):
        repository._connect()


def test_production_sessions_fail_closed_without_service_token(monkeypatch):
    monkeypatch.setattr(sandbox_main, "APP_ENV", "production")
    monkeypatch.setattr(sandbox_main, "SANDBOX_SERVICE_TOKEN", "")

    response = client.post("/sessions", json={"user_id": "attacker"})

    assert response.status_code == 503


def test_sessions_route_is_open_when_no_service_token_is_configured(monkeypatch):
    monkeypatch.setattr(
        sandbox_main.manager, "create_session", lambda payload: {"session_id": "s1", "sandbox_token": "sbx-1"}
    )
    response = client.post("/sessions", json={"user_id": "attacker"})
    assert response.status_code == 200


def test_sessions_route_rejects_missing_token_when_configured(monkeypatch):
    monkeypatch.setattr(sandbox_main, "SANDBOX_SERVICE_TOKEN", "shared-secret")
    response = client.post("/sessions", json={"user_id": "attacker"})
    assert response.status_code == 401


def test_sessions_route_rejects_wrong_token_when_configured(monkeypatch):
    monkeypatch.setattr(sandbox_main, "SANDBOX_SERVICE_TOKEN", "shared-secret")
    response = client.post(
        "/sessions", json={"user_id": "attacker"}, headers={"X-Service-Token": "wrong"}
    )
    assert response.status_code == 401


def test_sessions_route_accepts_correct_token_when_configured(monkeypatch):
    monkeypatch.setattr(sandbox_main, "SANDBOX_SERVICE_TOKEN", "shared-secret")
    monkeypatch.setattr(
        sandbox_main.manager, "create_session", lambda payload: {"session_id": "s1", "sandbox_token": "sbx-1"}
    )
    response = client.post(
        "/sessions", json={"user_id": "attacker"}, headers={"X-Service-Token": "shared-secret"}
    )
    assert response.status_code == 200


def test_health_and_metrics_remain_exempt_even_when_token_is_configured(monkeypatch):
    monkeypatch.setattr(sandbox_main, "SANDBOX_SERVICE_TOKEN", "shared-secret")
    assert client.get("/health").status_code == 200
    assert client.get("/metrics").status_code == 200


def test_attacker_facing_routes_still_require_a_sandbox_token_not_a_service_token(monkeypatch):
    monkeypatch.setattr(sandbox_main, "SANDBOX_SERVICE_TOKEN", "shared-secret")
    # An attacker-facing route (not under /sessions) must still demand the per-session
    # sandbox token, and a valid service token must not substitute for it.
    response = client.get("/dashboard", headers={"X-Service-Token": "shared-secret"})
    assert response.status_code == 401
