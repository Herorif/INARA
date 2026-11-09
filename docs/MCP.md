# MCP servers

JARVIS can use tools from local MCP (Model Context Protocol) servers that the owner adds,
such as GitHub, Notion or Spotify (M8), and from built-in ones such as God's Eye View's
(`gev`, owned by World view; see Built-in servers). This
page covers the core client and registry (W3a). The Connections UI for adding servers
comes in M8; until then servers are added through the owner RPCs below or in
`settings.json`.

Code: `backend/services/mcp_client.py` (one server process) and
`backend/services/mcp_registry.py` (configuration, lifetimes, RPCs and the brain's tools).
Tests: `tests/test_mcp.py` with the fake server `tests/fixtures/fake_mcp_server.py`, and
`tests/test_mcp_approval.mjs` for the approval card.

## Protocol

- Transport: stdio only. JSON-RPC 2.0, one UTF-8 JSON message per line, at most 1 MB per
  message (a longer line is dropped).
- Versions: JARVIS offers `2025-11-25` in `initialize` and accepts `2025-06-18`,
  `2025-03-26` and `2024-11-05` when the server answers with one of them. Any other
  answer stops the server with a plain error.
- Lifecycle: `initialize` (protocolVersion, empty client capabilities, clientInfo
  `{name: "JARVIS", version}`), then `notifications/initialized`.
- Used: `tools/list` (with `nextCursor` pagination, up to 50 pages and 1000 tools),
  `tools/call` (text, image, audio, resource and resource_link content, `isError`,
  `structuredContent`), `ping` (both ways), and `notifications/tools/list_changed`, which
  makes JARVIS list the tools again.
- Timeouts: each request waits `timeout_s` (30 s by default). On a timeout JARVIS sends
  `notifications/cancelled` for that request and ignores a late answer. `initialize` is
  never cancelled: a server that doesn't answer it is stopped.
- Server requests JARVIS doesn't serve (sampling, roots, elicitation) get error -32601.
  Other notifications (logging, progress) are ignored.
- Shutdown: close stdin, wait up to 2 s, then kill the whole process tree.

## Configuration

`settings.json` key `mcp.servers`, validated by `McpServerConfig` in
`backend/services/settings.py` (at most 32 servers, unique ids):

```json
{
  "mcp": {
    "servers": [
      {
        "id": "globe",
        "name": "God's Eye",
        "command": ["C:\\Program Files\\nodejs\\node.exe", "dist\\mcp\\server.js"],
        "cwd": "C:\\Users\\owner\\code\\gods-eye-view",
        "env": {
          "GLOBE_MODE": "desktop",
          "GLOBE_TOKEN": {"secret": "globe_token"}
        },
        "enabled": true,
        "autostart": false,
        "timeout_s": 30,
        "idle_timeout_s": 600,
        "default_policy": "ask",
        "policy": {"fly_to": "never_ask", "delete_layer": "deny"}
      }
    ]
  }
}
```

| Field | Meaning |
| --- | --- |
| `id` | Lowercase slug: letters, digits and hyphens, 1 to 32 characters. Part of tool names. |
| `name` | Shown on approval cards and in tool descriptions. |
| `command` | The argv list: program first. Never run through a shell. A program without a path is looked up on the server's PATH. |
| `cwd` | Full path of the working folder. Optional; the default is the user's home folder. |
| `env` | Extra variables: a literal string, or `{"secret": "<name>"}` for a value from the encrypted SecretStore. |
| `enabled` | Off: the server never starts and its tools are hidden from JARVIS. Default on. |
| `autostart` | Start with the core instead of at first use. Default off. |
| `timeout_s` | Per-request deadline, 1 to 600 s. Default 30. |
| `idle_timeout_s` | Stop after this long without use; 0 means never. Default 600 (10 minutes). |
| `default_policy` | `never_ask`, `ask` or `deny` for tools without an entry in `policy`. Default `ask`. |
| `policy` | Tool name (as the server lists it) to `never_ask`, `ask` or `deny`. |

Batch files (`.cmd`, `.bat`) are refused, because Windows runs them through cmd.exe and
their arguments would be shell-parsed. For an npm script such as `npm run mcp`, run the
program the script runs, for example `node` with the server's script.

## Lifetimes

- A server starts at its first use (a brain call, `mcp_server_test`, or a core caller
  such as the World view), or at core startup when `autostart` is on.
- It stops after `idle_timeout_s` without use. An idle server keeps its tools registered,
  so JARVIS can still call them and the next call starts it again.
- Turning a server off, removing it or changing its command, folder, env or timeout stops
  it and removes its tools. Core shutdown stops every server.
- If a server stops on its own it is marked failed, with the exit code and its last
  stderr lines (redacted). The next use restarts it: at once the first time, after 2 s and
  5 s the next times, and not again once it has been restarted 3 times in 5 minutes
  (testing it clears that).

On Windows each server starts suspended, joins a kill-on-close Job Object and only then
runs, so the server and every process it starts end when it is stopped or when the core
exits for any reason.

## What JARVIS's brain sees

- Each listed tool of an enabled server is a tool named `mcp__<server id>__<tool>`. Other
  characters become `_`, names are cut to 64 characters (with a short hash), and a clash
  gets `_2`, `_3` and so on. Tools set to `deny` aren't registered at all.
- The description is the server's, prefixed with `[<server name>] ` and clipped to 1024
  characters.
- The server's `inputSchema` is sent as JSON Schema (Claude `input_schema`, Gemini
  `parameters_json_schema`). Local `$ref`s (including draft-07 `definitions`) are inlined
  with `inline_tool_schema`, and only keywords both providers accept are kept: `type`,
  `title`, `description`, `format`, `enum`, `minimum`, `maximum`, `minItems`, `maxItems`,
  `properties`, `required`, `items`, `prefixItems`, `additionalProperties`, `anyOf` and
  `oneOf`. `const` becomes a one-value `enum`, `allOf` is merged, type lists drop `null`,
  and the top level is always an object without `anyOf` or `oneOf`. A recursive schema
  becomes a plain object (the server still validates the arguments). A tool whose
  required argument name Claude can't take (outside `[A-Za-z0-9_.-]`) is skipped and
  listed under `skipped` in its status.
