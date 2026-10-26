"""Claude list prices, in one table, for usage receipts.

Estimates only: they never replace the provider invoice and the usage center keeps
``invoice_cost_known`` false. Update the table when Anthropic changes its prices.
Prices are US dollars per million tokens.
"""

import math

# model -> (prompt token limit or None, rates for prompts up to the limit, rates above it)
# rates: input, output, cache_write_5m, cache_read
CLAUDE_PRICES = {
    "claude-sonnet-5-5": (
        None,
        {"input": 2.00, "output": 10.00, "cache_write": 2.50, "cache_read": 0.20},
        None,
    ),
    "claude-haiku-5-5": (
        100_000,
        {"input": 0.10, "output": 0.50, "cache_write": 0.125, "cache_read": 0.01},
        {"input": 0.50, "output": 2.50, "cache_write": 0.625, "cache_read": 0.05},
    ),
}

COUNTERS = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_write": "cache_creation_input_tokens",
    "cache_read": "cache_read_input_tokens",
}


def estimate_microusd(model, counts):
    """Integer micro-USD estimate for one request, or None for an unpriced model."""
    entry = CLAUDE_PRICES.get(str(model))
    if entry is None or not counts:
        return None
    limit, base, long_prompt = entry
    prompt = sum(
        counts.get(COUNTERS[name], 0) for name in ("input", "cache_write", "cache_read")
    )
    rates = long_prompt if limit is not None and prompt > limit else base
    # Dollars per million tokens == micro-dollars per token.
    total = sum(rates[name] * counts.get(field, 0) for name, field in COUNTERS.items())
    return int(math.ceil(round(total, 6)))
