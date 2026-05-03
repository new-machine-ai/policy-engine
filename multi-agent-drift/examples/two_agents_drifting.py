# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Two agents drifting in policy, config, trust, version, and capability."""

from __future__ import annotations

from multi_agent_drift import DriftDetector


def main() -> None:
    detector = DriftDetector()
    report = detector.scan(
        [
            {
                "label": "planner-a",
                "config": {
                    "isolation": "serializable",
                    "require_human_approval": True,
                    "allowed_tools": ["search", "summarize"],
                },
                "policies": {"orders": {"market_hours_only": True}},
                "trust_scores": {"executor": 0.93},
                "capabilities": {"executor": ["place_trade"]},
                "components": {"agent/executor-a": "1.2.0"},
            },
            {
                "label": "planner-b",
                "config": {
                    "isolation": "read_committed",
                    "allowed_tools": ["search", "summarize", "shell"],
                },
                "policies": {"orders": {"market_hours_only": False}},
                "trust_scores": {"executor": 0.55},
                "capabilities": {"executor": ["place_trade", "exec_code"]},
                "components": {"agent/executor-b": "1.1.0"},
            },
        ]
    )
    print(detector.to_markdown(report))


if __name__ == "__main__":
    main()
