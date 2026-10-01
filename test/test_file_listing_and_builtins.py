import builtins
import os

from je_action_core import SAFE_BUILTINS, get_dir_files_as_list, safe_builtin_commands


def test_lists_matching_files_recursively_as_absolute_paths(tmp_path):
    (tmp_path / "sub").mkdir()
    for name in ("a.json", "sub/b.json", "c.txt", "D.JSON"):
        (tmp_path / name).write_text("[]", encoding="utf-8")
    found = sorted(os.path.basename(path) for path in get_dir_files_as_list(str(tmp_path)))
    assert found == ["a.json", "b.json"]
    assert all(os.path.isabs(path) for path in get_dir_files_as_list(str(tmp_path)))
    assert get_dir_files_as_list(str(tmp_path), ".TXT") == [os.path.abspath(tmp_path / "c.txt")]


def test_default_directory_is_the_current_one_at_call_time(tmp_path, monkeypatch):
    (tmp_path / "here.json").write_text("[]", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert get_dir_files_as_list() == [os.path.abspath("here.json")]


def test_missing_directory_gives_an_empty_list(tmp_path):
    assert get_dir_files_as_list(str(tmp_path / "missing")) == []


def test_safe_builtins_leave_out_code_execution_and_attribute_access():
    assert {"eval", "exec", "compile", "__import__", "open", "input", "getattr", "globals"}.isdisjoint(SAFE_BUILTINS)
    commands = safe_builtin_commands()
    assert list(commands) == sorted(SAFE_BUILTINS)
    assert commands["len"] is builtins.len
