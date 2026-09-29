"""Choosing which brain answers, in one place.

There are three, and the difference between them is only where the judgement
comes from -- the prompt, the schema, the guard, the scoring and the cache are
shared by all three, so switching is a fair comparison rather than a change of
system.

| name           | judgement            | costs        | needs                     |
|----------------|----------------------|--------------|---------------------------|
| `fake`         | arithmetic, no model | nothing      | nothing                   |
| `subscription` | Claude via the CLI   | subscription | a signed-in Claude account|
| `api`          | Claude via the API   | per token    | `ANTHROPIC_API_KEY`       |

`fake` is not a placeholder for the other two. It is the yardstick: identical
inputs and identical risk management with the judgement replaced by arithmetic,
so the gap between it and a real model is the value of the judgement alone.
"""

from __future__ import annotations

from typing import Any

from traidingbrain.brain.cache import DecisionCache
from traidingbrain.brain.client import AnthropicBrain
from traidingbrain.brain.fake import FakeBrain
from traidingbrain.brain.subscription import SubscriptionBrain
from traidingbrain.config.settings import AppConfig, load_secrets

BRAIN_NAMES = ["fake", "subscription", "api"]


def make_brain(name: str, config: AppConfig, *, cache: DecisionCache | None = None) -> Any:
    """Build a brain by name, failing loudly when its prerequisite is missing.

    A missing API key or an expired login must stop the run here. Falling back to
    `fake` would produce a full set of plausible results attributed to a model that
    was never asked -- the single most misleading outcome available.
    """
    if name == "fake":
        return FakeBrain(config)

    if name == "subscription":
        return SubscriptionBrain(config, cache)

    if name == "api":
        if not load_secrets().anthropic_api_key.get_secret_value():
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. Put it in .env, or use --brain subscription "
                "to ask through a signed-in Claude account instead."
            )
        return AnthropicBrain(config, cache)

    raise ValueError(f"unknown brain {name!r}; expected one of {', '.join(BRAIN_NAMES)}")
