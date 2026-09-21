import pytest

from bwf_player.exceptions import InvalidInputError
from bwf_player.names import derive_slug, normalize_name, sanitize_query


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Jonatan CHRISTIE", "jonatan christie"),
        ("  Adrian   CAPELLÁN ", "adrian capellan"),
        ("Alexander RINGBÆK", "alexander ringbaek"),
        ("O'Brien-Smith", "o brien smith"),
        ("Łukasz Đorđe", "lukasz dorde"),
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


def test_derive_slug() -> None:
    assert derive_slug("Jonatan CHRISTIE") == "jonatan-christie"
    assert derive_slug("Tzu Ying TAI") == "tzu-ying-tai"


def test_sanitize_strips_control_chars_and_whitespace() -> None:
    assert sanitize_query(" Jon\x00atan \n Christie\x07 ") == "Jon atan Christie"


@pytest.mark.parametrize("bad", ["", "   ", "!!!", None, 5, "x" * 101])
def test_sanitize_rejects_bad_input(bad: object) -> None:
    with pytest.raises(InvalidInputError):
        sanitize_query(bad)
