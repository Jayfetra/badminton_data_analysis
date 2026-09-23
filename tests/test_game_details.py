"""R8: the details of one match (the Match tab and one tab per game). Offline, on real fixtures."""

from __future__ import annotations

import copy
from datetime import date, datetime
from functools import lru_cache
from typing import Any, Callable

import pytest

from bwf_player import get_matches, get_tournaments
from bwf_player.exceptions import (
    BlockedByCloudflareError,
    BwfClientError,
    BwfNotFoundError,
    InvalidInputError,
)
from bwf_player.game_details import (
    check_against_match,
    check_internal,
    details_targets,
    format_match_details,
    game_point_rallies,
    get_match_details,
    longest_runs,
    parse_match_details,
)
from bwf_player.models import DetailPlayer, MatchPlayer, PlayerMatch, Rally, SideStats
from tests.fakes import FIXTURES, FakeApiClient, load_fixture

TODAY = date(2026, 9, 21)
PLAYERS = (73442, 88876, 81458, 81462, 89438)  # Christie, Fajar, Dejan, Apriyani, Aadhya
EXAMPLE = (5515, 13)  # the match from the request: All England 2026, R16, LIN Chun-Yi v Christie


def _raw(tournament: int, code: int) -> dict[str, Any]:
    return copy.deepcopy(load_fixture(f"h2h_match_{tournament}_{code}.json"))


def _details(tournament: int, code: int, **kwargs: Any) -> Any:
    return get_match_details(tournament, code, FakeApiClient(), **kwargs)


def _parse(raw: dict[str, Any], tournament: int = 5515, code: str = "13") -> Any:
    return parse_match_details(raw, tournament, code)


def _mutated(change: Callable[[dict[str, Any]], None], tournament: int = 5515, code: int = 13) -> Any:
    raw = _raw(tournament, code)
    change(raw)
    return _parse(raw, tournament, str(code))


@lru_cache(maxsize=None)
def _real_matches() -> tuple[tuple[int, PlayerMatch], ...]:
    """Every real match with a code that has details in the fixtures, with the player it was downloaded for."""
    client, found = FakeApiClient(), []
    for player in PLAYERS:
        for entry in get_tournaments(player, client, today=TODAY, with_categories=False).entries:
            for match in details_targets(get_matches(player, entry, client).matches):
                if (FIXTURES / f"h2h_match_{match.tournament_id}_{match.match_code}.json").exists():
                    found.append((player, match))
    return tuple(found)


def _match(player: int, tournament: int, code: int) -> PlayerMatch:
    return next(m for p, m in _real_matches() if p == player and m.tournament_id == tournament and m.match_code == str(code))


def _games(details: Any) -> list[tuple[int, int]]:
    return [(g.side1_points, g.side2_points) for g in details.games]


GAME_1_SEQUENCE = (
    "0-1 1-1 1-2 2-2 3-2 3-3 3-4 4-4 5-4 5-5 6-5 6-6 7-6 8-6 9-6 9-7 9-8 9-9 9-10 9-11 10-11 11-11 12-11 13-11 14-11 "
    "15-11 16-11 16-12 16-13 17-13 17-14 18-14 19-14 20-14 20-15 20-16 20-17 20-18 20-19 21-19"
)


# ---------------------------------------------------------------- the example from the request

def test_the_match_tab_of_the_example_match() -> None:
    d = _details(*EXAMPLE)
    assert d.model_dump(exclude={"games"}) == {
        "match_id": 1505450,
        "tournament_id": 5515,
        "match_code": "13",
        "tournament_name": "All England Open Badminton Championships 2026",
        "draw_name": "MS",
        "round": "R16",
        "start_local": datetime(2026, 3, 5, 19, 15),
        "venue": "Utilita Arena Birmingham",
        "duration_min": 48,
        "winner_side": 1,
        "score_status": 0,
        "side1_players": [{"player_id": 86114, "name": "LIN Chun-Yi", "slug": "chun-yi-lin", "country": "Chinese Taipei"}],
        "side2_players": [{"player_id": 73442, "name": "Jonatan CHRISTIE", "slug": "jonatan-christie", "country": "Indonesia"}],
        "side1_result": 2,
        "side2_result": 0,
        "side1": SideStats(consecutive_points=7, game_points=7, rallies_played=73, rallies_won=42, other=0,
                           challenge_used=0, challenge_won=0, challenge_lost=0, challenge_nodecision=0).model_dump(),
        "side2": SideStats(consecutive_points=5, game_points=0, rallies_played=73, rallies_won=31, other=0,
                           challenge_used=0, challenge_won=0, challenge_lost=0, challenge_nodecision=0).model_dump(),
        "tracked": True,
        "checks_ok": True,
        "differences": [],
        "notes": [],
    }


