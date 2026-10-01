"""
je_action_core: the keyword-driven action executor shared by APITestka, LoadDensity, MailThunder and
FileAutomation.

Each project configures these pieces with its own command prefix, document key, exceptions and messages;
``__all__`` is the supported import surface.
"""
from je_action_core.action_list import (
    ActionListRules,
    ActionParser,
    BoundAction,
    EmptyListPolicy,
    LegacyActionParser,
    ParsedAction,
    StrictActionParser,
)
from je_action_core.builtins_policy import SAFE_BUILTINS, safe_builtin_commands
from je_action_core.callback import CallbackErrorPolicy, CallbackFunctionExecutor, CallbackSettings, CallbackStyle
from je_action_core.exceptions import (
    ActionCoreException,
    ActionExecuteException,
    ActionJsonException,
    AddCommandException,
    CallbackExecutorException,
    PackageNotAllowedException,
)
from je_action_core.executor import (
    ActionExecutor,
    ActionListSource,
    DuplicateKeys,
    ExecutorSettings,
    indexed_record_key,
    plain_record_key,
    repr_failure,
    unique_record_key,
)
from je_action_core.file_listing import get_dir_files_as_list
from je_action_core.json_io import (
    ActionJsonFile,
    JsonFileMessages,
    JsonFileSettings,
    read_action_json,
    write_action_json,
)
from je_action_core.package_manager import (
    MemberNaming,
    PackageGate,
    PackageManager,
    PackageManagerSettings,
    is_identifier_path,
    is_module_name,
)
from je_action_core.registry import Command, CommandPolicy, CommandRegistry
from je_action_core.reporting import ExecutionReporter, LoggingReporter, PrintReporter
from je_action_core.socket_auth import EnvelopeTokenRequestHandler, SecretHeaderRequestHandler, secret_matches
from je_action_core.socket_server import (
    END_MARKER,
    MAX_FRAME_BYTES,
    MAX_PAYLOAD_BYTES,
    QUIT_COMMAND,
    ActionRequestHandler,
    ActionTCPServer,
    FailureStage,
    Framing,
    OversizePolicy,
    ReplyMessages,
    SocketServerSettings,
    server_tls_context,
    start_action_socket_server,
)

__all__ = [
    "ActionListRules", "ActionParser", "BoundAction", "EmptyListPolicy", "LegacyActionParser", "ParsedAction",
    "StrictActionParser",
    "SAFE_BUILTINS", "safe_builtin_commands",
    "CallbackErrorPolicy", "CallbackFunctionExecutor", "CallbackSettings", "CallbackStyle",
    "ActionCoreException", "ActionExecuteException", "ActionJsonException", "AddCommandException",
    "CallbackExecutorException", "PackageNotAllowedException",
    "ActionExecutor", "ActionListSource", "DuplicateKeys", "ExecutorSettings", "indexed_record_key",
    "plain_record_key", "repr_failure", "unique_record_key",
    "get_dir_files_as_list",
    "ActionJsonFile", "JsonFileMessages", "JsonFileSettings", "read_action_json", "write_action_json",
    "MemberNaming", "PackageGate", "PackageManager", "PackageManagerSettings", "is_identifier_path",
    "is_module_name",
    "Command", "CommandPolicy", "CommandRegistry",
    "ExecutionReporter", "LoggingReporter", "PrintReporter",
    "END_MARKER", "MAX_FRAME_BYTES", "MAX_PAYLOAD_BYTES", "QUIT_COMMAND", "ActionRequestHandler", "ActionTCPServer",
    "FailureStage", "Framing", "OversizePolicy", "ReplyMessages", "SocketServerSettings", "server_tls_context",
    "start_action_socket_server",
    "EnvelopeTokenRequestHandler", "SecretHeaderRequestHandler", "secret_matches",
]
