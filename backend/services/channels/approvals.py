"""Remote approvals (S8.1, docs/CHANNELS.md): a pending approval card offered on the owner's
paired remote channel, answered there with a signed, single-use, expiring id.

``ApprovalBridge`` observes every approval card the shared ``ToolDispatcher`` raises
(``dispatcher.approval_observers``). When the owner is away (the proactive engine's
presence) and a channel is paired, it sends the card there too; a remote owner turn's own
cards always go to the chat it came from. The desktop card is unchanged: whichever answer
arrives first wins, through ``ToolDispatcher.resolve``.

**Signature.** The card carries a random handle (12 url-safe characters), never the
dispatcher's request id. Each decision on it is signed:
``HMAC-SHA256(key, "jarvis-approval-v1\\n<channel>\\n<chat id>\\n<handle>\\n<approve|deny>\\n
<expires unix seconds>")``, the first 16 bytes in unpadded base64url. The key is a per-install
random secret (internal ``SecretSpec`` ``channel_approval_key``, DPAPI-encrypted in the
profile database), created on first use. An answer is accepted only from the chat the card
went to, only once, only before the approval's own timeout, and only with the signature of
the decision it claims.

**Physical-security class** (``physical_security``): Home Assistant locks, covers and alarms
(and every lock, unlock, open, close, arm and disarm action), every ``homelab_*`` tool (wake
and power actions), tools named for unlock, disarm, gates or garages, and computer use. It
is not approved remotely unless ``channels.remote_approval_physical`` is on: the card then
has no approve signature (it can still be declined), and an approve answer is refused.

Logs carry outcome codes and tool names only, never chat ids, handles, signatures or card text.
"""

import base64
import collections
import datetime as dt
import hashlib
import hmac
import json
import re
import secrets as token_source
import time
from dataclasses import dataclass

from services.channels.base import CARD_SUMMARY_LIMIT, CARD_TITLE_LIMIT, RemoteApproval
from services.log import get_logger
from services.settings import channels_settings
from services.tools import TAINT_FACT

logger = get_logger(__name__)

KEY_NAME = "channel_approval_key"
SIGNATURE_VERSION = "jarvis-approval-v1"
SIGNATURE_BYTES = 16
HANDLE_BYTES = 9  # 12 url-safe characters: a Telegram callback_data stays under 64 bytes
OFFER_LIMIT = 256  # offers remembered (open ones, then answered and settled tombstones)

# --- the physical-security class ------------------------------------------------------------

PHYSICAL_HOME_DOMAINS = frozenset({"lock", "cover", "alarm_control_panel"})
PHYSICAL_HOME_ACTIONS = frozenset(
    {"lock", "unlock", "open", "close", "arm_home", "arm_away", "disarm"}
)
PHYSICAL_TOOL_PREFIXES = ("homelab_", "computer_", "mcp__computer", "mcp__windows")
COMPUTER_USE_TOOLS = frozenset({"computer", "computer_use"})
_PHYSICAL_WORD = re.compile(r"(?:^|_)(unlock|disarm|gate|garage)(?:_|$)")


def physical_security(tool, args):
    """True for an approval no remote channel may grant by default."""
    if not isinstance(tool, str) or not tool:
        return True  # unknown: the safe side
    args = args if isinstance(args, dict) else {}
    if tool == "home_control":
        entity = args.get("entity_id")
        domain = entity.split(".", 1)[0] if isinstance(entity, str) else None
        return domain in PHYSICAL_HOME_DOMAINS or args.get("action") in PHYSICAL_HOME_ACTIONS
    if tool in COMPUTER_USE_TOOLS or tool.startswith(PHYSICAL_TOOL_PREFIXES):
        return True
    return _PHYSICAL_WORD.search(tool.lower()) is not None


# --- the card: the desktop card's title and summary (src/components/approvalView.js) --------

GENERIC_SUMMARY = "JARVIS continues only after you approve. Denying leaves this action undone."
HOME_ACTION_LABELS = frozenset({
    "Turn on", "Turn off", "Toggle", "Set", "Activate", "Run", "Lock", "Unlock", "Open",
    "Close", "Arm", "Disarm", "Play", "Pause",
})
FACT_LIMIT = 8
FACT_VALUE_LIMIT = 200
MCP_DETAILS_LIMIT = 600


