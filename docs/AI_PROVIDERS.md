# AI provider keys

INARA uses two providers:

| Key | Used for | Where to get it | Name in INARA |
| --- | --- | --- | --- |
| Anthropic API key (starts with `sk-ant-`) | Claude, the assistant | [Anthropic Console](https://console.anthropic.com/) | `anthropic_api_key` |
| Gemini API key (starts with `AIza`, about 39 characters) | Voice and transcription | [Google AI Studio](https://aistudio.google.com/app/apikey) | `gemini_api_key` |

Both are optional: INARA starts without them, and AI features report that a key is missing.

## Where keys are stored

Keys are stored in the profile database (`assistant.sqlite3` in the data directory), one `secrets` document per key, encrypted with Windows DPAPI for your Windows account like the rest of INARA's private data. They are not written to `.env`, settings files or logs.

- Installed versions: `<installation>/data/<version>/database`, the directory the launcher passes as `INARA_DATA_DIR`. Each installed version has its own profile, so keys saved for one version are not visible to another. Encrypted backups and recovery copies carry the stored keys with the rest of the profile.
- Development: `INARA_DATA_DIR` if set, otherwise `%LOCALAPPDATA%\INARA\data-v1`.

Key values never leave the backend. The UI and the command line only see a status: whether a key is configured, its source (`env` or `store`), its last four characters, and the result of the last check.

## Adding keys

**Setup.** After installing and selecting a version, open **04 AI providers** in INARA Setup. Enter either key, use **Test** to check it with the provider, then **Save**. Save checks each key first; a key the provider rejects is not saved. If the provider cannot be reached, the key is saved and marked as not yet verified. **Skip for now** leaves keys unset. Setup runs the selected version's own Python with `scripts/inara-secrets.py` and passes each key on standard input only.

**Preferences.** Keys can also be managed from Preferences inside INARA (owner-only `secrets_status`, `secrets_set`, `secrets_test` and `secrets_clear` routes; the Preferences screen is a later task).

**Command line.** `scripts/inara-secrets.py` reads keys from standard input only and refuses keys on the command line:

```powershell
# Development profile (INARA_DATA_DIR or %LOCALAPPDATA%\INARA\data-v1)
.venv\Scripts\python.exe scripts\inara-secrets.py set anthropic_api_key --verify   # prompts without echo
.venv\Scripts\python.exe scripts\inara-secrets.py status
.venv\Scripts\python.exe scripts\inara-secrets.py test gemini_api_key
.venv\Scripts\python.exe scripts\inara-secrets.py clear gemini_api_key

# An installed version (selected version by default, or --slot <id>)
<installation>\versions\<id>\runtime\python\python.exe -I -B <installation>\versions\<id>\scripts\inara-secrets.py --installation-root <installation> status

# Any explicit profile database directory
... inara-secrets.py --data-dir C:\path\to\database status
```

Exit codes: `0` ok, `2` invalid input, `3` the provider check failed, `4` storage error (including "installation is busy" while INARA from that installation is running; quit it first or use Preferences).

`scripts/bootstrap.ps1 -ConfigureKeys` prompts for both keys with hidden input and stores them in the development profile through the same tool.

## Checks

A check makes one cheap authenticated request with a 10 second timeout: Anthropic `GET /v1/models`, Gemini list models. Results are `ok`, `invalid_key` (401/403, or Google's invalid-key 400), `rate_limited` (429), `network_error`, `tls_error` or `unexpected`.

Provider requests verify HTTPS against the Windows certificate store (the `truststore` package), so antivirus HTTPS scanning and corporate proxies whose root is trusted by Windows work. This applies only to provider calls (`services.tls.provider_ssl_context()`); INARA's own pinned connections, such as the mobile companion, keep their own certificate checks.

## Developer override

A real value in the `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` environment variable (or a local `.env`) takes precedence over the store. Placeholder values such as `your_api_key_here` or `changeme` are ignored, so the stored key is used. Bootstrap no longer creates `.env`; copy `.env.example` yourself if you want other overrides.
