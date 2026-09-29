from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "inference-service"))

import main as inference_main
from core.auth import OIDCConfig, OIDCValidationError


@pytest.fixture
def protected_client(monkeypatch):
    monkeypatch.setattr(inference_main, "OIDC_REQUIRED", True)
    monkeypatch.setattr(inference_main, "OIDC_ISSUER", "http://localhost:8081/realms/neurosoc")
    monkeypatch.setattr(inference_main, "ENABLE_SIMULATION_API", True)
    monkeypatch.setattr(inference_main, "API_KEY", "")
    inference_main.rate_limiter.clear()
    audit_events = []
    monkeypatch.setattr(
        inference_main.runtime.repository,
        "record_audit_event",
        lambda event: audit_events.append(event),
    )

    def fake_validate_access_token(token: str, _config: OIDCConfig) -> dict[str, object]:
        if token == "invalid":
            raise OIDCValidationError("Invalid OIDC access token")
        return {"sub": "test-user", "roles": [token]}

    monkeypatch.setattr(inference_main, "validate_access_token", fake_validate_access_token)
    client = TestClient(inference_main.app)
    client.audit_events = audit_events
    return client


@pytest.mark.parametrize("role", ["analyst", "operator", "admin", "auditor"])
def test_read_endpoint_allows_each_read_role(protected_client, role):
    response = protected_client.get("/api/stats", headers={"Authorization": f"Bearer {role}"})

    assert response.status_code == 200


def test_versioned_routes_are_canonical_and_legacy_api_prefix_still_works(protected_client):
    schema = inference_main.app.openapi()
    documented_paths = schema["paths"]

    assert "/api/v1/stats" in documented_paths
    assert "/api/v1/models/reload" in documented_paths
    assert "/api/v1/profiles/{user_id}" in documented_paths
    assert "/api/stats" not in documented_paths
    assert "/models/reload" not in documented_paths
    assert schema["components"]["schemas"]["BankTransferRequest"]["additionalProperties"] is False
    assert schema["components"]["schemas"]["StatsResponse"]["additionalProperties"] is False
    versioned = protected_client.get("/api/v1/stats", headers={"Authorization": "Bearer analyst"})
    legacy = protected_client.get("/api/stats", headers={"Authorization": "Bearer analyst"})

    assert versioned.status_code == 200
    assert legacy.status_code == 200


def test_request_schemas_reject_unknown_fields_and_oversized_event_batches(protected_client):
    invalid_transfer = protected_client.post(
        "/api/v1/bank/transfer",
        json={
            "user_id": "alice",
            "destination": "utility",
            "amount": 25,
            "unexpected": "must be rejected",
        },
        headers={"Authorization": "Bearer operator"},
    )
    string_amount_transfer = protected_client.post(
        "/api/v1/bank/transfer",
        json={"user_id": "alice", "destination": "utility", "amount": "25"},
        headers={"Authorization": "Bearer operator"},
    )
    oversized_events = protected_client.post(
        "/api/v1/behavioral/vectorize",
        json={"events": [{} for _ in range(2001)]},
        headers={"Authorization": "Bearer operator"},
    )

    assert invalid_transfer.status_code == 422
    assert string_amount_transfer.status_code == 422
    assert oversized_events.status_code == 422
    invalid_limit = protected_client.get(
        "/api/v1/verdicts/latest?limit=0",
        headers={"Authorization": "Bearer analyst"},
    )
    assert invalid_limit.status_code == 422


