# 程式審核：ActionCore

## 審核者

| 欄位 | 內容 |
|---|---|
| 審核者 | 工作區程式審核 |
| 審核日期 | 2026-10-22 |
| 審核對象 | `ActionCore`（je_action_core） |
| 審核範圍 | 工作樹現況的架構、進入點、安全熱點、錯誤處理、測試配置與文件是否跟得上程式 |
| 結論 | 需修正 |

## 審核規範

共通規範在工作區 repo [JE-Chen/Codes](https://github.com/JE-Chen/Codes) 的 `docs/code-review-standard.md`。下面留下 2026-10-22 這次審核所用的條款，讓審核紀錄的依據對得上那一次。之後的審核以工作區那份為準。本專案更嚴的條款仍以本節與本專案的 `CLAUDE.md` 為準。

本審核用的規範如下。未在本專案另訂的門檻，用第 2 點的預設值。

1. 設計維持 SOLID、DRY、KISS、YAGNI。行為差異用設定或掛鉤，不在套件裡判斷專案名稱。
2. 可讀性。未另訂時：認知複雜度 15、函式 80 行、巢狀 4 層、參數 7 個、單行 120 字元。
3. 錯誤處理。不寫裸 `except:`、不吞例外、不用可變預設參數。廣捕 `Exception` 只允許在錯誤變成紀錄或重新拋出時，且要註明原因。
4. 不留死碼，不在程式裡留 TODO。
5. 公開 API 要有型別與 docstring。
6. 安全。不寫死祕密；不可信輸入不用 `eval` / `exec` / `shell=True` / `pickle` / 不安全的 `yaml.load`；查詢要參數化；不關閉 TLS 驗證。
7. 測試守住行為。新行為、修復與每個設定值都要有測試；這次只核對測試是否存在與是否鎖住熱點，不執行測試。
8. 先量測再最佳化。
9. `architecture.md` §6 的跨專案契約。名稱、`event_dict`、紀錄格式、覆寫點、錯誤文字與 socket 協定，沒有在同一輪改使用端之前不能改。
10. 文件跟程式一起更新。`architecture.md` 的分層、流程、契約，以及三種語文的 README，要和程式一致。

嚴重度：缺陷＝錯誤行為、安全問題、資料遺失或契約破壞；建議＝該改但未立即造成上述後果；備註＝風格或小處。

結論定義：通過＝沒有未關閉缺陷；有條件通過＝沒有會立即造成損害的缺陷；需修正＝有未關閉缺陷。

設計過且有測試守住的允許清單不當成缺陷。只有允許清單被繞過、預設仍載入任意套件，或文件與程式不符，才列缺陷。

### 本專案加嚴

取自 `CLAUDE.md`，比上面的預設更嚴：

- 函式不超過 50 行，檔案不超過 500 行，單行不超過 120 字元；認知複雜度不超過 15，循環複雜度不超過 10，巢狀不超過 4，參數不超過 7（多的放進 frozen dataclass）。
- 不寫魔術數字、不把同一字串字面重複三次以上、不留註解掉的程式、不在 `PrintReporter` 以外使用 `print()`。
- 套件閘門要讓 action 清單不能自行載入 `os` 或 `subprocess`。`allow_packages` 與 `set_allow_arbitrary_packages` 不得成為 action 命令。
- `SAFE_BUILTINS` 是允許清單，不得加入會執行程式、取屬性或命名空間、碰檔案或標準輸入的名稱（`eval`、`exec`、`compile`、`__import__`、`open`、`input`、`getattr`、`globals` 等）。
- 套件內不使用 `eval()`、`exec()`、`pickle`、`shell=True`。action 檔只當 UTF-8 JSON 讀。
- 基礎 socket 處理器沒有驗證，必須綁定呼叫端給的 host，不得預設 `0.0.0.0`。
- 每次行為變更都要在同一提交附上 `test/test_<piece>.py` 的測試。三種語文 README 要對得上，且反映英文內容而不只是標題。

## 審核紀錄

### 方法

審核的是 2026-10-22 工作樹現況，不是 git diff，也不是逐行審完全部程式。

讀了 `architecture.md`（分層、進入點、主流程、§6、§7）、`CLAUDE.md` 裡長度、安全與測試的段落，以及 `progress.md` 前 80 行。待辦沒有抄進本檔。

在 `je_action_core` 的程式裡搜尋 `eval(`、`exec(`、`shell=True`、`pickle`、`yaml.load`、`verify=False`、裸 `except:`、`subprocess`，排除 `test`、`build`、`dist`、`__pycache__`。除了 `package_manager.py` 模組說明裡的 `subprocess` 字樣，沒有符合的呼叫。每一則發現都再讀過該行。

確認有 `test/`，以及 `.github/workflows/ci.yml` 與 `publish.yml`。沒有執行測試，也沒有啟動套件。

### 總評

執行器、命令表、回呼、JSON、檔案列舉與 socket 的分層和 `architecture.md` §4 一致。`SAFE_BUILTINS` 與「宿主已經關閉任意載入之後」的套件允許清單都有測試守住，套件裡也沒有 `eval` / `exec`。這兩份允許清單不列為缺陷。

未關閉的問題是：閘門列舉雖然預設 `ON`，實例在宿主呼叫開關之前仍會匯入並註冊任意套件。`add_package_to_executor` 本身就是 action 命令。action 清單因此可以在預設狀態載入 `os` 或 `subprocess`。這和 `CLAUDE.md`、`architecture.md` §7 寫的「不能自行載入」不符。README 與模組說明有寫這個過渡行為，但那則 `DeprecationWarning` 在一般動作執行路徑上不會顯示。

### 發現

#### CR-01 · 缺陷 · 套件閘門預設仍載入任意套件

- 位置：`je_action_core/package_manager.py:95`、`je_action_core/package_manager.py:118`、`je_action_core/package_manager.py:125`、`je_action_core/package_manager.py:158`
- 說明：`PackageManagerSettings.gate` 預設是 `PackageGate.ON`，但新實例的 `allow_arbitrary_packages` 是 `None`。`_check_allowed` 只有在該值為 `False` 時才在匯入前拒絕；`None` 只呼叫 `warnings.warn`，然後 `add_package_to_executor` 仍繼續 `add_package_to_target`。允許清單沒有內建 `os` 或 `subprocess`，這兩個名稱走的就是這條預設路徑。模組說明寫明此方法是 `*_add_package_to_executor` 這種 action 命令，所以 action 清單叫得到它。預設成員包含函式、builtin 與類別，載入 `os` 後就能把會執行行程的成員註冊成命令。`test/test_package_manager.py:34` 把「未設定就警告但仍載入」鎖成現況；`test_closed_gate_refuses_before_importing` 只覆蓋宿主已經設成 `False` 之後。警告的 `stacklevel` 是 3，歸到 `add_package_to_executor` 的呼叫端；經執行器呼叫時那一格在 `je_action_core.executor`，不是 `__main__`。Python 預設警告過濾器會忽略非 `__main__` 的 `DeprecationWarning`，因此一般執行看不到這則警告，也不是例外。`CLAUDE.md` 安全節與 `architecture.md` §7 寫成閘門讓 action 清單不能自行載入 `os` 或 `subprocess`。README 三種語文與模組說明則寫「呼叫開關前仍會載入並發出警告」，和程式的載入行為一致，但和上述兩份規範不一致，也沒有寫明預設過濾器下警告不會出現。
- 依據：規範 6、規範 9、規範 10，以及本專案加嚴的套件閘門
- 狀態：未關閉
- 建議：未設定時應直接拒絕（`allow_arbitrary_packages` 預設 `False`），與警告文字說的未來行為一致。這會改變使用端現在靠預設放行的行為，必須在同一輪改那些專案並更新 §6，不能只改這個套件。同時改 `test_unconfigured_gate_warns_but_loads`，並讓 `architecture.md` §7 與 `CLAUDE.md` 不再把「尚未呼叫開關」寫成已經擋住。在預設改掉之前，至少不要依賴這則 `DeprecationWarning` 當控制措施。

#### CR-02 · 備註 · 英文 README 殘留半句

- 位置：`README.md:128`
- 說明：WebRunner 那段之後有一行獨立的 `n and an ACL.`。上一節已經寫完 FileAutomation 的 ACL，這行對不上上下文。`README/README_zh-TW.md` 與 `README/README_zh-CN.md` 的對應段落沒有這行。程式行為不受影響，但三種語文不再一致。
- 依據：規範 10，以及本專案加嚴的 README 對齊
- 狀態：未關閉
- 建議：刪掉這一行，再對一次英文與兩份譯文的「誰在使用」小節。

### 已核對且未列為問題的項目

- `SAFE_BUILTINS` 只有 `abs`、`all`、`any`、`ascii`、`bin`、`callable`、`chr`、`divmod`、`format`、`hash`、`hex`、`len`、`max`、`min`、`oct`、`ord`、`pow`、`print`、`repr`、`round`、`sorted`、`sum`。`safe_builtin_commands()` 只從這份清單取 builtin。`test/test_file_listing_and_builtins.py` 斷言它與 `eval`、`exec`、`compile`、`__import__`、`open`、`input`、`getattr`、`globals` 不相交。這是有測試的允許清單，不列缺陷。
- 宿主呼叫 `set_allow_arbitrary_packages(False)` 之後，不在允許清單上的套件會在 `import_module` 之前拒絕；允許項目含其點號子模組，不含只是前綴相似的名稱。`test_closed_gate_refuses_before_importing`、`test_closed_gate_covers_the_callback_executor`、`test_allowlist_covers_submodules_only` 守住這段。套件本身沒有把 `allow_packages` 或 `set_allow_arbitrary_packages` 放進 `event_dict`。
- `add_package_to_target` 與 `check_package` 不查閘門。action 命令走的 `add_package_to_executor`、`add_package_to_callback_executor`，以及 FileAutomation 用的 `check_and_add`，都會先呼叫 `_check_allowed`。這兩個內層方法不是 action 入口，不當成允許清單被繞過。
- `PackageGate.OFF` 是明示設定。`architecture.md` §6 寫 FileAutomation 使用它，README 也寫這是改用閘門期間的開關。不把這個設定本身當缺陷。
- 套件原始碼沒有 `eval(`、`exec(`、`pickle`、`yaml.load`、`shell=True`、`verify=False` 或裸 `except:`。JSON 讀寫使用 `json.load` / `json.dumps`，編碼為 UTF-8。
- `executor.py:125` 與 `callback.py:94` 的 `except Exception` 都有註明：前者把失敗收成紀錄，後者依政策重新拋出或變成 `None`。預設回呼政策是重新拋出。
- 命令表的 `FUNCTIONS_ONLY` 只約束 `add_commands`。專案要函式限定時自己傳入這個政策；直接寫 `event_dict` 是 §6 寫明的活字典，不是這次要列的繞過。
- `start_action_socket_server` 的 host 是必填參數，沒有預設 `0.0.0.0`。基礎處理器沒有驗證，文件要求綁在可信任介面。有祕密時，標頭方言先核對再交給基礎處理器記錄；信封方言拒絕沒有相符 token 的文件與 `quit_server`。比對使用 `hmac.compare_digest`，非字串視為不符。`server_tls_context` 用標準程式庫的預設伺服器情境，並把下限設為 TLS 1.2。測試有覆蓋這些分支。
- 預設日誌鉤子丟棄訊息。記錄範本可以改成只記長度，`test_log_command_template_can_hide_the_text` 守住這一點。信封方言的全文範本只有在宿主換上會保存訊息的 `log_info` 且沒改範本時才會帶出 token；§6 寫 LoadDensity 用的是只記大小的那一行。不另列。
- CI 在 Linux、macOS、Windows 上跑 Python 3.10 到 3.14，測試依賴以雜湊鎖定。`test/` 有對應各模組的測試，另有 workflow 與 sdist manifest 測試。這次沒有執行。

### 未涵蓋

這不是逐行審核，沒有量循環複雜度，也沒有核對每一個公開函式的行數。沒有執行測試或啟動伺服器，所以沒有執行期覆蓋率或實際警告輸出。沒有審使用此套件的其他儲存庫，因此不能從這邊判斷各專案是否已經呼叫閘門開關。`build/`、`dist/` 與 `__pycache__` 不在範圍內。`progress.md` 的待辦不是發現。

### 結論

需修正。未關閉缺陷 1 則（CR-01，預設載入任意套件，且規範文字與這段程式不符），建議 0 則，備註 1 則（CR-02）。允許清單在宿主明確關閉任意載入之後是被測試守住的，不構成另一則缺陷。
