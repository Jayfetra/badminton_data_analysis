# PRD Changelog

## Iteration 12 — 2026-09-25/26 (R9: deep-dive analysis; matches not played yet)

**What changed**
- New `bwf_player/analysis.py` (R9): `count_tournaments`, `activity`, `round_progress`, `game_split`, `run_correlation` (per match and per game), `deep_dive`, the statistics helpers (`pearson`, `permutation_p_value`, `partial_correlation`, `describe_correlation`) and text formatters. It reads the saved database only. Definitions and the real results for Jonatan Christie are in PRD section 12.
- Notebook section 7 ("Deep dive into one player's year"): the five questions, for the player of section 4; committed **with all 22 code cells executed** (a `CLAUDE.md` rule added the same day: the notebook is always delivered fully executed).
- **Matches not played yet** (found by running the deep dive on 2026-09-25): new match statuses `scheduled` and `in_progress`, decided by the site's `match_state` ("F" finished, "N" not started). Parser, report (`not played yet (2026-09-26)`), storage, `details_targets` and the analysis handle them; the analysis shows a `pending` column in the round funnel.
- `CLAUDE.md` (working agreements) and a memory note added.
- Report wording made neutral ("the player") so it is right for any player.
- Earlier-iteration code touched: `models.py` (two statuses), `matches.py` (state handling), `history.py` (report text and the "not requested" label), tests (`test_live.py`: three live tests made deterministic).

**Why**
- The owner asked for a deep dive on Christie's year (tournaments, rests, rounds, two- and three-game wins, runs vs winning), starting with Christie.

**Bugs found by looking at the real output (all fixed)**
1. **Wins/losses were 1/0 integers, and my code tested `is False`.** The first funnel showed "lost 0" everywhere and "runner-up 0" although he reached five finals; group-stage records read 0-0. Fixed (`== 0` / `== 1`); the round table is now checked for `reached = won + lost + pending` in the tests and, in the notebook guard, from its printed output.
2. **A tournament that overlaps the window only by its schedule** (China Masters 2025, scheduled to 21 Sep, all matches on 17-18 Sep) created a "rest" starting before the window. Activity now counts only tournaments where the player played inside the window, and says which it left out. Found by the fixture tests, not the live data.
3. **A match not played yet** (Asian Games 2026 individual, `match_state` "N") was stored as `played` with no winner and no games, which broke the round table (17 reached, 13 + 3 won or lost) and triggered a details request for a match that had not happened. Now `scheduled`, with a real fixture.
4. Tests that assumed "the latest tournament" is finished failed twice (the tournament under way has only a bye and a scheduled match). They now use fixed, finished tournaments.

**What was tested (`test_results/latest.txt`, final regression)**
- Offline: **905 passed** (835 before): 45 tests in `tests/test_analysis.py` (the five answers recomputed independently on the real fixtures; hand-worked synthetic calendars, funnels, game splits and correlations; helpers; text), 22 for matches not played yet and the analysis of them, and 3 in the notebook guard.
- Live: **20 passed** in 4 min 43 s. An earlier run had 2 failures (bug 4 above); the final run is clean.
- Notebook executed end to end in a real kernel: 22 code cells, no errors.

**Findings (Christie; PRD section 12)**
- (Figures of the committed notebook run, window 2025-09-26 to 2026-09-26; the window is rolling, so a day earlier on tour was 62 days.) 20 tournaments; on tour 61 days (17% of the year); 18 rests, average 16.8 days, longest 44; champion 3 times, runner-up 2; won 22 matches in two games and 16 in three; correlation of the run difference with winning r = 0.46 per match and 0.69 per game, both far from chance, but with the points balance taken out it is about nothing.
- The site's own match states: "F" finished, "N" not started; the `in_progress` state has not been seen.

**Corrections of earlier statements**
- README and PRD said matches in progress had not appeared in the real data; a not-started match did on 2026-09-25 (PRD section 8, item 6; README limitations). An in-progress (started, unfinished) match still has not.

## Notebook update — 2026-09-24 (two players side by side)

**What changed**
- Notebook section 6: downloads a second player (An Se Young) into the same database and compares the two with SQL on the views: record, results and titles, rally statistics (average length, share of points won, best run), the longest games, comeback games (needs the rally data), the latest matches with their Match-tab figures, and the first rallies of a game. `SECOND_PLAYER` can be changed. Committed with real outputs (16 code cells, no errors).
- The notebook now uses its own database (`data/bwf_notebook.sqlite`) and CSV folder (`data/notebook_export`), so runs of the command line or of older notebooks (with other date windows) cannot mix into its samples. New guard test for section 6 (836 offline tests).
- No package code changed.

**Real result (2026-09-24, window 2025-09-24 to 2026-09-24):** An Se Young: 17 tournaments, 79 matches (76 played, 1 retired, 2 walkovers), 168 games; game details for 77 matches (75 with rally data, 2 games-only; 5,439 rallies; 2 walkovers not requested); all checks agree; 11 titles, record 75-2. Jonatan Christie: 19 tournaments, 58 matches, 38-20; 56 matches with rally data.

**Finding (why the notebook got its own database)**
- The first sample showed 60 matches for Christie instead of 58. The shared `data/bwf_history.sqlite` still held two matches from an earlier run whose window (from 2025-09-21) included China Masters 2025; saving never deletes rows, so they stayed after the window moved. This is documented behaviour (README, "Stored data") but easy to overlook in a sample; a dedicated file removes it. To clean a database, delete the file and download again.

