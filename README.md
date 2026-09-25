# BWF Player Lookup and Tournament History

Type a badminton player's name and get, from [bwfbadminton.com](https://bwfbadminton.com):

| | What you get |
|---|---|
| **Search** | The player's profile URL. Ignores case, accents and word order; tolerates typos in full names; returns ranked candidates when the name is ambiguous; a clear "not found" otherwise. |
| **Personal details** | Nationality, height (cm), playing hand (Right/Left). |
| **Ranking** | Current rank and how many consecutive weeks the player has held it (plus since when). |
| **Tournament history** | Every tournament the player entered in the last year, and for each: the **result** (`1st`, `QF`, `R16`, ...), **who they played with** (doubles partner), **who they played against**, and the **points of every game**. Saved to a SQLite database and CSV files; running it again never duplicates anything. |
| **Deep dive** | For one player's year, from the saved data: tournaments entered, rests and time on tour, how often each round was reached, wins in two and in three games, and whether long runs of consecutive points go with winning (with a permutation p-value and a check that it is not just the points). Notebook section 7. |
| **Game details** | For every played match, what the site's match page shows: the **Match tab** and every **Game tab** (game points, most consecutive points, total points played and won) and the **score after every rally**, with built-in consistency checks. Downloaded with the history by default, saved in the same database and CSV files. |

A value the site does not list is `null`, with a note explaining it. A missing field never fails the whole request.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows; use `source .venv/bin/activate` elsewhere
pip install -e ".[dev,notebook]"   # "notebook" adds what is needed to run the notebook
```

**Notebook:** open [notebook.ipynb](notebook.ipynb) (VS Code or Jupyter), set `PLAYER_NAME`, run all cells. Section 4 downloads the last year's history with the game details of every match, section 5 shows the Match and Game tabs of one match, section 6 compares two players (Jonatan Christie and An Se Young) with SQL on the saved data, and section 7 is a deep dive into one player's year. The notebook keeps its own database (`data/bwf_notebook.sqlite`). The committed notebook already contains a run, so you can read the results without running anything.

**Command line:** the whole history download in one command.

```bash
python scripts/download_history.py "Jonatan Christie"
python scripts/download_history.py 73442 --since 2026-01-01 --until 2026-06-30
python scripts/download_history.py "Fajar Alfian" --db data/fajar.sqlite --out data/fajar_csv --no-matches
python scripts/download_history.py "Jonatan Christie" --show-games        # also one line per game
python scripts/download_history.py "Jonatan Christie" --no-game-details   # the shorter download without game details
```

## Tournament history (one call)

```python
from bwf_player import download_player_history, format_history

summary = download_player_history("jonathan cristie")    # a name, or the player id (73442)
print(format_history(summary))
```

Real output (2026-09-23; the window is one year back from today):

```
Search:       FOUND - Matched 'Jonatan CHRISTIE' (score 94).
Player:       Jonatan CHRISTIE (id 73442)
Window:       2025-09-23 to 2026-09-23
Downloaded:   19 tournament(s), 19 event(s), 58 match(es) (58 played), 139 game(s)
Checked:      the matches reproduce the site's own totals: yes (19 event(s))
Game details: 58 match(es), 56 with rally data, 2 with game scores only, 4779 rallies
Checked:      rallies, statistics and scores agree with each other and with the player's page: yes
Database:     data\bwf_history.sqlite
CSV:          data\export\results.csv
CSV:          data\export\matches.csv
CSV:          data\export\games.csv
CSV:          data\export\match_stats.csv
CSV:          data\export\game_stats.csv
CSV:          data\export\rallies.csv

2025-09-23  SUWON VICTOR Korea Open 2025  [MS]  result: 1st  5-0 in matches  (HSBC BWF World Tour Super 500)
    R32       won              vs NG Ka Long Angus  21-11, 21-17
    R16       won              vs Chia Hao LEE  22-20, 15-21, 21-15
    QF        won              vs Kenta NISHIMOTO  21-14, 21-8
    SF        won              vs Alwi FARHAN  18-21, 21-14, 21-15
    Final     won              vs Anders ANTONSEN  21-10, 15-21, 21-17
