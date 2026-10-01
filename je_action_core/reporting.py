"""What an executor reports while it runs: to a logger, to the console, or nowhere."""
from __future__ import annotations

import logging
import sys
from typing import Any, Mapping


class ExecutionReporter:
    """Hooks :class:`~je_action_core.executor.ActionExecutor` calls; this base class reports nothing."""

    def on_event(self, action: Any) -> None:
        """An action is about to be bound and run."""

    def on_success(self, action: Any) -> None:
        """``action`` returned normally."""

    def on_failure(self, action: Any, error: Exception) -> None:
        """``action`` raised ``error``; its record holds ``repr(error)``."""

    def on_empty(self, action_list: Any) -> None:
        """Under ``EmptyListPolicy.RETURN_EMPTY``, ``action_list`` had nothing to run."""

    def on_records(self, records: Mapping[str, Any]) -> None:
        """Every action has run; ``records`` is what ``execute_action`` returns."""


class LoggingReporter(ExecutionReporter):
    """Reports to ``logger``: each event at DEBUG, success and records at INFO, failures at ERROR."""

    def __init__(self, logger: logging.Logger, empty_message: str = "action list is empty") -> None:
        self.logger = logger
        self.empty_message = empty_message

    def on_event(self, action: Any) -> None:
        self.logger.debug(f"Execute event {action}")

    def on_success(self, action: Any) -> None:
        self.logger.info(f"Execute {action}")

    def on_failure(self, action: Any, error: Exception) -> None:
        self.logger.error(f"Execute {action} failed. {error!r}")

    def on_empty(self, action_list: Any) -> None:
        self.logger.error(f"Execute {action_list} failed. {self.empty_message}")

    def on_records(self, records: Mapping[str, Any]) -> None:
        for key, value in records.items():
            self.logger.info(f"{key} -> {value}")


class PrintReporter(ExecutionReporter):
    """
    Reports to the console, for command-line tools whose output is the record: a failure prints its ``repr``
    and the action to stderr, and every record prints its key and value on two lines of stdout.
    """

    def on_failure(self, action: Any, error: Exception) -> None:
        print(repr(error), file=sys.stderr)
        print(action, file=sys.stderr)

    def on_records(self, records: Mapping[str, Any]) -> None:
        for key, value in records.items():
            print(key)
            print(value)
