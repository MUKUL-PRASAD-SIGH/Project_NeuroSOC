from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError


SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "security-event-v1.schema.json"
SCHEMA_V1_1_PATH = Path(__file__).resolve().parents[1] / "schemas" / "security-event-v1.1.schema.json"
SCHEMA_V1_2_PATH = Path(__file__).resolve().parents[1] / "schemas" / "security-event-v1.2.schema.json"


@pytest.fixture
def event_validator():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.fixture
def event_v1_1_validator():
    schema = json.loads(SCHEMA_V1_1_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.fixture
def event_v1_2_validator():
    schema = json.loads(SCHEMA_V1_2_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_v1_schema_accepts_current_ingestion_packet_shape(event_validator):
    event = {
        "schema_version": "1.0",
        "event_type": "network.packet",
        "packet_id": str(uuid4()),
        "timestamp": 1_800_000_000.0,
        "src_ip": "192.0.2.10",
        "dst_ip": "198.51.100.4",
        "src_port": 49152,
        "dst_port": 443,
        "protocol": "TCP",
        "length": 512,
        "flags": {"SYN": True, "ACK": False},
        "ttl": 64,
        "source": "pcap",
        "session_id": None,
        "user_id": None,
        "extra": {},
    }

    event_validator.validate(event)


def test_v1_schema_accepts_current_extracted_flow_shape(event_validator):
    event = {
        "schema_version": "1.0",
        "event_type": "network.flow",
        "flow_id": str(uuid4()),
        "timestamp": 1_800_000_000.0,
        "src_ip": "192.0.2.10",
        "dst_ip": "198.51.100.4",
        "src_port": 49152,
        "dst_port": 443,
        "protocol": "TCP",
        "features": [0.0] * 80,
        "raw_features": [0.0] * 80,
        "n_packets": 4,
    }

    event_validator.validate(event)


def test_v1_schema_rejects_unversioned_and_malformed_flow_events(event_validator):
    with pytest.raises(ValidationError):
        event_validator.validate(
            {
                "event_type": "network.packet",
                "packet_id": str(uuid4()),
                "timestamp": 1_800_000_000.0,
            }
        )

    malformed_flow = {
        "schema_version": "1.0",
        "event_type": "network.flow",
        "flow_id": str(uuid4()),
        "timestamp": 1_800_000_000.0,
        "src_ip": "192.0.2.10",
        "dst_ip": "198.51.100.4",
        "src_port": 49152,
        "dst_port": 443,
        "protocol": "TCP",
        "features": [0.0] * 79,
        "raw_features": [0.0] * 80,
        "n_packets": 4,
    }
    with pytest.raises(ValidationError):
        event_validator.validate(malformed_flow)


def test_v1_1_schema_accepts_identified_packet_and_flow_events(event_v1_1_validator):
    packet_id = str(uuid4())
    packet = {
        "schema_version": "1.1",
        "event_type": "network.packet",
        "packet_id": packet_id,
        "timestamp": 1_800_000_000.0,
        "src_ip": "192.0.2.10",
        "dst_ip": "198.51.100.4",
        "src_port": 49152,
        "dst_port": 443,
        "protocol": "TCP",
        "length": 512,
        "flags": {"SYN": True, "ACK": False},
        "ttl": 64,
        "source": "bank_portal",
        "source_id": "ingestion-service:bank_portal",
        "correlation_id": "session-123",
        "idempotency_key": f"network.packet:{packet_id}",
        "session_id": "session-123",
        "user_id": "demo-user",
        "extra": {},
    }
    event_v1_1_validator.validate(packet)

    flow_id = str(uuid4())
    flow = {
        "schema_version": "1.1",
        "event_type": "network.flow",
        "flow_id": flow_id,
        "timestamp": 1_800_000_000.0,
        "src_ip": "192.0.2.10",
        "dst_ip": "198.51.100.4",
        "src_port": 49152,
        "dst_port": 443,
        "protocol": "TCP",
        "features": [0.0] * 80,
        "raw_features": [0.0] * 80,
        "n_packets": 4,
        "source_id": "ingestion-service:bank_portal",
        "correlation_id": "session-123",
        "idempotency_key": f"network.flow:{flow_id}",
    }
    event_v1_1_validator.validate(flow)


def test_v1_1_schema_requires_identifiers_and_defers_tenant_id(event_v1_1_validator):
    packet_id = str(uuid4())
    packet = {
        "schema_version": "1.1",
        "event_type": "network.packet",
        "packet_id": packet_id,
        "timestamp": 1_800_000_000.0,
        "src_ip": "192.0.2.10",
        "dst_ip": "198.51.100.4",
        "src_port": 49152,
        "dst_port": 443,
        "protocol": "TCP",
        "length": 512,
        "flags": {},
        "ttl": 64,
        "source": "pcap",
        "source_id": "ingestion-service:pcap",
        "correlation_id": None,
        "idempotency_key": f"network.packet:{packet_id}",
    }
    event_v1_1_validator.validate(packet)

    packet.pop("idempotency_key")
    with pytest.raises(ValidationError):
        event_v1_1_validator.validate(packet)
    packet["idempotency_key"] = f"network.packet:{packet_id}"
    packet["tenant_id"] = "future-field"
    with pytest.raises(ValidationError):
        event_v1_1_validator.validate(packet)


def test_v1_2_events_require_a_valid_tenant_id(event_v1_2_validator):
    packet_id = str(uuid4())
    packet = {
        "schema_version": "1.2",
        "event_type": "network.packet",
        "tenant_id": "acme-prod",
        "packet_id": packet_id,
        "timestamp": 1_800_000_000.0,
        "src_ip": "192.0.2.10",
        "dst_ip": "198.51.100.4",
        "src_port": 49152,
        "dst_port": 443,
        "protocol": "TCP",
        "length": 512,
        "flags": {},
        "ttl": 64,
        "source": "pcap",
        "source_id": "sensor-1:pcap",
        "correlation_id": None,
        "idempotency_key": f"network.packet:{packet_id}",
    }
    event_v1_2_validator.validate(packet)

    packet.pop("tenant_id")
    with pytest.raises(ValidationError):
        event_v1_2_validator.validate(packet)

    packet["tenant_id"] = "other tenant"
    with pytest.raises(ValidationError):
        event_v1_2_validator.validate(packet)
