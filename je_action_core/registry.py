"""Commands by name, shared by an executor and its callback executor."""
from __future__ import annotations

import types
from enum import Enum
from typing import Callable, Dict, Iterator, KeysView, Mapping, Optional

from je_action_core.exceptions import AddCommandException

Command = Callable[..., object]


class CommandPolicy(Enum):
    """What :meth:`CommandRegistry.add_commands` accepts from callers."""

    FUNCTIONS_ONLY = "functions_only"  # plain functions and bound methods
    ANY_CALLABLE = "any_callable"


def _default_rejection(name: str) -> Exception:
    return AddCommandException(f"{name!r} is not an accepted command")


class CommandRegistry:
    """
    Commands by name.

    Commands given to the constructor, :meth:`register` or :meth:`register_many` are the project's own: they
    only have to be callable. :meth:`add_commands` is the path for commands from callers and also applies
    :attr:`policy`. ``event_dict`` is the live mapping, so code that updates ``executor.event_dict`` in place
    keeps working.
    """

    def __init__(self, commands: Optional[Mapping[str, Command]] = None, *,
                 policy: CommandPolicy = CommandPolicy.ANY_CALLABLE,
                 rejection: Callable[[str], Exception] = _default_rejection) -> None:
        """
        :param commands: initial commands.
        :param policy: what :meth:`add_commands` accepts.
        :param rejection: builds the exception raised for a refused command, given its name.
        """
        self._commands: Dict[str, Command] = {}
        self.policy = policy
        self._rejection = rejection
        self.register_many(commands or {})

    @property
    def event_dict(self) -> Dict[str, Command]:
        """The live name -> command mapping."""
        return self._commands

    @event_dict.setter
    def event_dict(self, commands: Dict[str, Command]) -> None:
        self._commands = commands

    def register(self, name: str, command: Command) -> None:
        """Add or replace ``name``; raises the rejection exception when ``command`` is not callable."""
        if not callable(command):
            raise self._rejection(name)
        self._commands[name] = command

    def register_many(self, commands: Mapping[str, Command]) -> None:
        """:meth:`register` every pair of ``commands``."""
        for name, command in commands.items():
            self.register(name, command)

    def update(self, commands: Mapping[str, Command]) -> None:
        """Alias of :meth:`register_many`, so the registry can stand in for a dict."""
        self.register_many(commands)

    def add_commands(self, commands: Mapping[str, Command]) -> None:
        """
        Add commands from a caller. The first command :attr:`policy` refuses raises; the ones before it stay.
        """
        for name, command in commands.items():
            if not self.accepts(command):
                raise self._rejection(name)
            self._commands[name] = command

    def accepts(self, command: object) -> bool:
        """True when :attr:`policy` lets :meth:`add_commands` take ``command``."""
        if self.policy is CommandPolicy.FUNCTIONS_ONLY:
            return isinstance(command, (types.FunctionType, types.MethodType))
        return callable(command)

    def resolve(self, name: object) -> Optional[Command]:
        """The command called ``name``, or ``None``. An unhashable name raises ``TypeError``, as a dict does."""
        return self._commands.get(name)  # type: ignore[call-overload]

    def unregister(self, name: str) -> None:
        """Remove ``name`` if present."""
        self._commands.pop(name, None)

    def names(self) -> KeysView[str]:
        """The registered names."""
        return self._commands.keys()

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._commands

    def __len__(self) -> int:
        return len(self._commands)

    def __iter__(self) -> Iterator[str]:
        return iter(self._commands)