```

In doubles each match also names the partner and both opponents:

```
    Final     lost             with Muhammad Shohibul FIKRI vs KIM Won Ho / SEO Seung Jae  16-21, 21-23
```

- The window is `since`/`until` (default: one year back from today to today). A tournament counts if its dates overlap the window.
- **The "Checked" line is a built-in test.** The site shows its own totals for each tournament (matches, games and points won and lost). The downloaded matches are added up and compared with them; any difference is listed in `summary.notes` and `summary.events_disagreeing`.
- **Game details** are downloaded by default: one more request per played match, checked and saved with the history. `download_player_history(..., game_details=False)` (command line `--no-game-details`) skips them. `format_history(summary, games=True)` (command line `--show-games`) prints one line per game:
  ```
  2026-09-01  LI-NING China Masters 2026  [MS]  result: R16  1-1 in matches  (HSBC BWF World Tour Super 750)
      R32       won              vs LEONG Jun Hao  21-17, 21-19
          game 1  21-17  38 rallies  longest run 3-3  game points 3-0
          game 2  21-19  40 rallies  longest run 7-4  game points 1-0
  ```
- **Cost.** About 25 requests for a singles player who entered 19 events without game details (two for the years, up to four for tournament categories, one per event entered), and one more per played match with them: about 85 for 58 matches, roughly four minutes at the polite pace of 2.5 s per request. Doubles players who enter several events per tournament need more. Everything is cached, so repeating the call is instant and free.
- **Failures.** If a request fails (for example Cloudflare blocks it) the exception is raised and whatever was saved up to then stays in the database. Run the same call again later: it continues from the cache and updates the same rows.
- A name that matches no single player, or a player with no tournament in the window, downloads nothing and creates no database; `summary.notes` says why.
- `summary` is a pydantic model (`summary.matches`, `summary.all_totals_agree`, `summary.game_details`, `summary.rallies`, `summary.all_details_agree`, `summary.history`, `summary.event_matches`, `summary.details`, `summary.model_dump_json()`).

### Sample: two players compared with SQL

Real output of notebook section 6 (2026-09-24; Jonatan Christie and An Se Young, one year each, everything from the saved views):

```
Matches played in the window
player            matches  won  lost  win_pct
Jonatan CHRISTIE  58       38   20    65.5
AN Se Young       77       75   2     97.4

Rally statistics per player (matches with rally data)
player            matches  avg_minutes  avg_rallies  points_won_pct  best_run  worst_run_against
Jonatan CHRISTIE  56       53.9         85.3         52.8            10        9
AN Se Young       75       45.4         72.5         61.6            16        10

Comeback games: won after trailing by 8 points or more (needs the rally-by-rally data)
player            date        tournament                  round  opponent      game  score  max_deficit
AN Se Young       2026-06-06  POLYTRON Indonesia Open 20  SF     CHEN Yu Fei   3     23-21  10
AN Se Young       2025-10-19  VICTOR Denmark Open 2025    Final  WANG Zhi Yi   2     24-22  9
Jonatan CHRISTIE  2026-01-17  YONEX-SUNRISE India Open 2  SF     LOH Kean Yew  1     21-18  8

Latest matches of player 87442 (the match-level columns come from the Match tab)
date        tournament                    round  won  opponent          games         min  rallies  run  run_against
2026-09-23  20th Asian Games Aichi-Nagoy  SF     1    Akane YAMAGUCHI   21-9, 18-21, 21-11  87   -    -    -
2026-09-06  LI-NING China Masters 2026    Final  1    Tomoka MIYAZAKI   21-17, 21-6   45   65       9    3
```

The two 2026 Asian Games matches show `-` for rallies and runs: for that team event the site gives only the game scores, so the statistics are empty (NULL), not zero.

### The saved data

`data/bwf_history.sqlite` (git-ignored) has the tables `players`, `tournaments`, `results`, `matches`, `match_players` and `games`, the game-detail tables `match_stats`, `game_stats` and `rallies`, and views with one row per player and match (`player_match_view`, `player_match_stats_view`), per game (`player_game_view`) and per rally (`player_rally_view`):

```python
import sqlite3
con = sqlite3.connect("data/bwf_history.sqlite")
con.execute("""SELECT match_date, tournament, round, won, partner, opponent_1, opponent_2, games
               FROM player_match_view WHERE player_id = 73442 ORDER BY match_date, seq""").fetchall()
