"""The channel gateway (S8.1, docs/CHANNELS.md): every remote messaging channel enters here.

- **The owner's messages** (the channel's paired owner chat) become a brain turn,
  ``ConversationService.reply``, in one conversation per channel and chat (persisted; a new
  one after a project switch). The answer goes back with ``send_text``, split at sentence
  boundaries into parts of at most ``PART_LIMIT`` characters; the channel's ``typing`` runs
  every ``TYPING_INTERVAL_S`` while the reply is written. Approval cards of that turn go to
  the owner's desktop windows and to the chat the turn came from.
- **Taint decision.** An owner turn from a channel is the owner's turn: it passes
  ``channel="owner"``, so it starts untainted, gets the owner's remembered facts and may run
  phrase routines, exactly as on the desktop. A paired chat is the owner's because the
  channel's provider authenticates the chat (a Telegram chat id, the WhatsApp linked
  account); the gateway checks ``chat_id`` against the channel's ``owner_chat_id`` itself
  and never trusts ``is_owner`` alone. What a stolen chat could still do is bounded by the
  ordinary approval policy, and the physical-security class is never approved remotely by
  default (services/channels/approvals.py). Untrusted content the turn reads still taints
  it as usual.
- **Everyone else's messages** never reach the brain: each is stored in the channel inbox
  (``ChannelMessages``) and published as a ``message.received`` Signal (urgency 1, with
  ``person_id`` when the sender is in the People list; none for a blocked person). A
  routine started by that signal starts tainted (services/routines.py).
- **Remote approvals**: ``ApprovalBridge`` (approvals.py).
- **Away delivery**: ``remote_delivery`` is a proactive ``remote_hooks`` entry: while the
  owner is away a signal is sent as one short text to the paired owner chat.

Never logged: message text, sender names or addresses, chat ids, conversation ids.
"""

import asyncio
import datetime as dt
import hmac
import re

from services.channels.approvals import (
    APPROVED, DECLINED, EXPIRED, INVALID, NOT_OWNER, PHYSICAL, USED, ApprovalBridge,
)
from services.channels.base import Channel, InboundMessage
from services.channels.store import ChannelMessages
from services.log import get_logger
from services.signals import signal
from services.tools import ServiceError

logger = get_logger(__name__)

PART_LIMIT = 3500  # characters per sent part (Telegram allows 4096)
TYPING_INTERVAL_S = 4.0  # a Telegram chat action lasts about five seconds
REQUEST_TEXT_LIMIT = 12_000  # ConversationRequest.text
REMOTE_TEXT_LIMIT = 600
OWNER_CHANNEL = "owner"  # services/conversation.py channel_taint: the owner's own turn
MESSAGE_TTL_HOURS = 12
CHANNEL_LABELS = {"telegram": "Telegram", "whatsapp": "WhatsApp"}
NOT_READY = "JARVIS isn't ready on the PC yet. Try again in a moment."
FAILED = "Something went wrong on the PC. Try again."
ANSWER_LINES = {
    APPROVED: "Approved.",
    DECLINED: "Declined.",
    EXPIRED: "That approval is no longer waiting.",
    USED: "That approval was already answered.",
    INVALID: "That approval couldn't be verified.",
    PHYSICAL: "That one can only be approved on the PC.",
}
_BOUNDARY = re.compile(r"(?<=[.!?…])[\"')\]]*\s+|\n+")


def split_text(text, limit=PART_LIMIT):
    """Parts of at most ``limit`` characters, cut after a sentence (or a line) when one ends
    in the second half of the window, else at a space, else hard."""
    text = (text or "").strip()
    parts = []
    while len(text) > limit:
        window = text[: limit + 1]
        cut = 0
        for match in _BOUNDARY.finditer(window):
            if match.start() <= limit:
                cut = match.start()
        if cut < limit // 2:
            space = window.rfind(" ", 0, limit)
            cut = space if space >= limit // 2 else limit
        part = text[:cut].rstrip()
        if part:
            parts.append(part)
        text = text[cut:].lstrip()
    if text:
        parts.append(text)
    return parts


def remote_text(item):
    """The short text a signal is sent as while the owner is away."""
    text = item.title
    if item.body:
        text = f"{text}. {item.body}" if not text.endswith((".", "!", "?")) else f"{text} {item.body}"
    return text if len(text) <= REMOTE_TEXT_LIMIT else text[: REMOTE_TEXT_LIMIT - 1] + "…"


