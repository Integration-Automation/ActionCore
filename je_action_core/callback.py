"""
The callback executor: run a named trigger command, then a callback, and return the trigger's result.

``callback_param_method`` says how ``callback_function_param`` reaches the callback: ``"kwargs"`` unpacks a
mapping, ``"args"`` a sequence. With no parameters the callback is called with none.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional, Type, Union, cast

from je_action_core.exceptions import CallbackExecutorException
from je_action_core.registry import Command, CommandRegistry

_PARAM_METHODS = ("kwargs", "args")
CallbackParam = Union[Mapping, list, tuple, None]


def _discard(_message: str) -> None:
    """Default log hook: report nothing."""


class CallbackStyle(Enum):
    """How strictly the call is checked."""

    LEGACY = "legacy"  # the trigger runs first; the method is checked only when there are parameters
    STRICT = "strict"  # the method is checked first; kwargs need a mapping, args a list or tuple


class CallbackErrorPolicy(Enum):
    """What happens when the trigger, the callback or a check raises (the error is logged either way)."""

    RETURN_NONE = "return_none"
    RAISE = "raise"


@dataclass(frozen=True)
class CallbackSettings:
    """
    ``unknown_trigger_message`` is a ``str.format`` template with ``name``; ``bad_method_message`` has
    ``method``.
    """

    error: Type[Exception] = CallbackExecutorException
    unknown_trigger_message: str = "unknown trigger: {name!r}"
    bad_method_message: str = "callback_param_method must be 'kwargs' or 'args', got {method!r}"
    style: CallbackStyle = CallbackStyle.LEGACY
    on_error: CallbackErrorPolicy = CallbackErrorPolicy.RAISE
    log_info: Callable[[str], None] = _discard
    log_error: Callable[[str], None] = _discard


_DEFAULT_SETTINGS = CallbackSettings()


class CallbackFunctionExecutor:
    """Runs a trigger from :attr:`registry`, then a callback."""

    def __init__(self, registry: Optional[CommandRegistry] = None,
                 settings: CallbackSettings = _DEFAULT_SETTINGS) -> None:
        self.registry = registry if registry is not None else CommandRegistry()
        self.settings = settings

    @property
    def event_dict(self) -> Dict[str, Command]:
        """The live name -> trigger mapping of :attr:`registry`."""
        return self.registry.event_dict

    @event_dict.setter
    def event_dict(self, commands: Dict[str, Command]) -> None:
        self.registry.event_dict = commands

    def callback_function(self, trigger_function_name: str, callback_function: Callable[..., Any],
                          callback_function_param: CallbackParam = None,
                          callback_param_method: str = "kwargs", **kwargs: Any) -> Any:
        """
        Run the trigger with ``kwargs``, then the callback, and return the trigger's result.

        :raises settings.error: the trigger is unknown or the parameters do not fit the method, under
            :attr:`CallbackErrorPolicy.RAISE` (otherwise the error is logged and ``None`` returned).
        """
        self.settings.log_info(
            f"callback_function trigger_function_name: {trigger_function_name} "
            f"callback_function_param: {callback_function_param} "
            f"callback_param_method: {callback_param_method} kwargs: {kwargs}")
        try:
            trigger = self._trigger(trigger_function_name)
            if self.settings.style is CallbackStyle.STRICT:
                self._check_method(callback_param_method)
            return_value = trigger(**kwargs)
            self._call_back(callback_function, callback_function_param, callback_param_method)
        except Exception as error:  # noqa: BLE001 - logged, then raised or turned into None by the policy
            self.settings.log_error(repr(error))
            if self.settings.on_error is CallbackErrorPolicy.RAISE:
                raise
            return None
        return return_value

    def _trigger(self, name: str) -> Command:
        trigger = self.registry.resolve(name)
        if trigger is None:
            raise self.settings.error(self.settings.unknown_trigger_message.format(name=name))
        return trigger

    def _check_method(self, method: str) -> None:
        if method not in _PARAM_METHODS:
            raise self.settings.error(self.settings.bad_method_message.format(method=method))

    def _call_back(self, callback: Callable[..., Any], param: CallbackParam, method: str) -> None:
        if param is None:
            callback()
            return
        self._check_method(method)
        if method == "kwargs":
            if self.settings.style is CallbackStyle.STRICT and not isinstance(param, Mapping):
                raise self.settings.error("callback_param_method='kwargs' requires a mapping payload")
            # LEGACY passes any payload on, and a non-mapping fails in the call as it always has
            callback(**cast(Mapping[str, Any], param))
            return
        if self.settings.style is CallbackStyle.STRICT and not isinstance(param, (list, tuple)):
            raise self.settings.error("callback_param_method='args' requires a list/tuple payload")
        callback(*param)
