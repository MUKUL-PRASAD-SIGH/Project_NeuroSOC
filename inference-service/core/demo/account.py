"""The NovaTrust demo account: a small in-memory ledger, one per demo browser session.

All of it is fake data. Transfers go through ``pending`` (funds held, waiting for the user's confirmation
in the chat) to ``settled``, or to ``cancelled`` (funds released).
"""

from __future__ import annotations

import copy
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any

ACCOUNT_ID = "act_alex_novatrust"

INITIAL_ACCOUNT: dict[str, Any] = {
    "account_id": ACCOUNT_ID,
    "user_name": "Alex Chen",
    "email": "alex.chen@novatrust.example",
    "currency": "USD",
    "portfolio_value": 124850.00,
    "available_balance": 18420.00,
    "portfolio_allocation": [
        {"asset": "US Treasury Yield Fund", "value": 42310.00, "allocation": 33.9, "change": "+0.4%"},
        {"asset": "S&P 500 Index ETF", "value": 64120.00, "allocation": 51.4, "change": "+1.8%"},
        {"asset": "USD Cash Reserves", "value": 18420.00, "allocation": 14.7, "change": "0.0%"},
    ],
    "transactions": [
        {"id": "tx_1094", "type": "credit", "counterparty": "Stripe payout #8902", "amount": 4200.00,
         "date": "2026-09-29 14:15", "status": "settled"},
        {"id": "tx_1093", "type": "debit", "counterparty": "AWS Cloud Infrastructure", "amount": 680.00,
         "date": "2026-09-28 09:30", "status": "settled"},
        {"id": "tx_1092", "type": "credit", "counterparty": "Client retainer, Acme Corp", "amount": 9500.00,
         "date": "2026-09-25 11:00", "status": "settled"},
        {"id": "tx_1091", "type": "debit", "counterparty": "Engineering payroll", "amount": 3400.00,
         "date": "2026-09-22 16:45", "status": "settled"},
    ],
}


class InsufficientFunds(ValueError):
    pass


class TransferNotFound(KeyError):
    pass


class Account:
    """One session's ledger. Methods are safe to call from several request threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = copy.deepcopy(INITIAL_ACCOUNT)
        self._next_id = 1100

    # ── reads ───────────────────────────────────────────────────────────────
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._state)

    def balance(self) -> dict[str, Any]:
        with self._lock:
            return {"available_balance": self._state["available_balance"],
                    "portfolio_value": self._state["portfolio_value"], "currency": self._state["currency"]}

    def transactions(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._state["transactions"][:limit])

    def portfolio(self) -> dict[str, Any]:
        with self._lock:
            return {"total_value": self._state["portfolio_value"], "currency": self._state["currency"],
                    "allocations": copy.deepcopy(self._state["portfolio_allocation"])}

    def latest_pending(self) -> dict[str, Any] | None:
        with self._lock:
            return next((copy.deepcopy(t) for t in self._state["transactions"] if t["status"] == "pending"), None)

    # ── writes ──────────────────────────────────────────────────────────────
    def _cash_row(self) -> dict[str, Any]:
        return next(a for a in self._state["portfolio_allocation"] if a["asset"] == "USD Cash Reserves")

    def _sync_cash(self) -> None:
        self._cash_row()["value"] = round(self._state["available_balance"], 2)

    def create_transfer(self, to: str, amount: float, purpose: str = "", *, status: str = "pending",
                        origin: str = "agent") -> dict[str, Any]:
        """Hold ``amount`` and record a transfer (``pending`` until confirmed, or ``settled`` at once)."""
        if amount <= 0:
            raise ValueError("amount must be positive")
        with self._lock:
            if amount > self._state["available_balance"]:
                raise InsufficientFunds(f"available balance is {self._state['available_balance']:,.2f}")
            self._next_id += 1
            tx = {"id": f"tx_{self._next_id}", "type": "debit", "counterparty": to, "amount": round(amount, 2),
                  "purpose": purpose, "origin": origin, "status": status,
                  "date": time.strftime("%Y-%m-%d %H:%M", time.gmtime())}
            self._state["available_balance"] = round(self._state["available_balance"] - amount, 2)
            self._state["portfolio_value"] = round(self._state["portfolio_value"] - amount, 2)
            self._sync_cash()
            self._state["transactions"].insert(0, tx)
            return copy.deepcopy(tx)

    def _find(self, tx_id: str) -> dict[str, Any]:
        tx = next((t for t in self._state["transactions"] if t["id"] == tx_id), None)
        if tx is None:
            raise TransferNotFound(tx_id)
        return tx

    def confirm_transfer(self, tx_id: str) -> dict[str, Any]:
        with self._lock:
            tx = self._find(tx_id)
            if tx["status"] != "pending":
                raise ValueError(f"transfer {tx_id} is {tx['status']}, not pending")
            tx["status"] = "settled"
            return copy.deepcopy(tx)

    def cancel_transfer(self, tx_id: str) -> dict[str, Any]:
        """Only a pending transfer can be cancelled; its held funds are released."""
        with self._lock:
            tx = self._find(tx_id)
            if tx["status"] != "pending":
                raise ValueError(f"transfer {tx_id} is {tx['status']}; only pending transfers can be cancelled")
            tx["status"] = "cancelled"
            self._state["available_balance"] = round(self._state["available_balance"] + tx["amount"], 2)
            self._state["portfolio_value"] = round(self._state["portfolio_value"] + tx["amount"], 2)
            self._sync_cash()
            return copy.deepcopy(tx)


class SessionStore:
    """Per-browser-session accounts: bounded (LRU) and expiring, so a demo left open cannot grow memory."""

    def __init__(self, max_sessions: int = 200, ttl_seconds: float = 2 * 3600) -> None:
        self._lock = threading.Lock()
        self._items: OrderedDict[str, tuple[float, Account]] = OrderedDict()
        self._max = max_sessions
        self._ttl = ttl_seconds

    def get(self, session_key: str) -> Account:
        now = time.monotonic()
        with self._lock:
            for key in [k for k, (seen, _) in self._items.items() if now - seen > self._ttl]:
                del self._items[key]
            entry = self._items.pop(session_key, None)
            account = entry[1] if entry else Account()
            self._items[session_key] = (now, account)
            while len(self._items) > self._max:
                self._items.popitem(last=False)
            return account

    def reset(self, session_key: str) -> Account:
        with self._lock:
            account = Account()
            self._items.pop(session_key, None)
            self._items[session_key] = (time.monotonic(), account)
            return account


def new_session_key() -> str:
    return uuid.uuid4().hex
