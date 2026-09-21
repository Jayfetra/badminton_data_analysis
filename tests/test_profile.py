"""R2 personal details, offline against saved real API responses."""

from __future__ import annotations

import copy

import pytest

from bwf_player.exceptions import BlockedByCloudflareError, BwfClientError, InvalidInputError
from bwf_player.profile import get_profile, parse_profile
from fakes import FakeApiClient, load_fixture


@pytest.fixture
def client() -> FakeApiClient:
    return FakeApiClient()


def summary(name: str = "summary_christie.json") -> dict:
    return copy.deepcopy(load_fixture(name))


def test_right_handed_player(client: FakeApiClient) -> None:
    profile = get_profile("73442", client)
    assert profile.player_found is True
    assert profile.name == "Jonatan CHRISTIE"
    assert profile.nationality == "Indonesia"
    assert profile.height_cm == 179.0
    assert profile.playing_hand == "Right"
    assert profile.missing_fields == []
    assert profile.notes == []


def test_left_handed_player(client: FakeApiClient) -> None:
    profile = get_profile("18228", client)
    assert (profile.name, profile.nationality, profile.height_cm, profile.playing_hand) == (
        "Carolina MARIN", "Spain", 172.0, "Left")


def test_player_with_no_details_returns_nulls_and_notes_not_an_error(client: FakeApiClient) -> None:
    profile = get_profile("89438", client)
    assert profile.player_found is True
    assert profile.name == "Aadhya SHINE"
    assert profile.nationality is None
    assert profile.height_cm is None
    assert profile.playing_hand is None
    assert profile.missing_fields == ["nationality", "height", "playing_hand"]
    assert len(profile.notes) == 3
    assert all("not listed" in note for note in profile.notes)


def test_unknown_player_id(client: FakeApiClient) -> None:
    profile = get_profile("999999999", client)
    assert profile.player_found is False
    assert profile.missing_fields == ["nationality", "height", "playing_hand"]
    assert "No player with id 999999999" in profile.notes[0]


def test_one_request_with_only_validated_params(client: FakeApiClient) -> None:
    get_profile(73442, client)
    assert client.calls == [
        ("vue-player-summary", {"drawCount": 1, "playerId": "73442", "isPara": "false"})
    ]


@pytest.mark.parametrize("player_id", ["73442", 73442, " 73442 ", "0073442"])
def test_accepted_id_forms_are_normalised(client: FakeApiClient, player_id: object) -> None:
    assert get_profile(player_id, client).name == "Jonatan CHRISTIE"  # type: ignore[arg-type]
    assert client.calls[0][1]["playerId"] == "73442"


@pytest.mark.parametrize(
    "bad_id",
    ["abc", "", "  ", "12a", "-1", "1 2", "1.5", "0", 0, None, True, 1.5, "12345678901",
     "٣٤", "73442&isPara=true", "../1", "1;DROP TABLE"],
)
def test_malformed_ids_are_rejected_before_any_request(client: FakeApiClient, bad_id: object) -> None:
    with pytest.raises(InvalidInputError):
        get_profile(bad_id, client)  # type: ignore[arg-type]
    assert client.calls == []


def test_response_for_a_different_player_is_rejected() -> None:
    """The real API answers id 'abc' with an unrelated player; never return that data."""
    with pytest.raises(BwfClientError, match="received"):
        parse_profile(summary(), "18228")


@pytest.mark.parametrize("payload", [None, [], "text", {}, {"results": None}, {"results": "x"}, {"results": ["a"]}])
def test_malformed_payloads_raise_client_error(payload: object) -> None:
    with pytest.raises(BwfClientError):
        parse_profile(payload, "73442")


def test_empty_list_results_means_player_not_found() -> None:
    assert parse_profile({"results": []}, "5").player_found is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("179.00", 179.0), ("179", 179.0), (179, 179.0), ("178.5", 178.5), (" 180 ", 180.0)],
)
def test_height_formats(raw: object, expected: float) -> None:
    payload = summary()
    payload["results"]["bio_model"]["height"] = raw
    profile = parse_profile(payload, "73442")
    assert profile.height_cm == expected
    assert "height" not in profile.missing_fields


@pytest.mark.parametrize("raw", ["abc", "0.00", "-5", "301", "nan", "inf", "1e999", True, [], {}])
def test_unusable_height_becomes_null_with_a_note(raw: object) -> None:
    payload = summary()
    payload["results"]["bio_model"]["height"] = raw
    profile = parse_profile(payload, "73442")
    assert profile.height_cm is None
    assert "height" in profile.missing_fields
    assert any("unusable value" in note for note in profile.notes)
    assert profile.nationality == "Indonesia" and profile.playing_hand == "Right"


@pytest.mark.parametrize("raw", [None, ""])
def test_absent_height_is_a_plain_missing_field(raw: object) -> None:
    payload = summary()
    payload["results"]["bio_model"]["height"] = raw
    profile = parse_profile(payload, "73442")
    assert profile.missing_fields == ["height"]
    assert profile.notes == ["height is not listed on the player's profile."]


@pytest.mark.parametrize(("raw", "expected"), [(1, "Right"), ("1", "Right"), (2, "Left"), ("2", "Left")])
def test_hand_mapping(raw: object, expected: str) -> None:
    payload = summary()
    payload["results"]["bio_model"]["plays"] = raw
    assert parse_profile(payload, "73442").playing_hand == expected


@pytest.mark.parametrize("raw", [0, "0", 3, "R", "left", [], -1])
def test_unmapped_hand_value_is_null_with_a_note(raw: object) -> None:
    payload = summary()
    payload["results"]["bio_model"]["plays"] = raw
    profile = parse_profile(payload, "73442")
    assert profile.playing_hand is None
    assert profile.missing_fields == ["playing_hand"]
    assert any("does not map" in note for note in profile.notes)


def test_missing_country_falls_back_to_code_with_a_note() -> None:
    payload = summary()
    payload["results"]["country_model"] = None
    profile = parse_profile(payload, "73442")
    assert profile.nationality == "INA"
    assert profile.missing_fields == []
    assert any("country code" in note for note in profile.notes)


def test_no_country_and_no_code_is_missing() -> None:
    payload = summary()
    payload["results"]["country_model"] = None
    payload["results"]["nationality"] = None
    profile = parse_profile(payload, "73442")
    assert profile.nationality is None and profile.missing_fields == ["nationality"]


def test_missing_bio_model_only_affects_height_and_hand() -> None:
    payload = summary()
    payload["results"]["bio_model"] = None
    profile = parse_profile(payload, "73442")
    assert profile.nationality == "Indonesia"
    assert profile.missing_fields == ["height", "playing_hand"]


def test_cloudflare_block_propagates() -> None:
    class Blocked(FakeApiClient):
        def get_json(self, *args: object, **kwargs: object) -> object:
            raise BlockedByCloudflareError("blocked")

    with pytest.raises(BlockedByCloudflareError):
        get_profile("73442", Blocked())