def test_request_body_limit_rejects_oversized_body(protected_client):
    response = protected_client.post(
        "/api/v1/behavioral",
        content=b"x" * (inference_main.MAX_REQUEST_BODY_BYTES + 1),
        headers={
            "Authorization": "Bearer operator",
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body exceeds the configured size limit."}


def test_request_body_limit_rejects_oversized_chunked_body():
    sent = []
    calls = 0

    async def receive():
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"type": "http.request", "body": b"1234", "more_body": True}
        return {"type": "http.request", "body": b"5678", "more_body": False}

    async def send(message):
        sent.append(message)

    async def unreachable_app(_scope, _receive, _send):
        raise AssertionError("Oversized request must not reach the application")

    middleware = inference_main.RequestBodyLimitMiddleware(unreachable_app, max_bytes=6)
    scope = {"type": "http", "method": "POST", "headers": []}

    asyncio.run(middleware(scope, receive, send))

    assert sent[0]["status"] == 413
    assert b"size limit" in sent[1]["body"]


def test_rate_limit_returns_retry_after_header(protected_client, monkeypatch):
    monkeypatch.setattr(inference_main.rate_limiter, "limit", 2)
    headers = {"Authorization": "Bearer analyst"}

    assert protected_client.get("/api/v1/stats", headers=headers).status_code == 200
    assert protected_client.get("/api/v1/stats", headers=headers).status_code == 200
    limited = protected_client.get("/api/v1/stats", headers=headers)

    assert limited.status_code == 429
    assert int(limited.headers["retry-after"]) >= 1
    assert limited.json()["detail"] == "Rate limit exceeded."


def test_cors_preflight_reaches_cors_middleware_without_bearer_token(protected_client):
    response = protected_client.options(
        "/api/v1/stats",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_rejects_unlisted_origins(protected_client):
    response = protected_client.options(
        "/api/v1/stats",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://soc.example.com/path",
        "https://user@soc.example.com",
        "ftp://soc.example.com",
        "https://soc.example.com:invalid",
    ],
)
def test_cors_configuration_accepts_only_explicit_origins(origin):
    with pytest.raises(RuntimeError, match="CORS_ALLOWED_ORIGINS"):
        inference_main._parse_cors_origins(origin)


def test_trusted_proxy_configuration_rejects_wildcards_and_bad_addresses():
    with pytest.raises(RuntimeError, match="wildcards"):
        inference_main._parse_trusted_proxy_ips("*")
    with pytest.raises(RuntimeError, match="valid IP addresses"):
        inference_main._parse_trusted_proxy_ips("not-an-ip")


@pytest.mark.parametrize(
    ("peer", "expected_client"),
    [
        (("172.30.0.10", 80), ("198.51.100.25", 0)),
        (("172.30.0.12", 80), ("172.30.0.12", 80)),
    ],
)
def test_proxy_headers_are_used_only_from_explicitly_trusted_frontends(peer, expected_client):
    captured = []

    async def capture_client(scope, _receive, _send):
        captured.append(scope["client"])

    middleware = ProxyHeadersMiddleware(
        capture_client,
        trusted_hosts=inference_main._parse_trusted_proxy_ips("172.30.0.10,172.30.0.11"),
    )
    scope = {
        "type": "http",
        "scheme": "http",
        "client": peer,
        "headers": [(b"x-forwarded-for", b"198.51.100.25")],
    }

    asyncio.run(middleware(scope, None, None))

    assert captured == [expected_client]


def test_validation_error_does_not_echo_credentials(protected_client):
    response = protected_client.post(
        "/api/v1/bank/login",
        json={"password": "never-echo-this-secret"},
        headers={"Authorization": "Bearer operator"},
    )

    assert response.status_code == 422
    assert "never-echo-this-secret" not in response.text
    assert response.json() == {"detail": "Request validation failed."}


def test_unexpected_error_response_does_not_echo_exception_details():
    request = inference_main.Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/v1/test",
            "raw_path": b"/api/v1/test",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )

    response = asyncio.run(
        inference_main.unexpected_error_handler(request, RuntimeError("sensitive database detail"))
    )

    assert response.status_code == 500
    assert b"sensitive database detail" not in response.body
    assert response.body == b'{"detail":"Internal server error."}'


