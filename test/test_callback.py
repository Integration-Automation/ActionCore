import pytest

from je_action_core import (
    CallbackErrorPolicy,
    CallbackExecutorException,
    CallbackFunctionExecutor,
    CallbackSettings,
    CallbackStyle,
    CommandRegistry,
)


def _executor(**settings):
    calls = []
    registry = CommandRegistry({"trigger": lambda **kwargs: calls.append(("trigger", kwargs)) or "result"})
    return CallbackFunctionExecutor(registry, CallbackSettings(**settings)), calls


def _callback_recorder(calls):
    return lambda *args, **kwargs: calls.append(("callback", args, kwargs))


@pytest.mark.parametrize("style", list(CallbackStyle))
def test_runs_trigger_then_callback(style):
    executor, calls = _executor(style=style)
    callback = _callback_recorder(calls)
    assert executor.callback_function("trigger", callback, {"a": 1}, value=2) == "result"
    assert executor.callback_function("trigger", callback, [3], "args") == "result"
    assert executor.callback_function("trigger", callback) == "result"
    assert calls == [("trigger", {"value": 2}), ("callback", (), {"a": 1}),
                     ("trigger", {}), ("callback", (3,), {}),
                     ("trigger", {}), ("callback", (), {})]


def test_unknown_trigger_and_bad_method_raise_by_default():
    executor, calls = _executor(unknown_trigger_message="no {name}", bad_method_message="bad {method}")
    with pytest.raises(CallbackExecutorException, match="no missing"):
        executor.callback_function("missing", print)
    with pytest.raises(CallbackExecutorException, match="bad positional"):
        executor.callback_function("trigger", print, [1], "positional")
    assert calls == [("trigger", {})]  # legacy style: the trigger ran before the method was checked


def test_strict_style_checks_the_method_and_payload_first():
    executor, calls = _executor(style=CallbackStyle.STRICT)
    with pytest.raises(CallbackExecutorException, match="must be 'kwargs' or 'args'"):
        executor.callback_function("trigger", print, None, "positional")
    assert calls == []
    with pytest.raises(CallbackExecutorException, match="requires a mapping"):
        executor.callback_function("trigger", print, [1], "kwargs")
    with pytest.raises(CallbackExecutorException, match="requires a list/tuple"):
        executor.callback_function("trigger", print, {"a": 1}, "args")


def test_return_none_policy_logs_instead_of_raising():
    errors = []
    executor, _calls = _executor(on_error=CallbackErrorPolicy.RETURN_NONE, log_error=errors.append)
    assert executor.callback_function("missing", print) is None
    assert errors[0].startswith("CallbackExecutorException(")


def test_raise_policy_logs_and_reraises_callback_errors():
    errors = []
    executor, _calls = _executor(log_error=errors.append)

    def failing_callback():
        raise ValueError("cb")
    with pytest.raises(ValueError):
        executor.callback_function("trigger", failing_callback)
    assert errors == ["ValueError('cb')"]


def test_event_dict_is_the_registry_mapping():
    executor = CallbackFunctionExecutor()
    executor.event_dict["t"] = lambda: 1
    assert executor.callback_function("t", lambda: None) == 1
    executor.event_dict = {}
    assert "t" not in executor.registry
