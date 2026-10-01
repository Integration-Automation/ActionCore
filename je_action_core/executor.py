"""
The action executor: run every action of a list and record each result.

One action failing does not stop the list: its record holds ``repr(error)`` and the next action runs. What
differs between projects (where the list is, how an action is read, how a record is keyed, what is reported)
is set by :class:`ExecutorSettings`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional

from je_action_core.action_list import ActionListRules, ActionParser, BoundAction, LegacyActionParser
from je_action_core.json_io import read_action_json
from je_action_core.registry import Command, CommandRegistry
from je_action_core.reporting import ExecutionReporter


def plain_record_key(_index: int, action: Any) -> str:
    """``"execute: <action>"``: a repeated identical action keeps only its last result."""
    return f"execute: {action}"


def indexed_record_key(index: int, action: Any) -> str:
    """``"execute[<index>]: <action>"``: every action keeps its own result."""
    return f"execute[{index}]: {action}"


@dataclass(frozen=True)
class ExecutorSettings:
    """
    What makes one project's executor different from another's.

    :param rules: where the action list is and what is wrong with a bad one.
    :param parser: binds one action to its command.
    :param reporter: hears about every action and the final records.
    :param read_json: reads an action file for :meth:`ActionExecutor.execute_files`.
    :param record_key: names the record of an action from its index and the action as given.
    :param prepare: rewrites an action just before it is bound (the record key still uses the action as given).
    """

    rules: ActionListRules
    parser: ActionParser = field(default_factory=LegacyActionParser)
    reporter: ExecutionReporter = field(default_factory=ExecutionReporter)
    read_json: Callable[[str], Any] = read_action_json
    record_key: Callable[[int, Any], str] = plain_record_key
    prepare: Optional[Callable[[Any], Any]] = None


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

    def run_one(self, action: Any) -> Any:
        """Run one action; return its result, or ``repr(error)`` when it raised."""
        try:
            value = self._execute_event(action)
        except Exception as error:  # noqa: BLE001 - one failing action must not stop the list; repr is its record
            self.settings.reporter.on_failure(action, error)
            return repr(error)
        self.settings.reporter.on_success(action)
        return value

    def execute_action(self, action_list: Any) -> Dict[str, Any]:
        """
        Run every action of ``action_list`` (a list, or a document holding one) and return the records.

        :raises rules.error: the document or list is invalid (see :class:`ActionListRules`).
        """
        actions = self.settings.rules.extract(action_list)
        if actions is None:
            self.settings.reporter.on_empty(action_list)
            return {}
        records: Dict[str, Any] = {}
        for index, action in enumerate(actions):
            records[self.settings.record_key(index, action)] = self.run_one(action)
        self.settings.reporter.on_records(records)
        return records

    def execute_files(self, execute_files_list: List[str]) -> List[Dict[str, Any]]:
        """Run the action file at every path, in order, and return their records."""
        return [self.execute_action(self.settings.read_json(path)) for path in execute_files_list]

    def add_command_to_executor(self, command_dict: Mapping[str, Command]) -> None:
        """Add commands from a caller under :attr:`registry`'s policy (the first refused one raises)."""
        self.registry.add_commands(command_dict)
