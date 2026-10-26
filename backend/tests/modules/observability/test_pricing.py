from decimal import Decimal

import pytest

from app.core.llm import TokenUsage
from app.modules.observability import pricing


def test_known_model_cost_uses_input_and_output_prices() -> None:
    # gpt-4.1-mini: 0.40 / 1.60 USD per 1M tokens
    cost = pricing.estimate_cost(
        "gpt-4.1-mini", TokenUsage(prompt_tokens=1_000, completion_tokens=500)
    )
    assert cost == Decimal("0.001200")


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("gpt-4.1-mini-2025-04-14", "gpt-4.1-mini"),  # dated name -> longest prefix
        ("gpt-4.1-2025-04-14", "gpt-4.1"),
        ("gpt-4o-mini", "gpt-4o-mini"),
    ],
)
def test_dated_model_names_resolve_to_the_longest_known_prefix(model: str, expected: str) -> None:
    assert pricing.price_for(model) == pricing.PRICES[expected]


@pytest.mark.parametrize("model", ["fake-model", "gpt-4.1mini", "o3"])
def test_unknown_models_have_no_price(model: str) -> None:
    assert pricing.price_for(model) is None
    assert pricing.estimate_cost(model, TokenUsage(prompt_tokens=10)) is None


def test_cost_is_rounded_to_six_places() -> None:
    cost = pricing.estimate_cost("text-embedding-3-small", TokenUsage(prompt_tokens=7))
    assert cost == Decimal("0.000000")  # 0.00000014 rounds down
    cost = pricing.estimate_cost("gpt-4.1-mini", TokenUsage(prompt_tokens=3, completion_tokens=0))
    assert cost == Decimal("0.000001")  # 0.0000012 rounds to 0.000001
