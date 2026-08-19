"""Variants and the reliability scoreboard.

A "Variant" is one way of running a logical task: a specific `.pipe` file
(e.g. one wired to OpenAI, another wired to Anthropic, another to a local
model) plus metadata about its relative cost and quality. PipelineGuard
picks *which* variant to try next based on a running score, not a fixed
priority order -- that's what makes the failover cost-aware instead of
"just pick the next one in the list."
"""

from dataclasses import dataclass, field
from time import monotonic
from typing import Dict, List, Optional
import json
import os
import yaml


@dataclass
class Variant:
    """One candidate way of running a pipeline task.

    Args:
        name: short unique identifier, e.g. "openai-gpt", "anthropic-claude".
        filepath: path to the .pipe file that implements this variant.
        relative_cost: rough cost weight (1.0 = baseline). Higher = pricier.
        quality: rough quality weight (1.0 = baseline). Higher = better.
    """

    name: str
    filepath: str
    relative_cost: float = 1.0
    quality: float = 1.0


def load_variants_from_yaml(filepath: str) -> List[Variant]:
    """Load variants from a YAML configuration file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    
    variants = []
    for item in data.get('variants', []):
        variants.append(Variant(
            name=item['name'],
            filepath=item['filepath'],
            relative_cost=item.get('relative_cost', 1.0),
            quality=item.get('quality', 1.0)
        ))
    return variants


@dataclass
class VariantStats:
    """Rolling reliability stats for a single variant."""

    successes: int = 0
    failures: int = 0
    total_latency_s: float = 0.0
    last_failure_at: Optional[float] = None
    consecutive_failures: int = 0

    @property
    def attempts(self) -> int:
        return self.successes + self.failures

    @property
    def success_rate(self) -> float:
        if self.attempts == 0:
            return 1.0  # optimistic prior -- untested variants get a fair shot
        return self.successes / self.attempts

    @property
    def avg_latency_s(self) -> float:
        if self.successes == 0:
            return 0.0
        return self.total_latency_s / self.successes


class VariantScoreboard:
    """Tracks outcomes per variant and ranks them for selection.

    The score is a simple, explainable heuristic on purpose -- this is a
    reliability router, not a research project, and an evaluator should be
    able to read `score()` in ten seconds and know exactly why a variant
    was chosen.
    """

    # How long a variant is "cooled down" (deprioritized) after a failure,
    # in seconds. Prevents hammering a provider that just errored.
    COOLDOWN_S = 30.0

    def __init__(self, variants: List[Variant], persistence_file: Optional[str] = None):
        if not variants:
            raise ValueError("VariantScoreboard needs at least one variant")
        self.variants: Dict[str, Variant] = {v.name: v for v in variants}
        self.stats: Dict[str, VariantStats] = {v.name: VariantStats() for v in variants}
        self.persistence_file = persistence_file
        if self.persistence_file:
            self._load()

    def _save(self) -> None:
        if not self.persistence_file:
            return
        data = {}
        for name, s in self.stats.items():
            data[name] = {
                "successes": s.successes,
                "failures": s.failures,
                "total_latency_s": s.total_latency_s,
                "last_failure_at": s.last_failure_at,
                "consecutive_failures": s.consecutive_failures,
            }
        with open(self.persistence_file, 'w', encoding='utf-8') as f:
            json.dump(data, f)

    def _load(self) -> None:
        if not os.path.exists(self.persistence_file):
            return
        try:
            with open(self.persistence_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for name, s_data in data.items():
                if name in self.stats:
                    s = self.stats[name]
                    s.successes = s_data.get("successes", 0)
                    s.failures = s_data.get("failures", 0)
                    s.total_latency_s = s_data.get("total_latency_s", 0.0)
                    s.last_failure_at = s_data.get("last_failure_at")
                    s.consecutive_failures = s_data.get("consecutive_failures", 0)
        except Exception:
            pass  # Fallback to empty stats on load failure

    def record_success(self, name: str, latency_s: float) -> None:
        s = self.stats[name]
        s.successes += 1
        s.total_latency_s += latency_s
        s.consecutive_failures = 0
        self._save()

    def record_failure(self, name: str) -> None:
        s = self.stats[name]
        s.failures += 1
        s.consecutive_failures += 1
        s.last_failure_at = monotonic()
        self._save()

    def _in_cooldown(self, name: str) -> bool:
        s = self.stats[name]
        if s.last_failure_at is None:
            return False
        return (monotonic() - s.last_failure_at) < self.COOLDOWN_S

    def score(self, name: str) -> float:
        """Higher is better. Combines reliability, quality, and cost."""
        v = self.variants[name]
        s = self.stats[name]

        reliability = s.success_rate
        if self._in_cooldown(name):
            reliability *= 0.25  # heavily deprioritize a variant that just failed

        # Quality helps, cost hurts. Both are user-supplied relative weights.
        value = (reliability * v.quality) / max(v.relative_cost, 0.01)
        return value

    def ranked(self) -> List[str]:
        """Variant names ordered best-first for the next attempt."""
        return sorted(self.variants.keys(), key=self.score, reverse=True)

    def summary(self) -> Dict[str, dict]:
        """A plain-dict snapshot, handy for logging or a dashboard."""
        out = {}
        for name, v in self.variants.items():
            s = self.stats[name]
            out[name] = {
                "attempts": s.attempts,
                "success_rate": round(s.success_rate, 3),
                "avg_latency_s": round(s.avg_latency_s, 3),
                "consecutive_failures": s.consecutive_failures,
                "relative_cost": v.relative_cost,
                "quality": v.quality,
                "score": round(self.score(name), 4),
            }
        return out
