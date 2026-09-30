"""NeuroSOC client for backends and AI agents. Standard library only.

    from neurosoc import NeuroSOC, ActionBlocked

    soc = NeuroSOC(endpoint="http://localhost:8000", secret_key="sk_...")

    # Backend: check a browser session before paying a reward
    if soc.session_verdict(form["neurosoc_session"]).action in ("shadow", "step_up"):
        hold_reward()

    # Agent: every call to this tool is scored before it runs
    @soc.guard_tool(agent_id="flows-agent-1", action="token.transfer", resource="treasury")
    def transfer(to: str, amount: float, instruction_source: str = "owner"): ...
"""

from __future__ import annotations

import functools
import inspect
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

Transport = Callable[[str, str, Optional[dict]], dict]


@dataclass
class Verdict:
    verdict: str
    action: str
    risk: float = 0.0
    reasons: list = field(default_factory=list)
    verdict_id: Optional[str] = None
    session_id: Optional[str] = None
    raw: dict = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.action == "allow"

    @classmethod
    def from_payload(cls, payload: dict) -> "Verdict":
        return cls(
            verdict=str(payload.get("verdict", "unknown")),
            action=str(payload.get("action", "allow")),
            risk=float(payload.get("risk", 0.0) or 0.0),
            reasons=list(payload.get("reasons") or []),
            verdict_id=payload.get("verdict_id"),
            session_id=payload.get("session_id"),
            raw=payload,
        )


class NeuroSOCError(RuntimeError):
    """The NeuroSOC API could not be reached or refused the request."""


class ActionBlocked(RuntimeError):
    """Raised by a guarded tool when NeuroSOC says the action must not run."""

    def __init__(self, verdict: Verdict) -> None:
        self.verdict = verdict
        reasons = "; ".join(verdict.reasons) or verdict.verdict
        super().__init__(f"NeuroSOC blocked this action ({verdict.action}): {reasons}")


class NeuroSOC:
    def __init__(self, endpoint: str, secret_key: str, *, timeout: float = 5.0,
                 transport: Optional[Transport] = None) -> None:
        if not secret_key.startswith("sk_"):
            raise ValueError("Use a secret key (sk_...) on servers and agents; publishable keys belong in browsers.")
        self.endpoint = endpoint.rstrip("/")
        self._key = secret_key
        self._timeout = timeout
        self._transport = transport or self._http

    # ── HTTP ──────────────────────────────────────────────────────────────
    def _http(self, method: str, path: str, body: Optional[dict]) -> dict:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib_request.Request(self.endpoint + path, data=data, method=method, headers={
            "Content-Type": "application/json", "X-NeuroSOC-Key": self._key})
        try:
            with urllib_request.urlopen(req, timeout=self._timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            raise NeuroSOCError(f"NeuroSOC returned HTTP {exc.code} for {path}") from None
        except (urllib_error.URLError, TimeoutError, ValueError) as exc:
            raise NeuroSOCError(f"NeuroSOC is unreachable: {exc}") from None

    # ── events ────────────────────────────────────────────────────────────
    @staticmethod
    def event(*, entity_id: str, action: str, resource_id: str, resource_type: str = "resource",
              entity_type: str = "human", session_id: Optional[str] = None, result: str = "success",
              sensitivity: Optional[str] = None, amount: Optional[float] = None, asset: Optional[str] = None,
              destination: Optional[str] = None, context: Optional[dict] = None,
              tool: Optional[str] = None, instruction_source: Optional[str] = None,
              owner_id: Optional[str] = None) -> dict:
        resource: dict[str, Any] = {"id": resource_id, "type": resource_type}
        if sensitivity:
            resource["sensitivity"] = sensitivity
        event: dict[str, Any] = {
            "event_id": str(uuid.uuid4()),
            "timestamp": time.time(),
            "session_id": session_id or f"srv_{uuid.uuid4().hex}",
            "entity": {"id": entity_id, "type": entity_type},
            "action": action,
            "resource": resource,
            "result": result,
        }
        if amount is not None:
            event["value"] = {"amount": float(amount), "asset": asset, "destination": destination}
        if context:
            event["context"] = {k: str(v) for k, v in context.items() if v is not None}
        if tool or instruction_source or owner_id:
            event["agent"] = {"tool": tool, "instruction_source": instruction_source, "owner_id": owner_id}
        return event

    def track(self, **kwargs: Any) -> Verdict:
        """Record an action from a backend; returns its verdict."""
        body = self._transport("POST", "/api/v1/sdk/events", {"events": [self.event(**kwargs)]})
        return Verdict.from_payload(body["verdicts"][0])

    def guard(self, **kwargs: Any) -> Verdict:
        """Score an action synchronously, before it runs."""
        return Verdict.from_payload(self._transport("POST", "/api/v1/sdk/guard", self.event(**kwargs)))

    def session_verdict(self, session_id: str) -> Verdict:
        """The verdict for a browser session (from the hidden neurosoc_session form field)."""
        safe = urllib_request.quote(str(session_id)[:128], safe="")
        return Verdict.from_payload(self._transport("GET", f"/api/v1/sdk/sessions/{safe}/verdict", None))

    # ── agents ────────────────────────────────────────────────────────────
    def guard_tool(self, *, agent_id: str, action: str = "agent.tool_call", resource: str = "agent-tools",
                   resource_type: str = "tool", sensitivity: Optional[str] = None, owner_id: Optional[str] = None,
                   amount_arg: str = "amount", destination_arg: str = "to",
                   instruction_source_arg: str = "instruction_source", session_id: Optional[str] = None,
                   block_on: tuple = ("pause_agent", "shadow"), fail_open: bool = False,
                   on_verdict: Optional[Callable[[Verdict], None]] = None) -> Callable:
        """Decorate an agent tool so every call is scored by NeuroSOC before it executes.

        The check runs outside the language model: whatever a prompt says, a blocked call raises
        ActionBlocked and the tool body never runs. ``fail_open=False`` (the default) also blocks
        when NeuroSOC cannot be reached, which is the safe choice for tools that move value.
        """
        run_session = session_id or f"agent_{agent_id}_{uuid.uuid4().hex[:12]}"

        def decorate(tool: Callable) -> Callable:
            signature = inspect.signature(tool)

            @functools.wraps(tool)
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                bound = signature.bind_partial(*args, **kwargs)
                bound.apply_defaults()
                values = bound.arguments
                amount = values.get(amount_arg)
                try:
                    verdict = self.guard(
                        entity_id=agent_id, entity_type="agent", action=action, resource_id=resource,
                        resource_type=resource_type, sensitivity=sensitivity, session_id=run_session,
                        amount=float(amount) if amount is not None else None,
                        destination=str(values[destination_arg]) if values.get(destination_arg) is not None else None,
                        tool=tool.__name__, instruction_source=values.get(instruction_source_arg) or "owner",
                        owner_id=owner_id,
                    )
                except NeuroSOCError:
                    if fail_open:
                        return tool(*args, **kwargs)
                    raise ActionBlocked(Verdict(verdict="unavailable", action="pause_agent",
                                                reasons=["NeuroSOC could not be reached; failing closed"])) from None
                if on_verdict is not None:
                    on_verdict(verdict)
                if verdict.action in block_on:
                    raise ActionBlocked(verdict)
                return tool(*args, **kwargs)

            return wrapper

        return decorate
