# CLAUDE.md - ActionCore Development Guide

## Project Overview

ActionCore (`je_action_core`) is the keyword-driven action executor shared by APITestka, LoadDensity, MailThunder
and FileAutomation: executor, command registry, package manager with the package gate, callback executor,
action-file reading and writing, action-file discovery, and the plain TCP action server.

- **Python**: 3.10+
- **Dependencies**: none (the standard library only). Keep it that way: every project that uses this package
  installs it.

## Build & Test Commands

```bash
pip install -e .          # Install in development mode
pip install pytest        # The only test dependency (CI: .github/requirements/ci.txt)
pytest                    # Run all tests
pytest -x                 # Stop on first failure
```

## Architecture

`architecture.md` has the layers (one module per piece), the flows and the contracts with the four projects (§6).
Every difference between projects is a **setting** (a frozen dataclass) or a hook, never a check for a project
name.

- **Template Method**: `ActionExecutor` runs the list; `invoke` and `run_one` are the override points.
- **Strategy**: the action parser (`LegacyActionParser`, `StrictActionParser`) and the reporter.
- **Registry**: `CommandRegistry` (`event_dict` is the live mapping projects already use).

## Coding Standards

### Security (Mandatory)

- The package gate in `package_manager.py` stops an action list from loading `os` or `subprocess` on its own.
  Its switches (`allow_packages`, `set_allow_arbitrary_packages`) must never become action commands.
- `SAFE_BUILTINS` is an allowlist: never add anything that runs code, reaches attributes or namespaces, or touches
  files or stdin (`eval`, `exec`, `compile`, `__import__`, `open`, `input`, `getattr`, `globals`, ...).
- No `eval()`, `exec()`, `pickle`, `shell=True`. Action files are read as UTF-8 JSON only.
- The socket server has no authentication: it binds exactly the host it is given; never default to `0.0.0.0`.

### Software Engineering Practices

- Single responsibility per module; no project-specific code in this package.
- A change to behaviour a project relies on (`architecture.md` §6) must change that project in the same round.
- Type hints and a docstring on every public function and class; non-obvious side effects stated.

### Static Analysis Compliance

Code must pass ruff (`E,F,W,C90,B,PL,SIM,I,S,N,UP` at 120 columns), Bandit-level security checks and SonarCloud /
Codacy without warnings:

- no bare `except:`; a broad `except Exception` only where the error becomes a record or is re-raised, with a
  comment saying so;
- no mutable default arguments (module-level default settings objects instead);
- cognitive complexity ≤ 15, cyclomatic complexity ≤ 10, ≤ 7 parameters (group them in a settings dataclass),
  functions ≤ 50 lines, files ≤ 500 lines, nesting ≤ 4, lines ≤ 120 characters;
- no magic numbers, no duplicated string literals (3+), no commented-out code, no `print()` outside `PrintReporter`;
- f-strings for new code.

## Testing Guidelines

- Every new feature, fix or refactor ships with tests in the same commit, under `test/test_<piece>.py`.
- A bug fix starts with a test that fails before the fix.
- A setting needs a test for each of its values.
- Run `pytest -x` before committing; CI runs Python 3.10–3.14 on Linux, macOS and Windows.

## Documentation

- **README parity.** `README.md` (English), `README/README_zh-TW.md` and `README/README_zh-CN.md` must stay current
  with the code and aligned with each other in the same commit: the translations reflect the English content, not
  only its headings. No automated parity guard exists; check by hand.
- `architecture.md` changes in the same commit as a change to its layers, flows or contracts.

## Stage commits, `progress.md`, `docs/updates/` and `architecture.md`

Workspace rule shared by every repository under `D:\Codes` (full text: `D:\Codes\CLAUDE.md`).

- **Commit at every stage.** A stage is the smallest piece of work that leaves the repository consistent and passes this project's checks (definition of done, tests, lint): one finished `progress.md` item, or one self-contained step of a larger one. Commit it before starting the next stage, before switching to another repository, and before the session ends. Do not leave work uncommitted across sessions; if a stage cannot be finished, commit the consistent part and record the rest in `progress.md`.
  - Stage only the files that stage touched (`git add <path>`, never `git add -A`), follow this file's commit-message rules, and never add AI attribution.
  - Committing is not pushing: push or open a PR only as this project's branch flow says or when asked.
  - **Commit and push frequently.** After each big feature — a self-contained stage that passes this project's checks — commit and push to the remote; do not pile up a large batch of work before committing or pushing. Smaller batches collide less with other sessions, let CI catch problems earlier, and are easier to revert. Follow this project's normal branch flow (`dev`).
  - **SonarCloud / Codacy findings.** When a PR or commit fails a SonarCloud or Codacy check, look the findings up through their APIs instead of guessing. The keys are in environment variables: `SonarCloudToken` (SonarCloud) and `CODACY_PROJECT_TOKEN` (a Codacy project token, valid only for its own project; for a public repository query the Codacy API without a key). **Never reveal a key or any personal credential while doing so**: refer to the variables by name only, never echo or print their values, and never put them in files, commit messages, PR or issue text, logs, or any output that leaves the machine.
- **`progress.md`** (repository root, tracked) holds outstanding work only: no finished items, no history, no rules.
- **`docs/updates/`** records finished work: one batch file per month (`YYYY-MM.md`), one entry per piece of work headed `## U-YYYYMMDD-NN · date · title · #tags`, and an index with query commands in `docs/updates/README.md`. When a `progress.md` item is done, delete it and add a `#done` entry plus its index row in the same commit.
- **`architecture.md`** (repository root) is the short architecture overview: layers, entry points, main flows, extension points, cross-project boundaries. Update it in the same commit whenever a change alters any of those.
- **Cross-project contracts** are listed in `architecture.md` §6: what other repositories rely on here and what this repository relies on elsewhere. No test here protects the consumers, so never rename or remove one without changing its consumers in the same round, and update §6 whenever a contract is added or changes.

## Commit Guidelines

- Write commit messages in English, in the form `type: short description`.
  - Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`, `security`, `ci`.
- **Do NOT mention any AI tools, assistants, or co-authors in commit messages**, and add no `Co-Authored-By` lines
  referencing AI.
- Say what changed and why.
- **Version numbers**: the publish workflow bumps the patch version on `main`. Never change the version by hand.
