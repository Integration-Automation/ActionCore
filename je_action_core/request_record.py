"""Versioned request results, independent of action-executor records and transports."""

from __future__ import annotations

import base64
import json
import math
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import TypedDict, cast

from je_action_core.exceptions import ActionCoreException


class RecordError(TypedDict):
    """A transport, assertion or runner failure without a Python exception object."""

    kind: str
    message: str


class RequestRecord(TypedDict):
    """Required fields of the request-result v1 contract."""

    schema_version: int
    record_id: str
    run_id: str
    source: str
    phase: str
    engine: str
    worker_id: str | None
    scenario_id: str | None
    step_id: str | None
    protocol: str
    request_method: str
    request_url: str
    name: str
    status_code: int | None
    start_time: float | None
    end_time: float | None
    response_time_ms: float | None
    response_length: int | None
    outcome: str
    error: RecordError | None
    assertions: list[dict[str, object]]
    extensions: dict[str, object]


class RequestRecordError(ActionCoreException, ValueError):
    """A request result is malformed; the message includes its field location."""


_TEXT_FIELDS = (
    "record_id", "run_id", "source", "phase", "engine", "protocol", "request_method", "request_url", "name",
)
_OPTIONAL_IDS = ("worker_id", "scenario_id", "step_id")
_MEASUREMENTS = ("start_time", "end_time", "response_time_ms")
_CHOICES = {
    "source": ("apitestka", "loaddensity", "webrunner"),
    "phase": ("functional", "load", "synthetic"),
    "outcome": ("passed", "failed"),
}
_PAYLOAD_FIELDS = ("text", "headers", "content_base64", "request_body")
_REQUIRED = tuple(RequestRecord.__annotations__)


def _fail(location: str, reason: str) -> None:
    raise RequestRecordError(f"{location}: {reason}")


def _json_value(value: object, location: str, ancestors: frozenset[int] = frozenset()) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            _fail(location, "must be finite")
        return value
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, timedelta):
        return value.total_seconds() * 1000.0
    if isinstance(value, bytes):
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    if id(value) in ancestors:
        _fail(location, "circular value")
    nested = ancestors | {id(value)}
    return _json_container(value, location, nested)


def _json_container(value: object, location: str, ancestors: frozenset[int]) -> object:
    if isinstance(value, Mapping):
        converted = {}
        for key, item in value.items():
            if not isinstance(key, str):
                _fail(location, "object keys must be strings")
            converted[key] = _json_value(item, f"{location}.{key}", ancestors)
        return converted
    if isinstance(value, (list, tuple)):
        return [_json_value(item, f"{location}[{index}]", ancestors) for index, item in enumerate(value)]
    _fail(location, f"unsupported value type {type(value).__name__}")


def _validate_text(record: Mapping[str, object]) -> None:
    for field in _TEXT_FIELDS:
        if not isinstance(record[field], str) or not record[field]:
            _fail(field, "must be a non-empty string")
    for field in _OPTIONAL_IDS:
        if record[field] is not None and not isinstance(record[field], str):
            _fail(field, "must be a string or null")
    for field, choices in _CHOICES.items():
        if record[field] not in choices:
            _fail(field, f"must be one of {choices}")
    method = cast(str, record["request_method"])
    if record["protocol"] == "http" and method != method.upper():
        _fail("request_method", "HTTP methods must be uppercase")


def _validate_integer(record: Mapping[str, object], field: str, minimum: int | None = None) -> None:
    value = record[field]
    if value is None:
        return
    if type(value) is not int:
        _fail(field, "must be an integer or null")
    if minimum is not None and cast(int, value) < minimum:
        _fail(field, f"must be at least {minimum}")


def _validate_measurements(record: Mapping[str, object]) -> None:
    for field in _MEASUREMENTS:
        value = record[field]
        if value is not None and (type(value) not in (int, float) or not math.isfinite(cast(float, value))):
            _fail(field, "must be a finite number or null")
    elapsed = record["response_time_ms"]
    if elapsed is not None and cast(float, elapsed) < 0:
        _fail("response_time_ms", "must be non-negative")
    start, end = record["start_time"], record["end_time"]
    if start is not None and end is not None and cast(float, end) < cast(float, start):
        _fail("end_time", "must not precede start_time")
    _validate_integer(record, "status_code")
    _validate_integer(record, "response_length", minimum=0)


