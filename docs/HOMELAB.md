# Homelab (S12.3)

JARVIS watches the owner's servers, NAS, containers and UPS through a few **generic
adapters** that together cover almost any system, keeps the latest state in memory, raises
`homelab.alert` signals when something goes wrong, and runs only the actions the owner set
up, each after an approval card. Presets (Proxmox, Portainer, Uptime Kuma, Glances, NUT, …)
and the "Add a system" page are S12.4: a preset is only a saved config for one of these
adapters.

Code: `backend/services/homelab/` (`base.py`, `adapters/`, `process.py`, `registry.py`,
`tools.py`), `backend/transport/homelab.py`. Tests: `tests/test_homelab.py`.

## Configuration: `homelab.hosts`

Settings hold a list of systems, replaced whole on each save (like `mcp.servers`). Each entry
is a `HostConfig`:

| Field | Meaning |
|---|---|
| `id` | `a-z`, `0-9` and `-`, up to 32 characters; unique |
| `name` | What JARVIS calls it ("NAS") |
| `adapter` | `ping`, `tcp`, `http_json`, `prometheus`, `ssh` or `wol` |
| `address` | A bare host name or IP (`ping`, `tcp`, `ssh`, `wol`) or a base URL (`http_json`, `prometheus`). URLs carry no sign-in, query or fragment; `http://` only for an address on the home network |
| `options` | The adapter's own options (below); unknown keys are refused |
| `secret` | `http_json` and `prometheus` only: the **name** of a secret in the encrypted store, never a value |
| `named_actions` | Up to 16 `{name, command}` (ssh) or `{name, request: {method, path, body?}}` (http_json) |
| `interval_s` | 15 to 3600 seconds, default 60 |

Options every adapter takes: `temp_max_c` (30-120, default 80; the high-temperature alert).
Every adapter except `wol` also takes `wake_mac`, `wake_broadcast` (default
`255.255.255.255`, home network only) and `wake_port` (7 or 9) so `homelab_wake` can wake it.

A secret is saved in the same encrypted store as the other JARVIS secrets, under the owner's
own name (as MCP server secrets are). It is read only when a request is made, put only in the
auth header, and never logged, returned or placed in a URL or argv.

## Adapters

### `ping`
`PING.EXE -n 1 -w <timeout_ms> <address>` (`%SystemRoot%\System32\PING.EXE`, else `ping` on
PATH). Up means a reply with a round-trip time (any Windows language); "Destination host
unreachable" counts as down. Options: `timeout_ms` (100-5000, default 1000), `warn_ms`
(latency above it is warn). One `host` entity with `latency_ms`.

```json
{"id": "nas", "name": "NAS", "adapter": "ping", "address": "192.168.1.5",
 "options": {"warn_ms": 50, "wake_mac": "aa:bb:cc:dd:ee:01"}}
```

### `tcp`
Opens and closes one TCP connection per port. Options: `ports` (1-32, distinct), `labels`
(`{"8006": "Proxmox"}`), `timeout_s` (0.2-10, default 2). One `service` entity per port.

```json
{"id": "pve-ports", "name": "Proxmox", "adapter": "tcp", "address": "pve.local",
 "options": {"ports": [22, 8006], "labels": {"8006": "Web UI"}}}
```

### `http_json`
GET `address + path` with `Accept: application/json` and, when `secret` is set,
`<auth_header>: <auth_prefix><secret value>`. Options: `path`, `auth_header` (default
`Authorization`), `auth_prefix` (e.g. `Bearer `, `PVEAPIToken=`), `verify_tls` (default true;
false only for a self-signed box on the home network), `timeout_s` (1-30, default 10),
`fields` (metric name → dotted path), `ok_when` (rules, below), `fail_state` (`down` or
`warn`), `kind` (entity kind, default `service`), and for a list answer `each` (dotted path to
the list), `id_field`, `name_field`. Redirects are not followed; answers over 2 MB are refused.

A 401/403 makes the state unknown ("refused the saved secret"), not down. A missing secret is
unknown too. Unreachable, a timeout or another non-2xx answer is down; an answer that isn't
JSON is warn.

```json
{"id": "pve", "name": "Proxmox", "adapter": "http_json", "address": "https://pve.local:8006",
 "secret": "pve_api_token",
 "options": {"path": "/api2/json/cluster/resources", "auth_prefix": "PVEAPIToken=",
             "verify_tls": false, "each": "data", "id_field": "id", "name_field": "name",
             "kind": "vm", "fields": {"cpu": "cpu"},
             "ok_when": [{"path": "status", "op": "==", "value": "running"}]},
 "named_actions": [{"name": "reboot plex vm",
                    "request": {"method": "POST", "path": "/api2/json/nodes/pve/qemu/100/status/reboot"}}]}
```

