"""``ssh``: read-only command presets over Windows' OpenSSH client, and the host-key trust.

The client is ``%SystemRoot%\\System32\\OpenSSH\\ssh.exe`` (else ``ssh`` on PATH), run with
no shell, the minimal environment and a kill-on-close job, and always with
``BatchMode=yes``, ``StrictHostKeyChecking=yes`` and JARVIS's own known_hosts file, key
auth only (``-i <key_path>``, ``IdentitiesOnly=yes``, no passwords) and ``-F none`` (the
owner's ssh config doesn't apply).

The remote command is built only from fixed presets (``PRESETS``) and systemd unit names
that pass ``UNIT``: the brain can never send shell text. An owner-defined named action is
the one other command that runs, exactly as the owner saved it, after an approval card.

A host must be trusted first: ``scan_keys`` runs ``ssh-keyscan``, the owner compares the
fingerprints on an always-ask card, and ``KnownHosts.add`` writes the approved lines.
Output (stdout and stderr) is parsed in memory, never logged or returned whole.
"""

import base64
import binascii
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Annotated, Literal

from pydantic import Field, StrictInt, StrictStr, StringConstraints, field_validator

from services.homelab.adapters.common import BaseAdapter, WakeOptions
from services.homelab.base import AdapterError
from services.homelab.process import program

MARK = "@@jarvis:"
# Read-only presets. ``systemctl`` takes the validated ``units``; nothing else is ever sent.
PRESETS = {
    "uptime": "uptime",
    "df": "df -P",
    "free": "free -m",
    "systemctl": "systemctl is-active",
    "docker": "docker ps -a --format '{{json .}}'",
    "sensors": "sensors -j",
}
PresetName = Literal["uptime", "df", "free", "systemctl", "docker", "sensors"]
# A systemd unit name: letters, digits and @ _ . : - (never a leading dash), optionally typed.
UNIT = r"^[A-Za-z0-9_][A-Za-z0-9@_.:-]{0,79}$"
USER = r"^[a-z_][a-z0-9_.-]{0,31}$"
KEY_TYPES = ("ssh-ed25519", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384",
             "ecdsa-sha2-nistp521", "ssh-rsa")
PSEUDO_FILESYSTEMS = ("tmpfs", "devtmpfs", "udev", "overlay", "squashfs", "none", "shm",
                      "efivarfs", "proc", "sysfs", "cgroup", "run")
DISK_LIMIT = 32
CONTAINER_LIMIT = 100


