from __future__ import annotations

import fnmatch
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "inference-service"))

import main as inference_main  # noqa: E402
from core.simulation_accounts import password_fingerprint  # noqa: E402


class FakeRedis:
    """Minimal in-memory stand-in for the handful of redis-py calls PortalState makes."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def scan_iter(self, match: str):
        for key in list(self.store.keys()):
            if fnmatch.fnmatch(key, match):
                yield key


def test_serialize_deserialize_round_trips_sets_and_all_fields():
    session = inference_main.PortalSession(session_id="s1", user_key="alice", source_ip="1.2.3.4")
    session.known_aliases.update({"alice", "alice@example.com"})
    session.login_passwords.add("hunter2")
    session.failed_logins = 3
    session.honeypot_hits.append({"source": "form", "timestamp": 123.0})
    session.sandbox_token = "sbx-1"

    restored = inference_main._deserialize_portal_session(inference_main._serialize_portal_session(session))

    assert restored.session_id == "s1"
    assert restored.known_aliases == {"alice", "alice@example.com"}
    assert restored.login_passwords == {"hunter2"}
    assert restored.failed_logins == 3
    assert restored.honeypot_hits == [{"source": "form", "timestamp": 123.0}]
    assert restored.sandbox_token == "sbx-1"


def test_portal_state_without_redis_behaves_exactly_as_before():
    state = inference_main.PortalState(redis_client=None)
    session = state.bind_aliases("bob", None, ["bob"])
    assert session.session_id
    assert state.load_from_redis() == 0  # no-op, no crash


def test_session_state_survives_a_simulated_restart():
    """Simulates 'restart the inference-service container mid-session': write through one
    PortalState instance, then load a brand-new instance (as a fresh process would) from the
    same Redis backing and confirm the session and its mutations are still there."""
    fake_redis = FakeRedis()

    before_restart = inference_main.PortalState(redis_client=fake_redis)
    before_restart.record_login_attempt("victim@bank.com", "wrong-pass-1", None, "203.0.113.5", authenticated=False)
    session = before_restart.record_login_attempt(
        "victim@bank.com", "wrong-pass-2", None, "203.0.113.5", authenticated=False
    )
    before_restart.attach_sandbox(session.session_id, "sbx-token-99", "live")

    # A fresh process, same Redis -- this is the "after restart" instance.
    after_restart = inference_main.PortalState(redis_client=fake_redis)
    restored_count = after_restart.load_from_redis()

    assert restored_count == 1
    restored_session = after_restart.get_session(identifier="victim@bank.com")
    assert restored_session is not None
    assert restored_session.failed_logins == 2
    assert restored_session.login_passwords == {password_fingerprint("wrong-pass-1"), password_fingerprint("wrong-pass-2")}
    assert restored_session.sandbox_token == "sbx-token-99"
    assert restored_session.sandbox_mode == "live"


def test_persist_failure_is_logged_and_swallowed(caplog):
    class BrokenRedis:
        def set(self, *_args, **_kwargs):
            raise ConnectionError("redis unreachable")

    state = inference_main.PortalState(redis_client=BrokenRedis())
    # Must not raise even though every persist call fails.
    state.bind_aliases("carol", None, ["carol"])


def test_build_redis_client_returns_none_without_a_configured_url(monkeypatch):
    monkeypatch.setattr(inference_main, "REDIS_URL", "")
    assert inference_main._build_redis_client() is None