# or: pandas.read_sql("SELECT * FROM player_match_view", con)
```

`data/export/` holds the same as CSV (UTF-8 with a byte-order mark so Excel shows accents; empty values are blank):

| File | One row per | Main columns |
|---|---|---|
| `results.csv` | event entered | player, tournament, category, dates, location, event (`MS`, `WD`, ...), `position`, matches/games/points won and lost |
| `matches.csv` | match | player, tournament, event, round, date, `status`, `won` (1/0/empty), partner, `opponent_1`, `opponent_2`, `games` ("21-17, 21-19", the player's points first) |
| `games.csv` | game | player, tournament, round, match, `game_no`, `player_points`, `opponent_points` |
| `match_stats.csv` | match with saved details | the Match tab: `player_games_won`, `opponent_games_won`, and for the player and the opponent the most consecutive points, game points, rallies played and won (plus the site's tracking fields), start time, venue, `tracked`, `checks_ok` |
| `game_stats.csv` | game with saved details | the Game tabs: points, `total_points_played`, and the same statistics per game |
| `rallies.csv` | rally | the score after every rally (`player_points`, `opponent_points`, `rally_won_by_player`) |

`status` is `played`, `bye` (the player advanced without playing; the site counts it as a match won, `won` is empty), `walkover`, `retired` (the partial game is kept), `disqualified`, `scheduled` (not played yet: planned date, no result) or `in_progress`. Filter `status = 'played'` for matches that were really played. Column and table details: PRD section 10.

## Game details of one match (Match tab, Game 1, Game 2, ...)

Everything the site's match page shows for one match, including the score after every rally:

```python
from bwf_player import format_match_details, get_match_details

details = get_match_details(5515, 13)            # tournament id and match number (the "match/13" of the page URL)
print(format_match_details(details, rallies=False))
```

```
All England Open Badminton Championships 2026 | MS | R16 | 2026-03-05 19:15 | Utilita Arena Birmingham | 48 min
  side 1: LIN Chun-Yi
  side 2: Jonatan CHRISTIE
  winner: LIN Chun-Yi

MATCH
                              side 1  side 2
  Final match score                2       0
  Game 1 score                    21      19
  Game 2 score                    21      12
  Game points                      7       0
  Most consecutive points          7       5
  Total points played             73      73
  Total points won                42      31

GAME 1
                              side 1  side 2
  Score                           21      19
  Most consecutive points          7       5
  Game points                      6       0
  Total points played             40      40
  Total points won                21      19
...
Checks: the rallies, statistics and scores agree.
```

`details.games[0].rallies` is the score after each rally (`0-1, 1-1, 1-2, ...`). Each match of a download has a `match_code` (`PlayerMatch.match_code`); `details_targets(event.matches)` lists the matches worth requesting. `download_player_history` does all of this for every played match of the download and saves it (`HistoryStore.save_match_details(details)`: Match tab, Game tabs and every rally; see below). To get one match on its own, use `get_match_details` as above.

- **Every figure is checked.** The statistics the site shows (most consecutive points, game points, points played and won) are re-derived from the rally sequence and compared; with `match=` the details are also compared with the match from the player's page (players, scores, winner). Differences are listed in `details.differences`; `details.checks_ok` is `True`, `False` or `None` (nothing to check).
- **Coverage differs by tournament.** World Tour level events have all of it. Lower-level events (for example an International Challenge) give only the game scores: there is no rally sequence or statistics, the fields are `None` (the site's zeros mean "not tracked"), and `details.tracked` is `False`. Byes and walkovers have no games and are not requested.
- A match the site does not have raises `BwfNotFoundError`.
- **Stored as NULL, never 0, where the site does not track it.** The site tracks rallies for most events but for some only the game scores (small tournaments, and also some big or brand-new ones such as a team event in progress). Those games have `tracked = 0` and blank statistics.

```python
from bwf_player import HistoryStore, details_targets, get_match_details, get_matches, get_tournaments

