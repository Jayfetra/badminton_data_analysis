# BWF Player Lookup

Look up a badminton player by name and retrieve their profile (nationality, height, playing hand) and ranking (current rank, time at rank) from bwfbadminton.com.

**Status:** Iterations 1-3 done (player search, personal details, ranking). Iteration 4 finalises the notebook; see [docs/PRD_master.md](docs/PRD_master.md).

## Usage

```python
import logging
from bwf_player.search import search_player

logging.basicConfig(level=logging.INFO)
result = search_player("jonathan cristie")
result.status                 # "found" | "ambiguous" | "not_found"
result.best_match.profile_url # https://bwfbadminton.com/player/73442/jonatan-christie
```

```python
from bwf_player.profile import get_profile

profile = get_profile(result.best_match.player_id)
profile.nationality, profile.height_cm, profile.playing_hand   # ("Indonesia", 179.0, "Right")
profile.missing_fields, profile.notes                          # fields the site does not list
```

```python
from bwf_player.ranking import get_ranking

ranking = get_ranking(result.best_match.player_id)
ranking.event.name, ranking.current_rank               # ("MEN'S SINGLES", 1)
ranking.weeks_at_current_rank, ranking.at_rank_since   # (4, date(2026, 8, 25))
ranking.other_events                                   # e.g. doubles; pick one with get_ranking(id, event_id="9-90070")
```

An unranked player returns `is_ranked=False`, `current_rank=None` and a note. Weeks at rank are derived from the weekly ranking history (the site's own "consecutive weeks" figure is for the player's best rank, not the current one).

A profile field the site does not list is `None` (named in `missing_fields`, explained in `notes`); the rest of the profile is still returned.

Search tolerates case, extra whitespace, accents, reversed name order and typos in full names. A partial name such as "christie" returns ranked candidates (`ambiguous`) instead of guessing. Responses are cached under `.cache/bwf_player` (a repeat lookup makes no requests).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows; use `source .venv/bin/activate` elsewhere
pip install -e ".[dev]"        # add ",notebook" to also install Jupyter
```

## Tests

```bash
pytest                # offline unit tests (default)
pytest -m live        # live smoke tests against bwfbadminton.com
python scripts/save_test_results.py   # run both, save output to test_results/latest.txt
```

## Notes

- The site sits behind Cloudflare bot protection. The client rate-limits and caches, but heavy use can get your IP blocked. See the risks section of the PRD.
- The API used is the site's own undocumented front-end API and may change. Check the site's terms before any non-personal use.

## Docs

- [PRD_master.md](docs/PRD_master.md): requirements, architecture, schema, open questions
- [PRD_changelog.md](docs/PRD_changelog.md): per-iteration changes
