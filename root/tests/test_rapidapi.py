from __future__ import annotations

from src.app.config import AppConfig
from src.app.rapidapi import ApiAccessError
from src.server import create_app
import src.app.api_v1 as api_module


class RecordingUsageLogger:
    def __init__(self):
        self.records = []

    def record(self, **record):
        self.records.append(record)


class RecordingPolicy:
    def __init__(self):
        self.requests = []

    def authorize(self, request):
        self.requests.append((request.method, request.path))


class RejectingPolicy:
    def authorize(self, request):
        raise ApiAccessError("api_key_required", "an API key is required", 401)


def make_app(tmp_path, *, policy=None, usage_logger=None):
    return create_app(
        AppConfig(database_path=tmp_path / "tracker.db"),
        api_access_policy=policy,
        api_usage_logger=usage_logger,
    )


def test_api_access_policy_and_usage_logger_are_injectable(tmp_path):
    policy = RecordingPolicy()
    usage_logger = RecordingUsageLogger()
    app = make_app(tmp_path, policy=policy, usage_logger=usage_logger)

    response = app.test_client().get(
        "/api/v1?check=ignored",
        headers={"X-Request-ID": "test-request-1"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-1"
    assert policy.requests == [("GET", "/api/v1")]
    assert len(usage_logger.records) == 1
    assert usage_logger.records[0]["request_id"] == "test-request-1"
    assert usage_logger.records[0]["method"] == "GET"
    assert usage_logger.records[0]["path"] == "/api/v1"
    assert usage_logger.records[0]["status_code"] == 200
    assert isinstance(usage_logger.records[0]["duration_ms"], int)
    assert usage_logger.records[0]["duration_ms"] >= 0


def test_access_policy_can_reject_with_stable_error_and_usage_record(tmp_path):
    usage_logger = RecordingUsageLogger()
    app = make_app(tmp_path, policy=RejectingPolicy(), usage_logger=usage_logger)

    response = app.test_client().get("/api/v1")

    assert response.status_code == 401
    assert response.get_json() == {
        "error": {"code": "api_key_required", "message": "an API key is required"}
    }
    assert usage_logger.records[0]["status_code"] == 401


def test_invalid_request_id_is_replaced_before_logging(tmp_path):
    usage_logger = RecordingUsageLogger()
    app = make_app(tmp_path, usage_logger=usage_logger)

    response = app.test_client().get(
        "/api/v1",
        headers={"X-Request-ID": "bad request"},
    )

    request_id = response.headers["X-Request-ID"]
    assert request_id != "bad request"
    assert usage_logger.records[0]["request_id"] == request_id


def test_unexpected_api_failure_uses_stable_internal_error(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    monkeypatch.setattr(
        api_module,
        "list_public_analysts",
        lambda database_path: (_ for _ in ()).throw(RuntimeError("private detail")),
    )

    response = app.test_client().get("/api/v1/analysts")

    assert response.status_code == 500
    assert response.get_json() == {
        "error": {"code": "internal_error", "message": "internal server error"}
    }
    assert "private detail" not in response.get_data(as_text=True)