with HistoryStore("data/bwf_history.sqlite") as store:
    store.save_tournaments(history, player_name="Jonatan CHRISTIE")
    for entry in history.entries:
        event = get_matches(pid, entry)
        store.save_matches(event)
        for match in details_targets(event.matches):
            store.save_match_details(get_match_details(match.tournament_id, match.match_code, match=match))
    store.export_csv("data/export")          # now also match_stats.csv, game_stats.csv, rallies.csv
```

An existing database from before this feature is upgraded automatically when it is opened; nothing in it is lost.

## Deep dive into one player's year

`bwf_player.analysis` answers five questions from the saved database (it never calls the site). Notebook section 7 runs them for the player of section 4; in Python:

```python
import sqlite3
from bwf_player.analysis import deep_dive, format_activity, format_round_progress, format_game_split, format_run_correlation

con = sqlite3.connect("data/bwf_notebook.sqlite")
dive = deep_dive(con, 73442, since, until)          # count, activity, rounds, games, runs_by_match, runs_by_game
print(format_round_progress(dive.rounds))
```

Real results for Jonatan Christie, 2025-09-26 to 2026-09-26 (the notebook's committed run; details and definitions: PRD section 12):

| Question | Answer |
|---|---|
| Tournaments | **20** (18 individual, 2 team) |
| Rest and time on tour | On tour 61 days (17% of the year); **18 rests**, average 16.8 days, longest 44 days; 5 rests shorter than a week, 3 of 28 days or more |
| Rounds (17 knockout events) | R64 2, R32 **17**, R16 **13**, QF **9**, SF **6**, Final **5**; **champion 3 times**, runner-up 2 (plus team events and a group stage listed apart) |
| Games | 59 matches: **won 38** (22 in two games, 16 in three), lost 21 (7 in three, 14 in two); won 16 of 23 three-game matches |
| Runs and winning | Positive: r = 0.46 per match, 0.69 per game, both far from chance; the player with the longer run won 86.7% of matches and 94.1% of games. But it is mostly the points: with the points balance taken out the correlation is about zero (-0.33 per match, -0.09 per game) |

Every answer is checked in the tests by recomputing it a different way. One player and one year is a small sample, so small differences mean little.

## Player lookup (name to details and ranking)

```python
from bwf_player import format_result, lookup_player

result = lookup_player("jonathan cristie")     # typo on purpose
print(format_result(result))
```

```
Search:         FOUND - Matched 'Jonatan CHRISTIE' (score 94).
Profile URL:    https://bwfbadminton.com/player/73442/jonatan-christie

Personal details
  Name:          Jonatan CHRISTIE
  Nationality:   Indonesia
  Height:        179.0 cm
  Playing hand:  Right

