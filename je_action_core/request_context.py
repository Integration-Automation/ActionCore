"""Explicit run-scoped request storage shared by synchronous and asynchronous runners."""

from __future__ import annotations

import copy
import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock
from uuid import uuid4

from je_action_core.request_record import (
    RequestRecord,
    RequestRecordError,
    _validate_run_identity,
    validate_request_record,
)


class RunContext:
    """Own request identities and records for one run; snapshots never expose mutable storage."""

    def __init__(self, source: str, phase: str, engine: str, worker_id: str | None = None,
                 run_id: str | None = None) -> None:
        self.run_id = str(uuid4()) if run_id is None else run_id
        self._identity = {"run_id": self.run_id, "source": source, "phase": phase,
                          "engine": engine, "worker_id": worker_id}
        _validate_run_identity(self._identity)
        self._records: dict[str, RequestRecord] = {}
        self._lock = RLock()

    def capture(self, fields: Mapping[str, object]) -> RequestRecord:
        """Build and append a measured result with this run's identity and a unique record ID."""
        record = {"schema_version": 1, "record_id": str(uuid4()), "scenario_id": None, "step_id": None,
                  "assertions": [], "extensions": {}, **self._identity, **fields}
        validated = validate_request_record(record)
        self.append(validated)
        return validated

    def append(self, record: Mapping[str, object]) -> bool:
        """Append once, returning False for identical retries and rejecting conflicts or foreign runs."""
        validated = validate_request_record(record)
        for field, expected in self._identity.items():
            if validated[field] != expected:
                raise RequestRecordError(f"{field}: does not belong to this run context")
        identifier = validated["record_id"]
        with self._lock:
            previous = self._records.get(identifier)
            if previous is not None:
                if json.dumps(previous, sort_keys=True) != json.dumps(validated, sort_keys=True):
                    raise RequestRecordError("record_id: conflicting retry of an existing record")
                return False
            self._records[identifier] = validated
        return True

    def snapshot(self) -> list[RequestRecord]:
        """Return a detached, insertion-ordered copy of all records in this run."""
        with self._lock:
            return copy.deepcopy(list(self._records.values()))

    def to_json(self) -> str:
        """Export this run's canonical records as a JSON array."""
        return json.dumps(self.snapshot(), ensure_ascii=False, allow_nan=False)


_active_context: ContextVar[RunContext | None] = ContextVar("request_run_context", default=None)


def get_run_context() -> RunContext | None:
    """Return the request context active in this thread/task, if explicitly selected."""
    return _active_context.get()


@contextmanager
def use_run_context(context: RunContext) -> Iterator[RunContext]:
    """Activate a context for a scope, restoring the prior scope even when the runner fails."""
    token = _active_context.set(context)
    try:
        yield context
    finally:
        _active_context.reset(token)
