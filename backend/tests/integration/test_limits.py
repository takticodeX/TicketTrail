"""The per-organization concurrency limit and the project lock, against a real Redis."""

import threading
import time
import uuid

from redis import Redis

from app.integrations.trackers.limits import RedisSlotLimiter
from app.sync.lock import RedisProjectLock, lock_key


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


def test_slots_are_shared_per_organization(redis: Redis) -> None:
    first = RedisSlotLimiter.for_organization(redis, "https://dev.azure.com/Shared/", 1)
    other_org = RedisSlotLimiter.for_organization(redis, "https://dev.azure.com/other", 1)
    key = "tt:azure:slots:https://dev.azure.com/shared"
    with first.slot():
        with other_org.slot():  # another organization has its own slots
            pass
        assert redis.zcard(key) == 1
        # A second worker for the same organization (any spelling) would have to wait.
        probe = redis.register_script(
            "return redis.call('ZCARD', KEYS[1]) < tonumber(ARGV[1]) and 1 or 0"
        )
        assert probe(keys=[key], args=[1]) == 0
    assert redis.zcard(key) == 0


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


def test_project_lock_is_held_by_one_run(redis: Redis) -> None:
    lock = RedisProjectLock(redis)
    project, run_a, run_b = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert lock.acquire(project, run_a)
    assert not lock.acquire(project, run_b)
    lock.release(project, run_b)  # not the holder: no effect
    assert redis.get(lock_key(project)) == str(run_a).encode()
    lock.release(project, run_a)
    assert lock.acquire(project, run_b)


def test_project_lock_expires_after_30_minutes_unless_refreshed(redis: Redis) -> None:
    lock = RedisProjectLock(redis)
    project, run = uuid.uuid4(), uuid.uuid4()
    lock.acquire(project, run)
    ttl = redis.pttl(lock_key(project))
    assert 29 * 60_000 < ttl <= 30 * 60_000
    redis.pexpire(lock_key(project), 1_000)
    lock.refresh(project, run)  # the heartbeat
    assert redis.pttl(lock_key(project)) > 29 * 60_000
    lock.refresh(project, uuid.uuid4())  # someone else can't extend it
    assert redis.get(lock_key(project)) == str(run).encode()
