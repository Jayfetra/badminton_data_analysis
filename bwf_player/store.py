"""SQLite storage and CSV export for a player's tournament history (R7).

Tables (everything is keyed by the site's own ids, so saving the same data again replaces it
instead of duplicating it):

* ``players``: the subject, partners and opponents (``name`` and ``country`` are filled in as they
  become known and never blanked by a later save that lacks them).
* ``tournaments``: one row per tournament (``category`` is kept if a later save has none).
* ``results``: the subject's result per event (``event_id`` 0 means the site lists no event).
* ``matches``: one row per match. ``winner_side`` is 1 or 2, NULL for a bye or an unknown winner.
  ``seq`` is the match's position among its event's matches, in playing order.
* ``match_players``: who was on which side (1 or 2). Partners and opponents are both here, so
  "played with" and "played against" are the same side / other side question.
* ``games``: the points of each game as ``side1_points`` / ``side2_points``, the site's own
  orientation, so a match stored from either player's point of view is identical.

``player_match_view`` turns that back into one row per (subject, match): partner, opponents, the
games as text ("21-17, 21-19") and whether the subject won. A subject is a player with a result in
that tournament. The CSV files are exports of the tables and this view.
"""

from __future__ import annotations

import csv
import logging
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from bwf_player.exceptions import BwfClientError, InvalidInputError
from bwf_player.models import EventMatches, MatchPlayer, PlayerMatch, TournamentHistory

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    player_id INTEGER PRIMARY KEY,
    name TEXT,
    country TEXT
);
CREATE TABLE IF NOT EXISTS tournaments (
    tournament_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    location TEXT,
    country TEXT,
    type_id INTEGER,
    url TEXT
);
CREATE TABLE IF NOT EXISTS results (
    player_id INTEGER NOT NULL REFERENCES players(player_id),
    tournament_id INTEGER NOT NULL REFERENCES tournaments(tournament_id),
    event_id INTEGER NOT NULL,
    event_code TEXT,
    position TEXT,
    matches_won INTEGER,
    matches_lost INTEGER,
    games_won INTEGER,
    games_lost INTEGER,
    points_for INTEGER,
    points_against INTEGER,
    PRIMARY KEY (player_id, tournament_id, event_id)
);
CREATE TABLE IF NOT EXISTS matches (
    match_id INTEGER PRIMARY KEY,
    tournament_id INTEGER NOT NULL REFERENCES tournaments(tournament_id),
    event_id INTEGER,
    event_code TEXT,
    seq INTEGER NOT NULL,
    draw_id INTEGER,
    draw_name TEXT,
    round TEXT,
    match_date TEXT,
    duration_min INTEGER,
    status TEXT NOT NULL,
    winner_side INTEGER CHECK (winner_side IN (1, 2))
);
CREATE TABLE IF NOT EXISTS match_players (
    match_id INTEGER NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    player_id INTEGER NOT NULL REFERENCES players(player_id),
    side INTEGER NOT NULL CHECK (side IN (1, 2)),
    PRIMARY KEY (match_id, player_id)
);
CREATE TABLE IF NOT EXISTS games (
    match_id INTEGER NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    game_no INTEGER NOT NULL,
    side1_points INTEGER NOT NULL,
    side2_points INTEGER NOT NULL,
    PRIMARY KEY (match_id, game_no)
);
CREATE INDEX IF NOT EXISTS idx_matches_tournament ON matches(tournament_id, event_id, seq);
CREATE INDEX IF NOT EXISTS idx_match_players_player ON match_players(player_id);