## Iteration 11 — 2026-09-23 (R8c: game details in the one-call download, notebook, README, full regression)

**What changed**
- `download_player_history(..., game_details=True)`: after each event's matches, the game details of every played match are fetched, checked, saved and counted. New `HistorySummary` fields: `game_details`, `game_details_tracked`, `game_details_untracked`, `game_details_skipped`, `game_details_not_found`, `game_details_disagreeing`, `all_details_agree`, `rallies`, `details`. `format_history(summary, games=True)` adds a line per game and the header has a `Game details:` line and its own check line.
- `scripts/download_history.py`: `--no-game-details` and `--show-games`.
- Notebook: section 4 now downloads the game details (`GAME_DETAILS = True`, switchable); new section 5 shows the Match tab, Game 1 and Game 2 and the rally sequence for the example match of the request, and reads the same match back from the database; committed **with its executed outputs** from a real run (10 code cells, no errors).
- README rewritten for the finished feature; PRD_master version 3.0.
- Earlier-iteration code touched: additions to `models.py` (`HistorySummary`), `history.py` and the script. `tests/test_history.py` now keeps its tests on the history itself by turning the game details off in a small wrapper (they are tested in the new file); one live test was extended.

**Why**
- The user asked to record the Match and Game tabs of every match of the same one-year download, on by default. Details are fetched right after each event so that a failure keeps everything finished so far, and a missing page is noted instead of aborting the whole download.

**What was tested (`test_results/latest.txt`, final regression)**
- Offline: **835 passed** (810 before; 24 new in `tests/test_history_details.py` plus one in `tests/test_notebook.py`). Christie's whole year from fixtures: 58 details, 138 games, all checks agree, exactly one request per match (right parameters, right order), database and six CSV files, JSON, running twice changes nothing, progress messages; the switch turns it all off; details can be added to an existing history database without touching it; games-only matches stored as NULL with the note; byes and walkovers not requested; a doubles run; a missing details page noted while the rest carries on; **a corrupted response is reported and stored but does not stop the download**; **a Cloudflare block on the 11th details request keeps the earlier matches and a re-run gives a database identical to an uninterrupted run**; a malformed details response stops with a clear error; the report header, per-game lines and games-only marker; the command line (default, `--no-game-details`, `--show-games`).
- Live: **20 passed** in 4 min 38 s. The end-to-end test now downloads the real details for Christie's whole year and checks that every played match is fetched, skipped or noted, that all checks agree, and that a second run makes **no request**.
- Notebook executed in a real kernel (10 code cells, no errors). Real result: 19 tournaments, 58 matches, 139 games; details for 58 matches, 56 with rally data (4,779 rallies) and 2 with game scores only; all checks agree.
- **Fresh environment:** the current tree was copied to a temporary folder, installed into a new virtual environment and its offline suite run there: 835 passed.

**Findings**
- The two games-only matches in Christie's real download are from the ongoing 2026 Asian Games team event; so games-only coverage is not limited to small tournaments (also in the Iteration 10 entry). Both are stored with NULL statistics and pass the checks against the player's page.
- The window moved with the date (2025-09-23 to 2026-09-23): China Masters 2025 dropped out, the Asian Games came in, and Christie still has 19 tournaments and 58 matches (139 games instead of 138).
- The live suite is now much longer (4 min 38 s instead of about 2.5 minutes) because its end-to-end test does the real ~85-request download once; run it sparingly.

**Stale statements corrected**
- PRD risk 4 (live suite length) and risk 5 (request volume: about 85 with game details), PRD open question 9 (terms of service: more requests now), README test counts and cost lines, the README's "in progress" / "comes next" wording for game details, and PRD section 11's status.

**Still open**
- The terms and conditions of bwfbadminton.com remain unreviewed (PRD section 8, items 2 and 9; acknowledged by the user).
- Not covered by real data: a disqualification, a match still in progress, and a game reaching 29 points (PRD section 8, item 6 and section 4).

## Iteration 10 — 2026-09-23 (R8b: storage of the game details)

**What changed**
- `store.py`: schema version **2**. New tables `match_stats` (the Match tab), `game_stats` (the Game tabs) and `rallies` (the score after every rally); `matches.match_code`; `HistoryStore.save_match_details(details)`; views `player_match_stats_view`, `player_game_view`, `player_rally_view` in the player's point of view; CSV files `match_stats.csv`, `game_stats.csv`, `rallies.csv`; `match_code` added as the last column of `matches.csv` and of `player_match_view`. Opening a version 1 database migrates it (adds the column, creates the new tables and views; nothing is deleted).
- The statistic columns, inserts, views and CSV columns are generated from `SideStats`, so they cannot drift apart.
- Earlier-iteration code touched: `store.py` (as above), `tests/test_store.py` (the CSV file set and the `matches.csv` columns changed), `tests/test_history.py` (the CSV file set; one index into a table row, because `match_code` is now the second column), `tests/test_live.py`. No behaviour of R1-R9 other than these additions changed.
- PRD_master: version 2.2, section 11 data model rewritten as implemented, storage design note, iteration table.

**Why**
- The user wants the Match tab and every Game tab recorded, in SQLite and CSV like the rest. Statistics the site does not track are NULL (never 0), because a games-only match with zeros would look like a match with no points won.

