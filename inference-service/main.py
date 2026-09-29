from __future__ import annotations

import hashlib
import json
import ipaddress
import logging
import os
import re
import tempfile
import threading
import time
import uuid
from collections import OrderedDict, deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit
from urllib import error as urllib_error
from urllib import request as urllib_request

import numpy as np
import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.exceptions import RequestValidationError
from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError, NoBrokersAvailable
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator
import asyncio
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import WebSocketRoute
from starlette.responses import JSONResponse

try:
    import psycopg2
    from psycopg2.extras import Json, RealDictCursor
except ImportError:  # pragma: no cover - keeps importable in lightweight environments
    psycopg2 = None
    RealDictCursor = None

    def Json(value: Any) -> Any:  # type: ignore[misc]
        return value

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("BEHAVIOR_PROFILE_DIR", str(REPO_ROOT / "data" / "behavioral_profiles"))

from core.behavioral.signals import extract_session_vector
from core.engine import DecisionEngine, ThreatVerdict
from core.xgboost.model import CLASS_NAMES as TRAINING_CLASS_NAMES
from core.auth import (
    AuthorizationError,
    MODEL_ADMIN_ROLES,
    OIDCConfig,
    OIDCValidationError,
    canonical_route_path,
    require_roles,
    required_roles_for_route,
    validate_access_token,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [inference] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)


def _resolve_model_dir() -> Path:
    configured = os.getenv("MODEL_PATH")
    if configured:
        return Path(configured).expanduser()
    container_models = Path("/models")
    if os.name != "nt" and container_models.exists():
        return container_models
    return REPO_ROOT / "models"


def _read_bool_env(name: str, default: str) -> bool:
    value = os.getenv(name, default).strip().lower()
    if value not in {"true", "false"}:
        raise RuntimeError(f"{name} must be set to 'true' or 'false'.")
    return value == "true"


def _read_positive_int_env(name: str, default: str) -> int:
    try:
        value = int(os.getenv(name, default))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer.") from exc
    if value < 1:
        raise RuntimeError(f"{name} must be a positive integer.")
    return value


def _parse_cors_origins(value: str) -> list[str]:
    origins: list[str] = []
    for entry in value.split(","):
        candidate = entry.strip()
        if not candidate:
            continue
        try:
            parsed = urlsplit(candidate)
            hostname = parsed.hostname
            port = parsed.port
        except ValueError as exc:
            raise RuntimeError("CORS_ALLOWED_ORIGINS must contain valid HTTP or HTTPS origins only.") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or "?" in candidate
            or "#" in candidate
            or any(character.isspace() for character in parsed.netloc)
            or "*" in parsed.netloc
        ):
            raise RuntimeError("CORS_ALLOWED_ORIGINS must contain valid HTTP or HTTPS origins only.")

        try:
            address = ipaddress.ip_address(hostname)
            canonical_host = f"[{address.compressed}]" if address.version == 6 else address.compressed
        except ValueError:
            try:
                canonical_host = hostname.encode("idna").decode("ascii").lower()
            except UnicodeError as exc:
                raise RuntimeError("CORS_ALLOWED_ORIGINS contains an invalid host.") from exc
            labels = canonical_host.rstrip(".").split(".")
            if any(
                not label
                or len(label) > 63
                or label[0] == "-"
                or label[-1] == "-"
                or not re.fullmatch(r"[a-z0-9-]+", label)
                for label in labels
            ):
                raise RuntimeError("CORS_ALLOWED_ORIGINS contains an invalid host.")

        if port is not None and not (parsed.scheme == "http" and port == 80) and not (
            parsed.scheme == "https" and port == 443
        ):
            canonical_host = f"{canonical_host}:{port}"
        normalized = f"{parsed.scheme}://{canonical_host}"
        if normalized not in origins:
            origins.append(normalized)
    if not origins:
        raise RuntimeError("CORS_ALLOWED_ORIGINS must contain at least one explicit origin.")
    return origins


def _parse_trusted_proxy_ips(value: str) -> str:
    entries = [entry.strip() for entry in value.split(",")]
    if not value.strip():
        return ""
    if any(not entry or entry == "*" for entry in entries):
        raise RuntimeError("TRUSTED_PROXY_IPS must contain explicit IP addresses or CIDRs; wildcards are not allowed.")
    normalized: list[str] = []
    for entry in entries:
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError as exc:
            raise RuntimeError("TRUSTED_PROXY_IPS must contain valid IP addresses or CIDRs.") from exc
        value = str(network)
        if value not in normalized:
            normalized.append(value)
    return ",".join(normalized)


KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "kafka:9092")
DATABASE_URL = os.getenv("DATABASE_URL", "")
INPUT_TOPIC = os.getenv("INFERENCE_INPUT_TOPIC", "extracted-features")
VERDICTS_TOPIC = os.getenv("VERDICTS_TOPIC", "verdicts")
ALERTS_TOPIC = os.getenv("ALERTS_TOPIC", "alerts")
GROUP_ID = os.getenv("INFERENCE_GROUP_ID", "inference-service")
MODEL_DIR = _resolve_model_dir()
MODEL_VERSION_PATH = Path(os.getenv("MODEL_VERSION_FILE", str(MODEL_DIR / "model_version.json")))
MODEL_CANDIDATES_DIR = MODEL_VERSION_PATH.parent / "candidates"
MODEL_HISTORY_DIR = MODEL_VERSION_PATH.parent / "history"
MODEL_POLL_SECONDS = float(os.getenv("MODEL_POLL_SECONDS", "60"))
CONSUMER_RETRY_SECONDS = float(os.getenv("CONSUMER_RETRY_SECONDS", "5"))
LATEST_VERDICTS_LIMIT = int(os.getenv("LATEST_VERDICTS_LIMIT", "200"))
HOST = os.getenv("INFERENCE_HOST", "0.0.0.0")
PORT = int(os.getenv("INFERENCE_PORT", "8000"))
API_KEY = os.getenv("API_KEY", "")
APP_ENV = os.getenv("APP_ENV", "local").strip().lower()
OIDC_ISSUER = os.getenv("OIDC_ISSUER", "").rstrip("/")
OIDC_AUDIENCE = os.getenv("OIDC_AUDIENCE", "neurosoc-dashboard")
OIDC_REQUIRED = _read_bool_env("OIDC_REQUIRED", "false")
ENABLE_SIMULATION_API = _read_bool_env("ENABLE_SIMULATION_API", "false")
ALLOWED_ORIGINS = _parse_cors_origins(
    os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5174")
)
TRUSTED_PROXY_IPS = _parse_trusted_proxy_ips(os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1,::1"))
MAX_REQUEST_BODY_BYTES = _read_positive_int_env("API_MAX_REQUEST_BODY_BYTES", "1048576")
API_RATE_LIMIT_PER_MINUTE = _read_positive_int_env("API_RATE_LIMIT_PER_MINUTE", "120")
SANDBOX_BASE_URL = os.getenv("SANDBOX_BASE_URL", "").rstrip("/")
IPINFO_TOKEN = os.getenv("IPINFO_TOKEN", "").strip()
SANDBOX_TIMEOUT_SECONDS = int(os.getenv("SANDBOX_TIMEOUT_SEC", "300"))
PORTAL_SESSION_TTL_SECONDS = int(os.getenv("PORTAL_SESSION_TTL_SECONDS", "1800"))
APP_STARTED_AT = time.time()

SQLI_PATTERN = re.compile(r"(union\s+select|or\s+1\s*=\s*1|--|/\*|drop\s+table|insert\s+into)", re.IGNORECASE)
BEHAVIOR_DIMENSIONS = [
    "Velocity",
    "Session Drift",
    "Bot Pressure",
    "Credential Risk",
    "Geo Variance",
    "Device Novelty",
    "Typing Rhythm",
    "Mouse Entropy",
    "Route Depth",
    "Auth Friction",
    "Token Churn",
    "Transfer Heat",
    "Time Deviation",
    "Privilege Lift",
    "IP Reputation",
    "Cashout Risk",
    "Login Burst",
    "Browser Trust",
    "Peer Similarity",
    "Recovery Abuse",
]

def _load_simulation_accounts() -> dict[str, dict[str, Any]]:
    if not ENABLE_SIMULATION_API:
        return {}
    from core.simulation_accounts import BANK_ACCOUNTS

    return BANK_ACCOUNTS


BANK_ACCOUNTS = _load_simulation_accounts()


Identifier = Annotated[StrictStr, Field(min_length=1, max_length=256)]
SessionIdentifier = Annotated[StrictStr, Field(min_length=1, max_length=128)]
SourceAddress = Annotated[StrictStr, Field(min_length=1, max_length=64)]
FiniteFloat = Annotated[StrictFloat, Field(allow_inf_nan=False)]
Probability = Annotated[StrictFloat, Field(ge=0.0, le=1.0, allow_inf_nan=False)]


class StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StrictResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionAnalyzeRequest(StrictRequestModel):
    session_id: SessionIdentifier
    user_id: Identifier = "unknown-user"
    source_ip: SourceAddress = "unknown"
    flow_features: list[FiniteFloat] = Field(..., min_length=80, max_length=80)
    raw_flow_features: list[FiniteFloat] | None = Field(default=None, min_length=80, max_length=80)
    behavioral_events: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)
    behavioral_vector: list[FiniteFloat] | None = Field(default=None, min_length=20, max_length=20)
    session_sequence: list[FiniteFloat] | list[list[FiniteFloat]] | None = Field(default=None, max_length=200)
    unique_dst_ports: StrictInt | None = Field(default=None, ge=0, le=65536)
    login_attempts: StrictInt | None = Field(default=None, ge=0, le=100000)
    all_different_passwords: StrictBool | None = None
    sql_injection_detected: StrictBool | None = None
    timestamp: FiniteFloat | None = None

    @model_validator(mode="after")
    def validate_session_sequence_width(self) -> "SessionAnalyzeRequest":
        sequence = self.session_sequence
        if not sequence:
            return self
        if isinstance(sequence[0], list):
            rows = sequence  # type: ignore[assignment]
            if any(len(row) != 80 for row in rows):
                raise ValueError("session_sequence rows must contain exactly 80 feature values")
        elif len(sequence) != 80:
            raise ValueError("session_sequence must contain exactly 80 feature values")
        return self


class BehavioralVectorRequest(StrictRequestModel):
    events: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)


class BehavioralIngestRequest(StrictRequestModel):
    user_id: Identifier = "anonymous"
    session_id: SessionIdentifier | None = None
    events: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)
    source_ip: SourceAddress = "unknown"
    page: Annotated[str, Field(max_length=2048)] | None = None


class BankLoginRequest(StrictRequestModel):
    email: Annotated[StrictStr, Field(min_length=3, max_length=254)]
    password: Annotated[StrictStr, Field(max_length=1024)]
    session_id: SessionIdentifier | None = None
    source_ip: SourceAddress = "unknown"


class BankTransferRequest(StrictRequestModel):
    user_id: Identifier = "unknown-user"
    session_id: SessionIdentifier | None = None
    source_ip: SourceAddress = "unknown"
    destination: Annotated[StrictStr, Field(min_length=1, max_length=256)]
    amount: Annotated[StrictFloat, Field(ge=0.0, le=1_000_000_000.0, allow_inf_nan=False)]
    memo: Annotated[StrictStr, Field(max_length=4096)] | None = None
    confirm_routing_number: Annotated[StrictStr, Field(max_length=64)] | None = None


class HoneypotHitRequest(StrictRequestModel):
    source: Annotated[StrictStr, Field(max_length=128)] = "unknown"
    user_id: Identifier = "anonymous"
    session_id: SessionIdentifier | None = None
    source_ip: SourceAddress = "unknown"


class WebAttackDetectedRequest(StrictRequestModel):
    attack_type: Annotated[StrictStr, Field(min_length=1, max_length=64)] = "WEB_ATTACK"
    payload: Annotated[StrictStr, Field(max_length=4096)] = ""
    user_id: Identifier = "anonymous"
    session_id: SessionIdentifier | None = None
    source_ip: SourceAddress = "unknown"


class AlertDecisionRequest(StrictRequestModel):
    decision: Literal["confirm_threat", "false_positive", "restore_access", "escalate"]
    notes: Annotated[StrictStr, Field(max_length=2048)] | None = None


class AlertDecisionResponse(StrictResponseModel):
    sessionId: StrictStr
    decision: StrictStr
    status: StrictStr
    decidedBy: StrictStr
    decidedAt: datetime
    trainingLabelWritten: StrictStr | None = None


class RootResponse(StrictResponseModel):
    service: StrictStr
    phase: StrictInt
    status: StrictStr
    input_topic: StrictStr
    verdicts_topic: StrictStr
    alerts_topic: StrictStr


class ThreatVerdictResponse(StrictResponseModel):
    session_id: SessionIdentifier
    user_id: Identifier
    source_ip: SourceAddress
    snn_score: Probability
    lnn_class: StrictStr
    xgb_class: StrictStr
    behavioral_delta: Probability
    confidence: Probability
    verdict: StrictStr
    timestamp: FiniteFloat
    model_version: StrictStr
    features_dict: dict[str, Any] = Field(default_factory=dict)


