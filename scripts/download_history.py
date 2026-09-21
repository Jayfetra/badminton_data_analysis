"""Download a player's tournament history (results, partners, opponents, game scores) for the last year.

Usage:
    python scripts/download_history.py "Jonatan Christie"
    python scripts/download_history.py 73442 --since 2026-01-01 --until 2026-06-30
    python scripts/download_history.py "Fajar Alfian" --db data/fajar.sqlite --out data/fajar_csv --no-matches

Saves to a SQLite database and CSV files (defaults: data/bwf_history.sqlite and data/export/) and
prints a report. Makes real, rate-limited requests to bwfbadminton.com (about 25-40 for a busy
player, roughly a minute or two; cached, so repeating the command is quick).

Exit status: 0 = downloaded, 2 = the name matched no single player (or the player entered no
tournament in the window, nothing was saved), 1 = the download failed (for example Cloudflare
blocked it: wait before retrying; whatever was saved before the failure is kept).
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from bwf_player import (
    BwfClientError,
    BwfHttpClient,
    InvalidInputError,
    download_player_history,
    format_history,
)


def _date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{text!r} is not a date like 2026-09-21") from exc


def main(argv: list[str] | None = None, client: BwfHttpClient | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("player", help="the player's name, or the site's player id")
    parser.add_argument("--since", type=_date, help="first day of the window (default: one year ago)")
    parser.add_argument("--until", type=_date, help="last day of the window (default: today)")
    parser.add_argument("--db", type=Path, help="SQLite file (default: data/bwf_history.sqlite)")
    parser.add_argument("--out", type=Path, help="CSV folder (default: data/export)")
    parser.add_argument("--no-csv", action="store_true", help="do not write the CSV files")
    parser.add_argument("--no-matches", action="store_true", help="print only the event list, not every match")
    args = parser.parse_args(argv)

    try:
        summary = download_player_history(
            args.player,
            client,
            since=args.since,
            until=args.until,
            db_path=args.db,
            export_dir=args.out,
            export=not args.no_csv,
            progress=lambda message: print(message, file=sys.stderr),
        )
    except InvalidInputError as exc:
        print(f"Invalid input: {exc}", file=sys.stderr)
        return 1
    except BwfClientError as exc:
        print(f"The download failed: {exc}", file=sys.stderr)
        return 1

    print(format_history(summary, matches=not args.no_matches))
    return 0 if summary.database else 2


if __name__ == "__main__":
    sys.exit(main())
