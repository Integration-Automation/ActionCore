import asyncio
import json

import pytest

from je_action_core.request_context import RunContext, get_run_context, use_run_context
from je_action_core.request_record import RequestRecordError


def fields(**changes):
    result = {"protocol": "http", "request_method": "GET", "request_url": "http://localhost/",
              "name": "GET /", "status_code": 200, "start_time": 100.0, "end_time": 100.01,
              "response_time_ms": 10.0, "response_length": 2, "outcome": "passed", "error": None}
    result.update(changes)
    return result


def context():
    return RunContext(source="loaddensity", phase="load", engine="asyncio")


def test_runs_have_distinct_ids_and_detached_records():
    first, second = context(), context()
    assert first.run_id != second.run_id
    first.capture(fields(extensions={"nested": [1]}))
    assert second.snapshot() == []
    snapshot = first.snapshot()
    snapshot[0]["extensions"]["nested"].append(2)
    assert first.snapshot()[0]["extensions"] == {"nested": [1]}
    assert json.loads(first.to_json())[0]["response_time_ms"] == 10.0


def test_identical_retry_deduplicates_but_conflicting_result_fails():
    run = context()
    record = run.capture(fields())
    assert run.append(record) is False
    assert len(run.snapshot()) == 1
    with pytest.raises(RequestRecordError, match="record_id"):
        run.append({**record, "status_code": 201})


def test_record_from_other_run_is_rejected():
    first, second = context(), context()
    record = first.capture(fields())
    with pytest.raises(RequestRecordError, match="run_id"):
        second.append(record)


def test_nested_context_restores_after_exception():
    first, second = context(), context()
    assert get_run_context() is None
    with use_run_context(first):
        assert get_run_context() is first
        with pytest.raises(ValueError), use_run_context(second):
            assert get_run_context() is second
            raise ValueError("probe")
        assert get_run_context() is first
    assert get_run_context() is None


def test_async_task_contexts_do_not_cross_contaminate():
    async def worker(run, status):
        with use_run_context(run):
            await asyncio.sleep(0)
            get_run_context().capture(fields(status_code=status))

    async def execute():
        first, second = context(), context()
        await asyncio.gather(worker(first, 200), worker(second, 201))
        return first, second

    first, second = asyncio.run(execute())
    assert [record["status_code"] for record in first.snapshot()] == [200]
    assert [record["status_code"] for record in second.snapshot()] == [201]


def test_capture_rejects_wrong_source_instead_of_overriding_identity():
    with pytest.raises(RequestRecordError, match="source"):
        context().capture(fields(source="apitestka"))
