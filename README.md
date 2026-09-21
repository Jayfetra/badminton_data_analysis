# BWF Player Lookup

Look up a badminton player by name and retrieve their profile (nationality, height, playing hand) and ranking (current rank, time at rank) from bwfbadminton.com.

**Status:** Iteration 0 (scaffold). Search, profile and ranking are implemented in Iterations 1-3; see [docs/PRD_master.md](docs/PRD_master.md).

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
