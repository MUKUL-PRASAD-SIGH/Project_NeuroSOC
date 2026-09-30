"""What an SDK sends, and how it becomes a full ``behavior.event`` (schema v1.3).

The SDK sends only what the page or agent knows. The server adds the tenant, the site, schema
and idempotency fields, and hashes network identifiers (IP, /24 block) with a server secret so
raw IPs are never stored by the engine.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .taxonomy import ACTIONS, ENTITY_TYPES, INSTRUCTION_SOURCES, RESULTS, SENSITIVITIES

MAX_CLOCK_SKEW_SECONDS = 300
MAX_TELEMETRY_EVENTS = 2000

Short = Field(min_length=1, max_length=256)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SdkEntity(_Strict):
    id: str = Short
    type: str = "human"

    @field_validator("type")
    @classmethod
    def _type(cls, value: str) -> str:
        if value not in ENTITY_TYPES:
            raise ValueError("unknown entity type")
        return value


class SdkResource(_Strict):
    id: str = Short
    type: str = Field(min_length=1, max_length=64)
    sensitivity: str | None = None

    @field_validator("sensitivity")
    @classmethod
    def _sensitivity(cls, value: str | None) -> str | None:
        if value is not None and value not in SENSITIVITIES:
            raise ValueError("unknown sensitivity")
        return value


class SdkValue(_Strict):
    amount: float = Field(ge=0)
    asset: str | None = Field(default=None, max_length=32)
    destination: str | None = Field(default=None, max_length=256)


class SdkContext(_Strict):
    device_hash: str | None = Field(default=None, max_length=128)
    user_agent_hash: str | None = Field(default=None, max_length=128)
    wallet: str | None = Field(default=None, max_length=128)
    funded_by: str | None = Field(default=None, max_length=128)
    geo: str | None = Field(default=None, max_length=8)
    page: str | None = Field(default=None, max_length=256)
    page_origin: str | None = Field(default=None, max_length=256)


class SdkTelemetryEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str = Field(max_length=16)
    timestamp: float
    key: str | None = Field(default=None, max_length=16)  # a key class ("char", "space", "backspace"), never the key
    x: float | None = None
    y: float | None = None
    page: str | None = Field(default=None, max_length=256)


class SdkTelemetry(_Strict):
    session_vector: list[float] | None = Field(default=None, min_length=20, max_length=20)
    events: list[SdkTelemetryEvent] | None = Field(default=None, max_length=MAX_TELEMETRY_EVENTS)
    event_count: int | None = Field(default=None, ge=0)


class SdkAgent(_Strict):
    tool: str | None = Field(default=None, max_length=128)
    instruction_source: str | None = None
    owner_id: str | None = Field(default=None, max_length=256)

    @field_validator("instruction_source")
    @classmethod
    def _source(cls, value: str | None) -> str | None:
        if value is not None and value not in INSTRUCTION_SOURCES:
            raise ValueError("unknown instruction source")
        return value


class SdkEvent(_Strict):
    event_id: str | None = Field(default=None, max_length=64)
    timestamp: float | None = None
    session_id: str = Field(min_length=8, max_length=128)
    entity: SdkEntity
    action: str
    resource: SdkResource
    result: str = "success"
    value: SdkValue | None = None
    context: SdkContext | None = None
    telemetry: SdkTelemetry | None = None
    agent: SdkAgent | None = None

    @field_validator("action")
    @classmethod
    def _action(cls, value: str) -> str:
        if value not in ACTIONS:
            raise ValueError("action is not in the NeuroSOC taxonomy")
        return value

    @field_validator("result")
    @classmethod
    def _result(cls, value: str) -> str:
        if value not in RESULTS:
            raise ValueError("unknown result")
        return value


class SdkBatch(_Strict):
    events: list[SdkEvent] = Field(min_length=1, max_length=50)


def _keyed_hash(secret: str, tenant: str, value: str) -> str:
    return hmac.new(secret.encode("utf-8"), f"{tenant}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def _ip_prefix(ip: str) -> str | None:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return None
    prefix = 24 if address.version == 4 else 48
    return str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))


def normalize(event: SdkEvent, *, site: dict[str, Any], client_ip: str | None, origin: str | None,
              hash_secret: str, source: Literal["sdk-js", "sdk-py", "extension", "server"]) -> dict[str, Any]:
    tenant = site["tenant_id"]
    now = time.time()
    timestamp = event.timestamp if event.timestamp and abs(event.timestamp - now) <= MAX_CLOCK_SKEW_SECONDS else now
    event_id = event.event_id or str(uuid.uuid4())
    try:
        event_id = str(uuid.UUID(event_id))
    except ValueError:
        event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{site['site_id']}:{event_id}"))

    context = event.context.model_dump(exclude_none=True) if event.context else {}
    if client_ip:
        context["ip_hash"] = _keyed_hash(hash_secret, tenant, client_ip)
        prefix = _ip_prefix(client_ip)
        if prefix:
            context["ip_prefix_hash"] = _keyed_hash(hash_secret, tenant, prefix)
    if origin:
        context["origin"] = origin[:256]

    telemetry = None
    if event.telemetry:
        telemetry = {"event_count": event.telemetry.event_count}
        if event.telemetry.session_vector is not None:
            telemetry["session_vector"] = event.telemetry.session_vector
        elif event.telemetry.events:
            telemetry["events"] = [e.model_dump(exclude_none=True) for e in event.telemetry.events]
            if telemetry["event_count"] is None:
                telemetry["event_count"] = len(event.telemetry.events)

    resource = event.resource.model_dump(exclude_none=True)
    return {
        "schema_version": "1.3",
        "event_type": "behavior.event",
        "event_id": event_id,
        "tenant_id": tenant,
        "timestamp": float(timestamp),
        "source": source,
        "source_id": site["site_id"],
        "correlation_id": None,
        "idempotency_key": f"{site['site_id']}:{event_id}",
        "session_id": event.session_id,
        "entity": event.entity.model_dump(),
        "action": event.action,
        "resource": resource,
        "result": event.result,
        "value": event.value.model_dump() if event.value else None,
        "context": context,
        "telemetry": telemetry,
        "agent": event.agent.model_dump() if event.agent else None,
    }


def schema_view(event: dict[str, Any]) -> dict[str, Any]:
    """The event as published on the ``behavior-events`` topic: telemetry reduced to its vector."""
    telemetry = event.get("telemetry")
    if telemetry and "events" in telemetry:
        telemetry = {"event_count": telemetry.get("event_count")}
    return {**event, "telemetry": telemetry}
