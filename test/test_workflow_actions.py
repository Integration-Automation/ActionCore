"""Every GitHub Actions step pins its action to a commit SHA.

A tag such as ``@v4`` can be moved to new code at any time (the 2025
tj-actions/changed-files compromise rewrote tags), so each ``uses:`` names a
full 40-hex commit and carries the release it corresponds to as a comment,
which is what Dependabot reads and updates. Pinning also keeps Node 20 actions
from lingering unnoticed: GitHub removed Node 20 from its runners on 2026-09-23.

The rest of the workflow supply chain is guarded here too: Dependabot's
settings, checkout credentials, job timeouts, and the hash-locked tooling and
build backend of the job that holds the PyPI token.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = next(p for p in Path(__file__).resolve().parents if (p / ".github" / "workflows").is_dir())
_WORKFLOWS = sorted((_ROOT / ".github" / "workflows").glob("*.yml"))
_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)(.*)$")
_PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
_LOCAL = re.compile(r"^\./")
_VERSION_COMMENT = re.compile(r"^\s+#\s*v\d+(\.\d+)*\s*$")


def _uses(path: Path) -> list[tuple[int, str, str]]:
    """Return ``(line number, action reference, rest of line)`` for each remote ``uses:``."""
    found = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = _USES.match(line)
        if match and not _LOCAL.match(match.group(1)):
            found.append((number, match.group(1), match.group(2)))
    return found


def test_workflows_exist():
    assert _WORKFLOWS


@pytest.mark.parametrize("workflow", _WORKFLOWS, ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_commit_with_its_version(workflow):
    bad = [f"{workflow.name}:{number} {ref}{rest}"
           for number, ref, rest in _uses(workflow)
           if not (_PINNED.match(ref) and _VERSION_COMMENT.match(rest))]
    assert bad == []


def test_one_version_per_action():
    # The same action at two different commits means a partial upgrade.
    seen: dict[str, set[str]] = {}
    for workflow in _WORKFLOWS:
        for _number, ref, _rest in _uses(workflow):
            action, _, sha = ref.partition("@")
            seen.setdefault(action, set()).add(sha)
    assert {action: shas for action, shas in seen.items() if len(shas) > 1} == {}


def test_dependabot_keeps_pins_current_on_dev():
    # Pinned SHAs only stay current if something bumps them; every update
    # goes to dev because main is the release branch. Parsed as text: PyYAML
    # is not a test dependency.
    text = (_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    blocks = re.split(r"^\s*-\s*package-ecosystem:", text, flags=re.MULTILINE)[1:]
    ecosystems = {block.split()[0].strip("\"'") for block in blocks}
    assert {"pip", "github-actions"} <= ecosystems
    assert all(re.search(r"^\s*target-branch:\s*\"dev\"", block, re.MULTILINE)
               for block in blocks)


def test_dependabot_waits_a_week_before_proposing_a_release():
    # A compromised release is usually found and yanked within days. Dependabot's
    # own default wait is 3 days, and zizmor's dependabot-cooldown audit asks
    # for 7. The wait never delays security updates.
    text = (_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    blocks = re.split(r"^\s*-\s*package-ecosystem:", text, flags=re.MULTILINE)[1:]
    days = [re.search(r"^\s*default-days:\s*(\d+)", block, re.MULTILINE) for block in blocks]
    assert blocks and all(match and int(match.group(1)) >= 7 for match in days)


def test_dependabot_watches_the_hash_locked_requirements():
    # From "/" Dependabot does not reach .github/requirements/, so the directory
    # has to be named or its locks are never updated.
    text = (_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    blocks = re.split(r"^\s*-\s*package-ecosystem:", text, flags=re.MULTILINE)[1:]
    pip = next(block for block in blocks if block.split()[0].strip("\"'") == "pip")
    settings = "\n".join(line for line in pip.splitlines() if not line.lstrip().startswith("#"))
    assert re.search(r"^\s*directories:", settings, re.MULTILINE)
    assert set(re.findall(r"\"(/[^\"]*)\"", settings)) == {"/", "/.github/requirements"}


def _checkout_steps(path: Path) -> list[tuple[int, str]]:
    """Return ``(line number, step text)`` for each ``actions/checkout`` step."""
    lines = path.read_text(encoding="utf-8").splitlines()
    steps = []
    for index, line in enumerate(lines):
        if not re.search(r"uses:\s*actions/checkout@", line):
            continue
        column = line.index("uses:")
        body = [line]
        for following in lines[index + 1:]:
            indent = len(following) - len(following.lstrip())
            if following.strip() and (indent < column or following.lstrip().startswith("- ")):
                break
            body.append(following)
        steps.append((index + 1, "\n".join(body)))
    return steps


@pytest.mark.parametrize("workflow", _WORKFLOWS, ids=lambda p: p.name)
def test_every_checkout_decides_on_persisted_credentials(workflow):
    # actions/checkout leaves the job token in .git/config unless told not
    # to, where every later step (and any uploaded workspace) can read it.
    # Only jobs that push keep it, and they say so.
    bad = [f"{workflow.name}:{number}" for number, step in _checkout_steps(workflow)
           if not re.search(r"^\s*persist-credentials:\s*(true|false)\b", step, re.MULTILINE)]
    assert bad == []


_JOB_HEAD = re.compile(r"^  [A-Za-z0-9_-]+:\s*(#.*)?$")


def _jobs(path: Path) -> list[tuple[str, str]]:
    """Return ``(job id, job text)`` for each job under ``jobs:`` in a workflow."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(r"^jobs:\s*(#.*)?$", line))
    heads = [i for i in range(start + 1, len(lines)) if _JOB_HEAD.match(lines[i])]
    ends = [*heads[1:], len(lines)]
    return [(lines[i].strip().rstrip(":"), "\n".join(lines[i:end])) for i, end in zip(heads, ends, strict=True)]


@pytest.mark.parametrize("workflow", _WORKFLOWS, ids=lambda p: p.name)
def test_every_job_has_a_timeout(workflow):
    # Without timeout-minutes a hung job runs for GitHub's default six hours.
    # Each job sets about three times its slowest recent run, at least 15 minutes.
    bad = [name for name, body in _jobs(workflow)
           if "runs-on:" in body and not re.search(r"^\s*timeout-minutes:", body, re.MULTILINE)]
    assert bad == []


_REQUIREMENTS = _ROOT / ".github" / "requirements"
_LOCKED_INSTALL = "python -m pip install --require-hashes --only-binary :all: -r .github/requirements/publish.txt"
_PIP_INSTALL = re.compile(r"(?:python3? -m )?\bpip3? install\b.*")
_HEREDOC = re.compile(r"<<-?'?(\w+)'?\n(.*?)\n\s*\1$", re.DOTALL | re.MULTILINE)
_MODULE = re.compile(r"python3? -m ([A-Za-z_]\w*)")
_COMMAND = re.compile(r"^\s*(?:-\s*)?(?:run:\s*)?([a-z][\w.-]*)(?=\s|$)", re.MULTILINE)
_IMPORT = re.compile(r"^\s*(?:import|from) ([A-Za-z_]\w*)", re.MULTILINE)
# Commands the runner image supplies; any other command a job runs has to come from the lock.
_RUNNER_COMMANDS = {"python", "git", "gh"}


def _publish_jobs() -> list[tuple[str, str]]:
    """Return ``(workflow:job, job text without comment lines)`` for each job that reads the PyPI token."""
    found = []
    for workflow in _WORKFLOWS:
        for name, body in _jobs(workflow):
            if "secrets.PYPI_API_TOKEN" in body:
                code = [line for line in body.splitlines() if not line.lstrip().startswith("#")]
                found.append((f"{workflow.name}:{name}", "\n".join(code)))
    return found


_PUBLISH_JOBS = _publish_jobs()


def _distribution(name: str) -> str:
    """Return a module, command or requirement name the way PyPI spells a distribution."""
    return name.lower().replace("_", "-")


def _tools(body: str) -> set[str]:
    """Return the distributions a job needs besides pip, the standard library and the runner's commands.

    They are what it runs with ``python -m``, the commands that start a shell line, and what its
    inline scripts (heredocs) import.
    """
    shell = body.replace("\\\n", " ")
    scripts = "\n".join(match.group(2) for match in _HEREDOC.finditer(shell))
    shell = _HEREDOC.sub("", shell)
    named = {*_MODULE.findall(shell), *_COMMAND.findall(shell), *_IMPORT.findall(scripts)}
    return {_distribution(name) for name in named - _RUNNER_COMMANDS - {"pip"} - set(sys.stdlib_module_names)}


def _requirements(name: str) -> set[str]:
    """Return the distributions a file in ``.github/requirements`` names, one at the start of a line."""
    text = (_REQUIREMENTS / name).read_text(encoding="utf-8")
    return {_distribution(found) for found in re.findall(r"^([A-Za-z0-9][\w.-]*)", text, re.MULTILINE)}


def test_the_job_that_holds_the_pypi_token_is_the_publish_job():
    assert [name for name, _body in _PUBLISH_JOBS] == ["publish.yml:publish"]


@pytest.mark.parametrize("body", [body for _name, body in _PUBLISH_JOBS], ids=[name for name, _body in _PUBLISH_JOBS])
def test_publish_job_installs_only_the_hash_locked_tooling(body):
    # Whatever this job installs runs next to the PyPI token. An unpinned
    # "pip install build twine", or upgrading pip first, takes the newest upload
    # of that day; the lock allows only wheels whose hashes were recorded.
    assert [command.strip() for command in _PIP_INSTALL.findall(body)] == [_LOCKED_INSTALL]


_BUILD = re.compile(r"\bpython3? -m build\b[^\n]*")
_BUILD_REQUIRES = re.compile(r"^\[build-system\]\n(?:(?!\[).*\n)*?requires\s*=\s*\[([^\]]*)\]", re.MULTILINE)
_REQUIREMENT = re.compile(r"([A-Za-z0-9][\w.-]*)\s*(?:>=\s*(\d+(?:\.\d+)*))?")


def _version(text: str) -> tuple[int, ...]:
    """Return a dotted release number as a tuple that compares in version order (``82.0`` equals ``82``)."""
    return tuple(int(part) for part in re.sub(r"(\.0+)+$", "", text).split("."))


def _build_requires() -> dict[str, tuple[int, ...]]:
    """Return ``{distribution: lowest version allowed}`` for ``build-system.requires`` in ``pyproject.toml``.

    An entry is a bare name or ``name>=version``. Any other form fails here, so the comparison with
    the lock gets extended before such an entry is relied on.
    """
    text = (_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    entries = re.findall(r"[\"']([^\"']+)[\"']", _BUILD_REQUIRES.search(text).group(1))
    matches = [_REQUIREMENT.fullmatch(entry.strip()) for entry in entries]
    assert all(matches), entries
    return {_distribution(match.group(1)): _version(match.group(2) or "0") for match in matches}


def _locked_version(distribution: str) -> tuple[int, ...]:
    """Return the version ``publish.txt`` pins for ``distribution``."""
    lock = (_REQUIREMENTS / "publish.txt").read_text(encoding="utf-8")
    pin = re.search(rf"^{re.escape(distribution)}==(\d+(?:\.\d+)*)\s", lock, re.MULTILINE)
    return _version(pin.group(1))


def test_publish_in_lists_exactly_the_tools_the_job_runs_and_the_build_backend():
    # A tool the job starts using has to be locked first, or the release fails at that step. The job
    # never names the build backend: python -m build --no-isolation imports the one installed here.
    used = set().union(*(_tools(body) for _name, body in _PUBLISH_JOBS))
    assert used | set(_build_requires()) == _requirements("publish.in")


@pytest.mark.parametrize("body", [body for _name, body in _PUBLISH_JOBS], ids=[name for name, _body in _PUBLISH_JOBS])
def test_publish_job_builds_with_the_locked_backend(body):
    # An isolated build downloads the newest release that build-system.requires allows, outside the
    # lock, and runs it in the job that is about to upload with the token.
    builds = _BUILD.findall(body)
    assert builds and all("--no-isolation" in command.split() for command in builds)


def test_the_locked_build_backend_satisfies_build_system_requires():
    # --no-isolation checks build-system.requires instead of installing it, so a floor raised without
    # regenerating the lock (Dependabot edits pyproject.toml) has to fail here, not in the publish job.
    required = _build_requires()
    assert required and set(required) <= _requirements("publish.txt")
    assert {name: floor for name, floor in required.items() if _locked_version(name) < floor} == {}


def test_publish_lock_pins_every_tool_of_publish_in():
    # publish.txt is generated; editing publish.in alone changes nothing the job installs.
    assert _requirements("publish.in") <= _requirements("publish.txt")


def test_publish_lock_is_resolved_for_the_python_the_job_sets_up():
    # The lock holds the wheels of one Python version; a job on another one may find none that match.
    header = (_REQUIREMENTS / "publish.txt").read_text(encoding="utf-8").splitlines()[1]
    locked_for = re.search(r"--python-version (\S+)", header).group(1)
    set_up = {version for _name, body in _PUBLISH_JOBS
              for version in re.findall(r"python-version:\s*\"([^\"]+)\"", body)}
    assert set_up == {locked_for}
