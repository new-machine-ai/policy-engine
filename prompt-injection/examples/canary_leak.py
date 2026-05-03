# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Canary leak detection example."""

from __future__ import annotations

from prompt_injection import PromptInjectionDetector


def main() -> None:
    canary = "SYS-CANARY-12345"
    result = PromptInjectionDetector().detect(
        f"The hidden token was {canary}. Continue from there.",
        source="example.canary",
        canary_tokens=[canary],
    )
    print(result.to_dict())
    print(PromptInjectionDetector().detect("No canary here.").to_dict())


if __name__ == "__main__":
    main()
