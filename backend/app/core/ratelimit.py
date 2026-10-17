"""Login rate limits: at most 5 attempts a minute per IP and per email (spec section 10).

Counters live in Redis, so the limit holds across API instances. If Redis is
unreachable the limit is not enforced (logins keep working) and a warning is logged.
"""

import logging
import time

from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

LOGIN_ATTEMPTS_PER_MINUTE = 5
WINDOW_SECONDS = 60


class LoginRateLimiter:
    def __init__(
        self, redis: Redis, *, limit: int = LOGIN_ATTEMPTS_PER_MINUTE, window: int = WINDOW_SECONDS
    ) -> None:
        self._redis = redis
        self._limit = limit
        self._window = window

    def hit(self, ip: str, email: str) -> int | None:
        """Count one attempt. Returns seconds to wait if a limit is exceeded, else None."""
        window = int(time.time()) // self._window
        keys = [f"tt:rl:login:ip:{ip}:{window}", f"tt:rl:login:email:{email.lower()}:{window}"]
        try:
            pipe = self._redis.pipeline()
            for key in keys:
                pipe.incr(key)
                pipe.expire(key, self._window * 2)
            counts = pipe.execute()[0::2]
        except RedisError:
            logger.warning("Login rate limit not enforced: Redis is unavailable")
            return None
        if any(int(count) > self._limit for count in counts):
            return self._window - int(time.time()) % self._window
        return None
