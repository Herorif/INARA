"""An in-memory channel for tests (S8.1): records what the gateway sends and feeds it inbound
messages. Never registered by the application; Telegram (S8.2) and WhatsApp (S8.3/8.4) are
the real channels."""

import datetime as dt

from services.channels.base import ApprovalAnswer, InboundMessage

UTC = dt.timezone.utc


class FakeChannel:
    def __init__(self, name="fake", owner_chat_id="owner-chat", *, typing=True):
        self.name = name
        self.paired_chat = owner_chat_id
        self.current_state = "stopped"
        self.deliver = None
        self.sent = []  # (chat_id, text)
        self.approvals = []  # (chat_id, RemoteApproval)
        self.typed = []  # chat ids, one per typing call
        self.fail_sends = False
        if not typing:
            self.typing = None

    @property
    def owner_chat_id(self):
        return self.paired_chat

    @property
    def state(self):
        return self.current_state

    def bind(self, deliver):
        self.deliver = deliver

    async def start(self):
        self.current_state = "running"

    async def stop(self):
        self.current_state = "stopped"

    async def send_text(self, chat_id, text):
        if self.fail_sends:
            raise ConnectionError("fake send failure")
        self.sent.append((chat_id, text))

    async def send_approval(self, chat_id, approval):
        self.approvals.append((chat_id, approval))

    async def typing(self, chat_id):
        self.typed.append(chat_id)

    async def inbound(self, text="", *, chat_id=None, sender="+60111111111", is_owner=None,
                      answer=None, media=(), sender_name=None, at=None):
        """Deliver one message as the channel would; the owner chat by default."""
        chat_id = self.paired_chat if chat_id is None else chat_id
        message = InboundMessage(
            channel=self.name, chat_id=chat_id, sender=sender, text=text, media=media,
            at=at or dt.datetime.now(UTC),
            is_owner=(chat_id == self.paired_chat) if is_owner is None else is_owner,
            approval_answer=answer, sender_name=sender_name,
        )
        return await self.deliver(message)

    async def answer(self, approval, approved=True, *, signature=None, **options):
        """Press a card's button (or forge one with ``signature``)."""
        if signature is None:
            signature = approval.approve_signature if approved else approval.deny_signature
        return await self.inbound(
            answer=ApprovalAnswer(approval.approval_id, approved, signature), **options
        )