class HealthResponse(StrictResponseModel):
    status: StrictStr
    timestamp: FiniteFloat
    kafka_consumer_connected: StrictBool
    kafka_producer_connected: StrictBool
    processed_messages: StrictInt
    model_version: StrictStr
    latest_verdict: ThreatVerdictResponse | None
    database_enabled: StrictBool


class RecentVerdictResponse(StrictResponseModel):
    id: StrictStr
    verdict: StrictStr
    score: Probability
    timestamp: FiniteFloat | datetime


class AlertDimensionResponse(StrictResponseModel):
    subject: StrictStr
    value: FiniteFloat


class SandboxActivationResponse(StrictResponseModel):
    active: StrictBool
    mode: StrictStr | None = None
    sandboxToken: StrictStr | None = None
    sandboxPath: StrictStr | None = None


class ModelVersionEntryResponse(StrictResponseModel):
    label: StrictStr
    value: StrictStr


class ModelScoreEntryResponse(StrictResponseModel):
    label: StrictStr
    value: Probability | None


class ModelVersionResponse(StrictResponseModel):
    version: StrictStr
    versions: list[ModelVersionEntryResponse]
    validationF1: list[ModelScoreEntryResponse]
    lastRetrainedAt: StrictStr | FiniteFloat | None
    activeModels: list[StrictStr]


class StatsResponse(StrictResponseModel):
    totalTransactions: StrictInt
    hackerDetections: StrictInt
    avgRiskScore: FiniteFloat
    liveAlerts: StrictInt
    legitimateCount: StrictInt
    uptimeSeconds: StrictInt


class ExplanationFeatureResponse(StrictResponseModel):
    feature: StrictStr
    value: FiniteFloat
    impact: FiniteFloat


class AlertExplanationResponse(StrictResponseModel):
    summary: StrictStr
    topFeatures: list[ExplanationFeatureResponse]
    snnSpikeScore: FiniteFloat
    lnnBehavioralDelta: FiniteFloat
    method: StrictStr


class AlertResponse(StrictResponseModel):
    id: StrictStr
    severity: StrictStr
    verdict: StrictStr
    message: StrictStr
    timestamp: FiniteFloat | datetime
    sourceIp: StrictStr
    userId: Identifier
    userName: StrictStr
    locationLabel: StrictStr
    score: Probability
    dimensions: list[AlertDimensionResponse]
    recentVerdicts: list[RecentVerdictResponse]
    modelVersion: StrictStr
    status: StrictStr = "new"
    decision: StrictStr | None = None
    explanation: AlertExplanationResponse


class RawAlertResponse(StrictResponseModel):
    session_id: SessionIdentifier
    user_id: Identifier
    source_ip: SourceAddress
    confidence: Probability
    verdict: StrictStr
    timestamp: FiniteFloat | None = None
    model_version: StrictStr | None = None
    xgb_class: StrictStr | None = None
    created_at: datetime | None = None


class LatestVerdictsResponse(StrictResponseModel):
    count: int = Field(ge=0)
    items: list[ThreatVerdictResponse]


class LatestAlertsResponse(StrictResponseModel):
    count: int = Field(ge=0)
    items: list[RawAlertResponse]


class VerdictSnapshotResponse(StrictResponseModel):
    session_id: SessionIdentifier | None = None
    user_id: Identifier | None = None
    source_ip: SourceAddress | None = None
    snn_score: Probability | None = None
    lnn_class: StrictStr | None = None
    xgb_class: StrictStr | None = None
    behavioral_delta: Probability | None = None
    confidence: Probability | None = None
    verdict: StrictStr | None = None
    timestamp: FiniteFloat | None = None
    model_version: StrictStr | None = None
    features_dict: dict[str, Any] | None = None
    created_at: datetime | None = None
    sessionId: SessionIdentifier | None = None
    userId: Identifier | None = None
    sourceIp: SourceAddress | None = None
    snnScore: Probability | None = None
    lnnClass: StrictStr | None = None
    xgbClass: StrictStr | None = None
    behavioralDelta: Probability | None = None
    modelVersion: StrictStr | None = None
    sandbox: SandboxActivationResponse | None = None
    recentVerdicts: list[RecentVerdictResponse] | None = None
    history: list["VerdictSnapshotResponse"] | None = None


class BehavioralVectorResponse(StrictResponseModel):
    vector: list[FiniteFloat] = Field(min_length=20, max_length=20)


class BehavioralIngestResponse(StrictResponseModel):
    status: StrictStr
    userId: Identifier
    sessionId: SessionIdentifier
    eventCount: StrictInt
    vector: list[FiniteFloat] = Field(min_length=20, max_length=20)


class BankAccountSummaryResponse(StrictResponseModel):
    balance: FiniteFloat
    accountMasked: str


class BankLoginResponse(StrictResponseModel):
    authenticated: StrictBool
    user_id: Identifier
    displayName: StrictStr
    sessionId: SessionIdentifier
    verdict: StrictStr
    confidence: Probability
    sandbox: SandboxActivationResponse | None
    next: StrictStr
    account: BankAccountSummaryResponse | None = None
    error: StrictStr | None = None


class BankTransferResponse(StrictResponseModel):
    status: StrictStr
    sessionId: SessionIdentifier
    verdict: StrictStr
    confidence: Probability
    sandbox: SandboxActivationResponse | None
    message: StrictStr


class BankEventResponse(StrictResponseModel):
    status: StrictStr
    sessionId: SessionIdentifier
    verdict: StrictStr
    confidence: Probability
    sandbox: SandboxActivationResponse | None


class SandboxActionResponse(StrictResponseModel):
    action_id: StrictInt | None = None
    session_id: SessionIdentifier | None = None
    sandbox_token: str | None = None
    path: StrictStr
    method: StrictStr
    timestamp: FiniteFloat
    headers_json: dict[str, Any] | None = None
    body: Any = None
    response_sent: Any = None
    port: StrictInt | None = None
    features: list[FiniteFloat] | None = None
    trigger_tags: list[StrictStr] | None = None
    sandbox_ended_at: datetime | None = None
    feedback_sent: StrictBool | None = None
    assigned_label: StrictStr | None = None


class SandboxReplayResponse(StrictResponseModel):
    session_id: SessionIdentifier
    sandbox_token: StrictStr | None = None
    mode: StrictStr | None = None
    actions: list[SandboxActionResponse]


class ModelReloadResponse(StrictResponseModel):
    reloaded: StrictBool
    active_model_version: StrictStr


class ModelCandidateResponse(StrictResponseModel):
    candidateId: StrictStr
    status: StrictStr
    modelKey: StrictStr
    baseModelVersion: StrictStr
    proposedVersion: StrictStr
    validationF1: FiniteFloat
    metrics: dict[str, Any]
    createdAt: StrictStr
    promotedAt: StrictStr | None = None
    promotedBy: StrictStr | None = None
    rejectedAt: StrictStr | None = None
    rejectedBy: StrictStr | None = None


class ModelPromotionResponse(StrictResponseModel):
    candidateId: StrictStr
    status: StrictStr
    activeModelVersion: StrictStr
    reloaded: StrictBool


class ModelRollbackResponse(StrictResponseModel):
    restoredVersion: StrictStr
    activeModelVersion: StrictStr
    reloaded: StrictBool


class ProfileResponse(StrictResponseModel):
    user_id: Identifier
    profile_vector: list[FiniteFloat] = Field(min_length=20, max_length=20)
    profile_std: list[FiniteFloat] = Field(min_length=20, max_length=20)
    session_count: StrictInt = Field(ge=0)
    last_updated: FiniteFloat
    alpha: Probability


class ErrorResponse(StrictResponseModel):
    detail: StrictStr


class RateLimitResponse(ErrorResponse):
    retry_after_seconds: StrictInt


class RequestBodyLimitMiddleware:
    """Buffer only bounded HTTP request bodies before dispatching the app."""

    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = next(
            (value for key, value in scope.get("headers", []) if key.lower() == b"content-length"),
            None,
        )
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                await JSONResponse(
                    status_code=400,
                    content=ErrorResponse(detail="Invalid Content-Length header.").model_dump(),
                )(scope, receive, send)
                return
            if declared_length < 0:
                await JSONResponse(
                    status_code=400,
                    content=ErrorResponse(detail="Invalid Content-Length header.").model_dump(),
                )(scope, receive, send)
                return
            if declared_length > self.max_bytes:
                await JSONResponse(
                    status_code=413,
                    content=ErrorResponse(detail="Request body exceeds the configured size limit.").model_dump(),
                )(scope, receive, send)
                return

        body_chunks: list[bytes] = []
        total_bytes = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            total_bytes += len(chunk)
            if total_bytes > self.max_bytes:
                await JSONResponse(
                    status_code=413,
                    content=ErrorResponse(detail="Request body exceeds the configured size limit.").model_dump(),
                )(scope, receive, send)
                return
            body_chunks.append(chunk)
            if not message.get("more_body", False):
                break

        body = b"".join(body_chunks)
        body_sent = False

        async def replay_body():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay_body, send)


class FixedWindowRateLimiter:
    def __init__(self, limit: int, window_seconds: int = 60, max_clients: int = 10_000) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self._windows: OrderedDict[str, tuple[float, int]] = OrderedDict()
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._windows.clear()

    def check(self, client_key: str, now: float | None = None) -> int | None:
        now = time.monotonic() if now is None else now
        with self._lock:
            existing = self._windows.get(client_key)
            if existing is None:
                if len(self._windows) >= self.max_clients:
                    self._windows.popitem(last=False)
                self._windows[client_key] = (now, 1)
                return None

            window_started, count = existing
            elapsed = now - window_started
            if elapsed >= self.window_seconds:
                self._windows[client_key] = (now, 1)
                self._windows.move_to_end(client_key)
                return None

            self._windows.move_to_end(client_key)
            if count >= self.limit:
                return max(1, int(self.window_seconds - elapsed + 0.999))
            self._windows[client_key] = (window_started, count + 1)
            return None


@dataclass
class PortalSession:
    session_id: str
    user_key: str
    source_ip: str
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    behavioral_events: list[dict[str, Any]] = field(default_factory=list)
    behavioral_vector: list[float] = field(default_factory=lambda: [0.0] * 20)
    known_aliases: set[str] = field(default_factory=set)
    login_passwords: set[str] = field(default_factory=set)
    login_attempts: int = 0
    failed_logins: int = 0
    honeypot_hits: list[dict[str, Any]] = field(default_factory=list)
    web_attacks: list[dict[str, Any]] = field(default_factory=list)
    transfer_attempts: list[dict[str, Any]] = field(default_factory=list)
    latest_verdict: dict[str, Any] | None = None
    sandbox_token: str | None = None
    sandbox_mode: str | None = None
    sandbox_started_at: float | None = None

    def touch(self) -> None:
        self.last_seen = time.time()


