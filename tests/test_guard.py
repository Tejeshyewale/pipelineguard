"""
Unit tests for PipelineGuard's failover and scoring logic.

These run with zero external dependencies (no live RocketRide server,
no API keys) by substituting a FakeClient for the real
`rocketride.RocketRideClient`. This is what proves the *decision logic*
(when to fail over, which variant to pick next, how scores update) is
correct, independent of network/server availability.

Run with:  pytest tests/ -v
"""

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipelineguard import PipelineGuard, Variant, AllVariantsFailedError
from pipelineguard.variants import VariantScoreboard
from tests.fakes import make_factory


def variants():
    return [
        Variant(name="primary", filepath="pipelines/summarize_openai.pipe",
                relative_cost=1.0, quality=1.0),
        Variant(name="backup", filepath="pipelines/summarize_anthropic.pipe",
                relative_cost=1.1, quality=1.05),
        Variant(name="cheap", filepath="pipelines/summarize_local.pipe",
                relative_cost=0.1, quality=0.8),
    ]


@pytest.mark.asyncio
async def test_first_variant_succeeds_no_failover():
    guard = PipelineGuard(make_factory([False]), variants())
    report = await guard.run("hello world")
    assert report.ok is True
    assert report.failover_count == 0
    assert len(report.attempts) == 1


@pytest.mark.asyncio
async def test_first_variant_fails_second_succeeds():
    # primary fails, backup or cheap (whichever ranks next) succeeds
    guard = PipelineGuard(make_factory([True, False, False]), variants())
    report = await guard.run("hello world")
    assert report.ok is True
    assert report.failover_count == 1
    assert report.attempts[0].ok is False
    assert report.attempts[-1].ok is True


@pytest.mark.asyncio
async def test_all_variants_fail_raises():
    guard = PipelineGuard(make_factory([True, True, True]), variants())
    with pytest.raises(AllVariantsFailedError) as excinfo:
        await guard.run("hello world")
    assert len(excinfo.value.attempts) == 3
    assert all(not a.ok for a in excinfo.value.attempts)


@pytest.mark.asyncio
async def test_failover_hook_is_called_on_each_failure():
    guard = PipelineGuard(make_factory([True, False]), variants())
    seen = []

    @guard.on_failover
    def hook(name, err):
        seen.append(name)

    await guard.run("hello world")
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_repeated_failures_deprioritize_a_variant():
    """After a variant fails a few times in a row, it should score lower
    than a same-cost variant with a clean record, even if it was
    configured first. (Compares primary vs backup only -- the much
    cheaper 'cheap' variant is intentionally excluded here since cost
    alone can outrank an untested variant; that's covered separately by
    test_score_prefers_cheaper_variant_at_equal_reliability.)
    """
    board = VariantScoreboard(variants())
    board.record_failure("primary")
    board.record_failure("primary")
    board.record_success("backup", latency_s=0.5)

    assert board.score("backup") > board.score("primary")


def test_scoreboard_rejects_empty_variant_list():
    with pytest.raises(ValueError):
        VariantScoreboard([])


def test_score_prefers_cheaper_variant_at_equal_reliability():
    vs = [
        Variant(name="pricey", filepath="a.pipe", relative_cost=2.0, quality=1.0),
        Variant(name="cheap", filepath="b.pipe", relative_cost=0.5, quality=1.0),
    ]
    board = VariantScoreboard(vs)
    # No runs yet -- both start with the same optimistic reliability prior,
    # so cost alone should decide the order.
    assert board.score("cheap") > board.score("pricey")
