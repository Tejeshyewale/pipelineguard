"""
PipelineGuard
=============

A cost-aware reliability layer for RocketRide pipelines.

PipelineGuard wraps the official `rocketride` Python SDK and adds:
  - Automatic failover when a pipeline run fails or times out
  - Cost/quality-aware selection of the next provider variant to try
  - A lightweight scoring system that learns which variants are
    currently reliable, based on real run outcomes
  - Structured run history you can inspect or export

It does not replace the RocketRide SDK -- it sits directly on top of it,
using only the public client API (`use`, `send`, `get_task_status`,
`terminate`, `on_event`, and the documented exception hierarchy).
"""

from .guard import PipelineGuard
from .variants import Variant, VariantScoreboard
from .exceptions import PipelineGuardError, AllVariantsFailedError

__all__ = [
    "PipelineGuard",
    "Variant",
    "VariantScoreboard",
    "PipelineGuardError",
    "AllVariantsFailedError",
]

__version__ = "0.1.0"
