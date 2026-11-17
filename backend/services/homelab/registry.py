"""The homelab poller (S12.3, docs/HOMELAB.md "Polling and signals").

``HomelabRegistry(app)`` reads ``homelab.hosts`` from settings (each entry a validated
``HostConfig``; a malformed entry is skipped), probes each system on its own interval
(jittered, at most ``MAX_CONCURRENT`` probes at once, never in gaming mode), keeps the latest
entities in memory and publishes ``homelab.alert`` signals when a condition starts:

    host_down      a host entity is down                         urgency 2 (2 probes in a row)
    service_down   any other entity is down                      urgency 1 (2 probes in a row)
    disk_full      metric disk_used_pct over 90                  urgency 1
    hot            metric temp_c over the system's temp_max_c    urgency 1
    backup_failed  a backup entity is down, or backup_ok falsy   urgency 1
    on_battery     ups_on_battery truthy or ups_status has "OB"  urgency 2

One signal per entity and condition while it lasts; when the entity reports without it the
condition clears (its pending signal is acknowledged) and a later return signals again. An
entity in the unknown state changes nothing. Logs carry the adapter kind and an error class
only: never an address, a secret, a command or any output.
"""

import asyncio
import datetime as dt
import json
import random
import sqlite3
import time
from pathlib import Path

from services.homelab.adapters import ADAPTERS
from services.homelab.adapters.common import AdapterContext
from services.homelab.adapters.ssh import KnownHosts, SshAdapter
from services.homelab.adapters.wol import send_udp, wake_target, magic_packet
from services.homelab.base import AdapterError, Entity, HostConfig, worst
from services.homelab.process import run_process
from services.log import get_logger
from services.storage import StorageError
from services.tools import ServiceError

logger = get_logger(__name__)

TICK_S = 5.0
FIRST_JITTER_S = 30.0
MAX_CONCURRENT = 4
PROBE_TIMEOUT_S = 75.0
ALERT_TTL = dt.timedelta(hours=12)
DISK_FULL_PCT = 90.0
STATUS_ENTITY_LIMIT = 40
CONDITIONS = {  # name -> (urgency, probes in a row before it signals)
    "host_down": (2, 2),
    "service_down": (1, 2),
    "disk_full": (1, 1),
    "hot": (1, 1),
    "backup_failed": (1, 1),
    "on_battery": (2, 1),
}
_FALSY = {"0", "false", "no", "off", "fail", "failed", "error", "bad"}
_TRUTHY = {"1", "true", "yes", "on"}


def utc_now():
    return dt.datetime.now(dt.timezone.utc)


def host_configs(settings):
    """The validated ``homelab.hosts`` by id; a malformed entry (or a repeated id) is skipped."""
    saved = settings.get("homelab") if isinstance(settings, dict) else None
    hosts = saved.get("hosts") if isinstance(saved, dict) else None
    result = {}
    for item in hosts if isinstance(hosts, list) else ():
        try:
            config = HostConfig.model_validate(item)
        except ValueError:
            # Pydantic details can include the owner's command text: report nothing more.
            logger.warning("A homelab entry in settings is invalid and was skipped")
            continue
        result.setdefault(config.id, config)
    return result


def _number(value):
    return value if isinstance(value, float) else None


def _truthy(value):
    if isinstance(value, float):
        return value != 0
    return isinstance(value, str) and value.strip().lower() in _TRUTHY


def _falsy(value):
    if isinstance(value, float):
        return value == 0
    return isinstance(value, str) and value.strip().lower() in _FALSY


def conditions(entity, config):
    """The alert conditions ``entity`` shows now (see the module docstring)."""
    found = set()
    metrics = entity.metrics
    if entity.state == "down":
        if entity.kind == "host":
            found.add("host_down")
        elif entity.kind == "backup":
            found.add("backup_failed")
        else:
            found.add("service_down")
    disk = _number(metrics.get("disk_used_pct"))
    if disk is not None and disk > DISK_FULL_PCT:
        found.add("disk_full")
    temperature = _number(metrics.get("temp_c"))
    limit = config.options.get("temp_max_c", 80)
    if temperature is not None and temperature > limit:
        found.add("hot")
    if "backup_ok" in metrics and _falsy(metrics["backup_ok"]):
        found.add("backup_failed")
    status = metrics.get("ups_status")
    if _truthy(metrics.get("ups_on_battery")) or (
        isinstance(status, str) and "OB" in status.upper().split()
    ):
        found.add("on_battery")
    return found


