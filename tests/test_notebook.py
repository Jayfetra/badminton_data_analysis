"""The committed notebook stays a thin, executed, error-free interface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

NOTEBOOK = Path(__file__).resolve().parents[1] / "notebook.ipynb"


@pytest.fixture(scope="module")
def notebook() -> dict:
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def code_cells(notebook: dict) -> list[dict]:
    return [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]


def test_is_a_valid_v4_notebook(notebook: dict) -> None:
    assert notebook["nbformat"] == 4
    assert all("id" in cell for cell in notebook["cells"])


def test_every_code_cell_was_executed_without_errors(notebook: dict) -> None:
    for cell in code_cells(notebook):
        assert cell["execution_count"] is not None, "run scripts/execute_notebook.py and commit the result"
        assert not [o for o in cell["outputs"] if o["output_type"] == "error"]


def test_is_a_thin_interface_over_the_package(notebook: dict) -> None:
    source = "\n".join("".join(cell["source"]) for cell in code_cells(notebook))
    assert "from bwf_player import" in source and "lookup_player(" in source and "format_result(" in source
    assert "download_player_history(" in source and "format_history(" in source
    assert "get_match_details(" in source and "format_match_details(" in source
    for forbidden in ("import requests", "rapidfuzz", "BeautifulSoup", "extranet-lv"):
        assert forbidden not in source


def test_shows_the_main_result(notebook: dict) -> None:
    output = "".join(
        "".join(o.get("text", "")) for cell in code_cells(notebook) for o in cell["outputs"]
    )
    for expected in ("FOUND", "Personal details", "Nationality:", "Current rank:", "At this rank:"):
        assert expected in output


def test_has_no_secrets_or_local_paths(notebook: dict) -> None:
    text = NOTEBOOK.read_text(encoding="utf-8")
    for marker in ("C:\\Users", "jayfet", "laravel_session", "@gmail.com"):
        assert marker not in text


def test_shows_the_history_download_and_the_saved_data(notebook: dict) -> None:
    output = "".join(
        "".join(o.get("text", "")) for cell in code_cells(notebook) for o in cell["outputs"]
    )
    for expected in (
        "Downloaded:", "tournament(s)", "the matches reproduce the site's own totals: yes",
        "result:", " vs ", "First matches in the database", "CSV files:",
    ):
        assert expected in output
    assert "NO - see notes" not in output


def test_shows_the_game_details_of_the_example_match(notebook: dict) -> None:
    output = "".join(
        "".join(o.get("text", "")) for cell in code_cells(notebook) for o in cell["outputs"]
    )
    for expected in (
        "Game details:", "with rally data", "MATCH", "Final match score", "Most consecutive points", "Total points played",
        "GAME 1", "GAME 2", "score after each rally: 0-1 1-1 1-2", "Checks: the rallies, statistics and scores agree.",
        "rallies are stored for this match",
    ):
        assert expected in output, expected
    assert "Checks failed" not in output and "NO - see notes" not in output


def test_shows_two_players_side_by_side(notebook: dict) -> None:
    output = "".join(
        "".join(o.get("text", "")) for cell in code_cells(notebook) for o in cell["outputs"]
    )
    for expected in (
        "Player:       AN Se Young", "Matches played in the window", "Jonatan CHRISTIE", "AN Se Young",
        "Rally statistics per player", "points_won_pct", "The longest games", "Comeback games",
        "Latest matches of player", "Rallies of game 1",
    ):
        assert expected in output, expected
    assert "Traceback" not in output
