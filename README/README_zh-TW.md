# ActionCore

[English](../README.md) | **繁體中文** | [简体中文](README_zh-CN.md)

`je_action_core` 是 [APITestka](https://github.com/Integration-Automation/APITestka)、[LoadDensity](https://github.com/Integration-Automation/LoadDensity)、
[MailThunder](https://github.com/Integration-Automation/MailThunder) 與 [FileAutomation](https://github.com/Integration-Automation/FileAutomation)
共用的關鍵字驅動 action 執行器。這四個專案原本各自帶著一份相同的執行器、套件管理器、回呼執行器、action 檔讀寫與
socket 伺服器。這個套件取代那些副本：每個專案用自己的命令前綴、文件鍵、例外類別與訊息來設定它。

它沒有任何相依套件，支援 Python 3.10 到 3.14。

## 目錄

- [安裝](#安裝)
- [Action](#action)
- [快速上手](#快速上手)
- [組成元件](#組成元件)
- [套件閘門](#套件閘門)
- [Socket 伺服器協定](#socket-伺服器協定)
- [誰在使用](#誰在使用)
- [開發](#開發)
- [授權](#授權)

## 安裝

```bash
pip install je_action_core
```

建立在它上面的框架會把它當成相依套件一起安裝。

## Action

action 清單是一個 JSON 陣列，或是把清單放在某個鍵底下的文件（`{"api_testka": [...]}`）。每個 action 有三種寫法：

| Action | 呼叫方式 |
|---|---|
| `["name"]` | `command()` |
| `["name", {"a": 1}]` | `command(a=1)` |
| `["name", [1, 2]]` | `command(1, 2)` |

執行一份清單會為每個 action 回傳一筆紀錄：命令的回傳值，或在出錯時的 `repr(error)`。一個 action 失敗不會中斷其他 action。

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

## 組成元件

| 模組 | 提供什麼 | 可設定的項目 |
|---|---|---|
| `registry` | `CommandRegistry`：依名稱存放命令，`event_dict` 是即時的對應表 | 呼叫端新增的命令用 `CommandPolicy.FUNCTIONS_ONLY` 或 `ANY_CALLABLE` 判斷；被拒絕時丟出的例外 |
| `action_list` | `ActionListRules`（清單在哪裡）、`LegacyActionParser` 與 `StrictActionParser` | 文件鍵與舊鍵（會發出 `DeprecationWarning`）；空清單要丟例外或回傳 `{}`；錯誤訊息 |
| `executor` | `ActionExecutor`：`execute_action`、`execute_files`、`add_command_to_executor` | `ExecutorSettings`：規則、解析器、回報器、檔案讀取、紀錄鍵（`execute: …` 或 `execute[i]: …`）、action 改寫 |
| `reporting` | `LoggingReporter`、`PrintReporter`，或自訂的 `ExecutionReporter` | 事件、失敗與紀錄要送到哪裡 |
| `package_manager` | `PackageManager`：把已安裝套件的成員載入成命令，前面有[套件閘門](#套件閘門) | 成員命名（`<package>_<member>` 或不加前綴）、篩選條件、名稱檢查、要記錄而不丟出的錯誤 |
| `callback` | `CallbackFunctionExecutor`：先執行觸發命令，再執行回呼 | 舊版或嚴格檢查；丟出例外，或記錄後回傳 `None` |
| `json_io` | `ActionJsonFile`、`read_action_json`、`write_action_json`：UTF-8、加鎖、保留非 ASCII 文字 | 例外類別與訊息範本 |
| `file_listing` | `get_dir_files_as_list`：找出目錄底下的 action 檔 | — |
| `socket_server` | `start_action_socket_server`：一般的 TCP action 伺服器 | 執行器、內容檢查、要回覆的錯誤、過大內容的處理方式 |
| `builtins_policy` | `SAFE_BUILTINS`：action 清單可以呼叫的內建函式 | — |

`je_action_core/__init__.py` 裡的 `__all__` 是正式支援的匯入介面。

## 套件閘門

`PackageManager.add_package_to_executor` 會匯入一個套件，並把它的成員註冊成命令。所以只要 action 清單寫得出
`os` 或 `subprocess`，就能執行任何東西。哪些套件可以載入，由宿主程式決定：

```python
package_manager.allow_packages("my_helpers")          # 這些套件與其子模組
package_manager.set_allow_arbitrary_packages(False)   # 其他套件在匯入前就拒絕
```

這兩個開關都不應該開放成 action 命令，這樣 action 清單就不能自己打開閘門。被拒絕的套件會丟出專案設定的
`refused` 例外，執行器會把它記成該 action 的結果。宿主程式呼叫任一個開關之前，任何套件仍會載入，但會發出
`DeprecationWarning`。專案在改用閘門的過程中，可以先把它關掉（`PackageGate.OFF`）。

## Socket 伺服器協定

`start_action_socket_server(host, port, settings)` 在背景執行緒上提供服務。用戶端每次連線送出一份 JSON action
文件；伺服器把每筆紀錄的值各自回覆成一行，最後是 `Return_Data_Over_JE`。失敗時回覆錯誤文字與同一個結束標記。
`quit_server` 會停止伺服器並設定 `close_flag`。伺服器沒有驗證機制，只能綁定在可信任的網路介面上。

## 誰在使用

這個套件是為 APITestka（`AT_`，埠號 9939）、LoadDensity（`LD_`）、MailThunder（`MT_`，埠號 9942）與
FileAutomation（`FA_`）而做的。`architecture.md` §6 列出其中哪些已經改用它，以及各自用了哪些元件與設定。
LoadDensity 與 FileAutomation 保留自己的 socket 伺服器：一個是有分框、權杖與 TLS 的 gevent 伺服器，另一個有驗證與存取控制清單。

## 開發

```bash
pip install -e .
pip install pytest
python -m pytest test/
```

`architecture.md` 說明分層，以及和這四個專案之間的約定。待辦事項在 `progress.md`，完成的工作記錄在 `docs/updates/`。

## 授權

MIT，見 [LICENSE](../LICENSE)。
