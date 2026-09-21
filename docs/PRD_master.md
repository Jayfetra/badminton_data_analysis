# PRD Master — BWF Player Lookup

**Version:** 2.0 (Iteration 8: one-call history download, notebook, README, full regression; R1-R7 complete) · **Last updated:** 2026-09-21

Single source of truth for requirements, architecture decisions, data schema and open questions.

## 1. Goal

Given a badminton player's name, retrieve profile and ranking data from bwfbadminton.com.

| ID | Requirement |
|----|-------------|
| R1 | Fuzzy player search (case, whitespace, accents, reversed order, partial names, minor typos). Configurable threshold. Ambiguous matches return ranked candidates; no match returns a clear "not found" result. Success returns the profile URL. |
| R2 | From the profile: nationality, height, playing hand. Missing field -> `null` plus a note; never fails the whole request. |
| R3 | From the ranking tab: current rank and how long the player has held it. Unranked -> `null` plus a note. |
| R4 | Match history (section 10, added 2026-09-21): the tournaments one player entered in the last year, with the result per event. **Done (Iteration 5).** |
| R5 | For each match: the player's partner and the opponent(s). **Done (Iteration 6).** |
| R6 | For each match: round, date, outcome, status and the points of every game. **Done (Iteration 6).** |
| R7 | Save everything to SQLite (re-runnable) and export CSV. **Done (Iteration 7).** |

R4-R7 are combined in one call, `download_player_history(name or id)` (Iteration 8), also available as `scripts/download_history.py` and in the notebook (section 4).

Out of scope: anything not listed above.

## 2. Site investigation findings (2026-09-21)

Method: `curl` with a browser User-Agent, inspecting page source and the inline Vue code.

- **Rendering model.** bwfbadminton.com is WordPress plus a Vue.js SPA (`<div id="app">`). Player list and profile pages contain **no server-rendered player data**; content is fetched client-side from `https://extranet-lv.bwfbadminton.com/api/vue-*`. HTML scraping is not viable without a headless browser, so the JSON API is used.
- **robots.txt** (bwfbadminton.com) disallows only `/24-live-blog/` and `/terms-and-conditions-plain-text/`. `/players/` and `/player/*` are not disallowed. The API host's robots.txt could not be read (blocked, see risks).
- **Terms & Conditions: NOT verified.** The rendered `/terms-and-conditions/` page returned a Cloudflare challenge after our test IP was blocked. robots.txt disallowing only the *plain-text* ToS variant is a weak signal, not evidence either way. Scraping may be discouraged; treat this as an open compliance item (section 8).
- **Undocumented API.** The endpoints below are the site's own front-end API, not a published public API. They can change or be restricted without notice.

### Endpoints (base `https://extranet-lv.bwfbadminton.com/api/`)