#### Rules (`ok_when`)
A list of `{"path", "op", "value"}`; all must hold for ok. `path` is a dotted path of object
keys and list indexes (`data.0.status`); segments are letters, digits, `_` and `-`, never
starting with `__`. `op` is one of `==`, `!=`, `<`, `<=`, `>`, `>=`, `in` (value is a list),
`contains` (substring of a string, or member of a list). Ordering needs a number on both
sides (numeric strings count). A missing value makes the comparison false. Rules are parsed
by a strict model and evaluated by item lookups only: nothing is ever passed to `eval`.

### `prometheus`
`mode: "exporter"` GETs `path` (default `/metrics`) and parses the text exposition format
(comments, labels with escapes, `NaN`, `±Inf`, timestamps). `mode: "query"` GETs
`/api/v1/query?query=<query>` and reads a vector or scalar result. `series` (1-32) each pick
samples by `metric` name and label equality (`labels`), store the value as `as_metric` and set
the state with `down_below`, `down_above`, `warn_below`, `warn_above`. With `each_label`
every distinct value of that label is its own entity; otherwise the system is one entity.
Same auth options as `http_json`.

```json
{"id": "kuma", "name": "Uptime Kuma", "adapter": "prometheus",
 "address": "http://192.168.1.9:3001", "secret": "kuma_api_key",
 "options": {"auth_prefix": "Bearer ", "each_label": "monitor_name",
             "series": [{"metric": "monitor_status", "as_metric": "up", "down_below": 1},
                        {"metric": "monitor_response_time", "as_metric": "ms", "warn_above": 1500}]}}
```

```json
{"id": "prom", "name": "Prometheus", "adapter": "prometheus",
 "address": "http://192.168.1.2:9090",
 "options": {"mode": "query", "query": "up", "each_label": "job",
             "series": [{"metric": "up", "as_metric": "up", "down_below": 1}]}}
```

### `ssh`
Windows' OpenSSH client (`%SystemRoot%\System32\OpenSSH\ssh.exe`, else `ssh` on PATH), run
with no shell, the minimal child environment and a kill-on-close job, always with
`-F none -T -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=<JARVIS's
file> -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no -o IdentitiesOnly=yes
-o ConnectTimeout=8 -i <key_path> -p <port> -l <user>`. Options: `user`, `key_path` (full path
of a private key without a passphrase), `port` (default 22), `presets`, `units`, `timeout_s`
(5-60, default 20).

One connection per probe runs only these read-only presets, each after a marker line, with
`LC_ALL=C`:

| Preset | Command | Becomes |
|---|---|---|
| `uptime` | `uptime` | host `load1`, `load5`, `load15`, `uptime_days` |
| `df` | `df -P` | one `disk` entity per real mount with `disk_used_pct` (warn over 90) |
| `free` | `free -m` | host `mem_used_pct`, `mem_total_mb` |
| `systemctl` | `systemctl is-active <units>` | one `service` entity per unit |
| `docker` | `docker ps -a --format '{{json .}}'` | one `container` entity per container (`-a` so a crashed container shows as down) |
| `sensors` | `sensors -j` | host `temp_c` (the hottest `temp*_input`) |

`units` must match `^[A-Za-z0-9_][A-Za-z0-9@_.:-]{0,79}$`. The brain never sends shell text:
it can only pick an owner-defined named action, whose fixed `command` runs as saved, after an
approval card that shows it.

**Trust first.** Until its host key is in JARVIS's `known_hosts` (`<data>\homelab\known_hosts`,
never the owner's `~\.ssh\known_hosts`) a system shows "Not trusted yet" and no connection is
made. `homelab_trust_host` runs `ssh-keyscan -T 5 -p <port> -t ed25519,ecdsa,rsa <address>`,
shows each key's type and SHA256 fingerprint on an always-ask card, and only on approval
appends the lines. A key mismatch or a refused key reads as unknown (with a plain reason);
any other connection failure is down. stdout and stderr are parsed in memory, never logged.

```json
{"id": "nas", "name": "NAS", "adapter": "ssh", "address": "192.168.1.5",
 "options": {"user": "jarvis", "key_path": "C:\\Users\\me\\.ssh\\jarvis_nas",
             "presets": ["uptime", "df", "free", "systemctl", "docker", "sensors"],
             "units": ["smbd.service", "restic-backup.timer"], "temp_max_c": 75},
 "named_actions": [{"name": "restart plex", "command": "docker restart plex"}]}
```

