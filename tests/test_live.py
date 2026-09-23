"""Live smoke tests against bwfbadminton.com. Excluded by default: run with `pytest -m live`.

These make a handful of real requests (cached in a temp dir). If Cloudflare blocks you, the
tests fail with BlockedByCloudflareError; wait before retrying.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bwf_player.config import BwfConfig
from bwf_player.http_client import BwfHttpClient
from bwf_player.search import search_player

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> BwfHttpClient:
    cache: Path = tmp_path_factory.mktemp("bwf_cache")
    return BwfHttpClient(BwfConfig(cache_dir=cache))


def test_live_exact_name(client: BwfHttpClient) -> None:
    result = search_player("Jonatan Christie", client)
    assert result.status == "found"
    assert result.best_match.profile_url == "https://bwfbadminton.com/player/73442/jonatan-christie"


def test_live_typo_and_reversed_order(client: BwfHttpClient) -> None:
    assert search_player("jonathan cristie", client).best_match.player_id == "73442"
    assert search_player("Christie Jonatan", client).best_match.player_id == "73442"


def test_live_player_missing_from_index(client: BwfHttpClient) -> None:
    result = search_player("Kento Momota", client)
    assert result.status == "found"
    assert result.best_match.player_id == "89785"


def test_live_reversed_name_and_common_word(client: BwfHttpClient) -> None:
    """'ying' alone returns too many players to page through; phrases must be used."""
    result = search_player("Tai Tzu Ying", client)
    assert result.status == "found"
    assert result.best_match.player_id == "61427"


def test_live_profile_right_and_left_handed(client: BwfHttpClient) -> None:
    from bwf_player.profile import get_profile

    christie = get_profile("73442", client)
    assert (christie.nationality, christie.height_cm, christie.playing_hand) == ("Indonesia", 179.0, "Right")
    marin = get_profile("18228", client)
    assert (marin.nationality, marin.height_cm, marin.playing_hand) == ("Spain", 172.0, "Left")


def test_live_profile_with_unlisted_details_and_unknown_id(client: BwfHttpClient) -> None:
    from bwf_player.profile import get_profile

    sparse = get_profile("89438", client)
    assert sparse.player_found and sparse.missing_fields == ["nationality", "height", "playing_hand"]
    assert get_profile("999999999", client).player_found is False


def test_live_ranking_of_an_active_player(client: BwfHttpClient) -> None:
    from datetime import date, timedelta

    from bwf_player.ranking import get_ranking

    ranking = get_ranking("73442", client)
    assert ranking.is_ranked and ranking.event.name == "MEN'S SINGLES"
    assert isinstance(ranking.current_rank, int) and ranking.current_rank >= 1
    assert ranking.weeks_at_current_rank >= 1 and ranking.weeks_source == "derived_from_history"
    assert ranking.at_rank_since <= ranking.as_of
    assert (ranking.as_of - ranking.at_rank_since).days >= 6 * (ranking.weeks_at_current_rank - 1)
    assert date.today() - ranking.as_of < timedelta(days=45), "ranking history looks stale"


def test_live_ranking_of_a_retired_and_an_unknown_player(client: BwfHttpClient) -> None:
    from bwf_player.ranking import get_ranking

    retired = get_ranking("50152", client)  # Lee Chong Wei
    assert retired.is_ranked is False and retired.current_rank is None
    assert retired.notes and retired.event is not None
    unknown = get_ranking("999999999", client)
    assert unknown.is_ranked is False and unknown.event is None and unknown.notes


def test_live_end_to_end_lookup_and_report(client: BwfHttpClient) -> None:
    from bwf_player import format_result, lookup_player

    result = lookup_player("jonathan cristie", client)
    assert result.search.status == "found" and result.profile.nationality == "Indonesia"
    assert result.ranking.is_ranked and result.ranking.weeks_at_current_rank >= 1
    text = format_result(result)
    assert "Personal details" in text and "Ranking (MEN'S SINGLES)" in text

    assert lookup_player("christie", client).profile is None  # ambiguous: nothing further fetched


def test_live_tournaments_in_the_last_year(client: BwfHttpClient) -> None:
    from bwf_player import get_tournaments, history_window
    from bwf_player.tournaments import overlaps

    since, until = history_window()
    history = get_tournaments("73442", client)  # Jonatan Christie
    assert (history.since, history.until) == (since, until)
    assert len(history.entries) >= 5, "an active top player enters many tournaments in a year"
    starts = [e.start_date for e in history.entries]
    assert starts == sorted(starts)
    for entry in history.entries:
        assert overlaps(entry, since, until)
        assert entry.name and entry.event_code and isinstance(entry.event_id, int)
        assert entry.matches_won is not None and entry.matches_lost is not None
        assert entry.games_won is not None and entry.games_lost is not None
    assert any(e.category for e in history.entries), "the calendar should give at least one category"
    assert any(e.position for e in history.entries)


def test_live_tournaments_of_an_unknown_player(client: BwfHttpClient) -> None:
    from bwf_player import get_tournaments

    history = get_tournaments("999999999", client)
    assert history.entries == [] and history.notes


def test_live_matches_of_a_singles_player_reproduce_the_sites_totals(client: BwfHttpClient) -> None:
    from bwf_player import get_matches, get_tournaments

    history = get_tournaments("73442", client, with_categories=False)
    for entry in history.entries[-3:]:  # the three most recent events
        result = get_matches("73442", entry, client)
        assert result.totals_agree is True, (entry.name, result.notes)
        assert result.matches and result.notes == []
        for match in result.matches:
            assert match.player.player_id == 73442 and match.partner is None
            if match.status == "played":
                assert len(match.opponents) == 1 and match.won is not None and match.games
                for game in match.games:  # a game goes to 21 (cap 30), won by 2 unless capped
                    top, low = max(game.player_points, game.opponent_points), min(game.player_points, game.opponent_points)
                    assert top >= 21 and (top - low >= 2 or top == 30)


def test_live_matches_of_a_doubles_player_have_partners(client: BwfHttpClient) -> None:
    from bwf_player import get_matches, get_tournaments

    history = get_tournaments("88876", client, with_categories=False)  # Fajar ALFIAN, men's doubles
    for entry in history.entries[-2:]:
        result = get_matches("88876", entry, client)
        assert result.totals_agree is True, (entry.name, result.notes)
        for match in result.matches:
            assert match.partner is not None and match.partner.player_id != 88876
            if match.status == "played":
                assert len(match.opponents) == 2 and match.games


def test_live_store_and_export_reproduce_the_sites_totals(client: BwfHttpClient, tmp_path: Path) -> None:
    import csv

    from bwf_player import get_matches, get_tournaments
    from bwf_player.store import HistoryStore

    history = get_tournaments("73442", client, with_categories=False)
    history.entries = history.entries[-3:]  # the same three events the other live tests already fetched
    with HistoryStore(tmp_path / "live.sqlite") as store:
        store.save_tournaments(history, player_name="Jonatan CHRISTIE")
        for entry in history.entries:
            store.save_matches(get_matches("73442", entry, client))
        counts = store.counts()
        expected = sum(e.matches_won + e.matches_lost for e in history.entries)
        assert counts["results"] == 3 and counts["matches"] == expected
        assert len(store.connection.execute("SELECT 1 FROM player_match_view").fetchall()) == expected
        wins = store.connection.execute("SELECT COUNT(*) FROM player_match_view WHERE won = 1").fetchone()[0]
        assert wins + store.connection.execute("SELECT COUNT(*) FROM player_match_view WHERE won = 0").fetchone()[0] == expected
        files = store.export_csv(tmp_path / "csv")
    with files["matches.csv"].open(encoding="utf-8-sig", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == expected


def test_live_end_to_end_history_download_and_a_free_second_run(client: BwfHttpClient, tmp_path: Path) -> None:
    import sqlite3

    from bwf_player import download_player_history, format_history

    db = tmp_path / "e2e.sqlite"
    summary = download_player_history("jonathan cristie", client, db_path=db, export_dir=tmp_path / "csv")
    assert summary.search.status == "found" and summary.player_id == "73442"
    assert summary.tournaments >= 10 and summary.matches >= 30 and summary.games >= 60
    assert summary.all_totals_agree is True, summary.events_disagreeing  # matches reproduce the site's totals
    assert summary.matches_by_status.get("played", 0) >= 30
    assert "Jonatan CHRISTIE" in format_history(summary)

    def dump() -> list[tuple]:
        with sqlite3.connect(db) as connection:
            return [row for table in ("tournaments", "results", "matches", "match_players", "games")
                    for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3")]

    before = dump()
    real_get, made = client._session.get, []
    client._session.get = lambda url, *a, **k: (made.append(url), real_get(url, *a, **k))[1]
    try:
        again = download_player_history(73442, client, db_path=db, export_dir=tmp_path / "csv")
    finally:
        client._session.get = real_get
    assert made == [], "the second run should be answered entirely from the cache"
    assert again.matches == summary.matches and dump() == before


def test_live_the_example_match_page(client: BwfHttpClient) -> None:
    """https://bwfworldtour.bwfbadminton.com/tournament/5515/.../match/13 (All England 2026, R16)."""
    from bwf_player import get_match_details

    d = get_match_details(5515, 13, client)
    assert d.match_id == 1505450 and d.round == "R16" and d.venue == "Utilita Arena Birmingham" and d.duration_min == 48
    assert [p.name for p in d.side1_players] == ["LIN Chun-Yi"] and [p.name for p in d.side2_players] == ["Jonatan CHRISTIE"]
    assert (d.side1_result, d.side2_result) == (2, 0) and [(g.side1_points, g.side2_points) for g in d.games] == [(21, 19), (21, 12)]
    assert (d.side1.rallies_played, d.side1.rallies_won, d.side2.rallies_won) == (73, 42, 31)
    assert (d.side1.consecutive_points, d.side2.consecutive_points, d.side1.game_points, d.side2.game_points) == (7, 5, 7, 0)
    assert [len(g.rallies) for g in d.games] == [40, 33] and d.tracked and d.checks_ok is True, d.differences


