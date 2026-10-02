"""A successful bank-portal login returns the account with its transactions; the rows the repository
produces must satisfy the response model (they once carried extra fields and every login returned HTTP 500)."""
from __future__ import annotations

import datetime
import decimal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "inference-service"))

import main as inference_main  # noqa: E402
from core.novatrust_repository import NovaTrustRepository  # noqa: E402


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, *args, **kwargs):
        pass

    def fetchall(self):
        return [dict(row) for row in self.rows]


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return FakeCursor(self.rows)


def repository_with(rows):
    repository = NovaTrustRepository("postgresql://unused")
    repository._connect = lambda: FakeConnection(rows)   # no database in the unit test
    return repository


ROWS = [
    {"id": "tx-alice-0", "user_id": "alice", "date": datetime.datetime(2026, 9, 30), "description": "Grocery Store", "amount": decimal.Decimal("-15.00")},
    {"id": "tx-alice-1", "user_id": "alice", "date": datetime.datetime(2026, 9, 29), "description": "Payroll", "amount": decimal.Decimal("500.00")},
]


def test_transactions_do_not_carry_the_user_id_and_are_typed_by_sign():
    transactions = repository_with(ROWS).get_transactions("alice")
    assert all("user_id" not in row for row in transactions)
    assert [row["type"] for row in transactions] == ["debit", "credit"]


def test_the_login_response_model_accepts_what_the_repository_returns():
    transactions = repository_with(ROWS).get_transactions("alice")
    summary = inference_main.BankAccountSummaryResponse(balance=12450.0, accountMasked="****4521", transactions=transactions)
    assert [t.id for t in summary.transactions] == ["tx-alice-0", "tx-alice-1"]
    assert summary.transactions[1].type == "credit"
