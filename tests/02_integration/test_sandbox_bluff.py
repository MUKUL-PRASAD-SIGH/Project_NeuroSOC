from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "inference-service"))

import main as inference_main  # noqa: E402


def test_decoy_account_is_deterministic_per_user():
    first = inference_main._decoy_account("alice", None)
    second = inference_main._decoy_account("alice", None)
    assert first == second
    assert 48_000 <= first["balance"] < 188_000


def test_decoy_account_differs_across_users():
    alice = inference_main._decoy_account("alice", None)
    bob = inference_main._decoy_account("bob", None)
    assert alice["balance"] != bob["balance"]
    assert alice["accountMasked"] != bob["accountMasked"]


def test_decoy_account_uses_real_masked_number_when_available():
    account = {"account_masked": "****1234", "balance": 999.0}
    decoy = inference_main._decoy_account("alice", account)
    assert decoy["accountMasked"] == "****1234"
    # Never reveal the real balance through the decoy vault.
    assert decoy["balance"] != account["balance"]


def test_location_label_for_private_ip_is_internal():
    assert inference_main._location_label_for_ip("10.0.0.5") == "Internal network"
    assert inference_main._location_label_for_ip("127.0.0.1") == "Internal network"


def test_location_label_falls_back_without_token(monkeypatch):
    monkeypatch.setattr(inference_main, "IPINFO_TOKEN", "")
    inference_main._LOCATION_LABELS.clear()
    assert inference_main._location_label_for_ip("185.220.101.5") == "TOR exit node"
    assert inference_main._location_label_for_ip("8.8.8.8") == "External · 8.8.8.8"


def test_location_label_handles_garbage_input():
    assert inference_main._location_label_for_ip(None) == "Unknown location"
    assert inference_main._location_label_for_ip("not-an-ip") == "Unknown location"


def test_sandbox_replay_merges_portal_and_live_actions(monkeypatch):
    state = inference_main.PortalState()
    session = state.bind_aliases("carol", None, ["carol"])
    state.attach_sandbox(session.session_id, "sbx-token-1", "live")

    class FakeGateway:
        def replay(self, sandbox_token: str) -> dict[str, object]:
            assert sandbox_token == "sbx-token-1"
            return {"actions": [{"path": "/api/admin", "method": "GET", "timestamp": 999999999.0}]}

    monkeypatch.setattr(inference_main, "portal_state", state)
    monkeypatch.setattr(inference_main, "sandbox_gateway", FakeGateway())

    result = inference_main.get_sandbox_replay(session.session_id)

    assert result["sandbox_token"] == "sbx-token-1"
    assert result["mode"] == "live"
    paths = [action["path"] for action in result["actions"]]
    assert "/api/bank/login" in paths  # portal-recorded sandbox-entry action
    assert "/api/admin" in paths  # live sandbox-service action
    # Actions are sorted by timestamp ascending.
    timestamps = [float(action.get("timestamp") or 0.0) for action in result["actions"]]
    assert timestamps == sorted(timestamps)


def test_sandbox_replay_survives_live_gateway_failure(monkeypatch):
    state = inference_main.PortalState()
    session = state.bind_aliases("dave", None, ["dave"])
    state.attach_sandbox(session.session_id, "sbx-token-2", "live")

    class BrokenGateway:
        def replay(self, sandbox_token: str) -> dict[str, object]:
            raise RuntimeError("sandbox-service unreachable")

    monkeypatch.setattr(inference_main, "portal_state", state)
    monkeypatch.setattr(inference_main, "sandbox_gateway", BrokenGateway())

    result = inference_main.get_sandbox_replay(session.session_id)
    assert result["sandbox_token"] == "sbx-token-2"
    assert any(action["path"] == "/api/bank/login" for action in result["actions"])


def test_sandbox_replay_missing_session_raises_404(monkeypatch):
    state = inference_main.PortalState()
    monkeypatch.setattr(inference_main, "portal_state", state)

    with pytest.raises(inference_main.HTTPException) as exc_info:
        inference_main.get_sandbox_replay("does-not-exist")
    assert exc_info.value.status_code == 404
