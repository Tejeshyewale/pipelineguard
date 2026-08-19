# PipelineGuard

**A cost-aware, self-healing reliability layer for [RocketRide](https://github.com/rocketride-org/rocketride-server) pipelines.**

[![Tests](https://github.com/Tejeshyewale/pipelineguard/actions/workflows/tests.yml/badge.svg)](https://github.com/Tejeshyewale/pipelineguard/actions)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](#requirements)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

## The problem

If you run RocketRide pipelines in production, you're depending on external LLM providers. Providers rate-limit you, time out, or go down. When that happens, a naive integration just crashes the whole pipeline run — even though RocketRide supports 13+ providers that could have handled the same request.

## What PipelineGuard does

PipelineGuard sits directly on top of the official `rocketride` Python SDK (`RocketRideClient.use/send/get_task_status/terminate`) and adds one thing: **automatic, cost-aware failover between pipeline variants.**

You give it a small list of `.pipe` files that all solve the same task (e.g. one wired to OpenAI, one to Anthropic, one to a cheap local model). PipelineGuard:

1. Picks the best-ranked variant based on a running reliability score (not just "try them in order")
2. Runs it through the real SDK
3. If it fails (any `rocketride` exception, a bad task status, or a timeout), records the failure, **deprioritizes that variant for a cooldown window**, and immediately tries the next-best one
4. Fires an `on_failover` hook so you can alert on it (Discord, Slack, whatever you want — PipelineGuard doesn't assume)
5. Returns a full `RunReport` so you know exactly what happened and what it cost you in retries

It is a thin, honest wrapper — not a rewrite of RocketRide's runtime. Every pipeline execution still goes through the real C++ engine; this just decides *which* `.pipe` to point the SDK at, and *when to switch*.

### Failover & Execution Flow

```mermaid
flowchart TD
    A[Request Received] --> B[PipelineGuard Ranks Variants]
    B --> C[Select Best-Ranked Variant]
    C --> D[Execute Task via RocketRide SDK]
    D --> E{Execution Success?}
    E -- Yes --> F[Record Success & Return RunReport]
    E -- No --> G[Record Failure & Apply Cooldown]
    G --> H[Trigger Failover Hooks]
    H --> I{More Variants Left?}
    I -- Yes --> C
    I -- No --> J[Raise AllVariantsFailedError]
```

## Configuration

### Loading Variants from config.yaml

```yaml
variants:
  - name: openai-gpt
    filepath: pipelines/summarize_openai.pipe
    relative_cost: 1.0
    quality: 1.0
  - name: anthropic-claude
    filepath: pipelines/summarize_anthropic.pipe
    relative_cost: 1.2
    quality: 1.1
```

```python
from pipelineguard.variants import load_variants_from_yaml

variants = load_variants_from_yaml('config.yaml')
```

### Structured Logging

PipelineGuard includes built-in structured JSON logging for all major lifecycle events (variant selection, success, failure, failover, and cooldowns). By default, it logs at the `INFO` level.

```bash
export LOG_LEVEL=DEBUG
```

Sample log entry:
```json
{"timestamp": "2026-08-19T04:28:34.000Z", "level": "WARNING", "message": "pipelineguard: 'openai-gpt' failed after 1.20s -- failing over", "name": "pipelineguard", "variant": "openai-gpt", "event_type": "run_failure", "latency_ms": 1200, "outcome": "failure", "error": "Connection timeout"}
```

### Persistence

By default, `VariantScoreboard` keeps its state in-memory. To persist reliability scores across restarts, pass a `persistence_file`:

```python
guard = PipelineGuard(
    client_factory=my_factory,
    variants=variants,
    persistence_file="scoreboard.json"
)
```

### Hooks

- `on_success(variant_name, result)` — fired when a variant succeeds
- `on_failover(variant_name, error)` — fired when a variant fails and PipelineGuard fails over
- `on_cooldown_start(variant_name)` — fired when a variant enters cooldown
- `on_cooldown_end(variant_name)` — fired when a variant exits cooldown

```python
@guard.on_failover
def alert_slack(name, error):
    requests.post(SLACK_URL, json={"text": f"Variant {name} failed: {error}"})

@guard.on_cooldown_start
def log_cooldown(name):
    print(f"Variant {name} has entered cooldown!")
```

## Architecture

```
pipelineguard/
├── pipelineguard/
│   ├── guard.py       # PipelineGuard: runs variants, drives failover
│   ├── variants.py    # Variant + VariantScoreboard: cost/quality-aware scoring
│   └── exceptions.py  # PipelineGuardError, AllVariantsFailedError
├── pipelines/          # Example .pipe files (openai / anthropic / local)
├── examples/
│   ├── run_demo.py         # Real end-to-end usage against a live RocketRide server
│   └── demo_failover.py    # Self-contained terminal demo (no live server needed)
└── tests/
    ├── fakes.py        # FakeClient — mirrors RocketRideClient's shape for tests
    └── test_guard.py   # 7 unit tests, no live server required
```

### How variant selection works

```
score = (success_rate * quality) / relative_cost
```

- `success_rate` starts at an optimistic 1.0 for untested variants, then reflects real outcomes.
- A variant that just failed goes into a 30-second cooldown where its score is cut to 25%.
- Cheaper variants are favored at equal reliability; higher-quality variants at equal cost.

This is a deliberately simple, readable heuristic — not a black box. `guard.health()` returns the full scoreboard as a plain dict at any time.

## Installation

```bash
git clone <this-repo>
cd pipelineguard
pip install -r requirements.txt
```

## Running the example (requires a live RocketRide server)

```bash
export ROCKETRIDE_URI="ws://localhost:5565"
export ROCKETRIDE_APIKEY="your-key"
python examples/run_demo.py
```

## Try it instantly (no server, no API keys)

```bash
pip install colorama
python examples/demo_failover.py
```

This runs a self-contained simulation showing variant selection, a deliberate failure, cooldown, and failover to a backup — all in your terminal.

## Run with Docker

```bash
docker-compose up --build
```

Spins up the app alongside a lightweight mock RocketRide server so you can see the full failover flow with zero setup.

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```

```
tests/test_guard.py::test_first_variant_succeeds_no_failover PASSED
tests/test_guard.py::test_first_variant_fails_second_succeeds PASSED
tests/test_guard.py::test_all_variants_fail_raises PASSED
tests/test_guard.py::test_failover_hook_is_called_on_each_failure PASSED
tests/test_guard.py::test_repeated_failures_deprioritize_a_variant PASSED
tests/test_guard.py::test_scoreboard_rejects_empty_variant_list PASSED
tests/test_guard.py::test_score_prefers_cheaper_variant_at_equal_reliability PASSED

7 passed
```

## Why this fits RocketRide specifically

- Uses the documented `.pipe` format and the real `RocketRideClient` methods (`use`, `send`, `get_task_status`, `terminate`) exactly as specified in the SDK docs — no invented API surface.
- Leans on RocketRide's own multi-provider design (13+ LLM providers) as the raw material for failover.
- The cost/quality scoring reflects RocketRide's own stated goal of reducing provider/GPU cost.

## Roadmap

- Predictive early-warning (flagging a provider as risky before it fails) — needs real historical trace data at volume, out of scope for now.
- A small web dashboard over `guard.health()` for live visibility.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
