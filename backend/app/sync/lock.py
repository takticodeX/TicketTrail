"""One run per project at a time: the Redis lock tt:sync:<project_id> (spec section 7).

The lock's value is the run ID that holds it, so it can only be refreshed or
released by that run, and a run closed as stale can have its lock cleared.
It expires after 30 minutes unless refreshed by the run's heartbeat.
"""

import uuid
from typing import Protocol

from redis import Redis

LOCK_TTL_MS = 30 * 60 * 1000

_REFRESH = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


def lock_key(project_id: uuid.UUID) -> str:
    return f"tt:sync:{project_id}"


class ProjectLock(Protocol):
    def acquire(self, project_id: uuid.UUID, run_id: uuid.UUID) -> bool: ...

    def refresh(self, project_id: uuid.UUID, run_id: uuid.UUID) -> None: ...

    def release(self, project_id: uuid.UUID, run_id: uuid.UUID) -> None: ...


class RedisProjectLock:
    def __init__(self, redis: Redis, ttl_ms: int = LOCK_TTL_MS) -> None:
        self._redis = redis
        self._ttl_ms = ttl_ms
        self._refresh = redis.register_script(_REFRESH)
        self._release = redis.register_script(_RELEASE)

    def acquire(self, project_id: uuid.UUID, run_id: uuid.UUID) -> bool:
        return bool(self._redis.set(lock_key(project_id), str(run_id), nx=True, px=self._ttl_ms))

    def refresh(self, project_id: uuid.UUID, run_id: uuid.UUID) -> None:
        self._refresh(keys=[lock_key(project_id)], args=[str(run_id), self._ttl_ms])

    def release(self, project_id: uuid.UUID, run_id: uuid.UUID) -> None:
        self._release(keys=[lock_key(project_id)], args=[str(run_id)])


class NoLock:
    """For tools and tests that run without Redis."""

    def acquire(self, project_id: uuid.UUID, run_id: uuid.UUID) -> bool:
        return True

    def refresh(self, project_id: uuid.UUID, run_id: uuid.UUID) -> None:
        return None

    def release(self, project_id: uuid.UUID, run_id: uuid.UUID) -> None:
        return None