def test_the_game_tabs_of_the_example_match() -> None:
    d = _details(*EXAMPLE)
    assert _games(d) == [(21, 19), (21, 12)] and [g.game_no for g in d.games] == [1, 2]
    one, two = d.games
    assert (one.total_points_played, two.total_points_played) == (40, 33) and one.tracked and two.tracked
    assert (one.side1.consecutive_points, one.side1.game_points, one.side1.rallies_played, one.side1.rallies_won) == (7, 6, 40, 21)
    assert (one.side2.consecutive_points, one.side2.game_points, one.side2.rallies_played, one.side2.rallies_won) == (5, 0, 40, 19)
    assert (two.side1.consecutive_points, two.side1.game_points, two.side1.rallies_played, two.side1.rallies_won) == (5, 1, 33, 21)
    assert (two.side2.consecutive_points, two.side2.game_points, two.side2.rallies_played, two.side2.rallies_won) == (4, 0, 33, 12)


def test_the_rally_by_rally_progression_of_game_one() -> None:
    game = _details(*EXAMPLE).games[0]
    assert " ".join(f"{r.side1_points}-{r.side2_points}" for r in game.rallies) == GAME_1_SEQUENCE
    assert [r.rally_no for r in game.rallies] == list(range(1, 41))
    assert [r.winner_side for r in game.rallies[:4]] == [2, 1, 2, 1]  # 0-1, 1-1, 1-2, 2-2
    assert sum(r.winner_side == 1 for r in game.rallies) == 21 and sum(r.winner_side == 2 for r in game.rallies) == 19


def test_the_request_made() -> None:
    client = FakeApiClient()
    get_match_details(5515, 13, client)
    assert client.calls == [("h2h/match", {"tmt_id": 5515, "match_code": "13"})]


def test_ids_may_be_text() -> None:
    client = FakeApiClient()
    assert get_match_details(" 5515 ", " 13 ", client).match_id == 1505450
    assert client.calls[0][1] == {"tmt_id": 5515, "match_code": "13"}


# ---------------------------------------------------------------- every real match agrees with itself and with our data

def test_the_real_matches_cover_every_case() -> None:
    real = _real_matches()
    assert len(real) == 88
    statuses = {m.status for _, m in real}
    assert statuses == {"played", "retired"}
    assert sum(1 for p, _ in real if p == 73442) == 58  # all of Christie's matches


@pytest.mark.parametrize(("player", "match"), _real_matches(), ids=lambda v: f"{v}" if isinstance(v, int) else f"{v.tournament_id}-{v.match_code}")
def test_every_real_match_passes_all_checks(player: int, match: PlayerMatch) -> None:
    details = get_match_details(match.tournament_id, match.match_code, FakeApiClient(), match=match)
    assert details.differences == [], details.differences
    assert details.checks_ok is True and details.match_id == match.match_id
    assert details.round == match.round
    assert [(g.side1_points, g.side2_points) for g in details.games] == [
        (g.player_points, g.opponent_points) if match.side == 1 else (g.opponent_points, g.player_points) for g in match.games
    ]


def test_tracked_and_untracked_matches_among_the_real_ones() -> None:
    kinds = {get_match_details(m.tournament_id, m.match_code, FakeApiClient()).tracked for _, m in _real_matches()}
    assert kinds == {True, False}
    assert sum(not get_match_details(m.tournament_id, m.match_code, FakeApiClient()).tracked for _, m in _real_matches()) == 2


