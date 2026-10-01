"""The fictional bank-account passwords come from the environment, never from the source."""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "inference-service"))

import core.simulation_accounts as accounts  # noqa: E402


def reload_accounts(monkeypatch, **env):
    for name in ("ALICE", "BOB", "CAROL"):
        monkeypatch.delenv(f"NOVATRUST_DEMO_PASSWORD_{name}", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return importlib.reload(accounts)


def test_password_is_read_from_the_environment(monkeypatch):
    module = reload_accounts(monkeypatch, NOVATRUST_DEMO_PASSWORD_ALICE="from-env-alice", NOVATRUST_DEMO_PASSWORD_BOB="from-env-bob")
    assert module.BANK_ACCOUNTS["normal1@novatrust.com"]["password"] == "from-env-alice"
    assert module.BANK_ACCOUNTS["normal2@novatrust.com"]["password"] == "from-env-bob"


def test_unset_password_is_random_and_different_each_time(monkeypatch):
    first = reload_accounts(monkeypatch).BANK_ACCOUNTS["admin@novatrust.com"]["password"]
    second = reload_accounts(monkeypatch).BANK_ACCOUNTS["admin@novatrust.com"]["password"]
    assert first and second and first != second and len(first) >= 24


def test_repository_seed_accounts_use_the_same_environment_names(monkeypatch):
    reload_accounts(monkeypatch, NOVATRUST_DEMO_PASSWORD_CAROL="from-env-carol")
    import core.novatrust_repository as repository
    repository = importlib.reload(repository)
    by_user = {account["user_id"]: account["password"] for account in repository.INITIAL_ACCOUNTS}
    assert by_user["carol"] == "from-env-carol"
    assert by_user["alice"] != by_user["bob"]  # unset ones are independent random values


def test_project_credential_scanner_finds_nothing_in_production_code():
    result = subprocess.run([sys.executable, str(REPO / "scripts" / "check_production_credential_patterns.py")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_env_example_lists_the_variables_with_placeholders_only():
    text = (REPO / ".env.example").read_text()
    for name in ("ALICE", "BOB", "CAROL"):
        line = next(item for item in text.splitlines() if item.startswith(f"NOVATRUST_DEMO_PASSWORD_{name}="))
        assert line.split("=", 1)[1].startswith("CHANGE_ME"), line