### `wol`
Options: `mac`, `broadcast` (default `255.255.255.255`; private or link-local only), `port`
(7 or 9). The magic packet is 6 × `0xFF` then the MAC 16 times, sent as one UDP broadcast.
A wol system has nothing to watch (its entity is unknown); add a ping system for its state.

```json
{"id": "gaming-pc", "name": "Gaming PC", "adapter": "wol", "address": "192.168.1.20",
 "options": {"mac": "aa:bb:cc:dd:ee:02", "broadcast": "192.168.1.255"}}
```

## Polling and signals

`HomelabRegistry` checks every 5 s which systems are due. A system's first probe is jittered
(up to 30 s), later ones come every `interval_s` ± 10 %. At most 4 probes run at once, each cut
at 75 s, and none run while the resident is in gaming mode (`homelab_probe_now` still works,
because the owner asked). A malformed settings entry is skipped with a content-free warning.

Signals are `homelab.alert` from source `homelab` with `data = {host, entity, condition}`:

| Condition | When | Urgency |
|---|---|---|
| `host_down` | a `host` entity is down for 2 probes in a row | 2 |
| `service_down` | any other entity (port, unit, container, VM, …) is down for 2 probes in a row | 1 |
| `disk_full` | metric `disk_used_pct` over 90 | 1 |
| `hot` | metric `temp_c` over the system's `temp_max_c` | 1 |
| `backup_failed` | a `backup` entity is down, or metric `backup_ok` is 0/false/failed/error | 1 |
| `on_battery` | metric `ups_on_battery` is truthy, or `ups_status` has the token `OB` (NUT) | 2 |

So any adapter can feed them: map a field to `disk_used_pct`, `temp_c`, `backup_ok`,
`ups_on_battery` or `ups_status` (http_json `fields`, prometheus `as_metric`), or set `kind`
to `backup`. Down needs two probes in a row so one lost ping doesn't wake anyone.

One signal per entity and condition while it lasts (12 h expiry). When the entity reports
again without the condition, it clears and its pending signal is acknowledged; a later return
signals again. An entity in the unknown state (a missing secret, an untrusted host, a refused
key, a check that failed) changes nothing. Removing or changing a system drops its state and
alerts.

## Brain tools

| Tool | Asks | Notes |
|---|---|---|
| `homelab_status(scope)` | never (permission default False) | `scope` is a system id or `all`; compact entities from memory, no probe. Untrusted output (names and details come from the systems) |
| `homelab_action(host, action)` | always (`always_ask`), outward | Only an owner-defined named action; the card's `exact` fact is the command (`On user@host: …`) or request (`POST https://…/path`) |
| `homelab_wake(host)` | always, outward | A wol system or one with `wake_mac`; the card shows the MAC, broadcast and port |
| `homelab_trust_host(host)` | through `homelab_trust_host_confirm` (always, outward) | ssh systems only; the card shows the fingerprints |

`homelab_trust_host_confirm` is model-invisible and refuses any call that doesn't carry the
scan `homelab_trust_host` just made, before any card.

**Physical-security class.** `services.homelab.PHYSICAL_SECURITY_TOOLS` lists
`homelab_action`, `homelab_wake`, `homelab_trust_host` and `homelab_trust_host_confirm`: the
tools whose approval card is not answered from a remote channel (S8.1) unless the owner turns
that on.

## Owner-only routes

`homelab_status {}`, `homelab_hosts_get {}`, `homelab_hosts_save {hosts}` (validated whole;
a problem is reported as `field: message` without the submitted value) and
`homelab_probe_now {host}`. Each needs the authenticated, unlocked desktop owner renderer.
See `docs/ROUTE_POLICY_MATRIX.json`.

## Safety rules

- The brain names a system and an action; it never sends a command, a URL, a header or a body.
- Every child process (ping, ssh, ssh-keyscan) gets the minimal environment, a kill-on-close
  job, an argv list (no shell) and a timeout.
- Secrets are referenced by name, resolved at request time, sent only in a header, and never
  logged, returned, put in argv or in a URL.
- Logs carry the adapter kind and an error class only: never an address, a secret, a command
  or any output. Settings errors don't echo submitted values.
- SSH connects only to hosts whose key the owner approved, with BatchMode and strict host key
  checking; no passwords, no agent forwarding, no user ssh config.
- Wake-on-LAN packets go only to the home network's broadcast addresses.
