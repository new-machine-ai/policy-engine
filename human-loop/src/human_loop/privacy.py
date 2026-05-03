# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Privacy helpers for audit-safe metadata."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def payload_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def summarize_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "keys": sorted(str(key) for key in context),
        "size": len(context),
        "classification": str(context.get("classification", ""))[:64] if "classification" in context else "",
    }
