# BWF Player Lookup

Look up a badminton player by name and retrieve their profile (nationality, height, playing hand) and ranking (current rank, time at rank) from bwfbadminton.com.

**Status:** Iteration 1 done (player search). Profile and ranking arrive in Iterations 2-3; see [docs/PRD_master.md](docs/PRD_master.md).

## Usage

```python
import logging
from bwf_player.search import search_player

logging.basicConfig(level=logging.INFO)
result = search_player("jonathan cristie")
result.status                 # "found" | "ambiguous" | "not_found"
result.best_match.profile_url # https://bwfbadminton.com/player/73442/jonatan-christie
```

Tolerates case, extra whitespace, accents, reversed name order and typos in full names. A partial name such as "christie" returns ranked candidates (`ambiguous`) instead of guessing. Responses are cached under `.cache/bwf_player` (a repeat lookup makes no requests).

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
```

## Notes

- The site sits behind Cloudflare bot protection. The client rate-limits and caches, but heavy use can get your IP blocked. See the risks section of the PRD.
- The API used is the site's own undocumented front-end API and may change. Check the site's terms before any non-personal use.

## Docs

- [PRD_master.md](docs/PRD_master.md): requirements, architecture, schema, open questions
- [PRD_changelog.md](docs/PRD_changelog.md): per-iteration changes
