# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Audit sink contracts for MCP security components."""

from __future__ import annotations

import threading
from typing import Any, Protocol


class AuditSink(Protocol):
    """Persistence contract for structured audit records."""

    def record(self, entry: dict[str, Any]) -> None:
        """Persist one structured audit entry."""


class InMemoryAuditSink:
    """Thread-safe in-memory audit sink used by tests and demos."""

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def record(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self._entries.append(dict(entry))

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(entry) for entry in self._entries]

