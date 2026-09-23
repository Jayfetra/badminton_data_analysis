"""R5 + R6: partners, opponents and per-game scores of one event's matches. Offline."""

from __future__ import annotations

import copy
import json
from datetime import date
from functools import lru_cache
from typing import Any

import pytest

from bwf_player.exceptions import BlockedByCloudflareError, BwfClientError, InvalidInputError
from bwf_player.matches import check_totals, get_matches, parse_matches
from bwf_player.models import PlayerMatch, TournamentEntry
from bwf_player.tournaments import get_tournaments
from tests.fakes import FIXTURES, FakeApiClient, load_fixture

TODAY = date(2026, 9, 21)
CHRISTIE, FAJAR, DEJAN, APRIYANI, AADHYA = 73442, 88876, 81458, 81462, 89438


@lru_cache(maxsize=None)
def _entries(player_id: int) -> tuple[TournamentEntry, ...]:
    return tuple(get_tournaments(player_id, FakeApiClient(), today=TODAY, with_categories=False).entries)


def _entry(player_id: int, tournament_id: int, event_id: int) -> TournamentEntry:
    return next(e for e in _entries(player_id) if (e.tournament_id, e.event_id) == (tournament_id, event_id))


def _matches(player_id: int, tournament_id: int, event_id: int) -> list[PlayerMatch]:
    return get_matches(player_id, _entry(player_id, tournament_id, event_id), FakeApiClient()).matches


def _games(match: PlayerMatch) -> list[tuple[int, int]]:
    return [(g.player_points, g.opponent_points) for g in match.games]


def _names(players: list[Any]) -> list[str]:
    return [p.name for p in players]


# ---------------------------------------------------------------- real data: singles

def test_a_full_singles_match_from_real_data() -> None:
    first = _matches(CHRISTIE, 5625, 28355)[0]
    assert first.model_dump() == {
        "match_id": 1539512,
        "match_code": "16",
        "tournament_id": 5625,
        "draw_id": 51388,
        "draw_name": "MS",
        "round": "R32",
        "match_date": date(2026, 9, 1),
        "duration_min": 44,
        "side": 1,
        "player": {"player_id": 73442, "name": "Jonatan CHRISTIE", "country": "INA"},
        "partner": None,
        "opponents": [{"player_id": 84838, "name": "LEONG Jun Hao", "country": "MAS"}],
        "won": True,
        "status": "played",
        "games": [
            {"game_no": 1, "player_points": 21, "opponent_points": 17},
            {"game_no": 2, "player_points": 21, "opponent_points": 19},
        ],
        "notes": [],
    }


def test_matches_come_oldest_first_with_both_results() -> None:
    matches = _matches(CHRISTIE, 5625, 28355)
    assert [m.round for m in matches] == ["R32", "R16"]
    assert [m.won for m in matches] == [True, False]
    assert matches[0].match_date <= matches[1].match_date


def test_games_are_oriented_to_the_subject_when_they_are_side_two() -> None:
    """Korea Open 2025: the site lists Christie as side 2 in every match."""
    matches = _matches(CHRISTIE, 5288, 25980)
    assert {m.side for m in matches} == {2}
    assert [m.round for m in matches] == ["R32", "R16", "QF", "SF", "Final"]
    assert all(m.won for m in matches)
    assert _games(matches[0]) == [(21, 11), (21, 17)]  # site: team1 11,17 / team2 21,21
    assert _games(matches[1]) == [(22, 20), (15, 21), (21, 15)]  # site: team1 20,21,15 / team2 22,15,21
    final = matches[-1]
    assert _names(final.opponents) == ["Anders ANTONSEN"]
    assert _games(final) == [(21, 10), (15, 21), (21, 17)]


def test_a_three_game_loss_is_oriented_correctly() -> None:
    """Finals group stage: the site lists Christie as side 2 and each opponent as side 1."""
    third = _matches(CHRISTIE, 5259, 25852)[2]
    assert third.won is False and third.round == "R3" and third.draw_name == "MS - Group A"
    assert _names(third.opponents) == ["Christo POPOV"]
    assert _games(third) == [(21, 18), (16, 21), (13, 21)]


