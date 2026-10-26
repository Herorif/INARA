# backend/core

Shared primitives used by the supported desktop runtime (`backend/server.py` ->
`backend/application.py`):

- `event_bus.py` — the in-process `EventBus` and `Events` names bridged to owner-scoped
  socket delivery (`transport/delivery.py`).
- `reminder_store.py` / `durable_reminders.py` — reminder persistence.

The archived experimental rewrite that used to live here (`core/server.py`,
`core/tool_registry.py`, `core/config.py`) was removed; it was never reachable from the
supported runtime. See `docs/RETIRED_PATHS.md`; its history is in git.
