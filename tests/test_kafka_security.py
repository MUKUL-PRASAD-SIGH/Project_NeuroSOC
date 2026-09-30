from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_MODULES = (
    ("inference-service/core/kafka_security.py", "neurosoc_test_inference_kafka_security"),
    ("ingestion-service/kafka_security.py", "neurosoc_test_ingestion_kafka_security"),
    ("feature-service/kafka_security.py", "neurosoc_test_feature_kafka_security"),
    ("feedback-service/kafka_security.py", "neurosoc_test_feedback_kafka_security"),
    ("sandbox-service/kafka_security.py", "neurosoc_test_sandbox_kafka_security"),
)


def _load_security_module(relative_path: str, module_name: str):
    module_path = REPO_ROOT / relative_path
    service_dir = module_path.parent.parent if module_path.parent.name == "core" else module_path.parent
    if str(service_dir) not in sys.path:
        sys.path.insert(0, str(service_dir))
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(("relative_path", "module_name"), SERVICE_MODULES)
def test_local_kafka_security_defaults_to_plaintext(relative_path, module_name):
    module = _load_security_module(relative_path, module_name)
    assert module.kafka_client_security_options("local", {}) == {"security_protocol": "PLAINTEXT"}


@pytest.mark.parametrize(("relative_path", "module_name"), SERVICE_MODULES)
def test_shared_environment_rejects_plaintext(relative_path, module_name):
    module = _load_security_module(relative_path, module_name)
    with pytest.raises(RuntimeError, match="SASL_SSL"):
        module.kafka_client_security_options("production", {})


@pytest.mark.parametrize(("relative_path", "module_name"), SERVICE_MODULES)
def test_shared_environment_requires_credentials_and_ca(relative_path, module_name, tmp_path):
    module = _load_security_module(relative_path, module_name)
    ca_file = tmp_path / "trusted-kafka-ca.pem"
    ca_file.write_text("test CA bundle", encoding="utf-8")
    shared_settings = {
        "KAFKA_SECURITY_PROTOCOL": "SASL_SSL",
        "KAFKA_SASL_MECHANISM": "SCRAM-SHA-512",
        "KAFKA_SASL_USERNAME": "service-user",
        "KAFKA_SASL_PASSWORD": "test-secret",
        "KAFKA_SSL_CA_LOCATION": str(ca_file),
    }
    options = module.kafka_client_security_options("production", shared_settings)
    assert options == {
        "security_protocol": "SASL_SSL",
        "sasl_mechanism": "SCRAM-SHA-512",
        "sasl_plain_username": "service-user",
        "sasl_plain_password": "test-secret",
        "ssl_cafile": str(ca_file),
    }

    with pytest.raises(RuntimeError, match="username and password"):
        module.kafka_client_security_options(
            "production", {**shared_settings, "KAFKA_SASL_PASSWORD": ""}
        )
    with pytest.raises(RuntimeError, match="trusted Kafka CA"):
        module.kafka_client_security_options(
            "production", {**shared_settings, "KAFKA_SSL_CA_LOCATION": str(tmp_path / "missing.pem")}
        )


def test_shared_deployment_requires_preprovisioned_topics():
    module = _load_security_module(
        "ingestion-service/kafka_setup.py", "neurosoc_test_ingestion_kafka_setup"
    )
    assert module.should_skip_runtime_topic_creation("local", "false") is False
    with pytest.raises(RuntimeError, match="provisioned by infrastructure"):
        module.should_skip_runtime_topic_creation("staging", "false")
    assert module.should_skip_runtime_topic_creation("production", "true") is True
