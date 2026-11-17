"""Remote messaging channels (S8, docs/CHANNELS.md): the contract, the gateway and remote
approvals. Telegram (S8.2) and WhatsApp (S8.3/8.4) plug in as ``Channel`` implementations."""

from services.channels.approvals import ApprovalBridge, physical_security
from services.channels.base import ApprovalAnswer, Channel, InboundMessage, RemoteApproval
from services.channels.gateway import ChannelGateway, split_text

__all__ = [
    "ApprovalAnswer",
    "ApprovalBridge",
    "Channel",
    "ChannelGateway",
    "InboundMessage",
    "RemoteApproval",
    "physical_security",
    "split_text",
]