class PortalState:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, PortalSession] = {}
        self._alias_to_session: dict[str, str] = {}
        self._user_current_session: dict[str, str] = {}
        self._current_session_id: str | None = None

    def cleanup(self) -> None:
        cutoff = time.time() - PORTAL_SESSION_TTL_SECONDS
        with self._lock:
            expired = [session_id for session_id, session in self._sessions.items() if session.last_seen < cutoff]
            for session_id in expired:
                session = self._sessions.pop(session_id, None)
                if session is None:
                    continue
                for alias in session.known_aliases:
                    if self._alias_to_session.get(alias) == session_id:
                        self._alias_to_session.pop(alias, None)
                for alias in list(self._user_current_session):
                    if self._user_current_session.get(alias) == session_id:
                        self._user_current_session.pop(alias, None)
                if self._current_session_id == session_id:
                    self._current_session_id = None

    def _normalize_alias(self, value: str | None) -> str:
        return (value or "anonymous").strip().lower() or "anonymous"

    def _ensure_session(self, user_key: str, session_id: str | None = None, source_ip: str = "unknown") -> PortalSession:
        self.cleanup()
        normalized_key = self._normalize_alias(user_key)
        resolved_session_id = session_id or self._alias_to_session.get(normalized_key) or f"portal-{uuid.uuid4().hex}"
        session = self._sessions.get(resolved_session_id)
        if session is None:
            session = PortalSession(session_id=resolved_session_id, user_key=normalized_key, source_ip=source_ip)
            self._sessions[resolved_session_id] = session
        session.source_ip = source_ip or session.source_ip
        session.known_aliases.add(normalized_key)
        self._alias_to_session[normalized_key] = resolved_session_id
        self._user_current_session[normalized_key] = resolved_session_id
        self._current_session_id = resolved_session_id
        session.touch()
        return session

    def bind_aliases(self, canonical_user_id: str, session_id: str | None, aliases: list[str]) -> PortalSession:
        with self._lock:
            base_alias = aliases[0] if aliases else canonical_user_id
            session = self._ensure_session(base_alias, session_id=session_id)
            for alias in aliases + [canonical_user_id]:
                normalized = self._normalize_alias(alias)
                session.known_aliases.add(normalized)
                self._alias_to_session[normalized] = session.session_id
                self._user_current_session[normalized] = session.session_id
            session.touch()
            return session

    def record_behavioral(self, request: BehavioralIngestRequest) -> PortalSession:
        with self._lock:
            session = self._ensure_session(request.user_id, request.session_id, request.source_ip)
            session.behavioral_events.extend(request.events)
            if request.page:
                session.behavioral_events.append(
                    {"type": "pagevisit", "timestamp": time.time(), "page": request.page}
                )
            session.behavioral_events = session.behavioral_events[-500:]
            session.behavioral_vector = extract_session_vector(session.behavioral_events).astype(float).tolist()
            return session

    def record_login_attempt(
        self,
        identifier: str,
        password: str,
        session_id: str | None,
        source_ip: str,
        authenticated: bool,
    ) -> PortalSession:
        with self._lock:
            session = self._ensure_session(identifier, session_id, source_ip)
            session.login_attempts += 1
            if password:
                session.login_passwords.add(password)
            if not authenticated:
                session.failed_logins += 1
            return session

    def record_honeypot(
        self,
        identifier: str,
        session_id: str | None,
        source_ip: str,
        source: str,
    ) -> PortalSession:
        with self._lock:
            session = self._ensure_session(identifier, session_id, source_ip)
            session.honeypot_hits.append({"source": source, "timestamp": time.time()})
            return session

    def record_web_attack(
        self,
        identifier: str,
        session_id: str | None,
        source_ip: str,
        attack_type: str,
        payload: str,
    ) -> PortalSession:
        with self._lock:
            session = self._ensure_session(identifier, session_id, source_ip)
            session.web_attacks.append({"attack_type": attack_type, "payload": payload, "timestamp": time.time()})
            return session

    def record_transfer(
        self,
        identifier: str,
        session_id: str | None,
        source_ip: str,
        amount: float,
        destination: str,
        memo: str | None,
    ) -> PortalSession:
        with self._lock:
            session = self._ensure_session(identifier, session_id, source_ip)
            session.transfer_attempts.append(
                {
                    "amount": amount,
                    "destination": destination,
                    "memo": memo,
                    "timestamp": time.time(),
                }
            )
            session.transfer_attempts = session.transfer_attempts[-25:]
            return session

    def set_verdict(self, session_id: str, verdict: dict[str, Any]) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            session.latest_verdict = verdict
            self._current_session_id = session_id
            session.touch()

    def attach_sandbox(self, session_id: str, sandbox_token: str, mode: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return
            session.sandbox_token = sandbox_token
            session.sandbox_mode = mode
            session.sandbox_started_at = session.sandbox_started_at or time.time()
            session.touch()

    def get_session(self, identifier: str | None = None, session_id: str | None = None) -> PortalSession | None:
        with self._lock:
            self.cleanup()
            resolved_session_id = session_id
            if resolved_session_id is None and identifier is not None:
                normalized = self._normalize_alias(identifier)
                resolved_session_id = self._alias_to_session.get(normalized) or self._user_current_session.get(normalized)
            if resolved_session_id is None:
                return None
            return self._sessions.get(resolved_session_id)

    def current_verdict(self) -> dict[str, Any] | None:
        with self._lock:
            if self._current_session_id is None:
                return None
            session = self._sessions.get(self._current_session_id)
            return None if session is None else session.latest_verdict

    def replay_stub(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return []
            actions: list[dict[str, Any]] = []
            if session.sandbox_started_at is not None:
                actions.append(
                    {
                        "path": "/api/bank/login",
                        "method": "POST",
                        "timestamp": session.sandbox_started_at,
                        "body": {
                            "event": "diverted_to_sandbox",
                            "failed_logins": session.failed_logins,
                            "distinct_passwords": len(session.login_passwords),
                        },
                    }
                )
            for hit in session.honeypot_hits:
                actions.append(
                    {
                        "path": "/api/bank/honeypot-hit",
                        "method": "POST",
                        "timestamp": hit["timestamp"],
                        "body": hit,
                    }
                )
            for attack in session.web_attacks:
                actions.append(
                    {
                        "path": "/api/bank/web-attack-detected",
                        "method": "POST",
                        "timestamp": attack["timestamp"],
                        "body": attack,
                    }
                )
            for transfer in session.transfer_attempts:
                actions.append(
                    {
                        "path": "/api/bank/transfer",
                        "method": "POST",
                        "timestamp": transfer["timestamp"],
                        "body": transfer,
                    }
                )
            return sorted(actions, key=lambda item: float(item["timestamp"]))


class SandboxGateway:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def _request(self, path: str, method: str = "GET", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.base_url:
            raise RuntimeError("SANDBOX_BASE_URL is not configured.")
        body = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
        request = urllib_request.Request(f"{self.base_url}{path}", method=method, data=body, headers=headers)
        with urllib_request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def create_session(self, session_id: str, user_id: str, source_ip: str) -> dict[str, Any]:
        try:
            return self._request(
                "/sessions",
                method="POST",
                payload={"session_id": session_id, "user_id": user_id, "source_ip": source_ip},
            )
        except (RuntimeError, urllib_error.URLError, urllib_error.HTTPError, TimeoutError) as exc:
            raise RuntimeError(f"Sandbox session creation failed: {exc}") from exc

    def replay(self, sandbox_token: str) -> dict[str, Any]:
        try:
            return self._request(f"/sessions/{sandbox_token}/replay")
        except (RuntimeError, urllib_error.URLError, urllib_error.HTTPError, TimeoutError) as exc:
            raise RuntimeError(f"Sandbox replay lookup failed: {exc}") from exc

class VerdictRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connect(self):
        if not self.database_url:
            return None
        if psycopg2 is None or RealDictCursor is None:
            raise RuntimeError("psycopg2 is required to persist inference verdicts.")
        return psycopg2.connect(
            self.database_url,
            cursor_factory=RealDictCursor,
            connect_timeout=5,
            options="-c statement_timeout=10000 -c lock_timeout=3000",
        )

    def bootstrap(self) -> None:
        conn = self._connect()
        if conn is None:
            log.info("DATABASE_URL not configured; inference DB persistence disabled.")
            return
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS verdicts (
                        id BIGSERIAL PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        source_ip TEXT NOT NULL,
                        verdict TEXT NOT NULL,
                        confidence DOUBLE PRECISION NOT NULL,
                        snn_score DOUBLE PRECISION NOT NULL,
                        lnn_class TEXT NOT NULL,
                        xgb_class TEXT NOT NULL,
                        behavioral_delta DOUBLE PRECISION NOT NULL,
                        model_version TEXT NOT NULL,
                        features JSONB NOT NULL,
                        features_dict JSONB NOT NULL DEFAULT '{}'::jsonb,
                        flow_features JSONB NOT NULL,
                        timestamp DOUBLE PRECISION NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS alerts (
                        id BIGSERIAL PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        source_ip TEXT NOT NULL,
                        verdict TEXT NOT NULL,
                        confidence DOUBLE PRECISION NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS security_audit_events (
                        event_id TEXT PRIMARY KEY,
                        event_type TEXT NOT NULL,
                        outcome TEXT NOT NULL,
                        actor_id TEXT,
                        actor_roles JSONB NOT NULL DEFAULT '[]'::jsonb,
                        http_method TEXT,
                        route TEXT NOT NULL,
                        source_ip TEXT,
                        resource_id TEXT,
                        details JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS alert_decisions (
                        id BIGSERIAL PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        decision TEXT NOT NULL,
                        status TEXT NOT NULL,
                        decided_by TEXT NOT NULL,
                        decided_by_roles JSONB NOT NULL DEFAULT '[]'::jsonb,
                        notes TEXT,
                        decided_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_alert_decisions_session
                    ON alert_decisions (session_id, decided_at DESC)
                    """
                )
                # Same shape feedback-service writes to; an analyst decision is a human label
                # that retraining should trust at least as much as the heuristic sandbox labels.
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS labeled_training_data (
                        id BIGSERIAL PRIMARY KEY,
                        session_id TEXT UNIQUE NOT NULL,
                        features JSONB NOT NULL,
                        label TEXT NOT NULL,
                        confidence DOUBLE PRECISION NOT NULL,
                        attack_type TEXT,
                        trigger_reason TEXT,
                        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
        conn.close()

    def record_audit_event(self, event: dict[str, Any]) -> None:
        conn = self._connect()
        if conn is None:
            log.info("security_audit %s", json.dumps(event, sort_keys=True, separators=(",", ":")))
            return
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO security_audit_events (
                            event_id, event_type, outcome, actor_id, actor_roles,
                            http_method, route, source_ip, resource_id, details
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            event["event_id"],
                            event["event_type"],
                            event["outcome"],
                            event.get("actor_id"),
                            Json(event.get("actor_roles", [])),
                            event.get("http_method"),
                            event["route"],
                            event.get("source_ip"),
                            event.get("resource_id"),
                            Json(event.get("details", {})),
                        ),
                    )
        finally:
            conn.close()

    def save_verdict(self, verdict: ThreatVerdict) -> None:
        conn = self._connect()
        if conn is None:
            return
        with conn:
            with conn.cursor() as cur:
                feature_vector = self._ordered_flow_features(verdict.features_dict)
                cur.execute(
                    """
                    INSERT INTO verdicts (
                        session_id,
                        user_id,
                        source_ip,
                        verdict,
                        confidence,
                        snn_score,
                        lnn_class,
                        xgb_class,
                        behavioral_delta,
                        model_version,
                        features,
                        features_dict,
                        flow_features,
                        timestamp
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        verdict.session_id,
                        verdict.user_id,
                        verdict.source_ip,
                        verdict.verdict,
                        verdict.confidence,
                        verdict.snn_score,
                        verdict.lnn_class,
                        verdict.xgb_class,
                        verdict.behavioral_delta,
                        verdict.model_version,
                        Json(feature_vector),
                        Json(verdict.features_dict),
                        Json(feature_vector),
                        verdict.timestamp,
                    ),
                )
                if verdict.verdict == "HACKER":
                    cur.execute(
                        """
                        INSERT INTO alerts (session_id, user_id, source_ip, verdict, confidence)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            verdict.session_id,
                            verdict.user_id,
                            verdict.source_ip,
                            verdict.verdict,
                            verdict.confidence,
                        ),
                    )
        conn.close()

    @staticmethod
    def _ordered_flow_features(features_dict: dict[str, Any]) -> list[float]:
        feature_keys = sorted(key for key in features_dict.keys() if not str(key).startswith("_"))
        vector = []
        for key in feature_keys:
            value = features_dict.get(key, 0.0)
            try:
                vector.append(float(value))
            except (TypeError, ValueError):
                vector.append(0.0)
        if len(vector) < 80:
            vector.extend([0.0] * (80 - len(vector)))
        return vector[:80]

    def latest_verdicts_for_user(self, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        conn = self._connect()
        if conn is None:
            return []
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT session_id, user_id, source_ip, verdict, confidence, snn_score,
                               lnn_class, xgb_class, behavioral_delta, model_version, timestamp,
                               created_at
                        FROM verdicts
                        WHERE user_id = %s
                        ORDER BY created_at DESC, id DESC
                        LIMIT %s
                        """,
                        (user_id, limit),
                    )
                    rows = cur.fetchall() or []
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def latest_alert_rows(self, limit: int = 50) -> list[dict[str, Any]]:
        conn = self._connect()
        if conn is None:
            return []
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT session_id, user_id, source_ip, verdict, confidence, created_at
                        FROM alerts
                        ORDER BY created_at DESC, id DESC
                        LIMIT %s
                        """,
                        (limit,),
                    )
                    rows = cur.fetchall() or []
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_verdict_by_session(self, session_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        if conn is None:
            return None
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT session_id, user_id, source_ip, verdict, confidence,
                               xgb_class, features, model_version, timestamp
                        FROM verdicts
                        WHERE session_id = %s
                        ORDER BY created_at DESC, id DESC
                        LIMIT 1
                        """,
                        (session_id,),
                    )
                    row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def record_alert_decision(
        self,
        session_id: str,
        decision: str,
        status: str,
        decided_by: str,
        decided_by_roles: list[str],
        notes: str | None,
    ) -> dict[str, Any] | None:
        conn = self._connect()
        if conn is None:
            return None
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO alert_decisions (
                            session_id, decision, status, decided_by, decided_by_roles, notes
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING session_id, decision, status, decided_by, decided_at
                        """,
                        (session_id, decision, status, decided_by, Json(decided_by_roles), notes),
                    )
                    row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def latest_decision_for_session(self, session_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        if conn is None:
            return None
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT session_id, decision, status, decided_by, decided_at
                        FROM alert_decisions
                        WHERE session_id = %s
                        ORDER BY decided_at DESC, id DESC
                        LIMIT 1
                        """,
                        (session_id,),
                    )
                    row = cur.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def write_labeled_training_row(
        self,
        session_id: str,
        features: list[float],
        label: str,
        confidence: float,
        attack_type: str,
        trigger_reason: str,
        metadata: dict[str, Any],
    ) -> bool:
        conn = self._connect()
        if conn is None:
            return False
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO labeled_training_data (
                            session_id, features, label, confidence, attack_type, trigger_reason, metadata, created_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (session_id) DO UPDATE
                        SET features = EXCLUDED.features,
                            label = EXCLUDED.label,
                            confidence = EXCLUDED.confidence,
                            attack_type = EXCLUDED.attack_type,
                            trigger_reason = EXCLUDED.trigger_reason,
                            metadata = EXCLUDED.metadata,
                            created_at = NOW()
                        """,
                        (session_id, Json(features), label, confidence, attack_type, trigger_reason, Json(metadata)),
                    )
            return True
        finally:
            conn.close()


def _new_security_audit_event(
    event_type: str,
    outcome: str,
    *,
    route: str,
    http_method: str | None = None,
    actor_id: str | None = None,
    actor_roles: list[str] | None = None,
    source_ip: str | None = None,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    actor_value = str(actor_id) if actor_id is not None else None
    return {
        "event_id": uuid.uuid4().hex,
        "event_type": event_type,
        "outcome": outcome,
        "actor_id": actor_value[:256] if actor_value else None,
        "actor_roles": sorted({str(role)[:64] for role in (actor_roles or [])}),
        "http_method": http_method,
        "route": route[:512],
        "source_ip": source_ip[:64] if source_ip else None,
        "resource_id": resource_id[:256] if resource_id else None,
        "details": details or {},
    }


def _route_template(app_instance: FastAPI, path: str, method: str) -> str:
    for route in app_instance.router.routes:
        path_regex = getattr(route, "path_regex", None)
        if path_regex is None or path_regex.fullmatch(path) is None:
            continue
        if method == "WEBSOCKET":
            if isinstance(route, WebSocketRoute):
                return str(getattr(route, "path", "/unmatched"))
        elif method in (getattr(route, "methods", None) or set()):
            return str(getattr(route, "path", "/unmatched"))
    return "/unmatched"


def _request_audit_event(
    app_instance: FastAPI,
    scope: dict[str, Any],
    path: str,
    method: str,
    identity: dict[str, Any] | None,
    event_type: str,
    outcome: str,
    *,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    client = scope.get("client")
    source_ip = client[0] if isinstance(client, (tuple, list)) and client else None
    identity = identity or {}
    return _new_security_audit_event(
        event_type,
        outcome,
        route=_route_template(app_instance, path, method),
        http_method=method,
        actor_id=identity.get("sub") or identity.get("user_id"),
        actor_roles=identity.get("roles", []),
        source_ip=source_ip,
        resource_id=resource_id,
        details=details,
    )


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass


manager = ConnectionManager()
portal_state = PortalState()
sandbox_gateway = SandboxGateway(SANDBOX_BASE_URL) if SANDBOX_BASE_URL else None


def _account_for_user(user_id: str) -> dict[str, Any] | None:
    normalized = user_id.strip().lower()
    for account in BANK_ACCOUNTS.values():
        if normalized in {account["email"].lower(), account["user_id"].lower()}:
            return account
    return None


def _display_name_for_user(user_id: str) -> str:
    account = _account_for_user(user_id)
    return account["display_name"] if account else user_id.replace("_", " ").title()


_LOCATION_LABELS: OrderedDict[str, str] = OrderedDict()
_LOCATION_LABELS_LIMIT = 2048


def _fallback_location_label(ip: str) -> str:
    if ip.startswith("185.220."):
        return "TOR exit node"
    return f"External · {ip}"


def _location_label_for_ip(source_ip: str | None) -> str:
    """Resolve a readable origin for an alert, using IPinfo when a token is configured."""
    ip = str(source_ip or "").strip()
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return "Unknown location"
    if address.is_private or address.is_loopback or address.is_link_local:
        return "Internal network"
    if ip in _LOCATION_LABELS:
        return _LOCATION_LABELS[ip]

    label = _fallback_location_label(ip)
    if IPINFO_TOKEN:
        try:
            lookup = urllib_request.Request(
                f"https://ipinfo.io/{ip}/json",
                headers={"Authorization": f"Bearer {IPINFO_TOKEN}", "Accept": "application/json"},
            )
            with urllib_request.urlopen(lookup, timeout=2.0) as reply:
                info = json.loads(reply.read().decode("utf-8"))
            place = ", ".join(part for part in (info.get("city"), info.get("country")) if part)
            privacy = info.get("privacy") or {}
            if privacy.get("tor"):
                place = f"{place} · TOR exit" if place else "TOR exit node"
            elif privacy.get("vpn") or privacy.get("proxy"):
                place = f"{place} · anonymizing proxy" if place else "Anonymizing proxy"
            if place:
                label = place
        except (urllib_error.URLError, TimeoutError, ValueError, OSError) as exc:
            log.warning("IPinfo lookup failed for %s: %s", ip, exc)

    _LOCATION_LABELS[ip] = label
    while len(_LOCATION_LABELS) > _LOCATION_LABELS_LIMIT:
        _LOCATION_LABELS.popitem(last=False)
    return label


def _severity_for_verdict(verdict: str, confidence: float) -> str:
    if verdict == "HACKER" or confidence >= 0.8:
        return "high"
    if verdict == "FORGETFUL_USER" or confidence >= 0.5:
        return "medium"
    return "low"


def _message_for_verdict(verdict: dict[str, Any]) -> str:
    if verdict.get("verdict") == "HACKER":
        return f"{verdict.get('xgb_class', 'Threat')} indicators triggered a sandbox-worthy decision."
    if verdict.get("verdict") == "FORGETFUL_USER":
        return "Behavior drift exceeded the normal-user baseline but stayed below hard attacker thresholds."
    return "Session aligned with the stored user profile and passed ensemble checks."


_SHAP_EXPLAINER_CACHE: dict[str, Any] = {"model_id": None, "explainer": None}


def _feature_vector_and_names_for_verdict(verdict: dict[str, Any]) -> tuple[list[float], list[str]]:
    feature_names = list(runtime.engine.feature_names) if "runtime" in globals() and runtime.engine.feature_names else None
    if not feature_names:
        feature_names = [f"feature_{index}" for index in range(80)]

    raw_features = verdict.get("features")
    if isinstance(raw_features, list) and raw_features:
        vector = [float(value) for value in raw_features[:80]]
    else:
        features_dict = verdict.get("features_dict")
        if isinstance(features_dict, dict):
            vector = VerdictRepository._ordered_flow_features(features_dict)
        else:
            vector = [0.0] * 80
    if len(vector) < 80:
        vector.extend([0.0] * (80 - len(vector)))
    return vector[:80], feature_names[:80]


def _shap_top_features(
    feature_vector: list[float],
    feature_names: list[str],
    predicted_class_index: int,
    top_n: int = 5,
) -> list[dict[str, Any]] | None:
    xgb_wrapper = runtime.engine.xgb_model if "runtime" in globals() else None
    model = getattr(xgb_wrapper, "model", None)
    if model is None or not hasattr(model, "get_booster"):
        return None
    try:
        import shap
    except ImportError:
        return None

    mapped_vector = feature_vector
    feature_bridge = getattr(xgb_wrapper, "feature_bridge", None)
    if feature_bridge is not None:
        try:
            mapped_vector = list(feature_bridge.map_vector(np.asarray(feature_vector, dtype=np.float32)))
        except Exception as exc:
            log.warning("SHAP legacy feature mapping failed, using raw features: %s", exc)

    model_identity = id(model)
    if _SHAP_EXPLAINER_CACHE.get("model_id") != model_identity:
        try:
            _SHAP_EXPLAINER_CACHE["explainer"] = shap.TreeExplainer(model)
            _SHAP_EXPLAINER_CACHE["model_id"] = model_identity
        except Exception as exc:
            log.warning("Could not build a SHAP explainer for the active XGBoost model: %s", exc)
            return None
    explainer = _SHAP_EXPLAINER_CACHE["explainer"]

    try:
        array = np.asarray([mapped_vector], dtype=np.float32)
        raw_shap_values = explainer.shap_values(array)
        if isinstance(raw_shap_values, list):
            class_index = min(predicted_class_index, len(raw_shap_values) - 1)
            class_values = np.asarray(raw_shap_values[class_index])[0]
        else:
            raw_array = np.asarray(raw_shap_values)
            if raw_array.ndim == 3:
                class_index = min(predicted_class_index, raw_array.shape[2] - 1)
                class_values = raw_array[0, :, class_index]
            else:
                class_values = raw_array[0]
    except Exception as exc:
        log.warning("SHAP computation failed for the active XGBoost model: %s", exc)
        return None

    ranked = sorted(
        zip(feature_names, feature_vector, (float(v) for v in class_values.tolist())),
        key=lambda item: abs(item[2]),
        reverse=True,
    )[:top_n]
    return [{"feature": name, "value": float(value), "impact": impact} for name, value, impact in ranked]


def _fallback_top_features(feature_vector: list[float], feature_names: list[str], top_n: int = 5) -> list[dict[str, Any]]:
    ranked = sorted(zip(feature_names, feature_vector), key=lambda item: abs(item[1]), reverse=True)[:top_n]
    return [{"feature": name, "value": float(value), "impact": 0.0} for name, value in ranked]


def _explanation_for_verdict(verdict: dict[str, Any]) -> dict[str, Any]:
    feature_vector, feature_names = _feature_vector_and_names_for_verdict(verdict)
    xgb_class = str(verdict.get("xgb_class") or "OTHER").strip().upper()
    predicted_class_index = TRAINING_CLASS_NAMES.index(xgb_class) if xgb_class in TRAINING_CLASS_NAMES else 0

    top_features = _shap_top_features(feature_vector, feature_names, predicted_class_index)
    method = "shap"
    if top_features is None:
        top_features = _fallback_top_features(feature_vector, feature_names)
        method = "feature_magnitude"

    snn_score = float(verdict.get("snn_score", 0.0) or 0.0)
    behavioral_delta = float(verdict.get("behavioral_delta", 0.0) or 0.0)
    lnn_class = str(verdict.get("lnn_class") or "")
    top_feature = top_features[0] if top_features else {"feature": "n/a", "value": 0.0}

    verdict_label = verdict.get("verdict")
    if verdict_label == "HACKER":
        summary = (
            f"{xgb_class.replace('_', ' ').title()} pattern: strongest signal was "
            f"{top_feature['feature']} (value {top_feature['value']:.2f}). "
            f"SNN spike score {snn_score:.2f}, LNN behavioral drift {behavioral_delta:.2f}."
        )
    elif verdict_label == "FORGETFUL_USER":
        summary = (
            f"Behavioral drift {behavioral_delta:.2f} exceeded the normal-user baseline without matching an "
            f"attack pattern; LNN class {lnn_class or 'INCONCLUSIVE'}."
        )
    else:
        summary = f"SNN spike score {snn_score:.2f} and LNN class {lnn_class or 'BENIGN'} stayed within normal range."

    return {
        "summary": summary,
        "topFeatures": top_features,
        "snnSpikeScore": snn_score,
        "lnnBehavioralDelta": behavioral_delta,
        "method": method,
    }


def _dimensions_from_profile(user_id: str) -> list[dict[str, Any]]:
    profile = runtime.engine.behavioral_profiler.load_profile(user_id) if "runtime" in globals() else None
    vector = profile.profile_vector.astype(float).tolist() if profile is not None else [0.0] * len(BEHAVIOR_DIMENSIONS)
    return [
        {"subject": label, "value": round(float(vector[index]) * 100, 2)}
        for index, label in enumerate(BEHAVIOR_DIMENSIONS)
    ]


def _serialize_timestamp(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _format_recent_verdicts(verdicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"{item.get('session_id', 'session')}-{index}",
            "verdict": item.get("verdict", "INCONCLUSIVE"),
            "score": float(item.get("confidence", 0.0)),
            "timestamp": _serialize_timestamp(item.get("created_at") or item.get("timestamp") or time.time()),
        }
        for index, item in enumerate(verdicts)
    ]


def _recent_verdicts_by_user(user_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if "runtime" not in globals():
        return {}
    requested_ids = {user_id for user_id in user_ids if user_id}
    grouped: dict[str, list[dict[str, Any]]] = {}
    with runtime._lock:
        for verdict in runtime._latest_verdicts:
            user_id = str(verdict.get("user_id", "unknown-user"))
            if user_id in requested_ids and len(grouped.setdefault(user_id, [])) < 10:
                grouped[user_id].append(verdict)
    return grouped


def _recent_verdicts_for_user(user_id: str) -> list[dict[str, Any]]:
    return _format_recent_verdicts(_recent_verdicts_by_user([user_id]).get(user_id, []))


def _format_alert_payload(
    verdict: dict[str, Any],
    *,
    recent_verdicts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    user_id = str(verdict.get("user_id", "unknown-user"))
    session_id = str(verdict.get("session_id", f"alert-{uuid.uuid4().hex[:8]}"))
    decision_record = runtime.decision_for_session(session_id) if "runtime" in globals() else None
    return {
        "id": session_id,
        "severity": _severity_for_verdict(str(verdict.get("verdict", "")), float(verdict.get("confidence", 0.0))),
        "verdict": verdict.get("verdict", "INCONCLUSIVE"),
        "message": _message_for_verdict(verdict),
        "timestamp": _serialize_timestamp(verdict.get("created_at") or verdict.get("timestamp") or time.time()),
        "sourceIp": verdict.get("source_ip", "unknown"),
        "userId": user_id,
        "userName": _display_name_for_user(user_id),
        "locationLabel": verdict.get("location_label") or _location_label_for_ip(verdict.get("source_ip")),
        "score": float(verdict.get("confidence", 0.0)),
        "dimensions": _dimensions_from_profile(user_id),
        "recentVerdicts": (
            _recent_verdicts_for_user(user_id)
            if recent_verdicts is None
            else _format_recent_verdicts(recent_verdicts)
        ),
        "modelVersion": verdict.get("model_version", runtime.engine.current_model_version if "runtime" in globals() else "0.0.0"),
        "status": (decision_record or {}).get("status", "new"),
        "decision": (decision_record or {}).get("decision"),
        "explanation": _explanation_for_verdict(verdict),
    }


def _format_alert_payloads(verdicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    user_ids = [str(verdict.get("user_id", "unknown-user")) for verdict in verdicts]
    recent_by_user = _recent_verdicts_by_user(user_ids)
    return [
        _format_alert_payload(
            verdict,
            recent_verdicts=recent_by_user.get(str(verdict.get("user_id", "unknown-user")), []),
        )
        for verdict in verdicts
    ]


def _camelize_verdict(verdict: dict[str, Any]) -> dict[str, Any]:
    session = portal_state.get_session(session_id=str(verdict.get("session_id"))) if verdict.get("session_id") else None
    return {
        **verdict,
        "sessionId": verdict.get("session_id"),
        "userId": verdict.get("user_id"),
        "sourceIp": verdict.get("source_ip"),
        "snnScore": float(verdict.get("snn_score", 0.0)),
        "lnnClass": verdict.get("lnn_class"),
        "xgbClass": verdict.get("xgb_class"),
        "behavioralDelta": float(verdict.get("behavioral_delta", 0.0)),
        "modelVersion": verdict.get("model_version"),
        "sandbox": (
            {
                "active": bool(session and session.sandbox_token),
                "mode": session.sandbox_mode if session else None,
                "sandboxToken": session.sandbox_token if session else None,
                "sandboxPath": "/dashboard" if session and session.sandbox_token else None,
            }
            if session is not None
            else None
        ),
    }


def _build_flow_features(feature_names: list[str], signals: dict[str, float]) -> list[float]:
    vector = [0.05] * len(feature_names)
    index_lookup = {name: index for index, name in enumerate(feature_names)}
    for name, value in signals.items():
        index = index_lookup.get(name)
        if index is None:
            continue
        vector[index] = float(value)
    return vector[:80] + ([0.0] * max(0, 80 - len(vector)))


def _build_portal_session_data(session: PortalSession, user_id: str) -> dict[str, Any]:
    feature_signals = {
        "packet_rate": min(15000.0, 250.0 * max(session.failed_logins, 1)),
        "ack_ratio": 0.05 * min(session.login_attempts, 10),
        "rst_flag_count": float(len(session.web_attacks)),
    }
    if session.transfer_attempts:
        latest_transfer = session.transfer_attempts[-1]
        feature_signals["packet_rate"] = max(feature_signals["packet_rate"], float(latest_transfer["amount"]) / 3.0)
    return {
        "session_id": session.session_id,
        "user_id": user_id,
        "source_ip": session.source_ip,
        "flow_features": _build_flow_features(runtime.engine.feature_names, feature_signals),
        "behavioral_events": list(session.behavioral_events),
        "behavioral_vector": list(session.behavioral_vector),
        "login_attempts": session.login_attempts,
        "all_different_passwords": len(session.login_passwords) > 1,
        "sql_injection_detected": any(SQLI_PATTERN.search(attack.get("payload", "")) for attack in session.web_attacks),
        "timestamp": time.time(),
    }


def _promote_verdict(
    verdict: ThreatVerdict,
    *,
    xgb_class: str,
    confidence: float,
    reason: str,
) -> ThreatVerdict:
    verdict.xgb_class = xgb_class
    verdict.confidence = max(float(verdict.confidence), confidence)
    verdict.snn_score = max(float(verdict.snn_score), min(confidence, 0.99))
    verdict.behavioral_delta = max(float(verdict.behavioral_delta), min(confidence, 0.99))
    verdict.lnn_class = xgb_class if verdict.lnn_class in {"BENIGN", "INCONCLUSIVE"} else verdict.lnn_class
    verdict.verdict = "HACKER" if verdict.confidence >= 0.8 else "FORGETFUL_USER"
    verdict.features_dict["_api_override"] = reason
    return verdict


# An analyst decision moves an alert out of "new". confirm_threat/false_positive are terminal
# judgements (closed); restore_access/escalate keep the alert active under further review.
DECISION_STATUS_BY_DECISION: dict[str, str] = {
    "confirm_threat": "closed",
    "false_positive": "closed",
    "restore_access": "triaged",
    "escalate": "triaged",
}
# Only these two decisions map cleanly onto the fixed CLASS_NAMES taxonomy used for training.
TRAINING_LABEL_DECISIONS = frozenset({"confirm_threat", "false_positive"})


def _coerce_verdict_features_for_training(verdict: dict[str, Any]) -> list[float]:
    raw_features = verdict.get("features")
    if isinstance(raw_features, list) and raw_features:
        vector = [float(value) for value in raw_features[:80]]
        if len(vector) < 80:
            vector.extend([0.0] * (80 - len(vector)))
        return vector
    features_dict = verdict.get("features_dict")
    if isinstance(features_dict, dict):
        return VerdictRepository._ordered_flow_features(features_dict)
    return [0.0] * 80


class InferenceRuntime:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._consumer_thread: threading.Thread | None = None
        self._producer: KafkaProducer | None = None
        self._consumer_connected = False
        self._producer_connected = False
        self._processed_messages = 0
        self._latest_verdicts: deque[dict[str, Any]] = deque(maxlen=LATEST_VERDICTS_LIMIT)
        self._latest_alerts: deque[dict[str, Any]] = deque(maxlen=LATEST_VERDICTS_LIMIT)
        self._alert_decisions: dict[str, dict[str, Any]] = {}
        self.repository = VerdictRepository(DATABASE_URL)
        self._loop = asyncio.get_event_loop()

        self.engine = DecisionEngine(
            model_version_path=MODEL_VERSION_PATH,
            kafka_bootstrap=None,
            publish_callback=self._publish,
            model_poll_interval_seconds=MODEL_POLL_SECONDS,
            start_model_monitor=False,
        )

    def start(self) -> None:
        self.repository.bootstrap()
        self._ensure_producer()
        self.engine.start_model_monitor()
        if self._consumer_thread is None or not self._consumer_thread.is_alive():
            self._stop_event.clear()
            self._consumer_thread = threading.Thread(
                target=self._consume_loop,
                name="inference-kafka-consumer",
                daemon=True,
            )
            self._consumer_thread.start()
        log.info("Inference runtime started.")

    def stop(self) -> None:
        self._stop_event.set()
        self.engine.stop_model_monitor()
        if self._consumer_thread is not None:
            self._consumer_thread.join(timeout=2.0)
        if self._producer is not None:
            self._producer.close(timeout=2)
        self._producer = None
        self._producer_connected = False
        self._consumer_connected = False
        log.info("Inference runtime stopped.")

    def _ensure_producer(self) -> None:
        if self._producer is not None:
            return
        try:
            self._producer = KafkaProducer(
                bootstrap_servers=KAFKA_BOOTSTRAP,
                value_serializer=lambda payload: json.dumps(payload).encode("utf-8"),
                acks="all",
                retries=3,
            )
            self._producer_connected = True
            log.info("Kafka producer connected for verdict publishing.")
        except Exception as exc:
            self._producer = None
            self._producer_connected = False
            log.warning("Kafka producer unavailable; service will stay live without broker publishing: %s", exc)

    def _publish(self, topic: str, payload: dict[str, Any]) -> None:
        with self._lock:
            if topic == VERDICTS_TOPIC:
                self._latest_verdicts.appendleft(payload)
            elif topic == ALERTS_TOPIC:
                self._latest_alerts.appendleft(payload)

        if self._producer is None:
            self._ensure_producer()
        if self._producer is None:
            return

        try:
            self._producer.send(topic, payload)
        except KafkaError as exc:
            self._producer_connected = False
            log.warning("Kafka publish failed for topic %s: %s", topic, exc)

    def _consume_loop(self) -> None:
        while not self._stop_event.is_set():
            consumer = None
            try:
                consumer = KafkaConsumer(
                    INPUT_TOPIC,
                    bootstrap_servers=KAFKA_BOOTSTRAP,
                    group_id=GROUP_ID,
                    value_deserializer=lambda payload: json.loads(payload.decode("utf-8")),
                    auto_offset_reset="latest",
                    enable_auto_commit=True,
                    consumer_timeout_ms=1000,
                )
                self._consumer_connected = True
                log.info("Kafka consumer connected for topic '%s'.", INPUT_TOPIC)

                while not self._stop_event.is_set():
                    for message in consumer:
                        self._handle_feature_message(message.value)
                        if self._stop_event.is_set():
                            break
            except NoBrokersAvailable:
                self._consumer_connected = False
                log.warning("Kafka consumer waiting for broker at %s.", KAFKA_BOOTSTRAP)
                time.sleep(CONSUMER_RETRY_SECONDS)
            except Exception as exc:
                self._consumer_connected = False
                log.exception("Inference consumer loop error: %s", exc)
                time.sleep(CONSUMER_RETRY_SECONDS)
            finally:
                if consumer is not None:
                    consumer.close()

    def _build_session_data(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "session_id": payload.get("flow_id", f"flow-{int(time.time() * 1000)}"),
            "user_id": payload.get("user_id") or payload.get("src_ip", "unknown-user"),
            "source_ip": payload.get("src_ip", "unknown"),
            "flow_features": payload.get("features", []),
            "raw_flow_features": payload.get("raw_features"),
            "timestamp": payload.get("timestamp", time.time()),
            "protocol": payload.get("protocol"),
            "dst_ip": payload.get("dst_ip"),
            "src_port": payload.get("src_port"),
            "dst_port": payload.get("dst_port"),
            "n_packets": payload.get("n_packets"),
            "session_sequence": payload.get("session_sequence"),
            "behavioral_vector": payload.get("behavioral_vector"),
            "behavioral_events": payload.get("behavioral_events"),
            "unique_dst_ports": payload.get("unique_dst_ports"),
            "login_attempts": payload.get("login_attempts"),
            "all_different_passwords": payload.get("all_different_passwords"),
            "sql_injection_detected": payload.get("sql_injection_detected"),
        }

    def _persist_verdict(self, verdict: ThreatVerdict) -> None:
        try:
            self.repository.save_verdict(verdict)
        except Exception as exc:
            log.warning("Failed to persist verdict %s to PostgreSQL: %s", verdict.session_id, exc)

    def _handle_verdict(self, verdict: ThreatVerdict) -> ThreatVerdict:
        self._persist_verdict(verdict)
        canonical_verdict = verdict.to_dict()
        with self._lock:
            prior_items = [item for item in self._latest_verdicts if item.get("session_id") != verdict.session_id]
            self._latest_verdicts.clear()
            self._latest_verdicts.appendleft(canonical_verdict)
            for item in prior_items:
                self._latest_verdicts.append(item)
        if verdict.verdict == "HACKER":
            alert_payload = {
                "session_id": verdict.session_id,
                "user_id": verdict.user_id,
                "source_ip": verdict.source_ip,
                "confidence": verdict.confidence,
                "verdict": verdict.verdict,
                "timestamp": verdict.timestamp,
                "model_version": verdict.model_version,
                "xgb_class": verdict.xgb_class,
            }
            try:
                self.repository.record_audit_event(
                    _new_security_audit_event(
                        "security.alert_created",
                        "created",
                        route="/internal/detection",
                        http_method="MODEL",
                        source_ip=verdict.source_ip,
                        resource_id=verdict.session_id,
                        details={
                            "confidence": float(verdict.confidence),
                            "model_version": str(verdict.model_version)[:128],
                            "classification": str(verdict.xgb_class)[:64],
                        },
                    )
                )
            except Exception as exc:
                log.error("Security audit write failed for alert event (%s)", type(exc).__name__)
            self._latest_alerts.appendleft(alert_payload)
            # Broadcast to UI
            try:
                if self._loop and self._loop.is_running():
                    self._loop.call_soon_threadsafe(
                        lambda: asyncio.create_task(manager.broadcast(_format_alert_payload(alert_payload)))
                    )
            except Exception as e:
                log.warning("WebSocket broadcast failed: %s", e)
        return verdict

    def _handle_feature_message(self, payload: dict[str, Any]) -> ThreatVerdict:
        session_data = self._build_session_data(payload)
        verdict = self.engine.analyze_session(session_data)
        self._handle_verdict(verdict)
        with self._lock:
            self._processed_messages += 1
        if self._processed_messages % 50 == 0:
            log.info(
                "Processed %d extracted feature messages. Latest verdict=%s confidence=%.3f",
                self._processed_messages,
                verdict.verdict,
                verdict.confidence,
            )
        return verdict

    def analyze_manual(self, session_data: dict[str, Any]) -> ThreatVerdict:
        verdict = self.engine.analyze_session(session_data)
        return self._handle_verdict(verdict)

    def health(self) -> dict[str, Any]:
        latest_verdict = self._latest_verdicts[0] if self._latest_verdicts else None
        return {
            "status": "ok",
            "timestamp": time.time(),
            "kafka_consumer_connected": self._consumer_connected,
            "kafka_producer_connected": self._producer_connected,
            "processed_messages": self._processed_messages,
            "model_version": self.engine.current_model_version,
            "latest_verdict": latest_verdict,
            "database_enabled": bool(DATABASE_URL),
        }

    def latest_verdicts(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._latest_verdicts)[:limit]

    def latest_alerts(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._latest_alerts)[:limit]

    def find_verdicts_for_user(self, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        database_rows = self.repository.latest_verdicts_for_user(user_id, limit=limit)
        if database_rows:
            return database_rows
        with self._lock:
            return [item for item in self._latest_verdicts if item.get("user_id") == user_id][:limit]

    def latest_verdict_for_user(self, user_id: str) -> dict[str, Any] | None:
        verdicts = self.find_verdicts_for_user(user_id, limit=1)
        return verdicts[0] if verdicts else None

    def list_alert_payloads(self, limit: int = 50) -> list[dict[str, Any]]:
        database_rows = self.repository.latest_alert_rows(limit=limit)
        if database_rows:
            return database_rows
        return self.latest_alerts(limit)

    def find_verdict_by_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            for item in self._latest_verdicts:
                if str(item.get("session_id")) == session_id:
                    return dict(item)
            for item in self._latest_alerts:
                if str(item.get("session_id")) == session_id:
                    return dict(item)
        return self.repository.get_verdict_by_session(session_id)

    def decision_for_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            cached = self._alert_decisions.get(session_id)
        if cached is not None:
            return cached
        return self.repository.latest_decision_for_session(session_id)

    def record_decision(
        self,
        session_id: str,
        decision: str,
        actor_id: str,
        actor_roles: list[str],
        notes: str | None,
    ) -> dict[str, Any] | None:
        verdict = self.find_verdict_by_session(session_id)
        if verdict is None:
            return None

        status = DECISION_STATUS_BY_DECISION.get(decision, "triaged")
        decided_at = datetime.now(timezone.utc)

        training_label_written: str | None = None
        if decision in TRAINING_LABEL_DECISIONS:
            if decision == "false_positive":
                label = "BENIGN"
            else:
                candidate_label = str(verdict.get("xgb_class") or "").strip().upper()
                label = candidate_label if candidate_label in TRAINING_CLASS_NAMES else "OTHER"
            features = _coerce_verdict_features_for_training(verdict)
            written = self.repository.write_labeled_training_row(
                session_id,
                features,
                label,
                1.0,
                label,
                f"analyst_decision:{decision}",
                {"decided_by": actor_id, "decision": decision},
            )
            if written:
                training_label_written = label

        self.repository.record_alert_decision(session_id, decision, status, actor_id, actor_roles, notes)
        record = {
            "session_id": session_id,
            "decision": decision,
            "status": status,
            "decided_by": actor_id,
            "decided_at": decided_at,
            "training_label_written": training_label_written,
        }
        with self._lock:
            self._alert_decisions[session_id] = record
        try:
            self.repository.record_audit_event(
                _new_security_audit_event(
                    "security.alert_decision",
                    "succeeded",
                    route="/api/alerts/{session_id}/decision",
                    http_method="POST",
                    actor_id=actor_id,
                    actor_roles=actor_roles,
                    resource_id=session_id,
                    details={
                        "decision": decision,
                        "status": status,
                        "training_label_written": training_label_written,
                    },
                )
            )
        except Exception as exc:
            log.error("Security audit write failed for alert decision (%s)", type(exc).__name__)
        return record


runtime = InferenceRuntime()

RESPONSE_ACTION_ROUTES = frozenset(
    {
        "/api/bank/transfer",
        "/api/bank/honeypot-hit",
        "/api/bank/web-attack-detected",
    }
)
MODEL_RELOAD_ROUTES = frozenset({"/models/reload", "/api/models/reload"})


def _record_security_audit_event(event: dict[str, Any]) -> bool:
    try:
        runtime.repository.record_audit_event(event)
        return True
    except Exception as exc:
        log.error("Security audit write failed for %s (%s)", event.get("event_type"), type(exc).__name__)
        return False


async def _record_http_audit_event(
    request: Request,
    event_type: str,
    outcome: str,
    *,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> bool:
    event = _request_audit_event(
        request.app,
        request.scope,
        request.scope.get("path", "/"),
        request.method,
        getattr(request.state, "identity", None),
        event_type,
        outcome,
        resource_id=resource_id,
        details=details,
    )
    return await asyncio.to_thread(_record_security_audit_event, event)


async def _record_websocket_audit_event(
    websocket: WebSocket,
    event_type: str,
    outcome: str,
    *,
    details: dict[str, Any] | None = None,
) -> bool:
    path = getattr(getattr(websocket, "url", None), "path", "/")
    app_instance = getattr(websocket, "app", app)
    scope = getattr(websocket, "scope", {})
    event = _request_audit_event(
        app_instance,
        scope,
        path,
        "WEBSOCKET",
        getattr(getattr(websocket, "state", None), "identity", None),
        event_type,
        outcome,
        details=details,
    )
    return await asyncio.to_thread(_record_security_audit_event, event)


def _audit_unavailable_response() -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content=ErrorResponse(detail="Security audit service is unavailable.").model_dump(),
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    _validate_startup_configuration()
    runtime.start()
    try:
        yield
    finally:
        runtime.stop()


app = FastAPI(title="NeuroShield Inference Service", version="0.9.0", lifespan=lifespan)

# Add CORS middleware
app.add_middleware(RequestBodyLimitMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
rate_limiter = FixedWindowRateLimiter(API_RATE_LIMIT_PER_MINUTE)


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(_: Request, __: RequestValidationError) -> JSONResponse:
    # Pydantic's default error payload can include rejected input values such as passwords.
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(detail="Request validation failed.").model_dump(),
    )


@app.exception_handler(StarletteHTTPException)
async def safe_http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail if isinstance(exc.detail, str) else "Request could not be completed."
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(detail=detail).model_dump(),
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    log.error(
        "Unhandled API exception on %s %s (%s)",
        request.method,
        request.url.path,
        type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(detail="Internal server error.").model_dump(),
    )


def _api_key_exempt(path: str) -> bool:
    if path in {"/", "/health"}:
        return True
    return APP_ENV in {"local", "test"} and (
        path == "/openapi.json" or path.startswith("/docs") or path.startswith("/redoc")
    )


def _validate_startup_configuration() -> None:
    if APP_ENV not in {"local", "test", "staging", "production"}:
        raise RuntimeError("APP_ENV must be local, test, staging, or production.")

    # Validate mutable settings here too, so startup rejects bad deployment overrides
    # instead of silently treating them as a permissive CORS/proxy configuration.
    if _parse_cors_origins(",".join(ALLOWED_ORIGINS)) != ALLOWED_ORIGINS:
        raise RuntimeError("CORS_ALLOWED_ORIGINS must use canonical origin values.")
    _parse_trusted_proxy_ips(TRUSTED_PROXY_IPS)

    if APP_ENV not in {"staging", "production"}:
        return

    if not OIDC_REQUIRED or not OIDC_ISSUER:
        raise RuntimeError("Staging and production require OIDC_REQUIRED=true and OIDC_ISSUER.")
    if not OIDC_ISSUER.startswith("https://"):
        raise RuntimeError("Staging and production require an HTTPS OIDC_ISSUER.")
    if ENABLE_SIMULATION_API:
        raise RuntimeError("Simulation APIs cannot be enabled in staging or production.")
    parsed_origins = [urlsplit(origin) for origin in ALLOWED_ORIGINS]
    if any(origin.scheme != "https" for origin in parsed_origins):
        raise RuntimeError("Staging and production require explicit HTTPS CORS_ALLOWED_ORIGINS without wildcards.")
    if (
        not DATABASE_URL.startswith(("postgresql://", "postgres://"))
        or "ns_pass" in DATABASE_URL
        or "ns_user" in DATABASE_URL
    ):
        raise RuntimeError("Staging and production require a non-demo DATABASE_URL.")


def _is_simulation_api(path: str) -> bool:
    path = canonical_route_path(path)
    if path in {
        "/behavioral/vectorize",
        "/api/behavioral",
        "/api/behavioral/vectorize",
        "/api/verdicts/current",
        "/api/verdicts/current-session",
    }:
        return True
    return path.startswith(("/api/bank/", "/api/sandbox/", "/api/verdicts/", "/api/profiles/"))


def _versioned_legacy_path(path: str) -> str:
    if path.startswith("/api/") and not path.startswith("/api/v1/"):
        return "/api/v1" + path[len("/api"):]

    exact_aliases = {
        "/analyze": "/api/v1/analyze",
        "/alerts/latest": "/api/v1/alerts/latest",
        "/models/reload": "/api/v1/models/reload",
    }
    if path in exact_aliases:
        return exact_aliases[path]

    prefixes = {
        "/behavioral/vectorize": "/api/v1/behavioral/vectorize",
        "/verdicts/": "/api/v1/verdicts/",
        "/profiles/": "/api/v1/profiles/",
    }
    for legacy_prefix, versioned_prefix in prefixes.items():
        if path.startswith(legacy_prefix):
            return versioned_prefix + path[len(legacy_prefix):]
    return path


def _versioned_legacy_raw_path(path: str, raw_path: bytes) -> bytes:
    prefixes = (
        ("/api/", "/api/v1/"),
        ("/behavioral/vectorize", "/api/v1/behavioral/vectorize"),
        ("/verdicts/", "/api/v1/verdicts/"),
        ("/profiles/", "/api/v1/profiles/"),
    )
    for legacy_prefix, versioned_prefix in prefixes:
        legacy_bytes = legacy_prefix.encode("ascii")
        if path.startswith(legacy_prefix) and raw_path.startswith(legacy_bytes):
            return versioned_prefix.encode("ascii") + raw_path[len(legacy_bytes):]

    exact_aliases = {
        "/analyze": "/api/v1/analyze",
        "/alerts/latest": "/api/v1/alerts/latest",
        "/models/reload": "/api/v1/models/reload",
    }
    for legacy_path, versioned_path in exact_aliases.items():
        legacy_bytes = legacy_path.encode("ascii")
        if path == legacy_path and raw_path.startswith(legacy_bytes):
            return versioned_path.encode("ascii") + raw_path[len(legacy_bytes):]
    return raw_path


def _oidc_config() -> OIDCConfig | None:
    if not OIDC_ISSUER:
        return None
    return OIDCConfig(issuer=OIDC_ISSUER, audience=OIDC_AUDIENCE)


def _current_model_payload() -> dict[str, Any]:
    payload = runtime.engine._read_model_version()
    validation = payload.get("validation_f1", {}) or {}
    version = payload.get("version", runtime.engine.current_model_version)

    def optional_score(name: str) -> float | None:
        value = validation.get(name)
        return None if value is None else float(value)

    return {
        "version": version,
        "versions": [
            {"label": "Primary", "value": str(version)},
            {"label": "SNN", "value": str(payload.get("snn") or "not-loaded")},
            {"label": "LNN", "value": str(payload.get("lnn") or "not-loaded")},
            {"label": "XGBoost", "value": str(payload.get("xgb") or "not-loaded")},
        ],
        "validationF1": [
            {"label": "SNN", "value": optional_score("snn")},
            {"label": "LNN", "value": optional_score("lnn")},
            {"label": "XGBoost", "value": optional_score("xgb")},
        ],
        "lastRetrainedAt": payload.get("timestamp"),
        "activeModels": ["SNN", "LNN", "XGBoost"],
    }


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=path.parent, encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _write_history_snapshot(payload: dict[str, Any]) -> str:
    MODEL_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    version = str(payload.get("version", "0.0.0")).replace("/", "_")
    filename = f"{timestamp}_{version}.json"
    _atomic_write_json(MODEL_HISTORY_DIR / filename, payload)
    return filename


def _latest_history_snapshot() -> tuple[str, dict[str, Any]] | None:
    if not MODEL_HISTORY_DIR.exists():
        return None
    snapshots = sorted(MODEL_HISTORY_DIR.glob("*.json"), reverse=True)
    if not snapshots:
        return None
    latest = snapshots[0]
    return latest.name, json.loads(latest.read_text(encoding="utf-8-sig"))


def _pop_latest_history_snapshot() -> tuple[str, dict[str, Any]] | None:
    found = _latest_history_snapshot()
    if found is None:
        return None
    name, payload = found
    (MODEL_HISTORY_DIR / name).unlink(missing_ok=True)
    return name, payload


def _candidate_manifest_path(candidate_id: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "", candidate_id)
    return MODEL_CANDIDATES_DIR / f"{safe_id}.manifest.json"


def _load_candidate_manifest(candidate_id: str) -> dict[str, Any] | None:
    path = _candidate_manifest_path(candidate_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _save_candidate_manifest(candidate: dict[str, Any]) -> None:
    _atomic_write_json(_candidate_manifest_path(candidate["candidate_id"]), candidate)


def _list_candidate_manifests() -> list[dict[str, Any]]:
    if not MODEL_CANDIDATES_DIR.exists():
        return []
    manifests = []
    for path in MODEL_CANDIDATES_DIR.glob("*.manifest.json"):
        try:
            manifests.append(json.loads(path.read_text(encoding="utf-8-sig")))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Skipping unreadable candidate manifest %s: %s", path, exc)
    manifests.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    return manifests


def _format_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidateId": candidate["candidate_id"],
        "status": candidate["status"],
        "modelKey": candidate["model_key"],
        "baseModelVersion": candidate["base_model_version"],
        "proposedVersion": candidate["proposed_version"],
        "validationF1": float(candidate["validation_f1"]),
        "metrics": candidate.get("metrics", {}),
        "createdAt": candidate["created_at"],
        "promotedAt": candidate.get("promoted_at"),
        "promotedBy": candidate.get("promoted_by"),
        "rejectedAt": candidate.get("rejected_at"),
        "rejectedBy": candidate.get("rejected_by"),
    }


def _actor_from_request(request: Request) -> str:
    identity = getattr(request.state, "identity", None) or {}
    return str(identity.get("username") or identity.get("user_id") or "anonymous-admin")


def _session_snapshot(identifier: str, session_id: str | None, source_ip: str) -> PortalSession:
    session = portal_state.get_session(identifier=identifier, session_id=session_id)
    if session is not None:
        return session
    return portal_state.bind_aliases(identifier, session_id, [identifier])


def _decoy_account(user_id: str, account: dict[str, Any] | None) -> dict[str, Any]:
    """Stable, believable decoy balance for a sandboxed session; never the real one."""
    digest = hashlib.sha256(f"decoy:{user_id}".encode("utf-8")).digest()
    balance = 48_000 + int.from_bytes(digest[:3], "big") % 140_000 + (digest[3] % 100) / 100
    masked = account["account_masked"] if account else f"****{int.from_bytes(digest[4:6], 'big') % 10000:04d}"
    return {"balance": round(balance, 2), "accountMasked": masked}


def _activate_sandbox(response: Response, session: PortalSession, user_id: str, source_ip: str) -> dict[str, Any]:
    if session.sandbox_token:
        # Already diverted: keep the attacker in the same decoy session.
        return {
            "active": True,
            "mode": session.sandbox_mode or "placeholder",
            "sandboxToken": session.sandbox_token,
            "sandboxPath": "/dashboard",
        }
    mode = "placeholder"
    sandbox_token = f"sbx-placeholder-{uuid.uuid4().hex[:12]}"
    if sandbox_gateway is not None:
        try:
            payload = sandbox_gateway.create_session(session.session_id, user_id, source_ip)
            sandbox_token = str(payload.get("sandbox_token", sandbox_token))
            mode = "live"
        except RuntimeError as exc:
            log.warning("%s", exc)
    portal_state.attach_sandbox(session.session_id, sandbox_token, mode)
    response.set_cookie(
        "sandbox_token",
        sandbox_token,
        httponly=True,
        samesite="lax",
        max_age=SANDBOX_TIMEOUT_SECONDS,
    )
    response.headers["X-Sandbox-Token"] = sandbox_token
    return {
        "active": True,
        "mode": mode,
        "sandboxToken": sandbox_token,
        "sandboxPath": "/dashboard",
    }


def _run_portal_analysis(session: PortalSession, user_id: str) -> ThreatVerdict:
    verdict = runtime.engine.analyze_session(_build_portal_session_data(session, user_id))
    if session.honeypot_hits:
        verdict = _promote_verdict(verdict, xgb_class="BOT", confidence=0.99, reason="HONEYPOT_TRIGGER")
    elif session.web_attacks:
        verdict = _promote_verdict(verdict, xgb_class="WEB_ATTACK", confidence=0.97, reason="WEB_ATTACK_REPORT")
    elif session.failed_logins >= 5 and len(session.login_passwords) > 1:
        verdict = _promote_verdict(verdict, xgb_class="BRUTE_FORCE", confidence=0.93, reason="BRUTE_FORCE_PATTERN")
    elif 2 <= session.failed_logins < 5:
        verdict = _promote_verdict(verdict, xgb_class="OTHER", confidence=0.58, reason="LOGIN_RECOVERY_PATTERN")
    elif session.transfer_attempts and float(session.transfer_attempts[-1]["amount"]) >= 10000:
        verdict = _promote_verdict(verdict, xgb_class="OTHER", confidence=0.65, reason="TRANSFER_HEAT")

    final_verdict = runtime._handle_verdict(verdict)
    with runtime._lock:
        runtime._processed_messages += 1
    portal_state.set_verdict(session.session_id, final_verdict.to_dict())
    return final_verdict


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    requested_path = request.scope["path"]
    versioned_path = _versioned_legacy_path(requested_path)
    if versioned_path != requested_path:
        # Keep the pre-versioned local pilot URLs working while making /api/v1
        # the canonical route surface and the path exposed by OpenAPI.
        request.scope["path"] = versioned_path
        request.scope["raw_path"] = _versioned_legacy_raw_path(
            requested_path,
            request.scope.get("raw_path", b""),
        )

    canonical_path = request.scope["path"]
    if request.method == "OPTIONS":
        return await call_next(request)

    if not _api_key_exempt(canonical_path):
        client_host = request.client.host if request.client is not None else "unknown"
        retry_after = rate_limiter.check(client_host)
        if retry_after is not None:
            return JSONResponse(
                status_code=429,
                content=RateLimitResponse(
                    detail="Rate limit exceeded.",
                    retry_after_seconds=retry_after,
                ).model_dump(),
                headers={"Retry-After": str(retry_after)},
            )

    if not ENABLE_SIMULATION_API and _is_simulation_api(canonical_path):
        return Response(status_code=status.HTTP_404_NOT_FOUND, content="Simulation endpoint is disabled.")

    admin_operation = set(required_roles_for_route(canonical_path, request.method)) == set(MODEL_ADMIN_ROLES)
    if (OIDC_REQUIRED or admin_operation) and not _api_key_exempt(request.url.path):
        oidc = _oidc_config()
        if oidc is None:
            await _record_http_audit_event(
                request,
                "security.authentication",
                "denied",
                details={"reason": "issuer_unconfigured"},
            )
            return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content="OIDC is required but no issuer is configured.")
        try:
            request.state.identity = _authorize_bearer(
                request.headers.get("authorization", ""),
                oidc,
                canonical_path,
                request.method,
            )
        except OIDCValidationError as exc:
            await _record_http_audit_event(
                request,
                "security.authentication",
                "denied",
                details={"reason": "token_rejected"},
            )
            return Response(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content=str(exc),
                headers={"WWW-Authenticate": "Bearer"},
            )
        except AuthorizationError as exc:
            request.state.identity = getattr(exc, "claims", None)
            await _record_http_audit_event(
                request,
                "security.authentication",
                "denied",
                details={"reason": "role_denied"},
            )
            return Response(status_code=status.HTTP_403_FORBIDDEN, content=str(exc))
        if not await _record_http_audit_event(
            request,
            "security.authentication",
            "succeeded",
            details={"method": "oidc_bearer"},
        ):
            return _audit_unavailable_response()

    if API_KEY and not _api_key_exempt(canonical_path):
        if request.headers.get("x-api-key") != API_KEY:
            await _record_http_audit_event(
                request,
                "security.authentication",
                "denied",
                details={"reason": "api_key_rejected"},
            )
            return Response(status_code=status.HTTP_401_UNAUTHORIZED, content="Missing or invalid X-API-Key.")
        if not await _record_http_audit_event(
            request,
            "security.authentication",
            "succeeded",
            details={"method": "api_key"},
        ):
            return _audit_unavailable_response()

    policy_path = canonical_route_path(canonical_path)
    is_response_action = policy_path in RESPONSE_ACTION_ROUTES
    is_model_reload = policy_path in MODEL_RELOAD_ROUTES
    if is_response_action or is_model_reload:
        event_type = "security.response_action" if is_response_action else "security.model_reload"
        details = {"simulated": True} if is_response_action else {}
        if not await _record_http_audit_event(request, event_type, "attempted", details=details):
            return _audit_unavailable_response()

    response = await call_next(request)
    if is_response_action:
        await _record_http_audit_event(
            request,
            "security.response_action",
            "succeeded" if response.status_code < 400 else "failed",
            details={"simulated": True, "status_code": response.status_code},
        )
    return response


def _authorize_bearer(authorization: str, oidc: OIDCConfig, path: str, method: str) -> dict[str, Any]:
    scheme, separator, token = authorization.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not separator or not token:
        raise OIDCValidationError("Missing bearer token")
    claims = validate_access_token(token, oidc)
    try:
        return require_roles(claims, set(required_roles_for_route(path, method)))
    except AuthorizationError as exc:
        exc.claims = claims
        raise


async def _authorize_websocket(websocket: WebSocket) -> bool:
    path = websocket.url.path
    if OIDC_REQUIRED and not _api_key_exempt(path):
        oidc = _oidc_config()
        if oidc is None:
            await _record_websocket_audit_event(
                websocket,
                "security.authentication",
                "denied",
                details={"reason": "issuer_unconfigured"},
            )
            await websocket.close(code=1011, reason="OIDC issuer is not configured")
            return False
        try:
            # Browsers cannot set a custom Authorization header on a WebSocket handshake, so
            # the dashboard passes the token as a query parameter instead; prefer a real header
            # when a non-browser client does send one.
            header_value = websocket.headers.get("authorization", "")
            if not header_value:
                query_token = websocket.query_params.get("access_token")
                if query_token:
                    header_value = f"Bearer {query_token}"
            websocket.state.identity = _authorize_bearer(
                header_value,
                oidc,
                path,
                "WEBSOCKET",
            )
        except OIDCValidationError:
            await _record_websocket_audit_event(
                websocket,
                "security.authentication",
                "denied",
                details={"reason": "token_rejected"},
            )
            await websocket.close(code=4401, reason="Authentication required")
            return False
        except AuthorizationError as exc:
            websocket.state.identity = getattr(exc, "claims", None)
            await _record_websocket_audit_event(
                websocket,
                "security.authentication",
                "denied",
                details={"reason": "role_denied"},
            )
            await websocket.close(code=4403, reason="Insufficient role")
            return False
        if not await _record_websocket_audit_event(
            websocket,
            "security.authentication",
            "succeeded",
            details={"method": "oidc_bearer"},
        ):
            await websocket.close(code=1011, reason="Security audit unavailable")
            return False

    if API_KEY and not _api_key_exempt(path) and websocket.headers.get("x-api-key") != API_KEY:
        await _record_websocket_audit_event(
            websocket,
            "security.authentication",
            "denied",
            details={"reason": "api_key_rejected"},
        )
        await websocket.close(code=4401, reason="Missing or invalid X-API-Key")
        return False
    if API_KEY and not _api_key_exempt(path):
        if not await _record_websocket_audit_event(
            websocket,
            "security.authentication",
            "succeeded",
            details={"method": "api_key"},
        ):
            await websocket.close(code=1011, reason="Security audit unavailable")
            return False
    return True


@app.get("/", response_model=RootResponse)
def root() -> dict[str, Any]:
    return {
        "service": "neuroshield-inference",
        "phase": 9,
        "status": "live",
        "input_topic": INPUT_TOPIC,
        "verdicts_topic": VERDICTS_TOPIC,
        "alerts_topic": ALERTS_TOPIC,
    }


@app.get("/health", response_model=HealthResponse)
def health() -> dict[str, Any]:
    return runtime.health()


@app.get("/api/v1/verdicts/latest", response_model=LatestVerdictsResponse)
def get_latest_verdicts(limit: int = Query(default=20, ge=1, le=LATEST_VERDICTS_LIMIT)) -> dict[str, Any]:
    return {"count": min(limit, LATEST_VERDICTS_LIMIT), "items": runtime.latest_verdicts(limit)}


@app.get("/api/v1/alerts/latest", response_model=LatestAlertsResponse)
def get_latest_alerts(limit: int = Query(default=20, ge=1, le=LATEST_VERDICTS_LIMIT)) -> dict[str, Any]:
    return {"count": min(limit, LATEST_VERDICTS_LIMIT), "items": runtime.latest_alerts(limit)}


# --- Analyst API (Frontend Compatibility) ---

@app.get("/api/v1/stats", response_model=StatsResponse)
def get_api_stats() -> dict[str, Any]:
    with runtime._lock:
        hacker_count = sum(1 for v in runtime._latest_verdicts if v.get("verdict") == "HACKER")
        legit_count = sum(1 for v in runtime._latest_verdicts if v.get("verdict") == "LEGITIMATE")
        avg_risk = sum(v.get("confidence", 0) for v in runtime._latest_verdicts) / max(len(runtime._latest_verdicts), 1)

    return {
        "totalTransactions": runtime._processed_messages,
        "hackerDetections": hacker_count,
        "avgRiskScore": round(avg_risk * 100, 2),
        "liveAlerts": len(runtime._latest_alerts),
        "legitimateCount": legit_count,
        "uptimeSeconds": int(time.time() - APP_STARTED_AT),
    }


@app.get("/api/v1/model/version", response_model=ModelVersionResponse)
def get_api_model_version() -> dict[str, Any]:
    return _current_model_payload()


@app.get("/api/v1/alerts", response_model=list[AlertResponse])
def get_api_alerts() -> list[dict[str, Any]]:
    return _format_alert_payloads(runtime.list_alert_payloads(50))


@app.post("/api/v1/alerts/{session_id}/decision", response_model=AlertDecisionResponse)
def submit_alert_decision(session_id: str, payload: AlertDecisionRequest, request: Request) -> dict[str, Any]:
    identity = getattr(request.state, "identity", None) or {}
    actor_id = str(identity.get("username") or identity.get("user_id") or "anonymous-analyst")
    actor_roles = list(identity.get("roles", []))
    record = runtime.record_decision(session_id, payload.decision, actor_id, actor_roles, payload.notes)
    if record is None:
        raise HTTPException(status_code=404, detail="Alert session not found.")
    return {
        "sessionId": record["session_id"],
        "decision": record["decision"],
        "status": record["status"],
        "decidedBy": record["decided_by"],
        "decidedAt": record["decided_at"],
        "trainingLabelWritten": record.get("training_label_written"),
    }


@app.websocket("/api/v1/ws/alerts")
@app.websocket("/ws/alerts")
async def websocket_alerts(websocket: WebSocket):
    if not await _authorize_websocket(websocket):
        return
    await manager.connect(websocket)
    try:
        # Send current backlog first
        backlog = _format_alert_payloads(runtime.list_alert_payloads(10))
        if backlog:
            await websocket.send_json(backlog)
        
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        log.error("WebSocket error: %s", e)
        manager.disconnect(websocket)


@app.post("/api/v1/analyze", response_model=ThreatVerdictResponse)
def analyze(request: SessionAnalyzeRequest) -> dict[str, Any]:
    verdict = runtime.analyze_manual(request.model_dump())
    return verdict.to_dict()


@app.post("/api/v1/behavioral/vectorize", response_model=BehavioralVectorResponse)
def behavioral_vectorize(request: BehavioralVectorRequest) -> dict[str, Any]:
    return {"vector": extract_session_vector(request.events).astype(float).tolist()}


@app.post("/api/v1/behavioral", response_model=BehavioralIngestResponse)
def behavioral_ingest(request: BehavioralIngestRequest) -> dict[str, Any]:
    session = portal_state.record_behavioral(request)
    return {
        "status": "captured",
        "userId": request.user_id,
        "sessionId": session.session_id,
        "eventCount": len(session.behavioral_events),
        "vector": session.behavioral_vector,
    }


@app.get("/api/v1/verdicts/current", response_model=VerdictSnapshotResponse)
@app.get("/api/v1/verdicts/current-session", response_model=VerdictSnapshotResponse)
def get_current_portal_verdict() -> dict[str, Any]:
    current = portal_state.current_verdict()
    if current is None:
        latest = runtime.latest_verdicts(1)
        if not latest:
            return {
                "sessionId": None,
                "verdict": "INCONCLUSIVE",
                "confidence": 0.0,
                "snnScore": 0.0,
                "lnnClass": "INCONCLUSIVE",
                "xgbClass": "INCONCLUSIVE",
                "behavioralDelta": 0.0,
            }
        current = latest[0]
    return _camelize_verdict(current)


@app.get("/api/v1/verdicts/{user_id}", response_model=VerdictSnapshotResponse)
def get_user_verdict(user_id: str) -> dict[str, Any]:
    verdict = runtime.latest_verdict_for_user(user_id)
    if verdict is None:
        raise HTTPException(status_code=404, detail="No verdicts found for user.")
    recent = runtime.find_verdicts_for_user(user_id, limit=10)
    return {
        **_camelize_verdict(verdict),
        "recentVerdicts": _recent_verdicts_for_user(user_id),
        "history": [_camelize_verdict(item) for item in recent],
    }


@app.post("/api/v1/bank/login", response_model=BankLoginResponse)
def bank_login(request: BankLoginRequest, response: Response) -> dict[str, Any]:
    account = BANK_ACCOUNTS.get(request.email.strip().lower())
    authenticated = bool(account and account["password"] == request.password)
    session = portal_state.record_login_attempt(request.email, request.password, request.session_id, request.source_ip, authenticated)

    user_id = account["user_id"] if account else request.email.strip().lower() or "unknown-user"
    aliases = [request.email, user_id]
    session = portal_state.bind_aliases(user_id, session.session_id, aliases)
    verdict = _run_portal_analysis(session, user_id)

    sandbox = None
    if verdict.verdict == "HACKER":
        sandbox = _activate_sandbox(response, session, user_id, request.source_ip)

    payload = {
        "authenticated": authenticated,
        "user_id": user_id,
        "displayName": _display_name_for_user(user_id),
        "sessionId": session.session_id,
        "verdict": verdict.verdict,
        "confidence": verdict.confidence,
        "sandbox": sandbox,
        # A diverted session is shown the normal account page backed by decoy data.
        "next": "/dashboard" if (sandbox or authenticated) else "/login",
    }
    if sandbox:
        payload["account"] = _decoy_account(user_id, account)
    elif account and authenticated:
        payload["account"] = {
            "balance": account["balance"],
            "accountMasked": account["account_masked"],
        }
    if not authenticated and not sandbox:
        payload["error"] = "Invalid credentials."
    return payload


@app.post("/api/v1/bank/transfer", response_model=BankTransferResponse)
def bank_transfer(request: BankTransferRequest, response: Response) -> dict[str, Any]:
    session = portal_state.record_transfer(request.user_id, request.session_id, request.source_ip, request.amount, request.destination, request.memo)
    if request.confirm_routing_number:
        session = portal_state.record_honeypot(request.user_id, session.session_id, request.source_ip, "confirm_routing_number")

    if request.memo and SQLI_PATTERN.search(request.memo):
        session = portal_state.record_web_attack(request.user_id, session.session_id, request.source_ip, "SQLI", request.memo)

    verdict = _run_portal_analysis(session, request.user_id)
    sandbox = None
    if verdict.verdict == "HACKER":
        sandbox = _activate_sandbox(response, session, request.user_id, request.source_ip)

    status = "accepted"
    message = "Transfer authorized"
    if sandbox:
        # The decoy vault confirms the transfer; nothing leaves the sandbox.
        status = "accepted"
    elif verdict.verdict != "LEGITIMATE" or request.amount >= 10000:
        status = "suspicious"
        message = "Transfer pending manual review."

    return {
        "status": status,
        "sessionId": session.session_id,
        "verdict": verdict.verdict,
        "confidence": verdict.confidence,
        "sandbox": sandbox,
        "message": message,
    }


@app.post("/api/v1/bank/honeypot-hit", response_model=BankEventResponse)
def honeypot_hit(request: HoneypotHitRequest, response: Response) -> dict[str, Any]:
    session = portal_state.record_honeypot(request.user_id, request.session_id, request.source_ip, request.source)
    verdict = _run_portal_analysis(session, request.user_id)
    sandbox = _activate_sandbox(response, session, request.user_id, request.source_ip)
    return {
        "status": "captured",
        "sessionId": session.session_id,
        "verdict": verdict.verdict,
        "confidence": verdict.confidence,
        "sandbox": sandbox,
    }


@app.post("/api/v1/bank/web-attack-detected", response_model=BankEventResponse)
def web_attack_detected(request: WebAttackDetectedRequest, response: Response) -> dict[str, Any]:
    session = portal_state.record_web_attack(request.user_id, request.session_id, request.source_ip, request.attack_type, request.payload)
    verdict = _run_portal_analysis(session, request.user_id)
    sandbox = _activate_sandbox(response, session, request.user_id, request.source_ip)
    return {
        "status": "captured",
        "sessionId": session.session_id,
        "verdict": verdict.verdict,
        "confidence": verdict.confidence,
        "sandbox": sandbox,
    }


@app.get("/api/v1/sandbox/{session_id}/replay", response_model=SandboxReplayResponse)
def get_sandbox_replay(session_id: str) -> dict[str, Any]:
    session = portal_state.get_session(session_id=session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Sandbox session not found.")
    actions = portal_state.replay_stub(session_id)
    if session.sandbox_token and sandbox_gateway is not None and session.sandbox_mode == "live":
        # Merge requests captured by the sandbox service with actions taken through the portal decoy.
        try:
            live = sandbox_gateway.replay(session.sandbox_token)
            actions = sorted(
                [*actions, *(live.get("actions") or [])],
                key=lambda item: float(item.get("timestamp") or 0.0),
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            log.warning("%s", exc)
    return {
        "session_id": session_id,
        "sandbox_token": session.sandbox_token,
        "mode": session.sandbox_mode or "placeholder",
        "actions": actions,
    }


@app.post("/api/v1/models/reload", response_model=ModelReloadResponse)
def reload_models(request: Request) -> dict[str, Any]:
    previous_version = str(runtime.engine.current_model_version)[:128]
    try:
        swapped = runtime.engine.check_model_version()
    except Exception as exc:
        event = _request_audit_event(
            request.app,
            request.scope,
            request.scope.get("path", "/"),
            request.method,
            getattr(request.state, "identity", None),
            "security.model_change",
            "failed",
            details={"error_type": type(exc).__name__},
        )
        _record_security_audit_event(event)
        raise
    active_version = str(runtime.engine.current_model_version)[:128]
    event = _request_audit_event(
        request.app,
        request.scope,
        request.scope.get("path", "/"),
        request.method,
        getattr(request.state, "identity", None),
        "security.model_change",
        "changed" if swapped else "unchanged",
        details={
            "previous_version": previous_version,
            "active_version": active_version,
        },
    )
    _record_security_audit_event(event)
    return {
        "reloaded": swapped,
        "active_model_version": active_version,
    }


@app.get("/api/v1/models/candidates", response_model=list[ModelCandidateResponse])
def list_model_candidates() -> list[dict[str, Any]]:
    return [_format_candidate(candidate) for candidate in _list_candidate_manifests()]


@app.post("/api/v1/models/candidates/{candidate_id}/promote", response_model=ModelPromotionResponse)
def promote_model_candidate(candidate_id: str, request: Request) -> dict[str, Any]:
    candidate = _load_candidate_manifest(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    if candidate.get("status") != "pending_approval":
        raise HTTPException(status_code=409, detail=f"Candidate is already {candidate.get('status')}.")

    current_payload = runtime.engine._read_model_version()
    _write_history_snapshot(current_payload)

    new_payload = dict(current_payload)
    new_payload["version"] = candidate["proposed_version"]
    new_payload[candidate["model_key"]] = candidate["artifact_path"]
    validation_f1 = dict(new_payload.get("validation_f1") or {})
    validation_f1[candidate["model_key"]] = candidate["validation_f1"]
    new_payload["validation_f1"] = validation_f1
    new_payload["timestamp"] = datetime.now(timezone.utc).isoformat()
    _atomic_write_json(MODEL_VERSION_PATH, new_payload)

    reloaded = runtime.engine.force_activate_manifest(new_payload)

    actor_id = _actor_from_request(request)
    actor_roles = list((getattr(request.state, "identity", None) or {}).get("roles", []))
    candidate["status"] = "promoted"
    candidate["promoted_at"] = datetime.now(timezone.utc).isoformat()
    candidate["promoted_by"] = actor_id
    _save_candidate_manifest(candidate)

    _record_security_audit_event(
        _new_security_audit_event(
            "security.model_promotion",
            "succeeded",
            route="/api/models/candidates/{candidate_id}/promote",
            http_method="POST",
            actor_id=actor_id,
            actor_roles=actor_roles,
            resource_id=candidate_id,
            details={
                "model_key": candidate["model_key"],
                "new_version": candidate["proposed_version"],
                "reloaded": reloaded,
            },
        )
    )

    return {
        "candidateId": candidate_id,
        "status": "promoted",
        "activeModelVersion": str(runtime.engine.current_model_version),
        "reloaded": reloaded,
    }


@app.post("/api/v1/models/candidates/{candidate_id}/reject", response_model=ModelCandidateResponse)
def reject_model_candidate(candidate_id: str, request: Request) -> dict[str, Any]:
    candidate = _load_candidate_manifest(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found.")
    if candidate.get("status") != "pending_approval":
        raise HTTPException(status_code=409, detail=f"Candidate is already {candidate.get('status')}.")

    actor_id = _actor_from_request(request)
    actor_roles = list((getattr(request.state, "identity", None) or {}).get("roles", []))
    candidate["status"] = "rejected"
    candidate["rejected_at"] = datetime.now(timezone.utc).isoformat()
    candidate["rejected_by"] = actor_id
    _save_candidate_manifest(candidate)

    _record_security_audit_event(
        _new_security_audit_event(
            "security.model_rejection",
            "succeeded",
            route="/api/models/candidates/{candidate_id}/reject",
            http_method="POST",
            actor_id=actor_id,
            actor_roles=actor_roles,
            resource_id=candidate_id,
            details={"model_key": candidate["model_key"]},
        )
    )

    return _format_candidate(candidate)


@app.post("/api/v1/models/rollback", response_model=ModelRollbackResponse)
def rollback_model(request: Request) -> dict[str, Any]:
    snapshot = _pop_latest_history_snapshot()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No previous model version to roll back to.")
    _snapshot_name, restored_payload = snapshot

    _atomic_write_json(MODEL_VERSION_PATH, restored_payload)
    reloaded = runtime.engine.force_activate_manifest(restored_payload)

    actor_id = _actor_from_request(request)
    actor_roles = list((getattr(request.state, "identity", None) or {}).get("roles", []))
    _record_security_audit_event(
        _new_security_audit_event(
            "security.model_rollback",
            "succeeded",
            route="/api/models/rollback",
            http_method="POST",
            actor_id=actor_id,
            actor_roles=actor_roles,
            details={
                "restored_version": str(restored_payload.get("version")),
                "reloaded": reloaded,
            },
        )
    )

    return {
        "restoredVersion": str(restored_payload.get("version")),
        "activeModelVersion": str(runtime.engine.current_model_version),
        "reloaded": reloaded,
    }


@app.get("/api/v1/profiles/{user_id}", response_model=ProfileResponse)
def get_profile(user_id: str) -> dict[str, Any]:
    profile = runtime.engine.behavioral_profiler.load_profile(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile.to_payload()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=HOST,
        port=PORT,
        reload=False,
        proxy_headers=True,
        forwarded_allow_ips=TRUSTED_PROXY_IPS,
    )
