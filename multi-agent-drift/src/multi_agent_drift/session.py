# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Session isolation, intent locks, and vector clocks."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class IsolationLevel(str, Enum):
    """Session isolation levels."""

    SNAPSHOT = "snapshot"
    READ_COMMITTED = "read_committed"
    SERIALIZABLE = "serializable"

    @property
    def requires_vector_clocks(self) -> bool:
        return self in (IsolationLevel.SNAPSHOT, IsolationLevel.SERIALIZABLE)

    @property
    def requires_intent_locks(self) -> bool:
        return self in (IsolationLevel.READ_COMMITTED, IsolationLevel.SERIALIZABLE)

    @property
    def allows_concurrent_writes(self) -> bool:
        return self != IsolationLevel.SERIALIZABLE

    @property
    def coordination_cost(self) -> str:
        return {
            IsolationLevel.SNAPSHOT: "medium",
            IsolationLevel.READ_COMMITTED: "medium",
            IsolationLevel.SERIALIZABLE: "high",
        }[self]


class LockIntent(str, Enum):
    """Types of lock intent."""

    READ = "read"
    WRITE = "write"
    EXCLUSIVE = "exclusive"


@dataclass
class IntentLock:
    """A declared resource lock."""

    lock_id: str = field(default_factory=lambda: f"lock:{uuid.uuid4().hex[:8]}")
    agent_did: str = ""
    session_id: str = ""
    resource_path: str = ""
    intent: LockIntent = LockIntent.READ
    acquired_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    is_active: bool = True
    saga_step_id: str | None = None


class LockContentionError(Exception):
    """Raised when lock contention is detected."""


class DeadlockError(Exception):
    """Raised when a deadlock is detected."""


class IntentLockManager:
    """Resource lock manager with read/write/exclusive contention checks."""

    def __init__(self) -> None:
        self._locks: dict[str, IntentLock] = {}
        self._lock = threading.Lock()

    def acquire(
        self,
        agent_did: str,
        session_id: str,
        resource_path: str,
        intent: LockIntent,
        saga_step_id: str | None = None,
    ) -> IntentLock:
        with self._lock:
            conflicts = self._conflicts(agent_did, session_id, resource_path, intent)
            if conflicts:
                holders = ", ".join(sorted({lock.agent_did for lock in conflicts}))
                raise LockContentionError(
                    f"{intent.value} lock for {resource_path!r} conflicts with active lock(s) held by {holders}"
                )
            lock = IntentLock(
                agent_did=agent_did,
                session_id=session_id,
                resource_path=resource_path,
                intent=intent,
                saga_step_id=saga_step_id,
            )
            self._locks[lock.lock_id] = lock
            return lock

    def release(self, lock_id: str) -> None:
        with self._lock:
            lock = self._locks.get(lock_id)
            if lock is not None:
                lock.is_active = False

    def release_agent_locks(self, agent_did: str, session_id: str) -> int:
        with self._lock:
            count = 0
            for lock in self._locks.values():
                if lock.agent_did == agent_did and lock.session_id == session_id and lock.is_active:
                    lock.is_active = False
                    count += 1
            return count

    def release_session_locks(self, session_id: str) -> int:
        with self._lock:
            count = 0
            for lock in self._locks.values():
                if lock.session_id == session_id and lock.is_active:
                    lock.is_active = False
                    count += 1
            return count

    def get_agent_locks(self, agent_did: str, session_id: str) -> list[IntentLock]:
        with self._lock:
            return [
                lock
                for lock in self._locks.values()
                if lock.agent_did == agent_did and lock.session_id == session_id and lock.is_active
            ]

    def get_resource_locks(self, resource_path: str) -> list[IntentLock]:
        with self._lock:
            return [
                lock
                for lock in self._locks.values()
                if lock.resource_path == resource_path and lock.is_active
            ]

    @property
    def active_lock_count(self) -> int:
        with self._lock:
            return sum(1 for lock in self._locks.values() if lock.is_active)

    @property
    def contention_points(self) -> list[str]:
        with self._lock:
            points = []
            for path in sorted({lock.resource_path for lock in self._locks.values() if lock.is_active}):
                active = [lock for lock in self._locks.values() if lock.resource_path == path and lock.is_active]
                if len(active) > 1:
                    points.append(path)
            return points

    def _conflicts(
        self,
        agent_did: str,
        session_id: str,
        resource_path: str,
        intent: LockIntent,
    ) -> list[IntentLock]:
        conflicts: list[IntentLock] = []
        for lock in self._locks.values():
            if not lock.is_active or lock.resource_path != resource_path:
                continue
            if lock.agent_did == agent_did and lock.session_id == session_id:
                continue
            if intent == LockIntent.READ and lock.intent == LockIntent.READ:
                continue
            conflicts.append(lock)
        return conflicts


