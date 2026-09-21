# PRD Changelog

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