def test_team_event_matches_have_the_same_shape() -> None:
    """Thomas Cup 2026: a team event, the subject is side 1, results are per tie."""
    matches = _matches(CHRISTIE, 5600, 1)
    assert {m.side for m in matches} == {1} and [m.won for m in matches] == [True, False, False]
    assert {m.draw_name for m in matches} == {"Thomas Cup - Group D"}
    assert _games(matches[0]) == [(21, 8), (21, 6)]
    assert _games(matches[1]) == [(16, 21), (22, 20), (20, 22)]
    assert _names(matches[1].opponents) == ["Kunlavut VITIDSARN"]


# ---------------------------------------------------------------- real data: doubles

def test_men_doubles_partner_opponents_and_scores() -> None:
    final = _matches(FAJAR, 5288, 25982)[-1]
    assert final.round == "Final" and final.won is False and final.side == 2
    assert final.player.name == "Fajar ALFIAN"
    assert final.partner.name == "Muhammad Shohibul FIKRI" and final.partner.country == "INA"
    assert _names(final.opponents) == ["KIM Won Ho", "SEO Seung Jae"]
    assert _games(final) == [(16, 21), (21, 23)]


def test_mixed_doubles_champion_run() -> None:
    matches = _matches(DEJAN, 5284, 25963)
    assert [m.round for m in matches] == ["R32", "R16", "QF", "SF", "Final"]
    assert {m.partner.name for m in matches} == {"Bernadine Anindiya WARDANA"}
    final = matches[-1]
    assert final.won is True
    assert _names(final.opponents) == ["Marwan FAZA", "Aisyah Salsabila Putri PRANATA"]
    assert _games(final) == [(21, 12), (21, 16)]
    assert _games(matches[0]) == [(21, 12), (22, 24), (21, 19)]  # a game lost 22-24 inside a win


def test_partner_is_found_when_the_subject_is_the_second_player_of_the_pair() -> None:
    """Apriyani RAHAYU is listed second in her pair."""
    match = _matches(APRIYANI, 5623, 28347)[0]
    assert match.player.name == "Apriyani RAHAYU" and match.partner.name == "Lanny Tria MAYASARI"


def test_team_event_partner_changes_from_tie_to_tie() -> None:
    matches = _matches(FAJAR, 5600, 3)
    assert [m.partner.name for m in matches] == [
        "Muhammad Shohibul FIKRI", "Nikolaus JOAQUIN", "Muhammad Shohibul FIKRI",
    ]
    assert all(m.won for m in matches)


def test_double_spaces_in_names_are_collapsed() -> None:
    first = _matches(FAJAR, 5600, 3)[0]
    assert _names(first.opponents) == ["Mohamed Abderrahime BELARBI", "Koceila MAMMERI"]


def test_qualification_and_main_draw_are_both_returned_even_when_a_draw_is_an_object() -> None:
    """Mixed doubles at the Ruichang China Masters 2026: the main draw arrives as {"2": {...}}, not a list."""
    raw = load_fixture("matches_81462_5623_28346.json")["results"]
    assert isinstance(raw["49642"], list) and isinstance(raw["49650"], dict)
    matches = _matches(APRIYANI, 5623, 28346)
    assert [(m.round, m.draw_name, m.draw_id) for m in matches] == [
        ("Qual. R16", "XD - Qualification", 49642),
        ("Qual. QF", "XD - Qualification", 49642),
        ("R32", "XD", 49650),
    ]
    assert [m.won for m in matches] == [True, True, False]
    assert {m.partner.name for m in matches} == {"Taufik ADERYA"}


def test_qualifying_and_doubles_at_the_same_tournament_are_separate_events() -> None:
    ws = _matches(AADHYA, 5306, 26122)
    wd = _matches(AADHYA, 5306, 26119)
    assert [(m.round, m.partner, m.won) for m in ws] == [("Qual. R64", None, False)]
    assert [(m.round, m.partner.name, m.won) for m in wd] == [("R32", "Nanda GHOSH", False)]
    assert _games(ws[0]) == [(19, 21), (21, 23)]