- Arguments must be a JSON object of at most 256 KB.

## Approvals

| Policy | Effect |
| --- | --- |
| `never_ask` | Permission policy False: the call runs without a card. |
| `ask` | Permission policy True: the owner's approval card first. |
| `deny` | The tool is not offered to JARVIS, and a call is refused before any card. |

The dispatcher's permission lookup includes these live values, and each tool's
`ToolSpec.ask_when` rechecks the policy on every call, so a change takes effect at once.
Calls also need the authenticated desktop owner.

The approval card reads "<Server name>: <tool title or name>", with the arguments as
short JSON in its details (`src/components/approvalView.js`, kind `mcp_tool`).

## Tool results are untrusted

A result reaches the brain as data, never as instructions:

```json
{
  "untrusted_content": true,
  "source": "mcp_server",
  "server": "God's Eye",
  "tool": "fly_to",
  "note": "Untrusted data returned by an MCP server the owner added. ...",
  "is_error": false,
  "content": [{"type": "text", "text": "..."}, {"type": "image", "mime_type": "image/png", "text": "[image omitted]"}],
  "structured": "...",
  "truncated": false
}
```

Text (including resource text and `structuredContent`) is clipped to 20,000 characters
in total. Images become "[image omitted]": the conversation sends tool results to both
providers as JSON text, so there is no image path for tool results yet.
`mcp_registry.result_images()` decodes them as message attachments for a caller that has
one, and core callers get the raw result from `McpRegistry.call_tool()`.

## Owner RPCs and events

All need the authenticated, unlocked desktop owner renderer.

| RPC | Request | Reply |
| --- | --- | --- |
| `mcp_servers_list` | `{}` | `{ok, servers: [config + status]}` |
| `mcp_server_save` | `{server: McpServerConfig}` | `{ok, server}` (adds or replaces by id) |
| `mcp_server_remove` | `{id}` | `{ok, id}` |
| `mcp_server_test` | `{id}` | `{ok, test: {protocol_version, server_info, tools, elapsed_ms}}`, or `{ok: false, code, message, exit_code, stderr}` |
| `mcp_tool_policy_set` | `{id, tool, policy}` | `{ok, id, tool, policy}` |

