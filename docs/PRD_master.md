# PRD Master — BWF Player Lookup

**Version:** 0.2 (Iteration 1: R1 search) · **Last updated:** 2026-09-21

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
| `vue-player-bio` | `playerId`, `activeTab` | R2 details. | Response shape **not yet inspected** |
| `vue-player-ranking-events` | `playerId`, `activeTab`, `isPara` | R3: lists ranking events; the first is the default. | Not yet tested |
| `vue-player-ranking-current` | `rankingEvent`, `playerId`, `isPara` | R3 current rank. | Not yet tested |
| `vue-player-ranking-highest` | `rankingEvent`, `playerId`, `isPara` | Not needed for R3. | Not yet tested |
| `vue-player-ranking-history` | `activeTab`, `rankingEvent`, `playerId`, `isPara` | R3. The front-end reads `response.data.consecutive` into `playerConsecWeeks`. | Not yet tested |

**Profile URL pattern:** `https://bwfbadminton.com/player/{id}/{slug}` (`id`/`slug` from the search result; URL-encode when building).

**R3 "time at rank".** The site front-end appears to compute consecutive weeks itself (`consecutive` in the ranking-history response). If Iteration 3 confirms this, no derivation is needed (`weeks_source = "site_reported"`). Otherwise derive from `results` history as the run length of unchanged rank ending at the latest entry (`weeks_source = "derived_from_history"`) and document it here.

**Access requirements.** API calls need a `laravel_session` cookie (obtained by first requesting any bwfbadminton.com page) and a `Referer` header. Without the cookie the API returned 403.

## 3. Risks

1. **Cloudflare bot protection (high).** After roughly 15 requests in a few minutes, Cloudflare **hard-blocked** the test IP site-wide ("Sorry, you have been blocked"), even for plain pages. Consequences for the design:
   - A block is detected explicitly and is **never retried**; the client raises `BlockedByCloudflareError` with an actionable message.
   - Rate limiting (default 2.5 s between requests) and on-disk caching are required, not optional.
   - Decision (user, 2026-09-21): plain `requests` client, no headless-browser fallback. The risk is documented, not engineered around. Reconsider if blocks prove persistent.
2. **ToS unverified (medium).** See section 2.
3. **Unofficial API (medium).** Field names and endpoints may change. Parsers are isolated in their own modules and tested against saved fixtures so drift is easy to spot.
4. **Live testing.** The block observed in Iteration 0 lifted within a day. Iteration 1 live smoke tests (about 5 requests, 2.5 s apart, custom `Mozilla/5.0 (compatible; bwf-player-lookup/...)` User-Agent) passed with no block. Run them sparingly.

## 4. Architecture

Notebook is a thin interface over the `bwf_player` package.

```
bwf_player/
  config.py       BwfConfig (pydantic): thresholds, rate limit, cache, URLs, timeouts
  exceptions.py   BwfClientError, BlockedByCloudflareError, InvalidInputError
  models.py       PlayerCandidate, SearchResult, PlayerProfile, PlayerRanking, PlayerResult
  http_client.py  session bootstrap, rate limit, retry/backoff, disk cache, block detection
  names.py        query sanitizing, name normalization, slug derivation
  search.py       R1 (Iteration 1)
  profile.py      R2 (Iteration 2)
  ranking.py      R3 (Iteration 3)
notebook.ipynb    end-to-end demo
tests/            pytest; offline unit tests on saved fixtures; @pytest.mark.live smoke tests
```

### Framework recommendation

**No Flask, no HTTP API layer.** The deliverable is a notebook-driven, on-demand lookup, so a web server adds deployment and security surface with no consumer. A plain importable package plus a notebook is the leanest option. If an API is wanted later, add a thin optional FastAPI layer over the same pydantic models (validation and docs for free). That is out of scope unless requested.

### Design notes

- **Search algorithm (R1, implemented).**
  1. *Sanitize* (`names.sanitize_query`): NFKC, control characters to spaces, whitespace collapsed, max 100 chars. Bad input (non-text, empty, too long, no letters/digits) returns a `not_found` result with a message; it never raises.
  2. *Normalize* (`names.normalize_name`): casefold, strip accents (plus o-slash, ae, ss, l-stroke, d-stroke...), punctuation to spaces.
  3. *Index stage*: fetch `vue-h2h-players` once (cached 7 days), score every name locally.
  4. *Server stage*: only if no single index name scores 100, query `vue-popular-players` with the two longest query tokens (max 2 pages each), stopping as soon as a confident match exists. Results are merged by player id; server data (real slug, country) wins.
  5. *Decide*: keep candidates scoring at least the threshold (default 85). None -> `not_found` (message names the closest candidate). One, or a lead of at least the margin (default 5) -> `found`. Otherwise -> `ambiguous` with up to 5 ranked candidates.