| Endpoint | Params | Use | Status |
|----------|--------|-----|--------|
| `vue-popular-players` | `searchKey`, `activeTab=1`, `page` | R1 server search. Returns `results[]` (`id`, `slug`, `name_display`, `country_model`, ...) and `pagination` (30 per page, `next_page_url`). **Strict, case-insensitive substring match on `name_display`**: "cristie" returns 0, "tai tzu" returns 0 (site stores "Tzu Ying TAI"). Empty `searchKey` pages through all players. `activeTab=0` returns HTTP 500. | Used (Iteration 1) |
| `vue-h2h-players` | `searchKey` (ignored), `drawCount`, `drawTab` | R1 index. Returns **every** player as `{value: id, text: "Given FAMILY"}` in one response (3,429 entries, ~130 KB), regardless of `searchKey`. No slug or country. **Incomplete**: e.g. Kento MOMOTA and Tai Tzu Ying are absent. | Used (Iteration 1) |
| `vue-player-summary` | `playerId`, `drawCount`, `isPara=false` | **R2 source.** `results` holds `id`, `name_display`, `nationality` (ISO code), `country_model.name`, `bio_model.height` (cm, e.g. `"179.00"`) and `bio_model.plays` (1 = right, 2 = left; the site shows anything else as "n/a"). An unknown id returns `results: {}`. **A malformed id (`abc`) returns an unrelated player**, so ids are validated and the returned id is checked. | Used (Iteration 2) |
| `vue-player-bio` | `playerId`, `activeTab=5` | Returns `height` (`"179"`), `hand` (`"R"`/`"L"`), `age`, `current_residence`, ... but **no nationality**. Redundant with the summary endpoint for R2. | Inspected, not used |
| `vue-player-ranking-events` | `playerId`, `activeTab=4`, `isPara=false` | R3. `results` is an object keyed by event id: `{"6-0": {"id": "6-0", "name": "MEN'S SINGLES", "partner_id": 0}}`. A player can have several (Aadhya SHINE: `7-0` women's singles, `9-90070` "WOMEN'S DOUBLES (Nanda GHOSH)"). An unknown id returns `results: []`, indistinguishable from a never-ranked player. | Used (Iteration 3) |
| `vue-player-ranking-current` | `rankingEvent`, `playerId`, `isPara=false` | R3 current rank: `{"results": 1}`. No current rank (retired player) returns `{"results": "-"}`. | Used (Iteration 3) |
| `vue-player-ranking-history` | `activeTab=4`, `rankingEvent`, `playerId`, `isPara=false` | R3. `results` is a **JSON string** (double-encoded) of weekly rows `{"date": "2026-09-15", "value_1": 1}`; `value_1` is the world rank (the chart plots it as the world series), `value_2` the World Tour series. Also returns `consecutive` (see below). | Used (Iteration 3) |
| `vue-player-ranking-highest` | `rankingEvent`, `playerId`, `isPara=false` | `{"rank", "date", "total"}`: best rank ever, its latest date, total weeks at it. Not needed for R3. | Inspected, not used |
| `vue-player-tournaments` | `playerId`, `tmtYear`, `activeTab=3`, `isPara=false`, `drawCount`, `searchKey`, `locale` | **R4 source.** `results` is a list, one item per tournament the player entered in that calendar year (Christie: 18 in 2025, 12 in 2026). Item: `tournament_id`, `date`, `location`, `tmt_url`, `tournament_model` (`name`, `start_date`, `end_date`, `type_id`: 0 for every individual tournament seen, 1 for the two team events seen (Sudirman Cup, Thomas & Uber Cup), `country_model`, plus about 250 unused fields) and `draws[]`, one per event entered: `name` (MS, WD, ...), `event_id`, **`position`** (the result: `1st`, `2nd`, `3rd`, `QF`, `R16`, `R32`, `R3` for a finals group stage, `Qual. R32`; `N/A` for team events), `match_win/lose/count`, `game_win/lose/count`, `score_player`, `score_opponent`. An unknown id yields no tournaments (checked live with id 999999999). | Used (Iteration 5) |
| `vue-tournaments-search` | `startDate`, `endDate`, `page`, `perPage`, `drawCount`, `activeTab=1` | The site calendar. `results.data[]` with `id`, `name`, `start_date`, `end_date`, `location`, `country`, `category` ("HSBC BWF World Tour Super 750"); `results.last_page`. For 2025-09-21..2026-09-21: 326 tournaments, sorted by start date, 100 per page. **62 of them have no `category` key.** Used only to add the category to R4 entries. | Used (Iteration 5) |
| `vue-player-tmt-matches` | `playerId`, `tmtId`, `tmtType` (= `tournament_model.type_id`), `eventId` (= draw `event_id`), `activeTab=3`, `isPara=false`, `drawCount`, `locale` | **R5/R6 source.** `results` is `{draw_id: matches}`: one draw for a knockout event, several when the event has a qualification and a main draw, or a group stage and a knockout. **A draw's matches are usually a list but can be an object with gapped keys (`{"2": {...}}`)**, seen on a real mixed-doubles event. Per match: `id`, `round_name`, `draw_name` (`MS`, `MS - Group A`, `XD - Qualification`, `Thomas Cup - Group D`), `winner` (side 1 or 2), `player_win`, `status_name`, `score_status`, `t1p1..t1p2_player_model` and `t2p1..t2p2_player_model` (id, name, slug; `null` for an empty slot), `t*_country` (ISO code), **`match_set_model[]`** = `{ordering, team1, team2}` (points per game), the HTML strings `team1Score`/`team2Score`, `result_team1/2` (games won), `duration` (minutes) and `match_start_time_details` (a JSON *string* with `dateLocal`, `dateUTC`, `timeUTC`, `actualTimeUTC`). `match_time_utc` is only the day, so it cannot order a day's rounds. **The subject is side 1 in some matches and side 2 in others**, so the side is found from the player ids. Team events (Sudirman, Thomas & Uber Cup) use the same shape, one row per tie, with `tmtType=1`. | Used (Iteration 6) |
| `vue-player-tmt-years` | `playerId`, `activeTab`, `isPara` | Years with results (`[{"year": 2026}, ...]`). Not needed: the years come from the requested window. | Inspected, not used |
| `vue-tournament-matches` | `tmtId`, `tmtTab`, `tmtType`, `courtCode`, `eventCode`, `hideTeamMatches`, `isPara`, `searchKey` | All matches of a tournament (the tournament page's results tab). Returned `results: null` for the parameter values tried (`tmtTab` = `matches` and `match`); the page also holds a `selectedDate`, so it is probably per day. Not needed for the per-player design. | Inspected, parked |

**Profile URL pattern:** `https://bwfbadminton.com/player/{id}/{slug}` (`id`/`slug` from the search result; URL-encode when building).

**R3 "time at rank": derived from the history, not read from the site.** The history response includes a `consecutive` block (`{"rank", "streak", "start_date", "end_date"}`, shown on the site as "Consecutive Weeks"). Iteration 0 assumed it was the weeks at the *current* rank. **That was wrong**, found by comparing players: for Christie it reads rank 1 / 4 weeks (coincidentally his current rank), but for Aadhya SHINE (current 423) it reads rank 364 / 3 weeks, and for the retired Lee Chong Wei rank 1 / 138 weeks. It is the streak at the player's *best* rank (the site shows it next to "Rank Highest" and "Total Weeks"). So `weeks_at_current_rank` is derived (`weeks_source = "derived_from_history"`): the number of consecutive weekly ranking lists, ending with the latest, that show the current rank. For Christie this gives 4 weeks since 2026-08-25, matching the site's own streak, which validates the row-counting convention.

**Access requirements.** API calls need a `laravel_session` cookie (obtained by first requesting any bwfbadminton.com page) and a `Referer` header. Without the cookie the API returned 403.

## 3. Risks

1. **Cloudflare bot protection (high).** After roughly 15 requests in a few minutes, Cloudflare **hard-blocked** the test IP site-wide ("Sorry, you have been blocked"), even for plain pages. Consequences for the design:
   - A block is detected explicitly and is **never retried**; the client raises `BlockedByCloudflareError` with an actionable message.
   - Rate limiting (default 2.5 s between requests) and on-disk caching are required, not optional.
   - Decision (user, 2026-09-21): plain `requests` client, no headless-browser fallback. The risk is documented, not engineered around. Reconsider if blocks prove persistent.
2. **ToS unverified (medium).** See section 2.
3. **Unofficial API (medium).** Field names and endpoints may change. Parsers are isolated in their own modules and tested against saved fixtures so drift is easy to spot.
4. **Live testing.** The block observed in Iteration 0 lifted within a day. Since then the live smoke suite (15 tests after Iteration 8, about 2 minutes; earlier versions of this line said 8 tests / 40 s, which had already gone stale at 9 tests in Iteration 4, then 11 in Iteration 5; requests are 2.5 s apart, custom `Mozilla/5.0 (compatible; bwf-player-lookup/...)` User-Agent) and repeated notebook runs have caused no block. Run the live suite sparingly.

5. **Request volume of the history download (medium).** A lookup costs about 5 requests once the index is cached; a history download costs about 25-40 (two years, up to four calendar pages, one per event entered; a doubles player entering several events per tournament needs more). The pacing (2.5 s), the cache and the stop-on-block behaviour are the mitigations. It is one player per call on purpose; a loop over many players is not supported and would raise the Cloudflare and terms-of-service risks above.

## 4. Architecture

Notebook is a thin interface over the `bwf_player` package.

```
bwf_player/
  config.py       BwfConfig (pydantic): thresholds, rate limit, cache, URLs, timeouts
  exceptions.py   BwfClientError, BlockedByCloudflareError, InvalidInputError
  models.py       PlayerCandidate, SearchResult, PlayerProfile, PlayerRanking, PlayerResult, TournamentEntry, TournamentHistory, PlayerMatch, GameScore, MatchPlayer, EventMatches, HistorySummary
  http_client.py  session bootstrap, rate limit, retry/backoff, disk cache, block detection
  names.py        query sanitizing, name normalization, slug derivation, player-id validation
  search.py       R1 (Iteration 1)
  profile.py      R2 (Iteration 2)
  ranking.py      R3 (Iteration 3)
  lookup.py       lookup_player (search -> profile -> ranking) and format_result (Iteration 4)
  tournaments.py  R4: history_window, get_tournaments (tournaments and results in a date window) (Iteration 5)
  matches.py      R5/R6: get_matches (partner, opponents, per-game scores of one event), check_totals (Iteration 6)
  parsing.py      to_int, to_date, clean_text: defensive coercion shared by the parsers
  history.py      download_player_history (search -> tournaments -> matches -> store -> export) and format_history (Iteration 8)
  store.py        R7: HistoryStore (SQLite tables, player_match_view, CSV export) (Iteration 7)
notebook.ipynb    thin interface over the package; committed with its executed outputs
tests/            pytest; offline unit tests on saved fixtures; @pytest.mark.live smoke tests
scripts/          download_history.py (command line), save_test_results.py (both suites -> test_results/latest.txt), execute_notebook.py (runs notebook.ipynb, saves outputs)
test_results/     latest.txt: full output of the most recent test run (overwritten each iteration)
```

### Framework recommendation

**No Flask, no HTTP API layer.** The deliverable is a notebook-driven, on-demand lookup, so a web server adds deployment and security surface with no consumer. A plain importable package plus a notebook is the leanest option. If an API is wanted later, add a thin optional FastAPI layer over the same pydantic models (validation and docs for free). That is out of scope unless requested.

### Design notes

- **Search algorithm (R1, implemented).**
  1. *Sanitize* (`names.sanitize_query`): NFKC, control characters to spaces, whitespace collapsed, max 100 chars. Bad input (non-text, empty, too long, no letters/digits) returns a `not_found` result with a message; it never raises.
  2. *Normalize* (`names.normalize_name`): casefold, strip accents (plus o-slash, ae, ss, l-stroke, d-stroke...), punctuation to spaces.
  3. *Index stage*: fetch `vue-h2h-players` once (cached 7 days), score every name locally.
  4. *Server stage*: only if no single index name scores 100, query `vue-popular-players` with contiguous word sequences of the query, longest first (`tai tzu ying`, then `tzu ying`, then `tai tzu`; max 3 queries x 2 pages), stopping as soon as a confident match exists. Phrases, not single words: a common word such as "ying" returns more players than we page through, and the server matches the site's word order ("Tzu Ying TAI"), not the user's. Results are merged by player id; server data (real slug, country) wins.
  5. *Decide*: keep candidates scoring at least the threshold (default 85). None -> `not_found` (message names the closest candidate). One, or a lead of at least the margin (default 5) -> `found`. Otherwise -> `ambiguous` with up to 5 ranked candidates.
- **Scoring**: `max(token_sort_ratio, 0.9 * token_set_ratio)` from rapidfuzz on normalized names. Same words in any order = 100 (so reversed names need no special code); "jonathan cristie" vs "Jonatan CHRISTIE" = 94; a partial name ("christie", "lee") = a flat 90 for every player containing it, so partial queries are `ambiguous` by design. `WRatio` was rejected because it scores shorter names higher for the same partial query.
- **Profile URL**: `https://bwfbadminton.com/player/{id}/{slug}`. The slug comes from the server when available, otherwise it is derived from the name (`Jonatan CHRISTIE` -> `jonatan-christie`). The id is authoritative: the site 302-redirects `/player/{id}/` and `/player/{id}/<any-slug>` to the canonical URL.
- **Request economy**: a repeat lookup of a known player costs zero requests (index + results cached). A first-ever lookup costs one session bootstrap plus the index; players missing from the index cost 1-6 more (up to 3 phrases x 2 pages).
- **Personal details (R2, implemented).** One request per player to `vue-player-summary`, the same source the site's profile header renders. `profile.get_profile(player_id)`:
  - *Input*: `player_id` must be a positive integer of at most 10 ASCII digits (`int` or `str`); anything else raises `InvalidInputError` **before any request**, because the API answers a malformed id with an unrelated player. The returned `id` must also equal the requested id, otherwise `BwfClientError`.
  - *Nationality*: `country_model.name` ("Indonesia"); falls back to the ISO code (`INA`) with a note if there is no country name.
  - *Height*: parsed to cm (float). `null`/blank means "not listed"; a value that is not a number, not finite, `<= 0` or `> 300` becomes `null` with an "unusable value" note.
  - *Hand*: `1` -> `Right`, `2` -> `Left` (the site's own mapping); any other value -> `null` with a note.
  - *Missing data*: each unlisted field is `null`, named in `missing_fields`, and explained in `notes`; the other fields are still returned. A player the site does not know returns `player_found=False` (no exception). Verified on a real player with nothing listed (Aadhya SHINE).
- **Ranking (R3, implemented).** `ranking.get_ranking(player_id, client=None, *, event_id=None)`; 3 requests per player (events, current, history), all cached 24 h.
  - *Event*: the first event the site lists (what the site's own ranking tab selects; for most players men's/women's singles), unless `event_id` is given. The others come back in `other_events`, so nothing is hidden. An unknown or malformed `event_id` raises `InvalidInputError` listing the valid ones (event ids are also regex-validated before being sent).
  - *Current rank*: `results` as a positive int. `"-"`, blank, `null`, `0` -> not ranked; any other value -> not ranked with an "unrecognised" note.
  - *Unranked* (no events, or no current rank) is a normal result: `is_ranked=False`, `current_rank=None`, and a note. When there is no current rank the history is not requested.
  - *Weeks at rank*: trailing run of the current rank in the weekly history (row count, like the site's own streak). It is `None` with a note if the history is unreadable/empty, or if its latest row shows a different rank than the current one (the history lags). A week without a usable rank ends the run. `at_rank_since` is the first week of the run and `as_of` the latest list, so callers can also compute calendar time. Gaps in the weekly series (ranking freezes, e.g. 2020) are not counted as weeks.
  - *Input*: same `validate_player_id` as R2 (moved to `names.py` so both share it).
- **End-to-end (Iteration 4).** `lookup_player(name, client=None, *, event_id=None)` returns a `PlayerResult` (search, profile, ranking, fetched_at). Profile and ranking are fetched only when the search finds exactly one player; an ambiguous or unknown name makes no further requests. `format_result` renders the text report used by the notebook (missing values as `null`, notes listed at the end). Network failures propagate as `BwfClientError` / `BlockedByCloudflareError`; the notebook catches them and prints a clear message.
- **Tournaments and results (R4, implemented in Iteration 5).** `tournaments.get_tournaments(player_id, client=None, *, since=None, until=None, today=None, with_categories=True)` returns a `TournamentHistory`.
  - *Window*: default is one year back from today to today (`history_window`; 29 February moves to 28 February in a year without one). A tournament is included when its dates **overlap** the window (inclusive at both ends), so China Masters 2025 (16-21 Sep 2025) is in a window starting 21 Sep 2025.
  - *Requests*: one `vue-player-tournaments` request per calendar year the window touches (2 for the default window), then the calendar for categories: pages of 100 in date order, stopping as soon as every needed tournament has been seen (1 to 4 requests; Christie needs 4 because of September 2026). The years endpoint is not called.
  - *One entry per event*: a player who enters women's singles and doubles at one tournament has two entries (same `tournament_id`, different `event_id`). A tournament the site lists with no event still yields an entry, with the event fields `null`, so it is never lost silently. Entries are de-duplicated on (tournament, event) and sorted oldest first.
  - *Result*: `position` is the site's own label. `N/A` (team events) and blank become `null`. Match, game and point totals are copied as the site's summary and are what Iteration 6 reconciles the parsed matches against.
  - *Category*: from the calendar, whitespace-normalised. Where the calendar has no category (62 of 326 tournaments in the window) or lacks the tournament, it is `null` with a note; if the calendar request fails (other than a Cloudflare block, which always propagates) the tournaments are still returned with a note.
  - *Robustness*: a row without a usable id, name or dates is skipped and counted in the notes. Counts are coerced defensively (negative, boolean, NaN and non-numeric values become `null`). Malformed payloads raise `BwfClientError`. Same `validate_player_id` as R2/R3. No player at all in the window is a normal result (empty list plus a note).
- **Matches (R5 + R6, implemented in Iteration 6).** `matches.get_matches(player_id, entry, client=None)` takes a `TournamentEntry` from R4 and makes one request (none if the entry has no event id), returning `EventMatches` (matches, `totals_agree`, notes).
  - *Perspective*: the subject's side is found from the player ids (`t1p1/t1p2/t2p1/t2p2_player_model`, falling back to the flat `team*_player*_id` fields). A match that names the subject on neither or both sides is skipped and counted in the notes. `partner` is the other member of the subject's pair (None in singles, and per tie in team events); `opponents` is the other side. Games are oriented so `player_points` is the subject's side; `side` (1 or 2) is kept because it is what the database stores.
  - *Games*: from `match_set_model`, sorted by `ordering`; unreadable games are left out and noted; 0-0 games (never played) are dropped. Only if the structured list is missing are the `<span>` score texts used (noted). The parsed games are also checked against the recorded game result (`result_team1/2`) and a disagreement is noted (skipped for retirements).
  - *Status*: `played`, `bye`, `walkover`, `retired`, `disqualified` or `unknown`. `score_status` 0/1/2/3 is read as played/walkover/retired/disqualified, the mapping in the site's own match template; codes 1 and 2 were confirmed on real matches, **3 (disqualified) never appeared in the data seen**. Anything else is `unknown`. A **bye** is a match with no opponent whose score text is "BYE": `won` is None, no games, and it is not a played match (filter `status == "played"` for those). A **walkover** has no games and a result. A **retirement** keeps the points of the game in progress.
  - *Order*: by real start time (`actualTimeUTC`, else the scheduled `timeUTC`, else `match_time_utc`), then id. Ordering by `match_time_utc` and id was wrong on a real event (two qualifying rounds on one day).
  - *Date*: the local date from `match_start_time_details`, else `match_time`.
  - *Reconciliation* (`check_totals`): matches won/lost, games won/lost and points for/against, as computed from the parsed matches, must equal the totals the tournament list gives for the event. **The site counts a bye as a match won**, so byes are added to the wins for this comparison. A difference sets `totals_agree=False` and is listed in the notes; an entry without totals gives None.
  - *Robustness*: malformed payloads raise `BwfClientError`; an unreadable draw or match is skipped and counted; the same match id in two draws is kept once; names have whitespace collapsed (the site has double spaces, e.g. "Mohamed  Abderrahime BELARBI").
- **Storage (R7, implemented in Iteration 7).** `store.HistoryStore(path=":memory:")` (a context manager) with `save_tournaments(history, *, player_name, player_country)`, `save_matches(event_matches)`, `export_csv(directory)`, `counts()` and `connection` for read queries. Data model: section 10.
  - *Re-runnable*: every table is keyed by the site's ids and written with an upsert, so a second download of the same player changes nothing (tested by comparing complete table dumps). A corrected match replaces its players and games, so no stale rows survive; the same match saved from the opponent's point of view is identical.
  - *Atomic*: each `save_*` call is one transaction; a failure part-way leaves the database as it was (tested with an injected failure).
  - *Order of saving*: tournaments first; `save_matches` for a tournament that is not stored raises `InvalidInputError` and stores nothing. A participant the site gives no id cannot be stored and is skipped with a log warning.
  - *Safety*: every value goes in through bound parameters (a tournament called `O'Brien Open"; DROP TABLE players; --` is stored literally); foreign keys are on; a file that is not a database, a path that cannot be created and a newer schema version each raise `BwfClientError`.
  - *Config*: `BwfConfig.history_db_path` (`data/bwf_history.sqlite`) and `history_export_dir` (`data/export`) hold the defaults; `data/` is git-ignored. `download_player_history` reads them when no path is given.
- **End-to-end history (Iteration 8).** `history.download_player_history(player, client=None, *, since, until, today, db_path, export_dir, export, progress)` returns a `HistorySummary`.
  - *Input*: a name (searched with the R1 search; a string of digits or an `int` is a player id and skips the search). A name that is ambiguous or unknown returns the search result with a note, makes no history request and creates no database. A malformed id raises `InvalidInputError` before any request.
  - *Flow*: `get_tournaments` -> `HistoryStore.save_tournaments` -> for each entry `get_matches` -> `save_matches` (so each event is saved as soon as it is downloaded) -> `export_csv`. No tournament in the window: nothing is saved and no database is created.
  - *Failure*: the first failed request propagates (`BlockedByCloudflareError` must stop the run; a network failure would otherwise cost minutes of retries per event). What was saved before the failure stays, and calling again continues from the HTTP cache and the upserts. Tested: a block on the fifth match request, then a complete re-run, gives a database identical to an uninterrupted run.
  - *Verification in the result*: `all_totals_agree` and `events_disagreeing` report whether the parsed matches reproduce the site's totals for each event; each disagreement is also written in `notes`. What was found is still saved when there is a disagreement.
  - *Output*: `format_history(summary, matches=True)` gives the text report; `scripts/download_history.py` prints it and returns 0 (downloaded), 2 (no single player found, or nothing in the window) or 1 (invalid input or the download failed).
- **Input safety.** Names are sanitized as above and passed to the API only via `requests` `params` (encoded), never string-concatenated into URLs. Server queries use only the normalized (alphanumeric) tokens. Player ids/slugs are URL-quoted when building profile URLs.
- **No secrets** are used or stored. The session cookie is fetched at runtime and kept in memory.

## 5. Data schema (v2.0)

See `bwf_player/models.py`.

- `PlayerCandidate`: `player_id`, `slug`, `name`, `country`, `profile_url`, `score` (0-100)
- `SearchResult`: `query`, `status` (`found` | `ambiguous` | `not_found`), `best_match`, `candidates`, `message`
- `PlayerProfile`: `player_id`, `player_found`, `name`, `nationality` (country name), `height_cm` (float), `playing_hand` (`Right` | `Left` | null), `missing_fields`, `notes`
- `RankingEvent`: `id` (e.g. `6-0`), `name`
- `PlayerRanking`: `player_id`, `event`, `other_events`, `is_ranked`, `current_rank`, `weeks_at_current_rank`, `at_rank_since`, `as_of`, `weeks_source`, `notes`
- `PlayerResult`: `search`, `profile`, `ranking`, `fetched_at`
- `TournamentEntry` (R4): `tournament_id`, `name`, `category`, `start_date`, `end_date`, `location`, `country`, `type_id`, `url`, `event_code`, `event_id`, `position`, `matches_won`, `matches_lost`, `games_won`, `games_lost`, `points_for`, `points_against`
- `TournamentHistory` (R4): `player_id`, `since`, `until`, `entries`, `notes`
- `MatchPlayer` (R5): `player_id`, `name`, `country` (ISO code)
- `GameScore` (R6): `game_no`, `player_points`, `opponent_points` (subject's side first)
- `PlayerMatch` (R5, R6): `match_id`, `tournament_id`, `draw_id`, `draw_name`, `round`, `match_date`, `duration_min`, `side`, `player`, `partner`, `opponents`, `won`, `status`, `games`, `notes`
- `EventMatches` (R5, R6): `tournament_id`, `event_code`, `event_id`, `matches`, `totals_agree`, `notes`
- `HistorySummary` (Iteration 8): `search`, `player_id`, `player_name`, `since`, `until`, `tournaments`, `events`, `matches`, `matches_by_status`, `games`, `events_checked`, `events_disagreeing`, `all_totals_agree`, `database`, `csv_files`, `history`, `event_matches`, `notes`

BWF raw field names for bio/ranking are unconfirmed; models are the package's own schema and parsers map onto them.

## 6. Testing strategy

pytest. Offline unit tests use saved JSON fixtures in `tests/fixtures/`. Live smoke tests are marked `@pytest.mark.live` and excluded by default (`pytest -m live` to run). `python scripts/save_test_results.py` runs both suites and saves the full output to `test_results/latest.txt` (overwritten every iteration; `--no-live` skips the live suite). Required edge cases: exact, fuzzy, ambiguous, not found, empty input, special characters, missing fields, unranked player. Iteration 5 adds `tests/test_tournaments.py` and two live tests; Iteration 6 adds `tests/test_matches.py` (real fixtures for singles, doubles, mixed, team events, group stage, qualification, retirement, walkover and bye) and two live tests; Iteration 7 adds `tests/test_store.py` (database, view and CSV on real fixtures) and one live test; Iteration 8 adds `tests/test_history.py` (the whole download on fixtures, including a Cloudflare block half way followed by a resume, and an event that does not add up), `tests/test_script.py` (the command line) and one live end-to-end test (the second run must make no request). `tests/test_notebook.py` guards the committed notebook: valid, every code cell executed without errors, only uses the package, shows the main result, contains no secrets or local paths.

## 7. Iteration plan

| Iteration | Scope | Status |
|-----------|-------|--------|
| 0 | Scaffold, investigation, PRD v0.1, first commit | Done |
| 1 | R1 search + tests | Done |
| 2 | R2 profile + tests | Done |
| 3 | R3 ranking + tests | Done |
| 4 | Notebook, README, full regression | Done |
| 5 | R4: tournaments in a one-year window and the result per event | Done |
| 6 | R5 + R6: partners, opponents, per-game scores; reconciliation with the R4 totals | Done |
| 7 | R7: SQLite storage (re-runnable) and CSV export | Done |
| 8 | End-to-end `download_player_history`, command line, notebook, README, full regression | Done |

## 8. Open questions

1. ~~Search coverage~~ **Resolved in Iteration 1.** `vue-popular-players` searches the whole database but is a strict substring match; `vue-h2h-players` is a complete-looking but incomplete index. Hybrid design in section 4.
1a. **Known limitations of R1.** (a) A typo inside a *single-word* partial name ("cristie", "jonathan") is not matched; typo tolerance applies to full names. (b) A typo'd query for a player absent from the index (Momota, Tai Tzu Ying, Carolina Marin) will not be found, because the server search is strict. (c) If a typo'd query closely resembles a different indexed player, that player can be returned as `found`. (d) A reversed query for a player who is missing from the index and whose name parts are common fails: "Dan Lin" does not find "LIN Dan" (found while testing R3), because the server is queried with the phrase as typed and then with single common words that return more players than are paged. Rotating the words ("lin dan") would fix it; not done, to keep R1 unchanged in this iteration. Mitigation if any of these matter: page the full player list once (about 100+ requests at 30 per page; not done, given the block risk).
2. **ToS.** Read `/terms-and-conditions/` from an unblocked network and record the scraping stance here.
3. ~~Bio field names~~ **Resolved in Iteration 2** (see `vue-player-summary`). **Ranking field names** also **resolved in Iteration 3** (see the ranking endpoints; real responses are saved as fixtures).
4. ~~Height format~~ **Resolved:** centimetres, returned as `height_cm` (float).
5. **Which ranking event (awaiting your decision).** Implemented as: the first event the site lists, with the others in `other_events` and selectable via `event_id`. Confirm this is what you want, or whether the result should contain all events (2 more requests per extra event).
6. ~~Team events and group stages~~ **Resolved in Iteration 6.** Team events and group stages use the same match shape as ordinary events (Thomas Cup ties, a finals group stage, qualification plus main draw, all fixtures). New unusual cases found and handled: a draw whose matches are an object instead of a list, byes, and start times that must come from `match_start_time_details`. Not seen in the data: a disqualification (`score_status` 3) and a match still in progress (`match_state` other than `F`); both are handled defensively (status `unknown` or no usable winner, with a note) but untested against real data.
7. **Para-badminton (open, limitation).** Every request sends `isPara=false`, so a para player's tournaments are not covered. Supporting them needs the para variants of the same endpoints; not planned.
8. **Window rule (decided by the assistant, still awaiting your confirmation).** A tournament counts when its dates overlap the window, not only when it starts inside it. Effect on the default window (2025-09-21 to 2026-09-21): China Masters 2025 (16-21 Sep 2025) is included. Say so if you want start-date-in-window instead.

9. **Terms of service (still open, now more relevant).** The history download makes 25-40 requests per player rather than about 5. The site's terms and conditions have still not been read from an unblocked network (item 2). Please check them before using the tool beyond personal research.

## 9. Development procedure

Every iteration follows these steps, in order. The order matters: documentation is written **after** testing, so that every number and claim in it comes from the final run.

1. **Understand.** Read the requirement; inspect the real site or data first; ask the user when something is ambiguous instead of guessing.
2. **Implement in small steps.** Keep earlier functionality unchanged unless the iteration requires it; if it does, record the change in `PRD_changelog.md`. Validate all input; never build URLs from raw input.
3. **Test.** Add pytest tests with the code: offline unit tests on saved real responses (`tests/fixtures/`), edge cases, and a few `@pytest.mark.live` smoke tests. Fix failures at the cause. Run the notebook if it changed (`python scripts/execute_notebook.py`).
4. **Save the results.** `python scripts/save_test_results.py` runs the offline and live suites and overwrites `test_results/latest.txt` (only the latest result is kept).
5. **Update the documentation (mandatory, after all testing).** Using the final test results:
   - `docs/PRD_master.md`: version, findings and endpoint table, schema, design notes, iteration table, open questions (mark resolved ones).
   - `docs/PRD_changelog.md`: one entry (date, what changed, why, what was tested, findings); test counts must match `test_results/latest.txt`.
   - `README.md`: usage, layout and limitations.
   - Check for statements the change made stale (search for "Pending", "not yet", request or test counts, superseded assumptions) and correct them; state corrections openly.
6. **Commit and push to `main`** with a clear message (e.g. `feat(search): fuzzy player lookup`), then report: summary, files changed, test results, commit hash and repo link, open questions and risks.

## 10. Match history feature (R4-R7)

Added 2026-09-21. Given one player, download the tournaments they entered in the last year and, for each, the result, the partner and the score of every game.

### Decisions (user, 2026-09-21)

- **Scope**: one input player (e.g. "Jonatan Christie") plus everyone that player faced or played with. It is *not* a download of every player. Reason for the clarification: the first request read "for all player".
- **Tournaments**: all the player entered, whatever the category; the category is saved with each tournament so analysis can filter later. (The user's answer "all 326 calendar tournaments" applies to the category lookup: the whole calendar is read only to label the player's tournaments.)
- **Storage**: SQLite database plus CSV export.
- **Window**: today minus one year to today (2025-09-21 to 2026-09-21 when written), overlap rule (section 8, item 8).

### Method

Player-centric, using the endpoints the site's own player "Tournaments" tab uses: `vue-player-tournaments` (tournaments and results, per calendar year) then `vue-player-tmt-matches` (matches with partners, opponents and per-game points, one request per event). About 25-40 requests per player, 1-2 minutes at the 2.5 s pace, and cached afterwards. A tournament-centric route (every match of every tournament, once) would be cheaper for many players, but `vue-tournament-matches` did not answer with the parameters tried, and it is not needed for one player.

**Built-in cross-check.** Every event in the tournament list carries the site's own totals (`match_win/lose`, `game_win/lose`, points). The parsed matches must add up to them (`check_totals`); a mismatch is reported, so the parser is validated on live data rather than trusted. During Iteration 6 this held for 72 real events (215 matches) of five players; 29 of those events are saved as fixtures and re-checked by every offline run.

### Data model (SQLite, `data/bwf_history.sqlite`, git-ignored; implemented in Iteration 7)

Everything is keyed by the site's own ids, so saving the same data again replaces it instead of duplicating it. `PRAGMA user_version` holds the schema version (1); a database from a newer version is refused.

- `players(player_id PK, name, country)`: the subject, partners and opponents. A later save that lacks a name or country never blanks the stored one.
- `tournaments(tournament_id PK, name, category, start_date, end_date, location, country, type_id, url)`. A later save without a category keeps the stored one.
- `results(player_id, tournament_id, event_id, event_code, position, matches_won, matches_lost, games_won, games_lost, points_for, points_against)`, PK (player, tournament, event). `event_id` 0 means the site lists no event for that tournament.
- `matches(match_id PK, tournament_id, event_id, event_code, seq, draw_id, draw_name, round, match_date, duration_min, status, winner_side)`. `status` is one of played, bye, walkover, retired, disqualified, unknown. `winner_side` is 1 or 2, NULL for a bye or an unknown winner. `seq` is the match's position within its event, in playing order.
- `match_players(match_id, player_id, side 1|2)`: who was on which side. Partners are on the subject's side, opponents on the other, so "played with" and "played against" are the same side / other side question.
- `games(match_id, game_no, side1_points, side2_points)`: the site's own orientation (side 1 first), so a match stored from either player's point of view is identical.
- View `player_match_view`: one row per (subject, match) with `partner_id`, `partner`, `opponent_1`, `opponent_2`, `games` ("21-17, 21-19", the subject's points first), `won` (1, 0 or NULL) plus tournament, category, event, round and date. A subject is a player with a result in that tournament, so opponents do not appear as subjects unless they were downloaded too.
- CSV export (`HistoryStore.export_csv`): `results.csv` (one row per event entered), `matches.csv` (one row per subject and match, from the view) and `games.csv` (one row per game, subject's points first). UTF-8 with a byte-order mark so Excel shows accents; empty values are blank.

Differences from the model planned on 2026-09-21: the `slot` column was dropped (the position of a player within a side has no analytical use); `seq` was added (matches need an order within their event); `players.slug` was dropped (the match responses carry no slug that is needed); `winner_side` is nullable (byes); `event_id` 0 stands for "no event" so it can be part of the primary key.

### Status

All of R4-R7 are implemented and tested: `bwf_player/tournaments.py` (Iteration 5), `matches.py` (Iteration 6), `store.py` (Iteration 7) and, tying them together, `history.py` (Iteration 8). The notebook (section 4) and `scripts/download_history.py` are thin interfaces over `download_player_history`.

**Live result (2026-09-21):** for Jonatan CHRISTIE the download gives 19 tournaments, 58 matches, 138 games, and every one of the 19 events reproduces the site's own match, game and point totals. A second run is answered entirely from the cache (tested live: no request made) and leaves the database unchanged.

**Differences from the plan approved on 2026-09-21:** the notebook does not add `pandas` to its extra (the notebook reads the database with the standard library, and the README shows the one-line `pandas.read_sql` call; this keeps the install light); a command-line script (`scripts/download_history.py`) was added, which the plan called optional; the `slot` column, `players.slug` and the `runs` idea were dropped (Iteration 7 notes). Everything else follows the plan.

**Not covered:** several players in one call (each player is tens of requests, so a batch would need its own pacing and block handling, and the terms of the site have not been reviewed), para players (section 8, item 7), and the practical limits listed in the README.