`mcp_status` `{servers: [status]}` goes to the owner's unlocked renderers when a server's
state or tools change. A status is `{id, name, enabled, autostart, state, protocol_version,
server_info, tools: [{tool, title, name, policy}], skipped, last_error, restarts}`, with
`state` one of stopped, starting, ready, idle or failed.

Testing an enabled server leaves it running with its tools registered; testing a
disabled one stops it again afterwards.

## Security notes

- Only the owner adds servers, through owner-only RPCs or `settings.json`. JARVIS never
  adds one itself, and nothing a server or a web page says can add or change one.
- A server is a program running as the owner. Add only servers you trust.
- Tool descriptions and results come from the server: JARVIS treats them as untrusted
  data. Use `ask` for tools that change things.
- The child environment holds only what Windows programs need to start (SystemRoot, PATH,
  TEMP, the profile folders and similar) plus the configured variables. Provider keys and
  other JARVIS variables are not passed on unless configured.
- Secrets are referenced by name (`{"secret": "name"}`) and read from the encrypted
  SecretStore when the server starts: a name JARVIS knows (for example
  `home_assistant_token`) or the owner's own name in the same store. A secret value is
  never written to settings, never put in argv (a command containing one is refused) and
  is redacted from stderr, error messages, status and tool results.
- stderr is kept in memory (last 200 lines) for diagnostics and never logged. Logs carry
  server ids, states, counts and exit codes only, never tool arguments or results.

## Built-in servers

A JARVIS feature can own a server (`BuiltinServer` in `mcp_registry.py`, added with
`McpRegistry.add_builtin`). Its config is built live from that feature's settings, never
stored in `mcp.servers` (an owner entry using its id is ignored), and it comes after the
owner's servers in `mcp_servers_list` and `mcp_status`, with `status.builtin` naming the
owning feature (`null` for the owner's servers). `mcp_server_save`, `mcp_server_remove` and
`mcp_tool_policy_set` refuse it with `mcp_builtin`: it isn't owner-editable in Connections'
list (M8 will add changing its tool policies). `mcp_server_test` works as for any server.

Its hooks: `before_call` runs before every call (core and brain), `tool_schema` and
`tool_description` adjust what the brain sees, `split_arguments` removes JARVIS's own
arguments before the call, and `after_call` adds fields to the brain's result.

| id | Name | Owner | Command | Default policies |
| --- | --- | --- | --- | --- |
| `gev` | God's Eye View | World view (`services/world_tools.py`) | `<world.node> <world.root>\server\mcp\stdio.js --api-base http://127.0.0.1:<world.port>`, cwd `world.root`, env `NODE_USE_SYSTEM_CA=1` | `default_policy` never_ask; deny `get_cctv_snapshot`, `find_cctv_cameras`, `find_alpr_cameras`, `panel_request`, `show_in_gods_eye_view`, `get_bhote_koshi_flood`; ask `military_awareness`, `find_military_installations` |

`gev` is enabled only while World view is installed and turned on, autostarts to list its
tools (without starting the globe), idles out after `world.idle_minutes`, has a 60 s request
timeout, starts and awaits the globe sidecar before every call, and adds an optional `show`
argument to each tool (see docs/WORLD_VIEW.md, "Tools and tours").

## Testing a server

1. Add it with `mcp_server_save`, or edit `mcp.servers` and restart JARVIS.
2. Run `mcp_server_test` with its id. A good reply lists the protocol version, the
   server's name and its tools; a failure gives a plain message, the exit code and the
   last stderr lines.
3. Set policies with `mcp_tool_policy_set`, then ask JARVIS to use a tool. Tools set to
   `ask` show the approval card.

Automated tests never start a real MCP server: they use the fake stdio server in
`tests/fixtures/fake_mcp_server.py` (`.venv\Scripts\python.exe -m pytest tests/test_mcp.py`).