def test_live_details_of_recent_matches_agree_with_the_players_page(client: BwfHttpClient) -> None:
    from bwf_player import details_targets, get_match_details, get_matches, get_tournaments

    entry = get_tournaments("73442", client, with_categories=False).entries[-1]
    matches = details_targets(get_matches("73442", entry, client).matches)
    assert matches, "the latest tournament has played matches"
    for match in matches:
        details = get_match_details(match.tournament_id, match.match_code, client, match=match)
        assert details.differences == [] and details.checks_ok is True, (match.round, details.differences)
        assert details.match_id == match.match_id and len(details.games) == len(match.games)


def test_live_a_match_that_does_not_exist_is_not_found(client: BwfHttpClient) -> None:
    import pytest

    from bwf_player import BwfNotFoundError, get_match_details

    with pytest.raises(BwfNotFoundError):
        get_match_details(5515, 99999, client)


def _store_details_of(client: BwfHttpClient, player: str, tmp_path: Path, **window: object) -> tuple[object, list, Path]:
    """Save one tournament's matches and their details from the real site; returns (store counts, targets, csv dir)."""
    from bwf_player import details_targets, get_match_details, get_matches, get_tournaments
    from bwf_player.store import HistoryStore

    history = get_tournaments(player, client, with_categories=False, **window)
    assert len({e.tournament_id for e in history.entries}) == 1, [e.name for e in history.entries]
    targets = []
    with HistoryStore(tmp_path / "details.sqlite") as store:
        store.save_tournaments(history, player_name="x")
        for entry in history.entries:  # one entry per event entered
            event = get_matches(player, entry, client)
            store.save_matches(event)
            for match in details_targets(event.matches):
                targets.append(match)
                store.save_match_details(get_match_details(match.tournament_id, match.match_code, client, match=match))
        rows = {
            "counts": store.counts(),
            "checks": store.connection.execute("SELECT DISTINCT checks_ok FROM match_stats").fetchall(),
            "points": store.connection.execute("SELECT SUM(total_points_played) FROM game_stats").fetchone()[0],
            "tracked": store.connection.execute("SELECT DISTINCT tracked FROM match_stats").fetchall(),
            "null_stats": store.connection.execute(
                "SELECT COUNT(*) FROM match_stats WHERE side1_rallies_won IS NOT NULL OR side1_consecutive_points IS NOT NULL"
            ).fetchone()[0],
        }
        files = store.export_csv(tmp_path / "csv")
    return rows, targets, files["rallies.csv"].parent


