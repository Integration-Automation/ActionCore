import json

import pytest

from je_action_core import (
    ActionJsonException,
    ActionJsonFile,
    JsonFileMessages,
    JsonFileSettings,
    read_action_json,
    write_action_json,
)


def test_round_trip_keeps_non_ascii_text(tmp_path):
    path = tmp_path / "actions.json"
    write_action_json(str(path), {"doc": [["say", ["測試"]]]})
    assert "測試" in path.read_text(encoding="utf-8")
    assert read_action_json(str(path)) == {"doc": [["say", ["測試"]]]}


def test_missing_and_invalid_files(tmp_path):
    with pytest.raises(ActionJsonException, match="can't find JSON file"):
        read_action_json(str(tmp_path / "missing.json"))
    bad = tmp_path / "bad.json"
    bad.write_text("{nope", encoding="utf-8")
    with pytest.raises(ActionJsonException, match="can't read JSON file") as caught:
        read_action_json(str(bad))
    assert isinstance(caught.value.__cause__, json.JSONDecodeError)


def test_unserialisable_data_leaves_the_file_unchanged(tmp_path):
    path = tmp_path / "keep.json"
    path.write_text("[1]", encoding="utf-8")
    with pytest.raises(ActionJsonException, match="can't write JSON file"):
        write_action_json(str(path), {"bad": object()})
    assert path.read_text(encoding="utf-8") == "[1]"


def test_project_messages_errors_and_log(tmp_path):
    logged = []
    store = ActionJsonFile(JsonFileSettings(
        error=KeyError, messages=JsonFileMessages(missing="gone: {path}", unreadable="broken: {error!r}",
                                                  unwritable="unsaved {path}"),
        log_info=logged.append))
    with pytest.raises(KeyError, match="gone"):
        store.read(str(tmp_path / "x.json"))
    (tmp_path / "bad.json").write_text("[", encoding="utf-8")
    with pytest.raises(KeyError, match="broken: JSONDecodeError"):
        store.read(str(tmp_path / "bad.json"))
    with pytest.raises(KeyError, match="unsaved"):
        store.write(str(tmp_path / "missing_dir" / "x.json"), [])
    assert logged[0].startswith("read_action_json: ")


def test_errors_outside_the_tuples_propagate(tmp_path):
    narrow = ActionJsonFile(JsonFileSettings(read_errors=(OSError,)))
    (tmp_path / "bad.json").write_text("[", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        narrow.read(str(tmp_path / "bad.json"))
    with pytest.raises(TypeError):
        narrow.read(None)
    broad = ActionJsonFile(JsonFileSettings(read_errors=(Exception,)))
    with pytest.raises(ActionJsonException):
        broad.read(None)