# ---------------------------------------------------------------- real data: unusual matches

def test_a_retirement_keeps_the_partial_game() -> None:
    """French Open 2025, R32: the opponents retired after one game."""
    match = _matches(FAJAR, 5257, 25839)[0]
    assert match.status == "retired" and match.won is True and match.round == "R32"
    assert _games(match) == [(21, 16)]
    assert _names(match.opponents) == ["HUANG Di", "LIU Yang"] and match.notes == []


def test_a_walkover_has_no_games_and_a_result() -> None:
    walkover = next(m for m in _matches(DEJAN, 5378, 26850) if m.status == "walkover")
    assert walkover.round == "R16" and walkover.won is False and walkover.games == []
    assert _names(walkover.opponents) == ["CHEN Yu-Che", "LIN Wan Ching"] and walkover.notes == []


def test_a_bye_is_not_a_played_match() -> None:
    bye = _matches(FAJAR, 5601, 27953)[0]
    assert (bye.round, bye.status, bye.won, bye.games, bye.opponents) == ("R64", "bye", None, [], [])
    assert bye.partner.name == "Muhammad Shohibul FIKRI" and bye.notes == []


def test_the_site_counts_a_bye_as_a_match_won() -> None:
    """Fajar's 2026 World Championships: 4 'matches' on the site, one of them the bye."""
    entry = _entry(FAJAR, 5601, 27953)
    matches = _matches(FAJAR, 5601, 27953)
    assert entry.matches_won + entry.matches_lost == len(matches) == 4
    assert sum(m.status == "bye" for m in matches) == 1
    assert check_totals(entry, matches) == (True, [])


# ---------------------------------------------------------------- reconciliation on every real event

def _fixture_events() -> list[tuple[int, TournamentEntry]]:
    found = []
    for player_id in (CHRISTIE, FAJAR, DEJAN, APRIYANI, AADHYA):
        for entry in _entries(player_id):
            if (FIXTURES / f"matches_{player_id}_{entry.tournament_id}_{entry.event_id}.json").exists():
                found.append((player_id, entry))
    return found


@pytest.mark.parametrize(
    ("player_id", "entry"), _fixture_events(), ids=lambda v: f"{v}" if isinstance(v, int) else f"{v.tournament_id}-{v.event_code}"
)
def test_every_real_event_reproduces_the_sites_totals(player_id: int, entry: TournamentEntry) -> None:
    result = get_matches(player_id, entry, FakeApiClient())
    assert result.totals_agree is True and result.notes == []
    assert all(m.notes == [] for m in result.matches)
    assert all(m.player.player_id == player_id and m.side in (1, 2) for m in result.matches)
    assert len(result.matches) == entry.matches_won + entry.matches_lost


def test_the_real_events_cover_all_the_unusual_cases() -> None:
    events = _fixture_events()
    assert len(events) == 29
    statuses = {
        m.status
        for player_id, entry in events
        for m in get_matches(player_id, entry, FakeApiClient()).matches
    }
    assert statuses == {"played", "bye", "walkover", "retired"}


def test_all_of_christies_nineteen_events_are_covered() -> None:
    covered = [e for pid, e in _fixture_events() if pid == CHRISTIE]
    assert len(covered) == 19 == len(_entries(CHRISTIE))
    total = sum(len(get_matches(CHRISTIE, e, FakeApiClient()).matches) for e in covered)
    assert total == sum(e.matches_won + e.matches_lost for e in covered) == 58


# ---------------------------------------------------------------- get_matches: requests and inputs

def test_one_request_with_the_right_parameters() -> None:
    client = FakeApiClient()
    get_matches(CHRISTIE, _entry(CHRISTIE, 5625, 28355), client)
    assert client.calls == [(
        "vue-player-tmt-matches",
        {"playerId": "73442", "tmtId": 5625, "tmtType": 0, "eventId": 28355,
         "activeTab": 3, "isPara": "false", "drawCount": 1, "locale": "en"},
    )]


def test_team_events_are_requested_with_their_tournament_type() -> None:
    client = FakeApiClient()
    get_matches(CHRISTIE, _entry(CHRISTIE, 5600, 1), client)
    assert client.calls_to("vue-player-tmt-matches")[0]["tmtType"] == 1


