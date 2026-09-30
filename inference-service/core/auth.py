from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import jwt
from jwt import PyJWKClient
import re


class OIDCValidationError(ValueError):
    """Raised when an OIDC access token cannot be trusted."""


class AuthorizationError(PermissionError):
    """Raised when an authenticated identity lacks a required role."""


KNOWN_ROLES = frozenset({"analyst", "operator", "admin", "auditor", "platform-admin"})
READ_ROLES = KNOWN_ROLES
RESPONSE_ROLES = frozenset({"operator", "admin"})
MODEL_ADMIN_ROLES = frozenset({"platform-admin"})
TENANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")

WRITE_ROUTES = frozenset(
    {
        "/analyze",
        "/api/analyze",
        "/behavioral/vectorize",
        "/api/behavioral",
        "/api/behavioral/vectorize",
        "/api/bank/login",
        "/api/bank/transfer",
        "/api/bank/honeypot-hit",
        "/api/bank/web-attack-detected",
    }
)


@dataclass(frozen=True)
class OIDCConfig:
    issuer: str
    audience: str

    @property
    def jwks_url(self) -> str:
        return f"{self.issuer.rstrip('/')}/protocol/openid-connect/certs"


def _roles_from_claims(claims: dict[str, Any], audience: str) -> list[str]:
    roles = set(claims.get("realm_access", {}).get("roles", []))
    client_roles = claims.get("resource_access", {}).get(audience, {}).get("roles", [])
    roles.update(client_roles)
    return sorted(str(role) for role in roles)


def normalize_tenant_id(value: Any) -> str:
    """Validate the tenant identifier emitted by the configured identity provider."""
    if not isinstance(value, str) or not TENANT_ID_PATTERN.fullmatch(value):
        raise OIDCValidationError("OIDC token does not contain a valid tenant_id claim")
    return value


def validate_access_token(
    token: str,
    config: OIDCConfig,
    *,
    signing_key_loader: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    if not token:
        raise OIDCValidationError("Missing bearer token")

    try:
        signing_key = (
            signing_key_loader
            or PyJWKClient(config.jwks_url, timeout=5).get_signing_key_from_jwt
        )(token)
        if hasattr(signing_key, "key"):
            signing_key = signing_key.key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=config.issuer,
            options={"require": ["exp", "iat", "iss", "sub"], "verify_aud": False},
            leeway=5,
        )
    except Exception as exc:
        raise OIDCValidationError("Invalid OIDC access token") from exc

    token_audiences = claims.get("aud", [])
    if isinstance(token_audiences, str):
        token_audiences = [token_audiences]
    authorized_party = claims.get("azp")
    if config.audience not in token_audiences and authorized_party != config.audience:
        raise OIDCValidationError("OIDC token audience does not match configured client")

    claims["roles"] = _roles_from_claims(claims, config.audience)
    claims["user_id"] = claims.get("sub")
    claims["username"] = claims.get("preferred_username")
    claims["tenant_id"] = normalize_tenant_id(claims.get("tenant_id"))
    return claims


def require_roles(claims: dict[str, Any], allowed_roles: set[str]) -> dict[str, Any]:
    roles = set(claims.get("roles", []))
    if not roles.intersection(allowed_roles):
        raise AuthorizationError("Authenticated user lacks the required role")
    return claims


def canonical_route_path(path: str) -> str:
    """Map versioned API paths to the policy's canonical route names."""
    if path.startswith("/api/v1/"):
        return "/api" + path[len("/api/v1"):]
    return path


def required_roles_for_route(path: str, method: str) -> frozenset[str]:
    path = canonical_route_path(path)
    method = method.upper()
    admin_prefixes = ("/admin", "/api/admin")
    if any(path == prefix or path.startswith(prefix + "/") for prefix in admin_prefixes):
        return MODEL_ADMIN_ROLES
    if path in {"/models/reload", "/api/models/reload"}:
        return MODEL_ADMIN_ROLES
    if path in {"/models/candidates", "/api/models/candidates"} or path.startswith(
        ("/models/candidates/", "/api/models/candidates/")
    ):
        return MODEL_ADMIN_ROLES
    if method in {"POST", "PUT", "PATCH", "DELETE"} and path.startswith(("/models/", "/api/models/")):
        return MODEL_ADMIN_ROLES
    if path in {"/ws/alerts", "/api/ws/alerts"}:
        return READ_ROLES
    if method == "POST" and path.startswith("/api/alerts/") and path.endswith("/decision"):
        return RESPONSE_ROLES
    if method in {"POST", "PUT", "PATCH", "DELETE"} and path in WRITE_ROUTES:
        return RESPONSE_ROLES
    if method in {"GET", "HEAD", "OPTIONS"}:
        return READ_ROLES
    # Keep future protected routes behind a valid NeuroSOC role until their
    # endpoint-specific policy is added.
    return KNOWN_ROLES