def test_the_match_level_longest_run_crosses_the_game_boundary() -> None:
    """Match 5227/3: side 2's run of 6 is longer than its best inside any single game (4)."""
    d = _details(5227, 3)
    assert max(g.side2.consecutive_points for g in d.games) == 4 and d.side2.consecutive_points == 6
    assert d.checks_ok is True


def test_the_match_level_figures_are_the_sums_over_the_games() -> None:
    d = _details(5207, 6)  # three games, one of them 21-23
    assert d.side1.game_points == sum(g.side1.game_points for g in d.games) == 8
    assert d.side2.rallies_won == sum(g.side2_points for g in d.games) == 58
    assert d.side1.rallies_played == sum(len(g.rallies) for g in d.games) == 121


# ---------------------------------------------------------------- other kinds of match

def test_doubles_details() -> None:
    d = _details(5288, 317)  # men's doubles final, Korea Open 2025
    assert [p.name for p in d.side1_players] == ["KIM Won Ho", "SEO Seung Jae"]
    assert [p.player_id for p in d.side2_players] == [88876, 91440]
    assert d.side2_players[0].country == "Indonesia" and (d.side1_result, d.side2_result) == (2, 0)
    assert _games(d) == [(21, 16), (23, 21)] and d.games[1].total_points_played == 44
    assert d.checks_ok is True


def test_team_event_details() -> None:
    d = _details(5600, 106)  # Thomas Cup, group D, R1
    assert d.draw_name == "Thomas Cup - Group D" and d.round == "R1" and d.venue == "Forum Horsens"
    assert [p.name for p in d.side1_players] == ["Jonatan CHRISTIE"] and _games(d) == [(21, 8), (21, 6)]
    assert d.checks_ok is True


def test_a_retirement_keeps_its_partial_game() -> None:
    d = _details(5257, 151)  # French Open 2025, R32: the Chinese pair retired
    assert d.score_status == 2 and d.winner_side == 2 and (d.side1_result, d.side2_result) == (0, 1)
    assert _games(d) == [(16, 21)] and d.games[0].tracked and d.checks_ok is True
    assert d.duration_min == 15


def test_a_long_game_counts_its_game_points() -> None:
    game = _details(5207, 6).games[1]  # 21-23
    assert (game.side1_points, game.side2_points) == (21, 23) and len(game.rallies) == 44
    assert (game.side1.game_points, game.side2.game_points) == (3, 1)


def test_a_match_without_tracking_has_only_scores_and_says_so() -> None:
    d = _details(5306, 276)  # Aadhya SHINE, qualifying, Telangana International Challenge
    assert d.tracked is False and d.side1 is None and d.side2 is None
    assert _games(d) == [(21, 19), (23, 21)] and [g.total_points_played for g in d.games] == [40, 44]
    assert all(not g.tracked and g.side1 is None and g.side2 is None and g.rallies == [] for g in d.games)
    assert (d.side1_result, d.side2_result) == (2, 0) and d.venue == "GMC Balayogi Sports Complex"
    assert d.checks_ok is None and d.differences == []  # nothing to check without the match
    assert len(d.notes) == 1 and "not tracked" in d.notes[0]


def test_untracked_details_are_still_checked_against_our_match() -> None:
    d = _details(5306, 276, match=_match(89438, 5306, 276))
    assert d.checks_ok is True and d.differences == []


def test_a_bye_and_a_walkover_have_no_games() -> None:
    bye = _details(5378, 535)  # Dejan FERDINANSYAH, R32 bye
    assert bye.games == [] and bye.side1_players == [] and len(bye.side2_players) == 2
    assert bye.start_local is None and bye.venue is None and bye.duration_min is None
    assert bye.winner_side == 2 and bye.checks_ok is None and bye.notes == []
    walkover = _details(5378, 521)
    assert walkover.games == [] and walkover.score_status == 1 and walkover.winner_side == 1
    assert len(walkover.side1_players) == 2 and walkover.side1 is None


