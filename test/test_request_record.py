import json
from datetime import datetime, timedelta, timezone

import pytest

from je_action_core.request_record import (
    RequestRecordError,
    request_record_schema,
    serialize_request_record,
    validate_request_record,
)


def sample(**changes):
    record = {
        "schema_version": 1, "record_id": "r-1", "run_id": "run-1", "source": "loaddensity",
        "phase": "load", "engine": "locust", "worker_id": None, "scenario_id": None, "step_id": None,
        "protocol": "http", "request_method": "GET", "request_url": "http://localhost/health", "name": "health",
        "status_code": 200, "start_time": 100.0, "end_time": 100.025, "response_time_ms": 25.0,
        "response_length": 12, "outcome": "passed", "error": None, "assertions": [], "extensions": {},
    }
    record.update(changes)
    return record


def test_success_record_round_trips_without_altering_values():
    record = sample()
    assert json.loads(serialize_request_record(record)) == record
    assert validate_request_record(record)["response_time_ms"] == 25.0


def test_failure_preserves_status_and_assertion_result():
    record = sample(status_code=500, outcome="failed", error={"kind": "http_status", "message": "HTTP 500"},
                    assertions=[{"type": "status_code", "passed": False, "message": "wanted 200"}])
    result = json.loads(serialize_request_record(record))
    assert result["status_code"] == 500
    assert result["outcome"] == "failed"
    assert result["assertions"][0]["passed"] is False


def test_transport_failure_allows_unknown_measurements():
    result = validate_request_record(sample(status_code=None, start_time=None, end_time=None, response_time_ms=None,
                                           response_length=None, outcome="failed",
                                           error={"kind": "connection", "message": "refused"}))
    assert result["status_code"] is None
    assert result["response_time_ms"] is None


@pytest.mark.parametrize("field,value", [
    ("schema_version", 2), ("schema_version", True), ("run_id", ""), ("record_id", ""),
    ("source", "unknown"), ("phase", "unknown"), ("engine", ""), ("protocol", ""),
    ("request_method", "get"), ("status_code", "200"), ("status_code", True),
    ("response_time_ms", -1), ("response_time_ms", float("nan")), ("start_time", float("inf")),
    ("response_length", -1), ("response_length", 1.5), ("response_length", True),
    ("outcome", "success"), ("error", {"kind": "timeout", "message": "oops"}),
    ("assertions", [{"type": "status_code", "passed": "false"}]), ("assertions", [{}]),
    ("extensions", []), ("worker_id", 1), ("end_time", 99.0),
])
def test_malformed_record_is_rejected_with_field_location(field, value):
    with pytest.raises(RequestRecordError, match=field):
        validate_request_record(sample(**{field: value}))


@pytest.mark.parametrize("error", [None, "oops", {}, {"kind": "timeout"}, {"kind": "", "message": "oops"}])
def test_failed_record_requires_structured_error(error):
    with pytest.raises(RequestRecordError, match="error"):
        validate_request_record(sample(outcome="failed", error=error))


def test_missing_required_field_is_reported():
    record = sample()
    del record["step_id"]
    with pytest.raises(RequestRecordError, match="step_id"):
        validate_request_record(record)


def test_payload_converts_supported_python_values_without_stringifying_objects():
    record = sample(extensions={"bytes": b"\x00\xff", "when": datetime(2026, 1, 1, tzinfo=timezone.utc),
                                "elapsed": timedelta(milliseconds=1500), "label": "測試"})
    payload = json.loads(serialize_request_record(record))
    assert payload["extensions"] == {
        "bytes": {"encoding": "base64", "data": "AP8="}, "when": 1767225600.0,
        "elapsed": 1500.0, "label": "測試",
    }
    with pytest.raises(RequestRecordError, match="extensions"):
        serialize_request_record(sample(extensions={"opaque": object()}))


def test_nested_nan_and_non_string_keys_are_rejected():
    with pytest.raises(RequestRecordError, match="extensions"):
        serialize_request_record(sample(extensions={"nested": [float("nan")]}))
    with pytest.raises(RequestRecordError, match="extensions"):
        serialize_request_record(sample(extensions={1: "bad key"}))


def test_validation_returns_a_detached_snapshot():
    original = sample(extensions={"nested": [1]})
    result = validate_request_record(original)
    original["extensions"]["nested"].append(2)
    assert result["extensions"] == {"nested": [1]}


def test_schema_covers_required_keys_and_nullable_transport_status():
    schema = request_record_schema()
    assert set(schema["required"]) == set(sample())
    assert schema["properties"]["schema_version"] == {"const": 1, "type": "integer"}
    assert schema["properties"]["status_code"]["type"] == ["integer", "null"]


@pytest.mark.parametrize("field,value", [("text", 1), ("headers", []), ("content_base64", 1)])
def test_payload_types_match_schema(field, value):
    with pytest.raises(RequestRecordError, match=field):
        validate_request_record(sample(**{field: value}))


def test_failed_assertion_cannot_be_marked_as_passed_request():
    with pytest.raises(RequestRecordError, match="assertions"):
        validate_request_record(sample(assertions=[{"type": "status_code", "passed": False, "message": "bad"}]))


def test_circular_payload_is_rejected_with_location():
    extensions = {}
    extensions["cycle"] = extensions
    with pytest.raises(RequestRecordError, match="extensions.cycle"):
        serialize_request_record(sample(extensions=extensions))


def test_passed_assertion_message_must_be_text_when_present():
    with pytest.raises(RequestRecordError, match="assertions"):
        validate_request_record(sample(assertions=[{"type": "status", "passed": True, "message": 1}]))


@pytest.mark.parametrize("field,value", [("start_time", 10**1000), ("response_length", 10**5000)],
                         ids=["huge-timestamp", "huge-length"])
def test_extreme_integer_errors_keep_the_field_location(field, value):
    with pytest.raises(RequestRecordError, match=field):
        serialize_request_record(sample(**{field: value}))


@pytest.mark.parametrize("assertion,outcome", [
    ({"type": "status", "passed": False}, "failed"),
    ({"type": "status", "passed": True, "message": 1}, "passed"),
    ({"type": "status", "passed": False, "message": "bad"}, "passed"),
])
def test_schema_and_validator_reject_the_same_assertion_errors(assertion, outcome):
    jsonschema = pytest.importorskip("jsonschema")
    record = sample(assertions=[assertion], outcome=outcome,
                    error={"kind": "assertion", "message": "bad"} if outcome == "failed" else None)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(request_record_schema()).validate(record)
    with pytest.raises(RequestRecordError):
        validate_request_record(record)


@pytest.mark.parametrize("method", ["get", "BAD METHOD", "GÉT", "GET\n"])
def test_http_methods_use_the_same_uppercase_token_rule_in_schema(method):
    jsonschema = pytest.importorskip("jsonschema")
    record = sample(request_method=method)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(request_record_schema()).validate(record)
    with pytest.raises(RequestRecordError, match="request_method"):
        validate_request_record(record)
