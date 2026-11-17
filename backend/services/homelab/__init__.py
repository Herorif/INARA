"""Homelab monitoring and owner-defined actions (S12.3, docs/HOMELAB.md).

``base`` holds the shapes (Entity, the Adapter protocol, HostConfig), ``adapters`` the
generic adapters (ping, tcp, http_json, prometheus, ssh, wol), ``registry`` the poller that
keeps the latest entities and publishes ``homelab.alert`` signals, and ``tools`` the brain
tools. This package import stays light: settings.py imports ``base`` at startup.
"""

# The "physical security" class for remote approvals (S8.1): tools whose approval card must
# not be answered from a remote channel (Telegram, WhatsApp) unless the owner turns that on.
# Each of these acts on real machines (runs an owner-defined command on a server, sends an
# HTTP request that changes something, wakes a machine, or trusts a new SSH host key). The
# names are the dispatcher tool names that carry the approval card: ``homelab_trust_host``
# asks through its internal ``homelab_trust_host_confirm`` step, so both are listed.
PHYSICAL_SECURITY_TOOLS = frozenset({
    "homelab_action",
    "homelab_wake",
    "homelab_trust_host",
    "homelab_trust_host_confirm",
})