def test_player_id_may_be_text_and_the_entry_is_not_modified() -> None:
    entry = _entry(CHRISTIE, 5625, 28355)
    before = entry.model_copy(deep=True)
    assert len(get_matches(f" {CHRISTIE} ", entry, FakeApiClient()).matches) == 2
    assert entry == before


def test_entry_without_an_event_makes_no_request() -> None:
    entry = _entry(CHRISTIE, 5625, 28355).model_copy(update={"event_id": None, "event_code": None})
    client = FakeApiClient()
    result = get_matches(CHRISTIE, entry, client)
    assert client.calls == [] and result.matches == [] and result.totals_agree is None
    assert "no event" in result.notes[0]


@pytest.mark.parametrize("bad", ["abc", "0", -5, "", None, True, 1.5, "1" * 11])
def test_bad_player_id_is_rejected_before_any_request(bad: object) -> None:
    client = FakeApiClient()
    with pytest.raises(InvalidInputError):
        get_matches(bad, _entry(CHRISTIE, 5625, 28355), client)  # type: ignore[arg-type]
    assert client.calls == []


def test_an_event_with_no_matches_agrees_with_zero_totals() -> None:
    entry = _entry(CHRISTIE, 5625, 28355).model_copy(update={
        "event_id": 1, "matches_won": 0, "matches_lost": 0, "games_won": 0, "games_lost": 0,
        "points_for": 0, "points_against": 0,
    })
    result = get_matches(CHRISTIE, entry, FakeApiClient())  # the fake answers an unknown event with []
    assert result.matches == [] and result.totals_agree is True


def test_cloudflare_block_propagates() -> None:
    class Blocked:
        def get_json(self, *args: Any, **kwargs: Any) -> Any:
            raise BlockedByCloudflareError("blocked")

    with pytest.raises(BlockedByCloudflareError):
        get_matches(CHRISTIE, _entry(CHRISTIE, 5625, 28355), Blocked())  # type: ignore[arg-type]


# ---------------------------------------------------------------- check_totals

def _real_result() -> tuple[TournamentEntry, list[PlayerMatch]]:
    return _entry(CHRISTIE, 5625, 28355), _matches(CHRISTIE, 5625, 28355)


def test_totals_that_match_give_true() -> None:
    assert check_totals(*_real_result()) == (True, [])


@pytest.mark.parametrize(
    ("field", "label"),
    [("matches_won", "matches won"), ("matches_lost", "matches lost"), ("games_won", "games won"),
     ("games_lost", "games lost"), ("points_for", "points for"), ("points_against", "points against")],
)
def test_each_total_is_checked(field: str, label: str) -> None:
    entry, matches = _real_result()
    entry = entry.model_copy(update={field: getattr(entry, field) + 1})
    agree, differences = check_totals(entry, matches)
    assert agree is False and len(differences) == 1 and differences[0].startswith(label)


def test_missing_totals_are_skipped_and_none_at_all_gives_none() -> None:
    entry, matches = _real_result()
    partial = entry.model_copy(update={"games_won": None, "games_lost": None, "points_for": 1})
    agree, differences = check_totals(partial, matches)
    assert agree is False and [d.split(":")[0] for d in differences] == ["points for"]
    empty = entry.model_copy(update={k: None for k in (
        "matches_won", "matches_lost", "games_won", "games_lost", "points_for", "points_against")})
    assert check_totals(empty, matches) == (None, [])


def test_a_dropped_match_is_detected() -> None:
    entry, matches = _real_result()
    agree, differences = check_totals(entry, matches[:1])
    assert agree is False and any(d.startswith("matches lost") for d in differences)


# ---------------------------------------------------------------- parser robustness (synthetic)

