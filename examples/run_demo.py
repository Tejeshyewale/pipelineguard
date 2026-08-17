"""
End-to-end example: PipelineGuard protecting a summarization task.

This is what a real caller's code looks like. It needs a running
RocketRide server (local Docker, on-prem, or RocketRide Cloud) and API
keys for at least one provider set as env vars -- see README.md.

    export ROCKETRIDE_URI="ws://localhost:5565"
    export ROCKETRIDE_APIKEY="your-key"
    python examples/run_demo.py
"""

import asyncio
import logging
import os

from rocketride import RocketRideClient

from pipelineguard import PipelineGuard, Variant

logging.basicConfig(level=logging.INFO, format="%(message)s")


def make_client():
    """Factory PipelineGuard calls before every attempt.

    A fresh client per attempt keeps failed connections from poisoning
    the next try, and matches the SDK's recommended
    `async with RocketRideClient(...) as client:` pattern.
    """
    return RocketRideClient(
        uri=os.environ.get("ROCKETRIDE_URI", ""),
        auth=os.environ.get("ROCKETRIDE_APIKEY", ""),
    )


async def main():
    variants = [
        Variant(name="openai", filepath="pipelines/summarize_openai.pipe",
                relative_cost=1.0, quality=1.0),
        Variant(name="anthropic", filepath="pipelines/summarize_anthropic.pipe",
                relative_cost=1.1, quality=1.05),
        Variant(name="local", filepath="pipelines/summarize_local.pipe",
                relative_cost=0.1, quality=0.8),
    ]

    guard = PipelineGuard(client_factory=make_client, variants=variants)

    @guard.on_failover
    def alert(variant_name, error):
        # Swap this for a real Discord/Slack webhook call in production.
        print(f"[ALERT] variant '{variant_name}' failed: {error}. Failing over...")

    text = (
        "RocketRide lets you build AI pipelines as portable JSON, run by a "
        "high-performance C++ engine, with 50+ nodes across 13 LLM providers "
        "and 8 vector databases."
    )

    report = await guard.run(text, objinfo={"name": "input.txt"}, mimetype="text/plain")

    print("\n--- Run report ---")
    print("success:", report.ok)
    print("variant used:", report.variant_used)
    print("failovers before success:", report.failover_count)
    for a in report.attempts:
        status = "OK" if a.ok else f"FAILED ({a.error})"
        print(f"  - {a.variant}: {status} in {a.latency_s:.2f}s")

    print("\n--- Scoreboard ---")
    for name, stats in guard.health().items():
        print(f"  {name}: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
