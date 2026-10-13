# Archived Core Refactor

`backend/core/` contains an unfinished backend rewrite that introduced an event bus,
provider router, and agent abstractions.

It is not the supported desktop runtime.

The canonical runtime for this repository is:

- `electron/main.js`
- `backend/server.py`

Why this folder still exists:

- reference for future architectural work
- source material if the refactor is resumed later
- not part of the supported `npm run dev` path

If you intentionally want to experiment with the archived refactor, set:

```powershell
$env:INARA_ALLOW_EXPERIMENTAL_CORE_SERVER="1"
python backend/core/server.py
```

Do not treat the `backend/core/` socket contract as the active source of truth for the app.
