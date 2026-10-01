from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "inference-service"))

import main as inference_main  # noqa: E402


def test_decoy_transaction_history_is_deterministic_and_plausible():
    first = inference_main._decoy_transaction_base_history("alice")
    second = inference_main._decoy_transaction_base_history("alice")
    assert first == second
    assert len(first) == len(inference_main._DECOY_MERCHANTS)
    descriptions = {item["description"] for item in first}
    assert descriptions.issubset(set(inference_main._DECOY_MERCHANTS))
    # Sorted newest-first.
    dates = [item["date"] for item in first]
    assert dates == sorted(dates, reverse=True)


def test_decoy_transaction_history_differs_across_users():
    alice = inference_main._decoy_transaction_base_history("alice")
    bob = inference_main._decoy_transaction_base_history("bob")
    assert alice != bob


def test_decoy_transactions_for_session_includes_real_transfer_attempts():
    state = inference_main.PortalState()
    session = state.record_transfer("mallory", None, "203.0.113.9", 500.0, "offshore-account", None)

    ledger = inference_main._decoy_transactions_for_session("mallory", session)

    live_entries = [item for item in ledger if item["description"] == "offshore-account"]
    assert len(live_entries) == 1
    assert live_entries[0]["amount"] == -500.0
    assert len(ledger) <= 10


def test_decoy_transactions_for_session_without_a_session_returns_base_history_only():
    ledger = inference_main._decoy_transactions_for_session("carol", None)
    assert ledger == inference_main._decoy_transaction_base_history("carol")


def test_decoy_account_includes_transactions_key():
    account = inference_main._decoy_account("dave", None, None)
    assert "transactions" in account
    assert len(account["transactions"]) > 0


def test_sandbox_gateway_sends_service_token_header(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def read(self):
            return b'{"session_id": "s1", "sandbox_token": "sbx-1"}'

    def fake_urlopen(request, timeout=None):
        captured["headers"] = dict(request.headers)
        return FakeResponse()

    monkeypatch.setattr(inference_main.urllib_request, "urlopen", fake_urlopen)

    gateway = inference_main.SandboxGateway("http://sandbox:8001", service_token="shared-secret")
    gateway.create_session("s1", "attacker", "203.0.113.1")

    assert captured["headers"].get("X-service-token") == "shared-secret"


def test_sandbox_gateway_omits_header_when_no_token_configured(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def read(self):
            return b'{"session_id": "s1", "sandbox_token": "sbx-1"}'

    def fake_urlopen(request, timeout=None):
        captured["headers"] = dict(request.headers)
        return FakeResponse()

    monkeypatch.setattr(inference_main.urllib_request, "urlopen", fake_urlopen)

    gateway = inference_main.SandboxGateway("http://sandbox:8001")
    gateway.create_session("s1", "attacker", "203.0.113.1")

    assert "X-service-token" not in captured["headers"]
