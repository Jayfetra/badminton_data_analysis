"""End-to-end history download: player -> tournaments -> matches -> game details -> SQLite/CSV (R4-R8)."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable
from datetime import date
from pathlib import Path

from bwf_player.exceptions import BwfNotFoundError
from bwf_player.game_details import details_targets, get_match_details
from bwf_player.http_client import BwfHttpClient
from bwf_player.matches import get_matches
from bwf_player.models import HistorySummary, MatchDetails, PlayerMatch
from bwf_player.names import validate_player_id
from bwf_player.search import search_player
from bwf_player.store import HistoryStore
from bwf_player.tournaments import get_tournaments

logger = logging.getLogger(__name__)


def download_player_history(
    player: str | int,
    client: BwfHttpClient | None = None,
    *,
    since: date | None = None,
    until: date | None = None,
    today: date | None = None,
    db_path: str | Path | None = None,
    export_dir: str | Path | None = None,
    export: bool = True,
    game_details: bool = True,
    progress: Callable[[str], None] | None = None,
) -> HistorySummary:
    """Download a player's tournaments for the window and save results, partners, opponents and scores.

    Args:
        player: a name (any reasonable spelling, see ``search_player``), or the site's player id
            as an ``int`` or a string of digits.
        client: HTTP client to reuse (defaults to a new polite client).
        since, until: window, inclusive; default one year back from ``today`` to ``today``.
        today: only used to derive the default window.
        db_path: SQLite file; default ``client.config.history_db_path``.
        export_dir: CSV folder; default ``client.config.history_export_dir``.
        export: write the CSV files after saving.
        game_details: also download, for every played match, what the site's match page shows (the
            Match tab, the Game tabs and the score after every rally). One more request per match;
            ``False`` skips it and gives the shorter, older download.
        progress: called with a short message per tournament event and per match (default: logged at INFO).

    A name that matches no single player, or a player with no tournament in the window, downloads
    nothing and creates no database; ``notes`` says why. Requests are made one after another at the
    client's polite pace (about 25-40 for a busy player, and one more per played match with game
    details: about 85 for a singles player with 58 matches). If one fails (for example a Cloudflare
    block) the exception propagates, and everything saved so far stays in the database; running
    the same call again picks up from the cache and the upserts without duplicating anything. The
    exception is a match the site has no details page for (HTTP 404): that is noted and skipped.

    Raises:
        InvalidInputError: an id or a window that is malformed.
        BlockedByCloudflareError, BwfClientError: a request failed or a response was malformed.
    """
    client = client or BwfHttpClient()
    say = progress or (lambda message: logger.info(message))
    summary = HistorySummary()

    if isinstance(player, str) and not _is_digits(player):
        search = search_player(player, client)
        summary.search = search
        if search.best_match is None:
            summary.notes.append(f"Nothing was downloaded. {search.message or 'No single player was found.'}")
            return summary
        player_id, name = search.best_match.player_id, search.best_match.name
    else:
        player_id, name = validate_player_id(player.strip() if isinstance(player, str) else player), None
    summary.player_id = player_id

    say(f"Looking up the tournaments of player {player_id}")
    history = get_tournaments(player_id, client, since=since, until=until, today=today)
    summary.since, summary.until, summary.history = history.since, history.until, history
    summary.notes.extend(history.notes)
    summary.events = len(history.entries)
    summary.tournaments = len({e.tournament_id for e in history.entries})
    if not history.entries:
        summary.player_name = name
        summary.notes.append("Nothing was saved: no tournaments in the window.")
        return summary

    config = client.config
    database = Path(db_path) if db_path is not None else config.history_db_path
    with HistoryStore(database) as store:
        store.save_tournaments(history, player_name=name)
        for number, entry in enumerate(history.entries, start=1):
            say(f"[{number}/{summary.events}] {entry.start_date} {entry.name} ({entry.event_code or 'no event'})")
            event = get_matches(player_id, entry, client)
            store.save_matches(event)
            summary.event_matches.append(event)
            label = f"{entry.name} ({entry.event_code or 'no event'})"
            summary.notes.extend(f"{label}: {note}" for note in event.notes)
            summary.notes.extend(f"{label}, {m.round or 'match'}: {n}" for m in event.matches for n in m.notes)
            if event.totals_agree is not None:
                summary.events_checked += 1
            if event.totals_agree is False:
                summary.events_disagreeing.append(label)
            if game_details:
                _download_details(player_id, event.matches, label, client, store, summary, say)
        if export:
            files = store.export_csv(export_dir if export_dir is not None else config.history_export_dir)
            summary.csv_files = {file: str(path) for file, path in files.items()}
    summary.database = str(database)

    matches = [m for event in summary.event_matches for m in event.matches]
    summary.matches = len(matches)
    summary.matches_by_status = dict(Counter(m.status for m in matches))
    summary.games = sum(len(m.games) for m in matches)
    if summary.events_checked:
        summary.all_totals_agree = not summary.events_disagreeing
    if summary.details:
        summary.game_details = len(summary.details)
        summary.game_details_tracked = sum(d.tracked for d in summary.details)
        summary.game_details_untracked = summary.game_details - summary.game_details_tracked
        summary.rallies = sum(len(g.rallies) for d in summary.details for g in d.games)
        summary.all_details_agree = not summary.game_details_disagreeing
        if summary.game_details_untracked:
            summary.notes.append(
                f"{summary.game_details_untracked} match(es) have only game scores on the site (no rally-by-rally data or "
                "statistics); their statistics are stored as NULL, not 0."
            )
    summary.player_name = name or next((m.player.name for m in matches), None)
    return summary


def _download_details(
    player_id: str,
    matches: list[PlayerMatch],
    label: str,
    client: BwfHttpClient,
    store: HistoryStore,
    summary: HistorySummary,
    say: Callable[[str], None],
) -> None:
    """Fetch, check and store the game details of the matches of one event that have them."""
    targets = details_targets(matches)
    summary.game_details_skipped += len(matches) - len(targets)
    for position, match in enumerate(targets, start=1):
        say(f"    match {position}/{len(targets)}: {match.round or '?'} (code {match.match_code}), game details")
        where = f"{label}, {match.round or 'match'}"
        try:
            details = get_match_details(match.tournament_id, match.match_code, client, match=match)
        except BwfNotFoundError:
            summary.game_details_not_found += 1
            summary.notes.append(f"{where}: the site has no details page for this match (HTTP 404); nothing was stored for it.")
            continue
        if details.match_id is None:
            summary.game_details_not_found += 1
            summary.notes.append(f"{where}: the site's details do not name a match id; nothing was stored for it.")
            continue
        store.save_match_details(details)
        summary.details.append(details)
        summary.notes.extend(f"{where}: {difference}" for difference in details.differences)
        if details.checks_ok is False:
            summary.game_details_disagreeing.append(where)


def format_history(summary: HistorySummary, *, matches: bool = True, games: bool = False) -> str:
    """Render a ``HistorySummary`` as readable text: a header, one line per event, then its matches.

    With ``games=True`` each match with downloaded details also gets one line per game (score,
    rallies, longest run of points and game points, the player's figures first).
    """
    lines: list[str] = []
    if summary.search is not None:
        lines.append(f"Search:       {summary.search.status.upper()} - {summary.search.message}")
        if summary.search.best_match is None:
            lines += [
                f"  {c.score:5.1f}  {c.name} ({c.country or 'country unknown'})  {c.profile_url}"
                for c in summary.search.candidates
            ]
    if summary.player_id is None:
        lines += [f"  - {note}" for note in summary.notes]
        return "\n".join(lines)

    lines.append(f"Player:       {summary.player_name or 'name unknown'} (id {summary.player_id})")
    if summary.since and summary.until:
        lines.append(f"Window:       {summary.since} to {summary.until}")
    by_status = ", ".join(f"{n} {status}" for status, n in sorted(summary.matches_by_status.items()))
    lines.append(
        f"Downloaded:   {summary.tournaments} tournament(s), {summary.events} event(s), "
        f"{summary.matches} match(es)" + (f" ({by_status})" if by_status else "") + f", {summary.games} game(s)"
    )
    if summary.all_totals_agree is not None:
        verdict = "yes" if summary.all_totals_agree else "NO - see notes"
        lines.append(f"Checked:      the matches reproduce the site's own totals: {verdict} ({summary.events_checked} event(s))")
    if summary.game_details or summary.game_details_skipped or summary.game_details_not_found:
        parts = [f"{summary.game_details} match(es)"]
        if summary.game_details:
            parts.append(f"{summary.game_details_tracked} with rally data, {summary.game_details_untracked} with game scores only")
        if summary.rallies:
            parts.append(f"{summary.rallies} rallies")
        if summary.game_details_skipped:
            parts.append(f"{summary.game_details_skipped} not requested (byes, walkovers, matches not played yet)")
        if summary.game_details_not_found:
            parts.append(f"{summary.game_details_not_found} without a details page")
        lines.append("Game details: " + ", ".join(parts))
        if summary.all_details_agree is not None:
            verdict = "yes" if summary.all_details_agree else "NO - see notes"
            lines.append(f"Checked:      rallies, statistics and scores agree with each other and with the player's page: {verdict}")
    if summary.database:
        lines.append(f"Database:     {summary.database}")
    lines += [f"CSV:          {path}" for path in summary.csv_files.values()]

    events = {(e.tournament_id, e.event_id): e for e in summary.event_matches}
    details = {d.match_id: d for d in summary.details}
    for entry in summary.history.entries if summary.history else []:
        record = "" if entry.matches_won is None else f"  {entry.matches_won}-{entry.matches_lost} in matches"
        lines += [
            "",
            f"{entry.start_date}  {entry.name}  [{entry.event_code or 'no event'}]  "
            f"result: {entry.position or 'null'}{record}"
            + (f"  ({entry.category})" if entry.category else ""),
        ]
        if matches and (event := events.get((entry.tournament_id, entry.event_id))):
            for match in event.matches:
                lines.append(_match_line(match))
                if games and match.match_id in details:
                    lines += _game_lines(match, details[match.match_id])

    if summary.notes:
        lines += ["", "Notes"] + [f"  - {note}" for note in summary.notes]
    return "\n".join(lines)


def _match_line(match: PlayerMatch) -> str:
    if match.status == "bye":
        outcome = "bye"
    elif match.status in ("scheduled", "in_progress"):
        outcome = "not played yet" if match.status == "scheduled" else "in progress"
        if match.match_date:
            outcome += f" ({match.match_date})"
    else:
        outcome = {True: "won", False: "lost", None: "?"}[match.won]
        if match.status != "played":
            outcome += f" ({match.status})"
    versus = " / ".join(o.name for o in match.opponents) or "-"
    partner = f" with {match.partner.name}" if match.partner else ""
    scores = ", ".join(f"{g.player_points}-{g.opponent_points}" for g in match.games)
    return f"    {match.round or '?':<9} {outcome:<16}{partner} vs {versus}  {scores}".rstrip()


def _game_lines(match: PlayerMatch, details: MatchDetails) -> list[str]:
    """One line per game from the player's side, from the match details."""
    out = []
    for game in details.games:
        mine, theirs = (game.side1_points, game.side2_points) if match.side == 1 else (game.side2_points, game.side1_points)
        if not game.tracked or game.side1 is None or game.side2 is None:
            out.append(f"        game {game.game_no}  {mine}-{theirs}  (game score only)")
            continue
        own, other = (game.side1, game.side2) if match.side == 1 else (game.side2, game.side1)
        out.append(
            f"        game {game.game_no}  {mine}-{theirs}  {len(game.rallies)} rallies  "
            f"longest run {own.consecutive_points}-{other.consecutive_points}  "
            f"game points {own.game_points}-{other.game_points}"
        )
    return out


def _is_digits(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and stripped.isascii() and stripped.isdigit()
