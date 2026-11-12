from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "inference-service"))

from core.universal import sites  # noqa: E402


def _resolves_to(monkeypatch, address: str) -> None:
    monkeypatch.setattr(sites.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (address, 443))])


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.5", "172.30.0.20", "192.168.1.9", "169.254.169.254", "::1",
                                     "::ffff:10.0.0.5", "0.0.0.0"])
def test_webhook_targets_that_resolve_inside_the_network_are_refused(monkeypatch, address):
    monkeypatch.delenv("UNIVERSAL_WEBHOOK_ALLOW_PRIVATE", raising=False)
    _resolves_to(monkeypatch, address)
    with pytest.raises(ValueError, match="public address"):
        sites.check_webhook_target("https://hooks.example.com/neurosoc")


def test_public_webhook_target_is_accepted(monkeypatch):
    monkeypatch.delenv("UNIVERSAL_WEBHOOK_ALLOW_PRIVATE", raising=False)
    _resolves_to(monkeypatch, "93.184.216.34")
    sites.check_webhook_target("https://hooks.example.com/neurosoc")


@pytest.mark.parametrize("url", ["ftp://example.com/x", "file:///etc/passwd", "https://user:pw@example.com/x", "https:///x"])
def test_malformed_webhook_urls_are_refused(monkeypatch, url):
    _resolves_to(monkeypatch, "93.184.216.34")
    with pytest.raises(ValueError):
        sites.check_webhook_target(url)


def test_private_targets_are_allowed_only_with_the_explicit_development_flag(monkeypatch):
    _resolves_to(monkeypatch, "127.0.0.1")
    monkeypatch.setenv("UNIVERSAL_WEBHOOK_ALLOW_PRIVATE", "true")
    sites.check_webhook_target("http://localhost:9000/hook")
