from __future__ import annotations

import importlib.util
import logging
import sys
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FEEDBACK_DIR = REPO_ROOT / "feedback-service"
RETRAINING_DIR = REPO_ROOT / "retraining-service"

sys.path.insert(0, str(RETRAINING_DIR))
from common import CLASS_NAMES  # noqa: E402


def _load_module(module_name: str, module_path: Path, extra_sys_path: Path | None = None):
    if extra_sys_path is not None and str(extra_sys_path) not in sys.path:
        sys.path.insert(0, str(extra_sys_path))
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


feedback_service = _load_module(
    "neurosoc_feedback_main_for_tests", FEEDBACK_DIR / "main.py", FEEDBACK_DIR
)
retraining_main = _load_module("neurosoc_retraining_main_for_tests", RETRAINING_DIR / "main.py", RETRAINING_DIR)


def test_empty_session_gets_a_valid_class_label():
    label = feedback_service.detect_label([])
    assert label.label in CLASS_NAMES
    assert label.label == "OTHER"


def test_honeypot_field_label_is_a_valid_class():
    actions = [{"path": "/transfer", "method": "POST", "timestamp": 1.0, "body": {"confirm_routing_number": "12345"}}]
    label = feedback_service.detect_label(actions)
    assert label.label in CLASS_NAMES
    assert label.attack_type == "HONEYPOT_ACCESS"


def test_canary_token_label_is_a_valid_class():
    actions = [{"path": "/api/notes", "method": "POST", "timestamp": 1.0, "body": {"note": "csrf-token leaked"}}]
    label = feedback_service.detect_label(actions)
    assert label.label in CLASS_NAMES
    assert label.attack_type == "CANARY_TOKEN"


def test_honeypot_path_label_is_a_valid_class():
    actions = [{"path": "/api/admin", "method": "GET", "timestamp": 1.0, "body": None}]
    label = feedback_service.detect_label(actions)
    assert label.label in CLASS_NAMES
    assert label.attack_type == "HONEYPOT_ACCESS"


def test_unclassified_session_falls_back_to_a_valid_class():
    actions = [{"path": "/dashboard", "method": "GET", "timestamp": 1.0, "body": None}]
    label = feedback_service.detect_label(actions)
    assert label.label in CLASS_NAMES
    assert label.attack_type == "UNKNOWN"


class _FakeCursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def execute(self, *_args: object, **_kwargs: object) -> None:
        return None

    def fetchall(self) -> list[dict[str, object]]:
        return self._rows


class _FakeConnection:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._rows)

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


@contextmanager
def _fake_connect(rows: list[dict[str, object]]):
    yield _FakeConnection(rows)


def test_retraining_drops_and_logs_rows_with_invalid_label_or_features(monkeypatch, caplog):
    repository = retraining_main.PostgresFeedbackRepository("postgresql://unused")
    rows = [
        {"id": 1, "session_id": "s1", "features": "[" + ",".join(["0.1"] * 80) + "]", "label": "OTHER", "confidence": 0.5, "metadata": {}, "created_at": None},
        {"id": 2, "session_id": "s2", "features": "[" + ",".join(["0.1"] * 80) + "]", "label": "NOT_A_REAL_CLASS", "confidence": 0.5, "metadata": {}, "created_at": None},
        {"id": 3, "session_id": "s3", "features": "not-json", "label": "OTHER", "confidence": 0.5, "metadata": {}, "created_at": None},
    ]
    monkeypatch.setattr(repository, "connect", lambda: _fake_connect(rows))

    with caplog.at_level(logging.WARNING):
        samples = repository.fetch_feedback_samples()

    assert [sample.id for sample in samples] == [1]
    warnings = [record.message for record in caplog.records if record.levelno == logging.WARNING]
    assert any("id=2" in message and "NOT_A_REAL_CLASS" in message for message in warnings)
    assert any("id=3" in message for message in warnings)