class SshOptions(WakeOptions):
    user: Annotated[StrictStr, StringConstraints(pattern=USER)]
    key_path: StrictStr = Field(min_length=3, max_length=400)
    port: StrictInt = Field(default=22, ge=1, le=65535)
    presets: list[PresetName] = Field(default_factory=lambda: ["uptime", "df", "free"],
                                      min_length=1, max_length=6)
    units: list[Annotated[StrictStr, StringConstraints(pattern=UNIT)]] = Field(
        default_factory=list, max_length=32)
    timeout_s: StrictInt = Field(default=20, ge=5, le=60)

    @field_validator("key_path")
    @classmethod
    def absolute_key(cls, value):
        if any(ord(char) < 32 for char in value) or not (
            PureWindowsPath(value).is_absolute() or Path(value).is_absolute()
        ):
            raise ValueError("Use the full path of the private key file.")
        return value

    @field_validator("presets")
    @classmethod
    def distinct(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("List each preset once.")
        return value


def remote_command(presets, units):
    """The one remote command a probe sends: fixed presets, each after a marker line."""
    parts = ["export LC_ALL=C"]
    for name in presets:
        if name not in PRESETS:
            raise AdapterError("homelab_bad_preset", "That check isn't a JARVIS preset.")
        command = PRESETS[name]
        if name == "systemctl":
            if not units:
                continue
            if not all(re.fullmatch(UNIT, unit) for unit in units):
                raise AdapterError("homelab_bad_unit", "That unit name isn't allowed.")
            command = f"{command} {' '.join(units)}"
        parts.append(f"echo {MARK}{name}; {command} 2>/dev/null")
    return "; ".join(parts)


def sections(stdout):
    """{preset: text} from the marked output."""
    found, current, lines = {}, None, []
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        if line.startswith(MARK):
            if current is not None:
                found[current] = "\n".join(lines)
            current, lines = line[len(MARK):].strip(), []
        elif current is not None:
            lines.append(line)
    if current is not None:
        found[current] = "\n".join(lines)
    return found


# --- parsers ----------------------------------------------------------------------------------

_LOAD = re.compile(r"load averages?:\s*([\d.]+),?\s+([\d.]+),?\s+([\d.]+)")
_UP_DAYS = re.compile(r"\bup\s+(\d+)\s+day")


def parse_uptime(text):
    metrics = {}
    match = _LOAD.search(text or "")
    if match:
        metrics.update(load1=float(match.group(1)), load5=float(match.group(2)),
                       load15=float(match.group(3)))
    days = _UP_DAYS.search(text or "")
    if days:
        metrics["uptime_days"] = float(days.group(1))
    elif match:
        metrics["uptime_days"] = 0.0
    return metrics


def parse_df(text):
    """[(mount, used_pct, used_kb, available_kb)] from ``df -P`` (pseudo filesystems skipped)."""
    disks = []
    for line in (text or "").splitlines()[1:]:
        parts = line.split()
        if len(parts) < 6 or not parts[4].endswith("%"):
            continue
        source, mount = parts[0], " ".join(parts[5:])
        if source in PSEUDO_FILESYSTEMS or mount.startswith(("/proc", "/sys", "/dev", "/run")):
            continue
        try:
            used_pct = float(parts[4].rstrip("%"))
            used, available = float(parts[2]), float(parts[3])
        except ValueError:
            continue
        disks.append((mount, used_pct, used, available))
        if len(disks) >= DISK_LIMIT:
            break
    return disks


def parse_free(text):
    for line in (text or "").splitlines():
        parts = line.split()
        if parts and parts[0] == "Mem:" and len(parts) >= 3:
            try:
                total = float(parts[1])
                available = float(parts[6]) if len(parts) >= 7 else total - float(parts[2])
            except ValueError:
                return {}
            if total <= 0:
                return {}
            return {"mem_total_mb": total,
                    "mem_used_pct": round((total - available) / total * 100, 1)}
    return {}


def parse_systemctl(text, units):
    """{unit: state} from ``systemctl is-active u1 u2`` (one line per unit, in order)."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return {unit: (lines[index] if index < len(lines) else "unknown")
            for index, unit in enumerate(units)}


def unit_state(text):
    if text == "active":
        return "ok"
    if text in ("inactive", "failed", "dead"):
        return "down"
    if text == "unknown":
        return "unknown"
    return "warn"  # activating, deactivating, reloading


def parse_docker(text):
    """[(name, state, status, image)] from ``docker ps --format '{{json .}}'`` lines."""
    containers = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if not isinstance(item, dict):
            continue
        name = str(item.get("Names") or item.get("ID") or "").split(",")[0].strip()
        if not name:
            continue
        state = str(item.get("State") or "").lower()
        if not state:
            status = str(item.get("Status") or "").lower()
            state = "running" if status.startswith("up") else "exited"
        containers.append((name[:80], state, str(item.get("Status") or "")[:80],
                           str(item.get("Image") or "")[:80]))
        if len(containers) >= CONTAINER_LIMIT:
            break
    return containers


def container_state(state):
    if state == "running":
        return "ok"
    if state in ("exited", "dead"):
        return "down"
    return "warn"  # restarting, paused, created, removing


def parse_sensors(text):
    """The hottest ``temp*_input`` reading in ``sensors -j`` output, or None."""
    try:
        data = json.loads(text or "")
    except ValueError:
        return None
    readings = []

    def walk(value, depth=0):
        if depth > 4 or not isinstance(value, dict):
            return
        for key, item in value.items():
            if isinstance(item, dict):
                walk(item, depth + 1)
            elif (isinstance(key, str) and key.startswith("temp") and key.endswith("_input")
                  and isinstance(item, (int, float)) and not isinstance(item, bool)
                  and -50 < item < 200):
                readings.append(float(item))

    walk(data)
    return max(readings) if readings else None


# --- known_hosts and host keys --------------------------------------------------------------


def host_token(host, port):
    return host if int(port) == 22 else f"[{host}]:{port}"


def fingerprint(blob):
    digest = hashlib.sha256(blob).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


@dataclass(frozen=True)
class HostKey:
    key_type: str
    blob: str  # base64, as in known_hosts
    fingerprint: str

    def line(self, token):
        return f"{token} {self.key_type} {self.blob}"


@dataclass(frozen=True)
class HostKeyScan:
    host_id: str
    token: str
    keys: tuple

    @property
    def fingerprints(self):
        return [key.fingerprint for key in self.keys]


def parse_keyscan(stdout, token):
    """The keys in ``ssh-keyscan`` output for exactly ``token`` (other lines are ignored)."""
    keys, seen = [], set()
    for line in stdout.decode("ascii", errors="replace").splitlines():
        parts = line.strip().split()
        if len(parts) < 3 or parts[0].startswith("#") or parts[0].lower() != token.lower():
            continue
        key_type, blob = parts[1], parts[2]
        if key_type not in KEY_TYPES or blob in seen:
            continue
        try:
            raw = base64.b64decode(blob, validate=True)
        except (binascii.Error, ValueError):
            continue
        if not raw:
            continue
        seen.add(blob)
        keys.append(HostKey(key_type, blob, fingerprint(raw)))
    return keys


class KnownHosts:
    """JARVIS's own known_hosts file (never the owner's ~/.ssh/known_hosts)."""

    def __init__(self, path):
        self.path = Path(path)

    def lines(self):
        try:
            return self.path.read_text(encoding="ascii", errors="replace").splitlines()
        except FileNotFoundError:
            return []

    def has(self, token):
        token = token.lower()
        return any(line.split(maxsplit=1)[0].lower() == token
                   for line in self.lines() if line.strip() and not line.startswith("#"))

    def add(self, token, keys):
        """Append the approved keys for ``token`` (atomically; existing lines kept)."""
        current = self.lines()
        wanted = [key.line(token) for key in keys]
        merged = current + [line for line in wanted if line not in current]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=self.path.parent, prefix="known_hosts.",
                                             suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="ascii", newline="\n") as stream:
                stream.write("\n".join(merged) + "\n")
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def option(self):
        """The UserKnownHostsFile option (forward slashes, quoted for ssh's parser)."""
        return f'UserKnownHostsFile="{self.path.as_posix()}"'


# --- the adapter ------------------------------------------------------------------------------


class SshAdapter(BaseAdapter):
    Options = SshOptions

    @property
    def token(self):
        return host_token(self.config.address, self.options.port)

    def argv(self, command):
        path = self.context.programs.get("ssh") or program("ssh")
        return [
            path, "-F", "none", "-T",
            "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes",
            "-o", self.context.known_hosts.option(),
            "-o", "PasswordAuthentication=no",
            "-o", "KbdInteractiveAuthentication=no",
            "-o", "IdentitiesOnly=yes",
            "-o", "ConnectTimeout=8",
            "-o", "LogLevel=ERROR",
            "-i", self.options.key_path,
            "-p", str(self.options.port),
            "-l", self.options.user,
            self.config.address,
            command,
        ]

    def keyscan_argv(self):
        path = self.context.programs.get("ssh-keyscan") or program("ssh-keyscan")
        return [path, "-T", "5", "-p", str(self.options.port), "-t", "ed25519,ecdsa,rsa",
                self.config.address]

    async def scan_keys(self):
        result = await self.context.run(self.keyscan_argv(), timeout=15,
                                        label="A homelab host-key scan")
        keys = parse_keyscan(result.stdout, self.token)
        if not keys:
            raise AdapterError("homelab_no_host_key", "The system didn't offer an SSH host key.")
        return HostKeyScan(self.config.id, self.token, tuple(keys))

    def _host(self, state, metrics=None, detail=""):
        return self.entity(None, "host", self.config.name, state, metrics, detail)

    async def _ssh(self, command, label):
        if not self.context.known_hosts.has(self.token):
            raise AdapterError("homelab_not_trusted",
                               "Not trusted yet: approve its SSH host key first.")
        if not Path(self.options.key_path).is_file():
            raise AdapterError("homelab_key_missing", "The SSH key file isn't there.")
        return await self.context.run(self.argv(command), timeout=float(self.options.timeout_s),
                                      label=label)

    @staticmethod
    def _failure(result):
        """(state, detail) for ssh's own failure (exit 255); stderr is only classified."""
        text = result.stderr.decode("utf-8", errors="replace").lower()
        if "host key verification failed" in text or "remote host identification" in text:
            return "unknown", "The SSH host key doesn't match the trusted one."
        if "permission denied" in text:
            return "unknown", "The system refused JARVIS's SSH key."
        return "down", "SSH couldn't connect."

    async def probe(self):
        command = remote_command(self.options.presets, self.options.units)
        try:
            result = await self._ssh(command, "A homelab SSH check")
        except AdapterError as exc:
            state = "down" if exc.code == "timeout" else "unknown"
            return [self._host(state, {}, str(exc))]
        if result.code == 255:
            state, detail = self._failure(result)
            return [self._host(state, {}, detail)]
        found = sections(result.stdout)
        metrics = {}
        metrics.update(parse_uptime(found.get("uptime", "")))
        metrics.update(parse_free(found.get("free", "")))
        temperature = parse_sensors(found.get("sensors", "")) if "sensors" in found else None
        if temperature is not None:
            metrics["temp_c"] = temperature
        entities = [self._host("ok", metrics, "Answered over SSH.")]
        for mount, used_pct, used, available in parse_df(found.get("df", "")):
            entities.append(self.entity(
                f"disk:{mount}", "disk", mount, "warn" if used_pct > 90 else "ok",
                {"disk_used_pct": used_pct, "used_kb": used, "available_kb": available},
            ))
        if "systemctl" in found:
            for unit, text in parse_systemctl(found["systemctl"], self.options.units).items():
                entities.append(self.entity(f"unit:{unit}", "service", unit, unit_state(text),
                                            {"active": text[:40]}))
        for name, state, status, image in parse_docker(found.get("docker", "")):
            entities.append(self.entity(f"container:{name}", "container", name,
                                        container_state(state),
                                        {"status": status, "image": image}))
        return entities

    async def act(self, action, args):
        named = self.config.action(action)
        if named is None or named.command is None:
            raise AdapterError("homelab_unknown_action", "That action isn't set up for this system.")
        result = await self._ssh(named.command, "A homelab action")
        if result.code == 255:
            _state, detail = self._failure(result)
            raise AdapterError("homelab_ssh_failed", detail)
        return {"done": result.code == 0, "exit_code": result.code}

    def describe(self, action):
        """The exact command as the approval card shows it."""
        return f"On {self.options.user}@{self.token}: {action.command}"
