"""The per-organization concurrency limit against a real Redis."""

import threading
import time
from collections.abc import Iterator

import pytest
from redis import Redis
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from app.integrations.trackers.limits import RedisSlotLimiter

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def redis() -> Iterator[Redis]:
    container = (
        DockerContainer("docker.io/library/redis:7-alpine")
        .with_exposed_ports(6379)
        .waiting_for(LogMessageWaitStrategy("Ready to accept connections"))
    )
    with container:
        # 127.0.0.1, not localhost: Podman on Windows forwards ports on IPv4 only.
        client = Redis(host="127.0.0.1", port=int(container.get_exposed_port(6379)))
        yield client
        client.close()


def test_never_more_than_the_limit_at_once(redis: Redis) -> None:
    limiter = RedisSlotLimiter(redis, "tt:test:limit", 2, poll_seconds=0.01)
    lock = threading.Lock()
    active, peak, done = 0, 0, 0

    def request() -> None:
        nonlocal active, peak, done
        with limiter.slot():
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.1)
            with lock:
                active -= 1
                done += 1

    threads = [threading.Thread(target=request) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert done == 6
    assert peak == 2


def test_slots_are_shared_by_every_limiter_for_the_organization(redis: Redis) -> None:
    first = RedisSlotLimiter.for_organization(redis, "https://dev.azure.com/Shared/", 1)
    second = RedisSlotLimiter.for_organization(redis, "https://dev.azure.com/shared", 1)
    other_org = RedisSlotLimiter.for_organization(redis, "https://dev.azure.com/other", 1)
    waits: list[float] = []
    blocked = RedisSlotLimiter(
        redis, "tt:azure:slots:https://dev.azure.com/shared", 1, sleep=waits.append
    )
    with first.slot():
        with other_org.slot():  # another organization has its own slots
            pass
        assert redis.zcard("tt:azure:slots:https://dev.azure.com/shared") == 1
        # A second worker for the same organization would have to wait.
        acquired = blocked._acquire(
            keys=["tt:azure:slots:https://dev.azure.com/shared"],
            args=[int(time.time() * 1000), 1, 120_000, "probe"],
        )
        assert acquired == 0
    with second.slot():  # released, so it is free again
        pass
    assert waits == []


def test_a_dead_workers_slot_expires(redis: Redis) -> None:
    key = "tt:test:lease"
    # A holder that took the slot 5 s ago and never released it (its worker died).
    redis.zadd(key, {"dead-worker": int(time.time() * 1000) - 5_000})
    limiter = RedisSlotLimiter(redis, key, 1, lease_ms=1_000, poll_seconds=0.01)
    started = time.monotonic()
    with limiter.slot():
        pass
    assert time.monotonic() - started < 1
    assert redis.zscore(key, "dead-worker") is None
