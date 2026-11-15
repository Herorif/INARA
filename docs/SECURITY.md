# JARVIS security notes

## Child processes

Every program JARVIS starts (sidecars, isolated workers, MCP servers, the Electron windows,
the Cloudflare tunnel) follows three rules: a minimal environment, a kill-on-close Job
Object and, for anything that listens, loopback only.

### Minimal environment (`backend/services/child_env.py`)

`minimal_env(extra=None, *, keep=(), python=False)` builds a child's environment from
scratch. It never copies the core's environment wholesale.

1. **Allow-list.** From the parent it copies only what Windows programs need to start:
   `SystemRoot`, `SystemDrive`, `WINDIR`, `COMSPEC`, `PATHEXT`, `PATH`, `TEMP`, `TMP`,
   `USERPROFILE`, `USERNAME`, `HOMEDRIVE`, `HOMEPATH`, `APPDATA`, `LOCALAPPDATA`,
   `PROGRAMDATA`, `ALLUSERSPROFILE`, `PUBLIC`, `ProgramFiles`, `ProgramFiles(x86)`,
   `ProgramW6432`, `CommonProgramFiles`, `CommonProgramFiles(x86)`, `CommonProgramW6432`,
   `NUMBER_OF_PROCESSORS`, `PROCESSOR_ARCHITECTURE`, `OS`, `PYTHONDONTWRITEBYTECODE`, and
   the locale (`LANG`, `LANGUAGE`, `LC_*`). `python=True` adds `PYTHONIOENCODING=utf-8`.
2. **`keep`.** Further parent variable names a child needs, named at its spawn site.
3. **Never inherited.** A name containing `KEY`, `TOKEN`, `SECRET`, `PASSWORD` or `AUTH`,
   or starting `ANTHROPIC_`, `GEMINI_`, `GOOGLE_`, `TWILIO_` or `JARVIS_`, is never copied
   from the parent, even when it is in `keep`. This covers the session token the resident
   host puts in its own environment and every provider key with an environment override.
4. **`extra`.** Values set as given, last (an `extra` name replaces any spelling of the
   same name). This is the only way a secret reaches a child: resolved from the encrypted
   store at the spawn site, passed in the environment (never on the command line), and
   never logged.

| Child | Spawned by | Environment |
| --- | --- | --- |
| Isolated Python workers (browser, quality, face, printing, image, CAD, legacy CAD, call bridge) | `resident.win32.WorkspaceProcess` | minimal, `python=True`; the job request goes over the stdin pipe |
| Blender (from the CAD worker) | the CAD worker, inside its job | inherits the worker's minimal environment |
| Workspace and overlay windows (Electron) | `WorkspaceProcess` from `resident/host.py` | minimal; the bootstrap token goes over the stdin pipe only |
| cloudflared | `WorkspaceProcess` from `telephony/tunnel.py` | minimal + `TUNNEL_TOKEN` (extra) |
| MCP servers (owner-added and the built-in God's Eye View server) | `services/mcp_client.py` | minimal + exactly the server's configured `env` (secrets by name from the store) |
| CAD kernel (`.venv-cad`, `-I`) | `services/cad_kernel.py` | minimal, `python=True`; no keys at all |
| World view globe (Node 24, vite preview) | `services/world_view.py` | minimal + `PATH` (Node's folder and System32), `OPENAI_API_KEY`/`GEMINI_API_KEY` set empty, `GEV_ALLOWED_HOSTS`, `GEV_EMBED_FRAME_ANCESTORS`, `NO_COLOR`, `NODE_USE_SYSTEM_CA=1`; a GEV provider key would go through `extra` |

### Kill-on-close Job Object (`backend/services/job_object.py`)

Each child and everything it starts sit in a Job Object with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`: when the core exits, crashes or closes the job, the
whole tree dies.

- `WorkspaceProcess` creates the job with `job_object.create_job()` and names it in
  CreateProcessW's attribute list, so the child is born inside it. If that fails, nothing
  starts (legacy CAD runs generated code and depends on the job).
- `job_object.spawn()` (MCP servers, the CAD kernel, the globe) starts the child
  suspended through asyncio, assigns it with `contain()` and only then resumes it, so no
  grandchild can start outside the job. If the job can't be made or joined, `contain()`
  logs one warning per kind of child and lets it run without a job: the owner's `close()`
  still stops it. A child that can't be resumed is killed.

### Loopback only

A sidecar that listens binds `127.0.0.1` and nothing else:

- World view: `vite preview --host 127.0.0.1 --port <world.port> --strictPort`, and
  `GEV_ALLOWED_HOSTS=127.0.0.1,localhost`. The God's Eye View MCP server reaches it at
  `--api-base http://127.0.0.1:<port>`. Tests: `tests/test_child_env.py`.
- MCP servers and the CAD kernel speak over stdio and listen on nothing.
- The core itself binds `127.0.0.1:8000`. LAN endpoints are off by default (S15).

### Adding a sidecar

1. Start it from an explicit argv list, never a shell or a `.cmd`/`.bat`.
2. Build its environment with `minimal_env(extra, keep=..., python=...)`: name each extra
   variable it needs at the spawn site; pass a secret only through `extra`, resolved from
   `services.secrets`, never in argv.
3. Start it in a job: `WorkspaceProcess` for a worker fed over stdin, or
   `job_object.spawn(argv, cwd=..., env=..., label="...", stdin=..., stdout=..., stderr=...)`
   for an asyncio child. Keep the returned job and `close()` it when the sidecar stops.
4. If it listens, bind `127.0.0.1` (a fixed port with a strict-port flag) and add a test
   assertion for the host argument.
5. Add a spawn-site test to `tests/test_child_env.py`: the environment the fake spawner
   gets has no parent secret and has what the child needs.
