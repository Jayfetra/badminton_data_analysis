# BWF Player Lookup

Type a badminton player's name and get their personal details and ranking from [bwfbadminton.com](https://bwfbadminton.com).

| | What you get |
|---|---|
| **Search** | The player's profile URL. Ignores case, accents and word order; tolerates typos in full names; returns ranked candidates when the name is ambiguous; a clear "not found" otherwise. |
| **Personal details** | Nationality, height (cm), playing hand (Right/Left). |
| **Ranking** | Current rank and how many consecutive weeks the player has held it (plus since when). |
| **Tournaments (new, in progress)** | Every tournament the player entered in the last year, with the result per event (`1st`, `QF`, ...), the record and the category. |
| **Matches (new, in progress)** | For each event: every match with the partner, the opponents, the round, the date and the points of every game. |
| **Storage (new, in progress)** | Saved to a SQLite database (re-runnable) and exported as CSV. The one-call download comes next. |

A value the site does not list is `null`, with a note explaining it. A missing field never fails the whole request.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows; use `source .venv/bin/activate` elsewhere
pip install -e ".[dev,notebook]"   # "notebook" adds what is needed to run the notebook
```

**Notebook:** open [notebook.ipynb](notebook.ipynb) (VS Code or Jupyter), set `PLAYER_NAME`, run all cells. The committed notebook already contains a run, so you can read the results without running anything.

**Python:**

```python
from bwf_player import format_result, lookup_player

result = lookup_player("jonathan cristie")     # typo on purpose
print(format_result(result))
```

```
Search:         FOUND - Matched 'Jonatan CHRISTIE' (score 94).
Profile URL:    https://bwfbadminton.com/player/73442/jonatan-christie

Personal details
  Name:          Jonatan CHRISTIE
  Nationality:   Indonesia
  Height:        179.0 cm
  Playing hand:  Right

