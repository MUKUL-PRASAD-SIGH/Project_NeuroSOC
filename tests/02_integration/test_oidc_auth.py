from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "inference-service"))

from core.auth import (
    AuthorizationError,
    KNOWN_ROLES,
    OIDCConfig,
    OIDCValidationError,
    RESPONSE_ROLES,
    require_roles,
    required_roles_for_route,
    validate_access_token,
)


@pytest.fixture
def key_pair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def make_token(private_key, *, issuer="http://localhost:8081/realms/neurosoc", audience="neurosoc-dashboard", expires=None):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "iss": issuer,
            "sub": "pilot-user",
            "tenant_id": "acme-prod",
            "iat": now,
            "exp": expires or now + timedelta(minutes=5),
            "aud": audience,
            "preferred_username": "pilot-analyst",
            "realm_access": {"roles": ["analyst"]},
        },
        private_key,
        algorithm="RS256",
    )


def test_valid_token_returns_identity_and_roles(key_pair):
    private_key, public_key = key_pair
    token = make_token(private_key)

    claims = validate_access_token(
        token,
        OIDCConfig("http://localhost:8081/realms/neurosoc", "neurosoc-dashboard"),
        signing_key_loader=lambda _: public_key,
    )

    assert claims["user_id"] == "pilot-user"
    assert claims["username"] == "pilot-analyst"
    assert claims["roles"] == ["analyst"]
    assert claims["tenant_id"] == "acme-prod"


@pytest.mark.parametrize("tenant_id", [None, "", "bad tenant", ["acme"], "x" * 129])
def test_missing_or_malformed_tenant_claim_is_rejected(key_pair, tenant_id):
    private_key, public_key = key_pair
    now = datetime.now(timezone.utc)
    claims = {
        "iss": "http://localhost:8081/realms/neurosoc",
        "sub": "pilot-user",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        "aud": "neurosoc-dashboard",
        "tenant_id": tenant_id,
    }
    token = jwt.encode(claims, private_key, algorithm="RS256")

    with pytest.raises(OIDCValidationError, match="tenant_id"):
        validate_access_token(
            token,
            OIDCConfig("http://localhost:8081/realms/neurosoc", "neurosoc-dashboard"),
            signing_key_loader=lambda _: public_key,
        )


def test_expired_token_is_rejected(key_pair):
    private_key, public_key = key_pair
    token = make_token(private_key, expires=datetime.now(timezone.utc) - timedelta(minutes=1))

    with pytest.raises(OIDCValidationError):
        validate_access_token(token, OIDCConfig("http://localhost:8081/realms/neurosoc", "neurosoc-dashboard"), signing_key_loader=lambda _: public_key)


def test_invalid_signature_is_rejected(key_pair):
    private_key, _ = key_pair
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = make_token(private_key)

    with pytest.raises(OIDCValidationError):
        validate_access_token(token, OIDCConfig("http://localhost:8081/realms/neurosoc", "neurosoc-dashboard"), signing_key_loader=lambda _: other_key.public_key())


def test_wrong_issuer_is_rejected(key_pair):
    private_key, public_key = key_pair
    token = make_token(private_key, issuer="http://untrusted.example/realms/other")

    with pytest.raises(OIDCValidationError):
        validate_access_token(token, OIDCConfig("http://localhost:8081/realms/neurosoc", "neurosoc-dashboard"), signing_key_loader=lambda _: public_key)


def test_missing_token_is_rejected(key_pair):
    _, public_key = key_pair

    with pytest.raises(OIDCValidationError):
        validate_access_token("", OIDCConfig("http://localhost:8081/realms/neurosoc", "neurosoc-dashboard"), signing_key_loader=lambda _: public_key)


def test_role_matrix_allows_analyst_to_read():
    assert require_roles({"roles": ["analyst"]}, {"analyst", "operator", "admin", "auditor"})["roles"] == ["analyst"]


def test_role_matrix_denies_analyst_model_promotion():
    with pytest.raises(AuthorizationError):
        require_roles({"roles": ["analyst"]}, {"admin"})


def test_role_matrix_allows_operator_response_but_not_model_promotion():
    claims = {"roles": ["operator"]}
    assert require_roles(claims, {"operator", "admin"}) is claims
    with pytest.raises(AuthorizationError):
        require_roles(claims, {"admin"})


def test_role_matrix_allows_admin_model_promotion():
    assert require_roles({"roles": ["admin"]}, {"admin"})["roles"] == ["admin"]


def test_role_matrix_allows_auditor_read_but_not_response():
    claims = {"roles": ["auditor"]}
    assert require_roles(claims, {"analyst", "operator", "admin", "auditor"}) is claims
    with pytest.raises(AuthorizationError):
        require_roles(claims, {"operator", "admin"})


def test_route_policy_covers_read_response_and_model_operations():
    assert required_roles_for_route("/api/alerts", "GET") == {"analyst", "operator", "admin", "auditor", "platform-admin"}
    assert required_roles_for_route("/api/bank/transfer", "POST") == {"operator", "admin"}
    assert required_roles_for_route("/api/v1/bank/transfer", "POST") == {"operator", "admin"}
    assert required_roles_for_route("/api/v1/behavioral/vectorize", "POST") == {"operator", "admin"}
    assert required_roles_for_route("/api/v1/models/reload", "POST") == {"platform-admin"}
    assert required_roles_for_route("/models/reload", "POST") == {"platform-admin"}
    assert required_roles_for_route("/api/v1/models/candidates", "GET") == {"platform-admin"}


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/api/v1/models/promote", "POST"),
        ("/api/models/approve", "PATCH"),
        ("/models/rollback", "POST"),
        ("/api/v1/admin/users", "POST"),
        ("/admin/audit-export", "GET"),
    ],
)
def test_model_control_and_admin_namespaces_are_admin_only(path, method):
    assert required_roles_for_route(path, method) == {"platform-admin"}


@pytest.mark.parametrize(
    "path",
    [
        "/analyze",
        "/api/analyze",
        "/behavioral/vectorize",
        "/api/behavioral",
        "/api/bank/login",
        "/api/bank/transfer",
        "/api/bank/honeypot-hit",
        "/api/bank/web-attack-detected",
    ],
)
def test_state_changing_event_and_response_routes_require_operator_or_admin(path):
    assert required_roles_for_route(path, "POST") == RESPONSE_ROLES


@pytest.mark.parametrize(
    "path",
    [
        "/api/alerts/portal-abc123/decision",
        "/api/v1/alerts/portal-abc123/decision",
    ],
)
def test_alert_decision_route_requires_operator_or_admin(path):
    assert required_roles_for_route(path, "POST") == RESPONSE_ROLES


def test_websocket_and_unknown_route_policies_require_known_roles():
    assert required_roles_for_route("/ws/alerts", "WEBSOCKET") == KNOWN_ROLES
    assert required_roles_for_route("/future/endpoint", "GET") == KNOWN_ROLES
    assert required_roles_for_route("/future/endpoint", "POST") == KNOWN_ROLES
