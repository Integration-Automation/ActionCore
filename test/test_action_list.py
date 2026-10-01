import warnings

import pytest

from je_action_core import (
    ActionExecuteException,
    ActionListRules,
    EmptyListPolicy,
    LegacyActionParser,
    StrictActionParser,
)


def _commands(name):
    return {"f": lambda *args, **kwargs: (args, kwargs)}.get(name)


class TestActionListRules:

    def test_list_and_document(self):
        rules = ActionListRules("api_testka")
        assert rules.extract([["f"]]) == [["f"]]
        assert rules.extract({"api_testka": [["f"]]}) == [["f"]]

    @pytest.mark.parametrize("bad", [{}, {"api_testka": None}, {"other": [["f"]]}])
    def test_missing_list_raises_with_the_key(self, bad):
        with pytest.raises(ActionExecuteException, match="'api_testka'"):
            ActionListRules("api_testka").extract(bad)

    def test_not_a_list_and_empty_have_their_own_messages(self):
        rules = ActionListRules("k", error=ValueError, not_list_message="got {type}", empty_message="empty")
        with pytest.raises(ValueError, match="got str"):
            rules.extract("abc")
        with pytest.raises(ValueError, match="empty"):
            rules.extract([])
        with pytest.raises(ValueError, match="empty"):
            rules.extract({"k": []})

    def test_return_empty_policy_runs_nothing(self):
        rules = ActionListRules("k", empty=EmptyListPolicy.RETURN_EMPTY)
        assert rules.extract([]) is None
        assert rules.extract("not a list") is None
        with pytest.raises(ActionExecuteException):
            rules.extract({"other": []})

    def test_legacy_key_still_works_with_a_deprecation_warning(self):
        rules = ActionListRules("mail_thunder", legacy_keys=("auto_control",))
        with pytest.warns(DeprecationWarning, match='"auto_control" key is deprecated'):
            assert rules.extract({"auto_control": [["f"]]}) == [["f"]]
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            assert rules.extract({"mail_thunder": [["f"]], "auto_control": []}) == [["f"]]


class TestLegacyActionParser:

    def test_shapes(self):
        parser = LegacyActionParser()
        assert parser.bind(["f"], _commands).args == ()
        bound = parser.bind(["f", {"a": 1}], _commands)
        assert bound.command(*bound.args, **bound.kwargs) == ((), {"a": 1})
        bound = parser.bind(["f", [1, 2]], _commands)
        assert bound.command(*bound.args, **bound.kwargs) == ((1, 2), {})

    def test_a_non_dict_payload_is_unpacked_as_given(self):
        bound = LegacyActionParser().bind(["f", "ab"], _commands)
        assert bound.command(*bound.args, **bound.kwargs) == (("a", "b"), {})

    def test_unknown_name_is_checked_before_the_shape(self):
        parser = LegacyActionParser(error=KeyError, message="bad data")
        with pytest.raises(KeyError, match="bad data \\['g', 1, 2\\]"):
            parser.bind(["g", 1, 2], _commands)
        with pytest.raises(KeyError, match="bad data \\['f', 1, 2\\]"):
            parser.bind(["f", 1, 2], _commands)

    def test_empty_action_raises_index_error(self):
        with pytest.raises(IndexError):
            LegacyActionParser().bind([], _commands)


class TestStrictActionParser:

    @pytest.mark.parametrize(("action", "message"), [
        ([], "malformed action: \\[\\]"),
        ("f", "malformed action: 'f'"),
        ([1], "action name must be str: \\[1\\]"),
        (["f", "ab"], "action 'f' payload must be dict or list, got str"),
        (["f", [], {}], "action has too many elements"),
        (["g"], "unknown action: 'g'"),
    ])
    def test_errors(self, action, message):
        with pytest.raises(ActionExecuteException, match=message):
            StrictActionParser().bind(action, _commands)

    def test_shape_is_checked_before_the_name(self):
        with pytest.raises(ActionExecuteException, match="too many"):
            StrictActionParser().bind(["unknown", [], {}], _commands)

    def test_parse_and_bind(self):
        parser = StrictActionParser()
        assert parser.parse(["f", {"a": 1}]).kind == "kwargs"
        assert parser.parse(["f", [1]]).kind == "args"
        assert parser.parse(["f"]).kind == "none"
        bound = parser.bind(["f", [1]], _commands)
        assert bound.command(*bound.args, **bound.kwargs) == ((1,), {})
        bound = parser.bind(["f", {"a": 1}], _commands)
        assert bound.command(*bound.args, **bound.kwargs) == ((), {"a": 1})
        assert parser.bind(["f"], _commands).name == "f"
