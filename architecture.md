# architecture.md: ActionCore

The short architecture overview. `README.md` is the user guide; finished work is in `docs/updates/`.

## 1. Purpose

`je_action_core` is the keyword-driven action executor that APITestka, LoadDensity, MailThunder and FileAutomation
share (workspace item L-6). It holds one implementation of what those four used to copy: the executor, the
command registry, the package manager with its package gate, the callback executor, action-file reading and
writing, action-file discovery and the plain TCP action server. A project supplies everything that differs as
settings: command prefix, document key, exceptions, messages and reporting. The package has no dependencies.

## 2. Layers and directories

| Path | What it holds |
|---|---|
| `je_action_core/exceptions.py` | Default exceptions (`ActionCoreException` and one subclass per piece), used when a project passes none |
| `je_action_core/registry.py` | `CommandRegistry` (name -> callable, `event_dict` is the live dict), `CommandPolicy` for caller-added commands |
| `je_action_core/action_list.py` | `ActionListRules` (document key, legacy keys, empty-list policy, messages); `LegacyActionParser` and `StrictActionParser` bind one action to its command |
| `je_action_core/executor.py` | `ActionExecutor` and `ExecutorSettings`; record-key functions |
| `je_action_core/reporting.py` | `ExecutionReporter` hooks; `LoggingReporter` and `PrintReporter` |
| `je_action_core/package_manager.py` | `PackageManager` (members as commands) behind the package gate; `PackageManagerSettings` |
| `je_action_core/callback.py` | `CallbackFunctionExecutor` and `CallbackSettings` (legacy or strict checks, raise or return `None`) |
| `je_action_core/json_io.py` | `ActionJsonFile` (UTF-8, locked, project exception and message templates) and default `read_action_json` / `write_action_json` |
| `je_action_core/file_listing.py` | `get_dir_files_as_list` |
| `je_action_core/socket_server.py` | `ActionTCPServer` (`close_flag`, `close_event`, `request_stop`), the template `ActionRequestHandler`, `SocketServerSettings` (framing, TLS, `ReplyMessages`, secret), `server_tls_context`, `start_action_socket_server` |
| `je_action_core/socket_auth.py` | `SecretHeaderRequestHandler` (`<prefix><secret>` first line) and `EnvelopeTokenRequestHandler` (JSON envelope token) |
| `je_action_core/builtins_policy.py` | `SAFE_BUILTINS`, `safe_builtin_commands()` |
| `test/` | One test module per piece, plus the workflow pinning checks |

Nothing in the package imports a project; the projects import it.

## 3. Entry points and public interfaces

- `je_action_core.__all__` is the supported import surface. Every settings class is a frozen dataclass, so a
  project builds its settings once at import time.
- A project's executor subclasses `ActionExecutor` or instantiates it with its `ExecutorSettings` and a
  `CommandRegistry`, then fills `event_dict` with its own commands. Its existing module-level functions
  (`execute_action`, `execute_files`, `add_command_to_executor`) delegate to that instance.

## 4. Main flows

- **`ActionExecutor.execute_action(action_list)`**:
  1. `ActionListRules.extract` returns the list, raises, or returns `None` (run nothing, return `{}`).
  2. For each action, `run_one` calls `_execute_event`: reporter `on_event`, then `prepare`, then
     `parser.bind`, then `invoke`.
  3. `run_one` returns the result or `repr(error)`, and calls `on_success` or `on_failure`.
  4. The result is stored under `record_key(index, action)`, and `on_records` sees the whole record.
- **`PackageManager.add_package_to_executor(package)`**:
  1. `_check_allowed` applies the gate (refuse, allow, or warn).
  2. `check_package` validates the name, then `find_spec`, `import_module`, and caches the module.
  3. `get_member` runs once per predicate and writes `event_dict[name] = member`, naming each member
     `<package>_<member>` or bare.
- **`CallbackFunctionExecutor.callback_function`**: looks the trigger up, then (strict style only) checks the
  method, calls the trigger with `kwargs`, then calls the callback with no arguments, `**param` or `*param`.
  Errors are logged and then raised or turned into `None`.
- **Socket server** (`ActionRequestHandler.handle`, a template):
  1. `secure` wraps the connection in TLS when configured.
  2. `read_request` reads one 8 KiB `recv` or one length-prefixed frame.
  3. `decode` turns the bytes into text.
  4. `process` logs the request, then either handles `quit_server` (`on_quit`) or runs `run_text`:
     `json.loads`, then `run_document` (`validate`, `execute`, one line per record, the end marker).
  5. A failure is answered by `reply_failure(stage)` with that stage's template.

  The dialects override `process`: the secret header is checked first, or the JSON envelope is unwrapped.

## 5. Extension points