def _validate_outcome(record: Mapping[str, object]) -> None:
    error = record["error"]
    if record["outcome"] == "passed":
        if error is not None:
            _fail("error", "passed records must have null error")
    else:
        if not isinstance(error, dict):
            _fail("error", "failed records require a structured error")
        for field in ("kind", "message"):
            if not isinstance(error.get(field), str) or not error[field]:
                _fail(f"error.{field}", "must be a non-empty string")
    _validate_assertions(record)
    if not isinstance(record["extensions"], dict):
        _fail("extensions", "must be an object")


def _validate_assertions(record: Mapping[str, object]) -> None:
    assertions = record["assertions"]
    if not isinstance(assertions, list):
        _fail("assertions", "must be an array")
    for index, assertion in enumerate(assertions):
        location = f"assertions[{index}]"
        if not isinstance(assertion, dict) or not isinstance(assertion.get("type"), str):
            _fail(location, "must have a string type")
        if type(assertion.get("passed")) is not bool:
            _fail(location, "passed must be a boolean")
        if not assertion["passed"] and not isinstance(assertion.get("message"), str):
            _fail(location, "failed assertion must have a message")
        if not assertion["passed"] and record["outcome"] == "passed":
            _fail(location, "a failed assertion cannot have a passed outcome")


def _validate_payload(record: Mapping[str, object]) -> None:
    allowed_types = {"text": (str, type(None)), "headers": (dict,), "content_base64": (str,)}
    for field, types in allowed_types.items():
        if field in record and not isinstance(record[field], types):
            _fail(field, "invalid payload type")


def validate_request_record(record: Mapping[str, object]) -> RequestRecord:
    """Validate and detach a v1 record, converting supported payloads to JSON values."""
    if not isinstance(record, Mapping):
        _fail("record", "must be an object")
    for field in _REQUIRED:
        if field not in record:
            _fail(field, "required field is missing")
    unknown = set(record) - set(_REQUIRED) - set(_PAYLOAD_FIELDS)
    if unknown:
        _fail("record", f"unknown fields: {sorted(unknown, key=str)}; use extensions")
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        _fail("schema_version", "only integer version 1 is supported")
    converted = cast(dict[str, object], _json_value(record, "record"))
    _validate_text(converted)
    _validate_measurements(converted)
    _validate_outcome(converted)
    _validate_payload(converted)
    return cast(RequestRecord, converted)


def serialize_request_record(record: Mapping[str, object]) -> str:
    """Serialize a validated request result without arbitrary-object stringification."""
    return json.dumps(validate_request_record(record), ensure_ascii=False, allow_nan=False)


def request_record_schema() -> dict[str, object]:
    """Return the JSON Schema for request results, separate from action records."""
    properties: dict[str, object] = {field: {"type": "string", "minLength": 1} for field in _TEXT_FIELDS}
    properties.update({field: {"type": ["string", "null"]} for field in _OPTIONAL_IDS})
    properties.update({field: {"type": ["number", "null"]} for field in _MEASUREMENTS})
    properties.update({field: {"enum": list(values)} for field, values in _CHOICES.items()})
    properties.update({
        "schema_version": {"const": 1, "type": "integer"},
        "status_code": {"type": ["integer", "null"]},
        "response_length": {"type": ["integer", "null"], "minimum": 0},
        "response_time_ms": {"type": ["number", "null"], "minimum": 0},
        "error": {"anyOf": [{"type": "null"}, {"type": "object", "required": ["kind", "message"],
                                              "properties": {field: {"type": "string", "minLength": 1}
                                                             for field in ("kind", "message")}}]},
        "assertions": {"type": "array", "items": {"type": "object", "required": ["type", "passed"],
                                                 "properties": {"type": {"type": "string"},
                                                                "passed": {"type": "boolean"},
                                                                "message": {"type": "string"}}}},
        "extensions": {"type": "object"},
        "text": {"type": ["string", "null"]}, "headers": {"type": "object"},
        "content_base64": {"type": "string"}, "request_body": {},
    })
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "RequestRecord v1",
            "type": "object", "required": list(_REQUIRED), "properties": properties,
            "additionalProperties": False,
            "allOf": [{"if": {"properties": {"outcome": {"const": "passed"}}},
                       "then": {"properties": {"error": {"type": "null"}}},
                       "else": {"properties": {"error": {"type": "object"}}}}]}