def _raw(**over: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "id": 1, "tournament_draw_id": 10, "draw_name": "MS", "round_name": "R32",
        "match_time": "2026-03-03 00:00:00", "match_time_utc": "2026-03-02 16:00:00",
        "match_start_time_details": json.dumps({"dateLocal": "2026-03-03"}),
        "duration": 44, "winner": 1, "player_win": True, "status_name": "", "score_status": 0,
        "result_team1": 2, "result_team2": 0,
        "team1Score": "<span>21</span><span>21</span>", "team2Score": "<span>17</span><span>19</span>",
        "match_set_model": [{"ordering": 1, "team1": 21, "team2": 17}, {"ordering": 2, "team1": 21, "team2": 19}],
        "t1p1_player_model": {"id": 73442, "name_display": "Jonatan CHRISTIE"}, "t1p1_country": "INA",
        "t1p2_player_model": None,
        "t2p1_player_model": {"id": 84838, "name_display": "LEONG Jun Hao"}, "t2p1_country": "MAS",
        "t2p2_player_model": None,
    }
    raw.update(over)
    return raw


def _parse(*raws: dict[str, Any], draw: str = "10") -> tuple[list[PlayerMatch], list[str]]:
    return parse_matches({"results": {draw: list(raws)}}, CHRISTIE, 5625)


def _swap_sides(raw: dict[str, Any]) -> dict[str, Any]:
    """The same match with the two sides exchanged (the subject becomes side 2)."""
    swapped = dict(raw)
    for a, b in (("t1p1_player_model", "t2p1_player_model"), ("t1p1_country", "t2p1_country"),
                 ("t1p2_player_model", "t2p2_player_model"), ("team1Score", "team2Score"),
                 ("result_team1", "result_team2")):
        swapped[a], swapped[b] = raw.get(b), raw.get(a)
    swapped["match_set_model"] = [
        {"ordering": s["ordering"], "team1": s["team2"], "team2": s["team1"]} for s in raw["match_set_model"]
    ]
    swapped["winner"] = 3 - raw["winner"]
    return swapped


def test_swapping_the_sides_gives_the_same_match_from_the_subjects_view() -> None:
    (a,), _ = _parse(_raw())
    (b,), _ = _parse(_swap_sides(_raw()))
    assert (a.side, b.side) == (1, 2)
    assert a.model_copy(update={"side": 2}) == b


@pytest.mark.parametrize("payload", [None, [], "x", 5, {}, {"results": "x"}, {"results": 5}])
def test_unexpected_shapes_raise(payload: object) -> None:
    with pytest.raises(BwfClientError):
        parse_matches(payload, CHRISTIE, 5625)


@pytest.mark.parametrize("empty", [None, [], {}])
def test_no_results_means_no_matches(empty: object) -> None:
    assert parse_matches({"results": empty}, CHRISTIE, 5625) == ([], [])


def test_a_draw_that_is_neither_list_nor_object_is_noted_and_the_rest_is_kept() -> None:
    payload = {"results": {"1": "oops", "2": 7, "3": None, "10": [_raw()]}}
    matches, notes = parse_matches(payload, CHRISTIE, 5625)
    assert len(matches) == 1
    assert "Skipped 3 match(es)" in notes[0] and "unreadable list of matches" in notes[0]


def test_unreadable_matches_are_skipped_and_counted() -> None:
    no_id = _raw()
    del no_id["id"]
    stranger = _raw(t1p1_player_model={"id": 5, "name_display": "Someone ELSE"})
    both = _raw(t2p1_player_model={"id": 73442, "name_display": "Jonatan CHRISTIE"})
    matches, notes = _parse("text", 3, None, no_id, stranger, both, _raw(id=2))
    assert [m.match_id for m in matches] == [2]
    assert len(notes) == 1 and notes[0].startswith("Skipped 6 match(es)")
    assert "a match without an id" in notes[0] and "does not name the player on exactly one side" in notes[0]


def test_a_repeated_match_id_is_kept_once() -> None:
    matches, notes = parse_matches({"results": {"1": [_raw()], "2": [_raw()]}}, CHRISTIE, 5625)
    assert len(matches) == 1 and notes == []


def test_matches_are_sorted_by_start_time_then_id() -> None:
    late = _raw(id=1, match_time_utc="2026-03-04 10:00:00")
    early_b = _raw(id=3, match_time_utc="2026-03-02 10:00:00")
    early_a = _raw(id=2, match_time_utc="2026-03-02 10:00:00")
    matches, _ = _parse(late, early_b, early_a)
    assert [m.match_id for m in matches] == [2, 3, 1]


