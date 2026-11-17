"""S12.3 homelab: adapters, the eval-free rules, the registry's polling and signals, the brain
tools' ask rules and the owner-only routes. No real network and no real subprocess: ping,
ssh and ssh-keyscan go through a fake runner (or a fake job_object.spawn), HTTP through
httpx.MockTransport, TCP and UDP through fakes."""

import asyncio
import base64
import builtins
import hashlib
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from services.homelab import PHYSICAL_SECURITY_TOOLS
from services.homelab import process as process_module
from services.homelab.adapters import ADAPTERS
from services.homelab.adapters.common import AdapterContext
from services.homelab.adapters.prometheus import parse_exposition, parse_query
from services.homelab.adapters.reach import parse_ping
from services.homelab.adapters.ssh import (
    PRESETS,
    KnownHosts,
    SshOptions,
    fingerprint,
    parse_keyscan,
    remote_command,
)
from services.homelab.adapters.wol import magic_packet
from services.homelab.base import (
    AdapterError,
    Comparison,
    HomelabHosts,
    HostConfig,
    compare,
    dotted,
    evaluate,
)
from services.homelab.process import ProcessResult, program, run_process
from services.homelab.registry import CONDITIONS, HomelabRegistry, conditions
from services.homelab.tools import register_homelab_tools
from services.signals import SignalHub
from services.tools import ServiceError, ToolDispatcher

PROGRAMS = {"ping": "PING.EXE", "ssh": "ssh.exe", "ssh-keyscan": "ssh-keyscan.exe"}
SECRET = "pve-token-0123456789abcdef-SECRET"
ED25519 = base64.b64encode(b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + bytes(range(32))).decode()
ECDSA = base64.b64encode(b"\x00\x00\x00\x13ecdsa-sha2-nistp256" + bytes(range(70))).decode()

PING_UP = (b"\r\nPinging 192.168.1.5 with 32 bytes of data:\r\n"
           b"Reply from 192.168.1.5: bytes=32 time=3ms TTL=64\r\n\r\n"
           b"Ping statistics for 192.168.1.5:\r\n"
           b"    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),\r\n")
PING_UNREACHABLE = (b"Reply from 192.168.1.1: Destination host unreachable.\r\n"
                    b"    Packets: Sent = 1, Received = 1, Lost = 0 (0% loss),\r\n")

METRICS_TEXT = """\
# HELP monitor_status Monitor Status (1 = UP, 0= DOWN, 2= PENDING, 3= MAINTENANCE)
# TYPE monitor_status gauge
monitor_status{monitor_name="Plex",monitor_type="http",monitor_url="https://plex.local"} 1
monitor_status{monitor_name="Nextcloud \\"cloud\\"",monitor_type="http"} 0
monitor_response_time{monitor_name="Plex"} 35
node_filesystem_avail_bytes{mountpoint="/"} NaN
node_hwmon_temp_celsius{chip="cpu",sensor="temp1"} 91.5 1700000000000
process_open_fds 12
broken line without a value {
"""
QUERY_JSON = {
    "status": "success",
    "data": {"resultType": "vector", "result": [
        {"metric": {"__name__": "up", "job": "node", "instance": "nas:9100"},
         "value": [1700000000.1, "1"]},
        {"metric": {"__name__": "up", "job": "pihole", "instance": "pi:9617"},
         "value": [1700000000.1, "0"]},
    ]},
}
SSH_OUTPUT = b"""@@jarvis:uptime
 10:01:02 up 3 days,  2:03,  1 user,  load average: 0.10, 0.20, 0.30
@@jarvis:df
Filesystem     1024-blocks      Used Available Capacity Mounted on
/dev/sda1         98303400  90000000   8303400      92% /
tmpfs              1000000         0   1000000       0% /run
/dev/sdb1        976284676 100000000 876284676      11% /mnt/data
@@jarvis:free
               total        used        free      shared  buff/cache   available
Mem:            7820        2100        3000          50        2720        5400
Swap:           2047           0        2047
@@jarvis:systemctl
active
failed
@@jarvis:docker
{"Names":"plex","State":"running","Status":"Up 3 days","Image":"plexinc/pms-docker"}
{"Names":"sonarr","State":"exited","Status":"Exited (1) 2 hours ago","Image":"sonarr"}
@@jarvis:sensors
{"coretemp-isa-0000":{"Adapter":"ISA adapter","Package id 0":{"temp1_input":86.0,"temp1_max":100.0},"Core 0":{"temp2_input":84.0}}}
"""


# --- helpers --------------------------------------------------------------------------------------


class Runner:
    """A fake child-process runner: ``responses`` maps the program name to a ProcessResult
    (or a callable taking argv and returning one)."""

    def __init__(self, responses=None):
        self.responses = dict(responses or {})
        self.calls = []

    async def __call__(self, argv, *, timeout, label, stdin=None):
        self.calls.append(list(argv))
        response = self.responses[argv[0]]
        return response(argv) if callable(response) else response


class Secrets:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, name):
        return self.values.get(name)

    def _document(self, name):
        return {"value": self.values[name]} if name in self.values else None


def host(**fields):
    base = {"id": "nas", "name": "NAS", "adapter": "ping", "address": "192.168.1.5"}
    return {**base, **fields}


def context(tmp_path, runner=None, transport=None, connect=None, secrets=None, udp=None):
    known = KnownHosts(tmp_path / "known_hosts")
    item = AdapterContext(secret=(secrets or {}).get, run=runner or Runner(),
                          known_hosts=known, transport=transport, send_udp=udp,
                          programs=dict(PROGRAMS))
    if connect is not None:
        item.connect = connect
    return item


def adapter(raw, ctx):
    config = HostConfig.model_validate(raw)
    return ADAPTERS[config.adapter](config, ctx)


def json_transport(payload, status=200, seen=None):
    def handle(request):
        if seen is not None:
            seen.append(request)
        body = payload if isinstance(payload, (bytes, str)) else json.dumps(payload)
        return httpx.Response(status, content=body if isinstance(body, bytes) else body.encode())

    return httpx.MockTransport(handle)


def make_app(hosts, secrets=None):
    app = SimpleNamespace(settings={"homelab": {"hosts": hosts}},
                          resources=SimpleNamespace(state="chat"),
                          secrets=Secrets(secrets))
    app.signals = SignalHub(app)
    return app


class Clock:
    def __init__(self):
        self.value = 1000.0

    def __call__(self):
        return self.value


def registry_for(app, tmp_path, runner=None, transport=None, connect=None, udp=None):
    return HomelabRegistry(app, runner=runner or Runner(), transport=transport, connect=connect,
                           udp=udp or (lambda packet, address: None),
                           known_hosts=tmp_path / "known_hosts", rand=lambda: 0.0,
                           monotonic=Clock(), programs=PROGRAMS)


