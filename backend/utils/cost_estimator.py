"""Estimate LLM call cost by model and token counts."""
from __future__ import annotations

# USD per 1M tokens {input, output}
_PRICE_TABLE: dict[str, dict[str, float]] = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    "claude-sonnet-4-6":         {"input": 3.0,  "output": 15.0},
    "claude-opus-4-8":           {"input": 15.0, "output": 75.0},
    # Bailian / DashScope approximations
    "qwen-max":                  {"input": 2.4,  "output": 9.6},
    "qwen-plus":                 {"input": 0.8,  "output": 3.2},
    "qwen-turbo":                {"input": 0.3,  "output": 0.6},
}
_DEFAULT_PRICE = {"input": 3.0, "output": 15.0}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Return estimated USD cost for a single LLM call."""
    # strip version suffixes like -20251001 when looking up
    p = _PRICE_TABLE.get(model) or _PRICE_TABLE.get(model.rsplit("-", 1)[0]) or _DEFAULT_PRICE
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000
