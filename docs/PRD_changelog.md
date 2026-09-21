# PRD Changelog

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