- **Reporting**: subclass `ExecutionReporter`, or pass log hooks (`log_info`, `log_error`) to the settings of
  the package manager, callback executor, JSON file and socket server.
- **Wrapping every command call** (tracing, metrics): override `ActionExecutor.invoke` or `run_one`.
- **Action rules**: `ExecutorSettings.parser` takes any object with `bind(action, resolve)`; `prepare` rewrites
  an action before it is bound.
- **Socket dialect**: subclass `ActionRequestHandler` and override the step that differs (`read_request`,
  `decode`, `process`, `on_quit`, `write`); pass it as `handler_class` to `start_action_socket_server`.
- **New piece**: add a module, export it in `__init__.py` and `__all__`, add `test/test_<piece>.py`, and add a
  row to §2 and to the README's table (three languages).

## 6. Cross-project boundaries

**Used by.** Each project that moves adds a row here; the same round updates that project's own
`architecture.md` §6. The projects install it from PyPI (`je_action_core>=0.0.1`); a change they need is released
first and their minimum version raised in the same round.

| Project | Pieces | Settings |
|---|---|---|
| APITestka (`AT_`, `api_testka`) | executor, registry, package manager, callback executor, JSON files, file listing, socket server (9939) | `LegacyActionParser`, plain record keys, `LoggingReporter`, `strip_runner_metadata` as `prepare`; functions-only registry; gate on, prefixed members, every load error logged; callback returns `None` on failure; socket reads the prefix and answers every error |
| MailThunder (`MT_`, `mail_thunder`, legacy `auto_control`) | executor, registry, package manager, JSON files, file listing, socket server (9942) | `LegacyActionParser`, `EmptyListPolicy.RETURN_EMPTY`, plain record keys, `LoggingReporter` with its empty message, `SAFE_BUILTINS`; functions-only registry; gate on, identifier-path names, import and attribute errors logged; `from_document` in its payload check; socket rejects oversized payloads and answers `ValueError`, `OSError`, `TypeError` |
| LoadDensity (`LD_`, `load_density`) | executor, registry, package manager, callback executor, JSON files, socket server (9940) | `LegacyActionParser`, plain record keys, `PrintReporter`, `SAFE_BUILTINS`; functions-only registry; gate on, bare member names, functions only, ASCII names, errors printed; callback raises after printing; JSON wraps every error; `EnvelopeTokenRequestHandler`, raw or `LENGTH_PREFIX` framing, optional TLS, `Error: <text>` replies, size-only log line, run under gevent. Its file listing stays in LoadDensity |
| FileAutomation (`FA_`, `auto_control`) | registry, executor pipeline, package loader, callback executor, JSON files, TCP server (9943) | any-callable registry (`"<name> is not callable"`); `StrictActionParser`, `indexed_record_key`, its three list messages; tracing through `invoke`; `check_and_add` for the member count, gate off, `ImportError` logged; strict callback, errors raised; JSON wraps `JSONDecodeError` / `OSError` on read and `OSError` / `TypeError` on write; `SecretHeaderRequestHandler` (`AUTH <secret>`), the ACL as `validate`, `<key> -> <value>` records and prefixed error replies. Dry run, validate, substitute, parallel runs, metrics and its HTTP server stay in FileAutomation |

**What the projects rely on here.** They rely on these, and none may change without changing the projects in
the same round:

- the names in `__all__`, and the settings fields they pass;
- `event_dict` staying the live mapping of a registry, executor and callback executor;
- the record formats `"execute: <action>"` and `"execute[<index>]: <action>"`, and `repr(error)` as a failed
  action's record;
- the error texts of `LegacyActionParser` (`f"{message} {action}"`) and of `StrictActionParser` (FileAutomation's
  messages);
- the socket protocol: `Return_Data_Over_JE`, `quit_server`, one line per value.

**What this package relies on.** Nothing outside the standard library.

## 7. Design constraints

- No runtime dependencies. Python 3.10 and later. Every settings object is a frozen dataclass; mutable state
  lives on instances (registries, caches, the gate).
- Behaviour that differs between projects is a setting, never a project-name check. A refactor in a project
  that moves onto this package must not change that project's behaviour; where a project behaved differently
  for no reason, that change is a separate commit in the project.
- The package gate exists so an action list can never load `os` or `subprocess` on its own: the gate switches
  are never action commands.
- Functions ≤ 50 lines, files ≤ 500 lines, lines ≤ 120 characters; every public function and class has type hints
  and a docstring; every change ships with tests (`CLAUDE.md`).

## 8. When to update this file

- A module is added, removed or renamed (§2), or the import surface changes (§3).
- A flow in §4 changes.
- A project moves onto the package, changes the pieces or settings it uses, or a contract in §6 changes.