async def run_tick(registry):
    tasks = await registry.tick()
    await asyncio.gather(*tasks)
    return tasks


def trust(tmp_path, token="192.168.1.5"):
    KnownHosts(tmp_path / "known_hosts").add(token, parse_keyscan(
        f"{token} ssh-ed25519 {ED25519}\n".encode(), token))


def key_file(tmp_path):
    path = tmp_path / "id_ed25519"
    path.write_text("not a real key")
    return str(path)


# --- configuration ----------------------------------------------------------------------------


def test_host_config_validates_and_normalises():
    config = HostConfig.model_validate(host(address=" NAS.Local "))
    assert config.address == "nas.local" and config.interval_s == 60
    assert config.options["timeout_ms"] == 1000
    for bad in (
        host(id="Bad Id"),
        host(address="-oProxyCommand=calc"),
        host(address="root@nas"),
        host(address="http://nas"),  # ping takes a bare host
        host(interval_s=5),
        host(interval_s=7200),
        host(adapter="telnet"),
        host(options={"unknown": 1}),
        host(secret="pve_token"),  # only http systems use a secret
        host(secret="Has-Bad Chars"),
        host(named_actions=[{"name": "reboot", "command": "reboot"}]),  # command needs ssh
        host(adapter="http_json", address="http://8.8.8.8"),  # http only at home
        host(adapter="http_json", address="https://user:pw@nas.example"),
        host(adapter="http_json", address="https://nas.example/?x=1"),
    ):
        with pytest.raises(ValidationError):
            HostConfig.model_validate(bad)
    with pytest.raises(ValidationError):
        HomelabHosts.model_validate({"hosts": [host(), host()]})  # repeated id
    with pytest.raises(ValidationError):
        HostConfig.model_validate(host(adapter="ssh", options={
            "user": "root", "key_path": "C:/k"},
            named_actions=[{"name": "a", "command": "x"}, {"name": "a", "command": "y"}]))


def test_settings_patch_takes_a_homelab_list_whole():
    from services.settings import SettingsPatch

    patch = SettingsPatch.model_validate({"homelab": {"hosts": [host()]}})
    dumped = patch.model_dump(exclude_unset=True)
    assert dumped["homelab"]["hosts"][0]["id"] == "nas"
    with pytest.raises(ValidationError):
        SettingsPatch.model_validate({"homelab": None})


# --- the rule language ------------------------------------------------------------------------


DATA = {"status": "ok", "temp": 41.5, "count": "7", "flags": ["a", "b"], "ok": True,
        "items": [{"name": "x"}], "msg": "backup finished"}


@pytest.mark.parametrize("path,op,value,expected", [
    ("status", "==", "ok", True), ("status", "!=", "ok", False), ("temp", ">", 40, True),
    ("temp", "<=", 41.5, True), ("count", ">=", 7, True), ("count", "<", 3, False),
    ("status", "in", ["ok", "degraded"], True), ("status", "in", ["down"], False),
    ("flags", "contains", "b", True), ("msg", "contains", "finished", True),
    ("items.0.name", "==", "x", True), ("items.3.name", "==", "x", False),
    ("missing", "!=", "x", False), ("ok", "==", True, True), ("ok", "==", 1, False),
    ("status", ">", 1, False),  # a string is never ordered
])
def test_comparisons(path, op, value, expected):
    rule = Comparison.model_validate({"path": path, "op": op, "value": value})
    assert compare(dotted(DATA, rule.path), rule.op, rule.value) is expected


@pytest.mark.parametrize("rule", [
    {"path": "status", "op": "__import__('os').system('calc')", "value": "ok"},
    {"path": "status", "op": "eval", "value": "ok"},
    {"path": "status; import os", "op": "==", "value": "ok"},
    {"path": "status.__class__", "op": "==", "value": "ok"},
    {"path": "a[0]", "op": "==", "value": 1},
    {"path": "status", "op": "==", "value": {"$where": "1"}},
    {"path": "status", "op": "in", "value": "ok"},
    {"path": "status", "op": "==", "value": ["ok"]},
    {"path": "status", "op": ">", "value": "1"},
    {"path": "status", "op": "==", "value": "ok", "code": "print(1)"},
])
def test_rule_injection_attempts_are_rejected(rule):
    with pytest.raises(ValidationError):
        Comparison.model_validate(rule)


