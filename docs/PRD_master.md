# PRD Master — BWF Player Lookup

**Version:** 1.0 (Iteration 4: final notebook, README, full regression) · **Last updated:** 2026-09-21

Single source of truth for requirements, architecture decisions, data schema and open questions.

## 1. Goal

Given a badminton player's name, retrieve profile and ranking data from bwfbadminton.com.

| ID | Requirement |
|----|-------------|
| R1 | Fuzzy player search (case, whitespace, accents, reversed order, partial names, minor typos). Configurable threshold. Ambiguous matches return ranked candidates; no match returns a clear "not found" result. Success returns the profile URL. |
| R2 | From the profile: nationality, height, playing hand. Missing field -> `null` plus a note; never fails the whole request. |
| R3 | From the ranking tab: current rank and how long the player has held it. Unranked -> `null` plus a note. |

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
4. **Live testing.** The block observed in Iteration 0 lifted within a day. Since then the live smoke suite (8 tests, roughly 15 requests over about 40 s, 2.5 s apart, custom `Mozilla/5.0 (compatible; bwf-player-lookup/...)` User-Agent) and repeated notebook runs have caused no block. Run the live suite sparingly.

## 4. Architecture

Notebook is a thin interface over the `bwf_player` package.

```
bwf_player/
  config.py       BwfConfig (pydantic): thresholds, rate limit, cache, URLs, timeouts
  exceptions.py   BwfClientError, BlockedByCloudflareError, InvalidInputError
  models.py       PlayerCandidate, SearchResult, PlayerProfile, PlayerRanking, PlayerResult
  http_client.py  session bootstrap, rate limit, retry/backoff, disk cache, block detection
  names.py        query sanitizing, name normalization, slug derivation, player-id validation
  search.py       R1 (Iteration 1)
  profile.py      R2 (Iteration 2)
  ranking.py      R3 (Iteration 3)
  lookup.py       lookup_player (search -> profile -> ranking) and format_result (Iteration 4)
notebook.ipynb    thin interface over the package; committed with its executed outputs
tests/            pytest; offline unit tests on saved fixtures; @pytest.mark.live smoke tests
scripts/          save_test_results.py (both suites -> test_results/latest.txt), execute_notebook.py (runs notebook.ipynb, saves outputs)
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
- **Input safety.** Names are sanitized as above and passed to the API only via `requests` `params` (encoded), never string-concatenated into URLs. Server queries use only the normalized (alphanumeric) tokens. Player ids/slugs are URL-quoted when building profile URLs.
- **No secrets** are used or stored. The session cookie is fetched at runtime and kept in memory.

## 5. Data schema (v1.0)

See `bwf_player/models.py`.

- `PlayerCandidate`: `player_id`, `slug`, `name`, `country`, `profile_url`, `score` (0-100)
- `SearchResult`: `query`, `status` (`found` | `ambiguous` | `not_found`), `best_match`, `candidates`, `message`
- `PlayerProfile`: `player_id`, `player_found`, `name`, `nationality` (country name), `height_cm` (float), `playing_hand` (`Right` | `Left` | null), `missing_fields`, `notes`
- `RankingEvent`: `id` (e.g. `6-0`), `name`
- `PlayerRanking`: `player_id`, `event`, `other_events`, `is_ranked`, `current_rank`, `weeks_at_current_rank`, `at_rank_since`, `as_of`, `weeks_source`, `notes`
- `PlayerResult`: `search`, `profile`, `ranking`, `fetched_at`

BWF raw field names for bio/ranking are unconfirmed; models are the package's own schema and parsers map onto them.

## 6. Testing strategy

pytest. Offline unit tests use saved JSON fixtures in `tests/fixtures/`. Live smoke tests are marked `@pytest.mark.live` and excluded by default (`pytest -m live` to run). `python scripts/save_test_results.py` runs both suites and saves the full output to `test_results/latest.txt` (overwritten every iteration; `--no-live` skips the live suite). Required edge cases: exact, fuzzy, ambiguous, not found, empty input, special characters, missing fields, unranked player. `tests/test_notebook.py` guards the committed notebook: valid, every code cell executed without errors, only uses the package, shows the main result, contains no secrets or local paths.

## 7. Iteration plan

| Iteration | Scope | Status |
|-----------|-------|--------|
| 0 | Scaffold, investigation, PRD v0.1, first commit | Done |
| 1 | R1 search + tests | Done |
| 2 | R2 profile + tests | Done |
| 3 | R3 ranking + tests | Done |
| 4 | Notebook, README, full regression | Done |

## 8. Open questions

1. ~~Search coverage~~ **Resolved in Iteration 1.** `vue-popular-players` searches the whole database but is a strict substring match; `vue-h2h-players` is a complete-looking but incomplete index. Hybrid design in section 4.
1a. **Known limitations of R1.** (a) A typo inside a *single-word* partial name ("cristie", "jonathan") is not matched; typo tolerance applies to full names. (b) A typo'd query for a player absent from the index (Momota, Tai Tzu Ying, Carolina Marin) will not be found, because the server search is strict. (c) If a typo'd query closely resembles a different indexed player, that player can be returned as `found`. (d) A reversed query for a player who is missing from the index and whose name parts are common fails: "Dan Lin" does not find "LIN Dan" (found while testing R3), because the server is queried with the phrase as typed and then with single common words that return more players than are paged. Rotating the words ("lin dan") would fix it; not done, to keep R1 unchanged in this iteration. Mitigation if any of these matter: page the full player list once (about 100+ requests at 30 per page; not done, given the block risk).
2. **ToS.** Read `/terms-and-conditions/` from an unblocked network and record the scraping stance here.
3. ~~Bio field names~~ **Resolved in Iteration 2** (see `vue-player-summary`). **Ranking field names** also **resolved in Iteration 3** (see the ranking endpoints; real responses are saved as fixtures).
4. ~~Height format~~ **Resolved:** centimetres, returned as `height_cm` (float).
5. **Which ranking event (awaiting your decision).** Implemented as: the first event the site lists, with the others in `other_events` and selectable via `event_id`. Confirm this is what you want, or whether the result should contain all events (2 more requests per extra event).

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
