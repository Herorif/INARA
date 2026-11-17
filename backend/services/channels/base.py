"""The channel contract (S8.1, docs/CHANNELS.md): what a remote messaging channel gives the
gateway and what the gateway gives back.

A channel (Telegram in S8.2, WhatsApp in S8.3/8.4, ``FakeChannel`` in tests) owns its
transport and its pairing. It hands every inbound message to the gateway as an
``InboundMessage`` through the callback ``bind`` gave it, and sends what the gateway asks:
plain text, a typing indicator and approval cards (``RemoteApproval``). The owner's answer to
a card comes back as an ``InboundMessage`` whose ``approval_answer`` is set.

``is_owner`` is the channel's claim that the message came from the paired owner chat; the
gateway accepts it only when ``chat_id`` is also the channel's ``owner_chat_id``.

Message text, sender names and chat ids are private: nothing here logs them.
"""

import datetime as dt
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Protocol, runtime_checkable

UTC = dt.timezone.utc
# Channel names the core knows (the taint labels in services/conversation.py CHANNEL_SOURCES).
CHANNEL_NAME_LIMIT = 32
CARD_TITLE_LIMIT = 160
CARD_SUMMARY_LIMIT = 600


@dataclass(frozen=True)
class ApprovalAnswer:
    """The owner's answer to a remote approval card: the signed id the card carried, the
    decision and that decision's signature (``ApprovalBridge.sign``)."""

    approval_id: str
    approved: bool
    signature: str

    def __post_init__(self):
        if not isinstance(self.approval_id, str) or not isinstance(self.signature, str):
            raise ValueError("An approval answer needs a string id and signature")
        if type(self.approved) is not bool:
            raise ValueError("An approval answer's decision must be a bool")


@dataclass(frozen=True)
class InboundMessage:
    """One message that reached a channel. ``media`` lists attachments as small dicts (at
    least ``kind``: photo, voice, document...); the channel keeps the bytes. ``sender`` is
    the channel's stable sender address (a phone number in E.164 for WhatsApp, a user id for
    Telegram); ``sender_name`` the display name the sender chose (untrusted text)."""

    channel: str
    chat_id: str
    sender: str
    text: str
    media: tuple = ()
    at: dt.datetime = field(default_factory=lambda: dt.datetime.now(UTC))
    is_owner: bool = False
    approval_answer: ApprovalAnswer | None = None
    sender_name: str | None = None

    def __post_init__(self):
        if not isinstance(self.channel, str) or not 0 < len(self.channel) <= CHANNEL_NAME_LIMIT:
            raise ValueError("A message needs its channel's name")
        if not isinstance(self.chat_id, str) or not self.chat_id:
            raise ValueError("A message needs a chat id")
        if not isinstance(self.sender, str):
            raise ValueError("A message sender must be a string")
        if not isinstance(self.text, str):
            raise ValueError("A message text must be a string")
        if not isinstance(self.at, dt.datetime) or self.at.tzinfo is None:
            raise ValueError("A message time must be an aware datetime")
        if type(self.is_owner) is not bool:
            raise ValueError("is_owner must be a bool")
        if self.approval_answer is not None and not isinstance(self.approval_answer, ApprovalAnswer):
            raise ValueError("approval_answer must be an ApprovalAnswer")
        if self.sender_name is not None and not isinstance(self.sender_name, str):
            raise ValueError("sender_name must be a string")
        media = tuple(dict(item) for item in self.media or () if isinstance(item, dict))
        object.__setattr__(self, "media", media)


@dataclass(frozen=True)
class RemoteApproval:
    """An approval card for a remote channel: the same title and summary the desktop card
    shows (``approval_card``), its review facts, the taint line when the turn read untrusted
    content, and the signed answers. ``approve_signature`` is empty when the action may not
    be approved remotely (the physical-security class with
    ``channels.remote_approval_physical`` off): such a card can only be declined there."""

    approval_id: str
    tool: str
    title: str
    summary: str
    facts: tuple = ()  # ((label, value), ...) plain text
    taint_line: str | None = None
    expires_at: dt.datetime | None = None
    approve_signature: str = ""
    deny_signature: str = ""
    physical: bool = False

    @property
    def approvable(self):
        return bool(self.approve_signature)

    def as_text(self):
        """A plain-text rendering for channels without rich cards."""
        lines = [self.title, self.summary]
        lines += [f"{label}: {value}" for label, value in self.facts]
        if self.taint_line:
            lines.append(self.taint_line)
        if not self.approvable:
            lines.append("Approve this one on the PC.")
        return "\n".join(line for line in lines if line)


Deliver = Callable[[InboundMessage], Awaitable[None]]


@runtime_checkable
class Channel(Protocol):
    """A remote messaging channel.

    ``owner_chat_id`` is the paired owner chat (None until paired); ``state`` a short word
    for ``channels_status`` (``stopped``, ``running``, ``error``...). ``bind(deliver)`` is
    called once by ``ChannelGateway.register``: the channel awaits ``deliver(message)`` for
    every inbound message, approval answers included. A channel may also define
    ``async typing(chat_id)``, called every few seconds while a reply is being written."""

    name: str

    @property
    def owner_chat_id(self) -> str | None: ...

    @property
    def state(self) -> str: ...

    def bind(self, deliver: Deliver) -> None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def send_text(self, chat_id: str, text: str) -> None: ...

    async def send_approval(self, chat_id: str, approval: RemoteApproval) -> None: ...
