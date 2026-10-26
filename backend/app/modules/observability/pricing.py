"""Static, dated OpenAI price table for estimated cost (PRD 0007 D4).

Prices are USD per 1M tokens, standard tier, checked on each model's page under
https://developers.openai.com/api/docs/models/ as of ``PRICES_AS_OF``. Cached-input
discounts and the Batch API are ignored, so the estimate is an upper bound for repeated
prompts. Refreshing the table is a manual code change.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.core.llm import TokenUsage

PRICES_AS_OF = date(2026, 10, 27)

_PER_TOKENS = Decimal(1_000_000)
_PLACES = Decimal("0.000001")


@dataclass(frozen=True)
class ModelPrice:
    input_per_million: Decimal
    output_per_million: Decimal


PRICES: dict[str, ModelPrice] = {
    "gpt-4.1": ModelPrice(Decimal("2.00"), Decimal("8.00")),
    "gpt-4.1-mini": ModelPrice(Decimal("0.40"), Decimal("1.60")),
    "gpt-4.1-nano": ModelPrice(Decimal("0.10"), Decimal("0.40")),
    "gpt-4o": ModelPrice(Decimal("2.50"), Decimal("10.00")),
    "gpt-4o-mini": ModelPrice(Decimal("0.15"), Decimal("0.60")),
    "text-embedding-3-small": ModelPrice(Decimal("0.02"), Decimal("0")),
    "text-embedding-3-large": ModelPrice(Decimal("0.13"), Decimal("0")),
}


def price_for(model: str) -> ModelPrice | None:
    """Exact name first, then the longest known prefix (the API reports dated names such
    as ``gpt-4.1-mini-2025-04-14``)."""
    if model in PRICES:
        return PRICES[model]
    matches = [name for name in PRICES if model.startswith(f"{name}-")]
    return PRICES[max(matches, key=len)] if matches else None


def estimate_cost(model: str, usage: TokenUsage) -> Decimal | None:
    """Estimated USD for one call, rounded to 6 places; ``None`` for an unknown model."""
    price = price_for(model)
    if price is None:
        return None
    cost = (
        Decimal(usage.prompt_tokens) * price.input_per_million
        + Decimal(usage.completion_tokens) * price.output_per_million
    ) / _PER_TOKENS
    return cost.quantize(_PLACES, rounding=ROUND_HALF_UP)