def test_the_bye_and_walkover_are_not_requested() -> None:
    client = FakeApiClient()
    tournaments = get_tournaments(81458, client, since=date(2025, 11, 10), until=date(2025, 11, 17), with_categories=False)
    matches = get_matches(81458, tournaments.entries[0], client).matches
    assert sorted(m.status for m in matches) == ["bye", "walkover"]
    assert details_targets(matches) == []


# ---------------------------------------------------------------- which matches to request

def _pm(status: str = "played", code: str | None = "5") -> PlayerMatch:
    return PlayerMatch(match_id=1, match_code=code, tournament_id=2, side=1, player=MatchPlayer(player_id=1, name="A"), status=status)  # type: ignore[arg-type]


def test_details_targets_are_the_played_and_retired_matches_with_a_code() -> None:
    matches = [_pm("played"), _pm("retired"), _pm("bye"), _pm("walkover"), _pm("disqualified"), _pm("unknown"), _pm("played", None)]
    assert [m.status for m in details_targets(matches)] == ["played", "retired"]
    assert details_targets([]) == []


def test_matches_carry_their_code() -> None:
    codes = [m.match_code for m in get_matches(73442, next(e for e in get_tournaments(73442, FakeApiClient(), today=TODAY, with_categories=False).entries if e.tournament_id == 5625), FakeApiClient()).matches]
    assert codes == ["16", "8"]


# ---------------------------------------------------------------- errors and inputs

def test_a_match_the_site_does_not_have_raises_not_found() -> None:
    with pytest.raises(BwfNotFoundError):
        get_match_details(5515, 99999, FakeApiClient())


@pytest.mark.parametrize("bad", [0, -1, "abc", "", None, True, 1.5, "1" * 11, "1 2", [5515]])
def test_bad_tournament_ids_are_rejected_before_any_request(bad: object) -> None:
    client = FakeApiClient()
    with pytest.raises(InvalidInputError):
        get_match_details(bad, 13, client)  # type: ignore[arg-type]
    assert client.calls == []


@pytest.mark.parametrize("bad", ["", " ", None, True, -3, 1.5, "a b", "x" * 21, "13&tmt_id=1", "../13", ["13"]])
def test_bad_match_codes_are_rejected_before_any_request(bad: object) -> None:
    client = FakeApiClient()
    with pytest.raises(InvalidInputError):
        get_match_details(5515, bad, client)  # type: ignore[arg-type]
    assert client.calls == []


def test_cloudflare_block_propagates() -> None:
    class Blocked:
        def get_json(self, *args: Any, **kwargs: Any) -> Any:
            raise BlockedByCloudflareError("blocked")

    with pytest.raises(BlockedByCloudflareError):
        get_match_details(5515, 13, Blocked())  # type: ignore[arg-type]


# ---------------------------------------------------------------- the checks catch corruption

def _diffs(change: Callable[[dict[str, Any]], None], **kw: Any) -> list[str]:
    details = _mutated(change, **kw)
    assert details.checks_ok is False
    return details.differences


def _has(differences: list[str], *parts: str) -> bool:
    return any(all(part in d for part in parts) for d in differences)


def test_a_lost_rally_is_detected() -> None:
    d = _diffs(lambda r: r["games"][0]["match_set_details_model"].pop())
    assert _has(d, "Game 1", "40 points played but lists 39 rallies")
    assert _has(d, "Game 1", "39 rallies but the score 21-19 has 40 points")
    assert _has(d, "Game 1", "last rally ends 20-19, not the score 21-19")
    assert _has(d, "Game 1", "total points played", "the site says 40, the rallies give 39")
    assert _has(d, "Match", "total points played", "the site says 73, the games give 72")


def test_a_wrong_last_score_and_a_jump_are_detected() -> None:
    def change(raw: dict[str, Any]) -> None:
        raw["games"][0]["match_set_details_model"][-1].update(team1=21, team2=18)

    d = _diffs(change)
    assert _has(d, "Game 1", "last rally ends 21-18") and _has(d, "Game 1", "rally 40 does not add exactly one point")


