# Legacy Runtime Manual Smoke Checklist

Use this after `npm run dev` changes that touch the Electron + `backend/server.py` path.

Automated smoke command:

- `python -m unittest tests.test_legacy_runtime_smoke -v`

## Startup

1. Run `npm run dev`.
2. Confirm Electron logs the canonical backend runtime:
   - `legacy-desktop-backend`
   - `backend/server.py`
3. Confirm the backend startup banner prints:
   - Gemini API status
   - Face auth status
   - Slicer status
   - Saved printer count
4. Confirm the app opens idle without auto-starting AI.

## Invalid Gemini Key Path

1. Set `GEMINI_API_KEY` to a placeholder or invalid value.
2. Launch the app.
3. Confirm the top bar shows:
   - `BACKEND CONNECTED`
   - `AI UNAVAILABLE` or `AI IDLE`
   - `LOCAL DEVICES READY`
4. Press the power button once.
5. Confirm AI fails once with a clear unavailable state instead of reconnect spam.

## Local Device Paths Without AI

1. Open the printer window.
2. Confirm saved printers appear even if AI is unavailable.
3. If printers are offline, confirm they show offline status without rapid error spam.
4. If no slicer is installed, confirm the UI shows printing unavailable instead of failing silently.
5. Open the smart-home window and trigger discovery.
6. Confirm discovery does not throw handler arity errors.

## Legacy Feature Regression Checks

1. Trigger `Save Memory` and confirm a file is written under `long_term_memory/`.
2. Trigger a web-agent prompt with a valid Gemini key and confirm it starts and finishes without `'WebAgent' object has no attribute 'run'`.
3. Use the CAD window print action and confirm it opens the printer UI directly.

## Shutdown

1. Close the app window.
2. Confirm the backend receives the shutdown signal and Electron exits cleanly.
