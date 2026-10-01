"""Exceptions raised by je_action_core when a project does not pass its own classes."""


class ActionCoreException(Exception):
    """Base class of every exception defined here."""


class ActionExecuteException(ActionCoreException):
    """An action list, or one action in it, could not be run."""


class AddCommandException(ActionCoreException):
    """A command was refused by a :class:`~je_action_core.registry.CommandRegistry`."""


class ActionJsonException(ActionCoreException):
    """An action file could not be read or written."""


class CallbackExecutorException(ActionCoreException):
    """A trigger or its callback could not be run."""


class PackageNotAllowedException(ActionCoreException):
    """The package gate refused to import a package."""
