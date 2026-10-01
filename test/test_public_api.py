import je_action_core


def test_every_public_name_is_importable():
    missing = [name for name in je_action_core.__all__ if not hasattr(je_action_core, name)]
    assert missing == []
    assert len(set(je_action_core.__all__)) == len(je_action_core.__all__)