Ranking (MEN'S SINGLES)
  Current rank:  1
  At this rank:  4 week(s), since 2026-08-25 (latest ranking list 2026-09-15)
```

`result` is a pydantic model (`result.search`, `result.profile`, `result.ranking`; `result.model_dump_json()` for JSON). The three steps are also available on their own:

```python
from bwf_player.search import search_player
from bwf_player.profile import get_profile
from bwf_player.ranking import get_ranking

found = search_player("Christie Jonatan")       # status: found | ambiguous | not_found
pid = found.best_match.player_id
get_profile(pid)                                 # nationality, height_cm, playing_hand, missing_fields, notes
get_ranking(pid)                                 # current_rank, weeks_at_current_rank, other_events, notes
get_ranking(pid, event_id="9-90070")             # a different ranking event (ids are listed in other_events)
```

**Tournaments, matches and storage for the last year** (Iterations 5-7; a one-call download follows):

```python
from bwf_player import get_tournaments

history = get_tournaments(pid)                    # 2025-09-21 .. 2026-09-21 when written
for e in history.entries:                         # oldest first, one row per event entered
    print(e.start_date, e.name, e.event_code, e.position, e.category)
# 2026-09-01 LI-NING China Masters 2026 MS R16 HSBC BWF World Tour Super 750

from bwf_player import get_matches
event = get_matches(pid, history.entries[-1])     # one request: every match of that event
for m in event.matches:
    scores = ", ".join(f"{g.player_points}-{g.opponent_points}" for g in m.games)
    print(m.round, "won" if m.won else "lost", m.partner and m.partner.name, [o.name for o in m.opponents], scores)
# R32 won None ['LEONG Jun Hao'] 21-17, 21-19
# R16 lost None ['Jason GUNAWAN'] 16-21, 16-21
event.totals_agree                                # True: the matches add up to the site's own totals

from bwf_player.store import HistoryStore
with HistoryStore("data/bwf_history.sqlite") as store:         # re-running never duplicates anything
    store.save_tournaments(history, player_name="Jonatan CHRISTIE")
    for entry in history.entries:
        store.save_matches(get_matches(pid, entry))
    store.export_csv("data/export")                          # results.csv, matches.csv, games.csv
    rows = store.connection.execute(
        "SELECT round, partner, opponent_1, opponent_2, games, won FROM player_match_view "
        "WHERE tournament_id = 5625 ORDER BY seq").fetchall()   # or pandas.read_sql(..., store.connection)
```

The database has `players`, `tournaments`, `results`, `matches`, `match_players` and `games` tables plus the view `player_match_view` (one row per player and match). Table details: PRD section 10.

`position` is the site's own label (`null` for team events, which have none). A tournament counts if its dates overlap the window. `get_tournaments(pid, since=date(...), until=date(...))` sets another window. The default window costs two requests plus one to four for the categories.

Settings (match threshold, request spacing, cache location and lifetime) live in `BwfConfig`; pass `BwfHttpClient(BwfConfig(...))` as the `client` argument.

## How it works

The site is a JavaScript app that loads its data from a JSON API, so the tool calls that API directly instead of scraping HTML. Search fuzzy-matches against the site's full player list (cached for 7 days) and falls back to the site's own name search for players missing from that list. "Weeks at this rank" is derived from the weekly ranking history: the site's own "consecutive weeks" figure describes the player's *best* rank, not the current one. Design, endpoints and decisions are in [docs/PRD_master.md](docs/PRD_master.md).

## Project layout

```
bwf_player/      the package: http_client, names, search, profile, ranking, lookup, tournaments, matches, store, parsing, models, config
notebook.ipynb   thin interface over the package (committed with its outputs)
tests/           pytest; offline tests use saved real API responses in tests/fixtures/
scripts/         save_test_results.py, execute_notebook.py
docs/            PRD_master.md (source of truth), PRD_changelog.md (per iteration)
test_results/    latest.txt: full output of the most recent test run
```

## Tests

```bash
pytest                                # offline suite (default; no network)
pytest -m live                        # live smoke tests against bwfbadminton.com
python scripts/save_test_results.py   # both suites -> test_results/latest.txt
python scripts/execute_notebook.py    # re-run the notebook and save its outputs
```

## Limitations and cautions

- **Cloudflare.** The site blocks automated traffic it dislikes; during development a test IP was hard-blocked after about 15 quick requests. The client waits 2.5 s between requests, caches everything, and stops at once (raising `BlockedByCloudflareError`) if it is blocked. Do not loop it over many players.
- **Unofficial API.** It is the site's own front-end API, undocumented, and may change without notice. **The site's terms and conditions have not been reviewed**; check them before any use beyond personal research.
- **Search limits.** A typo inside a one-word query ("cristie") is not matched. A typo'd name for a player missing from the site's player list (e.g. Kento Momota) is not found. A reversed name for such a player, when its words are common, may fail ("Dan Lin" does not find "LIN Dan"). Details and workarounds: PRD section 8.
- **Ranking events.** The result reports the first event the site lists (usually singles); others are in `other_events`.
- **Tournament history.** Para tournaments are not covered; the category is `null` for tournaments the site's calendar gives none (62 of the 326 in the last year's calendar; none for Christie's). A bye is returned as its own status (`bye`, no result); filter `status == "played"` for matches that were really played. Disqualifications and matches still in progress are handled defensively but were not present in the real data used for testing.
- **Stored data.** `data/` (database and CSV) is git-ignored. The database keeps everything you have saved; saving again updates rows but never deletes any, so a match the site later removes stays in the file. The view `player_match_view` lists only players whose own history you downloaded.
- **Unknown id vs never ranked.** The site answers both the same way, so both come back as "no ranking events".

## Documentation

- [docs/PRD_master.md](docs/PRD_master.md): requirements, findings, architecture, schema, development procedure, open questions
- [docs/PRD_changelog.md](docs/PRD_changelog.md): what changed in each iteration, why, and what was tested
