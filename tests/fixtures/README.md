# Fixtures

Real responses captured from `extranet-lv.bwfbadminton.com/api` on 2026-09-21.

- `popular_*.json` — `vue-popular-players` (search) responses. The bulky `pagination.data` duplicate of `results` was removed.
- `h2h_players_index.json` — `vue-h2h-players`, trimmed from 3,429 entries to a deterministic sample (plus a few required names). The real index does not include every player (e.g. Kento MOMOTA is absent).
- `summary_*.json` — `vue-player-summary` (R2 source: `country_model`, `bio_model.height`, `bio_model.plays`). `summary_no_details.json` is a real player (Aadhya SHINE, id 89438) whose nationality, height and hand are all unset; `summary_unknown_player.json` is the response for a non-existent id (`results` is empty).
- `ranking_*.json` — `vue-player-ranking-events` / `-current` / `-history` (R3). Players: Jonatan CHRISTIE (73442, ranked #1, men's singles), Aadhya SHINE (89438, two events: women's singles and women's doubles), Zygimantas MOLIS (39881, a single history row), Lee Chong Wei (50152, retired: `current` is `"-"`, history ends in 2019). `ranking_events_none.json` is the response for a non-existent id (an empty list). Note `results` of `-history` is a JSON string, exactly as the site sends it.
