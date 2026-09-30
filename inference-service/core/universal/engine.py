"""The universal behavioral engine: one normalized behavior.event in, one verdict out.

    features + baseline z-scores -> scorer (spike, drift) -> three detectors -> verdict + reasons

The engine is independent of ``core.engine.DecisionEngine`` and the 80-feature network path;
it shares nothing with them except the behavioral signal extractors it imports read-only.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

from . import agent_guard, baseline, explain, farm, features, humanity
from .scorer import Scorer, ZScoreScorer
from .store import get_json, set_json
from .taxonomy import ENGAGEMENT_ACTIONS, INTERACTIVE_ACTIONS, VALUE_ACTIONS

# Verdict -> recommended response, ordered from least to most severe.
RESPONSES = {
    "ok": "allow",
    "review": "step_up",
    "suspected_bot": "shadow",
    "bot_farm": "shadow",
    "agent_anomaly": "pause_agent",
}
SEVERITY = {name: rank for rank, name in enumerate(RESPONSES)}

ENTITY_TTL = 30 * 24 * 3600
SESSION_TTL = 24 * 3600
FLAG_TTL = 7 * 24 * 3600
VERDICT_TTL = 7 * 24 * 3600
RECENT_VERDICTS = 500
HUMANITY_BOT_THRESHOLD = 0.35
REVIEW_THRESHOLD = 0.6
AGENT_PAUSE_THRESHOLD = 0.6
FARM_ACTIONS = ENGAGEMENT_ACTIONS | VALUE_ACTIONS | {"account.create", "wallet.connect"}
LINK_WORDS = {
    "device_hash": "one device",
    "funded_by": "one funding wallet",
    "ip_block_and_input_timing": "one IP block with identical input timing",
}


class UniversalEngine:
    def __init__(self, kv: Any, scorer: Scorer | None = None) -> None:
        self.kv = kv
        self.scorer = scorer or ZScoreScorer()
        # Per-entity read-modify-write of the state document must not interleave within a process.
        self._lock = threading.Lock()

    # ── storage keys ────────────────────────────────────────────────────────
    @staticmethod
    def _entity_key(tenant: str, entity: dict[str, str]) -> str:
        return f"{tenant}:entity:{entity['type']}:{entity['id']}"

    @staticmethod
    def _group_key(tenant: str, entity_type: str) -> str:
        return f"{tenant}:group:{entity_type}"

    # ── main entry point ────────────────────────────────────────────────────
    def process(self, event: dict[str, Any], *, mode: str = "observe") -> dict[str, Any]:
        tenant = event["tenant_id"]
        entity = event["entity"]
        action = event["action"]
        resource = event["resource"]
        context = event.get("context") or {}

        with self._lock:
            entity_key = self._entity_key(tenant, entity)
            state = get_json(self.kv, entity_key) or features.empty_state()
            entity_baseline = get_json(self.kv, entity_key + ":baseline") or baseline.empty()
            group = get_json(self.kv, self._group_key(tenant, entity["type"])) or {
                "baseline": baseline.empty(), "transitions": {}}

            feats = features.compute(state, event, group["transitions"])
            chosen, baseline_source = baseline.choose(entity_baseline, group["baseline"])
            z = baseline.zscores(chosen, feats)

            sequence = [{"ts": e[0], "action": e[1], "result": e[2]} for e in state["events"][-features.SEQUENCE_WINDOW:]]
            model_scores = self.scorer.score(sequence, feats, z)
            spike = float(model_scores.get("spike", 0.0))
            drift = float(model_scores.get("drift", 0.0))

            telemetry = event.get("telemetry") or {}
            vector = humanity.session_vector(telemetry)
            input_count = telemetry.get("event_count") if telemetry else None
            human_score, human_reasons = humanity.score(vector, input_count, action)

            farm.record(self.kv, tenant, entity["id"], resource["id"], context, vector)
            cluster = (farm.cluster(self.kv, tenant, entity["id"], resource["id"])
                       if action in FARM_ACTIONS else {"size": 1, "members": [entity["id"]], "shared": {}})

            agent_risk, agent_reasons = agent_guard.evaluate(event, feats, z)

            verdict, risk, detector_reasons = self._decide(
                entity, action, human_score, human_reasons, cluster, agent_risk, agent_reasons, spike, drift)

            flag_key = f"{tenant}:flag:{entity['type']}:{entity['id']}"
            if SEVERITY[verdict] >= SEVERITY["suspected_bot"]:
                set_json(self.kv, flag_key, {"verdict": verdict, "at": event["timestamp"]}, ttl=FLAG_TTL)
                if verdict == "bot_farm":
                    for member in cluster["members"]:
                        set_json(self.kv, f"{tenant}:flag:{entity['type']}:{member}",
                                 {"verdict": "bot_farm", "at": event["timestamp"]}, ttl=FLAG_TTL)
                    self.kv.sadd(f"{tenant}:res:{resource['id']}:flagged", *cluster["members"])
                else:
                    self.kv.sadd(f"{tenant}:res:{resource['id']}:flagged", entity["id"])
            else:
                prior = get_json(self.kv, flag_key)
                if prior and SEVERITY.get(prior["verdict"], 0) > SEVERITY[verdict]:
                    verdict = prior["verdict"]
                    risk = max(risk, 0.8)
                    detector_reasons = ["account was already flagged: " + prior["verdict"].replace("_", " ")] + detector_reasons

            session_key = f"{tenant}:session:{event['session_id']}"
            previous_session = get_json(self.kv, session_key)
            # Shadow and pause stick to the session; a review is a one-off step-up and does not.
            previous_severity = SEVERITY.get(previous_session["verdict"], 0) if previous_session else 0
            if previous_severity >= SEVERITY["suspected_bot"] and previous_severity > SEVERITY[verdict]:
                verdict = previous_session["verdict"]
                risk = max(risk, float(previous_session.get("risk", 0.0)))
                detector_reasons = ["session was already flagged"] + detector_reasons

            result = {
                "verdict_id": uuid.uuid4().hex,
                "tenant_id": tenant,
                "session_id": event["session_id"],
                "event_id": event["event_id"],
                "entity": dict(entity),
                "event_action": action,
                "resource": dict(resource),
                "value": event.get("value"),
                "verdict": verdict,
                "action": RESPONSES[verdict],
                "enforced": mode == "enforce",
                "risk": round(float(risk), 3),
                "scores": {
                    "humanity": None if human_score is None else round(human_score, 3),
                    "spike": round(spike, 3),
                    "drift": round(drift, 3),
                    "agent_risk": round(agent_risk, 3),
                    "cluster_size": int(cluster["size"]),
                },
                "linked_by": cluster["shared"],
                "reasons": explain.reasons(detector_reasons, feats, z) or ["matches this account's usual behavior"],
                "scorer": getattr(self.scorer, "name", "custom"),
                "baseline": baseline_source,
                "timestamp": event["timestamp"],
            }

            # Learn from the event only after judging it, and never from flagged behavior, so an
            # attacker cannot teach the baseline that abuse is normal.
            if verdict in {"ok", "review"}:
                baseline.update(entity_baseline, feats)
                baseline.update(group["baseline"], feats)
            previous_action = state["events"][-1][1] if state["events"] else None
            features.remember_transition(group["transitions"], previous_action, action)
            features.remember(state, event)
            set_json(self.kv, entity_key, state, ttl=ENTITY_TTL)
            set_json(self.kv, entity_key + ":baseline", entity_baseline, ttl=ENTITY_TTL)
            set_json(self.kv, self._group_key(tenant, entity["type"]), group)

            set_json(self.kv, session_key, {"verdict": verdict, "action": result["action"], "risk": result["risk"],
                                            "reasons": result["reasons"], "verdict_id": result["verdict_id"],
                                            "updated_at": time.time()}, ttl=SESSION_TTL)
            set_json(self.kv, f"{tenant}:verdict:{result['verdict_id']}", result, ttl=VERDICT_TTL)
            self.kv.lpush_trim(f"{tenant}:verdicts", result["verdict_id"], RECENT_VERDICTS)
            self._count_resource(tenant, resource["id"], action, verdict, event.get("value") or {})
        return result

    @staticmethod
    def _decide(entity: dict[str, str], action: str, human_score: float | None, human_reasons: list[str],
                cluster: dict[str, Any], agent_risk: float, agent_reasons: list[str],
                spike: float, drift: float) -> tuple[str, float, list[str]]:
        if agent_risk >= AGENT_PAUSE_THRESHOLD:
            verdict = "agent_anomaly" if entity["type"] == "agent" else "review"
            return verdict, agent_risk, agent_reasons
        if farm.is_farm(cluster):
            shared = ", ".join(f"{LINK_WORDS.get(kind, kind)} ({count})" for kind, count in cluster["shared"].items())
            return "bot_farm", 0.9, [f"{cluster['size']} accounts on this resource are linked by {shared or 'shared traits'}"] + human_reasons
        if human_score is not None and human_score < HUMANITY_BOT_THRESHOLD and action in INTERACTIVE_ACTIONS | ENGAGEMENT_ACTIONS:
            return "suspected_bot", 1.0 - human_score, human_reasons
        anomaly = max(spike, drift, agent_risk, 0.0 if human_score is None else (1.0 - human_score) * 0.6)
        if anomaly >= REVIEW_THRESHOLD:
            return "review", anomaly, agent_reasons + human_reasons
        return "ok", anomaly, []

    def _count_resource(self, tenant: str, resource_id: str, action: str, verdict: str, value: dict[str, Any]) -> None:
        if action != "reward.claim":
            return
        key = f"{tenant}:res:{resource_id}:claims"
        counts = get_json(self.kv, key) or {"paid": 0, "withheld": 0, "amount_withheld": 0.0}
        if RESPONSES[verdict] == "shadow":
            counts["withheld"] += 1
            counts["amount_withheld"] += float(value.get("amount") or 0.0)
        else:
            counts["paid"] += 1
        set_json(self.kv, key, counts, ttl=FLAG_TTL)

    # ── read side for the dashboard and site backends ───────────────────────
    def session_verdict(self, tenant: str, session_id: str) -> dict[str, Any] | None:
        return get_json(self.kv, f"{tenant}:session:{session_id}")

    def verdict(self, tenant: str, verdict_id: str) -> dict[str, Any] | None:
        return get_json(self.kv, f"{tenant}:verdict:{verdict_id}")

    def latest_verdicts(self, tenant: str, limit: int = 50) -> list[dict[str, Any]]:
        out = []
        for verdict_id in self.kv.lrange(f"{tenant}:verdicts", limit):
            item = self.verdict(tenant, verdict_id)
            if item:
                out.append(item)
        return out

    def entity_profile(self, tenant: str, entity_type: str, entity_id: str) -> dict[str, Any] | None:
        key = self._entity_key(tenant, {"type": entity_type, "id": entity_id})
        state = get_json(self.kv, key)
        if state is None:
            return None
        return {
            "entity": {"id": entity_id, "type": entity_type},
            "first_seen": state["first_seen"],
            "event_count": len(state["events"]),
            "recent_events": [{"ts": e[0], "action": e[1], "result": e[2], "target": e[3]} for e in state["events"][-25:]],
            "devices_seen": len(state["seen"]["device"]),
            "resources_seen": len(state["seen"]["resource"]),
            "flag": get_json(self.kv, f"{tenant}:flag:{entity_type}:{entity_id}"),
            "links": sorted(self.kv.smembers(f"{tenant}:links:{entity_id}")),
        }

    def resource_integrity(self, tenant: str, resource_id: str) -> dict[str, Any]:
        participants = self.kv.smembers(f"{tenant}:res:{resource_id}:participants")
        flagged = self.kv.smembers(f"{tenant}:res:{resource_id}:flagged") & participants
        claims = get_json(self.kv, f"{tenant}:res:{resource_id}:claims") or {"paid": 0, "withheld": 0, "amount_withheld": 0.0}
        return {
            "resource_id": resource_id,
            "participants": len(participants),
            "flagged": len(flagged),
            "human": len(participants) - len(flagged),
            "claims": claims,
            "flagged_accounts": sorted(flagged)[:200],
            "human_accounts": sorted(participants - flagged)[:200],
        }

    def override(self, tenant: str, verdict_id: str, decision: str, actor: str | None) -> dict[str, Any] | None:
        """An analyst restores (clears) or confirms a verdict; the outcome becomes a training label."""
        result = self.verdict(tenant, verdict_id)
        if result is None:
            return None
        entity = result["entity"]
        if decision == "restore":
            self.kv.delete(f"{tenant}:flag:{entity['type']}:{entity['id']}")
            self.kv.delete(f"{tenant}:session:{result['session_id']}")
            self.kv.srem(f"{tenant}:res:{result['resource']['id']}:flagged", entity["id"])
        result["override"] = {"decision": decision, "actor": actor, "at": time.time()}
        set_json(self.kv, f"{tenant}:verdict:{verdict_id}", result, ttl=VERDICT_TTL)
        return result