DROP VIEW IF EXISTS player_match_view;
CREATE VIEW player_match_view AS
SELECT
    mp.player_id                    AS player_id,
    me.name                         AS player_name,
    m.match_id                      AS match_id,
    m.tournament_id                 AS tournament_id,
    t.name                          AS tournament,
    t.category                      AS category,
    m.event_id                      AS event_id,
    m.event_code                    AS event_code,
    m.seq                           AS seq,
    m.draw_name                     AS draw_name,
    m.round                         AS round,
    m.match_date                    AS match_date,
    m.status                        AS status,
    CASE WHEN m.winner_side IS NULL THEN NULL
         WHEN m.winner_side = mp.side THEN 1 ELSE 0 END AS won,
    (SELECT x.player_id FROM match_players x
       WHERE x.match_id = m.match_id AND x.side = mp.side AND x.player_id <> mp.player_id) AS partner_id,
    (SELECT p.name FROM match_players x JOIN players p ON p.player_id = x.player_id
       WHERE x.match_id = m.match_id AND x.side = mp.side AND x.player_id <> mp.player_id) AS partner,
    (SELECT p.name FROM match_players x JOIN players p ON p.player_id = x.player_id
       WHERE x.match_id = m.match_id AND x.side <> mp.side ORDER BY x.player_id LIMIT 1 OFFSET 0) AS opponent_1,
    (SELECT p.name FROM match_players x JOIN players p ON p.player_id = x.player_id
       WHERE x.match_id = m.match_id AND x.side <> mp.side ORDER BY x.player_id LIMIT 1 OFFSET 1) AS opponent_2,
    (SELECT group_concat(score, ', ') FROM (
        SELECT CASE WHEN mp.side = 1 THEN g.side1_points || '-' || g.side2_points
                    ELSE g.side2_points || '-' || g.side1_points END AS score
        FROM games g WHERE g.match_id = m.match_id ORDER BY g.game_no)) AS games,
    m.duration_min                  AS duration_min
