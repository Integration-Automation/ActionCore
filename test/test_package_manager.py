import types
import warnings
from inspect import isfunction
from unittest.mock import patch

import pytest

from je_action_core import (
    MemberNaming,
    PackageGate,
    PackageManager,
    PackageManagerSettings,
    PackageNotAllowedException,
    is_identifier_path,
    is_module_name,
)
from je_action_core import package_manager as package_manager_module


def _manager(**settings):
    manager = PackageManager(PackageManagerSettings(**settings))
    manager.executor = types.SimpleNamespace(event_dict={})
    return manager


def test_name_checks():
    assert is_module_name("os.path") and not is_module_name("os..path") and not is_module_name(3)
    assert not is_module_name("模組")
    assert is_identifier_path("模組.sub") and not is_identifier_path("") and not is_identifier_path("1x")


class TestGate:

    def test_unconfigured_gate_warns_but_loads(self):
        manager = _manager()
        with pytest.warns(DeprecationWarning, match="not on the allowlist"):
            assert manager.add_package_to_executor("json") > 0
        assert "json_dumps" in manager.executor.event_dict

    def test_closed_gate_refuses_before_importing(self):
        manager = _manager(refused=KeyError)
        manager.set_allow_arbitrary_packages(False)
        with patch.object(package_manager_module, "import_module") as importer:
            with pytest.raises(KeyError, match="not allowed"):
                manager.add_package_to_executor("os")
            importer.assert_not_called()
        assert manager.executor.event_dict == {}

    def test_closed_gate_covers_the_callback_executor(self):
        manager = PackageManager()
        manager.callback_executor = types.SimpleNamespace(event_dict={})
        manager.set_allow_arbitrary_packages(False)
        with pytest.raises(PackageNotAllowedException):
            manager.add_package_to_callback_executor("subprocess")

    def test_allowlist_covers_submodules_only(self):
        manager = _manager()
        manager.set_allow_arbitrary_packages(False)
        manager.allow_packages("json")
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            manager.add_package_to_executor("json")
            manager.add_package_to_executor("json.decoder")
        assert "json.decoder_JSONDecoder" in manager.executor.event_dict
        with pytest.raises(PackageNotAllowedException):
            manager.add_package_to_executor("jsonschema_lookalike")

    def test_open_gate_and_gate_off_load_silently(self):
        for manager in (_manager(), _manager(gate=PackageGate.OFF)):
            if manager.settings.gate is PackageGate.ON:
                manager.set_allow_arbitrary_packages(True)
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                manager.add_package_to_executor("json")
            assert "json_dumps" in manager.executor.event_dict


class TestLoading:

    def test_prefixed_names_cover_functions_builtins_and_classes(self):
        manager = _manager(gate=PackageGate.OFF)
        manager.add_package_to_executor("json")
        assert {"json_dumps", "json_JSONDecoder"} <= set(manager.executor.event_dict)
        assert manager.check_package("json") is manager.installed_package_dict["json"]

    def test_bare_names_with_functions_only(self):
        manager = _manager(gate=PackageGate.OFF, naming=MemberNaming.BARE, predicates=(isfunction,))
        manager.add_package_to_executor("json")
        assert "dumps" in manager.executor.event_dict
        assert "JSONDecoder" not in manager.executor.event_dict

    def test_missing_package_and_missing_target_are_logged(self):
        errors = []
        manager = _manager(gate=PackageGate.OFF, log_error=errors.append)
        assert manager.add_package_to_executor("no_such_package_xyz") == 0
        manager.executor = None
        assert manager.add_package_to_executor("json") == 0
        assert errors[0].startswith("ModuleNotFoundError(")
        assert errors[-1] == "Executor error None"

    def test_name_check_rejects_before_find_spec(self):
        errors = []
        manager = _manager(gate=PackageGate.OFF, name_check=is_module_name, log_error=errors.append)
        with patch.object(package_manager_module, "find_spec") as finder:
            assert manager.check_package("os;rm") is None
            finder.assert_not_called()
        assert errors == ["rejected package name: 'os;rm'"]

    def test_import_errors_are_logged_and_others_raise(self):
        errors = []
        manager = _manager(gate=PackageGate.OFF, log_error=errors.append)
        with patch.object(package_manager_module, "import_module", side_effect=ModuleNotFoundError("gone")):
            assert manager.check_package("json") is None
        assert errors == ["ModuleNotFoundError('gone')"]
        broken = patch.object(package_manager_module, "import_module", side_effect=ImportError("broken"))
        with broken, pytest.raises(ImportError):
            manager.check_package("json")

    def test_handled_errors_are_logged_instead_of_raised(self):
        errors = []
        manager = _manager(gate=PackageGate.OFF, handled=(ImportError,), log_error=errors.append)
        assert manager.add_package_to_executor("no_parent_xyz.child") == 0
        assert errors and "ModuleNotFoundError" in errors[0]
        with pytest.raises(ImportError):
            _manager(gate=PackageGate.OFF).add_package_to_executor("no_parent_xyz.child")
