# PRD Changelog

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
- Confirm the window rule (tournaments that overlap the window count, not only those that start in it; PRD section 8, item 8).

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
- Awaiting the user: which ranking event(s) to report (PRD section 8, item 5).
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