FROM match_players mp
JOIN matches m ON m.match_id = mp.match_id
JOIN tournaments t ON t.tournament_id = m.tournament_id
LEFT JOIN players me ON me.player_id = mp.player_id
WHERE EXISTS (SELECT 1 FROM results r WHERE r.player_id = mp.player_id AND r.tournament_id = m.tournament_id);
"""

_TABLES = ("players", "tournaments", "results", "matches", "match_players", "games")

_EXPORTS: dict[str, tuple[str, Sequence[str]]] = {
    "results.csv": (
        """
        SELECT r.player_id, p.name AS player_name, r.tournament_id, t.name AS tournament, t.category,
               t.start_date, t.end_date, t.location, t.country, r.event_code, NULLIF(r.event_id, 0) AS event_id,
               r.position, r.matches_won, r.matches_lost, r.games_won, r.games_lost,
               r.points_for, r.points_against, t.url
        FROM results r JOIN tournaments t ON t.tournament_id = r.tournament_id
        LEFT JOIN players p ON p.player_id = r.player_id
        ORDER BY r.player_id, t.start_date, r.tournament_id, r.event_code
        """,
        ("player_id", "player_name", "tournament_id", "tournament", "category", "start_date", "end_date",
         "location", "country", "event_code", "event_id", "position", "matches_won", "matches_lost",
         "games_won", "games_lost", "points_for", "points_against", "url"),
    ),
    "matches.csv": (
        """
        SELECT v.player_id, v.player_name, v.tournament_id, v.tournament, v.category, v.event_code, v.draw_name,
               v.round, v.match_date, v.status, v.won, v.partner_id, v.partner, v.opponent_1, v.opponent_2,
               v.games, v.duration_min, v.match_id
        FROM player_match_view v JOIN tournaments t ON t.tournament_id = v.tournament_id
        ORDER BY v.player_id, t.start_date, v.tournament_id, v.event_code, v.seq
        """,
        ("player_id", "player_name", "tournament_id", "tournament", "category", "event_code", "draw_name",
         "round", "match_date", "status", "won", "partner_id", "partner", "opponent_1", "opponent_2",
         "games", "duration_min", "match_id"),
    ),
    "games.csv": (
        """
        SELECT v.player_id, v.player_name, v.tournament_id, v.tournament, v.event_code, v.round, v.match_date,
               v.match_id, g.game_no,
               CASE WHEN mp.side = 1 THEN g.side1_points ELSE g.side2_points END AS player_points,
               CASE WHEN mp.side = 1 THEN g.side2_points ELSE g.side1_points END AS opponent_points
        FROM player_match_view v
        JOIN match_players mp ON mp.match_id = v.match_id AND mp.player_id = v.player_id
        JOIN games g ON g.match_id = v.match_id
        JOIN tournaments t ON t.tournament_id = v.tournament_id
        ORDER BY v.player_id, t.start_date, v.tournament_id, v.event_code, v.seq, g.game_no
        """,
        ("player_id", "player_name", "tournament_id", "tournament", "event_code", "round", "match_date",
         "match_id", "game_no", "player_points", "opponent_points"),
    ),
}


class HistoryStore:
    """A SQLite database of tournament history. Use as a context manager, or call ``close()``."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        try:
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.path)
        except (sqlite3.Error, OSError) as exc:
            raise BwfClientError(f"Cannot open the history database {self.path!r}: {exc}") from exc
        try:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._open_schema()
        except (sqlite3.Error, BwfClientError) as exc:
            self._conn.close()
            if isinstance(exc, BwfClientError):
                raise
            raise BwfClientError(f"Cannot open the history database {self.path!r}: {exc}") from exc

    def __enter__(self) -> HistoryStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    @property
    def connection(self) -> sqlite3.Connection:
        """The open connection, for read queries (tables and ``player_match_view``)."""
        return self._conn

    def counts(self) -> dict[str, int]:
        """Row count per table."""
        return {t: self._conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in _TABLES}

    def save_tournaments(
        self, history: TournamentHistory, *, player_name: str | None = None, player_country: str | None = None
    ) -> int:
        """Save the tournaments and the subject's results; returns the number of results saved.

        Saving again replaces the rows. A tournament category or a player name that the new data
        lacks does not erase the one already stored. One transaction: all or nothing.
        """
        player_id = int(history.player_id)
        with self._conn:
            self._upsert_player(player_id, player_name, player_country)
            for entry in history.entries:
                self._conn.execute(
                    """
                    INSERT INTO tournaments (tournament_id, name, category, start_date, end_date, location, country, type_id, url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(tournament_id) DO UPDATE SET
                        name = excluded.name, category = COALESCE(excluded.category, tournaments.category),
                        start_date = excluded.start_date, end_date = excluded.end_date,
                        location = excluded.location, country = excluded.country,
                        type_id = excluded.type_id, url = excluded.url
                    """,
                    (entry.tournament_id, entry.name, entry.category, entry.start_date.isoformat(),
                     entry.end_date.isoformat(), entry.location, entry.country, entry.type_id, entry.url),
                )
                self._conn.execute(
                    """
                    INSERT INTO results (player_id, tournament_id, event_id, event_code, position, matches_won,
                                         matches_lost, games_won, games_lost, points_for, points_against)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(player_id, tournament_id, event_id) DO UPDATE SET
                        event_code = excluded.event_code, position = excluded.position,
                        matches_won = excluded.matches_won, matches_lost = excluded.matches_lost,
                        games_won = excluded.games_won, games_lost = excluded.games_lost,
                        points_for = excluded.points_for, points_against = excluded.points_against
                    """,
                    (player_id, entry.tournament_id, entry.event_id or 0, entry.event_code, entry.position,
                     entry.matches_won, entry.matches_lost, entry.games_won, entry.games_lost,
                     entry.points_for, entry.points_against),
                )
        return len(history.entries)

    def save_matches(self, event: EventMatches) -> int:
        """Save one event's matches with their players and games; returns the matches saved.

        The tournament must have been saved first (:meth:`save_tournaments`). Saving a match again,
        also from another player's point of view, replaces its players and games, so nothing goes
        stale. A player the site gives no id cannot be stored and is skipped with a warning.
        One transaction: all or nothing.

        Raises:
            InvalidInputError: the tournament is not in the database yet.
        """
        known = self._conn.execute(
            "SELECT 1 FROM tournaments WHERE tournament_id = ?", (event.tournament_id,)
        ).fetchone()
        if known is None:
            raise InvalidInputError(
                f"Tournament {event.tournament_id} is not in the database; save the tournament list first."
            )
        with self._conn:
            for seq, match in enumerate(event.matches, start=1):
                self._save_match(match, event, seq)
        return len(event.matches)

    def export_csv(self, directory: str | Path) -> dict[str, Path]:
        """Write ``results.csv``, ``matches.csv`` and ``games.csv`` into ``directory``.

        Files are UTF-8 with a byte-order mark (so Excel shows accents correctly); empty values
        are blank; existing files are replaced. Returns the path of each file written.
        """
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        written = {}
        for name, (sql, columns) in _EXPORTS.items():
            path = target / name
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(columns)
                writer.writerows(self._conn.execute(sql))
            written[name] = path
        return written

    # ------------------------------------------------------------------ internals

    def _open_schema(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise BwfClientError(
                f"The database has schema version {version}; this package understands up to {SCHEMA_VERSION}."
            )
        self._conn.executescript(_SCHEMA)
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._conn.commit()

    def _upsert_player(self, player_id: int, name: str | None, country: str | None) -> None:
        self._conn.execute(
            """
            INSERT INTO players (player_id, name, country) VALUES (?, ?, ?)
            ON CONFLICT(player_id) DO UPDATE SET
                name = COALESCE(excluded.name, players.name),
                country = COALESCE(excluded.country, players.country)
            """,
            (player_id, name, country),
        )

    def _save_match(self, match: PlayerMatch, event: EventMatches, seq: int) -> None:
        winner_side = None if match.won is None else (match.side if match.won else 3 - match.side)
        self._conn.execute(
            """
            INSERT INTO matches (match_id, tournament_id, event_id, event_code, seq, draw_id, draw_name, round,
                                 match_date, duration_min, status, winner_side)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_id) DO UPDATE SET
                tournament_id = excluded.tournament_id, event_id = excluded.event_id,
                event_code = excluded.event_code, seq = excluded.seq, draw_id = excluded.draw_id,
                draw_name = excluded.draw_name, round = excluded.round, match_date = excluded.match_date,
                duration_min = excluded.duration_min, status = excluded.status,
                winner_side = excluded.winner_side
            """,
            (match.match_id, match.tournament_id, event.event_id, event.event_code, seq, match.draw_id,
             match.draw_name, match.round, match.match_date.isoformat() if match.match_date else None,
             match.duration_min, match.status, winner_side),
        )
        self._conn.execute("DELETE FROM match_players WHERE match_id = ?", (match.match_id,))
        self._conn.execute("DELETE FROM games WHERE match_id = ?", (match.match_id,))

        own = [match.player] + ([match.partner] if match.partner else [])
        for players, side in ((own, match.side), (match.opponents, 3 - match.side)):
            for player in players:
                self._save_participant(match.match_id, player, side)
        for game in match.games:
            mine, theirs = game.player_points, game.opponent_points
            side1, side2 = (mine, theirs) if match.side == 1 else (theirs, mine)
            self._conn.execute(
                "INSERT INTO games (match_id, game_no, side1_points, side2_points) VALUES (?, ?, ?, ?)",
                (match.match_id, game.game_no, side1, side2),
            )

    def _save_participant(self, match_id: int, player: MatchPlayer, side: int) -> None:
        if player.player_id is None:
            logger.warning("match %s: %r has no player id and was not stored", match_id, player.name)
            return
        self._upsert_player(player.player_id, player.name, player.country)
        self._conn.execute(
            "INSERT OR REPLACE INTO match_players (match_id, player_id, side) VALUES (?, ?, ?)",
            (match_id, player.player_id, side),
        )
