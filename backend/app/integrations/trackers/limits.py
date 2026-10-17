"""At most N concurrent requests per Azure organization, across all workers (spec section 6)."""

import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Protocol

from redis import Redis


class ConcurrencyLimiter(Protocol):
    def slot(self) -> AbstractContextManager[None]:
        """Hold one of the slots for the duration of a request."""
        ...


class NoLimit:
    @contextmanager
    def slot(self) -> Iterator[None]:
        yield


# A sorted set of slot holders, scored by when they took the slot. Holders older
# than the lease are dropped, so a worker that dies holding a slot can't leak it.
_ACQUIRE = """
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', tonumber(ARGV[1]) - tonumber(ARGV[3]))
if redis.call('ZCARD', KEYS[1]) < tonumber(ARGV[2]) then
  redis.call('ZADD', KEYS[1], ARGV[1], ARGV[4])
  redis.call('PEXPIRE', KEYS[1], ARGV[3])
  return 1
end
return 0
"""


class RedisSlotLimiter:
    def __init__(
        self,
        redis: Redis,
        key: str,
        limit: int,
        *,
        lease_ms: int = 120_000,
        poll_seconds: float = 0.05,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._redis = redis
        self._key = key
        self._limit = limit
        self._lease_ms = lease_ms
        self._poll = poll_seconds
        self._sleep = sleep
        self._acquire = redis.register_script(_ACQUIRE)

    @classmethod
    def for_organization(
        cls, redis: Redis, organization_url: str, limit: int
    ) -> "RedisSlotLimiter":
        return cls(redis, f"tt:azure:slots:{organization_url.lower().rstrip('/')}", limit)

    @contextmanager
    def slot(self) -> Iterator[None]:
        token = uuid.uuid4().hex
        while not self._acquire(
            keys=[self._key], args=[int(time.time() * 1000), self._limit, self._lease_ms, token]
        ):
            self._sleep(self._poll)
        try:
            yield
        finally:
            self._redis.zrem(self._key, token)