def test_a_rally_that_skips_a_point_is_detected() -> None:
    def change(raw: dict[str, Any]) -> None:
        raw["games"][0]["match_set_details_model"][4]["team1"] = 4  # 2-2 -> 4-2

    assert _has(_diffs(change), "Game 1", "rally 5 does not add exactly one point")


def test_gaps_in_the_rally_numbers_are_detected() -> None:
    def change(raw: dict[str, Any]) -> None:
        raw["games"][0]["match_set_details_model"][4]["ordering"] = 50

    assert _has(_diffs(change), "Game 1", "rally numbers are not 1 to 40")


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("team1_consecutive_points", 8, "side 1 most consecutive points: the site says 8, the rallies give 7"),
        ("team2_game_points", 1, "side 2 game points: the site says 1, the rallies give 0"),
        ("team1_game_points", 5, "side 1 game points: the site says 5, the rallies give 6"),
        ("team1_rallies_won", 20, "side 1 total points won: the site says 20, the rallies give 21"),
        ("team2_rallies_played", 41, "side 2 total points played: the site says 41, the rallies give 40"),
    ],
)
def test_a_wrong_game_statistic_is_detected(field: str, value: int, expected: str) -> None:
    def change(raw: dict[str, Any]) -> None:
        raw["games"][0]["match_set_stats_model"][field] = value

    assert _has(_diffs(change), "Game 1", expected)


def test_a_wrong_total_points_played_is_detected() -> None:
    assert _has(_diffs(lambda r: r["games"][0].update(total_points_played=41)), "Game 1", "41 points played but lists 40 rallies")


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("team1_consecutive_points", 6, "Match: side 1 most consecutive points (across the whole match): the site says 6, the games give 7"),
        ("team1_rallies_won", 41, "Match: side 1 total points won: the site says 41, the games give 42"),
        ("team2_game_points", 3, "Match: side 2 game points: the site says 3, the games give 0"),
        ("team1_rallies_played", 70, "Match: side 1 total points played: the site says 70, the games give 73"),
    ],
)
def test_a_wrong_match_statistic_is_detected(field: str, value: int, expected: str) -> None:
    def change(raw: dict[str, Any]) -> None:
        raw["stats"][field] = value

    assert expected in _diffs(change)


def test_a_match_streak_that_is_only_the_best_game_is_detected() -> None:
    """The real match-level run crosses the game boundary, so quoting the per-game maximum is a difference."""
    def change(raw: dict[str, Any]) -> None:
        raw["stats"]["team2_consecutive_points"] = 4

    assert _has(_diffs(change, tournament=5227, code=3), "Match: side 2", "the site says 4, the games give 6")


def test_a_wrong_final_result_is_detected() -> None:
    assert "the final result 1-0 does not match the games won (2-0)" in _diffs(lambda r: r["stats"].update(team1_result=1, team2_result=0))


def test_a_retirement_is_not_held_to_the_final_result() -> None:
    details = _mutated(lambda r: r["stats"].update(team1_result=5), tournament=5257, code=151)
    assert details.checks_ok is True


def test_two_match_ids_in_one_response_are_detected() -> None:
    def change(raw: dict[str, Any]) -> None:
        raw["games"][1]["tournament_match_id"] = 1

    details = _mutated(change)
    assert details.match_id is None and _has(details.differences, "more than one match id")


def test_an_unreadable_game_is_skipped_and_reported() -> None:
    def change(raw: dict[str, Any]) -> None:
        raw["games"][1]["team1"] = None

    details = _mutated(change)
    assert _games(details) == [(21, 19)] and "game entry 2 has no readable score" in details.differences


def test_an_unreadable_rally_is_skipped_and_reported() -> None:
    def change(raw: dict[str, Any]) -> None:
        raw["games"][0]["match_set_details_model"][3]["team2"] = "x"

    details = _mutated(change)
    assert "Game 1: rally 4 has no readable score" in details.differences and len(details.games[0].rallies) == 39


# ---------------------------------------------------------------- checks against the match we already hold

def _ours() -> PlayerMatch:
    return _match(73442, 5515, 13)


