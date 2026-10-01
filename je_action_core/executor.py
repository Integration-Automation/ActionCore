"""
The action executor: run every action of a list and record each result.

One action failing does not stop the list: its record holds ``repr(error)`` (or what
:attr:`ExecutorSettings.failure_record` makes of the error) and the next action runs. What differs between
projects (where the list is, how an action is read, how a record is keyed, what a failure records, what is
reported) is set by :class:`ExecutorSettings`. :meth:`ActionExecutor.attempt` is the place to wrap every action,
e.g. in retries or a tracing span.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Tuple

from je_action_core.action_list import ActionParser, BoundAction, LegacyActionParser
from je_action_core.json_io import read_action_json
from je_action_core.registry import Command, CommandRegistry
from je_action_core.reporting import ExecutionReporter


def plain_record_key(_index: int, action: Any) -> str:
    """``"execute: <action>"``: a repeated identical action keeps only its last result."""
    return f"execute: {action}"


def indexed_record_key(index: int, action: Any) -> str:
    """``"execute[<index>]: <action>"``: every action keeps its own result."""
    return f"execute[{index}]: {action}"


def unique_record_key(records: Mapping[str, Any], key: str) -> str:
    """``key``, or ``key #N`` with the lowest ``N`` from 2 up that ``records`` does not have yet."""
    if key not in records:
        return key
    suffix = 2
    while f"{key} #{suffix}" in records:
        suffix += 1
    return f"{key} #{suffix}"


def repr_failure(_action: Any, error: Exception) -> str:
    """The default record of a failed action: ``repr(error)``."""
    return repr(error)


class DuplicateKeys(Enum):
    """What happens when two actions of one list get the same record key."""

    REPLACE = "replace"  # the later result replaces the earlier one
    NUMBER = "number"  # the later one is keyed ``<key> #2``, ``<key> #3`` ... (see unique_record_key)


class ActionListSource(Protocol):
    """Finds the actions to run in what was passed to an executor (:class:`ActionListRules` is one)."""

    def extract(self, action_list: Any) -> Optional[list]:
        """Return the actions to run, or ``None`` to run nothing; raise when ``action_list`` is invalid."""


@dataclass(frozen=True)
class ExecutorSettings:
    """
    What makes one project's executor different from another's.

    :param rules: where the action list is and what is wrong with a bad one (usually :class:`ActionListRules`).
    :param parser: binds one action to its command.
    :param reporter: hears about every action and the final records.
    :param read_json: reads an action file for :meth:`ActionExecutor.execute_files`.
    :param record_key: names the record of an action from its index and the action as given.
    :param prepare: rewrites an action just before it is bound (the record key still uses the action as given).
    :param failure_record: the record of an action that raised, from the action and the error.
    :param duplicate_keys: whether a repeated record key replaces the earlier record or is numbered.
    """

    rules: ActionListSource
    parser: ActionParser = field(default_factory=LegacyActionParser)
    reporter: ExecutionReporter = field(default_factory=ExecutionReporter)
    read_json: Callable[[str], Any] = read_action_json
    record_key: Callable[[int, Any], str] = plain_record_key
    prepare: Optional[Callable[[Any], Any]] = None
    failure_record: Callable[[Any, Exception], Any] = repr_failure
    duplicate_keys: DuplicateKeys = DuplicateKeys.REPLACE


class ActionExecutor:
    """Runs action lists against a :class:`CommandRegistry`."""

    def __init__(self, settings: ExecutorSettings, registry: Optional[CommandRegistry] = None) -> None:
        self.settings = settings
        self.registry = registry if registry is not None else CommandRegistry()

    @property
    def event_dict(self) -> Dict[str, Command]:
        """The live name -> command mapping of :attr:`registry`."""
        return self.registry.event_dict

    @event_dict.setter
    def event_dict(self, commands: Dict[str, Command]) -> None:
        self.registry.event_dict = commands

    def _execute_event(self, action: Any) -> Any:
        """Run one action and return what its command returned; raise what binding or the command raised."""
        self.settings.reporter.on_event(action)
        prepared = self.settings.prepare(action) if self.settings.prepare is not None else action
        return self.invoke(self.settings.parser.bind(prepared, self.registry.resolve))

    def invoke(self, bound: BoundAction) -> Any:
        """Call the bound command (override to wrap every call, e.g. in a tracing span)."""
        return bound.command(*bound.args, **bound.kwargs)

    def attempt(self, action: Any) -> Any:
        """
        Run one action and return what its command returned; raise what it raised.

        Every action of a list passes here once. Override to wrap each one, e.g. in retries or a tracing span
        (:meth:`invoke` wraps only the call of the bound command).
        """
        return self._execute_event(action)

    def _recorded(self, action: Any) -> Tuple[Any, bool]:
        """``(record, succeeded)`` for one action: its result, or :attr:`ExecutorSettings.failure_record`."""
        try:
            value = self.attempt(action)
        except Exception as error:  # noqa: BLE001 - one failing action must not stop the list; it is recorded
            self.settings.reporter.on_failure(action, error)
            return self.settings.failure_record(action, error), False
        self.settings.reporter.on_success(action)
        return value, True

    def run_one(self, action: Any) -> Any:
        """Run one action; return its result, or its failure record (``repr(error)`` by default) when it raised."""
        return self._recorded(action)[0]

    def _actions(self, action_list: Any) -> Optional[list]:
        self.settings.reporter.on_start(action_list)
        actions = self.settings.rules.extract(action_list)
        if actions is None:
            self.settings.reporter.on_empty(action_list)
        return actions

    def _run_all(self, actions: list) -> Tuple[Dict[str, Any], List[str]]:
        records: Dict[str, Any] = {}
        failed: List[str] = []
        for index, action in enumerate(actions):
            key = self.settings.record_key(index, action)
            if self.settings.duplicate_keys is DuplicateKeys.NUMBER:
                key = unique_record_key(records, key)
            record, succeeded = self._recorded(action)
            records[key] = record
            if not succeeded:
                failed.append(key)
        return records, failed

    def collect_action_results(self, action_list: Any) -> Tuple[Dict[str, Any], List[str]]:
        """
        Run ``action_list`` like :meth:`execute_action`, but leave the records unreported.

        :return: ``(records, failed)``: the records, and the keys of the actions that raised, in order.
        :raises: what ``rules.extract`` raises for an invalid document or list.
        """
        actions = self._actions(action_list)
        if actions is None:
            return {}, []
        return self._run_all(actions)

    def execute_action(self, action_list: Any) -> Dict[str, Any]:
        """
        Run every action of ``action_list`` (a list, or a document holding one), report and return the records.

        :raises: what ``rules.extract`` raises for an invalid document or list (see :class:`ActionListRules`).
        """
        actions = self._actions(action_list)
        if actions is None:
            return {}
        records, _failed = self._run_all(actions)
        self.settings.reporter.on_records(records)
        return records

    def execute_files(self, execute_files_list: List[str]) -> List[Dict[str, Any]]:
        """Run the action file at every path, in order, and return their records."""
        return [self.execute_action(self.settings.read_json(path)) for path in execute_files_list]

    def add_command_to_executor(self, command_dict: Mapping[str, Command]) -> None:
        """Add commands from a caller under :attr:`registry`'s policy (the first refused one raises)."""
        self.registry.add_commands(command_dict)
