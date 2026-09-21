"""Execute notebook.ipynb top to bottom and save the outputs into it.

Usage:  python scripts/execute_notebook.py

Requires the notebook extra:  pip install -e ".[notebook]"
Makes real requests to bwfbadminton.com (rate limited; cached, so re-runs are quick).
"""

from __future__ import annotations

import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebook.ipynb"


def main() -> int:
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    for cell in notebook.cells:
        if cell.cell_type == "code":
            cell.outputs, cell.execution_count = [], None

    NotebookClient(
        notebook, timeout=600, kernel_name="python3", resources={"metadata": {"path": str(ROOT)}}
    ).execute()
    nbformat.write(notebook, NOTEBOOK)

    print(f"Executed {sum(c.cell_type == 'code' for c in notebook.cells)} code cells; saved to {NOTEBOOK.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
