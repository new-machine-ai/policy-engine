from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_no_forbidden_runtime_imports_or_dependencies():
    runtime_a = "agent" + "_" + "os"
    runtime_b = "hyper" + "visor"
    forbidden = [
        "import " + runtime_a,
        "from " + runtime_a,
        "import " + runtime_b,
        "from " + runtime_b,
    ]
    for folder in ("src", "tests"):
        for path in (ROOT / folder).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                assert token not in text, f"{token!r} found in {path}"

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for token in ("agent" + "-os", runtime_a, "agent" + "-" + runtime_b):
        assert token not in pyproject
