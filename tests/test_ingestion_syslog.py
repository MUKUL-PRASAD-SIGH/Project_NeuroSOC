from __future__ import annotations

import importlib.util
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[1]
INGESTION_DIR = REPO_ROOT / "ingestion-service"
sys.path.insert(0, str(INGESTION_DIR))
SCHEMA_V1_1_PATH = REPO_ROOT / "schemas" / "security-event-v1.2.schema.json"


def _load_ingestion_main():
    # Every service in this repo names its entrypoint main.py; importing it as a bare "main"
    # would silently reuse whichever service's "main" module another test file already cached
    # in sys.modules. Load it under a private name instead, matching the pattern used for
    # retraining/feedback-service in the other test files.
    module_name = "neurosoc_ingestion_main_for_tests"
    spec = importlib.util.spec_from_file_location(module_name, INGESTION_DIR / "main.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


ingestion_main = _load_ingestion_main()


def test_data_dir_permission_error_does_not_break_module_usage(monkeypatch):
    def _deny(*args, **kwargs):
        raise PermissionError("permission denied")

    monkeypatch.setattr(ingestion_main.os, "makedirs", _deny)
    assert ingestion_main._ensure_data_dir_exists() is False


@pytest.mark.parametrize(
    ("line", "expected_user", "expected_ip", "expected_port"),
    [
        (
            "<34>Oct  1 22:14:15 host sshd[1234]: Failed password for admin from 203.0.113.7 port 51234 ssh2",
            "admin",
            "203.0.113.7",
            "51234",
        ),
        (
            "<34>1 2026-09-30T22:14:15.003Z host sshd 1234 ID47 - Failed password for invalid user root "
            "from 198.51.100.9 port 4141 ssh2",
            "root",
            "198.51.100.9",
            "4141",
        ),
    ],
)
def test_ssh_auth_failure_pattern_matches_real_sshd_syslog_lines(line, expected_user, expected_ip, expected_port):
    match = ingestion_main.SSH_AUTH_FAILURE_PATTERN.search(line)
    assert match is not None
    assert match.group("user") == expected_user
    assert match.group("ip") == expected_ip
    assert match.group("port") == expected_port


@pytest.mark.parametrize(
    "line",
    [
        "<34>Oct  1 22:14:15 host sshd[1234]: Accepted password for admin from 203.0.113.7 port 51234 ssh2",
        "<30>Oct  1 22:14:15 host CRON[999]: (root) CMD (run-parts /etc/cron.hourly)",
        "",
    ],
)
def test_ssh_auth_failure_pattern_ignores_non_failure_lines(line):
    assert ingestion_main.SSH_AUTH_FAILURE_PATTERN.search(line) is None


def _free_udp_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("0.0.0.0", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def test_syslog_listener_publishes_a_v11_contract_event_for_a_real_udp_packet(monkeypatch):
    test_port = _free_udp_port()
    monkeypatch.setattr(ingestion_main, "SYSLOG_PORT", test_port)

    published = []

    class FakeProducer:
        def send(self, topic, value):
            published.append((topic, value))

    thread = threading.Thread(target=ingestion_main.run_syslog_mode, args=(FakeProducer(),), daemon=True)
    thread.start()
    time.sleep(0.2)  # let the listener bind

    line = (
        "<34>Oct  1 22:14:15 host sshd[1234]: Failed password for invalid user oracle "
        "from 203.0.113.42 port 55123 ssh2"
    ).encode("utf-8")
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sender.sendto(line, ("127.0.0.1", test_port))
    sender.close()

    deadline = time.time() + 2.0
    while not published and time.time() < deadline:
        time.sleep(0.05)

    assert published, "expected the syslog listener to publish a record"
    topic, record = published[0]
    assert topic == ingestion_main.TOPIC
    assert record["src_ip"] == "203.0.113.42"
    assert record["src_port"] == 55123
    assert record["dst_port"] == 22
    assert record["protocol"] == "TCP"
    assert record["source"] == "syslog"
    assert record["user_id"] == "oracle"
    assert record["schema_version"] == "1.2"
    assert record["tenant_id"] == "local"
    assert record["event_type"] == "network.packet"
    assert record["source_id"].endswith(":syslog")
    assert record["extra"]["login_attempts"] == 1

    schema = json.loads(SCHEMA_V1_1_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    assert list(validator.iter_errors(record)) == []
