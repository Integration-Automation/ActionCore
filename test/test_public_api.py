import je_action_core


def test_every_public_name_is_importable():
    missing = [name for name in je_action_core.__all__ if not hasattr(je_action_core, name)]
    assert missing == []
    assert len(set(je_action_core.__all__)) == len(je_action_core.__all__)


def test_the_package_declares_its_type_hints():
    """PEP 561: without py.typed, a type checker treats every import from here as Any."""
    from pathlib import Path
    assert (Path(je_action_core.__file__).parent / "py.typed").is_file()
