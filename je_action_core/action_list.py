"""
Action documents and single actions.

An action document is a list of actions, or a mapping that keeps the list under one key (``{"api_testka": [...]}``).
An action is ``[name]``, ``[name, {kwargs}]`` or ``[name, [args]]``. :class:`ActionListRules` finds the list;
a parser binds one action to its command.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, NamedTuple, Optional, Protocol, Tuple, Type

from je_action_core.exceptions import ActionExecuteException

Resolver = Callable[[Any], Optional[Callable[..., Any]]]
_NAME_ONLY: int = 1
_NAME_AND_PAYLOAD: int = 2
# warnings.warn -> from_document -> extract -> ActionExecutor.execute_action -> the caller of execute_action
_LEGACY_KEY_STACKLEVEL: int = 4


class EmptyListPolicy(Enum):
    """What an executor does with an empty action list, or with something that is not a list."""

    RAISE = "raise"
    RETURN_EMPTY = "return_empty"  # run nothing and return an empty record


@dataclass(frozen=True)
class ActionListRules:
    """
    Where a document keeps its action list and what is wrong with a bad one.

    The messages are ``str.format`` templates: ``missing_message`` gets ``key``, ``not_list_message`` gets
    ``type`` (the type name of what was found).
    """

    key: str
    legacy_keys: Tuple[str, ...] = ()
    error: Type[Exception] = ActionExecuteException
    missing_message: str = "action document has no {key!r} list"
    not_list_message: str = "action list must be a list, got {type}"
    empty_message: str = "action list is empty"
    empty: EmptyListPolicy = EmptyListPolicy.RAISE

    def extract(self, action_list: Any) -> Optional[list]:
        """
        Return the actions to run, or ``None`` when :attr:`empty` says to run nothing.

        :raises error: the document has no list under :attr:`key` (or a legacy key), or, under
            :attr:`EmptyListPolicy.RAISE`, the list is not a list or is empty.
        """
        actions = action_list
        if isinstance(action_list, Mapping):
            actions = self.from_document(action_list, stacklevel=_LEGACY_KEY_STACKLEVEL)
            if actions is None:
                raise self.error(self.missing_message.format(key=self.key))
        if isinstance(actions, list) and actions:
            return actions
        if self.empty is EmptyListPolicy.RETURN_EMPTY:
            return None
        if not isinstance(actions, list):
            raise self.error(self.not_list_message.format(type=type(actions).__name__))
        raise self.error(self.empty_message)

    def from_document(self, document: Mapping[str, Any], stacklevel: int = 2) -> Any:
        """
        The value under :attr:`key`, else under the first legacy key present (with a ``DeprecationWarning``
        attributed ``stacklevel`` frames up), else ``None``. The value is returned as found, unchecked.
        """
        if self.key in document:
            return document[self.key]
        for legacy_key in self.legacy_keys:
            if legacy_key in document:
                warnings.warn(f'the "{legacy_key}" key is deprecated; use "{self.key}"', DeprecationWarning,
                              stacklevel=stacklevel)
                return document[legacy_key]
        return None


class BoundAction(NamedTuple):
    """An action bound to its command; calling it is ``command(*args, **kwargs)``."""

    name: Any
    command: Callable[..., Any]
    args: Iterable[Any] = ()
    kwargs: Mapping[str, Any] = MappingProxyType({})


class ActionParser(Protocol):
    """Binds one action to its command."""

    def bind(self, action: Any, resolve: Resolver) -> BoundAction:
        """Return ``action`` bound to the command ``resolve`` finds for its name; raise when it cannot."""


@dataclass(frozen=True)
class LegacyActionParser:
    """
    The rules APITestka, LoadDensity and MailThunder have always used.

    The name is looked up first. A dict payload is passed as keyword arguments and any other payload is
    unpacked as positional arguments. An unknown name or more than two elements raises ``error`` with
    ``f"{message} {action}"``. An empty action raises ``IndexError``.
    """

    error: Type[Exception] = ActionExecuteException
    message: str = "invalid action"

    def bind(self, action: Any, resolve: Resolver) -> BoundAction:
        """See the class docstring."""
        command = resolve(action[0])
        if command is None:
            raise self.error(f"{self.message} {action}")
        if len(action) == _NAME_AND_PAYLOAD:
            payload = action[1]
            if isinstance(payload, dict):
                return BoundAction(action[0], command, (), payload)
            return BoundAction(action[0], command, payload, {})
        if len(action) == _NAME_ONLY:
            return BoundAction(action[0], command)
        raise self.error(f"{self.message} {action}")


class ParsedAction(NamedTuple):
    """A checked action: ``kind`` is ``"none"``, ``"kwargs"`` or ``"args"``."""

    name: str
    kind: str
    payload: Any


@dataclass(frozen=True)
class StrictActionParser:
    """
    FileAutomation's rules: the action must be a non-empty list, the name a string and the payload a dict or a
    list. The shape is checked before the name is looked up.
    """

    error: Type[Exception] = ActionExecuteException

    def parse(self, action: Any) -> ParsedAction:
        """Check the shape of ``action`` without looking its name up."""
        if not isinstance(action, list) or not action:
            raise self.error(f"malformed action: {action!r}")
        name = action[0]
        if not isinstance(name, str):
            raise self.error(f"action name must be str: {action!r}")
        if len(action) == _NAME_ONLY:
            return ParsedAction(name, "none", None)
        if len(action) == _NAME_AND_PAYLOAD:
            payload = action[1]
            if isinstance(payload, dict):
                return ParsedAction(name, "kwargs", payload)
            if isinstance(payload, list):
                return ParsedAction(name, "args", payload)
            raise self.error(f"action {name!r} payload must be dict or list, got {type(payload).__name__}")
        raise self.error(f"action has too many elements: {action!r}")

    def bind(self, action: Any, resolve: Resolver) -> BoundAction:
        """:meth:`parse`, then look the name up; an unknown name raises ``error``."""
        parsed = self.parse(action)
        command = resolve(parsed.name)
        if command is None:
            raise self.error(f"unknown action: {parsed.name!r}")
        if parsed.kind == "kwargs":
            return BoundAction(parsed.name, command, (), parsed.payload)
        if parsed.kind == "args":
            return BoundAction(parsed.name, command, parsed.payload, {})
        return BoundAction(parsed.name, command)