def _same(left, right):
    return isinstance(left, str) and isinstance(right, str) and hmac.compare_digest(
        left.encode("utf-8"), right.encode("utf-8")
    )


class ChannelGateway:
    """Owned by the composition root (application.py): ``start()`` / ``close()``."""

    def __init__(self, app, *, store=None):
        self.app = app
        self.channels = {}  # name -> Channel, in registration order
        self.store = store or ChannelMessages(app.database)
        self.bridge = ApprovalBridge(self)
        self.tasks = set()
        self.started = False
        self.last_owner_channel = None
        app.dispatcher.approval_observers.append(self.bridge)
        proactive = getattr(app, "proactive", None)
        if proactive is not None:
            proactive.remote_hooks.append(self.remote_delivery)

    # --- channels --------------------------------------------------------------------------

    def register(self, channel):
        if not isinstance(channel, Channel):
            raise TypeError("ChannelGateway.register takes a Channel")
        if channel.name in self.channels:
            raise ValueError("A channel with this name is already registered")
        channel.bind(self.receive)
        self.channels[channel.name] = channel
        if self.started:
            self.spawn(self._start(channel))
        return channel

    async def _start(self, channel):
        try:
            await channel.start()
        except Exception as exc:
            logger.warning("Channel %s did not start (%s)", channel.name, type(exc).__name__)

    async def start(self):
        if self.started:
            return
        self.started = True
        for channel in tuple(self.channels.values()):
            await self._start(channel)

    async def close(self):
        self.started = False
        for channel in tuple(self.channels.values()):
            try:
                await channel.stop()
            except Exception as exc:
                logger.warning("Channel %s did not stop (%s)", channel.name, type(exc).__name__)
        tasks = [task for task in self.tasks if not task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def spawn(self, coroutine):
        try:
            task = asyncio.get_running_loop().create_task(coroutine, name="channels")
        except RuntimeError:
            coroutine.close()
            return None
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    async def wait_idle(self):
        """Wait for the turns and sends started so far (tests, shutdown)."""
        while True:
            pending = [task for task in self.tasks if not task.done()]
            if not pending:
                return
            await asyncio.gather(*pending, return_exceptions=True)

    def status(self):
        items = []
        for channel in self.channels.values():
            try:
                paired, state = self._owner_chat(channel) is not None, str(channel.state)
            except Exception:
                paired, state = False, "error"
            items.append({"name": channel.name, "paired": paired, "state": state})
        return items

    # --- the owner -------------------------------------------------------------------------

    def owner(self):
        sessions = self.app.sessions
        native = getattr(sessions, "native_desktop", None)
        return native.state.identity.owner if native else sessions.local_owner

    def owner_is(self, principal):
        try:
            return principal is not None and self.app.sessions.is_owner(principal)
        except Exception:
            return False

    def away(self):
        proactive = getattr(self.app, "proactive", None)
        try:
            return proactive is not None and proactive.presence() == "away"
        except Exception:
            return False

    @staticmethod
    def _owner_chat(channel):
        chat = channel.owner_chat_id
        return str(chat) if chat not in (None, "") else None

    def owner_target(self):
        """(channel, owner chat id) the owner is reached on: the channel they last wrote
        from, else the first paired one; None when nothing is paired."""
        names = [self.last_owner_channel, *self.channels]
        for name in names:
            channel = self.channels.get(name) if name else None
            if channel is None:
                continue
            try:
                chat = self._owner_chat(channel)
            except Exception:
                continue
            if chat is not None:
                return channel, chat
        return None

    def from_owner(self, channel, message):
        """The channel says so and the chat is its paired owner chat."""
        try:
            return message.is_owner is True and _same(self._owner_chat(channel), message.chat_id)
        except Exception:
            return False

    # --- inbound ---------------------------------------------------------------------------

    async def receive(self, message):
        """A channel's inbound callback. Returns what happened: ``turn``, ``inbox``, an
        approval outcome, ``ignored`` or ``refused``. Never raises."""
        try:
            if not isinstance(message, InboundMessage):
                return "ignored"
            channel = self.channels.get(message.channel)
            if channel is None:
                return "ignored"
            owner = self.from_owner(channel, message)
            if message.approval_answer is not None:
                if not owner:
                    logger.info("Remote approval answer refused on %s: %s", channel.name,
                                NOT_OWNER)
                    return "refused"
                outcome = await self.bridge.answer(message)
                await self.say(channel, message.chat_id, ANSWER_LINES.get(outcome, FAILED))
                return outcome
            if owner:
                self.last_owner_channel = channel.name
                if not message.text.strip():
                    return "ignored"  # voice notes and photos arrive with the real channels
                self.spawn(self.owner_turn(channel, message))
                return "turn"
            self.someone_else(channel, message)
            return "inbox"
        except Exception as exc:
            logger.warning("A channel message could not be handled (%s)", type(exc).__name__)
            return "ignored"

    async def say(self, channel, chat_id, text):
        for part in split_text(text):
            try:
                await channel.send_text(chat_id, part)
            except Exception as exc:
                logger.warning("A message could not be sent on %s (%s)", channel.name,
                               type(exc).__name__)
                return False
        return True

    async def _typing(self, channel, chat_id):
        typing = getattr(channel, "typing", None)
        if not callable(typing):
            return
        while True:
            try:
                await typing(chat_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("Typing indicator failed on %s (%s)", channel.name,
                             type(exc).__name__)
            await asyncio.sleep(TYPING_INTERVAL_S)

    def approver(self, owner, channel, chat_id):
        """A remote turn's approval cards: the owner's desktop windows and the chat itself."""

        async def approve(payload):
            for room in self.app.sessions.rooms(owner, "renderer"):
                await self.app.sio.emit("tool_confirmation_request", payload, room=room)
            self.bridge.offer(owner, payload, (channel, chat_id), self.app.dispatcher.timeout)

        return approve

    async def owner_turn(self, channel, message):
        from services.conversation import ConversationRequest

        chat_id = message.chat_id
        owner = self.owner()
        if owner is None:
            await self.say(channel, chat_id, NOT_READY)
            return
        typing = asyncio.get_running_loop().create_task(self._typing(channel, chat_id))
        try:
            project = self.app.projects.get_current_project_path().resolve()
            conversation_id = self.store.conversation(channel.name, chat_id, project)
            request = ConversationRequest(
                text=message.text.strip()[:REQUEST_TEXT_LIMIT], conversation_id=conversation_id
            )
            result = await self.app.conversation.reply(
                owner, request, project, self.approver(owner, channel, chat_id),
                channel=OWNER_CHANNEL,
            )
            answer = result.text
            logger.info("Channel turn on %s answered (%d parts)", channel.name,
                        len(split_text(answer)))
        except ServiceError as exc:
            answer = str(exc) or FAILED  # ServiceError messages are written for the owner
            logger.info("Channel turn on %s failed (%s)", channel.name, exc.code)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            answer = FAILED
            logger.warning("Channel turn on %s failed (%s)", channel.name, type(exc).__name__)
        finally:
            typing.cancel()
            await asyncio.gather(typing, return_exceptions=True)
        await self.say(channel, chat_id, answer)

    def _person(self, sender):
        contacts = getattr(self.app, "contacts", None)
        if contacts is None or not isinstance(sender, str) or not sender:
            return None
        try:
            person = contacts.match(sender)
        except Exception as exc:
            logger.warning("A channel message could not read the people list (%s)",
                           type(exc).__name__)
            return None
        return person if isinstance(person, dict) else None

    def someone_else(self, channel, message):
        """Someone else's message: the inbox and a ``message.received`` signal, never a turn."""
        person = self._person(message.sender)
        entry = self.store.add(message, person)
        group = person.get("group") if person else None
        logger.info("Channel message on %s stored for the inbox", channel.name)
        if group == "blocked":
            return entry
        label = CHANNEL_LABELS.get(channel.name, channel.name.replace("_", " ").title())
        name = (person or {}).get("name") or entry.get("sender_name")
        title = f"{label} message from {name}" if name else f"New {label} message"
        signals = getattr(self.app, "signals", None)
        if signals is not None:
            now = signals.now()
            item = signal(
                "message.received", channel.name, title, at=now,
                ttl=dt.timedelta(hours=MESSAGE_TTL_HOURS), urgency=1,
                dedupe_key=f"message:{entry['id']}", body=message.text,
                data={"channel": channel.name, "message_id": entry["id"],
                      "media": len(entry["media"]),
                      **({"group": group} if group in ("vip", "known") else {})},
                person_id=person.get("id") if person else None,
            )
            signals.publish(item)
        return entry

    # --- proactive away delivery -----------------------------------------------------------

    async def remote_delivery(self, item):
        """A proactive ``remote_hooks`` entry: one short text to the paired owner chat."""
        target = self.owner_target()
        if target is None:
            return False
        channel, chat_id = target
        return await self.say(channel, chat_id, remote_text(item))