def test_our_own_match_agrees_with_the_details() -> None:
    d = _details(*EXAMPLE, match=_ours())
    assert d.checks_ok is True and d.differences == []
    assert (_ours().side, _ours().won) == (2, False)  # Christie was side 2 and lost


def test_a_different_match_id_or_tournament_is_detected() -> None:
    d = _details(*EXAMPLE)
    assert check_against_match(d, _ours().model_copy(update={"match_id": 7})) == ["the details are for match 1505450, not 7"]
    assert check_against_match(d, _ours().model_copy(update={"tournament_id": 9})) == ["the details are for tournament 5515, not 9"]


def test_different_game_scores_are_detected() -> None:
    ours = _ours().model_copy(deep=True)
    ours.games[0].player_points = 20
    found = check_against_match(_details(*EXAMPLE), ours)
    assert len(found) == 1 and found[0].startswith("the game scores differ: details [(21, 19), (21, 12)]")


def test_different_players_are_detected() -> None:
    ours = _ours().model_copy(deep=True)
    ours.opponents = [MatchPlayer(player_id=5, name="Someone ELSE")]
    assert check_against_match(_details(*EXAMPLE), ours)[0].startswith("the players differ")


def test_a_wrong_side_is_detected() -> None:
    swapped = _ours().model_copy(update={"side": 1})
    found = check_against_match(_details(*EXAMPLE), swapped)
    assert any(f.startswith("the players differ") for f in found) and any(f.startswith("the game scores differ") for f in found)


def test_a_different_winner_is_detected() -> None:
    found = check_against_match(_details(*EXAMPLE), _ours().model_copy(update={"won": True}))
    assert found == ["the winner differs: details say side 1, ours side 2"]


def test_an_unknown_winner_is_not_compared() -> None:
    assert check_against_match(_details(*EXAMPLE), _ours().model_copy(update={"won": None})) == []


def test_the_checks_against_our_match_set_the_verdict() -> None:
    bad = _details(*EXAMPLE, match=_ours().model_copy(update={"won": True}))
    assert bad.checks_ok is False and bad.differences == ["the winner differs: details say side 1, ours side 2"]


# ---------------------------------------------------------------- parser robustness

@pytest.mark.parametrize("payload", [None, [], "x", 5, {}, {"games": []}, {"stats": None}, {"stats": None, "games": "x"}])
def test_unexpected_shapes_raise(payload: object) -> None:
    with pytest.raises(BwfClientError):
        parse_match_details(payload, 5515, "13")


def test_a_response_without_match_information_raises() -> None:
    with pytest.raises(BwfClientError, match="no match information"):
        parse_match_details({"stats": None, "games": []}, 5515, "13")  # the shape of the site's 404 body


def test_missing_optional_parts_give_nulls() -> None:
    raw = {"info": {"drawName": "MS", "roundName": "R32", "winner": 1}, "stats": None, "games": []}
    d = parse_match_details(raw, 5515, "13")
    assert (d.tournament_name, d.start_local, d.venue, d.duration_min, d.side1, d.side2) == (None, None, None, None, None, None)
    assert d.games == [] and d.side1_players == [] and d.checks_ok is None and d.winner_side == 1


@pytest.mark.parametrize("winner", [None, 0, 3, "x", "", True, -1])
def test_an_unusable_winner_is_none(winner: object) -> None:
    raw = _raw(*EXAMPLE)
    raw["info"]["winner"] = winner
    assert _parse(raw).winner_side is None


@pytest.mark.parametrize(("winner", "expected"), [(1, 1), (2, 2), ("1", 1), (" 2 ", 2)])
def test_a_winner_sent_as_text_is_read(winner: object, expected: int) -> None:
    raw = _raw(*EXAMPLE)
    raw["info"]["winner"] = winner
    assert _parse(raw).winner_side == expected


@pytest.mark.parametrize("value", [None, "", "soon", 5, "2026-03-05"])
def test_an_unreadable_start_time_is_none(value: object) -> None:
    raw = _raw(*EXAMPLE)
    raw["matchStartTimeDetails"]["dateTimeLocal"] = value
    expected = datetime(2026, 3, 5) if value == "2026-03-05" else None
    assert _parse(raw).start_local == expected