def test_versioned_http_routes_declare_response_models():
    versioned_routes = [
        route
        for route in inference_main.app.routes
        if getattr(route, "path", "").startswith("/api/v1/") and getattr(route, "methods", None)
    ]

    assert versioned_routes
    assert all(route.response_model is not None for route in versioned_routes)


def test_request_schema_rejects_malformed_feature_sequence(protected_client):
    response = protected_client.post(
        "/api/v1/analyze",
        json={
            "session_id": "session-1",
            "flow_features": [0.0] * 80,
            "session_sequence": [[0.0] * 79],
        },
        headers={"Authorization": "Bearer operator"},
    )

    assert response.status_code == 422


def test_versioned_read_endpoints_return_declared_response_shapes(protected_client):
    headers = {"Authorization": "Bearer analyst"}
    paths = [
        "/api/v1/stats",
        "/api/v1/model/version",
        "/api/v1/alerts",
        "/api/v1/alerts/latest",
        "/api/v1/verdicts/latest",
        "/api/v1/verdicts/current",
    ]

    responses = [protected_client.get(path, headers=headers) for path in paths]

    assert [response.status_code for response in responses] == [200] * len(paths)


def test_transfer_contract_accepts_json_integer_amount(protected_client, monkeypatch):
    monkeypatch.setattr(
        inference_main.portal_state,
        "record_transfer",
        lambda *_args, **_kwargs: SimpleNamespace(session_id="session-1"),
    )
    monkeypatch.setattr(
        inference_main,
        "_run_portal_analysis",
        lambda *_args, **_kwargs: SimpleNamespace(verdict="LEGITIMATE", confidence=0.1),
    )

    response = protected_client.post(
        "/api/v1/bank/transfer",
        json={"user_id": "alice", "destination": "utility", "amount": 25},
        headers={"Authorization": "Bearer operator"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"


def test_protected_endpoint_rejects_missing_or_invalid_bearer_token(protected_client):
    missing = protected_client.get("/api/stats")
    invalid = protected_client.get("/api/stats", headers={"Authorization": "Bearer invalid"})

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert invalid.status_code == 401
    auth_events = [
        event for event in protected_client.audit_events
        if event["event_type"] == "security.authentication"
    ]
    assert [event["outcome"] for event in auth_events] == ["denied", "denied"]
    assert all(event["details"]["reason"] == "token_rejected" for event in auth_events)
    assert all("invalid" not in str(event) for event in auth_events)


def test_unrecognized_role_is_denied_but_known_role_reaches_unknown_route(protected_client):
    denied = protected_client.get("/future/endpoint", headers={"Authorization": "Bearer service"})
    allowed_to_route = protected_client.get("/future/endpoint", headers={"Authorization": "Bearer analyst"})

    assert denied.status_code == 403
    assert allowed_to_route.status_code == 404
    denied_event = next(
        event for event in protected_client.audit_events
        if event["event_type"] == "security.authentication" and event["outcome"] == "denied"
    )
    assert denied_event["actor_id"] == "test-user"
    assert denied_event["actor_roles"] == ["service"]


def test_missing_oidc_issuer_fails_closed(protected_client, monkeypatch):
    monkeypatch.setattr(inference_main, "OIDC_ISSUER", "")

    response = protected_client.get("/api/stats", headers={"Authorization": "Bearer analyst"})

    assert response.status_code == 503


def test_api_docs_are_not_exempt_from_auth_outside_local_mode(protected_client, monkeypatch):
    monkeypatch.setattr(inference_main, "APP_ENV", "production")

    response = protected_client.get("/docs")

    assert response.status_code == 401


def test_simulation_endpoints_are_hidden_by_default(protected_client, monkeypatch):
    monkeypatch.setattr(inference_main, "ENABLE_SIMULATION_API", False)

    legacy_response = protected_client.get(
        "/api/verdicts/current",
        headers={"Authorization": "Bearer analyst"},
    )
    versioned_response = protected_client.get(
        "/api/v1/profiles/pilot-analyst",
        headers={"Authorization": "Bearer analyst"},
    )

    assert legacy_response.status_code == 404
    assert versioned_response.status_code == 404


@pytest.mark.parametrize("role", ["analyst", "operator", "auditor"])
def test_model_reload_denies_non_admin_roles(protected_client, monkeypatch, role):
    monkeypatch.setattr(inference_main.runtime.engine, "check_model_version", lambda: False)

    response = protected_client.post("/models/reload", headers={"Authorization": f"Bearer {role}"})

    assert response.status_code == 403


def test_model_reload_allows_admin(protected_client, monkeypatch):
    monkeypatch.setattr(inference_main.runtime.engine, "check_model_version", lambda: False)

    response = protected_client.post("/api/v1/models/reload", headers={"Authorization": "Bearer admin"})

    assert response.status_code == 200
    assert response.json()["reloaded"] is False
    model_events = [
        event for event in protected_client.audit_events
        if event["event_type"] in {"security.model_reload", "security.model_change"}
    ]
    assert [(event["event_type"], event["outcome"]) for event in model_events] == [
        ("security.model_reload", "attempted"),
        ("security.model_change", "unchanged"),
    ]
    assert model_events[-1]["details"]["previous_version"] == model_events[-1]["details"]["active_version"]


def test_model_reload_requires_oidc_even_when_general_oidc_is_optional(protected_client, monkeypatch):
    monkeypatch.setattr(inference_main, "OIDC_REQUIRED", False)

    def fail_if_called():
        raise AssertionError("Unauthenticated callers must not reach model reload")

    monkeypatch.setattr(inference_main.runtime.engine, "check_model_version", fail_if_called)

    response = protected_client.post("/api/v1/models/reload")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_future_admin_route_requires_oidc_when_general_oidc_is_optional(protected_client, monkeypatch):
    monkeypatch.setattr(inference_main, "OIDC_REQUIRED", False)

    response = protected_client.post("/api/v1/admin/models/promote")

    assert response.status_code == 401


@pytest.mark.parametrize("role", ["analyst", "auditor"])
def test_response_route_denies_read_only_roles(protected_client, monkeypatch, role):
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("The response handler must not run for a read-only role")

    monkeypatch.setattr(inference_main.portal_state, "record_honeypot", fail_if_called)

    response = protected_client.post(
        "/api/bank/honeypot-hit",
        json={"user_id": "test-user"},
        headers={"Authorization": f"Bearer {role}"},
    )

    assert response.status_code == 403


def test_response_route_allows_operator(protected_client, monkeypatch):
    monkeypatch.setattr(
        inference_main.portal_state,
        "record_honeypot",
        lambda *_args, **_kwargs: SimpleNamespace(session_id="session-1"),
    )
    monkeypatch.setattr(
        inference_main,
        "_run_portal_analysis",
        lambda *_args, **_kwargs: SimpleNamespace(verdict="HACKER", confidence=0.95),
    )
    monkeypatch.setattr(inference_main, "_activate_sandbox", lambda *_args, **_kwargs: {"active": True})

    response = protected_client.post(
        "/api/bank/honeypot-hit",
        json={"user_id": "test-user"},
        headers={"Authorization": "Bearer operator"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "captured"


class FakeWebSocket:
    def __init__(self, authorization: str, query_params: dict[str, str] | None = None):
        self.headers = {"authorization": authorization}
        self.query_params = query_params or {}
        self.url = SimpleNamespace(path="/ws/alerts")
        self.state = SimpleNamespace()
        self.closed_with: tuple[int, str] | None = None

    async def close(self, *, code: int, reason: str = "") -> None:
        self.closed_with = (code, reason)


def test_alert_websocket_applies_role_policy(protected_client):
    _ = protected_client  # Apply the fixture's OIDC and token validator settings.
    accepted_identity = FakeWebSocket("Bearer analyst")
    denied_identity = FakeWebSocket("Bearer service")

    assert asyncio.run(inference_main._authorize_websocket(accepted_identity)) is True
    assert accepted_identity.state.identity["roles"] == ["analyst"]
    assert asyncio.run(inference_main._authorize_websocket(denied_identity)) is False
    assert denied_identity.closed_with is not None
    assert denied_identity.closed_with[0] == 4403
    websocket_events = [
        event for event in protected_client.audit_events
        if event["event_type"] == "security.authentication" and event["http_method"] == "WEBSOCKET"
    ]
    assert [event["outcome"] for event in websocket_events] == ["succeeded", "denied"]
    assert websocket_events[-1]["actor_id"] == "test-user"


def test_alert_websocket_accepts_token_via_query_param(protected_client):
    # Browsers cannot set a custom header on a WebSocket handshake; the dashboard passes the
    # token as ?access_token=... instead, and the backend must accept it as a fallback.
    _ = protected_client
    query_param_identity = FakeWebSocket("", query_params={"access_token": "operator"})

    assert asyncio.run(inference_main._authorize_websocket(query_param_identity)) is True
    assert query_param_identity.state.identity["roles"] == ["operator"]


def test_simulated_response_action_is_audited_without_request_body(protected_client, monkeypatch):
    monkeypatch.setattr(
        inference_main.portal_state,
        "record_transfer",
        lambda *_args, **_kwargs: SimpleNamespace(session_id="session-1"),
    )
    monkeypatch.setattr(
        inference_main,
        "_run_portal_analysis",
        lambda *_args, **_kwargs: SimpleNamespace(verdict="LEGITIMATE", confidence=0.1),
    )

    response = protected_client.post(
        "/api/v1/bank/transfer",
        json={"user_id": "alice", "destination": "utility", "amount": 25, "memo": "private memo"},
        headers={"Authorization": "Bearer operator"},
    )

    assert response.status_code == 200
    action_events = [
        event for event in protected_client.audit_events
        if event["event_type"] == "security.response_action"
    ]
    assert [event["outcome"] for event in action_events] == ["attempted", "succeeded"]
    assert all(event["details"]["simulated"] is True for event in action_events)
    assert all("private memo" not in str(event) for event in action_events)


def test_response_action_is_blocked_when_attempt_cannot_be_audited(protected_client, monkeypatch):
    def fail_for_response_attempt(event):
        if event["event_type"] == "security.response_action":
            raise RuntimeError("audit database unavailable")

    action_called = False

    def mark_action(*_args, **_kwargs):
        nonlocal action_called
        action_called = True

    monkeypatch.setattr(
        inference_main.runtime.repository,
        "record_audit_event",
        fail_for_response_attempt,
    )
    monkeypatch.setattr(inference_main.portal_state, "record_transfer", mark_action)

    response = protected_client.post(
        "/api/v1/bank/transfer",
        json={"user_id": "alice", "destination": "utility", "amount": 25},
        headers={"Authorization": "Bearer operator"},
    )

    assert response.status_code == 503
    assert action_called is False


def test_created_alert_emits_compact_audit_event(protected_client, monkeypatch):
    monkeypatch.setattr(inference_main.runtime.repository, "save_verdict", lambda _verdict: None)

    class FakeVerdict:
        session_id = "session-1"
        user_id = "alice"
        source_ip = "192.0.2.4"
        verdict = "HACKER"
        confidence = 0.98
        model_version = "model-v2"
        xgb_class = "BOT"
        timestamp = 123.0

        def to_dict(self):
            return {
                "session_id": self.session_id,
                "user_id": self.user_id,
                "source_ip": self.source_ip,
                "verdict": self.verdict,
                "confidence": self.confidence,
                "model_version": self.model_version,
                "xgb_class": self.xgb_class,
                "timestamp": self.timestamp,
            }

    inference_main.runtime._handle_verdict(FakeVerdict())

    alert_events = [
        event for event in protected_client.audit_events
        if event["event_type"] == "security.alert_created"
    ]
    assert len(alert_events) == 1
    assert alert_events[0]["resource_id"] == "session-1"
    assert alert_events[0]["details"] == {
        "confidence": 0.98,
        "model_version": "model-v2",
        "classification": "BOT",
    }


def test_audit_repository_uses_parameterized_database_insert(monkeypatch):
    calls = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, parameters):
            calls.append((query, parameters))

    class FakeConnection:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return FakeCursor()

        def close(self):
            self.closed = True

    connection = FakeConnection()
    repository = inference_main.VerdictRepository("postgresql://audit-test")
    monkeypatch.setattr(repository, "_connect", lambda: connection)
    event = inference_main._new_security_audit_event(
        "security.authentication",
        "succeeded",
        route="/api/v1/alerts",
        http_method="GET",
        actor_id="user-123",
        actor_roles=["analyst"],
        source_ip="192.0.2.5",
        details={"method": "oidc_bearer"},
    )

    repository.record_audit_event(event)

    assert len(calls) == 1
    query, parameters = calls[0]
    assert "INSERT INTO security_audit_events" in query
    assert event["event_id"] in parameters
    assert "user-123" in parameters
    assert "Bearer" not in query
    assert connection.closed is True


def configure_valid_production_environment(monkeypatch):
    monkeypatch.setattr(inference_main, "APP_ENV", "production")
    monkeypatch.setattr(inference_main, "OIDC_REQUIRED", True)
    monkeypatch.setattr(inference_main, "OIDC_ISSUER", "https://identity.example.com/realms/neurosoc")
    monkeypatch.setattr(inference_main, "ENABLE_SIMULATION_API", False)
    monkeypatch.setattr(inference_main, "ALLOWED_ORIGINS", ["https://soc.example.com"])
    monkeypatch.setattr(
        inference_main,
        "DATABASE_URL",
        "postgresql://neurosoc_app:managed-secret@db.example.com:5432/neurosoc",
    )


def test_production_startup_accepts_explicit_secure_configuration(monkeypatch):
    configure_valid_production_environment(monkeypatch)

    inference_main._validate_startup_configuration()


def test_production_startup_rejects_simulation_api(monkeypatch):
    configure_valid_production_environment(monkeypatch)
    monkeypatch.setattr(inference_main, "ENABLE_SIMULATION_API", True)

    with pytest.raises(RuntimeError, match="Simulation APIs"):
        inference_main._validate_startup_configuration()


def test_production_startup_rejects_wildcard_cors_and_demo_database(monkeypatch):
    configure_valid_production_environment(monkeypatch)
    monkeypatch.setattr(inference_main, "ALLOWED_ORIGINS", ["*"])

    with pytest.raises(RuntimeError, match="CORS_ALLOWED_ORIGINS"):
        inference_main._validate_startup_configuration()

    monkeypatch.setattr(inference_main, "ALLOWED_ORIGINS", ["http://soc.example.com"])

    with pytest.raises(RuntimeError, match="HTTPS CORS_ALLOWED_ORIGINS"):
        inference_main._validate_startup_configuration()

    monkeypatch.setattr(inference_main, "ALLOWED_ORIGINS", ["https://soc.example.com"])
    monkeypatch.setattr(inference_main, "DATABASE_URL", "postgresql://ns_user:ns_pass@db/neurosoc")

    with pytest.raises(RuntimeError, match="non-demo DATABASE_URL"):
        inference_main._validate_startup_configuration()


def test_boolean_environment_settings_reject_typos(monkeypatch):
    monkeypatch.setenv("ENABLE_SIMULATION_API", "sometimes")

    with pytest.raises(RuntimeError, match="ENABLE_SIMULATION_API"):
        inference_main._read_bool_env("ENABLE_SIMULATION_API", "false")