- **Scoring**: `max(token_sort_ratio, 0.9 * token_set_ratio)` from rapidfuzz on normalized names. Same words in any order = 100 (so reversed names need no special code); "jonathan cristie" vs "Jonatan CHRISTIE" = 94; a partial name ("christie", "lee") = a flat 90 for every player containing it, so partial queries are `ambiguous` by design. `WRatio` was rejected because it scores shorter names higher for the same partial query.
- **Profile URL**: `https://bwfbadminton.com/player/{id}/{slug}`. The slug comes from the server when available, otherwise it is derived from the name (`Jonatan CHRISTIE` -> `jonatan-christie`). The id is authoritative: the site 302-redirects `/player/{id}/` and `/player/{id}/<any-slug>` to the canonical URL.
- **Request economy**: a repeat lookup of a known player costs zero requests (index + results cached). A first-ever lookup costs one session bootstrap plus the index; players missing from the index cost 1-2 more.
- **Input safety.** Names are sanitized as above and passed to the API only via `requests` `params` (encoded), never string-concatenated into URLs. Server queries use only the normalized (alphanumeric) tokens. Player ids/slugs are URL-quoted when building profile URLs.
- **No secrets** are used or stored. The session cookie is fetched at runtime and kept in memory.

## 5. Data schema (v0.1)

See `bwf_player/models.py`.

- `PlayerCandidate`: `player_id`, `slug`, `name`, `country`, `profile_url`, `score` (0-100)
- `SearchResult`: `query`, `status` (`found` | `ambiguous` | `not_found`), `best_match`, `candidates`, `message`
- `PlayerProfile`: `player_id`, `name`, `nationality`, `height`, `playing_hand` (`Right` | `Left` | null), `missing_fields`
- `PlayerRanking`: `player_id`, `event`, `is_ranked`, `current_rank`, `weeks_at_current_rank`, `weeks_source`, `note`
- `PlayerResult`: `search`, `profile`, `ranking`, `fetched_at`

BWF raw field names for bio/ranking are unconfirmed; models are the package's own schema and parsers map onto them.

## 6. Testing strategy

pytest. Offline unit tests use saved JSON fixtures in `tests/fixtures/`. Live smoke tests are marked `@pytest.mark.live` and excluded by default (`pytest -m live` to run). Required edge cases: exact, fuzzy, ambiguous, not found, empty input, special characters, missing fields, unranked player.

## 7. Iteration plan

| Iteration | Scope | Status |
|-----------|-------|--------|
| 0 | Scaffold, investigation, PRD v0.1, first commit | Done |
| 1 | R1 search + tests | Done |
| 2 | R2 profile + tests | Pending |
| 3 | R3 ranking + tests | Pending |
| 4 | Notebook, README, full regression | Pending |

## 8. Open questions

1. ~~Search coverage~~ **Resolved in Iteration 1.** `vue-popular-players` searches the whole database but is a strict substring match; `vue-h2h-players` is a complete-looking but incomplete index. Hybrid design in section 4.
1a. **Known limitations of R1.** (a) A typo inside a *single-word* partial name ("cristie", "jonathan") is not matched; typo tolerance applies to full names. (b) A typo'd query for a player absent from the index (Momota, Tai Tzu Ying, Carolina Marin) will not be found, because the server search is strict. (c) If a typo'd query closely resembles a different indexed player, that player can be returned as `found`. Mitigation if any of these matter: page the full player list once (about 100+ requests at 30 per page; not done, given the block risk).
2. **ToS.** Read `/terms-and-conditions/` from an unblocked network and record the scraping stance here.
3. **Bio and ranking field names** (Iterations 2 and 3): capture real responses as fixtures first.
4. **Height format.** Units and representation on the site (cm? string?). Decide after inspecting bio JSON.
5. **Which ranking event** to report when a player has several (singles/doubles/mixed). Default proposal: the first event the site lists; return all if cheap. Confirm with the user in Iteration 3.
