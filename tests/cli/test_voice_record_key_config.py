from cli import _resolve_voice_record_key


def test_empty_record_key_falls_back_to_default():
    prompt_toolkit_key, display_key = _resolve_voice_record_key("")

    assert prompt_toolkit_key == "c-b"
    assert display_key == "CTRL+B"


def test_whitespace_or_non_string_record_key_falls_back_to_default():
    assert _resolve_voice_record_key("   ") == ("c-b", "CTRL+B")
    assert _resolve_voice_record_key(None) == ("c-b", "CTRL+B")


def test_alt_binding_is_preserved():
    assert _resolve_voice_record_key("alt+r") == ("a-r", "alt+r")
