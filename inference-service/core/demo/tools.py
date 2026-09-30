"""Nova AI's tools. The security boundary lives here:

    User -> Nova AI (planner) -> NeuroSOC guard (Python SDK, over HTTP) -> tool -> ledger

The agent id, the guarded action and the resource are fixed in code. Nothing in an HTTP request, and
nothing a language model says, can choose them. A tool that moves money is wrapped once with
``guard_tool``; both planners (scripted and Claude) call the very same wrapped functions, so there is one
code path to the ledger and it always passes the guard first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from neurosoc import ActionBlocked, NeuroSOC, NeuroSOCError, Verdict  # noqa: E402  (path set up by runtime.py)

from .account import ACCOUNT_ID, Account, InsufficientFunds, TransferNotFound

AGENT_ID = "novatrust-agent"
TREASURY = "treasury"
# A resource the registered agent is NOT authorized to touch; the "unauthorized resource" simulation uses it.
UNAUTHORIZED_RESOURCE = "treasury_cold_storage_vault"
READ_TOOLS = ("get_balance", "get_transactions", "get_portfolio")
GUARDED_TOOLS = ("create_transfer", "cancel_transfer")
TOOL_NAMES = READ_TOOLS + GUARDED_TOOLS


@dataclass
class Step:
    """One tool call and what happened to it: executed, blocked (by policy), unavailable (guard down) or error."""
    tool: str
    args: dict[str, Any]
    status: str
    result: Any = None
    error: str | None = None
    verdict: dict[str, Any] | None = None
    instruction_source: str = "owner"

    def to_dict(self) -> dict[str, Any]:
        return {"tool": self.tool, "args": self.args, "status": self.status, "result": self.result,
                "error": self.error, "verdict": self.verdict, "instruction_source": self.instruction_source}


def summarize(verdict: Verdict) -> dict[str, Any]:
    return {"verdict_id": verdict.verdict_id, "verdict": verdict.verdict, "action": verdict.action,
            "risk": round(verdict.risk, 3), "reasons": list(verdict.reasons),
            "enforced": bool(verdict.raw.get("enforced")), "session_id": verdict.session_id}


class NovaTools:
    """The five tools, bound to one account and one NeuroSOC client for the duration of a request."""

    def __init__(self, account: Account, soc: NeuroSOC, *, session_id: str) -> None:
        """``session_id`` is used as given for every guarded call, so whoever resets a demo session knows
        exactly which NeuroSOC session key to clear."""
        self.account = account
        self.soc = soc
        self.session_id = session_id
        self._seen: list[Verdict] = []
        self._guarded: dict[str, Callable[..., Any]] = {
            "create_transfer": self._guard("create_transfer", self._create_transfer_impl(), "token.transfer", TREASURY,
                                           "high"),
            "cancel_transfer": self._guard("cancel_transfer", self._cancel_transfer_impl(), "agent.tool_call", TREASURY,
                                           "medium"),
        }

    # ── wiring ──────────────────────────────────────────────────────────────
    def _guard(self, name: str, tool: Callable[..., Any], action: str, resource: str,
               sensitivity: str) -> Callable[..., Any]:
        tool.__name__ = name  # the SDK reports tool.__name__ to NeuroSOC, which checks it against the registry
        return self.soc.guard_tool(
            agent_id=AGENT_ID, action=action, resource=resource, resource_type="treasury_account",
            sensitivity=sensitivity, owner_id=ACCOUNT_ID, session_id=self.session_id,
            # Honor the application's mode: a site in Monitor records the decision and lets the call run,
            # a site in Protect stops it. Reaching NeuroSOC failing still fails closed (the SDK default).
            block_only_when_enforced=True, on_verdict=self._seen.append,
        )(tool)

    def _create_transfer_impl(self) -> Callable[..., Any]:
        account = self.account

        def create_transfer(to: str, amount: float, purpose: str = "", instruction_source: str = "owner") -> dict:
            return account.create_transfer(to, amount, purpose, status="pending", origin="agent")

        return create_transfer

    def _cancel_transfer_impl(self) -> Callable[..., Any]:
        account = self.account

        def cancel_transfer(tx_id: str, instruction_source: str = "owner") -> dict:
            return account.cancel_transfer(tx_id)

        return cancel_transfer

    def vault_transfer(self) -> Callable[..., Any]:
        """A transfer tool wired to a resource this agent is not authorized for (simulation only)."""
        account = self.account

        def create_transfer(to: str, amount: float, purpose: str = "", instruction_source: str = "owner") -> dict:
            return account.create_transfer(to, amount, purpose, status="pending", origin="agent")

        return self._guard("create_transfer", create_transfer, "token.transfer", UNAUTHORIZED_RESOURCE, "critical")

    # ── calling ─────────────────────────────────────────────────────────────
    def call(self, name: str, args: dict[str, Any], *, instruction_source: str = "owner",
             tool: Callable[..., Any] | None = None) -> Step:
        """Run one tool and describe the outcome. Blocked and unavailable are results, not exceptions."""
        if name in READ_TOOLS:
            return self._read(name, args)
        guarded = tool or self._guarded.get(name)
        if guarded is None:
            return Step(name, args, "error", error=f"unknown tool {name}", instruction_source=instruction_source)
        self._seen.clear()
        try:
            result = guarded(**args, instruction_source=instruction_source)
        except ActionBlocked as blocked:
            unavailable = blocked.verdict.verdict == "unavailable"
            verdict = summarize(blocked.verdict)
            return Step(name, args, "unavailable" if unavailable else "blocked", verdict=verdict,
                        error=("security service unavailable" if unavailable else "blocked by NeuroSOC"),
                        instruction_source=instruction_source)
        except (InsufficientFunds, TransferNotFound, ValueError) as exc:
            verdict = summarize(self._seen[-1]) if self._seen else None
            return Step(name, args, "error", error=str(exc).strip("'\""), verdict=verdict,
                        instruction_source=instruction_source)
        verdict = summarize(self._seen[-1]) if self._seen else None
        return Step(name, args, "executed", result=result, verdict=verdict, instruction_source=instruction_source)

    def _read(self, name: str, args: dict[str, Any]) -> Step:
        result = {"get_balance": self.account.balance, "get_transactions": lambda: self.account.transactions(
            int(args.get("limit", 5))), "get_portfolio": self.account.portfolio}[name]()
        self._observe(name)
        return Step(name, args, "executed", result=result)

    def _observe(self, name: str) -> None:
        """Best-effort telemetry for read-only tools; they are not guarded, and a NeuroSOC outage must not break them."""
        try:
            self.soc.track(entity_id=AGENT_ID, entity_type="agent", action="agent.tool_call", resource_id=TREASURY,
                           resource_type="treasury_account", tool=name, owner_id=ACCOUNT_ID,
                           instruction_source="owner", session_id=self.session_id)
        except (NeuroSOCError, ValueError):
            pass
