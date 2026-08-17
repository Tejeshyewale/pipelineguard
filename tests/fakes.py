"""Fake RocketRide client for unit tests.

Mirrors the *shape* of `rocketride.RocketRideClient` (async context
manager, `use`/`send`/`get_task_status`/`terminate`) without needing a
live server. Each fake client is configured with a scripted outcome so
tests can deterministically simulate a provider failing.
"""


class FakeExecutionException(Exception):
    """Stand-in for rocketride.core.exceptions.ExecutionException."""


class FakeClient:
    """One scripted fake client instance, used as an async context manager."""

    def __init__(self, should_fail: bool = False, latency_s: float = 0.0):
        self.should_fail = should_fail
        self.latency_s = latency_s
        self.terminated_token = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False

    async def use(self, filepath=None, pipeline=None, **kwargs):
        return {"token": f"tok-{filepath}"}

    async def send(self, token, data, objinfo=None, mimetype=None):
        if self.latency_s:
            import asyncio
            await asyncio.sleep(self.latency_s)
        if self.should_fail:
            raise FakeExecutionException(f"simulated failure for {token}")
        return {"name": "response_text_1", "path": [], "objectId": "obj-1",
                "data": {"answer": f"summary of: {data[:30]}..."}}

    async def get_task_status(self, token):
        return {"completedCount": 1, "totalCount": 1, "completed": True,
                "state": "completed", "exitCode": 0}

    async def terminate(self, token):
        self.terminated_token = token


def make_factory(outcomes):
    """Build a client_factory that returns FakeClients in sequence.

    Args:
        outcomes: list of bools, one per call to the factory -- True means
            that attempt should fail. Extra calls beyond the list reuse
            the last entry.
    """
    calls = {"count": 0}

    def factory():
        idx = min(calls["count"], len(outcomes) - 1)
        should_fail = outcomes[idx]
        calls["count"] += 1
        return FakeClient(should_fail=should_fail)

    return factory