def alert_title(condition, entity, config):
    metrics = entity.metrics
    if condition == "host_down":
        return f"{config.name} is down"
    if condition == "service_down":
        return f"{entity.name} on {config.name} is down"
    if condition == "disk_full":
        return f"{entity.name} on {config.name} is {metrics['disk_used_pct']:.0f}% full"
    if condition == "hot":
        return f"{config.name} is running hot ({metrics['temp_c']:.0f} °C)"
    if condition == "backup_failed":
        return f"A backup on {config.name} failed ({entity.name})"
    return f"The UPS on {config.name} is on battery"


class HomelabRegistry:
    """Owned by the composition root (application.py); ``start()`` / ``close()``."""

    def __init__(self, app, *, runner=run_process, transport=None, connect=None,
                 udp=send_udp, known_hosts=None, sleep=asyncio.sleep, monotonic=time.monotonic,
                 rand=random.random, now=utc_now, programs=None):
        self.app = app
        if known_hosts is None:
            database = getattr(app, "database", None)
            folder = Path(getattr(database, "directory", None) or ".") / "homelab"
            known_hosts = folder / "known_hosts"
        self.known_hosts = KnownHosts(known_hosts)
        self.context = AdapterContext(
            secret=self.secret, run=runner, known_hosts=self.known_hosts, transport=transport,
            send_udp=udp, programs=dict(programs or {}),
        )
        if connect is not None:
            self.context.connect = connect
        self.sleep, self.monotonic, self.rand, self.now = sleep, monotonic, rand, now
        self.semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        self.entities = {}  # host id -> [Entity]
        self.checked_at = {}  # host id -> ISO time of the last probe
        self.due = {}  # host id -> monotonic time of the next probe
        self.inflight = {}  # host id -> asyncio.Task
        self.active = {}  # (entity id, condition) -> dedupe_key of its signal
        self.streak = {}  # (entity id, condition) -> probes in a row showing it
        self.owners = {}  # (entity id, condition) -> host id
        self.scans = {}  # host id -> HostKeyScan awaiting the owner's approval
        self._raw = None
        self._hosts = {}
        self._serial = 0
        self.runner = None

    # --- lifetime ------------------------------------------------------------------------------
    def start(self):
        if self.runner is None or self.runner.done():
            self.runner = asyncio.get_running_loop().create_task(self.run(), name="homelab")
        return self.runner

    async def close(self):
        runner, self.runner = self.runner, None
        tasks = [task for task in (runner, *self.inflight.values()) if task and not task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.inflight.clear()

    async def run(self):
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Homelab polling failed (%s)", type(exc).__name__)
            await self.sleep(TICK_S)

    def gaming(self):
        return getattr(getattr(self.app, "resources", None), "state", None) == "gaming"

    # --- configuration ---------------------------------------------------------------------------
    def hosts(self):
        """The current validated hosts; state for removed or changed hosts is dropped."""
        settings = getattr(self.app, "settings", None)
        saved = settings.get("homelab") if isinstance(settings, dict) else None
        raw = json.dumps(saved, sort_keys=True, default=str)
        if raw != self._raw:
            previous, self._hosts = self._hosts, host_configs(settings)
            self._raw = raw
            for host_id, config in previous.items():
                if self._hosts.get(host_id) != config:
                    self.forget(host_id)
        return self._hosts

    def host(self, host_id):
        config = self.hosts().get(host_id)
        if config is None:
            raise ServiceError("homelab_unknown_host", "There's no system with that id.")
        return config

    def forget(self, host_id):
        self.entities.pop(host_id, None)
        self.checked_at.pop(host_id, None)
        self.due.pop(host_id, None)
        self.scans.pop(host_id, None)
        task = self.inflight.pop(host_id, None)
        if task is not None and not task.done():
            task.cancel()
        for key in [key for key, owner in self.owners.items() if owner == host_id]:
            self._clear(key)
            self.streak.pop(key, None)
            self.owners.pop(key, None)

    def adapter(self, config):
        return ADAPTERS[config.adapter](config, self.context)

    def secret(self, name):
        """A secret's value by name: a known JARVIS secret, else the owner's own name in the
        same encrypted store. None when unset or unreadable (never logged)."""
        store = getattr(self.app, "secrets", None)
        if store is None:
            return None
        from services.secrets import REGISTRY

        try:
            if name in REGISTRY:
                return store.get(name)
            document = store._document(name)
        except (StorageError, sqlite3.Error, OSError):
            return None
        value = document.get("value") if isinstance(document, dict) else None
        return value if isinstance(value, str) and value else None

    # --- polling ---------------------------------------------------------------------------------
    async def tick(self):
        """Start the probes that are due; returns the started tasks (none in gaming mode)."""
        if self.gaming():
            return []
        now = self.monotonic()
        started = []
        for host_id, config in self.hosts().items():
            if host_id not in self.due:
                self.due[host_id] = now + self.rand() * min(config.interval_s, FIRST_JITTER_S)
            running = self.inflight.get(host_id)
            if self.due[host_id] > now or (running is not None and not running.done()):
                continue
            self.due[host_id] = now + config.interval_s * (0.9 + 0.2 * self.rand())
            task = asyncio.get_running_loop().create_task(self.probe(config),
                                                          name=f"homelab-{host_id}")
            self.inflight[host_id] = task
            started.append(task)
        return started

    async def probe(self, config):
        """Probe one system now, record its entities and publish what changed."""
        async with self.semaphore:
            try:
                async with asyncio.timeout(PROBE_TIMEOUT_S):
                    entities = await self.adapter(config).probe()
            except asyncio.CancelledError:
                raise
            except AdapterError as exc:
                entities = [Entity(config.id, config.id, "host", config.name, "unknown", {},
                                   str(exc))]
            except TimeoutError:
                entities = [Entity(config.id, config.id, "host", config.name, "unknown", {},
                                   "The check took too long.")]
            except Exception as exc:
                logger.warning("Homelab probe of a %s system failed (%s)", config.adapter,
                               type(exc).__name__)
                entities = [Entity(config.id, config.id, "host", config.name, "unknown", {},
                                   "The check failed.")]
        if self.hosts().get(config.id) != config:
            return entities  # removed or changed while it ran
        self.entities[config.id] = list(entities)
        self.checked_at[config.id] = self.now().isoformat(timespec="seconds")
        self.evaluate(config, entities)
        return entities

    async def probe_now(self, host_id):
        config = self.host(host_id)
        return await self.probe(config)

    # --- signals ---------------------------------------------------------------------------------
    def evaluate(self, config, entities):
        for entity in entities:
            if entity.state == "unknown":
                continue
            now = conditions(entity, config)
            for condition, (_urgency, needed) in CONDITIONS.items():
                key = (entity.id, condition)
                if condition in now:
                    self.streak[key] = self.streak.get(key, 0) + 1
                    self.owners[key] = config.id
                    if key not in self.active and self.streak[key] >= needed:
                        self._raise(config, entity, condition)
                else:
                    self.streak.pop(key, None)
                    if key in self.active:
                        self._clear(key)
                        self.owners.pop(key, None)

    def _raise(self, config, entity, condition):
        from services.signals import signal

        hub = getattr(self.app, "signals", None)
        at = self.now()
        self._serial += 1
        key = f"homelab:{entity.id}:{condition}:{int(at.timestamp())}:{self._serial}"
        self.active[(entity.id, condition)] = key
        if hub is None:
            return
        hub.publish(signal(
            "homelab.alert", "homelab", alert_title(condition, entity, config), at=at,
            dedupe_key=key, ttl=ALERT_TTL, urgency=CONDITIONS[condition][0],
            body=entity.detail,
            data={"host": config.id, "entity": entity.id, "condition": condition},
        ))

    def _clear(self, key):
        dedupe_key = self.active.pop(key, None)
        hub = getattr(self.app, "signals", None)
        if dedupe_key and hub is not None:
            hub.ack(dedupe_key)

    # --- actions ---------------------------------------------------------------------------------
    def named_action(self, host_id, action):
        config = self.host(host_id)
        named = config.action(action)
        if named is None:
            raise ServiceError("homelab_unknown_action",
                               "That action isn't set up for this system.")
        return config, named

    def describe_action(self, host_id, action):
        """The exact command or request the approval card shows."""
        config, named = self.named_action(host_id, action)
        adapter = self.adapter(config)
        if isinstance(adapter, SshAdapter):
            return config, adapter.describe(named)
        return config, named.describe(config.address)

    async def act(self, host_id, action):
        config, _named = self.named_action(host_id, action)
        try:
            return await self.adapter(config).act(action, {})
        except AdapterError as exc:
            raise ServiceError(exc.code, str(exc)) from None

    def wake_target(self, host_id):
        config = self.host(host_id)
        target = wake_target(config)
        if target is None:
            raise ServiceError("homelab_no_wake", "This system has no Wake-on-LAN address.")
        return config, target

    async def wake(self, host_id):
        _config, (mac, broadcast, port) = self.wake_target(host_id)
        try:
            await asyncio.to_thread(self.context.send_udp, magic_packet(mac), (broadcast, port))
        except OSError as exc:
            logger.info("Wake-on-LAN send failed (%s)", type(exc).__name__)
            raise ServiceError("homelab_wake_failed", "The wake packet couldn't be sent.") from None
        return {"sent": True}

    # --- SSH trust -------------------------------------------------------------------------------
    def ssh_adapter(self, host_id):
        config = self.host(host_id)
        if config.adapter != "ssh":
            raise ServiceError("homelab_not_ssh", "Only ssh systems have a host key to trust.")
        return self.adapter(config)

    def trusted(self, host_id):
        adapter = self.ssh_adapter(host_id)
        return self.known_hosts.has(adapter.token)

    async def scan(self, host_id):
        adapter = self.ssh_adapter(host_id)
        try:
            scan = await adapter.scan_keys()
        except AdapterError as exc:
            raise ServiceError(exc.code, str(exc)) from None
        self.scans[host_id] = scan
        return scan

    def trust(self, host_id, scan):
        """Write the approved scan's keys to JARVIS's known_hosts."""
        adapter = self.ssh_adapter(host_id)
        if self.scans.get(host_id) is not scan or scan.token != adapter.token:
            raise ServiceError("homelab_scan_changed",
                               "The host key changed since it was shown; check it again.")
        self.known_hosts.add(scan.token, scan.keys)
        self.scans.pop(host_id, None)
        return {"trusted": True, "keys": len(scan.keys)}

    # --- status ----------------------------------------------------------------------------------
    def _host_summary(self, config):
        entities = self.entities.get(config.id, [])
        return {
            "id": config.id, "name": config.name, "adapter": config.adapter,
            "state": worst([entity.state for entity in entities]),
            "checked_at": self.checked_at.get(config.id),
        }

    def status_for_brain(self, scope="all"):
        hosts = self.hosts()
        if scope != "all":
            hosts = {scope: self.host(scope)}
        result = []
        for config in hosts.values():
            entities = self.entities.get(config.id, [])
            item = self._host_summary(config)
            item["entities"] = [
                {key: value for key, value in (
                    ("name", entity.name), ("kind", entity.kind), ("state", entity.state),
                    ("metrics", entity.metrics),
                    ("detail", entity.detail if entity.state != "ok" else ""),
                ) if value not in ("", {})}
                for entity in entities[:STATUS_ENTITY_LIMIT]
            ]
            if len(entities) > STATUS_ENTITY_LIMIT:
                item["more"] = len(entities) - STATUS_ENTITY_LIMIT
            if config.named_actions:
                item["actions"] = [action.name for action in config.named_actions]
            result.append(item)
        return {"hosts": result, "paused": self.gaming()}

    def status_for_owner(self):
        hosts = []
        for config in self.hosts().values():
            item = self._host_summary(config)
            item.update(
                address=config.address, interval_s=config.interval_s,
                actions=[action.name for action in config.named_actions],
                can_wake=wake_target(config) is not None,
                entities=[entity.as_dict() for entity in self.entities.get(config.id, [])],
            )
            if config.adapter == "ssh":
                item["trusted"] = self.known_hosts.has(self.adapter(config).token)
            hosts.append(item)
        return {"hosts": hosts, "paused": self.gaming()}
