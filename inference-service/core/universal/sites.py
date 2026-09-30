"""Site registry: every website or agent platform that installs the SDK is a site.

A site belongs to one tenant and holds:
  - a publishable key (``pk_``): safe to put in a page; can only send events and read its config
  - a secret key (``sk_``): server-side only; also reads session verdicts and guards agent actions
  - the origins allowed to send browser events with its publishable key
  - a mode (``observe`` or ``enforce``), its rules file, and webhook targets

Secret keys are stored as SHA-256 digests; the plain value is shown once, at creation.
Sites can be seeded at startup from ``UNIVERSAL_SITES_FILE`` (a JSON list) for local demos.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlsplit

from .store import get_json, set_json

log = logging.getLogger(__name__)

MODES = {"observe", "enforce"}
PRESETS_DIR_CANDIDATES = (
    Path(__file__).resolve().parents[3] / "sdk" / "presets",
    Path("/sdk/presets"),
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_origin(value: str) -> str | None:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname.lower()}{port}"


def load_preset(name: str) -> list[dict[str, Any]]:
    safe = "".join(ch for ch in name if ch.isalnum() or ch in "-_")
    for directory in PRESETS_DIR_CANDIDATES:
        path = directory / f"{safe}.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8")).get("rules", [])
    raise ValueError(f"Unknown rules preset: {name}")


class SiteRegistry:
    def __init__(self, kv: Any) -> None:
        self.kv = kv

    # ── lookups ─────────────────────────────────────────────────────────────
    def get(self, site_id: str) -> dict[str, Any] | None:
        return get_json(self.kv, f"site:{site_id}")

    def by_publishable_key(self, key: str) -> dict[str, Any] | None:
        site_id = self.kv.get(f"sitekey:pk:{key}") if key.startswith("pk_") else None
        return self.get(site_id) if site_id else None

    def by_secret_key(self, key: str) -> dict[str, Any] | None:
        if not key.startswith("sk_"):
            return None
        site_id = self.kv.get(f"sitekey:sk:{_digest(key)}")
        site = self.get(site_id) if site_id else None
        if site and hmac.compare_digest(site["secret_key_digest"], _digest(key)):
            return site
        return None

    def list(self, tenant_id: str) -> list[dict[str, Any]]:
        sites = [self.get(site_id) for site_id in sorted(self.kv.smembers(f"sites:{tenant_id}"))]
        return [self.public_view(site) for site in sites if site]

    def origin_allowed_anywhere(self, origin: str) -> bool:
        canonical = canonical_origin(origin)
        return bool(canonical) and bool(self.kv.smembers(f"origin:{canonical}"))

    @staticmethod
    def origin_allowed(site: dict[str, Any], origin: str | None) -> bool:
        canonical = canonical_origin(origin or "")
        return bool(canonical) and canonical in site.get("allowed_origins", [])

    @staticmethod
    def public_view(site: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in site.items() if key not in {"secret_key_digest", "webhooks"}} | {
            "webhooks": [{"url": hook["url"]} for hook in site.get("webhooks", [])]}

    # ── writes ──────────────────────────────────────────────────────────────
    def _save(self, site: dict[str, Any]) -> None:
        set_json(self.kv, f"site:{site['site_id']}", site)
        self.kv.sadd(f"sites:{site['tenant_id']}", site["site_id"])
        for origin in site.get("allowed_origins", []):
            self.kv.sadd(f"origin:{origin}", site["site_id"])

    def create(self, tenant_id: str, name: str, allowed_origins: list[str], mode: str = "observe",
               rules: list[dict[str, Any]] | None = None, preset: str | None = None,
               publishable_key: str | None = None, secret_key: str | None = None,
               site_id: str | None = None) -> tuple[dict[str, Any], str]:
        if mode not in MODES:
            raise ValueError("mode must be observe or enforce")
        origins = []
        for origin in allowed_origins:
            canonical = canonical_origin(origin)
            if canonical is None:
                raise ValueError(f"Invalid origin: {origin}")
            origins.append(canonical)
        secret = secret_key or "sk_" + secrets.token_urlsafe(32)
        site = {
            "site_id": site_id or uuid.uuid4().hex[:16],
            "tenant_id": tenant_id,
            "name": name,
            "publishable_key": publishable_key or "pk_" + secrets.token_urlsafe(24),
            "secret_key_digest": _digest(secret),
            "allowed_origins": origins,
            "mode": mode,
            "preset": preset,
            "rules": rules if rules is not None else (load_preset(preset) if preset else []),
            "webhooks": [],
            "created_at": time.time(),
        }
        self._save(site)
        self.kv.set(f"sitekey:pk:{site['publishable_key']}", site["site_id"])
        self.kv.set(f"sitekey:sk:{site['secret_key_digest']}", site["site_id"])
        return site, secret

    def update(self, site_id: str, *, rules: list[dict[str, Any]] | None = None, mode: str | None = None,
               allowed_origins: list[str] | None = None) -> dict[str, Any] | None:
        site = self.get(site_id)
        if site is None:
            return None
        if rules is not None:
            site["rules"] = rules
        if mode is not None:
            if mode not in MODES:
                raise ValueError("mode must be observe or enforce")
            site["mode"] = mode
        if allowed_origins is not None:
            canonical = [canonical_origin(origin) for origin in allowed_origins]
            if any(origin is None for origin in canonical):
                raise ValueError("Invalid origin")
            for origin in site["allowed_origins"]:
                self.kv.srem(f"origin:{origin}", site_id)
            site["allowed_origins"] = canonical
        self._save(site)
        return site

    def add_webhook(self, site_id: str, url: str) -> tuple[dict[str, Any], str] | None:
        site = self.get(site_id)
        if site is None:
            return None
        if urlsplit(url).scheme not in {"http", "https"}:
            raise ValueError("Webhook URL must be http or https")
        signing_secret = "whsec_" + secrets.token_urlsafe(24)
        site.setdefault("webhooks", []).append({"url": url, "secret": signing_secret})
        self._save(site)
        return site, signing_secret

    def seed_from_file(self, path: str) -> int:
        entries = json.loads(Path(path).read_text(encoding="utf-8"))
        seeded = 0
        for entry in entries:
            if self.get(entry["site_id"]) is not None:
                continue
            self.create(
                tenant_id=entry["tenant_id"], name=entry["name"], allowed_origins=entry.get("allowed_origins", []),
                mode=entry.get("mode", "observe"), rules=entry.get("rules"), preset=entry.get("preset"),
                publishable_key=entry.get("publishable_key"), secret_key=entry.get("secret_key"),
                site_id=entry["site_id"],
            )
            seeded += 1
        return seeded


def deliver_webhooks(site: dict[str, Any], verdict: dict[str, Any]) -> None:
    """POST a non-ok verdict to the site's webhooks in the background, signed with HMAC-SHA256."""
    hooks = site.get("webhooks") or []
    if not hooks or verdict.get("verdict") == "ok":
        return
    body = json.dumps({"type": "neurosoc.verdict", "data": verdict}).encode("utf-8")

    def _send() -> None:
        for hook in hooks:
            signature = hmac.new(hook["secret"].encode("utf-8"), body, hashlib.sha256).hexdigest()
            request = urllib_request.Request(hook["url"], data=body, method="POST", headers={
                "Content-Type": "application/json", "X-NeuroSOC-Signature": f"sha256={signature}"})
            try:
                with urllib_request.urlopen(request, timeout=5):
                    pass
            except (urllib_error.URLError, urllib_error.HTTPError, TimeoutError, ValueError) as exc:
                log.warning("Webhook delivery to %s failed: %s", urlsplit(hook["url"]).hostname, type(exc).__name__)

    threading.Thread(target=_send, daemon=True).start()
