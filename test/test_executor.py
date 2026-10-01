import json
import logging

import pytest

from je_action_core import (
    ActionExecuteException,
    ActionExecutor,
    ActionListRules,
    BoundAction,
    CommandPolicy,
    CommandRegistry,
    EmptyListPolicy,
    ExecutionReporter,
    ExecutorSettings,
    LoggingReporter,
    PrintReporter,
    StrictActionParser,
    indexed_record_key,
)


def _add(a, b=0):
    return a + b


def _boom():
    raise RuntimeError("boom")


def _executor(**settings):
    registry = CommandRegistry({"add": _add, "boom": _boom}, policy=CommandPolicy.FUNCTIONS_ONLY)
    return ActionExecutor(ExecutorSettings(rules=ActionListRules("doc"), **settings), registry)


def test_runs_every_action_and_records_failures():
    records = _executor().execute_action([["add", [1, 2]], ["boom"], ["add", {"a": 3, "b": 4}], ["nope"]])
    assert records["execute: ['add', [1, 2]]"] == 3
    assert records["execute: ['boom']"] == "RuntimeError('boom')"
    assert records["execute: ['add', {'a': 3, 'b': 4}]"] == 7
    assert records["execute: ['nope']"].startswith("ActionExecuteException(")


def test_document_form_and_invalid_lists():
    executor = _executor()
    assert executor.execute_action({"doc": [["add", [1]]]}) == {"execute: ['add', [1]]": 1}
    for bad in ([], {"other": []}, "text"):
        with pytest.raises(ActionExecuteException):
            executor.execute_action(bad)


def test_return_empty_policy_and_reporter_hook():
    class Recorder(ExecutionReporter):
        empty = None

        def on_empty(self, action_list):
            Recorder.empty = action_list

    executor = ActionExecutor(ExecutorSettings(rules=ActionListRules("doc", empty=EmptyListPolicy.RETURN_EMPTY),
                                               reporter=Recorder()))
    assert executor.execute_action([]) == {}
    assert Recorder.empty == []


def test_indexed_keys_keep_repeated_actions():
    records = _executor(record_key=indexed_record_key).execute_action([["add", [1]], ["add", [1]]])
    assert list(records) == ["execute[0]: ['add', [1]]", "execute[1]: ['add', [1]]"]


def test_plain_keys_keep_the_last_of_repeated_actions():
    assert len(_executor().execute_action([["add", [1]], ["add", [1]]])) == 1


def test_prepare_rewrites_before_binding_but_keys_use_the_action_as_given():
    def strip_tags(action):
        return [action[0], {key: value for key, value in action[1].items() if key != "tags"}]
    records = _executor(prepare=strip_tags).execute_action([["add", {"a": 1, "tags": ["x"]}]])
    assert records == {"execute: ['add', {'a': 1, 'tags': ['x']}]": 1}


def test_strict_parser_and_invoke_override():
    calls = []

    class Traced(ActionExecutor):
        def invoke(self, bound: BoundAction):
            calls.append(bound.name)
            return super().invoke(bound)

    executor = Traced(ExecutorSettings(rules=ActionListRules("doc"), parser=StrictActionParser()),
                      CommandRegistry({"add": _add}))
    records = executor.execute_action([["add", [2]], ["add", "x"]])
    assert records["execute: ['add', [2]]"] == 2
    assert "payload must be dict or list" in records["execute: ['add', 'x']"]
    assert calls == ["add"]


def test_execute_files_reads_each_file(tmp_path):
    paths = []
    for index in (1, 2):
        path = tmp_path / f"{index}.json"
        path.write_text(json.dumps({"doc": [["add", [index]]]}), encoding="utf-8")
        paths.append(str(path))
    assert _executor().execute_files(paths) == [{"execute: ['add', [1]]": 1}, {"execute: ['add', [2]]": 2}]


def test_add_command_applies_the_registry_policy():
    executor = _executor()
    executor.add_command_to_executor({"twice": lambda value: value * 2})
    assert executor.execute_action([["twice", [4]]]) == {"execute: ['twice', [4]]": 8}
    with pytest.raises(Exception, match="len"):
        executor.add_command_to_executor({"len": len})


def test_event_dict_is_the_registry_mapping():
    executor = _executor()
    executor.event_dict["sub"] = lambda a, b: a - b
    assert executor.registry.resolve("sub")(3, 1) == 2
    executor.event_dict = {"only": _add}
    assert list(executor.registry) == ["only"]


def test_logging_reporter(caplog):
    logger = logging.getLogger("je_action_core.test")
    with caplog.at_level(logging.DEBUG, logger="je_action_core.test"):
        _executor(reporter=LoggingReporter(logger)).execute_action([["add", [1]], ["boom"]])
    messages = [record.getMessage() for record in caplog.records]
    assert "Execute ['add', [1]]" in messages
    assert "Execute ['boom'] failed. RuntimeError('boom')" in messages
    assert "execute: ['add', [1]] -> 1" in messages
    assert any(record.levelno == logging.DEBUG for record in caplog.records)


def test_logging_reporter_empty_message(caplog):
    logger = logging.getLogger("je_action_core.test")
    reporter = LoggingReporter(logger, empty_message="nothing to do")
    with caplog.at_level(logging.ERROR, logger="je_action_core.test"):
        reporter.on_empty([])
    assert caplog.records[0].getMessage() == "Execute [] failed. nothing to do"


def test_print_reporter(capsys):
    _executor(reporter=PrintReporter()).execute_action([["add", [1]], ["boom"]])
    captured = capsys.readouterr()
    assert captured.out.splitlines() == ["execute: ['add', [1]]", "1", "execute: ['boom']", "RuntimeError('boom')"]
    assert captured.err.splitlines() == ["RuntimeError('boom')", "['boom']"]
