# Working agreements for this project

These are standing instructions from the project owner. Follow them in every session.

## The notebook is always delivered fully executed

The owner **reads** `notebook.ipynb`; they do not run it. So:

- After **every** change to the notebook (or to any code the notebook calls), **execute all cells** and commit the notebook **with its outputs**: `python scripts/execute_notebook.py` (uses the live site; needs the `notebook` extra; a busy download takes several minutes, so run it in the background and wait for it to finish).
- Never leave a code cell without output or an old output next to changed code. `tests/test_notebook.py` checks that every code cell ran without errors; add a check there for each new section's key output.
- Read the executed outputs yourself before reporting: show the owner the real numbers, and say plainly if a result looks wrong or surprising.
- The committed notebook must contain no local paths, secrets or personal data (the tests check this). Use relative paths (`data/...`).
- The notebook stays a thin interface: logic lives in the `bwf_player` package with tests.

## Development procedure (details: `docs/PRD_master.md`, section 9)

1. Inspect the real site or data first; ask when something is genuinely ambiguous.
2. Implement in small steps; validate input; never build URLs from raw input.
3. Add pytest tests (offline on saved real responses in `tests/fixtures/`, plus a few `@pytest.mark.live`). Real-data answers should be recomputed by an independent route in the tests.
4. Save results: `python scripts/save_test_results.py`.
5. **Update the documentation after all testing**: `docs/PRD_master.md`, `docs/PRD_changelog.md` (numbers must match `test_results/latest.txt`), `README.md`; sweep for statements the change made stale and correct them openly.
6. Commit and push to `main` with a clear message, then report (summary, tests, commit, open questions, risks).

## Cautions

- Be polite to bwfbadminton.com (Cloudflare): the client waits 2.5 s between requests and caches for 24 h. Never run two live jobs at once, and run the live suite sparingly (it does a real ~85-request download).
- `data/` (databases, CSV) and `.cache/` are git-ignored. The notebook uses its own database (`data/bwf_notebook.sqlite`); saving never deletes rows, so old runs with other date windows can leave extra rows in a shared database.
- Terms of service of the site are still unreviewed (PRD section 8, items 2 and 9): one player per call, no batch crawling.
- Do not guess pronouns for people; the report texts use "the player".
