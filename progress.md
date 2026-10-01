# progress.md: ActionCore

Outstanding work only. When an item is done, delete it in the same commit and add a `#done` entry to `docs/updates/` (format and query commands: `docs/updates/README.md`). No finished items, no history, no rules (rules live in `CLAUDE.md`).
Item numbers (`#n`) are never reused. Tags: [DECIDE] needs the owner's decision, [BLOCKED] waits on something else, [UNVERIFIED] observed but not confirmed.
Cross-repo and workspace items live in `D:\Codes\progress.md` (relevant here: L-6, X-12).

## Open

- **#3** [DECIDE] Move WebRunner's executor onto this package too. It already has the package gate and `SAFE_BUILTINS`, but differs in `[cmd, [args], {kwargs}]` actions, `restricted()`, retries and spans.
