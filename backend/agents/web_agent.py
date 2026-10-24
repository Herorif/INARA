"""Retired compatibility import. Use services.browser for explicit read-only inspection."""


class WebAgent:
    def __init__(self, *args, **kwargs):
        raise RuntimeError("Autonomous browser control is retired. Use the Web inspector.")