def _clip(text, limit):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _value(value):
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return str(value)


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def approval_card(payload):
    """(title, summary, facts) for one dispatcher approval payload, matching the desktop
    card's wording for the tools it lays out specially."""
    tool = payload.get("tool") if isinstance(payload.get("tool"), str) else ""
    args = payload.get("args") if isinstance(payload.get("args"), dict) else {}
    if tool == "place_task_call" and _text(args.get("summary")):
        return "Outgoing call", _text(args["summary"]), ()
    if tool == "calendar_add_event" and _text(args.get("approval")):
        return "Add to calendar", _text(args["approval"]), ()
    if tool == "home_control" and _text(args.get("approval")) \
            and args.get("approve_label") in HOME_ACTION_LABELS:
        return _text(args["approval"]), GENERIC_SUMMARY, ()
    if tool.startswith("mcp__") and _text(args.get("server")):
        name = _text(args.get("tool_title")) or _text(args.get("mcp_tool")) or tool
        values = args.get("arguments") if isinstance(args.get("arguments"), dict) else {}
        return (f"{_text(args['server'])}: {name}", GENERIC_SUMMARY,
                (("arguments", _clip(_value(values), MCP_DETAILS_LIMIT)),))
    if tool == "build_live_design":
        return ("Build live design",
                _text(args.get("summary")) or "Build the live design as STL and GLB on this PC.",
                ())
    if tool == "look_through_camera":
        return ("Look through your camera?",
                "JARVIS wants to look through your camera. It takes one still photo to answer "
                "you, then the camera turns off again.", ())
    if tool == "look_at_screen":
        target = "active window" if args.get("region") == "window" else "whole screen"
        return ("Look at your screen?",
                f"JARVIS takes one screenshot of the {target} to answer you. It goes only to "
                "your AI provider and isn't saved.", ())
    facts = tuple(
        (str(key), _clip(_value(value), FACT_VALUE_LIMIT))
        for key, value in args.items() if key != TAINT_FACT
    )[:FACT_LIMIT]
    return (tool.replace("_", " ") if tool else "Assistant action"), GENERIC_SUMMARY, facts


# --- signing --------------------------------------------------------------------------------


def sign(key, channel, chat_id, handle, approved, expires):
    message = "\n".join((
        SIGNATURE_VERSION, channel, str(chat_id), handle, "approve" if approved else "deny",
        str(int(expires)),
    ))
    digest = hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()[:SIGNATURE_BYTES]
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass
class Offer:
    handle: str
    request_id: str
    principal: str
    channel: str
    chat_id: str
    expires: int  # unix seconds
    physical: bool
    tool: str
    state: str = "open"  # open | answered | settled


# Outcomes of ApprovalBridge.answer.
APPROVED, DECLINED = "approved", "declined"
INVALID, EXPIRED, USED, NOT_OWNER, PHYSICAL = (
    "invalid", "expired", "used", "not_owner", "physical_refused"
)


