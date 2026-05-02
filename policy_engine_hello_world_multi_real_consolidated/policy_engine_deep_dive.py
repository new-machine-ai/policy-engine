"""Run the policy_engine_deep_dive notebook as a regular demo.

`run_all.py` discovers demos by importing a module and calling its
``main()``. The deep dive lives in a Jupyter notebook so it doubles as a
tutorial — this shim just parses the .ipynb as JSON and ``exec``s each
code cell into a shared namespace, so we don't pull in `nbclient` or
`jupyter` for one demo.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
NOTEBOOK = HERE / "policy_engine_deep_dive.ipynb"


def _is_magic(source: str) -> bool:
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        return stripped.startswith(("!", "%"))
    return False


def main() -> None:
    nb = json.loads(NOTEBOOK.read_text())
    shared: dict = {"__notebook_dir__": str(HERE), "__name__": "__notebook__"}
    for cell in nb["cells"]:
        if cell["cell_type"] != "code":
            continue
        source = cell["source"]
        if isinstance(source, list):
            source = "".join(source)
        if _is_magic(source):
            continue
        exec(compile(source, str(NOTEBOOK), "exec"), shared)


if __name__ == "__main__":
    main()
