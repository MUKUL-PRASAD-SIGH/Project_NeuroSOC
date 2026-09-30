from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INFERENCE_DIR = REPO_ROOT / "inference-service"
if str(INFERENCE_DIR) not in sys.path:
    sys.path.insert(0, str(INFERENCE_DIR))

from core.audit_chain import GENESIS_HASH, audit_event_hash, verify_audit_event  # noqa: E402
import main as inference_main  # noqa: E402


def _sample_event() -> dict:
    return {
        "event_id": "audit-1",
        "tenant_id": "tenant-a",
        "event_type": "security.authentication",
        "outcome": "succeeded",
        "actor_id": "analyst-1",
        "actor_roles": ["analyst", "auditor"],
        "http_method": "GET",
        "route": "/api/v1/alerts",
        "source_ip": "192.0.2.12",
        "resource_id": None,
        "details": {"method": "oidc_bearer"},
        "chain_id": "tenant-a",
        "chain_sequence": 1,
        "created_at": datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc),
    }


def test_audit_hash_is_deterministic_and_detects_event_edits():
    event = _sample_event()
    event_hash = audit_event_hash(GENESIS_HASH, event)
    exported = {**event, "previous_hash": GENESIS_HASH, "event_hash": event_hash}

    assert verify_audit_event(GENESIS_HASH, exported)
    assert audit_event_hash(GENESIS_HASH, event) == event_hash
    assert not verify_audit_event(GENESIS_HASH, {**exported, "outcome": "denied"})
    assert not verify_audit_event("f" * 64, exported)


def test_repository_serializes_and_appends_per_tenant_audit_chain():
    previous_hash = "a" * 64
    statements = []
    tenant_contexts = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, parameters=None):
            statements.append((query, parameters))

        def fetchone(self):
            return {"chain_sequence": 7, "event_hash": previous_hash}

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    repository = object.__new__(inference_main.VerdictRepository)

    def connect(tenant_id):
        tenant_contexts.append(tenant_id)
        return FakeConnection()

    repository._connect = connect
    event = _sample_event()
    repository.record_audit_event(event)

    assert tenant_contexts == ["tenant-a"]
    assert "pg_advisory_xact_lock" in statements[0][0]
    insert_query, parameters = statements[-1]
    assert "INSERT INTO security_audit_events" in insert_query
    assert parameters[1:5] == ("tenant-a", "tenant-a", 8, previous_hash)
    chained_event = {
        **event,
        "chain_sequence": 8,
        "previous_hash": previous_hash,
        "created_at": parameters[-1],
    }
    assert parameters[5] == audit_event_hash(previous_hash, chained_event)
    assert verify_audit_event(previous_hash, {**chained_event, "event_hash": parameters[5]})


def test_repository_maps_unattributed_events_to_a_private_chain():
    tenant_contexts = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            pass

        def fetchone(self):
            return None

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    repository = object.__new__(inference_main.VerdictRepository)

    def connect(tenant_id):
        tenant_contexts.append(tenant_id)
        return FakeConnection()

    repository._connect = connect
    repository.record_audit_event({**_sample_event(), "tenant_id": None})
    assert tenant_contexts == ["__unassigned__"]


def test_audit_export_query_is_scoped_and_uses_sequence_cursor():
    prior_hash = "b" * 64
    event = _sample_event()
    event["chain_sequence"] = 2
    event["created_at"] = datetime(2026, 9, 30, 12, 0, 2, tzinfo=timezone.utc)
    event["previous_hash"] = prior_hash
    event["event_hash"] = audit_event_hash(prior_hash, event)
    calls = []
    tenant_contexts = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, parameters=None):
            calls.append((query, parameters))

        def fetchone(self):
            return {"event_hash": prior_hash}

        def fetchall(self):
            return [event]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    repository = object.__new__(inference_main.VerdictRepository)

    def connect(tenant_id):
        tenant_contexts.append(tenant_id)
        return FakeConnection()

    repository._connect = connect
    anchor_hash, events = repository.list_audit_events("tenant-a", after_sequence=1, limit=10)

    assert tenant_contexts == ["tenant-a"]
    assert anchor_hash == prior_hash
    assert events == [event]
    assert calls[0][1] == ("tenant-a", 1)
    assert calls[1][1] == ("tenant-a", 1, 11)
    assert "WHERE tenant_id = %s AND chain_sequence > %s" in calls[1][0]
