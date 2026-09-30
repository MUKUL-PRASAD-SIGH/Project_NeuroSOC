from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INFERENCE_DIR = REPO_ROOT / "inference-service"
FEATURE_DIR = REPO_ROOT / "feature-service"
sys.path.insert(0, str(INFERENCE_DIR))
sys.path.insert(0, str(FEATURE_DIR))

from core.behavioral.profiler import BehavioralProfiler  # noqa: E402


def _load_inference_module():
    existing = sys.modules.get("main")
    existing_path = getattr(existing, "__file__", None)
    if existing_path and Path(existing_path).resolve() == (INFERENCE_DIR / "main.py").resolve():
        return existing
    module_name = "neurosoc_inference_main_for_tenant_tests"
    spec = importlib.util.spec_from_file_location(module_name, INFERENCE_DIR / "main.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


inference_main = _load_inference_module()
_feature_module = None


def _load_feature_module():
    global _feature_module
    if _feature_module is not None:
        return _feature_module
    module_name = "neurosoc_feature_main_for_tenant_tests"
    spec = importlib.util.spec_from_file_location(module_name, FEATURE_DIR / "main.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    _feature_module = module
    return _feature_module


def test_same_user_profile_is_isolated_by_tenant(tmp_path):
    profiler = BehavioralProfiler(database_url=None, storage_dir=tmp_path)
    tenant_a_vector = np.asarray([1.0] * 20, dtype=np.float32)
    tenant_b_vector = np.asarray([0.25] * 20, dtype=np.float32)

    tenant_a = profiler.update_profile("same-user", tenant_a_vector, "tenant-a")
    assert profiler.load_profile("same-user", "tenant-b") is None

    tenant_b = profiler.update_profile("same-user", tenant_b_vector, "tenant-b")
    assert tenant_a.tenant_id == "tenant-a"
    assert tenant_b.tenant_id == "tenant-b"
    assert not np.array_equal(tenant_a.profile_vector, tenant_b.profile_vector)

    restarted = BehavioralProfiler(database_url=None, storage_dir=tmp_path)
    assert restarted.load_profile("same-user", "tenant-a").tenant_id == "tenant-a"
    assert restarted.load_profile("same-user", "tenant-b").tenant_id == "tenant-b"


def test_feature_flow_keys_include_trusted_tenant():
    feature = _load_feature_module()
    packet = {
        "src_ip": "192.0.2.1",
        "dst_ip": "198.51.100.2",
        "src_port": 12345,
        "dst_port": 443,
        "protocol": "TCP",
        "source_id": "sensor-1",
        "correlation_id": "same-flow",
    }

    key_a = feature._flow_key({**packet, "tenant_id": "tenant-a"})
    key_b = feature._flow_key({**packet, "tenant_id": "tenant-b"})
    assert key_a != key_b
    assert feature.FlowRecord(key_a, 1.0).tenant_id == "tenant-a"
    with pytest.raises(ValueError, match="trusted tenant_id"):
        feature._flow_key(packet)


def test_shared_database_bootstrap_enables_forced_row_policies(monkeypatch):
    statements = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, query, parameters=None):
            statements.append((query, parameters))

        def fetchone(self):
            return {"rolsuper": False, "rolbypassrls": False}

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    repository = inference_main.VerdictRepository("postgresql://fake")
    monkeypatch.setattr(repository, "_connect", lambda *_args: FakeConnection())
    monkeypatch.setattr(inference_main, "APP_ENV", "production")
    repository.bootstrap()

    sql = "\n".join(query for query, _ in statements)
    for table in ("verdicts", "alerts", "security_audit_events", "alert_decisions", "labeled_training_data"):
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in sql
        assert f"CREATE POLICY tenant_isolation ON {table}" in sql
    assert "idx_training_tenant_session" in sql
    assert "DROP CONSTRAINT IF EXISTS labeled_training_data_session_id_key" in sql