def test_rules_never_eval(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("eval/exec must never run")

    monkeypatch.setattr(builtins, "eval", forbidden)
    monkeypatch.setattr(builtins, "exec", forbidden)
    rules = [Comparison.model_validate({"path": "status", "op": "==", "value": "ok"}),
             Comparison.model_validate({"path": "temp", "op": "<", "value": 80})]
    assert evaluate(DATA, rules) is True
    assert evaluate({"status": "ok", "temp": 90}, rules) is False
    assert evaluate({}, []) is True


# --- child processes ------------------------------------------------------------------------


class FakeProcess:
    def __init__(self, stdout=b"out", code=0, hang=False):
        self.stdout, self.returncode_value, self.hang = stdout, code, hang
        self.returncode = None
        self.killed = False
        self.pid = 4242

    async def communicate(self, data=None):
        if self.hang:
            await asyncio.sleep(10)
        self.returncode = self.returncode_value
        return self.stdout, b""

    def kill(self):
        self.killed = True


class FakeJob:
    def __init__(self):
        self.closed = self.terminated = False

    def close(self):
        self.closed = True

    def terminate(self):
        self.terminated = True


async def test_run_process_uses_minimal_env_and_a_kill_on_close_job(monkeypatch):
    monkeypatch.setenv("JARVIS_HOMELAB_TOKEN", SECRET)
    monkeypatch.setenv("SOME_API_KEY", SECRET)
    seen = {}
    job = FakeJob()

    async def spawn(argv, *, cwd, env, label, **stdio):
        seen.update(argv=argv, env=env, label=label, stdio=stdio)
        return FakeProcess(b"hello", 0), job

    monkeypatch.setattr(process_module.job_object, "spawn", spawn)
    result = await run_process(["PING.EXE", "-n", "1", "nas"], timeout=5, label="A homelab ping")
    assert result == ProcessResult(0, b"hello", b"")
    assert seen["argv"] == ["PING.EXE", "-n", "1", "nas"]
    assert SECRET not in json.dumps(seen["env"])
    assert not any("TOKEN" in name.upper() or "KEY" in name.upper() for name in seen["env"])
    assert job.closed and not job.terminated


async def test_run_process_times_out_and_kills_the_tree(monkeypatch):
    job = FakeJob()
    child = FakeProcess(hang=True)

    async def spawn(argv, *, cwd, env, label, **stdio):
        return child, job

    monkeypatch.setattr(process_module.job_object, "spawn", spawn)
    with pytest.raises(AdapterError) as caught:
        await run_process(["ssh.exe", "nas", "uptime"], timeout=0.01)
    assert caught.value.code == "timeout"
    assert job.terminated and job.closed and child.killed


def test_programs_prefer_the_windows_copies():
    environ = {"SystemRoot": r"C:\Windows"}
    exists = {r"C:\Windows\System32\OpenSSH\ssh.exe", r"C:\Windows\System32\PING.EXE"}.__contains__
    assert program("ssh", environ=environ, exists=exists) == r"C:\Windows\System32\OpenSSH\ssh.exe"
    assert program("ping", environ=environ, exists=exists) == r"C:\Windows\System32\PING.EXE"
    assert program("ssh-keyscan", environ=environ, exists=exists,
                   which=lambda name: "/usr/bin/" + name) == "/usr/bin/ssh-keyscan"
    with pytest.raises(AdapterError):
        program("ssh", environ=environ, exists=lambda path: False, which=lambda name: None)


# --- ping and tcp ---------------------------------------------------------------------------


def test_parse_ping():
    assert parse_ping(0, PING_UP) == (True, 3.0)
    assert parse_ping(0, b"Reply from ::1: time<1ms\r\n") == (True, 1.0)
    assert parse_ping(0, b"Antwort von 10.0.0.2: Bytes=32 Zeit=12ms TTL=128\r\n") == (True, 12.0)
    assert parse_ping(0, PING_UNREACHABLE) == (False, None)
    assert parse_ping(1, b"Request timed out.\r\n") == (False, None)


async def test_ping_adapter(tmp_path):
    runner = Runner({"PING.EXE": ProcessResult(0, PING_UP, b"")})
    ping = adapter(host(options={"timeout_ms": 800, "warn_ms": 2}), context(tmp_path, runner))
    [entity] = await ping.probe()
    assert runner.calls == [["PING.EXE", "-n", "1", "-w", "800", "192.168.1.5"]]
    assert (entity.id, entity.kind, entity.state, entity.metrics) == (
        "nas", "host", "warn", {"latency_ms": 3.0})
    runner.responses["PING.EXE"] = ProcessResult(1, b"Request timed out.", b"")
    [entity] = await ping.probe()
    assert entity.state == "down"


async def test_tcp_adapter(tmp_path):
    attempts = []

    async def connect(address, port, timeout):
        attempts.append((address, port, timeout))
        if port != 22:
            raise ConnectionRefusedError

    tcp = adapter(host(adapter="tcp", options={"ports": [22, 8006], "labels": {"8006": "Proxmox"},
                                               "timeout_s": 1.5}),
                  context(tmp_path, connect=connect))
    ssh_port, proxmox = await tcp.probe()
    assert attempts == [("192.168.1.5", 22, 1.5), ("192.168.1.5", 8006, 1.5)]
    assert (ssh_port.id, ssh_port.name, ssh_port.state) == ("nas:port:22", "Port 22", "ok")
    assert (proxmox.name, proxmox.state, proxmox.kind) == ("Proxmox", "down", "service")
    with pytest.raises(ValidationError):
        HostConfig.model_validate(host(adapter="tcp", options={"ports": [22, 22]}))
    with pytest.raises(ValidationError):
        HostConfig.model_validate(host(adapter="tcp", options={"ports": [22],
                                                               "labels": {"80": "web"}}))


# --- http_json ------------------------------------------------------------------------------


HTTP_HOST = host(adapter="http_json", address="https://pve.local:8006", secret="pve_token",
                 options={"path": "/api2/json/status", "auth_prefix": "PVEAPIToken=",
                          "fields": {"temp_c": "data.temp", "state": "data.status"},
                          "ok_when": [{"path": "data.status", "op": "==", "value": "running"}]})


async def test_http_json_maps_fields_and_rules_with_the_secret_header(tmp_path):
    seen = []
    transport = json_transport({"data": {"status": "running", "temp": 55}}, seen=seen)
    http = adapter(HTTP_HOST, context(tmp_path, transport=transport,
                                      secrets={"pve_token": SECRET}))
    [entity] = await http.probe()
    assert (entity.id, entity.state, entity.metrics) == (
        "nas:service", "ok", {"temp_c": 55.0, "state": "running"})
    request = seen[0]
    assert str(request.url) == "https://pve.local:8006/api2/json/status"
    assert request.headers["Authorization"] == f"PVEAPIToken={SECRET}"
    assert SECRET not in str(request.url)

    http.context.transport = json_transport({"data": {"status": "stopped"}})
    [entity] = await http.probe()
    assert entity.state == "down" and entity.detail == "A health rule didn't hold."


@pytest.mark.parametrize("transport,secrets,state", [
    (json_transport({}, status=401), {"pve_token": SECRET}, "unknown"),
    (json_transport({}, status=503), {"pve_token": SECRET}, "down"),
    (json_transport(b"<html>", status=200), {"pve_token": SECRET}, "warn"),
    (json_transport({}), {}, "unknown"),  # the secret isn't saved yet
])
async def test_http_json_failures(tmp_path, transport, secrets, state):
    http = adapter(HTTP_HOST, context(tmp_path, transport=transport, secrets=secrets))
    [entity] = await http.probe()
    assert entity.state == state


async def test_http_json_each_item_is_an_entity(tmp_path):
    payload = {"data": [
        {"id": "qemu/100", "name": "plex-vm", "status": "running", "cpu": 0.1, "type": "qemu"},
        {"id": "qemu/101", "name": "nextcloud", "status": "stopped", "type": "qemu"},
        {"id": "qemu/101", "name": "dup", "status": "running"},
        {"name": "no id"},
    ]}
    http = adapter(host(adapter="http_json", address="https://pve.local:8006", options={
        "each": "data", "id_field": "id", "name_field": "name", "kind": "vm",
        "fields": {"cpu": "cpu"},
        "ok_when": [{"path": "status", "op": "==", "value": "running"}]}),
        context(tmp_path, transport=json_transport(payload)))
    plex, cloud = await http.probe()
    assert (plex.id, plex.name, plex.kind, plex.state, plex.metrics) == (
        "nas:vm:qemu/100", "plex-vm", "vm", "ok", {"cpu": 0.1})
    assert (cloud.name, cloud.state) == ("nextcloud", "down")


async def test_http_named_action_sends_the_fixed_request(tmp_path):
    seen = []
    config = {**HTTP_HOST, "named_actions": [{"name": "restart plex", "request": {
        "method": "POST", "path": "/api2/json/nodes/pve/qemu/100/status/reboot"}}]}
    http = adapter(config, context(tmp_path, transport=json_transport({}, seen=seen),
                                   secrets={"pve_token": SECRET}))
    assert await http.act("restart plex", {}) == {"done": True, "status": 200}
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/api2/json/nodes/pve/qemu/100/status/reboot"
    with pytest.raises(AdapterError):
        await http.act("rm -rf /", {})


# --- prometheus -----------------------------------------------------------------------------


def test_parse_exposition():
    samples = parse_exposition(METRICS_TEXT)
    names = [(name, labels.get("monitor_name")) for name, labels, _ in samples]
    assert ("monitor_status", "Plex") in names
    assert ("monitor_status", 'Nextcloud "cloud"') in names
    temp = next(value for name, _labels, value in samples if name == "node_hwmon_temp_celsius")
    assert temp == 91.5
    assert ("process_open_fds", {}, 12.0) in samples
    assert not any(name == "broken" for name, _l, _v in samples)


def test_parse_query():
    samples = parse_query(QUERY_JSON)
    assert samples == [("up", {"job": "node", "instance": "nas:9100"}, 1.0),
                       ("up", {"job": "pihole", "instance": "pi:9617"}, 0.0)]
    assert parse_query({"status": "success", "data": {"resultType": "scalar",
                                                      "result": [1, "2.5"]}}) == [("", {}, 2.5)]
    with pytest.raises(AdapterError):
        parse_query({"status": "error", "error": "bad query"})


async def test_prometheus_exporter_one_entity_per_label(tmp_path):
    kuma = adapter(host(adapter="prometheus", address="http://192.168.1.9:3001", options={
        "each_label": "monitor_name", "series": [
            {"metric": "monitor_status", "as_metric": "up", "down_below": 1},
            {"metric": "monitor_response_time", "as_metric": "ms", "warn_above": 30}]}),
        context(tmp_path, transport=json_transport(METRICS_TEXT)))
    plex, cloud = await kuma.probe()
    assert (plex.id, plex.name, plex.state, plex.metrics) == (
        "nas:service:Plex", "Plex", "warn", {"up": 1.0, "ms": 35.0})
    assert (cloud.name, cloud.state) == ('Nextcloud "cloud"', "down")


async def test_prometheus_single_entity_thresholds_and_failures(tmp_path):
    node = adapter(host(adapter="prometheus", address="http://192.168.1.5:9100", options={
        "series": [{"metric": "node_hwmon_temp_celsius", "labels": {"chip": "cpu"},
                    "as_metric": "temp_c"},
                   {"metric": "node_filesystem_avail_bytes", "as_metric": "avail"}]}),
        context(tmp_path, transport=json_transport(METRICS_TEXT)))
    [entity] = await node.probe()
    # NaN is dropped; the temperature alone decides (no thresholds: ok).
    assert (entity.id, entity.state, entity.metrics) == ("nas:prom", "ok", {"temp_c": 91.5})
    node.context.transport = json_transport("", status=500)
    [entity] = await node.probe()
    assert entity.state == "down"


async def test_prometheus_query_mode(tmp_path):
    seen = []
    server = adapter(host(adapter="prometheus", address="http://192.168.1.2:9090", options={
        "mode": "query", "query": 'up{job=~"node|pihole"}', "each_label": "job",
        "series": [{"metric": "up", "as_metric": "up", "down_below": 1}]}),
        context(tmp_path, transport=json_transport(QUERY_JSON, seen=seen)))
    node, pihole = await server.probe()
    assert seen[0].url.path == "/api/v1/query"
    assert seen[0].url.params["query"] == 'up{job=~"node|pihole"}'
    assert (node.name, node.state, pihole.name, pihole.state) == ("node", "ok", "pihole", "down")
    with pytest.raises(ValidationError):
        HostConfig.model_validate(host(adapter="prometheus", address="http://192.168.1.2:9090",
                                       options={"mode": "query",
                                                "series": [{"as_metric": "up"}]}))


# --- ssh ------------------------------------------------------------------------------------


def ssh_host(tmp_path, **options):
    return host(adapter="ssh", options={
        "user": "jarvis", "key_path": key_file(tmp_path),
        "presets": ["uptime", "df", "free", "systemctl", "docker", "sensors"],
        "units": ["nginx.service", "backup.timer"], "temp_max_c": 80, **options},
        named_actions=[{"name": "restart plex", "command": "docker restart plex"}])


@pytest.mark.parametrize("options", [
    {"presets": ["rm -rf /"]},
    {"presets": ["uptime; reboot"]},
    {"units": ["nginx; rm -rf /"]},
    {"units": ["-H evil"]},
    {"units": ["$(reboot)"]},
    {"user": "root; reboot"},
    {"key_path": "id_ed25519"},
    {"command": "cat /etc/shadow"},
])
def test_ssh_options_take_presets_only(tmp_path, options):
    with pytest.raises(ValidationError):
        SshOptions.model_validate({"user": "jarvis", "key_path": "C:/keys/id", **options})


def test_remote_command_is_built_from_presets_only():
    command = remote_command(["uptime", "systemctl", "docker"], ["nginx.service"])
    assert command == (
        "export LC_ALL=C; echo @@jarvis:uptime; uptime 2>/dev/null; "
        "echo @@jarvis:systemctl; systemctl is-active nginx.service 2>/dev/null; "
        "echo @@jarvis:docker; docker ps -a --format '{{json .}}' 2>/dev/null")
    with pytest.raises(AdapterError):
        remote_command(["reboot"], [])
    with pytest.raises(AdapterError):
        remote_command(["systemctl"], ["x; reboot"])
    assert set(PRESETS) == {"uptime", "df", "free", "systemctl", "docker", "sensors"}


async def test_ssh_refuses_an_untrusted_host_without_connecting(tmp_path):
    runner = Runner()
    ssh = adapter(ssh_host(tmp_path), context(tmp_path, runner))
    [entity] = await ssh.probe()
    assert entity.state == "unknown" and "Not trusted yet" in entity.detail
    assert runner.calls == []


async def test_ssh_probe_runs_presets_with_strict_options(tmp_path):
    trust(tmp_path)
    runner = Runner({"ssh.exe": ProcessResult(0, SSH_OUTPUT, b"")})
    ssh = adapter(ssh_host(tmp_path), context(tmp_path, runner))
    entities = {entity.id: entity for entity in await ssh.probe()}
    [argv] = runner.calls
    assert argv[0] == "ssh.exe" and argv[1:4] == ["-F", "none", "-T"]
    pairs = [argv[index + 1] for index, item in enumerate(argv) if item == "-o"]
    assert "BatchMode=yes" in pairs and "StrictHostKeyChecking=yes" in pairs
    assert "IdentitiesOnly=yes" in pairs and "PasswordAuthentication=no" in pairs
    known = (tmp_path / "known_hosts").as_posix()
    assert f'UserKnownHostsFile="{known}"' in pairs
    assert argv[argv.index("-i") + 1] == key_file(tmp_path)
    assert argv[argv.index("-l") + 1] == "jarvis" and argv[argv.index("-p") + 1] == "22"
    assert argv[-2] == "192.168.1.5"
    assert argv[-1] == remote_command(
        ["uptime", "df", "free", "systemctl", "docker", "sensors"],
        ["nginx.service", "backup.timer"])

    machine = entities["nas"]
    assert machine.state == "ok"
    assert machine.metrics["load1"] == 0.1 and machine.metrics["uptime_days"] == 3.0
    assert machine.metrics["mem_used_pct"] == round((7820 - 5400) / 7820 * 100, 1)
    assert machine.metrics["temp_c"] == 86.0
    assert entities["nas:disk:/"].state == "warn"
    assert entities["nas:disk:/"].metrics["disk_used_pct"] == 92.0
    assert entities["nas:disk:/mnt/data"].state == "ok"
    assert "nas:disk:/run" not in entities
    assert entities["nas:unit:nginx.service"].state == "ok"
    assert entities["nas:unit:backup.timer"].state == "down"
    assert entities["nas:container:plex"].state == "ok"
    assert entities["nas:container:sonarr"].state == "down"


@pytest.mark.parametrize("stderr,state", [
    (b"jarvis@192.168.1.5: Permission denied (publickey).", "unknown"),
    (b"Host key verification failed.", "unknown"),
    (b"ssh: connect to host 192.168.1.5 port 22: Connection timed out", "down"),
])
async def test_ssh_connection_failures(tmp_path, stderr, state):
    trust(tmp_path)
    runner = Runner({"ssh.exe": ProcessResult(255, b"", stderr)})
    [entity] = await adapter(ssh_host(tmp_path), context(tmp_path, runner)).probe()
    assert entity.state == state
    assert stderr.decode() not in entity.detail


async def test_ssh_actions_run_only_the_owners_named_command(tmp_path):
    trust(tmp_path)
    runner = Runner({"ssh.exe": ProcessResult(0, b"plex\n", b"")})
    ssh = adapter(ssh_host(tmp_path), context(tmp_path, runner))
    assert await ssh.act("restart plex", {}) == {"done": True, "exit_code": 0}
    assert runner.calls[-1][-1] == "docker restart plex"
    for free_text in ("docker restart plex; rm -rf /", "reboot", "uptime"):
        with pytest.raises(AdapterError):
            await ssh.act(free_text, {})
    assert len(runner.calls) == 1


def test_keyscan_parsing_and_fingerprints():
    output = (f"# 192.168.1.5:22 SSH-2.0-OpenSSH_9.6\n"
              f"192.168.1.5 ssh-ed25519 {ED25519}\n"
              f"192.168.1.5 ecdsa-sha2-nistp256 {ECDSA}\n"
              f"10.0.0.9 ssh-ed25519 {ED25519}\n"
              f"192.168.1.5 ssh-dss AAAA\n"
              f"192.168.1.5 ssh-ed25519 not-base64!\n").encode()
    keys = parse_keyscan(output, "192.168.1.5")
    assert [key.key_type for key in keys] == ["ssh-ed25519", "ecdsa-sha2-nistp256"]
    digest = hashlib.sha256(base64.b64decode(ED25519)).digest()
    assert keys[0].fingerprint == "SHA256:" + base64.b64encode(digest).decode().rstrip("=")
    assert fingerprint(base64.b64decode(ED25519)) == keys[0].fingerprint
    assert parse_keyscan(output.replace(b"192.168.1.5 ", b"[192.168.1.5]:2222 "),
                         "[192.168.1.5]:2222")


# --- wol ------------------------------------------------------------------------------------


def test_magic_packet_bytes():
    packet = magic_packet("AA-BB-CC-DD-EE-01")
    assert len(packet) == 102
    assert packet[:6] == b"\xff" * 6
    assert packet[6:] == bytes.fromhex("aabbccddee01") * 16
    assert magic_packet("aabbccddee01") == packet
    for bad in ("ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00", "aa:bb:cc", "aa:bb-cc:dd:ee:ff"):
        with pytest.raises(ValueError):
            magic_packet(bad)
    with pytest.raises(ValidationError):
        HostConfig.model_validate(host(adapter="wol", options={"mac": "aa:bb:cc:dd:ee:01",
                                                               "broadcast": "8.8.8.8"}))


async def test_wake_sends_one_broadcast(tmp_path):
    sent = []
    app = make_app([host(adapter="wol", options={"mac": "aa:bb:cc:dd:ee:01",
                                                 "broadcast": "192.168.1.255"}),
                    host(id="pc", options={"wake_mac": "aa:bb:cc:dd:ee:02"})])
    registry = registry_for(app, tmp_path, udp=lambda packet, address: sent.append((packet,
                                                                                     address)))
    assert await registry.wake("nas") == {"sent": True}
    assert await registry.wake("pc") == {"sent": True}
    assert sent == [(magic_packet("aa:bb:cc:dd:ee:01"), ("192.168.1.255", 9)),
                    (magic_packet("aa:bb:cc:dd:ee:02"), ("255.255.255.255", 9))]


# --- the registry ---------------------------------------------------------------------------


def toggling_ping(state):
    def respond(_argv):
        return ProcessResult(0, PING_UP, b"") if state["up"] else ProcessResult(1, b"", b"")

    return respond


async def test_registry_polls_on_interval_and_pauses_in_gaming_mode(tmp_path):
    runner = Runner({"PING.EXE": ProcessResult(0, PING_UP, b"")})
    app = make_app([host(interval_s=60), host(id="pi", name="Pi", address="192.168.1.6",
                                              interval_s=15)])
    registry = registry_for(app, tmp_path, runner)
    assert len(await run_tick(registry)) == 2
    assert len(await run_tick(registry)) == 0  # not due yet
    registry.monotonic.value += 16
    assert [task.get_name() for task in await run_tick(registry)] == ["homelab-pi"]
    app.resources.state = "gaming"
    registry.monotonic.value += 100
    assert await registry.tick() == []
    app.resources.state = "chat"
    assert len(await run_tick(registry)) == 2
    assert registry.entities["nas"][0].state == "ok" and registry.checked_at["pi"]


async def test_registry_first_probe_is_jittered(tmp_path):
    app = make_app([host(interval_s=600)])
    registry = registry_for(app, tmp_path, Runner({"PING.EXE": ProcessResult(0, PING_UP, b"")}))
    registry.rand = lambda: 0.5
    assert await registry.tick() == []
    assert registry.due["nas"] == 1000.0 + 15.0  # half of the 30 s cap
    registry.monotonic.value += 15
    assert len(await run_tick(registry)) == 1


async def test_registry_limits_concurrent_probes(tmp_path):
    gate, active, peak = asyncio.Event(), [0], [0]

    async def slow(argv, *, timeout, label, stdin=None):
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        await gate.wait()
        active[0] -= 1
        return ProcessResult(0, PING_UP, b"")

    hosts = [host(id=f"h{index}", address=f"192.168.1.{index + 10}") for index in range(7)]
    registry = registry_for(make_app(hosts), tmp_path, slow)
    tasks = await registry.tick()
    for _ in range(5):
        await asyncio.sleep(0)
    assert peak[0] == 4
    gate.set()
    await asyncio.gather(*tasks)
    assert len(registry.entities) == 7 and peak[0] == 4


async def test_host_down_signals_once_then_clears_on_recovery(tmp_path):
    state = {"up": False}
    app = make_app([host()])
    registry = registry_for(app, tmp_path, Runner({"PING.EXE": toggling_ping(state)}))
    await registry.probe_now("nas")
    assert app.signals.pending() == []  # one failed ping is not enough
    await registry.probe_now("nas")
    [alert] = app.signals.pending()
    assert (alert.kind, alert.source, alert.urgency, alert.title) == (
        "homelab.alert", "homelab", 2, "NAS is down")
    assert dict(alert.data) == {"host": "nas", "entity": "nas", "condition": "host_down"}
    await registry.probe_now("nas")
    assert len(app.signals.pending()) == 1  # deduped while it lasts
    state["up"] = True
    await registry.probe_now("nas")
    assert app.signals.pending() == [] and registry.active == {}
    state["up"] = False
    await registry.probe_now("nas")
    await registry.probe_now("nas")
    [again] = app.signals.pending()
    assert again.dedupe_key != alert.dedupe_key


async def test_unknown_changes_nothing_and_removed_hosts_clear(tmp_path):
    state = {"up": False}
    app = make_app([host()])
    registry = registry_for(app, tmp_path, Runner({"PING.EXE": toggling_ping(state)}))
    await registry.probe_now("nas")
    await registry.probe_now("nas")
    assert len(app.signals.pending()) == 1

    async def broken(argv, *, timeout, label, stdin=None):
        raise AdapterError("program_missing", "ping isn't installed on this PC.")

    registry.context.run = broken
    [entity] = await registry.probe_now("nas")
    assert entity.state == "unknown" and len(app.signals.pending()) == 1
    app.settings["homelab"]["hosts"] = []
    assert registry.hosts() == {}
    assert app.signals.pending() == [] and registry.active == {} and registry.entities == {}
    with pytest.raises(ServiceError):
        await registry.probe_now("nas")


async def test_ssh_disk_temperature_and_service_signals(tmp_path):
    trust(tmp_path)
    app = make_app([ssh_host(tmp_path)])
    registry = registry_for(app, tmp_path, Runner({"ssh.exe": ProcessResult(0, SSH_OUTPUT, b"")}))
    await registry.probe_now("nas")
    first = {(item.data["entity"], item.data["condition"]): item for item in app.signals.pending()}
    assert set(first) == {("nas:disk:/", "disk_full"), ("nas", "hot")}
    assert first[("nas:disk:/", "disk_full")].title == "/ on NAS is 92% full"
    assert first[("nas", "hot")].title == "NAS is running hot (86 °C)"
    await registry.probe_now("nas")  # services need two probes in a row
    second = {(item.data["entity"], item.data["condition"]): item.urgency
              for item in app.signals.pending()}
    assert second == {("nas:disk:/", "disk_full"): 1, ("nas", "hot"): 1,
                      ("nas:unit:backup.timer", "service_down"): 1,
                      ("nas:container:sonarr", "service_down"): 1}


async def test_ups_on_battery_and_backup_failed_from_mapped_fields(tmp_path):
    payload = {"ups": {"status": "OB DISCHRG", "charge": 87}, "backup": {"last_ok": 0}}
    app = make_app([host(adapter="http_json", address="http://192.168.1.7:8080", options={
        "kind": "ups", "fields": {"ups_status": "ups.status", "battery_pct": "ups.charge",
                                  "backup_ok": "backup.last_ok"}})])
    registry = registry_for(app, tmp_path, transport=json_transport(payload))
    await registry.probe_now("nas")
    alerts = {item.data["condition"]: item.urgency for item in app.signals.pending()}
    assert alerts == {"on_battery": 2, "backup_failed": 1}


def test_condition_rules():
    from services.homelab.base import Entity

    config = HostConfig.model_validate(host(options={"temp_max_c": 70}))
    assert conditions(Entity("x", "nas", "host", "x", "down"), config) == {"host_down"}
    assert conditions(Entity("x", "nas", "backup", "x", "down"), config) == {"backup_failed"}
    assert conditions(Entity("x", "nas", "disk", "x", "ok", {"disk_used_pct": 90}), config) == set()
    assert conditions(Entity("x", "nas", "host", "x", "ok", {"temp_c": 71}), config) == {"hot"}
    assert conditions(Entity("x", "nas", "ups", "x", "ok", {"ups_on_battery": True}),
                      config) == {"on_battery"}
    assert conditions(Entity("x", "nas", "ups", "x", "ok", {"ups_status": "OL"}), config) == set()
    assert set(CONDITIONS) == {"host_down", "service_down", "disk_full", "hot", "backup_failed",
                               "on_battery"}


async def test_secrets_never_reach_argv_or_logs(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)

    def explode(request):
        raise httpx.ConnectError(f"boom {SECRET} https://pve.local:8006", request=request)

    trust(tmp_path)
    runner = Runner({"ssh.exe": ProcessResult(0, SSH_OUTPUT, SECRET.encode()),
                     "PING.EXE": ProcessResult(0, PING_UP, b"")})
    app = make_app([HTTP_HOST, {**ssh_host(tmp_path), "id": "box"}, host(id="pi")],
                   secrets={"pve_token": SECRET})
    registry = registry_for(app, tmp_path, runner, transport=httpx.MockTransport(explode))
    await run_tick(registry)
    assert runner.calls and all(SECRET not in " ".join(argv) for argv in runner.calls)
    text = caplog.text + json.dumps(registry.status_for_owner())
    assert SECRET not in text
    assert "pve.local" not in caplog.text and "SSH-2.0" not in caplog.text
    assert "load average" not in caplog.text


# --- brain tools ----------------------------------------------------------------------------


def tool_setup(tmp_path, hosts, runner=None, permissions=None, transport=None, udp=None,
               secrets=None):
    app = make_app(hosts, secrets)
    registry = registry_for(app, tmp_path, runner, transport=transport, udp=udp)
    stored = {"homelab_trust_host": False, **(permissions or {})}
    dispatcher = ToolDispatcher(lambda: stored, timeout=5)
    register_homelab_tools(dispatcher, registry)
    cards = []

    def approver(answer=True):
        async def approve(payload):
            cards.append(payload)
            dispatcher.resolve("owner", payload["id"], answer)

        return approve

    return app, registry, dispatcher, cards, approver


async def test_status_never_asks_and_is_untrusted(tmp_path):
    _app, registry, dispatcher, _cards, _approver = tool_setup(
        tmp_path, [host()], Runner({"PING.EXE": ProcessResult(0, PING_UP, b"")}),
        {"homelab_status": False})
    await registry.probe_now("nas")
    result = await dispatcher.dispatch("owner", "homelab_status", {}, {})
    [item] = result["hosts"]
    assert (item["id"], item["state"], item["entities"][0]["metrics"]) == (
        "nas", "ok", {"latency_ms": 3.0})
    assert dispatcher.tools["homelab_status"].untrusted_output is True
    with pytest.raises(ServiceError):
        await dispatcher.dispatch("owner", "homelab_status", {"scope": "nowhere"}, {})
    with pytest.raises(ValidationError):
        await dispatcher.dispatch("owner", "homelab_status", {"scope": "a; b"}, {})


async def test_action_always_asks_and_shows_the_exact_command(tmp_path):
    trust(tmp_path)
    runner = Runner({"ssh.exe": ProcessResult(0, b"", b"")})
    _app, _registry, dispatcher, cards, approver = tool_setup(
        tmp_path, [ssh_host(tmp_path)], runner, {"homelab_action": False})
    spec = dispatcher.tools["homelab_action"]
    assert spec.always_ask is True and spec.outward is True
    with pytest.raises(ServiceError) as caught:
        await dispatcher.dispatch("owner", "homelab_action",
                                  {"host": "nas", "action": "restart plex"}, {})
    assert caught.value.code == "approval_required"
    result = await dispatcher.dispatch("owner", "homelab_action",
                                       {"host": "nas", "action": "restart plex"}, {},
                                       approver(True))
    assert result["done"] is True
    assert cards[0]["args"]["exact"] == "On jarvis@192.168.1.5: docker restart plex"
    assert runner.calls[-1][-1] == "docker restart plex"
    with pytest.raises(ServiceError):
        await dispatcher.dispatch("owner", "homelab_action",
                                  {"host": "nas", "action": "restart plex"}, {}, approver(False))
    assert len(runner.calls) == 1
    # Unknown actions are refused before any card; free text can't even be named.
    with pytest.raises(ServiceError):
        await dispatcher.dispatch("owner", "homelab_action", {"host": "nas", "action": "reboot"},
                                  {}, approver(True))
    with pytest.raises(ValidationError):
        await dispatcher.dispatch("owner", "homelab_action",
                                  {"host": "nas", "action": "rm -rf /; reboot"}, {}, approver())
    with pytest.raises(ValidationError):
        await dispatcher.dispatch("owner", "homelab_action",
                                  {"host": "nas", "action": "restart plex",
                                   "command": "reboot"}, {}, approver())
    assert len(cards) == 2 and len(runner.calls) == 1


async def test_http_action_card_shows_the_request(tmp_path):
    config = {**HTTP_HOST, "named_actions": [{"name": "reboot vm", "request": {
        "method": "POST", "path": "/api2/json/nodes/pve/qemu/100/status/reboot"}}]}
    _app, _registry, dispatcher, cards, approver = tool_setup(
        tmp_path, [config], transport=json_transport({}), secrets={"pve_token": SECRET})
    await dispatcher.dispatch("owner", "homelab_action", {"host": "nas", "action": "reboot vm"},
                              {}, approver(True))
    assert cards[0]["args"]["exact"] == (
        "POST https://pve.local:8006/api2/json/nodes/pve/qemu/100/status/reboot")


async def test_wake_always_asks(tmp_path):
    sent = []
    _app, _registry, dispatcher, cards, approver = tool_setup(
        tmp_path, [host(options={"wake_mac": "aa:bb:cc:dd:ee:01"}), host(id="pi")],
        udp=lambda packet, address: sent.append(address))
    spec = dispatcher.tools["homelab_wake"]
    assert spec.always_ask is True and spec.outward is True
    assert await dispatcher.dispatch("owner", "homelab_wake", {"host": "nas"}, {},
                                     approver(True)) == {"sent": True}
    assert "aa:bb:cc:dd:ee:01" in cards[0]["args"]["exact"] and sent == [("255.255.255.255", 9)]
    with pytest.raises(ServiceError) as caught:
        await dispatcher.dispatch("owner", "homelab_wake", {"host": "pi"}, {}, approver(True))
    assert caught.value.code == "homelab_no_wake" and len(cards) == 1


async def test_trust_host_shows_fingerprints_and_writes_known_hosts_on_approval(tmp_path):
    output = f"192.168.1.5 ssh-ed25519 {ED25519}\n".encode()
    runner = Runner({"ssh-keyscan.exe": ProcessResult(0, output, b"")})
    _app, registry, dispatcher, cards, approver = tool_setup(tmp_path, [ssh_host(tmp_path)],
                                                             runner)
    expected = parse_keyscan(output, "192.168.1.5")[0].fingerprint
    with pytest.raises(ServiceError):
        await dispatcher.dispatch("owner", "homelab_trust_host", {"host": "nas"}, {},
                                  approver(False))
    assert not (tmp_path / "known_hosts").exists()
    assert runner.calls[0] == ["ssh-keyscan.exe", "-T", "5", "-p", "22", "-t",
                               "ed25519,ecdsa,rsa", "192.168.1.5"]
    card = cards[0]
    assert card["tool"] == "homelab_trust_host_confirm"
    assert card["args"]["exact"] == [f"ssh-ed25519 {expected}"]
    result = await dispatcher.dispatch("owner", "homelab_trust_host", {"host": "nas"}, {},
                                       approver(True))
    assert result == {"trusted": True, "keys": 1}
    assert (tmp_path / "known_hosts").read_text() == f"192.168.1.5 ssh-ed25519 {ED25519}\n"
    assert registry.trusted("nas")
    again = await dispatcher.dispatch("owner", "homelab_trust_host", {"host": "nas"}, {},
                                      approver(True))
    assert again["trusted"] is True and len(cards) == 2


async def test_trust_confirm_cannot_be_called_directly(tmp_path):
    _app, _registry, dispatcher, cards, approver = tool_setup(tmp_path, [ssh_host(tmp_path)])
    spec = dispatcher.tools["homelab_trust_host_confirm"]
    assert spec.model_visible is False and spec.always_ask is True
    assert "homelab_trust_host_confirm" not in [item["name"] for item in dispatcher.schemas()]
    with pytest.raises(ServiceError) as caught:
        await dispatcher.dispatch("owner", "homelab_trust_host_confirm",
                                  {"host": "nas", "fingerprints": ["SHA256:" + "A" * 43]}, {},
                                  approver(True))
    assert caught.value.code == "homelab_trust_unavailable" and cards == []
    assert not (tmp_path / "known_hosts").exists()


async def test_trust_is_only_for_ssh_systems(tmp_path):
    _app, _registry, dispatcher, _cards, approver = tool_setup(tmp_path, [host()])
    with pytest.raises(ServiceError) as caught:
        await dispatcher.dispatch("owner", "homelab_trust_host", {"host": "nas"}, {}, approver())
    assert caught.value.code == "homelab_not_ssh"


async def test_physical_security_tools_are_the_registered_asking_tools(tmp_path):
    _app, _registry, dispatcher, _cards, _approver = tool_setup(tmp_path, [host()])
    assert PHYSICAL_SECURITY_TOOLS <= set(dispatcher.tools)
    assert "homelab_status" not in PHYSICAL_SECURITY_TOOLS
    for name in ("homelab_action", "homelab_wake", "homelab_trust_host_confirm"):
        assert dispatcher.tools[name].always_ask is True


async def test_denied_tools_stay_off(tmp_path):
    _app, _registry, dispatcher, cards, approver = tool_setup(
        tmp_path, [ssh_host(tmp_path)], permissions={"homelab_action": "deny",
                                                     "homelab_trust_host": "deny"})
    for name, args in (("homelab_action", {"host": "nas", "action": "restart plex"}),
                       ("homelab_trust_host", {"host": "nas"})):
        with pytest.raises(ServiceError) as caught:
            await dispatcher.dispatch("owner", name, args, {}, approver(True))
        assert caught.value.code == "permission_denied"
    assert cards == []


# --- owner-only routes ----------------------------------------------------------------------


def owner_app(application_factory):
    app = application_factory()
    app.sessions.local_owner = "owner"
    app.sessions.principals.update({"client": "owner", "second": "other", "tray": "owner"})
    app.sessions.roles.update({"client": "renderer", "second": "renderer", "tray": "resident"})
    return app


async def test_routes_are_owner_only(application_factory):
    app = owner_app(application_factory)
    handlers = app.sio.handlers["/"]
    payloads = {"homelab_status": {}, "homelab_hosts_get": {},
                "homelab_hosts_save": {"hosts": []}, "homelab_probe_now": {"host": "nas"}}
    for name, payload in payloads.items():
        assert (await handlers[name]("second", payload))["code"] == "permission_denied"
        assert (await handlers[name]("tray", payload))["code"] == "authentication_required"
    app.settings["face_auth_enabled"] = True
    assert (await handlers["homelab_status"]("client", {}))["code"] == "authentication_required"


async def test_routes_save_validate_and_probe(application_factory, tmp_path):
    app = owner_app(application_factory)
    handlers = app.sio.handlers["/"]
    assert await handlers["homelab_status"]("client", {}) == {"ok": True, "hosts": [],
                                                             "paused": False}
    saved = await handlers["homelab_hosts_save"]("client", {"hosts": [host()]})
    assert saved["ok"] is True and saved["hosts"][0]["id"] == "nas"
    assert app.settings["homelab"]["hosts"][0]["address"] == "192.168.1.5"
    got = await handlers["homelab_hosts_get"]("client", None)
    assert got["hosts"] == saved["hosts"]

    bad = await handlers["homelab_hosts_save"]("client", {"hosts": [host(
        adapter="http_json", address="https://admin:hunter2@nas.example")]})
    assert bad["code"] == "invalid_arguments" and "hunter2" not in bad["message"]
    assert app.settings["homelab"]["hosts"][0]["adapter"] == "ping"  # unchanged
    for payload in ({"hosts": [host(), host()]}, {"hosts": "x"}, {"hosts": [], "x": 1}):
        assert (await handlers["homelab_hosts_save"]("client", payload))["code"] == \
            "invalid_arguments"

    app.homelab.context.run = Runner({"PING.EXE": ProcessResult(0, PING_UP, b"")})
    app.homelab.context.programs = dict(PROGRAMS)
    probed = await handlers["homelab_probe_now"]("client", {"host": "nas"})
    assert probed["ok"] is True and probed["entities"][0]["state"] == "ok"
    missing = await handlers["homelab_probe_now"]("client", {"host": "nowhere"})
    assert missing["code"] == "homelab_unknown_host"
    assert (await handlers["homelab_probe_now"]("client", {"host": "A B"}))["code"] == \
        "invalid_arguments"
    status = await handlers["homelab_status"]("client", {})
    assert status["hosts"][0]["state"] == "ok" and status["hosts"][0]["entities"]

    cleared = await handlers["homelab_hosts_save"]("client", {"hosts": []})
    assert cleared["hosts"] == [] and app.homelab.entities == {}


def test_routes_and_tools_are_in_the_route_policy_matrix():
    matrix = json.loads((Path(__file__).resolve().parents[1] / "docs/ROUTE_POLICY_MATRIX.json")
                        .read_text(encoding="utf-8"))
    for name in ("homelab_status", "homelab_hosts_get", "homelab_hosts_save",
                 "homelab_probe_now"):
        assert matrix["socket_routes"][name]["status"] == "implemented"
    for name in ("homelab_status", "homelab_action", "homelab_wake", "homelab_trust_host",
                 "homelab_trust_host_confirm"):
        assert name in matrix["shared_tools"]


def test_server_permission_defaults():
    import server

    defaults = server.DEFAULT_SETTINGS["tool_permissions"]
    assert defaults["homelab_status"] is False and defaults["homelab_action"] is True
    assert defaults["homelab_wake"] is True and defaults["homelab_trust_host"] is False