@pytest.mark.parametrize(("value", "expected"), [(48, 48), ("48", 48), (0, None), (None, None), ("x", None)])
def test_duration(value: object, expected: int | None) -> None:
    raw = _raw(*EXAMPLE)
    raw["progress"]["duration"] = value
    assert _parse(raw).duration_min == expected


def test_player_names_are_cleaned_from_the_pages_markup() -> None:
    raw = _raw(*EXAMPLE)
    raw["team1"]["player1"]["name_display_bold"] = '<span class="name-2">O&#39;BRIEN</span>  <span class="name-1">Se&amp;an</span>'
    assert _parse(raw).side1_players[0].name == "O'BRIEN Se&an"


def test_a_player_without_a_name_falls_back_to_the_slug_then_the_id() -> None:
    raw = _raw(*EXAMPLE)
    raw["team1"]["player1"]["name_display_bold"] = None
    assert _parse(raw).side1_players[0].name == "chun-yi-lin"
    raw["team1"]["player1"]["slug"] = None
    assert _parse(raw).side1_players[0].name == "Player 86114"
    raw["team1"]["player1"]["id"] = None
    assert _parse(raw).side1_players == []


def test_a_team_that_is_missing_or_odd_has_no_players() -> None:
    raw = _raw(*EXAMPLE)
    raw["team1"] = None
    raw["team2"] = {"player1": "x", "player2": None}
    d = _parse(raw)
    assert d.side1_players == [] and d.side2_players == []


def test_stats_that_are_missing_leave_the_sides_empty_but_the_rallies_are_kept() -> None:
    raw = _raw(*EXAMPLE)
    raw["stats"] = {"team1_result": 2, "team2_result": 0}
    for game in raw["games"]:
        game["match_set_stats_model"] = None
    d = _parse(raw)
    assert d.side1 is None and d.games[0].side1 is None and len(d.games[0].rallies) == 40
    assert d.tracked and d.checks_ok is True  # the rally sequences and the score still agree


def test_games_are_sorted_by_their_number() -> None:
    raw = _raw(*EXAMPLE)
    raw["games"].reverse()
    assert [g.game_no for g in _parse(raw).games] == [1, 2]


def test_unknown_extra_fields_are_ignored() -> None:
    raw = _raw(*EXAMPLE)
    raw["surprise"] = {"a": 1}
    raw["games"][0]["extra"] = 5
    assert _parse(raw).checks_ok is True


def test_the_parser_does_not_change_its_input() -> None:
    raw = _raw(*EXAMPLE)
    before = copy.deepcopy(raw)
    _parse(raw)
    assert raw == before


def test_a_game_that_is_mostly_tracked_and_partly_not() -> None:
    def change(raw: dict[str, Any]) -> None:
        second = raw["games"][1]
        second["match_set_details_model"] = []
        for key in second["match_set_stats_model"]:
            if key.startswith("team"):
                second["match_set_stats_model"][key] = 0 if "smash" not in key else None

    d = _mutated(change)
    assert d.games[0].tracked and not d.games[1].tracked and d.tracked
    assert d.games[1].side1 is None and d.differences == []  # match-level sums are skipped, not failed


# ---------------------------------------------------------------- the derivations

@pytest.mark.parametrize(
    ("winners", "expected"),
    [([], (0, 0)), ([1], (1, 0)), ([1, 1, 2, 2, 2, 1], (2, 3)), ([2, 2, 2, 2], (0, 4)), ([1, 2, 1, 2], (1, 1)),
     ([1, 1, None, 1], (2, 0)), ([None, None], (0, 0)), ([1, None, 1], (1, 0))],
)
def test_longest_runs(winners: list[int | None], expected: tuple[int, int]) -> None:
    assert longest_runs(winners) == expected


def _rallies(*scores: tuple[int, int]) -> list[Rally]:
    out, previous = [], (0, 0)
    for number, (a, b) in enumerate(scores, start=1):
        out.append(Rally(rally_no=number, side1_points=a, side2_points=b, winner_side=1 if a > previous[0] else 2))
        previous = (a, b)
    return out


