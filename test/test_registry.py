import pytest

from je_action_core import AddCommandException, CommandPolicy, CommandRegistry


def _function():
    return "f"


class _Holder:
    def method(self):
        return "m"


def test_constructor_and_register_only_require_callables():
    registry = CommandRegistry({"f": _function, "len": len})
    registry.register("cls", dict)
    assert registry.resolve("f") is _function
    assert set(registry.names()) == {"f", "len", "cls"}
    with pytest.raises(AddCommandException):
        registry.register("x", 3)


def test_functions_only_policy_refuses_builtins_and_classes():
    registry = CommandRegistry(policy=CommandPolicy.FUNCTIONS_ONLY)
    registry.add_commands({"f": _function, "m": _Holder().method})
    assert registry.resolve("m")() == "m"
    for refused in (len, dict, object()):
        with pytest.raises(AddCommandException):
            registry.add_commands({"bad": refused})
    assert "bad" not in registry


def test_any_callable_policy_and_custom_rejection():
    registry = CommandRegistry(rejection=lambda name: ValueError(f"no {name}"))
    registry.add_commands({"len": len})
    with pytest.raises(ValueError, match="no x"):
        registry.add_commands({"x": "not callable"})


def test_earlier_commands_stay_when_a_later_one_is_refused():
    registry = CommandRegistry(policy=CommandPolicy.FUNCTIONS_ONLY)
    with pytest.raises(AddCommandException):
        registry.add_commands({"ok": _function, "bad": len})
    assert "ok" in registry and "bad" not in registry


def test_event_dict_is_live_and_replaceable():
    registry = CommandRegistry()
    registry.event_dict["f"] = _function
    assert registry.resolve("f") is _function
    registry.event_dict = {"g": len}
    assert list(registry) == ["g"] and len(registry) == 1
    registry.update({"h": abs})
    registry.unregister("g")
    registry.unregister("missing")
    assert list(registry) == ["h"]


def test_membership_needs_a_string_and_unhashable_names_raise():
    registry = CommandRegistry({"f": _function})
    assert 1 not in registry
    with pytest.raises(TypeError):
        registry.resolve(["f"])
