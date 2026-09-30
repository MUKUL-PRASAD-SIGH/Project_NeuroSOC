"""Universal behavioral engine behind the NeuroSOC SDK.

Scores any entity (person, AI agent, wallet, service) on any platform from domain-agnostic
behavior.event records. Separate from, and never calling into, the network ``DecisionEngine``.
Enabled only when ``ENABLE_UNIVERSAL_ENGINE=true``.
"""

from .engine import RESPONSES, UniversalEngine
from .scorer import ZScoreScorer, load_scorer
from .sites import SiteRegistry
from .store import MemoryKV, RedisKV, build_kv

__all__ = ["RESPONSES", "UniversalEngine", "ZScoreScorer", "load_scorer", "SiteRegistry", "MemoryKV", "RedisKV", "build_kv"]
