# progress.md: ActionCore

Outstanding work only. When an item is done, delete it in the same commit and add a `#done` entry to `docs/updates/` (format and query commands: `docs/updates/README.md`). No finished items, no history, no rules (rules live in `CLAUDE.md`).
Item numbers (`#n`) are never reused. Tags: [DECIDE] needs the owner's decision, [BLOCKED] waits on something else, [UNVERIFIED] observed but not confirmed.
Cross-repo and workspace items live in `D:\Codes\progress.md` (relevant here: L-6, X-12).

## Open

- **#4** Move WebRunner's other copies onto this package, as its executor was (WebRunner U-20261001-47):
  - `utils/package_manager/package_manager_class.py`: gate on by default, with an allowlist (`allow_packages`).
  - `utils/callback/callback_function_executor.py`: a separate `event_dict`.
  - `utils/json/json_file/json_file.py`.
  - `utils/socket_server/web_runner_socket_server.py`: 459 lines.

  Each needs characterization tests first, as LoadDensity's and FileAutomation's servers had. Jeffrey_RPA loads
  WebRunner's working tree live, so check `AI_CONTEXT.md` §5 before each step.