def test_ids_and_names_fall_back_to_the_flat_fields() -> None:
    raw = _raw(t1p1_player_model=None, team1_player1_id="73442", t1p1_firstname="Jonatan", t1p1_lastname="CHRISTIE",
               t2p1_player_model=None, team2_player1_id="84838")
    (match,), notes = _parse(raw)
    assert (match.player.player_id, match.player.name) == (73442, "Jonatan CHRISTIE")
    assert (match.opponents[0].player_id, match.opponents[0].name) == (84838, "Player 84838")
    assert notes == []


def test_a_partner_slot_that_is_empty_means_no_partner() -> None:
    (match,), _ = _parse(_raw(t1p2_player_model={"id": None, "name_display": " "}))
    assert match.partner is None


@pytest.mark.parametrize("winner", [None, 0, 3, "x", "", -1, True])
def test_unusable_winner_gives_won_none_and_a_note(winner: object) -> None:
    (match,), _ = _parse(_raw(winner=winner, player_win=None))
    assert match.won is None and "no usable winner" in match.notes[0]


def test_disagreement_with_player_win_is_noted_and_the_winner_is_used() -> None:
    (match,), _ = _parse(_raw(winner=1, player_win=False))
    assert match.won is True and "player_win" in match.notes[0]


@pytest.mark.parametrize(
    ("code", "name", "expected"),
    [(0, "", "played"), (1, "Walkover", "walkover"), (2, "Retired", "retired"), (3, "Disqualified", "disqualified"),
     (None, "", "played"), (None, "Walkover", "walkover"), (None, "retired", "retired"), ("2", "", "retired"),
     (9, "", "unknown"), (None, "Injured", "unknown")],
)
def test_status_from_the_code_or_the_name(code: object, name: str, expected: str) -> None:
    (match,), _ = _parse(_raw(score_status=code, status_name=name))
    assert match.status == expected


def test_games_are_ordered_by_their_ordering_field() -> None:
    sets = [{"ordering": 2, "team1": 21, "team2": 19}, {"ordering": 1, "team1": 21, "team2": 17}]
    (match,), _ = _parse(_raw(match_set_model=sets))
    assert _games(match) == [(21, 17), (21, 19)] and [g.game_no for g in match.games] == [1, 2]


def test_a_game_that_cannot_be_read_is_left_out_and_noted() -> None:
    sets = [{"ordering": 1, "team1": 21, "team2": 17}, {"ordering": 2, "team1": None, "team2": "x"}, "junk",
            {"ordering": 3, "team1": 21, "team2": 19}]
    (match,), _ = _parse(_raw(match_set_model=sets))
    assert _games(match) == [(21, 17), (21, 19)]
    assert match.notes.count("A game score could not be read and was left out.") == 2


def test_a_game_that_was_never_played_is_dropped() -> None:
    sets = [{"ordering": 1, "team1": 21, "team2": 17}, {"ordering": 2, "team1": 0, "team2": 0}]
    (match,), _ = _parse(_raw(match_set_model=sets, result_team1=1, result_team2=0))
    assert _games(match) == [(21, 17)]


@pytest.mark.parametrize("sets", [None, [], "x"])
def test_scores_are_read_from_the_score_text_when_the_game_list_is_missing(sets: object) -> None:
    (match,), _ = _parse(_raw(match_set_model=sets))
    assert _games(match) == [(21, 17), (21, 19)]
    assert match.notes == ["Game scores were read from the score text (no structured game list)."]


def test_score_text_of_different_lengths_gives_no_games() -> None:
    (match,), _ = _parse(_raw(match_set_model=[], team2Score="<span>17</span>"))
    assert match.games == [] and match.notes == ["No game scores were listed for a match marked as played."]


def test_games_that_disagree_with_the_recorded_result_are_noted() -> None:
    (match,), _ = _parse(_raw(result_team1=0, result_team2=2))
    assert match.notes == ["The game scores do not add up to the game result the site records for this match."]


