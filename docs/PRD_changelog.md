# PRD Changelog

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
