"""Core PipelineGuard implementation.

PipelineGuard.run() drives one logical task through a ranked list of
Variants, using the real `rocketride` SDK underneath:

    result["token"] = await client.use(filepath=variant.filepath)
    out              = await client.send(token, payload, ...)
    await client.terminate(token)

If `use()`/`send()` raises one of the SDK's documented exceptions
(ExecutionException, PipeException, ConnectionException, ...), or the
task status reports failure, PipelineGuard records the failure against
that variant, re-scores the scoreboard, and tries the next-best variant
-- instead of the caller's pipeline crashing outright.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Dict, List, Optional

from .exceptions import AllVariantsFailedError
from .variants import Variant, VariantScoreboard
from .logger import logger


@dataclass
class RunAttempt:
    """Record of one variant attempt within a PipelineGuard.run() call."""

    variant: str
    ok: bool
    latency_s: float
    error: Optional[str] = None


@dataclass
class RunReport:
    """Full outcome of a PipelineGuard.run() call, success or failure."""

    ok: bool
    variant_used: Optional[str]
    result: Optional[dict]
    attempts: List[RunAttempt] = field(default_factory=list)

    @property
    def failover_count(self) -> int:
        """How many variants failed before one succeeded (or all did)."""
        return sum(1 for a in self.attempts if not a.ok)


class PipelineGuard:
    """Wraps a RocketRideClient factory with cost-aware failover.

    Args:
        client_factory: a zero-arg callable returning a fresh, already
            *connected* `rocketride.RocketRideClient`-compatible object
            (or an async context manager). Injected rather than
            constructed here so tests can pass in a fake client and the
            real code never has to know the difference.
        variants: candidate ways to run the task, best-guess order aside
            -- the scoreboard decides real ordering after the first run.
        max_attempts: hard cap on variants tried per `run()` call, even
            if more are configured (defaults to len(variants)).
        per_attempt_timeout_s: soft budget per variant before it's
            treated as a failure and the next variant is tried.
    """

    def __init__(
        self,
        client_factory,
        variants: List[Variant],
        max_attempts: Optional[int] = None,
        per_attempt_timeout_s: float = 30.0,
        persistence_file: Optional[str] = None,
    ):
        self.client_factory = client_factory
        self.scoreboard = VariantScoreboard(variants, persistence_file=persistence_file)
        self.max_attempts = max_attempts or len(variants)
        self.per_attempt_timeout_s = per_attempt_timeout_s
        self._on_failover_hooks = []
        self._on_success_hooks = []
        self._on_cooldown_start_hooks = []
        self._on_cooldown_end_hooks = []
        self._cooldown_state = {v.name: False for v in variants}

    def on_failover(self, callback):
        """Register a callback(variant_name, error) fired on each failover.

        Use this to post a Discord/Slack alert, without PipelineGuard
        needing to know anything about your notification stack.
        """
        self._on_failover_hooks.append(callback)
        return callback

    def on_success(self, callback):
        """Register a callback(variant_name, result) fired on each success."""
        self._on_success_hooks.append(callback)
        return callback

    def on_cooldown_start(self, callback):
        """Register a callback(variant_name) fired when a variant enters cooldown."""
        self._on_cooldown_start_hooks.append(callback)
        return callback

    def on_cooldown_end(self, callback):
        """Register a callback(variant_name) fired when a variant exits cooldown."""
        self._on_cooldown_end_hooks.append(callback)
        return callback

    async def run(self, payload: Any, objinfo: Optional[dict] = None,
                   mimetype: Optional[str] = None) -> RunReport:
        """Run `payload` through the best-ranked variant, failing over as needed."""
        
        for name in self.scoreboard.variants:
            was_in_cooldown = self._cooldown_state.get(name, False)
            is_in_cooldown = self.scoreboard._in_cooldown(name)
            if was_in_cooldown and not is_in_cooldown:
                self._cooldown_state[name] = False
                logger.info(
                    "pipelineguard: variant '%s' exited cooldown", name,
                    extra={"variant": name, "event_type": "cooldown_end"}
                )
                for hook in self._on_cooldown_end_hooks:
                    try:
                        hook(name)
                    except Exception:
                        logger.exception("pipelineguard: on_cooldown_end hook raised")
                        
        attempts: List[RunAttempt] = []
        ranked = self.scoreboard.ranked()[: self.max_attempts]

        for variant_name in ranked:
            variant = self.scoreboard.variants[variant_name]
            logger.info(
                "pipelineguard: selected variant '%s'", variant_name,
                extra={"variant": variant_name, "event_type": "variant_selected"}
            )
            started = monotonic()
            try:
                result = await asyncio.wait_for(
                    self._run_one(variant, payload, objinfo, mimetype),
                    timeout=self.per_attempt_timeout_s,
                )
                latency = monotonic() - started
                self.scoreboard.record_success(variant_name, latency)
                attempts.append(RunAttempt(variant_name, ok=True, latency_s=latency))
                logger.info(
                    "pipelineguard: '%s' succeeded in %.2fs (attempt %d/%d)",
                    variant_name, latency, len(attempts), len(ranked),
                    extra={
                        "variant": variant_name,
                        "event_type": "run_success",
                        "latency_ms": int(latency * 1000),
                        "outcome": "success"
                    }
                )
                for hook in self._on_success_hooks:
                    try:
                        hook(variant_name, result)
                    except Exception:
                        logger.exception("pipelineguard: on_success hook raised")
                return RunReport(
                    ok=True,
                    variant_used=variant_name,
                    result=result,
                    attempts=attempts,
                )
            except Exception as exc:  # noqa: BLE001 - deliberately broad; see module docstring
                latency = monotonic() - started
                self.scoreboard.record_failure(variant_name)
                attempts.append(
                    RunAttempt(variant_name, ok=False, latency_s=latency, error=str(exc))
                )
                logger.warning(
                    "pipelineguard: '%s' failed after %.2fs (%s) -- failing over",
                    variant_name, latency, exc,
                    extra={
                        "variant": variant_name,
                        "event_type": "run_failure",
                        "latency_ms": int(latency * 1000),
                        "outcome": "failure",
                        "error": str(exc)
                    }
                )
                
                logger.warning(
                    "pipelineguard: failover triggered from '%s'", variant_name,
                    extra={"variant": variant_name, "event_type": "failover_triggered"}
                )
                
                if self.scoreboard._in_cooldown(variant_name) and not self._cooldown_state.get(variant_name, False):
                    self._cooldown_state[variant_name] = True
                    logger.info(
                        "pipelineguard: variant '%s' entered cooldown", variant_name,
                        extra={"variant": variant_name, "event_type": "cooldown_start"}
                    )
                    for hook in self._on_cooldown_start_hooks:
                        try:
                            hook(variant_name)
                        except Exception:
                            logger.exception("pipelineguard: on_cooldown_start hook raised")
                            
                for hook in self._on_failover_hooks:
                    try:
                        hook(variant_name, exc)
                    except Exception:  # noqa: BLE001 - a bad hook must not break failover
                        logger.exception("pipelineguard: on_failover hook raised")
                continue

        raise AllVariantsFailedError(
            f"All {len(ranked)} variant(s) failed for this run: "
            f"{[a.variant for a in attempts]}",
            attempts=attempts,
        )

    async def _run_one(self, variant: Variant, payload: Any,
                        objinfo: Optional[dict], mimetype: Optional[str]) -> dict:
        """Execute a single variant end-to-end via the RocketRide SDK."""
        client_cm = self.client_factory()
        async with client_cm as client:
            use_result = await client.use(filepath=variant.filepath)
            token = use_result["token"]
            try:
                out = await client.send(
                    token, payload, objinfo=objinfo, mimetype=mimetype
                )
                status = await client.get_task_status(token)
                if status.get("state") == "failed" or status.get("exitCode", 0) not in (0, None):
                    raise RuntimeError(f"pipeline reported failure: {status}")
                return {"output": out, "status": status, "variant": variant.name}
            finally:
                try:
                    await client.terminate(token)
                except Exception as e:
                    logger.warning("pipelineguard: failed to terminate token %s: %s", token, e)

    def health(self) -> Dict[str, dict]:
        """Snapshot of current variant scores -- feed this to a dashboard."""
        return self.scoreboard.summary()
