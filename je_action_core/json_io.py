"""Reading and writing action files: UTF-8 JSON, one lock per file object, the project's own exception."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Tuple, Type

from je_action_core.exceptions import ActionJsonException

_INDENT: int = 4


def _discard(_message: str) -> None:
    """Default log hook: report nothing."""


@dataclass(frozen=True)
class JsonFileMessages:
    """``str.format`` templates for the exception messages; each gets ``path``, and ``error`` when there is one."""

    missing: str = "can't find JSON file: {path}"
    unreadable: str = "can't read JSON file: {path}: {error}"
    unwritable: str = "can't write JSON file: {path}: {error}"


@dataclass(frozen=True)
class JsonFileSettings:
    """
    How :class:`ActionJsonFile` reports problems.

    ``read_errors`` and ``write_errors`` are the exceptions turned into ``error``; any other exception
    propagates unchanged.
    """

    error: Type[Exception] = ActionJsonException
    messages: JsonFileMessages = JsonFileMessages()
    read_errors: Tuple[Type[BaseException], ...] = (OSError, ValueError)
    write_errors: Tuple[Type[BaseException], ...] = (OSError, TypeError, ValueError)
    log_info: Callable[[str], None] = _discard


_DEFAULT_SETTINGS = JsonFileSettings()


class ActionJsonFile:
    """Reads and writes action files; reads and writes on one object never overlap."""

    def __init__(self, settings: JsonFileSettings = _DEFAULT_SETTINGS) -> None:
        self.settings = settings
        self._lock = Lock()

    def read(self, json_file_path: str) -> Any:
        """
        Return the parsed content of ``json_file_path`` (UTF-8).

        :raises settings.error: the file is missing, or reading or parsing it raised one of ``read_errors``
            (the cause is chained).
        """
        settings = self.settings
        settings.log_info(f"read_action_json: {json_file_path}")
        try:
            file_path = Path(json_file_path)
            found = file_path.is_file()
        except settings.read_errors as error:
            raise settings.error(settings.messages.unreadable.format(path=json_file_path, error=error)) from error
        if not found:
            raise settings.error(settings.messages.missing.format(path=json_file_path))
        with self._lock:
            try:
                with open(file_path, encoding="utf-8") as read_file:
                    return json.load(read_file)
            except settings.read_errors as error:
                raise settings.error(
                    settings.messages.unreadable.format(path=json_file_path, error=error)) from error

    def write(self, json_save_path: str, action_json: Any) -> None:
        """
        Write ``action_json`` to ``json_save_path`` as indented UTF-8 JSON with non-ASCII text kept as is.

        The JSON is built before the file is opened, so data that cannot be serialised leaves the file as it was.

        :raises settings.error: serialising or writing raised one of ``write_errors`` (the cause is chained).
        """
        settings = self.settings
        settings.log_info(f"write_action_json: {json_save_path}")
        with self._lock:
            try:
                content = json.dumps(action_json, indent=_INDENT, ensure_ascii=False)
                with open(json_save_path, "w", encoding="utf-8") as file_to_write:
                    file_to_write.write(content)
            except settings.write_errors as error:
                raise settings.error(
                    settings.messages.unwritable.format(path=json_save_path, error=error)) from error


_default_json_file = ActionJsonFile()


def read_action_json(json_file_path: str) -> Any:
    """:meth:`ActionJsonFile.read` with the default settings (raises :class:`ActionJsonException`)."""
    return _default_json_file.read(json_file_path)


def write_action_json(json_save_path: str, action_json: Any) -> None:
    """:meth:`ActionJsonFile.write` with the default settings (raises :class:`ActionJsonException`)."""
    _default_json_file.write(json_save_path, action_json)