def test_a_retirement_is_not_held_to_the_recorded_game_result() -> None:
    sets = [{"ordering": 1, "team1": 16, "team2": 21}]
    (match,), _ = _parse(_raw(match_set_model=sets, status_name="Retired", score_status=2, result_team1=0, result_team2=1, winner=2,
                          player_win=False))
    assert match.status == "retired" and match.won is False and match.notes == []


def test_a_bye_needs_the_bye_text_and_no_opponent() -> None:
    bye = _raw(t2p1_player_model=None, team2_player1_id=None, team2Score="<span>BYE&nbsp;&nbsp;</span>",
               team1Score="", match_set_model=[], result_team1=None, result_team2=None)
    (match,), _ = _parse(bye)
    assert (match.status, match.won, match.opponents, match.notes) == ("bye", None, [], [])
    # the text alone, with an opponent present, is not a bye
    (other,), _ = _parse(_raw(team2Score="<span>BYE</span>"))
    assert other.status == "played"
    # no opponent and no bye text is odd and is said so
    (odd,), _ = _parse(_raw(t2p1_player_model=None, team2_player1_id=None, match_set_model=[], team1Score="", team2Score=""))
    assert odd.status == "played" and "names no opponent" in " ".join(odd.notes)


def test_a_bye_word_inside_a_name_is_not_a_bye() -> None:
    (match,), _ = _parse(_raw(t2p1_player_model=None, team2_player1_id=None, team2Score="<span>ABYEY</span>",
                              team1Score="", match_set_model=[]))
    assert match.status == "played"


def test_a_days_rounds_are_ordered_by_actual_start_time_not_by_id() -> None:
    """Real case (Ruichang China Masters 2026): both qualifying rounds share a day and the id order is wrong."""
    def timed(match_id: int, **details: str) -> dict[str, Any]:
        return _raw(id=match_id, match_time_utc="2026-03-09 16:00:00",
                    match_start_time_details=json.dumps({"dateLocal": "2026-03-10", "dateUTC": "2026-03-10", **details}))

    matches, _ = _parse(
        timed(5, actualTimeUTC="06:17:00", timeUTC="06:15:00"),  # played second, lower id
        timed(9, actualTimeUTC="00:58:00", timeUTC="01:00:00"),  # played first, higher id
        timed(7, timeUTC="03:00:00"),  # no actual time: the scheduled time is used
    )
    assert [m.match_id for m in matches] == [9, 7, 5]


def test_local_date_is_preferred_over_match_time() -> None:
    (match,), _ = _parse(_raw(match_time="2026-03-02 00:00:00"))
    assert match.match_date == date(2026, 3, 3)  # dateLocal


@pytest.mark.parametrize("details", [None, "not json", "[]", "{}", json.dumps({"dateLocal": "soon"}), 5])
def test_date_falls_back_to_match_time(details: object) -> None:
    (match,), _ = _parse(_raw(match_start_time_details=details, match_time="2026-03-02 00:00:00"))
    assert match.match_date == date(2026, 3, 2)


def test_missing_dates_give_none() -> None:
    (match,), _ = _parse(_raw(match_start_time_details=None, match_time=None, match_time_utc=None))
    assert match.match_date is None


@pytest.mark.parametrize(("raw", "expected"), [(44, 44), ("44", 44), (0, None), (None, None), ("x", None), (-3, None)])
def test_duration(raw: object, expected: int | None) -> None:
    (match,), _ = _parse(_raw(duration=raw))
    assert match.duration_min == expected


def test_round_and_draw_names_are_cleaned_and_draw_id_falls_back_to_the_key() -> None:
    raw = _raw(round_name="  Qual.   R16 ", draw_name=None, tournament_draw_id=None)
    (match,), _ = _parse(raw, draw="4711")
    assert (match.round, match.draw_name, match.draw_id) == ("Qual. R16", None, 4711)


def test_parser_does_not_mutate_its_input() -> None:
    payload = load_fixture("matches_81462_5623_28346.json")
    before = copy.deepcopy(payload)
    parse_matches(payload, APRIYANI, 5623)
    assert payload == before
