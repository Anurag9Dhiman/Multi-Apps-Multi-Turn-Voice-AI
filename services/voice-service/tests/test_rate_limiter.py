import asyncio

from voice_service.rate_limiter import InMemoryRateLimiter


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_allows_up_to_capacity_in_a_burst():
    clock = _FakeClock()
    limiter = InMemoryRateLimiter(capacity=3, refill_rate=1.0, clock=clock)

    async def scenario():
        return [await limiter.allow("u1") for _ in range(3)]

    assert asyncio.run(scenario()) == [True, True, True]


def test_denies_once_capacity_is_exhausted():
    clock = _FakeClock()
    limiter = InMemoryRateLimiter(capacity=2, refill_rate=1.0, clock=clock)

    async def scenario():
        return [await limiter.allow("u1") for _ in range(3)]

    assert asyncio.run(scenario()) == [True, True, False]


def test_refills_over_time():
    clock = _FakeClock()
    limiter = InMemoryRateLimiter(capacity=1, refill_rate=1.0, clock=clock)

    async def scenario():
        first = await limiter.allow("u1")
        immediately_after = await limiter.allow("u1")
        clock.advance(1.0)  # one full token's worth of refill
        after_refill = await limiter.allow("u1")
        return first, immediately_after, after_refill

    assert asyncio.run(scenario()) == (True, False, True)


def test_buckets_are_independent_per_key():
    clock = _FakeClock()
    limiter = InMemoryRateLimiter(capacity=1, refill_rate=1.0, clock=clock)

    async def scenario():
        u1_first = await limiter.allow("u1")
        u1_second = await limiter.allow("u1")  # exhausted
        u2_first = await limiter.allow("u2")  # different user, fresh bucket
        return u1_first, u1_second, u2_first

    assert asyncio.run(scenario()) == (True, False, True)


def test_refill_never_exceeds_capacity():
    clock = _FakeClock()
    limiter = InMemoryRateLimiter(capacity=2, refill_rate=1.0, clock=clock)

    async def scenario():
        await limiter.allow("u1")
        clock.advance(1000.0)  # way more than enough to overfill if unbounded
        results = [await limiter.allow("u1") for _ in range(3)]
        return results

    # capacity=2, one token already spent above -- only 2 more should be allowed.
    assert asyncio.run(scenario()) == [True, True, False]
