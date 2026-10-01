"""
Loading an installed package's members as commands (``*_add_package_to_executor``), behind a package gate.

The gate exists because loading ``os`` or ``subprocess`` this way lets an action list run anything. The host
program, never an action list, decides what may load: :meth:`PackageManager.allow_packages` lists packages
(submodules included), and :meth:`PackageManager.set_allow_arbitrary_packages` opens (True) or closes (False)
the gate for everything else. Until the host calls either one, any package still loads, with a
``DeprecationWarning``.
"""
from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from enum import Enum
from importlib import import_module
from importlib.util import find_spec
from inspect import getmembers, isbuiltin, isclass, isfunction
from types import ModuleType
from typing import Any, Callable, Dict, Optional, Set, Tuple, Type

from je_action_core.exceptions import PackageNotAllowedException

_MODULE_NAME = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", re.ASCII)
# warnings.warn -> _check_allowed -> add_package_to_executor -> the command's caller
_GATE_WARNING_STACKLEVEL: int = 3


def _discard(_message: str) -> None:
    """Default log hook: report nothing."""


def is_module_name(package: object) -> bool:
    """True for a dotted name of ASCII identifiers (``os.path``)."""
    return isinstance(package, str) and _MODULE_NAME.fullmatch(package) is not None


def is_identifier_path(package: object) -> bool:
    """True for a dotted name whose every part is a Python identifier (Unicode allowed)."""
    return isinstance(package, str) and bool(package) and all(part.isidentifier() for part in package.split("."))


class MemberNaming(Enum):
    """How a loaded member is named in the target's commands."""

    PREFIXED = "prefixed"  # "<package>_<member>"
    BARE = "bare"  # "<member>"


class PackageGate(Enum):
    """Whether :class:`PackageManager` checks packages against its allowlist."""

    ON = "on"
    OFF = "off"


@dataclass(frozen=True)
class PackageManagerSettings:
    """
    :param naming: command names of loaded members.
    :param predicates: ``inspect`` predicates; members matching each, in order, are registered.
    :param name_check: a package name must pass this before ``find_spec`` sees it (``None``: no check).
    :param import_errors: exceptions from importing a package that are logged instead of raised.
    :param handled: exceptions from loading members that are logged instead of raised.
    :param gate: whether the package gate applies.
    :param refused: exception raised when the gate refuses a package.
    """

    naming: MemberNaming = MemberNaming.PREFIXED
    predicates: Tuple[Callable[[object], bool], ...] = (isfunction, isbuiltin, isclass)
    name_check: Optional[Callable[[object], bool]] = None
    import_errors: Tuple[Type[BaseException], ...] = (ModuleNotFoundError,)
    handled: Tuple[Type[BaseException], ...] = ()
    gate: PackageGate = PackageGate.ON
    refused: Type[Exception] = PackageNotAllowedException
    log_info: Callable[[str], None] = _discard
    log_error: Callable[[str], None] = _discard


_DEFAULT_SETTINGS = PackageManagerSettings()


