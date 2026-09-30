from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def kafka_client_security_options(
    app_env: str | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build Kafka TLS/SASL options and require them outside local/test."""
    settings = os.environ if env is None else env
    environment = (app_env or settings.get("APP_ENV", "local")).strip().lower()
    protocol = settings.get("KAFKA_SECURITY_PROTOCOL", "PLAINTEXT").strip().upper()
    if protocol not in {"PLAINTEXT", "SASL_SSL"}:
        raise RuntimeError("KAFKA_SECURITY_PROTOCOL must be PLAINTEXT locally or SASL_SSL for shared deployments.")
    if environment in {"staging", "production"} and protocol != "SASL_SSL":
        raise RuntimeError("Staging and production require Kafka SASL_SSL with a verified CA certificate.")
    if protocol == "PLAINTEXT":
        return {"security_protocol": protocol}

    mechanism = settings.get("KAFKA_SASL_MECHANISM", "SCRAM-SHA-512").strip().upper()
    username = settings.get("KAFKA_SASL_USERNAME", "").strip()
    password = settings.get("KAFKA_SASL_PASSWORD", "")
    ca_path = settings.get("KAFKA_SSL_CA_LOCATION", "").strip()
    if mechanism not in {"SCRAM-SHA-256", "SCRAM-SHA-512"}:
        raise RuntimeError("KAFKA_SASL_MECHANISM must be SCRAM-SHA-256 or SCRAM-SHA-512.")
    if not username or not password:
        raise RuntimeError("Kafka SASL username and password are required when SASL_SSL is enabled.")
    if not ca_path or not Path(ca_path).is_file():
        raise RuntimeError("KAFKA_SSL_CA_LOCATION must point to the trusted Kafka CA certificate file.")
    return {
        "security_protocol": protocol,
        "sasl_mechanism": mechanism,
        "sasl_plain_username": username,
        "sasl_plain_password": password,
        "ssl_cafile": ca_path,
    }
