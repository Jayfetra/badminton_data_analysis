# Fixtures

Real responses captured from `extranet-lv.bwfbadminton.com/api` on 2026-09-21.

- `popular_*.json` — `vue-popular-players` (search) responses. The bulky `pagination.data` duplicate of `results` was removed.
- `h2h_players_index.json` — `vue-h2h-players`, trimmed from 3,429 entries to a deterministic sample (plus a few required names). The real index does not include every player (e.g. Kento MOMOTA is absent).
- `summary_*.json` — `vue-player-summary` (R2 source: `country_model`, `bio_model.height`, `bio_model.plays`). `summary_no_details.json` is a real player (Aadhya SHINE, id 89438) whose nationality, height and hand are all unset; `summary_unknown_player.json` is the response for a non-existent id (`results` is empty).
