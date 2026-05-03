from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_no_agent_os_imports_or_dependencies():
    forbidden_imports = ("import agent_os", "from agent_os")
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for forbidden in forbidden_imports:
            assert forbidden not in text, f"{forbidden!r} found in {path}"

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "agent-os" not in pyproject
    assert "agent_os" not in pyproject
