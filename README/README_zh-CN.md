# ActionCore

[English](../README.md) | [繁體中文](README_zh-TW.md) | **简体中文**

`je_action_core` 是 [APITestka](https://github.com/Integration-Automation/APITestka)、[LoadDensity](https://github.com/Integration-Automation/LoadDensity)、
[MailThunder](https://github.com/Integration-Automation/MailThunder) 与 [FileAutomation](https://github.com/Integration-Automation/FileAutomation)
共用的关键字驱动 action 执行器。这四个项目原本各自带着一份相同的执行器、包管理器、回调执行器、action 文件读写与
socket 服务器。这个包取代那些副本：每个项目用自己的命令前缀、文档键、异常类与消息来配置它。

它没有任何依赖，支持 Python 3.10 到 3.14。

## 目录

- [安装](#安装)
- [Action](#action)
- [快速上手](#快速上手)
- [组成部件](#组成部件)
- [包闸门](#包闸门)
- [Socket 服务器协议](#socket-服务器协议)
- [谁在使用](#谁在使用)
- [开发](#开发)
- [许可](#许可)

## 安装

```bash
pip install je_action_core
```

建立在它之上的框架会把它作为依赖一起安装。

## Action

action 列表是一个 JSON 数组，或是把列表放在某个键下的文档（`{"api_testka": [...]}`）。每个 action 有三种写法：

| Action | 调用方式 |
|---|---|
| `["name"]` | `command()` |
| `["name", {"a": 1}]` | `command(a=1)` |
| `["name", [1, 2]]` | `command(1, 2)` |

执行一份列表会为每个 action 返回一条记录：命令的返回值，或在出错时的 `repr(error)`。一个 action 失败不会中断其他 action。

## 快速上手

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

## 组成部件

| 模块 | 提供什么 | 可配置的项目 |
|---|---|---|
| `registry` | `CommandRegistry`：按名称存放命令，`event_dict` 是实时的映射表 | 调用方新增的命令用 `CommandPolicy.FUNCTIONS_ONLY` 或 `ANY_CALLABLE` 判断；被拒绝时抛出的异常 |
| `action_list` | `ActionListRules`（列表在哪里）、`LegacyActionParser` 与 `StrictActionParser` | 文档键与旧键（会发出 `DeprecationWarning`）；空列表要抛异常或返回 `{}`；错误消息 |
| `executor` | `ActionExecutor`：`execute_action`、`collect_action_results`（记录与失败的键，不报告）、`execute_files`、`add_command_to_executor`；重写 `attempt` 可包住每个 action（重试、span） | `ExecutorSettings`：规则、解析器、报告器、文件读取、记录键（`execute: …` 或 `execute[i]: …`）、重复的键覆盖或编号（`#2`）、失败时记下什么（默认 `repr(error)`）、action 改写 |
| `reporting` | `LoggingReporter`、`PrintReporter`，或自定义的 `ExecutionReporter` | 事件、失败与记录要送到哪里 |
| `package_manager` | `PackageManager`：把已安装包的成员加载成命令，前面有[包闸门](#包闸门) | 成员命名（`<package>_<member>` 或不加前缀）、筛选条件、名称检查、要记录而不抛出的错误 |
| `callback` | `CallbackFunctionExecutor`：先执行触发命令，再执行回调 | 旧版或严格检查；抛出异常，或记录后返回 `None` |
| `json_io` | `ActionJsonFile`、`read_action_json`、`write_action_json`：UTF-8、加锁、保留非 ASCII 文本 | 异常类与消息模板 |
| `file_listing` | `get_dir_files_as_list`：找出目录下的 action 文件 | — |
| `socket_server`、`socket_auth` | `start_action_socket_server` 与请求处理器（无认证、密钥标头、JSON 信封令牌） | 执行器、内容检查、要回复的错误、分帧、TLS、回复模板、密钥 |
| `builtins_policy` | `SAFE_BUILTINS`：action 列表可以调用的内置函数 | — |

`je_action_core/__init__.py` 里的 `__all__` 是正式支持的导入接口。

## 包闸门

`PackageManager.add_package_to_executor` 会导入一个包，并把它的成员注册成命令。所以只要 action 列表写得出
`os` 或 `subprocess`，就能执行任何东西。哪些包可以加载，由宿主程序决定：

```python
package_manager.allow_packages("my_helpers")          # 这些包与其子模块
package_manager.set_allow_arbitrary_packages(False)   # 其他包在导入前就拒绝
```

这两个开关都不应该开放成 action 命令，这样 action 列表就不能自己打开闸门。被拒绝的包会抛出项目配置的
`refused` 异常，执行器会把它记成该 action 的结果。宿主程序调用任一个开关之前，任何包仍会加载，但会发出
`DeprecationWarning`。项目在改用闸门的过程中，可以先把它关掉（`PackageGate.OFF`）。

## Socket 服务器协议

`start_action_socket_server(host, port, settings, handler_class=ActionRequestHandler)` 在后台线程上提供服务。
客户端每次连接发送一份 JSON action 文档；服务器每条记录回复一行，最后是 `Return_Data_Over_JE`。失败时回复错误
文本与同一个结束标记。`quit_server` 会停止服务器并设置 `close_flag` 与 `close_event`。可以配置的有：

- **分帧**：`Framing.RAW` 读一次 8 KiB 的 `recv`，缓冲区被填满时怎么处理由 `OversizePolicy` 决定；
  `Framing.LENGTH_PREFIX` 先读 4 字节的大端序长度，再读内容（最多 1 MiB），每一行回复都是一个独立的帧。
- **TLS**：`tls_context=server_tls_context(certfile, keyfile)` 会包住每一条连接（TLS 1.2 以上）。
- **回复**：`ReplyMessages` 是各种回复的模板：记录行、每个失败阶段（JSON、被 `validate` 拒绝、执行）、
  无法解码的请求、quit 的回复、认证拒绝，以及日志行。
- **认证**：基本的处理器没有认证。`SecretHeaderRequestHandler` 要求第一行是 `<auth_prefix><secret>`；
  `EnvelopeTokenRequestHandler` 接受 `{"token": ..., "command": ...}` 与 `{"token": ..., "op": "quit"}`。
  两者都以固定时间比对密钥。

没有认证时，服务器只能绑定在可信任的网络接口上。

## 谁在使用

这个包是为 APITestka（`AT_`，端口 9939）、LoadDensity（`LD_`）、MailThunder（`MT_`，端口 9942）与
FileAutomation（`FA_`）而做的。`architecture.md` §6 列出其中哪些已经改用它，以及各自用了哪些部件与配置。
四个项目的 TCP 服务器都运行在 `socket_server` 上：LoadDensity 用 JSON 信封令牌、分帧与 TLS，FileAutomation 用 `AUTH` 标头与它的访问控制列表。

## 开发

```bash
pip install -e .
pip install pytest
python -m pytest test/
```

`architecture.md` 说明分层，以及和这四个项目之间的约定。待办事项在 `progress.md`，完成的工作记录在 `docs/updates/`。

## 许可

MIT，见 [LICENSE](../LICENSE)。
