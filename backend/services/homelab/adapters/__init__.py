"""The generic homelab adapters, by ``HostConfig.adapter`` name (docs/HOMELAB.md)."""

from services.homelab.adapters.http_json import HttpJsonAdapter
from services.homelab.adapters.prometheus import PrometheusAdapter
from services.homelab.adapters.reach import PingAdapter, TcpAdapter
from services.homelab.adapters.ssh import SshAdapter
from services.homelab.adapters.wol import WolAdapter

ADAPTERS = {
    "ping": PingAdapter,
    "tcp": TcpAdapter,
    "http_json": HttpJsonAdapter,
    "prometheus": PrometheusAdapter,
    "ssh": SshAdapter,
    "wol": WolAdapter,
}
