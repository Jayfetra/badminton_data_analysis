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
that tournament. The CSV files are exports of the tables and the views.

Game details (schema version 2, the site's match page): ``match_stats`` (the Match tab: one row per
match), ``game_stats`` (the Game tabs: one row per game) and ``rallies`` (the score after every
rally). Statistics are stored per side (``side1_``/``side2_``, the site's orientation) and are NULL,
never 0, where the site does not track them. ``player_match_stats_view``, ``player_game_view`` and
``player_rally_view`` give the subject's point of view (``player_`` and ``opponent_`` columns).
"""

from __future__ import annotations

import csv
import logging
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from bwf_player.exceptions import BwfClientError, InvalidInputError
from bwf_player.models import (
    EventMatches,
    MatchDetails,
    MatchPlayer,
    PlayerMatch,
    SideStats,
    TournamentHistory,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 2

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
    match_code TEXT,
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
    m.duration_min                  AS duration_min,
    m.match_code                    AS match_code
FROM match_players mp
JOIN matches m ON m.match_id = mp.match_id
JOIN tournaments t ON t.tournament_id = m.tournament_id
LEFT JOIN players me ON me.player_id = mp.player_id
WHERE EXISTS (SELECT 1 FROM results r WHERE r.player_id = mp.player_id AND r.tournament_id = m.tournament_id);
"""

_TABLES = (
    "players", "tournaments", "results", "matches", "match_players", "games", "match_stats", "game_stats", "rallies",
)

_STAT_FIELDS = tuple(SideStats.model_fields)  # consecutive_points, game_points, rallies_played, ...
_STAT_COLUMNS = [f"side{side}_{field}" for field in _STAT_FIELDS for side in (1, 2)]
_STAT_DDL = ",\n    ".join(f"{column} INTEGER" for column in _STAT_COLUMNS)
_PERSPECTIVE_COLUMNS = [f"{who}_{field}" for field in _STAT_FIELDS for who in ("player", "opponent")]


def _flip(table: str, source: str, alias: str) -> str:
    """Two SELECT expressions: the subject's and the opponent's value of ``side1_/side2_<source>``."""
    return (
        f"CASE WHEN mp.side = 1 THEN {table}.side1_{source} ELSE {table}.side2_{source} END AS player_{alias}, "
        f"CASE WHEN mp.side = 1 THEN {table}.side2_{source} ELSE {table}.side1_{source} END AS opponent_{alias}"
    )


def _flips(table: str) -> str:
    return ",\n    ".join(_flip(table, field, field) for field in _STAT_FIELDS)


_DETAIL_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS match_stats (
    match_id INTEGER PRIMARY KEY REFERENCES matches(match_id) ON DELETE CASCADE,
    start_local TEXT,
    venue TEXT,
    score_status INTEGER,
    tracked INTEGER NOT NULL,
    checks_ok INTEGER,
    differences TEXT,
    side1_result INTEGER,
    side2_result INTEGER,
    {_STAT_DDL}
);
CREATE TABLE IF NOT EXISTS game_stats (
    match_id INTEGER NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    game_no INTEGER NOT NULL,
    total_points_played INTEGER,
    tracked INTEGER NOT NULL,
    {_STAT_DDL},
    PRIMARY KEY (match_id, game_no)
);
CREATE TABLE IF NOT EXISTS rallies (
    match_id INTEGER NOT NULL REFERENCES matches(match_id) ON DELETE CASCADE,
    game_no INTEGER NOT NULL,
    rally_no INTEGER NOT NULL,
    side1_points INTEGER NOT NULL,
    side2_points INTEGER NOT NULL,
    winner_side INTEGER CHECK (winner_side IN (1, 2)),
    PRIMARY KEY (match_id, game_no, rally_no)
);

DROP VIEW IF EXISTS player_match_stats_view;
CREATE VIEW player_match_stats_view AS
SELECT
    v.player_id AS player_id, v.player_name AS player_name, v.match_id AS match_id, m.match_code AS match_code,
    v.tournament_id AS tournament_id, v.tournament AS tournament, v.category AS category,
    t.start_date AS tournament_start, v.event_code AS event_code, v.round AS round, v.match_date AS match_date,
    v.seq AS seq, s.start_local AS start_local, s.venue AS venue, v.duration_min AS duration_min,
    s.score_status AS score_status, s.tracked AS tracked, s.checks_ok AS checks_ok,
    {_flip("s", "result", "games_won")},
    {_flips("s")}
FROM player_match_view v
JOIN matches m ON m.match_id = v.match_id
JOIN tournaments t ON t.tournament_id = v.tournament_id
JOIN match_players mp ON mp.match_id = v.match_id AND mp.player_id = v.player_id
JOIN match_stats s ON s.match_id = v.match_id;

DROP VIEW IF EXISTS player_game_view;
CREATE VIEW player_game_view AS
SELECT
    v.player_id AS player_id, v.player_name AS player_name, v.match_id AS match_id, m.match_code AS match_code,
    v.tournament_id AS tournament_id, v.tournament AS tournament, t.start_date AS tournament_start,
    v.event_code AS event_code, v.round AS round, v.match_date AS match_date, v.seq AS seq, g.game_no AS game_no,
    {_flip("g", "points", "points")},
    gs.total_points_played AS total_points_played, gs.tracked AS tracked,
    {_flips("gs")}
FROM player_match_view v
JOIN matches m ON m.match_id = v.match_id
JOIN tournaments t ON t.tournament_id = v.tournament_id
JOIN match_players mp ON mp.match_id = v.match_id AND mp.player_id = v.player_id
JOIN games g ON g.match_id = v.match_id
LEFT JOIN game_stats gs ON gs.match_id = g.match_id AND gs.game_no = g.game_no;

DROP VIEW IF EXISTS player_rally_view;
CREATE VIEW player_rally_view AS
SELECT
    v.player_id AS player_id, v.player_name AS player_name, v.match_id AS match_id, m.match_code AS match_code,
    v.tournament_id AS tournament_id, v.tournament AS tournament, t.start_date AS tournament_start,
    v.event_code AS event_code, v.round AS round, v.match_date AS match_date, v.seq AS seq,
    r.game_no AS game_no, r.rally_no AS rally_no,
    {_flip("r", "points", "points")},
    CASE WHEN r.winner_side IS NULL THEN NULL WHEN r.winner_side = mp.side THEN 1 ELSE 0 END AS rally_won_by_player
FROM player_match_view v
JOIN matches m ON m.match_id = v.match_id
JOIN tournaments t ON t.tournament_id = v.tournament_id
JOIN match_players mp ON mp.match_id = v.match_id AND mp.player_id = v.player_id
JOIN rallies r ON r.match_id = v.match_id;
"""

_MATCH_HEAD = ("player_id", "player_name", "tournament_id", "tournament", "event_code", "round", "match_date", "match_id", "match_code")

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
               v.games, v.duration_min, v.match_id, v.match_code
        FROM player_match_view v JOIN tournaments t ON t.tournament_id = v.tournament_id
        ORDER BY v.player_id, t.start_date, v.tournament_id, v.event_code, v.seq
        """,
        ("player_id", "player_name", "tournament_id", "tournament", "category", "event_code", "draw_name",
         "round", "match_date", "status", "won", "partner_id", "partner", "opponent_1", "opponent_2",
         "games", "duration_min", "match_id", "match_code"),
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

_MATCH_STATS_COLUMNS = (
    *_MATCH_HEAD, "start_local", "venue", "duration_min", "tracked", "checks_ok", "player_games_won", "opponent_games_won",
    *_PERSPECTIVE_COLUMNS,
)
_GAME_STATS_COLUMNS = (
    *_MATCH_HEAD, "game_no", "player_points", "opponent_points", "total_points_played", "tracked", *_PERSPECTIVE_COLUMNS,
)
_RALLY_COLUMNS = (*_MATCH_HEAD, "game_no", "rally_no", "player_points", "opponent_points", "rally_won_by_player")
_EXPORTS["match_stats.csv"] = (
    f"SELECT {', '.join(_MATCH_STATS_COLUMNS)} FROM player_match_stats_view "
    "ORDER BY player_id, tournament_start, tournament_id, event_code, seq",
    _MATCH_STATS_COLUMNS,
)
_EXPORTS["game_stats.csv"] = (
    f"SELECT {', '.join(_GAME_STATS_COLUMNS)} FROM player_game_view "
    "ORDER BY player_id, tournament_start, tournament_id, event_code, seq, game_no",
    _GAME_STATS_COLUMNS,
)
_EXPORTS["rallies.csv"] = (
    f"SELECT {', '.join(_RALLY_COLUMNS)} FROM player_rally_view "
    "ORDER BY player_id, tournament_start, tournament_id, event_code, seq, game_no, rally_no",
    _RALLY_COLUMNS,
)


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

    def save_match_details(self, details: MatchDetails) -> int:
        """Save the Match tab, the Game tabs and every rally of one match; returns the rallies saved.

        The match must be in the database already (:meth:`save_matches`), and the details must be
        for that match. Saving again replaces everything stored for the match, so nothing goes
        stale. A tab the site does not track is stored with NULL statistics, never zeros.
        One transaction: all or nothing.

        Raises:
            InvalidInputError: the details name no match id, the match is not in the database, or it
                belongs to another tournament.
        """
        if details.match_id is None:
            raise InvalidInputError("The details do not name a match id, so they cannot be stored.")
        row = self._conn.execute(
            "SELECT tournament_id FROM matches WHERE match_id = ?", (details.match_id,)
        ).fetchone()
        if row is None:
            raise InvalidInputError(f"Match {details.match_id} is not in the database; save its matches first.")
        if row[0] != details.tournament_id:
            raise InvalidInputError(
                f"Match {details.match_id} is stored under tournament {row[0]}, the details are for {details.tournament_id}."
            )

        match_id = details.match_id
        stat_marks = ", ".join("?" * len(_STAT_COLUMNS))
        rallies = 0
        with self._conn:
            self._conn.execute("UPDATE matches SET match_code = COALESCE(match_code, ?) WHERE match_id = ?", (details.match_code, match_id))
            for table in ("rallies", "game_stats", "match_stats"):
                self._conn.execute(f"DELETE FROM {table} WHERE match_id = ?", (match_id,))
            self._conn.execute(
                f"INSERT INTO match_stats (match_id, start_local, venue, score_status, tracked, checks_ok, differences, "
                f"side1_result, side2_result, {', '.join(_STAT_COLUMNS)}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, {stat_marks})",
                (match_id, details.start_local.isoformat(sep=" ") if details.start_local else None, details.venue,
                 details.score_status, int(details.tracked), None if details.checks_ok is None else int(details.checks_ok),
                 "\n".join(details.differences) or None, details.side1_result, details.side2_result,
                 *_stat_values(details.side1, details.side2)),
            )
            for game in details.games:
                self._conn.execute(
                    f"INSERT INTO game_stats (match_id, game_no, total_points_played, tracked, {', '.join(_STAT_COLUMNS)}) "
                    f"VALUES (?, ?, ?, ?, {stat_marks})",
                    (match_id, game.game_no, game.total_points_played, int(game.tracked), *_stat_values(game.side1, game.side2)),
                )
                self._conn.executemany(
                    "INSERT INTO rallies (match_id, game_no, rally_no, side1_points, side2_points, winner_side) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [(match_id, game.game_no, r.rally_no, r.side1_points, r.side2_points, r.winner_side) for r in game.rallies],
                )
                rallies += len(game.rallies)
        return rallies

    def export_csv(self, directory: str | Path) -> dict[str, Path]:
        """Write ``results.csv``, ``matches.csv``, ``games.csv`` and the game-detail files into ``directory``.

        The game-detail files are ``match_stats.csv`` (the Match tab, one row per match), ``game_stats.csv``
        (the Game tabs, one row per game) and ``rallies.csv`` (the score after every rally); they hold
        only the matches whose details were saved, and a header when there are none.

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
        self._conn.executescript(_SCHEMA)  # creates what is missing; existing tables are left as they are
        self._migrate_matches_table()
        self._conn.executescript(_DETAIL_SCHEMA)
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._conn.commit()

    def _migrate_matches_table(self) -> None:
        """Version 1 -> 2: add ``matches.match_code`` to a database created before it existed."""
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(matches)")}
        if "match_code" not in columns:
            self._conn.execute("ALTER TABLE matches ADD COLUMN match_code TEXT")

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
            INSERT INTO matches (match_id, match_code, tournament_id, event_id, event_code, seq, draw_id, draw_name, round,
                                 match_date, duration_min, status, winner_side)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_id) DO UPDATE SET
                match_code = COALESCE(excluded.match_code, matches.match_code),
                tournament_id = excluded.tournament_id, event_id = excluded.event_id,
                event_code = excluded.event_code, seq = excluded.seq, draw_id = excluded.draw_id,
                draw_name = excluded.draw_name, round = excluded.round, match_date = excluded.match_date,
                duration_min = excluded.duration_min, status = excluded.status,
                winner_side = excluded.winner_side
            """,
            (match.match_id, match.match_code, match.tournament_id, event.event_id, event.event_code, seq, match.draw_id,
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


def _stat_values(side1: SideStats | None, side2: SideStats | None) -> list[int | None]:
    """The statistics as a flat list in ``_STAT_COLUMNS`` order (field by field, side 1 then side 2)."""
    values: list[int | None] = []
    for field in _STAT_FIELDS:
        values.append(getattr(side1, field) if side1 is not None else None)
        values.append(getattr(side2, field) if side2 is not None else None)
    return values