Ranking (MEN'S SINGLES)
  Current rank:  1
  At this rank:  4 week(s), since 2026-08-25 (latest ranking list 2026-09-15)
```

`result` is a pydantic model (`result.search`, `result.profile`, `result.ranking`; `result.model_dump_json()` for JSON).

## Step by step

Every stage is also available on its own:

```python
from datetime import date
from bwf_player import get_matches, get_tournaments, HistoryStore
from bwf_player.search import search_player
from bwf_player.profile import get_profile
from bwf_player.ranking import get_ranking

found = search_player("Christie Jonatan")        # status: found | ambiguous | not_found
pid = found.best_match.player_id
get_profile(pid)                                  # nationality, height_cm, playing_hand, missing_fields, notes
get_ranking(pid)                                  # current_rank, weeks_at_current_rank, other_events, notes
get_ranking(pid, event_id="9-90070")              # a different ranking event (ids are listed in other_events)

history = get_tournaments(pid)                    # oldest first, one entry per event entered
history.entries[-1]                               # position, matches_won, games_lost, points_for, category, ...
get_tournaments(pid, since=date(2026, 1, 1), until=date(2026, 3, 31))

event = get_matches(pid, history.entries[-1])     # one request: every match of that event
for m in event.matches:
    print(m.round, m.won, m.partner and m.partner.name, [o.name for o in m.opponents],
          [(g.player_points, g.opponent_points) for g in m.games])
event.totals_agree                                # True: the matches add up to the site's own totals

with HistoryStore("data/bwf_history.sqlite") as store:
    store.save_tournaments(history, player_name="Jonatan CHRISTIE")
    store.save_matches(event)
    store.export_csv("data/export")
```

Settings (match threshold, request spacing, cache location and lifetime, default database and CSV folder) live in `BwfConfig`; pass `BwfHttpClient(BwfConfig(...))` as the `client` argument.

## How it works

The site is a JavaScript app that loads its data from a JSON API, so the tool calls that API directly instead of scraping HTML. Search fuzzy-matches against the site's full player list (cached for 7 days) and falls back to the site's own name search for players missing from that list. "Weeks at this rank" is derived from the weekly ranking history: the site's own "consecutive weeks" figure describes the player's *best* rank, not the current one. The history comes from the same endpoints the site's player page uses for its Tournaments tab: the tournament list per year, then the match breakdown per event. Design, endpoints, findings and decisions are in [docs/PRD_master.md](docs/PRD_master.md).

## Project layout

```
bwf_player/      the package: http_client, names, search, profile, ranking, lookup,
                 tournaments, matches, store, history, parsing, models, config
notebook.ipynb   thin interface over the package (committed with its outputs)
tests/           pytest; offline tests use saved real API responses in tests/fixtures/
scripts/         download_history.py, save_test_results.py, execute_notebook.py
docs/            PRD_master.md (source of truth), PRD_changelog.md (per iteration)
test_results/    latest.txt: full output of the most recent test run
data/            the downloaded database and CSV files (created on first use, git-ignored)
```

## Tests

```bash
pytest                                # offline suite (default; no network): 905 tests
pytest -m live                        # live smoke tests against bwfbadminton.com: 20 tests, about 5 minutes (one does the full real download)
python scripts/save_test_results.py   # both suites -> test_results/latest.txt
python scripts/execute_notebook.py    # re-run the notebook and save its outputs
```

## Limitations and cautions

- **Cloudflare.** The site blocks automated traffic it dislikes; during development a test IP was hard-blocked after about 15 quick requests. The client waits 2.5 s between requests, caches everything, and stops at once (raising `BlockedByCloudflareError`) if it is blocked. Do not loop it over many players: a download is about 25 requests per player, about 85 with the game details.
- **Unofficial API.** It is the site's own front-end API, undocumented, and may change without notice. **The site's terms and conditions have not been reviewed**; check them before any use beyond personal research.
- **Search limits.** A typo inside a one-word query ("cristie") is not matched. A typo'd name for a player missing from the site's player list (e.g. Kento Momota) is not found. A reversed name for such a player, when its words are common, may fail ("Dan Lin" does not find "LIN Dan"). Details and workarounds: PRD section 8. To avoid the search, pass the player id.
- **Ranking events.** The result reports the first event the site lists (usually singles); others are in `other_events`.
- **Tournament history.** One player at a time. Para tournaments are not covered. The category is `null` for tournaments the site's calendar gives none (62 of the 326 in the last year's calendar; none for Christie's). Disqualifications are handled defensively but were not present in the real data used for testing. A match not played yet (seen on the ongoing Asian Games, September 2026) is stored as `scheduled` with no result and counts as neither win nor loss; a started but unfinished match would be `in_progress` (not seen yet). `position` is the site's own label and is `null` for team events, which have none.
- **Stored data.** The database keeps everything you have saved; saving again updates rows but never deletes any, so a match the site later removes stays in the file. The view `player_match_view` lists only players whose own history you downloaded (opponents are in `players` and `match_players`).
- **Unknown id vs never ranked.** The site answers both the same way, so both come back as "no ranking events".

## Documentation

- [docs/PRD_master.md](docs/PRD_master.md): requirements, findings, architecture, schema, development procedure, open questions
- [docs/PRD_changelog.md](docs/PRD_changelog.md): what changed in each iteration, why, and what was tested
