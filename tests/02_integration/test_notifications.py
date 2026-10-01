from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "inference-service"))

import main as inference_main  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_notification_config(monkeypatch):
    monkeypatch.setattr(inference_main, "ALERT_WEBHOOK_URL", "")
    monkeypatch.setattr(inference_main, "SMTP_HOST", "")
    monkeypatch.setattr(inference_main, "SMTP_USER", "")
    monkeypatch.setattr(inference_main, "SMTP_PASS", "")
    monkeypatch.setattr(inference_main, "REPORT_EMAIL", "")
    monkeypatch.setattr(inference_main, "REPORT_TIME", "06:00")


@pytest.fixture(autouse=True)
def _isolate_runtime_state():
    with inference_main.runtime._lock:
        saved_verdicts = list(inference_main.runtime._latest_verdicts)
        saved_alerts = list(inference_main.runtime._latest_alerts)
        saved_digest_date = inference_main.runtime._last_digest_date
        inference_main.runtime._latest_verdicts.clear()
        inference_main.runtime._latest_alerts.clear()
    try:
        yield
    finally:
        with inference_main.runtime._lock:
            inference_main.runtime._latest_verdicts.clear()
            inference_main.runtime._latest_verdicts.extend(saved_verdicts)
            inference_main.runtime._latest_alerts.clear()
            inference_main.runtime._latest_alerts.extend(saved_alerts)
            inference_main.runtime._last_digest_date = saved_digest_date


def test_webhook_notification_is_a_noop_without_a_configured_url(monkeypatch):
    calls = []
    monkeypatch.setattr(inference_main.urllib_request, "urlopen", lambda *a, **k: calls.append(1))
    inference_main._send_webhook_notification({"verdict": "HACKER", "source_ip": "1.2.3.4"})
    assert calls == []


def test_webhook_notification_posts_a_readable_payload(monkeypatch):
    monkeypatch.setattr(inference_main, "ALERT_WEBHOOK_URL", "https://hooks.example.com/incoming")
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["body"] = request.data
        return FakeResponse()

    monkeypatch.setattr(inference_main.urllib_request, "urlopen", fake_urlopen)

    inference_main._send_webhook_notification(
        {
            "verdict": "HACKER",
            "xgb_class": "BRUTE_FORCE",
            "source_ip": "203.0.113.9",
            "confidence": 0.93,
            "session_id": "portal-abc",
        }
    )

    assert captured["url"] == "https://hooks.example.com/incoming"
    assert captured["method"] == "POST"
    assert b"BRUTE_FORCE" in captured["body"]
    assert b"203.0.113.9" in captured["body"]


def test_webhook_notification_failure_does_not_raise(monkeypatch):
    monkeypatch.setattr(inference_main, "ALERT_WEBHOOK_URL", "https://hooks.example.com/incoming")

    def fake_urlopen(*_args, **_kwargs):
        raise inference_main.urllib_error.URLError("connection refused")

    monkeypatch.setattr(inference_main.urllib_request, "urlopen", fake_urlopen)

    inference_main._send_webhook_notification({"verdict": "HACKER", "source_ip": "1.2.3.4"})  # must not raise


def test_high_severity_verdict_triggers_webhook_but_low_severity_does_not(monkeypatch):
    calls = []
    monkeypatch.setattr(inference_main, "_send_webhook_notification", lambda payload: calls.append(payload))
    monkeypatch.setattr(inference_main.runtime, "_persist_verdict", lambda verdict: None)
    monkeypatch.setattr(inference_main.runtime.repository, "record_audit_event", lambda event: None)

    hacker_verdict = inference_main.ThreatVerdict(
        session_id="s1", user_id="u1", source_ip="1.2.3.4", snn_score=0.9, lnn_class="BRUTE_FORCE",
        xgb_class="BRUTE_FORCE", behavioral_delta=0.9, confidence=0.95, verdict="HACKER",
        timestamp=1_800_000_000.0, model_version="1.0.1", features_dict={},
    )
    legit_verdict = inference_main.ThreatVerdict(
        session_id="s2", user_id="u2", source_ip="5.6.7.8", snn_score=0.1, lnn_class="BENIGN",
        xgb_class="BENIGN", behavioral_delta=0.05, confidence=0.05, verdict="LEGITIMATE",
        timestamp=1_800_000_001.0, model_version="1.0.1", features_dict={},
    )

    inference_main.runtime._handle_verdict(hacker_verdict)
    inference_main.runtime._handle_verdict(legit_verdict)

    assert len(calls) == 1
    assert calls[0]["session_id"] == "s1"


def test_digest_email_body_lists_alerts():
    rows = [
        {"created_at": "2026-09-29T05:00:00Z", "verdict": "HACKER", "source_ip": "1.2.3.4", "user_id": "u1", "confidence": 0.9},
    ]
    body = inference_main._build_digest_email_body(rows)
    assert "1 alert(s)" in body
    assert "1.2.3.4" in body


def test_digest_email_body_handles_no_alerts():
    assert "No high-confidence alerts" in inference_main._build_digest_email_body([])


def test_send_digest_email_is_a_noop_without_smtp_config():
    assert inference_main._send_digest_email("body") is False


def test_send_digest_email_uses_starttls_and_login(monkeypatch):
    monkeypatch.setattr(inference_main, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(inference_main, "SMTP_USER", "neurosoc@example.com")
    monkeypatch.setattr(inference_main, "SMTP_PASS", "secret")
    monkeypatch.setattr(inference_main, "REPORT_EMAIL", "analyst@example.com")

    calls = {"starttls": 0, "login": None, "sendmail": None}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            calls["host"] = host
            calls["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def ehlo(self):
            return None

        def has_extn(self, name):
            return name == "STARTTLS"

        def starttls(self):
            calls["starttls"] += 1

        def login(self, user, password):
            calls["login"] = (user, password)

        def sendmail(self, from_addr, to_addrs, message):
            calls["sendmail"] = (from_addr, to_addrs)

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)

    assert inference_main._send_digest_email("digest body") is True
    assert calls["starttls"] == 1
    assert calls["login"] == ("neurosoc@example.com", "secret")
    assert calls["sendmail"][0] == "neurosoc@example.com"
    assert calls["sendmail"][1] == ["analyst@example.com"]


def test_send_digest_email_returns_false_on_smtp_failure(monkeypatch):
    monkeypatch.setattr(inference_main, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(inference_main, "REPORT_EMAIL", "analyst@example.com")

    class BrokenSMTP:
        def __init__(self, *_args, **_kwargs):
            raise OSError("connection refused")

    monkeypatch.setattr("smtplib.SMTP", BrokenSMTP)

    assert inference_main._send_digest_email("digest body") is False


def test_maybe_send_daily_digest_only_sends_once_per_day_after_report_time(monkeypatch):
    monkeypatch.setattr(inference_main, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(inference_main, "REPORT_EMAIL", "analyst@example.com")
    monkeypatch.setattr(inference_main, "REPORT_TIME", "00:00")
    monkeypatch.setattr(inference_main.runtime.repository, "latest_alert_rows", lambda tenant_id, limit=200: [])

    sent = []
    monkeypatch.setattr(inference_main, "_send_digest_email", lambda body: sent.append(body) or True)
    inference_main.runtime._last_digest_date = None

    inference_main.runtime._maybe_send_daily_digest()
    inference_main.runtime._maybe_send_daily_digest()

    assert len(sent) == 1
    assert inference_main.runtime._last_digest_date == datetime.now(timezone.utc).strftime("%Y-%m-%d")