def test_game_point_rallies_counts_rallies_played_at_game_point() -> None:
    ladder = [(i, 0) for i in range(1, 22)]  # side 1 wins 21-0: game point at 20-0 only
    assert game_point_rallies(_rallies(*ladder)) == (1, 0)
    assert game_point_rallies([]) == (0, 0)


def test_game_point_rallies_at_deuce_and_at_29_all() -> None:
    """Points alternate to 20-20, then side 1 keeps leading by one until 29-29 and wins 30-29.

    Side 1 is on game point at 20-19, at each lead from 21-20 to 29-28 (9 rallies) and at 29-29;
    side 2 only at 29-29 (either side wins the game with the next point).
    """
    build = [score for k in range(1, 21) for score in ((k, k - 1), (k, k))]  # ... (20, 19), (20, 20)
    extension = [(21, 20), (21, 21), (22, 21), (22, 22), (23, 22), (23, 23), (24, 23), (24, 24), (25, 24), (25, 25),
                 (26, 25), (26, 26), (27, 26), (27, 27), (28, 27), (28, 28), (29, 28), (29, 29), (30, 29)]
    assert game_point_rallies(_rallies(*build, *extension)) == (1 + 9 + 1, 1)


# ---------------------------------------------------------------- the text like the site's tabs

def _row(label: str, one: object, two: object) -> str:
    return f"  {label:<26}{one!s:>8}{two!s:>8}"


def test_the_text_follows_the_sites_tabs() -> None:
    text = format_match_details(_details(*EXAMPLE))
    lines = text.splitlines()
    assert lines[0] == "All England Open Badminton Championships 2026 | MS | R16 | 2026-03-05 19:15 | Utilita Arena Birmingham | 48 min"
    assert lines[1:4] == ["  side 1: LIN Chun-Yi", "  side 2: Jonatan CHRISTIE", "  winner: LIN Chun-Yi"]
    for expected in (
        "MATCH", _row("Final match score", 2, 0), _row("Game 1 score", 21, 19), _row("Game 2 score", 21, 12),
        _row("Game points", 7, 0), _row("Most consecutive points", 7, 5), _row("Total points played", 73, 73),
        _row("Total points won", 42, 31), "GAME 1", _row("Score", 21, 19), _row("Most consecutive points", 7, 5),
        _row("Game points", 6, 0), _row("Total points played", 40, 40), _row("Total points won", 21, 19), "GAME 2",
        _row("Score", 21, 12), _row("Game points", 1, 0), _row("Total points won", 21, 12),
        "  score after each rally: " + GAME_1_SEQUENCE,
    ):
        assert expected in lines, expected
    assert lines[-1] == "Checks: the rallies, statistics and scores agree."


def test_the_text_can_leave_out_the_rallies() -> None:
    assert "score after each rally" not in format_match_details(_details(*EXAMPLE), rallies=False)


def test_the_text_of_an_untracked_match() -> None:
    text = format_match_details(_details(5306, 276))
    assert _row("Game 1 score", 21, 19) in text and _row("Game 2 score", 23, 21) in text
    assert "Game points" not in text and "score after each rally" not in text
    assert "note: The site gives only the game scores" in text and "Checks:" not in text


def test_the_text_lists_failed_checks() -> None:
    text = format_match_details(_mutated(lambda r: r["stats"].update(team1_result=1)))
    assert "Checks failed:" in text and "  - the final result 1-0 does not match the games won (2-0)" in text


def test_the_text_of_a_bye() -> None:
    text = format_match_details(_details(5378, 535))
    assert "side 1: Side 1" in text and "Dejan FERDINANSYAH / Bernadine Anindya WARDANA" in text and "winner: Dejan" in text
    assert _row("Final match score", "-", "-") in text


# ---------------------------------------------------------------- models

def test_rally_and_player_models() -> None:
    with pytest.raises(ValueError):
        Rally(rally_no=0, side1_points=0, side2_points=1)
    assert DetailPlayer(name="A").player_id is None