class ApprovalBridge:
    """Owned by ``ChannelGateway``; registered as a dispatcher approval observer."""

    def __init__(self, gateway, *, clock=time.time):
        self.gateway, self.app, self.clock = gateway, gateway.app, clock
        self.offers = collections.OrderedDict()  # handle -> Offer, oldest first
        self.by_request = {}  # dispatcher request id -> handle
        self._key = None

    # --- the per-install key ---------------------------------------------------------------

    def key(self):
        if self._key is None:
            store = self.app.secrets
            value = store.get(KEY_NAME)
            if not value:
                value = token_source.token_urlsafe(32)
                store.set(KEY_NAME, value)
                logger.info("Remote approval signing key created")
            self._key = value.encode("utf-8")
        return self._key

    def sign(self, offer, approved):
        return sign(self.key(), offer.channel, offer.chat_id, offer.handle, approved,
                    offer.expires)

    def physical_allowed(self):
        return channels_settings(self.app.settings)["remote_approval_physical"] is True

    # --- ToolDispatcher.approval_observers -------------------------------------------------

    def approval_offered(self, principal, payload, timeout):
        """Every approval card: offered remotely when it is the owner's and they are away."""
        if not self.gateway.owner_is(principal) or not self.gateway.away():
            return
        target = self.gateway.owner_target()
        if target is not None:
            self.offer(principal, payload, target, timeout)

    def approval_settled(self, request_id):
        """The dispatcher stopped waiting (answered anywhere, expired or cancelled)."""
        offer = self.offers.get(self.by_request.pop(request_id, None))
        if offer is not None and offer.state == "open":
            offer.state = "settled"

    # --- offering ---------------------------------------------------------------------------

    def _remember(self, offer):
        self.offers[offer.handle] = offer
        self.by_request[offer.request_id] = offer.handle
        while len(self.offers) > OFFER_LIMIT:
            # The oldest answered or settled card goes first, else the oldest card.
            handle = next(
                (key for key, item in self.offers.items() if item.state != "open"),
                next(iter(self.offers)),
            )
            item = self.offers.pop(handle)
            if self.by_request.get(item.request_id) == handle:
                del self.by_request[item.request_id]

    def offer(self, principal, payload, target, timeout):
        """Send one card to ``target`` (channel, chat id) unless this approval was already
        offered remotely; returns the ``RemoteApproval`` sent, else None. Never raises."""
        try:
            request_id = payload.get("id") if isinstance(payload, dict) else None
            if not isinstance(request_id, str) or request_id in self.by_request:
                return None
            channel, chat_id = target
            tool = payload.get("tool") if isinstance(payload.get("tool"), str) else ""
            physical = physical_security(tool, payload.get("args"))
            offer = Offer(
                handle=token_source.token_urlsafe(HANDLE_BYTES), request_id=request_id,
                principal=principal, channel=channel.name, chat_id=str(chat_id),
                expires=int(self.clock() + float(timeout)), physical=physical, tool=tool,
            )
            title, summary, facts = approval_card(payload)
            taint = payload.get("taint_line")
            card = RemoteApproval(
                approval_id=offer.handle, tool=tool, title=_clip(title, CARD_TITLE_LIMIT),
                summary=_clip(summary, CARD_SUMMARY_LIMIT), facts=facts,
                taint_line=taint if isinstance(taint, str) and taint else None,
                expires_at=dt.datetime.fromtimestamp(offer.expires, dt.timezone.utc),
                approve_signature=(
                    self.sign(offer, True) if not physical or self.physical_allowed() else ""
                ),
                deny_signature=self.sign(offer, False), physical=physical,
            )
            self._remember(offer)
        except Exception as exc:
            logger.warning("A remote approval could not be prepared (%s)", type(exc).__name__)
            return None
        logger.info("Remote approval offered tool=%s channel=%s physical=%s", tool,
                    offer.channel, physical)
        self.gateway.spawn(self._send(channel, offer.chat_id, card))
        return card

    async def _send(self, channel, chat_id, card):
        try:
            await channel.send_approval(chat_id, card)
        except Exception as exc:
            logger.warning("A remote approval could not be sent on %s (%s)", channel.name,
                           type(exc).__name__)

    # --- answering --------------------------------------------------------------------------

    async def answer(self, message):
        """Check and apply one remote answer; returns an outcome code. The gateway has
        already checked the message came from the channel's paired owner chat."""
        answer = message.approval_answer
        offer = self.offers.get(answer.approval_id)
        if offer is None:
            outcome = INVALID
        elif offer.channel != message.channel or not hmac.compare_digest(
            offer.chat_id.encode("utf-8"), message.chat_id.encode("utf-8")
        ):
            outcome = NOT_OWNER
        elif not hmac.compare_digest(
            self.sign(offer, answer.approved).encode("ascii"),
            answer.signature.encode("utf-8", "replace"),
        ):
            outcome = INVALID
        elif offer.state == "answered":
            outcome = USED
        elif offer.state == "settled" or self.clock() >= offer.expires:
            outcome = EXPIRED
        elif answer.approved and offer.physical and not self.physical_allowed():
            outcome = PHYSICAL
        else:
            offer.state = "answered"  # once, whatever the dispatcher says next
            resolved = self.app.dispatcher.resolve(
                offer.principal, offer.request_id, answer.approved
            )
            outcome = (APPROVED if answer.approved else DECLINED) if resolved else EXPIRED
        logger.info("Remote approval answer on %s: %s", message.channel, outcome)
        return outcome
