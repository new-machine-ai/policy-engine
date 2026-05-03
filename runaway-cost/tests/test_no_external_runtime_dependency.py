from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_no_forbidden_runtime_imports_or_dependencies():
    runtime_a = "agent" + "_" + "os"
    runtime_b = "hyper" + "visor"
    runtime_c = "agent" + "_" + "sre"
    forbidden_imports = [
        "import " + runtime_a,
        "from " + runtime_a,
        "import " + runtime_b,
        "from " + runtime_b,
        "import " + runtime_c,
        "from " + runtime_c,
    ]
    for folder in ("src", "tests"):
        for path in (ROOT / folder).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden_imports:
                assert token not in text, f"{token!r} found in {path}"

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    forbidden_metadata = [
        "agent" + "-os",
        runtime_a,
        "agent" + "-" + runtime_b,
        runtime_b,
        "agent" + "-sre",
        runtime_c,
    ]
    for token in forbidden_metadata:
        assert token not in pyproject
