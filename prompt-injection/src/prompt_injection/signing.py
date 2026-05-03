# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""HMAC signing and replay protection for MCP-style messages."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol


class MCPNonceStore(Protocol):
    """Nonce persistence protocol used for replay protection."""

    def has(self, nonce: str) -> bool: ...
    def add(self, nonce: str, expires_at: datetime) -> None: ...
    def cleanup(self) -> int: ...
    def count(self) -> int: ...


class InMemoryNonceStore:
    """Bounded in-memory nonce store."""

    def __init__(self, max_entries: int = 10_000) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self.max_entries = max_entries
        self._nonces: dict[str, datetime] = {}

    def has(self, nonce: str) -> bool:
        self.cleanup()
        return nonce in self._nonces

    def add(self, nonce: str, expires_at: datetime) -> None:
        self.cleanup()
        while len(self._nonces) >= self.max_entries:
            oldest = min(self._nonces, key=lambda key: self._nonces[key])
            self._nonces.pop(oldest, None)
        self._nonces[nonce] = expires_at

    def cleanup(self) -> int:
        now = _utcnow()
        expired = [nonce for nonce, expires_at in self._nonces.items() if expires_at <= now]
        for nonce in expired:
            self._nonces.pop(nonce, None)
        return len(expired)

    def count(self) -> int:
        self.cleanup()
        return len(self._nonces)


@dataclass(frozen=True)
class MCPSignedEnvelope:
    """A signed message envelope."""

    payload: str
    nonce: str
    timestamp: datetime
    signature: str
    sender_id: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "payload": self.payload,
            "nonce": self.nonce,
            "timestamp": self.timestamp.isoformat(),
            "signature": self.signature,
            "sender_id": self.sender_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "MCPSignedEnvelope":
        return cls(
            payload=str(data["payload"]),
            nonce=str(data["nonce"]),
            timestamp=_parse_datetime(str(data["timestamp"])),
            signature=str(data["signature"]),
            sender_id=None if data.get("sender_id") is None else str(data["sender_id"]),
        )


@dataclass(frozen=True)
class MCPVerificationResult:
    """Result of verifying a signed envelope."""

    is_valid: bool
    payload: str | None = None
    sender_id: str | None = None
    failure_reason: str | None = None

    @classmethod
    def success(cls, payload: str, sender_id: str | None) -> "MCPVerificationResult":
        return cls(is_valid=True, payload=payload, sender_id=sender_id)

    @classmethod
    def failed(cls, reason: str) -> "MCPVerificationResult":
        return cls(is_valid=False, failure_reason=reason)

    def to_dict(self) -> dict[str, object]:
        return {
            "is_valid": self.is_valid,
            "payload": self.payload,
            "sender_id": self.sender_id,
            "failure_reason": self.failure_reason,
        }


class MCPMessageSigner:
    """Sign and verify messages with replay protection."""

    def __init__(
        self,
        signing_key: bytes,
        *,
        replay_window: timedelta = timedelta(minutes=5),
        nonce_cache_cleanup_interval: timedelta = timedelta(minutes=10),
        max_nonce_cache_size: int = 10_000,
        nonce_store: MCPNonceStore | None = None,
    ) -> None:
        if signing_key is None:
            raise ValueError("signing_key must not be None")
        if len(signing_key) < 32:
            raise ValueError("signing_key must be at least 32 bytes")
        if replay_window <= timedelta(0):
            raise ValueError("replay_window must be positive")
        if nonce_cache_cleanup_interval <= timedelta(0):
            raise ValueError("nonce_cache_cleanup_interval must be positive")
        self._signing_key = signing_key
        self.replay_window = replay_window
        self.nonce_cache_cleanup_interval = nonce_cache_cleanup_interval
        self._nonce_store = nonce_store or InMemoryNonceStore(max_nonce_cache_size)
        self._lock = threading.Lock()
        self._last_cleanup = _utcnow()

    @classmethod
    def from_base64_key(cls, base64_key: str, **kwargs: object) -> "MCPMessageSigner":
        if not base64_key or not base64_key.strip():
            raise ValueError("base64_key must not be empty")
        return cls(base64.b64decode(base64_key.encode("ascii"), validate=True), **kwargs)

    @staticmethod
    def generate_key() -> bytes:
        return secrets.token_bytes(32)

    @property
    def cached_nonce_count(self) -> int:
        with self._lock:
            return self._nonce_store.count()

    def sign_message(self, payload: str, sender_id: str | None = None) -> MCPSignedEnvelope:
        if payload is None:
            raise ValueError("payload must not be None")
        if not payload.strip():
            raise ValueError("payload must not be empty")
        timestamp = _utcnow()
        nonce = uuid.uuid4().hex
        return MCPSignedEnvelope(
            payload=payload,
            nonce=nonce,
            timestamp=timestamp,
            sender_id=sender_id,
            signature=self._compute_signature(nonce, timestamp, sender_id, payload),
        )

    def verify_message(self, envelope: MCPSignedEnvelope) -> MCPVerificationResult:
        if envelope is None:
            raise ValueError("envelope must not be None")
        try:
            now = _utcnow()
            age = now - envelope.timestamp
            if age > self.replay_window or age < -self.replay_window:
                return MCPVerificationResult.failed("Message timestamp outside replay window.")
            expected = self._compute_signature(
                envelope.nonce,
                envelope.timestamp,
                envelope.sender_id,
                envelope.payload,
            )
            if not hmac.compare_digest(expected, envelope.signature):
                return MCPVerificationResult.failed("Invalid signature.")
            with self._lock:
                self._maybe_cleanup_locked(now)
                if self._nonce_store.has(envelope.nonce):
                    return MCPVerificationResult.failed("Duplicate nonce (replay detected).")
                self._nonce_store.add(envelope.nonce, envelope.timestamp + self.replay_window)
            return MCPVerificationResult.success(envelope.payload, envelope.sender_id)
        except Exception as exc:
            return MCPVerificationResult.failed(f"Verification error (fail-closed): {exc}")

    def cleanup_nonce_cache(self) -> int:
        with self._lock:
            return self._cleanup_nonce_cache_locked(_utcnow())

    def _compute_signature(
        self,
        nonce: str,
        timestamp: datetime,
        sender_id: str | None,
        payload: str,
    ) -> str:
        canonical = self._build_canonical_string(nonce, timestamp, sender_id, payload)
        digest = hmac.new(self._signing_key, canonical.encode("utf-8"), hashlib.sha256).digest()
        return base64.b64encode(digest).decode("ascii")

    @staticmethod
    def _build_canonical_string(
        nonce: str,
        timestamp: datetime,
        sender_id: str | None,
        payload: str,
    ) -> str:
        timestamp_ms = int(timestamp.timestamp() * 1000)
        return f"{nonce}|{timestamp_ms}|{sender_id or ''}|{payload}"

    def _maybe_cleanup_locked(self, now: datetime) -> None:
        if now - self._last_cleanup >= self.nonce_cache_cleanup_interval:
            self._cleanup_nonce_cache_locked(now)

    def _cleanup_nonce_cache_locked(self, now: datetime) -> int:
        expired = self._nonce_store.cleanup()
        self._last_cleanup = now
        return expired


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
