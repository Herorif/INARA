"""Claude and Gemini Live list prices, for usage receipts.

Estimates only: they never replace the provider invoice and the usage center keeps
``invoice_cost_known`` false. Update the tables when a provider changes its prices.
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

# Gemini Live, paid Standard tier, per modality. Source: https://ai.google.dev/gemini-api/docs/pricing
# section "Gemini 3.8 Live, Gemini 3.8 Live Extended Thinking, and Gemini 3.1 Flash Live
# Preview" (page last updated 2026-10-22 UTC; checked 26 Oct 2026). Output text includes
# thinking tokens. The free tier is free of charge; receipts show the paid list price.
LIVE_RATES = {
    "input_text": 0.75,
    "input_audio": 3.00,
    "input_image": 1.00,  # image and video
    "output_text": 4.50,
    "output_audio": 12.00,
}
GEMINI_LIVE_PRICES = {
    "gemini-3.8-live": LIVE_RATES,
    "gemini-3.8-live-extended-thinking": LIVE_RATES,
    "gemini-3.1-flash-live-preview": LIVE_RATES,
}

COUNTERS = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_write": "cache_creation_input_tokens",
    "cache_read": "cache_read_input_tokens",
}


def estimate_microusd(model, counts):
    """Integer micro-USD estimate for one request, or None for an unpriced model."""
    live = GEMINI_LIVE_PRICES.get(str(model).removeprefix("models/"))
    if live is not None:
        return _live_estimate(live, counts) if counts else None
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


def _live_estimate(rates, counts):
    """One Live turn from modality counters. Tokens the provider did not label by modality
    are priced at the audio rate (the higher one), so an estimate never undercounts them."""
    total = 0.0
    for side in ("input", "output"):
        labelled = 0
        for kind in ("text", "audio", "image"):
            count = counts.get(f"{side}_{kind}_tokens", 0)
            labelled += count
            rate = rates.get(f"{side}_{kind}", rates[f"{side}_audio"])
            total += rate * count
        total += rates[f"{side}_audio"] * max(0, counts.get(f"{side}_tokens", 0) - labelled)
    total += rates["output_text"] * counts.get("thinking_tokens", 0)
    total += rates["input_text"] * counts.get("tool_prompt_tokens", 0)
    return int(math.ceil(round(total, 6)))
