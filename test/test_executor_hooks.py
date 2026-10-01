"""attempt(), failure records, numbered keys, collect_action_results, on_start and the list-source protocol."""
import pytest

from je_action_core import (
    ActionExecutor,
    ActionListRules,
    CommandRegistry,
    DuplicateKeys,
    ExecutionReporter,
    ExecutorSettings,
    PrintReporter,
    repr_failure,
    unique_record_key,
)


def _add(a, b=0):
    return a + b


def _boom():
    raise RuntimeError("boom")


class _Calls(ExecutionReporter):
    def __init__(self):
        self.calls = []

    def on_start(self, action_list):
        self.calls.append(("start", action_list))

    def on_failure(self, action, error):
        self.calls.append(("failure", action))

    def on_empty(self, action_list):
        self.calls.append(("empty", action_list))

    def on_records(self, records):
        self.calls.append(("records", dict(records)))


def _executor(**settings):
    settings.setdefault("rules", ActionListRules("doc"))
    return ActionExecutor(ExecutorSettings(**settings), CommandRegistry({"add": _add, "boom": _boom}))


def test_unique_record_key_numbers_repeats_from_two():
    records = {}
    for value in range(3):
        records[unique_record_key(records, "k")] = value
    assert records == {"k": 0, "k #2": 1, "k #3": 2}
    assert unique_record_key({"k": 0, "k #3": 1}, "k") == "k #2"


def test_repeated_keys_replace_by_default_and_are_numbered_on_request():
    actions = [["add", [1]], ["add", [1]]]
    assert _executor().execute_action(actions) == {"execute: ['add', [1]]": 1}
    numbered = _executor(duplicate_keys=DuplicateKeys.NUMBER).execute_action(actions)
    assert numbered == {"execute: ['add', [1]]": 1, "execute: ['add', [1]] #2": 1}


def test_the_failure_record_is_repr_by_default_and_can_be_replaced():
    assert repr_failure(["boom"], RuntimeError("x")) == "RuntimeError('x')"
    assert _executor().run_one(["boom"]) == "RuntimeError('boom')"
    custom = _executor(failure_record=lambda action, error: f"{action[0]} failed: {error}")
    assert custom.execute_action([["boom"]]) == {"execute: ['boom']": "boom failed: boom"}


def test_collect_returns_the_failed_keys_and_does_not_report_the_records():
    reporter = _Calls()
    executor = _executor(reporter=reporter, duplicate_keys=DuplicateKeys.NUMBER)
    records, failed = executor.collect_action_results([["boom"], ["add", [2]], ["boom"]])
    assert records == {"execute: ['boom']": "RuntimeError('boom')", "execute: ['add', [2]]": 2,
                       "execute: ['boom'] #2": "RuntimeError('boom')"}
    assert failed == ["execute: ['boom']", "execute: ['boom'] #2"]
    assert [call[0] for call in reporter.calls] == ["start", "failure", "failure"]


def test_execute_action_reports_start_then_records(capsys):
    reporter = _Calls()
    assert _executor(reporter=reporter).execute_action({"doc": [["add", [1, 2]]]}) == {"execute: ['add', [1, 2]]": 3}
    assert reporter.calls == [("start", {"doc": [["add", [1, 2]]]}), ("records", {"execute: ['add', [1, 2]]": 3})]
    _executor(reporter=PrintReporter()).execute_action([["add", [4]]])
    assert capsys.readouterr().out == "execute: ['add', [4]]\n4\n"


def test_on_start_comes_before_the_list_is_checked():
    reporter = _Calls()
    with pytest.raises(Exception, match="action list must be a list"):
        _executor(reporter=reporter).collect_action_results("not a list")
    assert reporter.calls == [("start", "not a list")]


class _Source:
    """A list source that is not ActionListRules: an empty list runs nothing, a tuple is refused."""

    def extract(self, action_list):
        if isinstance(action_list, tuple):
            raise ValueError("no tuples")
        return action_list or None


def test_any_list_source_works_and_none_means_run_nothing():
    reporter = _Calls()
    executor = _executor(rules=_Source(), reporter=reporter)
    assert executor.collect_action_results([]) == ({}, [])
    assert executor.execute_action([]) == {}
    assert ("empty", []) in reporter.calls
    assert ("records", {}) not in reporter.calls
    assert executor.execute_action([["add", [5]]]) == {"execute: ['add', [5]]": 5}
    with pytest.raises(ValueError, match="no tuples"):
        executor.execute_action((["add", [5]],))


class _Retrying(ActionExecutor):
    """Retries each action once: attempt() wraps the whole action, binding included."""

    def __init__(self):
        super().__init__(ExecutorSettings(rules=ActionListRules("doc")), CommandRegistry({"add": _add}))
        self.attempts = []

    def attempt(self, action):
        for remaining in (1, 0):
            self.attempts.append(action[0])
            try:
                return super().attempt(action)
            except Exception:
                if not remaining:
                    raise
        raise AssertionError("unreachable")


def test_attempt_wraps_every_action_of_run_one_execute_and_collect():
    executor = _Retrying()
    records, failed = executor.collect_action_results([["missing"], ["add", [1]]])
    assert failed == ["execute: ['missing']"]
    assert records["execute: ['add', [1]]"] == 1
    assert executor.attempts == ["missing", "missing", "add"]
    executor.attempts.clear()
    executor.run_one(["add", [2]])
    executor.execute_action([["add", [3]]])
    assert executor.attempts == ["add", "add"]
