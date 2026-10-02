# ActionCore

**English** | [繁體中文](README/README_zh-TW.md) | [简体中文](README/README_zh-CN.md)

`je_action_core` is the keyword-driven action executor shared by
[APITestka](https://github.com/Integration-Automation/APITestka), [LoadDensity](https://github.com/Integration-Automation/LoadDensity),
[MailThunder](https://github.com/Integration-Automation/MailThunder) and [FileAutomation](https://github.com/Integration-Automation/FileAutomation).
Each of them carried its own copy of the same executor, package manager, callback executor, action-file reader
and socket server. This package replaces those copies: a project configures it with its own command prefix,
document key, exceptions and messages.

It has no dependencies and supports Python 3.10 to 3.14.

## Contents

- [Installation](#installation)
- [Actions](#actions)
- [Quick start](#quick-start)
- [The pieces](#the-pieces)
- [Package gate](#package-gate)
- [Socket server protocol](#socket-server-protocol)
- [Who uses it](#who-uses-it)
- [Development](#development)
- [License](#license)

## Installation

```bash
pip install je_action_core
```

A framework that is built on it installs it as a dependency.

## Actions

An action list is a JSON list of actions, or a document that keeps the list under one key
(`{"api_testka": [...]}`). Each action takes one of three forms:

| Action | Call |
|---|---|
| `["name"]` | `command()` |
| `["name", {"a": 1}]` | `command(a=1)` |
| `["name", [1, 2]]` | `command(1, 2)` |

Running a list returns one record per action: the command's return value, or `repr(error)` when it raised. One
failing action does not stop the rest.

## Quick start

```python
from je_action_core import (
    ActionExecutor, ActionListRules, CommandPolicy, CommandRegistry, ExecutorSettings, LoggingReporter,
)
import logging

registry = CommandRegistry({"MY_add": lambda a, b: a + b}, policy=CommandPolicy.FUNCTIONS_ONLY)
executor = ActionExecutor(
    ExecutorSettings(rules=ActionListRules("my_tool"), reporter=LoggingReporter(logging.getLogger("my_tool"))),
    registry,
)

executor.execute_action({"my_tool": [["MY_add", [1, 2]], ["MY_add", {"a": 3, "b": 4}]]})
# {"execute: ['MY_add', [1, 2]]": 3, "execute: ['MY_add', {'a': 3, 'b': 4}]": 7}
```

## The pieces

| Module | What it gives you | Settings |
|---|---|---|
| `registry` | `CommandRegistry`: commands by name, `event_dict` as the live mapping | `CommandPolicy.FUNCTIONS_ONLY` or `ANY_CALLABLE` for caller-added commands; the exception for a refused one |
| `action_list` | `ActionListRules` (where the list is), `LegacyActionParser` and `StrictActionParser` | document key and legacy keys (with a `DeprecationWarning`); empty list raises or returns `{}`; error messages |
| `executor` | `ActionExecutor`: `execute_action`, `collect_action_results` (records and the failed keys, unreported), `execute_files`, `add_command_to_executor`; override `attempt` to wrap every action (retries, a span) | `ExecutorSettings`: rules, parser, reporter, file reader, record key (`execute: …` or `execute[i]: …`), repeated keys replaced or numbered (`#2`), what a failure records (`repr(error)` by default), action rewrite |
| `reporting` | `LoggingReporter`, `PrintReporter`, or your own `ExecutionReporter` | where events, failures and records go |
| `package_manager` | `PackageManager`: load an installed package's members as commands, behind the [package gate](#package-gate) | member naming (`<package>_<member>` or bare), predicates, name check, errors to log |
| `callback` | `CallbackFunctionExecutor`: run a trigger, then a callback | legacy or strict checking; raise or log and return `None` |
| `json_io` | `ActionJsonFile`, `read_action_json`, `write_action_json`: UTF-8, locked, non-ASCII kept | exception class and message templates |
| `file_listing` | `get_dir_files_as_list`: action files under a directory | — |
| `socket_server`, `socket_auth` | `start_action_socket_server` and the request handlers (plain, secret header, JSON-envelope token) | executor, payload check, errors answered, framing, TLS, reply templates, secret |
| `builtins_policy` | `SAFE_BUILTINS`: the builtins an action list may call | — |
| `request_record`, `request_context` | Versioned request-result validation, JSON serialization/schema and isolated `RunContext` storage | source, phase, engine, worker and run identities |

`__all__` in `je_action_core/__init__.py` is the supported import surface.

## Request results

HTTP `request_method`: uppercase ASCII token; schema and Python validation enforce the same rule.

Run identities are validated when the context is constructed. Retries compare JSON content with object keys sorted, distinguishing booleans from numbers. Assertion messages must be strings when present, and failed assertions require a message. Integer values beyond the portable JSON conversion limit and unrepresentable measurement values raise field-located contract errors.

Request results are separate from executor action records. `RequestRecord` v1 gives functional,
load and synthetic runs the same method/URL, numeric status, nullable measurements, structured error,
assertions and run/worker/step identities. `validate_request_record` returns a detached JSON-safe result;
`serialize_request_record` exports it and `request_record_schema` describes the contract.
Bytes become base64 objects, datetimes become epoch seconds and timedeltas become milliseconds.
Unknown versions, invalid fields, non-finite measurements and opaque objects raise `RequestRecordError`.

`RunContext(source="loaddensity", phase="load", engine="asyncio")` owns one run's records.
Use `capture(fields)` for a new result, `append(record)` for a validated retry, `snapshot()` for a detached
copy and `to_json()` for an array export. Identical record IDs deduplicate; conflicting retries and foreign
run identities raise an error. `use_run_context(context)` activates it for a thread/task scope and restores
the previous context on exit; `get_run_context()` returns the active context or `None`.
Storage retains the complete run; long-lived monitors should create a new context per iteration and persist results.
The contract records the runner's judgement and does not decide whether a status code is successful.

## Package gate

`PackageManager.add_package_to_executor` imports a package and registers its members as commands. An action list
that can name `os` or `subprocess` could therefore run anything. The host program decides what may load:

```python
package_manager.allow_packages("my_helpers")          # these, and their submodules
package_manager.set_allow_arbitrary_packages(False)   # refuse everything else before importing it
```

Neither switch should ever be exposed as an action command, so an action list cannot open its own gate. A
refused package raises the project's `refused` exception, which the executor records as that action's result.
Until the host calls either switch, any package still loads but raises a `DeprecationWarning`. A project can
turn the gate off (`PackageGate.OFF`) while it moves to it.

## Socket server protocol

`start_action_socket_server(host, port, settings, handler_class=ActionRequestHandler)` serves on a daemon thread.
A client sends one JSON action document per connection. The server replies with one line per record, then
`Return_Data_Over_JE`. A failure replies with the error text and the same marker. `quit_server` stops the server
and sets `close_flag` and `close_event`. What can be configured:

- **Framing**: `Framing.RAW` reads one 8 KiB `recv`, and `OversizePolicy` says what happens to a full buffer.
  `Framing.LENGTH_PREFIX` reads a 4-byte big-endian length, then the body (at most 1 MiB), and sends every reply
  line as its own frame.
- **TLS**: `tls_context=server_tls_context(certfile, keyfile)` wraps each connection (TLS 1.2 or later).
- **Replies**: `ReplyMessages` holds the templates for a record line, each failure stage (JSON, refused by
  `validate`, execution), an undecodable request, the quit reply, the authentication refusals and the log line.
- **Authentication**: the base handler has none. `SecretHeaderRequestHandler` requires a first line
  `<auth_prefix><secret>`. `EnvelopeTokenRequestHandler` accepts `{"token": ..., "command": ...}` and
  `{"token": ..., "op": "quit"}`. Both compare secrets in constant time.

Without authentication, bind the server only to a trusted interface.

## Who uses it

APITestka (`AT_`, port 9939), LoadDensity (`LD_`), MailThunder (`MT_`, port 9942) and FileAutomation (`FA_`) are
the projects this package is for. `architecture.md` §6 lists which of them have moved to it and which pieces and
settings each one uses. All four run their TCP servers on `socket_server`: LoadDensity with the JSON-envelope
token, framing and TLS, FileAutomation with the `AUTH` header and its ACL.

[WebRunner](https://github.com/Integration-Automation/WebRunner) (`WR_`) runs its action executor on it as well. Its
own action format (`[name, [args], {kwargs}]`) is a parser, and its retries and action span wrap `attempt`.
Failure screenshots go into `failure_record`, and repeated actions are numbered (`DuplicateKeys.NUMBER`).

n and an ACL.

## Development

```bash
pip install -e .
pip install pytest
python -m pytest test/
```

`architecture.md` describes the layers and the contracts with the four projects. Outstanding work is in
`progress.md`, and finished work is recorded in `docs/updates/`.

## License

MIT, see [LICENSE](LICENSE).