class PackageManager:
    """
    Imports packages on request and registers their members into ``executor`` or ``callback_executor``
    (any object with an ``event_dict`` mapping).
    """

    def __init__(self, settings: PackageManagerSettings = _DEFAULT_SETTINGS) -> None:
        self.settings = settings
        self.installed_package_dict: Dict[str, ModuleType] = {}
        self.executor: Optional[Any] = None
        self.callback_executor: Optional[Any] = None
        # None: not configured (load anything, with a DeprecationWarning); False: allowlist only; True: anything.
        self.allow_arbitrary_packages: Optional[bool] = None
        self.allowed_packages: Set[str] = set()

    def set_allow_arbitrary_packages(self, enabled: bool) -> None:
        """
        Allow (True) or refuse (False) packages outside :attr:`allowed_packages`. Never expose this as an
        action command: an action list must not open its own gate.
        """
        self.allow_arbitrary_packages = bool(enabled)

    def allow_packages(self, *packages: str) -> None:
        """Add packages to the allowlist; a listed package also allows its submodules."""
        self.allowed_packages.update(packages)

    def _is_allowlisted(self, package: str) -> bool:
        return any(package == allowed or package.startswith(allowed + ".") for allowed in self.allowed_packages)

    def _check_allowed(self, package: object) -> None:
        """Refuse ``package`` before it is imported, unless the gate is off or lets it through."""
        if self.settings.gate is PackageGate.OFF:
            return
        if isinstance(package, str) and self._is_allowlisted(package):
            return
        if self.allow_arbitrary_packages is True:
            return
        if self.allow_arbitrary_packages is False:
            raise self.settings.refused(
                f"package {package!r} is not allowed; the host must call "
                "executor.allow_packages(...) or executor.set_allow_arbitrary_packages(True)"
            )
        warnings.warn(
            f"loading package {package!r} that is not on the allowlist; a future release will refuse "
            "it by default. Call executor.allow_packages(...) for the packages you load, or "
            "executor.set_allow_arbitrary_packages(True) to keep loading any package.",
            DeprecationWarning,
            stacklevel=_GATE_WARNING_STACKLEVEL,
        )

    def check_package(self, package: Any) -> Optional[ModuleType]:
        """Import ``package`` once (cached) and return it; ``None`` when it cannot be found or imported."""
        settings = self.settings
        settings.log_info(f"PackageManager check_package package: {package}")
        if self.installed_package_dict.get(package) is None:
            if settings.name_check is not None and not settings.name_check(package):
                settings.log_error(f"rejected package name: {package!r}")
                return None
            found_spec = find_spec(package)
            if found_spec is not None and (settings.name_check is None or settings.name_check(found_spec.name)):
                try:
                    installed_package = import_module(found_spec.name)  # nosemgrep: non-literal-import
                    self.installed_package_dict[found_spec.name] = installed_package
                except settings.import_errors as error:
                    settings.log_error(repr(error))
        return self.installed_package_dict.get(package)

    def add_package_to_executor(self, package: Any) -> int:
        """
        Register ``package``'s members into :attr:`executor`; return how many were registered.

        :raises settings.refused: the package gate refused ``package`` (nothing is imported).
        """
        self.settings.log_info(f"PackageManager add_package_to_executor package: {package}")
        self._check_allowed(package)
        return self.add_package_to_target(package, self.executor)

    def add_package_to_callback_executor(self, package: Any) -> int:
        """
        Register ``package``'s members into :attr:`callback_executor`; return how many were registered.

        :raises settings.refused: the package gate refused ``package`` (nothing is imported).
        """
        self.settings.log_info(f"PackageManager add_package_to_callback_executor package: {package}")
        self._check_allowed(package)
        return self.add_package_to_target(package, self.callback_executor)

    def add_package_to_target(self, package: Any, target: Optional[Any]) -> int:
        """Register the members matching every predicate; ``handled`` errors are logged, and the count so far kept."""
        registered = 0
        try:
            for predicate in self.settings.predicates:
                registered += self.get_member(package, predicate, target)
        except self.settings.handled as error:
            self.settings.log_error(repr(error))
        return registered

    def get_member(self, package: Any, predicate: Callable[[object], bool], target: Optional[Any]) -> int:
        """Register the members of ``package`` matching ``predicate`` into ``target``; return how many."""
        installed_package = self.check_package(package)
        if installed_package is None:
            self.settings.log_error(repr(ModuleNotFoundError(f"Can't find package {package}")))
            return 0
        if target is None:
            self.settings.log_error(f"Executor error {target}")
            return 0
        members = getmembers(installed_package, predicate)
        for member_name, member in members:
            target.event_dict[self._command_name(package, member_name)] = member
        return len(members)

    def _command_name(self, package: Any, member_name: str) -> str:
        if self.settings.naming is MemberNaming.BARE:
            return member_name
        return f"{package}_{member_name}"