class CausalViolationError(Exception):
    """Raised when a write would violate causal ordering."""


@dataclass
class VectorClock:
    """Thread-safe vector clock."""

    clocks: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def tick(self, agent_did: str) -> None:
        with self._lock:
            self.clocks[agent_did] = self.clocks.get(agent_did, 0) + 1

    def get(self, agent_did: str) -> int:
        with self._lock:
            return self.clocks.get(agent_did, 0)

    def merge(self, other: "VectorClock") -> "VectorClock":
        left, right = self._snapshots(other)
        merged = dict(left)
        for agent, value in right.items():
            merged[agent] = max(merged.get(agent, 0), value)
        return VectorClock(clocks=merged)

    def happens_before(self, other: "VectorClock") -> bool:
        left, right = self._snapshots(other)
        agents = set(left) | set(right)
        return all(left.get(agent, 0) <= right.get(agent, 0) for agent in agents) and any(
            left.get(agent, 0) < right.get(agent, 0) for agent in agents
        )

    def is_concurrent(self, other: "VectorClock") -> bool:
        return self != other and not self.happens_before(other) and not other.happens_before(self)

    def copy(self) -> "VectorClock":
        with self._lock:
            return VectorClock(clocks=dict(self.clocks))

    def is_empty(self) -> bool:
        with self._lock:
            return not self.clocks

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VectorClock):
            return False
        left, right = self._snapshots(other)
        agents = set(left) | set(right)
        return all(left.get(agent, 0) == right.get(agent, 0) for agent in agents)

    def _snapshots(self, other: "VectorClock") -> tuple[dict[str, int], dict[str, int]]:
        if self is other:
            with self._lock:
                snapshot = dict(self.clocks)
            return snapshot, dict(snapshot)
        first, second = sorted([self, other], key=id)
        with first._lock:
            with second._lock:
                return dict(self.clocks), dict(other.clocks)


class VectorClockManager:
    """Vector clock manager with causal write checks."""

    def __init__(self) -> None:
        self._path_clocks: dict[str, VectorClock] = {}
        self._agent_clocks: dict[str, VectorClock] = {}
        self._conflict_count = 0

    def read(self, path: str, agent_did: str) -> VectorClock:
        path_clock = self._path_clocks.get(path, VectorClock()).copy()
        agent_clock = self._agent_clocks.get(agent_did, VectorClock()).merge(path_clock)
        self._agent_clocks[agent_did] = agent_clock
        return path_clock

    def write(self, path: str, agent_did: str, strict: bool = True) -> VectorClock:
        current_path_clock = self._path_clocks.get(path, VectorClock())
        agent_clock = self._agent_clocks.get(agent_did, VectorClock())
        if strict and not current_path_clock.is_empty():
            has_seen_current = current_path_clock == agent_clock or current_path_clock.happens_before(agent_clock)
            if not has_seen_current:
                self._conflict_count += 1
                raise CausalViolationError(
                    f"Agent {agent_did} has not observed latest clock for {path}"
                )
        agent_clock = agent_clock.copy()
        agent_clock.tick(agent_did)
        self._agent_clocks[agent_did] = agent_clock
        self._path_clocks[path] = agent_clock.copy()
        return self._path_clocks[path].copy()

    def get_path_clock(self, path: str) -> VectorClock:
        return self._path_clocks.get(path, VectorClock()).copy()

    def get_agent_clock(self, agent_did: str) -> VectorClock:
        return self._agent_clocks.get(agent_did, VectorClock()).copy()

    @property
    def conflict_count(self) -> int:
        return self._conflict_count

    @property
    def tracked_paths(self) -> int:
        return len(self._path_clocks)
