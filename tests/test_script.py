"""The command-line script: exit codes, output and options. Offline (fake client)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from bwf_player import BwfConfig
from bwf_player.exceptions import BlockedByCloudflareError
from tests.fakes import FakeApiClient

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "download_history.py"


@pytest.fixture(scope="module")
def script() -> Any:
    spec = importlib.util.spec_from_file_location("download_history", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _client(tmp_path: Path) -> FakeApiClient:
    return FakeApiClient(BwfConfig(history_db_path=tmp_path / "h.sqlite", history_export_dir=tmp_path / "csv"))


def test_downloads_and_prints_the_report(script: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = script.main(["73442", "--since", "2026-01-01", "--until", "2026-01-31"], _client(tmp_path))
    out, err = capsys.readouterr()
    assert code == 0
    assert "Player:       Jonatan CHRISTIE (id 73442)" in out and "Window:       2026-01-01 to 2026-01-31" in out
    assert "PETRONAS Malaysia Open 2026" in out and "vs" in out
    assert "[1/2]" in err and "[2/2]" in err  # progress goes to stderr
    assert (tmp_path / "h.sqlite").is_file() and (tmp_path / "csv" / "games.csv").is_file()


def test_options_choose_the_outputs(script: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = script.main(
        ["Jonatan Christie", "--since", "2026-01-01", "--until", "2026-01-31", "--db", str(tmp_path / "x.sqlite"),
         "--out", str(tmp_path / "o"), "--no-matches"],
        _client(tmp_path),
    )
    out = capsys.readouterr().out
    assert code == 0 and (tmp_path / "x.sqlite").is_file() and (tmp_path / "o" / "results.csv").is_file()
    assert "PETRONAS Malaysia Open 2026" in out and " vs " not in out  # events only, no match lines


def test_no_csv(script: Any, tmp_path: Path) -> None:
    assert script.main(["73442", "--since", "2026-01-01", "--until", "2026-01-31", "--no-csv"], _client(tmp_path)) == 0
    assert (tmp_path / "h.sqlite").is_file() and not (tmp_path / "csv").exists()


@pytest.mark.parametrize("name", ["christie", "not a real player zzz"])
def test_exit_2_when_no_single_player_is_found(script: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str) -> None:
    assert script.main([name], _client(tmp_path)) == 2
    assert "Nothing was downloaded." in capsys.readouterr().out
    assert not (tmp_path / "h.sqlite").exists()


def test_exit_2_when_the_player_has_no_tournaments(script: Any, tmp_path: Path) -> None:
    assert script.main(["999999999"], _client(tmp_path)) == 2


def test_exit_1_on_invalid_input_and_failures(script: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert script.main(["73442", "--since", "2026-02-01", "--until", "2026-01-01"], _client(tmp_path)) == 1
    assert "Invalid input" in capsys.readouterr().err

    class Blocked(FakeApiClient):
        def get_json(self, *args: Any, **kwargs: Any) -> Any:
            raise BlockedByCloudflareError("blocked")

    assert script.main(["73442"], Blocked(BwfConfig(history_db_path=tmp_path / "b.sqlite"))) == 1
    assert "The download failed" in capsys.readouterr().err


def test_a_bad_date_is_refused_by_the_parser(script: Any, tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as raised:
        script.main(["73442", "--since", "yesterday"], _client(tmp_path))
    assert raised.value.code == 2