**What was tested (`test_results/latest.txt`)**
- Offline: **810 passed** (769 before; 41 new in `tests/test_store_details.py`): the new tables and views; Christie's whole year (58 match tabs, 138 game tabs, every game with as many rally rows as points); the example match (All England 2026, R16) field by field in all three tables, and the whole 40-rally sequence of game 1; the player's-side views for a match where the player is side 2 and one where the player is side 1; games without details show NULL statistics; games-only matches (NULL statistics, no rallies, in the views and CSV as blanks); saving twice changes nothing; a re-save replaces stale games and rallies; failed checks stored with their text; a missing match code is filled and never erased; refusals (match not stored, no match id, wrong tournament); **a constraint failure half way rolls the match back**; foreign keys; **a real database turned back into a version 1 file is migrated with its data intact**, takes details afterwards, and reopening a current database is harmless; the three CSV files (columns, row counts, values from the player's side, ordering, blanks for untracked, header-only when there are no details).
- Live: **20 passed** (2 new): China Masters 2026 stored and exported (rally rows equal the sum of the games' points, all checks agree) and Telangana International Challenge 2025 (games only: NULL statistics, no rallies, checks agree).

**Findings**
- **A live test failed and taught something.** My first live storage test used "the player's latest tournament" and asserted rally data. Because the date had moved on, the latest tournament was the ongoing 2026 Asian Games team event, for which the site gives only game scores. The code was right (untracked, NULL, checks pass); the assumption in the test was wrong. So games-only coverage can affect any event, including new ones. The tests now use fixed historical tournaments.
- The earlier Iteration 9 live test ("recent matches agree with the player's page") passes for both kinds of tournament, because it does not assume rally data.
- The default window moved with the date (now 2025-09-23 to 2026-09-23); Christie still has 19 tournaments in it, one of them new (5876, the Asian Games).

## Iteration 9 — 2026-09-22 (R8a: game details of one match)

**What changed**
- New feature area, PRD section 11 (R8): record what the site's match page shows (Match tab, Game 1, Game 2, ...). This iteration fetches, parses and checks the details of one match; storage is Iteration 10, the integration into the download Iteration 11.
- Added `bwf_player/game_details.py`: `get_match_details(tournament_id, match_code, client=None, *, match=None)` (one request to `h2h/match`), `details_targets`, `parse_match_details`, `check_internal`, `check_against_match`, `longest_runs`, `game_point_rallies`, `format_match_details`.
- Models: `SideStats`, `Rally`, `GameDetail`, `DetailPlayer`, `MatchDetails`; `PlayerMatch.match_code`.
- `BwfNotFoundError` (HTTP 404, new in `exceptions.py`; `http_client.py` raises it and does not retry it); `parsing.to_code`.
- Earlier-iteration code touched: `matches.py` now reads the match `code` (nothing else changed), `http_client.py` (404 is its own error), `tests/fakes.py`, `__init__.py`, `tests/test_live.py`. The 29 saved match fixtures were regenerated from the same real responses **with `code` included** (they had been trimmed without it); one existing test gained the `match_code` field. No behaviour of R1-R7 changed.
- Fixtures: 91 real `h2h/match` responses (all 58 Christie matches, doubles, mixed doubles, team events, a retirement, games-only matches, a bye and a walkover), trimmed of avatars, flags and short names.

**Why**
- The user asked for the game detail of each match as on the match page, including "all information" from the Match and Game tabs. The page loads one endpoint (`h2h/match`) that has all of it, including the score after every rally.

**What was tested (`test_results/latest.txt`)**
- Offline: **769 passed** (556 before the details module: 553 plus 3 new HTTP-client tests; then 213 new in `tests/test_game_details.py`). Highlights: the example match from the request compared field by field (Match tab, both Game tabs, the whole 40-rally sequence of game 1); **all 88 real matches with details pass every internal check and the cross-check with our own data**; the cross-game longest run, sums, extended games; doubles, team event, retirement, games-only matches, bye, walkover; **each check is proven by corrupting a real response** (lost rally, wrong last score, skipped point, gap in numbering, each wrong statistic at game and match level, wrong result, two match ids, unreadable game or rally); wrong match id, tournament, players, side, scores and winner against our data; malformed payloads; ids validated before any request; 404; Cloudflare block; text layout line by line.
- Live: **18 passed** (3 new): the example match page (All England 2026, R16), Christie's latest tournament (every played match agrees with our data), and a real 404.

**Findings**
- **Every statistic the site shows can be re-derived from the rally sequence, and matches it, on all 204 tracked real games**: most consecutive points, game points (rallies played while one point from the game), rallies played and won. Match-level **most consecutive points crosses game boundaries** (it is not the best game's value); other match-level figures are sums.
- **Coverage varies**: lower-level tournaments (International Challenge) give only the game scores; their statistics are zeros meaning "not tracked". Stored as NULL, not 0, with a note.
- A missing match is HTTP 404 with a body of `{"stats":null,"games":[]}`; byes and walkovers answer 200 with no games.
- Names differ slightly between the match page and the player page for a few players (one spelling of `Anindya/Anindiya`); players are compared by id.
- Not covered by real data: a game reaching 29 points (none of 204 did; 15 went past 21, the longest 26-24). The rule for the deuce end (one point from the game at 29-29) is covered by a unit test only.
- A connection failure (HTTP 000) happened once during the investigation and did not recur.

**Correction of my own earlier statement**
- While planning I wrote that Christie beat LIN Chun-Yi in the example match. He lost: LIN Chun-Yi (side 1) won 21-19, 21-12. The plan text was not used for any code; the tests and this documentation use the real result.

## Iteration 8 — 2026-09-21 (end-to-end history download, notebook, README, full regression)

**What changed**
- Added `bwf_player/history.py`: `download_player_history(player, client=None, *, since, until, today, db_path, export_dir, export, progress)` (name or id -> tournaments -> matches -> SQLite -> CSV) returning a `HistorySummary`, and `format_history` (text report). New model `HistorySummary` in `models.py`; `bwf_player` now also exports `download_player_history`, `format_history`, `HistorySummary`, `HistoryStore` and `BwfHttpClient`.
- Added `scripts/download_history.py`: the same download from the command line (`--since`, `--until`, `--db`, `--out`, `--no-csv`, `--no-matches`; exit code 0 downloaded, 2 nothing found or nothing in the window, 1 invalid input or failure).
- Notebook: new section 4 (download, then read the saved data back with the standard library); imports moved to the first cell; committed **with its executed outputs** from a real run (`scripts/execute_notebook.py`, 8 code cells, no errors).
- README rewritten as the final user documentation (history first: one call, real output, cost, failure behaviour, the saved data and CSV columns, step-by-step API, limitations, test counts).
- PRD_master: version 2.0, design notes, risk 5 (request volume), open question 9, status and differences from the plan, stale statements corrected (below).
- Earlier-iteration code touched: additions only (`__init__.py`, `models.py`). No behaviour of R1-R7 changed.

**Why**
- The user asked for the last year's tournaments of a player with results, partners and per-game scores. Iterations 5-7 built the parts; this one connects them so a single call (or command, or notebook cell) does the whole job and reports whether the result can be trusted.
- Failing fast (instead of skipping a failed event) was chosen because a Cloudflare block must stop the run at once, and a network outage would otherwise cost minutes of retries per event; saving each event as it arrives and the HTTP cache make a re-run cheap.

**What was tested (`test_results/latest.txt`, final regression)**
- Offline: **553 passed** (508 before; 45 new: 36 in `tests/test_history.py`, 8 in `tests/test_script.py`, 1 in `tests/test_notebook.py`). Highlights: Christie's whole year from fixtures (19 tournaments, 58 matches, 138 games, all totals agree; exact requests made; database and CSV written where configured); running twice leaves every table identical; id and name inputs; bad ids make no request; ambiguous or unknown names and an empty window download and create nothing; a doubles title run, a bye and a walkover; a dropped match is reported (`all_totals_agree` False, named event, note); **a Cloudflare block on the fifth match request keeps the earlier events and a re-run gives a database identical to an uninterrupted run**; the text report checked line by line; the command line (exit codes 0/1/2, options, progress on stderr, bad dates).
- Live: **15 passed** (1 new): "jonathan cristie" end to end from the real site (at least 10 tournaments and 30 matches, all events reproduce the site's totals), then a second run with the network wrapper counting calls: **zero requests**, database unchanged. Total 118 s.
- Notebook executed end to end in a real kernel: 8 code cells, no errors. Real result: 19 tournaments, 58 matches, 138 games, all 19 events reproduce the site's totals.
- **Fresh environment:** the current tree was copied to a temporary folder, installed into a new virtual environment (`pip install -e ".[dev]"`) and its offline suite run there: 553 passed.

**Corrections of earlier statements (found while checking for stale text)**
- PRD risk 4 said 11 live tests / about 60 s (from Iteration 5); it is now 15 tests, about 2 minutes.
- PRD section 10 said the end-to-end function was to come in Iteration 8, and the status paragraph repeated the R7 sentence; both rewritten.
- The plan said the notebook extra would gain `pandas`. It did not: the notebook uses `sqlite3` from the standard library, keeping the install light (README shows the `pandas.read_sql` one-liner). The plan called the command line optional; it was added.

**Findings / still open**
- Both questions to the user are resolved (2026-09-21): overlapping tournaments count, and the first ranking event is enough (PRD section 8, items 8 and 5).
- The terms and conditions of bwfbadminton.com remain unreviewed (item 2 and new item 9), which matters more now that a history costs 25-40 requests instead of about 5.
- One player per call by design; no batch mode.

## Iteration 7 — 2026-09-21 (R7: SQLite storage and CSV export)

**What changed**
- Added `bwf_player/store.py`: `HistoryStore` with `save_tournaments`, `save_matches`, `export_csv`, `counts`, and the view `player_match_view` (one row per subject and match: partner, opponents, games as "21-17, 21-19", won). Tables: `players`, `tournaments`, `results`, `matches`, `match_players`, `games`.
- `BwfConfig`: added `history_db_path` and `history_export_dir` (defaults under `data/`); `.gitignore`: `data/`. Earlier-iteration code touched: only these additions and `tests/test_live.py`; no behaviour of R1-R6 changed.
- PRD_master: version 1.3, section 10 data model rewritten as implemented, storage design notes, iteration table.
- CSV export: `results.csv`, `matches.csv`, `games.csv` (UTF-8 with a byte-order mark, so Excel shows accents; empty values blank).

**Why**
- The user asked for the downloaded data to be saved in SQLite plus a CSV export. Keeping the site's own ids as keys and using upserts makes a repeated download harmless, and storing games in the site's own side orientation makes a match identical whichever player it was downloaded for.

**Decisions and corrections to the plan**
- The planned model had `match_players.slot` and `players.slug`; both dropped (no analytical use, no data). `matches.seq` was added because a match needs an order within its event. `winner_side` is nullable because a bye has no winner. `event_id` 0 means "the site lists no event" so it can be part of the primary key.

**What was tested (`test_results/latest.txt`)**
- Offline: **508 passed** (467 before; 41 new in `tests/test_store.py`): new database (tables, view, schema version, foreign keys on), file and folders created, data survives reopening, newer schema / non-database file / uncreatable path refused; Christie's whole year saved (19 tournaments, 19 results, 58 matches, 116 participants, 138 games) and a result, tournament and player row compared exactly; games stored in the site's side orientation for a side-1 and a side-2 match; the view for singles, doubles (partner, two opponents), team-event partners changing per tie, two events at one tournament, bye, walkover and retirement; **saving twice changes nothing** (full table dumps compared); a corrected match replaces its games and players; the same match saved from the opponent's view is unchanged; a later save without category/name does not erase them; matches of an unsaved tournament refused; **a failed save leaves nothing behind** (injected failure); a player without an id skipped with a warning; awkward text (quotes, SQL, accents) stored literally; foreign keys enforced; CSV files (columns, order, values, BOM, accents, replaced on re-export, header-only when empty).
- Live: **14 passed** (1 new): the three most recent real Christie events saved and exported; results, matches and view rows equal the site's totals.

**Findings**
- SQLite correlated subqueries (partner, opponents, ordered game text) work inside the view on the Python-bundled SQLite; no SQL beyond what the standard library provides is needed.
- The view lists only subjects (players with a result in the tournament). Opponents appear in `players` and `match_players`, but only appear as view rows if they were downloaded too.

## Iteration 6 — 2026-09-21 (R5 + R6: matches, partners, opponents, game scores)

**What changed**
- Added `bwf_player/matches.py`: `get_matches(player_id, entry, client=None)` (one request per event entry) returning `EventMatches`, plus pure `parse_matches` and `check_totals`. Each `PlayerMatch` is seen from the subject's side: partner (None in singles), opponents, round, local date, duration, `won`, `status` (played / bye / walkover / retired / disqualified / unknown) and every game's points.
- `check_totals` compares the parsed matches with the totals the tournament list gives for the event (matches, games, points), so a parsing error shows up instead of passing silently.
- `bwf_player/parsing.py`: the three coercion helpers (`to_int`, `to_date`, `clean_text`) moved out of `tournaments.py` so both parsers share them. Earlier-iteration code touched: that move (behaviour unchanged, all 101 R4 tests still pass), additions to `models.py` (`MatchPlayer`, `GameScore`, `PlayerMatch`, `EventMatches`), `__init__.py`, `tests/fakes.py` (matches endpoint, three more players' tournament lists) and `tests/test_live.py`.
- Fixtures: 29 real match responses (all 19 of Christie's events in the window, plus doubles, mixed doubles, team-event doubles, qualification, retirement, bye and walkover cases) and tournament lists for Fajar ALFIAN, Dejan FERDINANSYAH and Apriyani RAHAYU, trimmed from real responses (`tests/fixtures/README.md`).
- PRD_master: version 1.2, endpoint row for `vue-player-tmt-matches` rewritten with what was found, R5/R6 design notes, schema, iteration table, open question 6 resolved.

**Why**
- The user wants the partner, the opponents and the score of every game for each tournament. The match breakdown endpoint has all three. Fixtures come from real responses so the parser is written against what the site actually sends, not against a guess.

**What was tested (`test_results/latest.txt`)**
- Offline: **467 passed** (334 before; 133 new in `tests/test_matches.py`): a full match compared field by field; games oriented correctly when the subject is side 1 or side 2 (including a synthetic test that swaps the sides of one match and gets the same result); singles, men's/women's/mixed doubles, partner found when the subject is listed second, partner changing between team-event ties; a group stage, a qualification plus main draw, the draw-as-object quirk; retirement, walkover and bye; **every one of the 29 real events reproduces the site's totals exactly**; `check_totals` (each of the six totals, missing totals, a dropped match); request parameters (team events use `tmtType=1`); invalid ids make no request; Cloudflare block propagates; parser robustness (unreadable draws and matches, duplicate ids, flat-field fallbacks, unusable winners, every status code, game ordering, unreadable games, 0-0 games, score-text fallback, date and duration edge cases, input not mutated).
- Live: **13 passed** (2 new): Christie's three most recent events and Fajar ALFIAN's two most recent (men's doubles) reproduce the site's totals; singles have no partner and one opponent, doubles have a partner and two opponents; every game in a played match ends at 21 (cap 30) and is won by two.
- Development check on real data: 72 events (215 matches) of five players (Christie, Fajar ALFIAN, Dejan FERDINANSYAH, Apriyani RAHAYU, Aadhya SHINE) parsed with **no disagreement** with the site's totals: 210 played, 3 byes, 1 retirement, 1 walkover.

**Findings**
- The subject is side 1 in some matches and side 2 in others (Christie is side 2 in most, side 1 in the Thomas Cup), so the side must come from the player ids.
- A draw's matches can be an object with gapped keys (`{"2": {...}}`) instead of a list (real mixed-doubles event). Bug avoided because it was found by inspecting real data first; it is now a fixture and a test.
- `match_time_utc` is only the day. Ordering by it and by id put a qualifying QF before the qualifying R16 (both on one day). **Bug found by a test written from real data and fixed:** the order now uses `actualTimeUTC` / `timeUTC` from `match_start_time_details`.
- The site counts a **bye** as a match won in its totals. Byes therefore appear as their own status (`won` is None) and `check_totals` adds them to the wins.
- Team events and group stages have the same match shape as ordinary events; a team-event doubles player's partner changes between ties.
- **Not seen in real data**: a disqualification (`score_status` 3, mapped from the site's own template) and a match still in progress. Handled defensively, untested against real data (PRD section 8, item 6).
- The position label `Final` (Dejan FERDINANSYAH, one event in 2025, 4 wins and 1 loss) also exists next to `2nd`; its exact meaning is not documented by the site. It is stored as the site writes it.
- A bug of my own, caught by the reconciliation run: the first version of the bye check contained control characters instead of a regular-expression word boundary (a quoting slip in a patch script), so byes were reported as played matches. Fixed, and a scan of all `.py`, `.md` and `.json` files for stray control characters found none.

## Iteration 5 — 2026-09-21 (R4: tournaments and results)

**What changed**
- New feature area, PRD section 10 (R4-R7): download the last year's tournaments for one player, with results, partners, opponents and per-game scores, into SQLite plus CSV. This iteration delivers R4 only.
- Added `bwf_player/tournaments.py`: `history_window`, `get_tournaments(player_id, client=None, *, since, until, today, with_categories)` and pure parsers (`parse_tournaments`, `parse_calendar`). Two requests for the default window (one per calendar year), then 1-4 calendar pages for the tournament category.
- `models.py`: added `TournamentEntry` (one row per player, tournament and event) and `TournamentHistory`. `__init__.py` exports them with `get_tournaments` and `history_window`.
- Earlier-iteration code touched: only additions to `models.py`, `__init__.py`, `tests/fakes.py` (two new fake endpoints) and `tests/test_live.py`. No behaviour of R1-R3 changed.
- Fixtures added: `tournaments_*.json` (Christie and Aadhya SHINE, 2025 and 2026) and `calendar_page1..4.json` (the real 326-tournament calendar), trimmed from real responses (see `tests/fixtures/README.md`).
- PRD_master: version 1.1, endpoint table (5 new rows), R4 design notes, schema, iteration plan 5-8, open questions 6-8, section 10.

**Why**
- The user asked for a one-year tournament history per player. Inspecting the site's player page showed it already loads exactly this data through `vue-player-tournaments` and `vue-player-tmt-matches`, so a player-centric download needs about 25-40 requests per player instead of the 35,000+ a loop over the 3,429-player index would need.
- The user clarified the scope: one input player plus that player's opponents, not every player.
- The tournament list has no category, so the calendar endpoint is read (paged only as far as needed) to label each tournament.

**What was tested (`test_results/latest.txt`)**
- Offline: **334 passed** (233 before; 101 new in `tests/test_tournaments.py`): default window 2025-09-21..2026-09-21, 29 February, overlap rule at both edges, real Christie data (19 entries, chronological, one full entry compared field by field, positions `1st/2nd/3rd/QF/R3`, team event without position, categories), request economy (two year requests, calendar stops when everything is found, bounded paging), player with two events at one tournament, no tournaments, 10 malformed ids and no request made, since after until, calendar failure keeps the tournaments, Cloudflare block propagates, de-duplication across years, malformed rows skipped and counted, defensive coercion of counts (negative, boolean, NaN, non-numeric), placeholder positions, calendar parser.
- Live: **11 passed** (2 new): Christie's real window (at least 5 tournaments, all overlapping the window, sorted, event records present, at least one category and one position) and an unknown id.

**Findings**
- The result label is `position` in the site's own words: `1st`, `2nd`, `3rd`, `QF`, `R16`, `R32`, `Qual. R32`, `R3` (finals group stage), and `N/A` for team events (stored as `null`).
- 62 of the 326 calendar tournaments in the window have no category at all, so `category` can legitimately be `null`.
- Corrected a stale statement: PRD risk 4 said the live suite had 8 tests and ran in about 40 s; it was already 9 tests after Iteration 4 and is 11 tests, about 60 s, now.
- Not yet verified (Iteration 6): match shape for team events and group stages (open question 6). Para players are not covered (open question 7).

**Open for the user**
- Resolved on 2026-09-21: the user confirmed that overlapping tournaments count (PRD section 8, item 8).

## Iteration 4 — 2026-09-21 (final notebook, README, full regression)

**What changed**
- Added `bwf_player/lookup.py`: `lookup_player(name, client=None, *, event_id=None)` (search -> profile -> ranking in one call, returning the existing `PlayerResult` model) and `format_result` (text report). Both are exported from `bwf_player`. Profile and ranking are fetched only when the search finds exactly one player.
- Notebook rebuilt as a thin interface (`lookup_player` + `format_result`, no logic of its own): input cell, readable result, JSON result, examples, notes. Committed **with its executed outputs** so it can be read without running. Added `scripts/execute_notebook.py` to refresh the outputs.
- README rewritten as the final user documentation (quick start, example output, layout, tests, limitations).
- PRD: version 1.0, new section 9 **Development procedure** (test, save results, then update documentation, commit, push; documentation is written after testing so its numbers come from the final run).
- Earlier-iteration code touched: `bwf_player/__init__.py` (now also exports `lookup_player`, `format_result`, `RankingEvent`); `pyproject.toml` (the `notebook` extra is now `ipykernel`, `nbclient`, `nbformat` instead of the much heavier `jupyter` meta-package, which hung pip during development). No search, profile or ranking behaviour changed.
- Fixtures: added a real `popular_chong_wei.json` (server-search response, captured from the local cache) and Aadhya SHINE's real entry in the trimmed player index, so the offline suite can run the full lookup for a retired and a sparse-profile player.

**Why**
- The notebook duplicated the orchestration (search, then profile, then ranking) across cells; a package-level function keeps it thin, as the specification requires, and makes the end-to-end path testable offline.
- The user asked that documentation always be updated after testing; this is now a written step of the development procedure.

**What was tested (full regression, `test_results/latest.txt`)**
- Offline: **233 passed** (all iterations; 19 new: 14 for `lookup_player`/`format_result` incl. an exact text snapshot, ambiguous and not-found paths making no profile/ranking requests, event selection, JSON serialisation, Cloudflare block; 5 for the committed notebook).
- Live: **9 passed** (1 new: end-to-end lookup and report; ambiguous name fetches nothing further).
- Notebook executed end to end in a real kernel: 5 code cells, no errors.
- A fresh clone of the repository was installed in a new virtual environment and its offline suite run (result in the iteration report).

**Findings / still open**
- Resolved on 2026-09-21: the user decided that reporting the first ranking event, with the others in `other_events`, is enough (PRD section 8, item 5). The terms-of-service review (item 2 and 9) stays open; the user acknowledged it.
- R1 limitation "Dan Lin" -> "LIN Dan" is documented, not fixed (README, PRD section 8, 1a-d).
- Terms and conditions of bwfbadminton.com remain unreviewed.

## Iteration 3 — 2026-09-21 (R3: ranking)

**What changed**
- Implemented `ranking.get_ranking(player_id, client=None, *, event_id=None)` plus pure parsers (`parse_events`, `parse_current_rank`, `parse_history`, `trailing_run`). Three requests per player: events, current rank, history.
- Earlier-iteration code touched (required by this iteration): `models.PlayerRanking` (Iteration 0 stub, unused until now) was reshaped: `event` is now a `RankingEvent`, added `other_events`, `at_rank_since`, `as_of`; `note` became `notes`; `weeks_source` lost the never-used `"site_reported"` value. `validate_player_id` moved from `profile.py` to `names.py` so R2 and R3 share it (behaviour unchanged; all R2 tests still pass). `tests/fakes.py` gained the ranking endpoints.
- Notebook: added a ranking cell. README: usage. PRD: endpoint table, R3 method, schema, open questions.

**Why**
- **Correction of an earlier assumption.** PRD v0.1-0.3 said the site's `consecutive` value might be the weeks at the current rank. Real data disproved it: it is the streak at the player's best rank (Aadhya SHINE: current 423, `consecutive` says rank 364 / 3 weeks; Lee Chong Wei: rank 1 / 138 weeks). Weeks at current rank are therefore derived from the weekly history; Christie's derived value (4 weeks since 2026-08-25) equals the site's streak, which confirms the counting convention.
- The site's history `results` is a JSON string inside JSON, so it is decoded twice; a malformed history degrades to "weeks unknown" instead of failing the whole request.

**What was tested**
- Offline: 214 tests in total (83 new for R3). Real fixtures: ranked player (rank, weeks, since, as-of, event), player with two events (default, explicit selection, unknown/malformed event id), retired unranked player (`"-"`, no history request), unknown id (empty events), single-row history, exact request parameters, 10 malformed player ids (no request made). Synthetic cases: run boundaries, an earlier equal-rank run not counted, latest rank differing from current, a week without rank ending the run, empty/None/unreadable history, duplicate/odd rows, current-rank placeholders and unrecognised values, unsafe event ids, malformed payloads, Cloudflare block.
- Live: 8 tests in total (2 new): active player (rank, weeks, dates consistent and fresh), retired player (unranked), unknown id. Notebook run end to end for four players.
- Full output: `test_results/latest.txt`.

**Findings**
- Unknown player id and never-ranked player are indistinguishable at the events endpoint.
- R1 limitation found: "Dan Lin" does not find "LIN Dan" (details in PRD section 8, 1a-d). Not changed in this iteration.

## Iteration 2 — 2026-09-21 (R2: personal details)

**What changed**
- Implemented `profile.get_profile(player_id)` (+ pure `parse_profile`) returning nationality, height and playing hand, one request per player to `vue-player-summary`.
- Earlier-iteration code touched: `models.PlayerProfile` (an Iteration 0 stub model, unused until now): `height: str` became `height_cm: float`; added `player_found` and `notes`. `tests/fakes.py` gained a `vue-player-summary` fake. No search/HTTP-client behaviour changed.
- Added `scripts/save_test_results.py` and `test_results/latest.txt` (user request: save the latest test results every iteration).
- Notebook: added a profile cell after the search cell. README: usage and test-results instructions.

**Why**
- Inspecting the real responses showed the site's profile header renders all three fields from `vue-player-summary` (nationality from `country_model.name`, height and hand from `bio_model`), so one request suffices. `vue-player-bio` has height and hand but no nationality, so it was not needed. The site's own template defines hand as `plays` 1 = right, 2 = left, anything else "n/a", so that mapping is not a guess.
- The API answers a **malformed id (`abc`) with an unrelated player** (found by probing). Ids are therefore validated as positive integers before any request, and the returned `id` must equal the requested one.

**What was tested**
- Offline: 131 tests in total (67 new for R2): right- and left-handed players from real fixtures, a real player with nothing listed (all null + notes, request still succeeds), unknown id (`player_found=False`), id validation (17 malformed forms, no request made), response for a different player rejected, malformed payloads, height formats and unusable values (abc, 0, negative, >300, nan, inf, bool, list), unmapped hand values, missing country (falls back to ISO code), missing `bio_model`, Cloudflare block propagates.
- Live: 6 tests passed in total (2 new): Christie (Indonesia, 179 cm, Right), Marin (Spain, 172 cm, Left), Aadhya Shine (nothing listed), unknown id. Notebook cells executed end to end for four sample queries.
- Full output: `test_results/latest.txt`.

**Decisions**
- `height_cm` is a float in centimetres (the site stores `"179.00"`); implausible values (<= 0 or > 300) are treated as unusable.
- Nationality is the country name; the ISO code is used only as a fallback, with a note.

## Iteration 1 — 2026-09-21 (R1: player search)

**What changed**
- Implemented `http_client` (session bootstrap, rate limit, retry/backoff, Cloudflare-block detection, disk cache), `names` (sanitize/normalize/slug) and `search` (hybrid index + server fuzzy search).
- `BwfConfig`: added `index_cache_ttl_seconds`, `max_query_length`, `search_max_tokens`, `search_max_pages`; changed the default User-Agent to a `Mozilla/5.0 (compatible; ...)` form.
- Fixtures added under `tests/fixtures/` (real captured responses); `pytest -m live` smoke tests added.
- Earlier-iteration code touched: `config.py` only (the additions above). No behaviour from Iteration 0 was altered.

**Why**
- Live probing showed the server search is a strict substring match (no typo tolerance) and the only full player list (`vue-h2h-players`) is incomplete and slug-less, so neither source alone satisfies R1. The hybrid approach gets typo/accent/order tolerance from the index and coverage from the server search.
- `WRatio` scoring was replaced with `max(token_sort_ratio, 0.9 * token_set_ratio)` after a test showed it ranked "Christie XU" above "Jonatan CHRISTIE" for the query "christie" purely on name length.

**What was tested**
- Offline (`pytest`): 63 tests. Exact, case, whitespace, accents, reversed order, typo, hyphenated, partial (ambiguous), player missing from index (server fallback), not found, empty/None/non-text, special characters and injection strings, control characters, over-long input, configurable threshold, Cloudflare block propagation, zero-request repeat lookups. HTTP client: bootstrap once, headers, cache hit/expiry/disabled/corrupt, throttling, retry/backoff, `Retry-After`, give-up, block not retried, plain 403 not a block, non-JSON, params never in URL.
- Live (`pytest -m live`): 3 tests passed (exact name, typo + reversed order, player absent from index).

**Follow-up fix (same iteration, found by running the tool live)**
- "Tai Tzu Ying" returned `not_found`: the server stage queried single words (`ying`, `tai`), which return more players than the 2 pages fetched, and the site stores her as "Tzu Ying TAI". The offline fixture was too small to expose this.
- Fix: the server stage now queries contiguous phrases of the query, longest first. Config `search_max_tokens` was renamed `search_max_queries` (default 3; introduced in this iteration, so nothing depended on the old name).
- Tests: the fake server now paginates (30/page) and holds 160 decoy players placed ahead of the real ones, so the old behaviour fails; added a phrase-generation unit test and a live test. Live: Tai Tzu Ying, Carolina Marin and "Yu Fei Chen" (stored as "CHEN Yu Fei") now resolve.
- Totals after the fix: 64 offline tests, 4 live tests, all passing.

**Findings recorded in PRD_master.md**
- `vue-popular-players`: strict substring; `activeTab=0` returns 500. `vue-h2h-players`: ignores `searchKey`, returns 3,429 players, incomplete (Momota, Tai Tzu Ying, Carolina Marin missing). `/player/{id}/` redirects to the canonical slug.
- Known limitation: typos inside single-word partial names are not matched.

## Iteration 0 — 2026-09-21

**What changed**
- Project scaffold: `bwf_player` package (config, models, exceptions, stubs for client/search/profile/ranking), `tests/`, `docs/`, notebook skeleton, `pyproject.toml`, `.gitignore`, `README.md`.
- `PRD_master.md` v0.1: site findings, endpoint inventory, risks, architecture, schema, framework recommendation (no Flask), open questions.

**Why**
- Working agreement requires inspecting the site before coding. Findings changed the plan: the site is a Vue SPA, so the JSON API is used instead of HTML scraping, and Cloudflare's aggressive blocking makes explicit block detection, rate limiting and caching mandatory.

**What was tested**
- Live `curl` investigation: robots.txt, players page, profile page, search endpoint (returned Jonatan Christie `id=73442`). Cloudflare hard-blocked the test IP mid-investigation; bio/ranking endpoints and the ToS page could not be inspected.
- `pytest`: scaffold smoke tests (imports, config validation, model defaults and bounds).

**Decisions**
- Plain `requests` client, no headless-browser fallback (user decision).
- No Flask/API layer.
- Target repo: `github.com/Jayfetra/badminton_data_analysis`.
