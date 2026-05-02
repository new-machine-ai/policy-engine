"""Run every live hello-world sample as a separate process."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLES = [
    "langchain_agent.py",
    "openai_agent.py",
    "microsoft_agent.py",
    "anthropic_agent.py",
    "google_adk_agent.py",
    "claude_agent_sdk_agent.py",
]


def run_sample(path: Path) -> float:
    start = time.monotonic()
    subprocess.run([sys.executable, str(path)], check=True)
    return time.monotonic() - start


def main() -> int:
    print(f"Running {len(SAMPLES)} live samples from {HERE.name}/\n")
    for sample in SAMPLES:
        path = HERE / sample
        print(f"=== {sample} ===")
        duration = run_sample(path)
        print(f"--> PASS in {duration:.1f}s\n")
    print(f"Summary: {len(SAMPLES)} passed, 0 failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