def test_live_game_details_are_stored_and_exported(client: BwfHttpClient, tmp_path: Path) -> None:
    """LI-NING China Masters 2026 (5-day World Tour event): rally data and statistics are there."""
    import csv
    from datetime import date

    rows, targets, folder = _store_details_of(client, "73442", tmp_path, since=date(2026, 9, 1), until=date(2026, 9, 6))
    counts = rows["counts"]
    assert counts["match_stats"] == len(targets) == 2 and counts["game_stats"] == sum(len(m.games) for m in targets)
    assert rows["checks"] == [(1,)] and rows["tracked"] == [(1,)]
    assert counts["rallies"] == rows["points"] > 0
    with (folder / "rallies.csv").open(encoding="utf-8-sig", newline="") as handle:
        assert len(list(csv.DictReader(handle))) == counts["rallies"]


def test_live_untracked_details_are_stored_as_null(client: BwfHttpClient, tmp_path: Path) -> None:
    """Telangana India International Challenge 2025 (Aadhya SHINE): the site gives only the game scores."""
    from datetime import date

    rows, targets, _ = _store_details_of(client, "89438", tmp_path, since=date(2025, 11, 4), until=date(2025, 11, 9))
    counts = rows["counts"]
    assert counts["match_stats"] == len(targets) == 2 and counts["rallies"] == 0
    assert rows["tracked"] == [(0,)] and rows["null_stats"] == 0  # NULL, not zeros
    assert rows["checks"] == [(1,)]  # the games still agree with the player's page
