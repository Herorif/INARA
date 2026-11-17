# Channels

Remote messaging channels let the owner talk to JARVIS away from the PC and let other
people's messages reach the owner as Signals. S8.1 is the package and the gateway; the real
channels come next: Telegram (S8.2, official Bot API) and WhatsApp (S8.3/8.4, a linked
device). Spec: `docs/handover/9NovWork-specs.md` S8.

Code: `backend/services/channels/` (`base.py`, `gateway.py`, `approvals.py`, `store.py`,
`fake.py`) and `backend/transport/channels.py`. Wired in `backend/application.py` as
`app.channels` (`ChannelGateway`), started after the heartbeat and closed with it.

## The channel contract (`base.py`)

A channel implements `Channel`:

| Member | What it does |
| --- | --- |
| `name` | `telegram`, `whatsapp`, ... (also the Signal `source` and the inbox `channel`) |
| `owner_chat_id` | The paired owner chat, or `None` before pairing |
| `state` | A short word for `channels_status` (`stopped`, `running`, `error`, ...) |
| `bind(deliver)` | Called once by `ChannelGateway.register`; the channel awaits `deliver(InboundMessage)` for every inbound message |
| `async start()` / `async stop()` | Lifetime |
| `async send_text(chat_id, text)` | One plain message (the gateway splits long answers) |
| `async send_approval(chat_id, RemoteApproval)` | An approval card with signed answers |
| `async typing(chat_id)` (optional) | Typing indicator, called every 4 s while a reply is written |

`InboundMessage(channel, chat_id, sender, text, media, at, is_owner, approval_answer,
sender_name)`. `media` is a tuple of small dicts (at least `kind`); the channel keeps the
bytes. `sender` is the stable address (E.164 for WhatsApp); `sender_name` is the sender's own
display name and is untrusted. `approval_answer` is an `ApprovalAnswer(approval_id, approved,
signature)` when the message is a button press on a card.

`RemoteApproval` carries `approval_id` (the signed handle), `tool`, `title`, `summary`,
`facts`, `taint_line`, `expires_at`, `approve_signature`, `deny_signature`, `physical` and
`as_text()` for channels without rich cards. An empty `approve_signature` means the card may
only be declined remotely.

`FakeChannel` (`fake.py`) records sends and feeds inbound messages; tests use it.

## Owner messages

The gateway accepts a message as the owner's only when the channel says `is_owner` **and**
`chat_id` equals the channel's `owner_chat_id` (constant-time compare). Then:

- One brain turn, `ConversationService.reply(owner, request, project, approve,
  channel="owner")`, run in the background so the channel's receive loop stays free (an
  approval answer for this very turn may arrive while it runs).
- One conversation per channel and chat, persisted (kind `channel_conversations`, keyed by a
  hash of channel and chat id, value encrypted). A project switch starts a new conversation,
  as the desktop does.
- The answer is sent with `send_text`, split at sentence (or line) boundaries into parts of at
  most 3,500 characters. A `ServiceError` is answered with its owner-facing message; anything
  else with a plain "Something went wrong" line.
- Messages with no text (a voice note, a photo) are ignored for now; the real channels add
  transcription (S8.2 routes voice notes through the existing Gemini transcription).

### Taint decision

An owner turn from a paired chat is the owner's own turn: it passes `channel="owner"`
(`channel_taint` gives an empty set), so it starts untainted, gets the owner's remembered
facts and may start phrase routines, exactly like a desktop turn. Reasons and limits:

- The chat is authenticated by the channel's provider (a Telegram chat id cannot be chosen by
  a sender; the WhatsApp linked account is the owner's). The gateway re-checks the chat id
  itself and never trusts `is_owner` alone.
- A stolen chat could still do what the owner could do remotely, bounded by the ordinary
  approval policy; the physical-security class is never approved remotely by default.
- Untrusted content the turn reads (a web page, an MCP result) still taints it as usual.
- Messages from anyone else never become a turn (below), so the S15.1 channel taint
  (`telegram` -> "a Telegram message") stays for any later non-owner path.
- Bot chats are not end-to-end encrypted: answers (which may draw on remembered facts) travel
  through the provider. Preferences must say so when Telegram is paired (S8.2).

Face lock still wins: while JARVIS is face-locked on the PC, the dispatcher refuses every tool
call (`authentication_required`), so a remote turn can talk but not act.

## Everyone else's messages

Never a brain turn. Each message is:

- stored in the channel inbox (kind `channel_messages`, one DPAPI-encrypted document per
  message, newest 500 kept; the chat id is stored encrypted but never listed), and
- published as a `message.received` Signal: urgency 1, source = the channel name, title
  "<Channel> message from <name>" (the People name when the sender's number matches a
  person, else the sender's display name, else "New <Channel> message"), body = the text,
  `person_id` when matched, `data` {channel, message_id, media count, group}. A blocked
  person's message is stored but not signalled. The heartbeat and routines treat titles and
  bodies as untrusted data; a routine started by it starts tainted.

There was no reusable Inbox store for this: the mobile `NotificationInbox` is a per-device
Android notification ledger, so channel messages have their own store.

## Remote approvals (`approvals.py`)

`ApprovalBridge` is registered on `ToolDispatcher.approval_observers`; the dispatcher calls
`approval_offered(principal, payload, timeout)` when it raises a card and
`approval_settled(request_id)` when it stops waiting. The bridge offers a card remotely when:

- the approval is the owner's, the owner is **away** (`ProactiveEngine.presence()`), and a
  channel is paired (the channel the owner last wrote from, else the first paired one); or
- the approval belongs to a remote owner turn: it always goes to the chat the turn came from,
  and to the owner's desktop windows too.

Each approval is offered remotely at most once. The desktop card is unchanged; the first
answer wins through `ToolDispatcher.resolve`.

**Card content** is the desktop card's (`src/components/approvalView.js`): the title and
summary of the special layouts (outgoing call, calendar event, home control, MCP tools, live
design, camera and screen looks), else the tool name with up to eight review facts (200
characters each), plus the taint line when the turn read untrusted content.

**Signature scheme.**

- The card carries a random handle (`secrets.token_urlsafe(9)`, 12 characters), never the
  dispatcher's request id.
- Each decision is signed: `HMAC-SHA256(key, "jarvis-approval-v1\n<channel>\n<chat id>\n
  <handle>\n<approve|deny>\n<expires unix seconds>")`, first 16 bytes, unpadded base64url
  (22 characters). Handle plus signature fit a Telegram `callback_data` (64 bytes).
- The key is a per-install random secret, the internal SecretSpec `channel_approval_key`
  (DPAPI-encrypted in the profile database, never listed or user-set), created on first use.
- The card expires after the approval's own timeout (the dispatcher's, 60 s by default).

An answer is accepted only from the paired owner chat the card went to, only with the
signature of the decision it claims, only once, and only while the approval is still waiting.
Outcomes: `approved`, `declined`, `invalid` (unknown handle or bad signature), `not_owner`,
`used`, `expired` (past the timeout or already answered elsewhere) and `physical_refused`; the
owner chat gets a one-line reply for each, other chats get nothing.

**Physical-security class** (`physical_security`): `home_control` on a lock, cover or alarm
(or any lock, unlock, open, close, arm or disarm action), every `homelab_*` tool (wake and
power actions), tools whose name has `unlock`, `disarm`, `gate` or `garage` as a word, and
computer use (`computer`, `computer_use`, `computer_*`, `mcp__computer*`, `mcp__windows*`). With
`channels.remote_approval_physical` off (the default) such a card has no approve signature and
an approve answer is refused even when correctly signed; declining still works. The setting
is read again when the answer arrives.

Known limit: a routine run with no workspace window open waits for one before its approval
card counts (`RoutineService.owner_approval`), so a remote approval of a routine step only
takes effect once a window is open.

## Away delivery

`ChannelGateway.remote_delivery` is a `ProactiveEngine.remote_hooks` entry. While the owner is
away, a signal the engine would tell is sent as one short text ("<title>. <body>", at most 600
characters) to the paired owner chat and recorded with the `remote` channel; with nothing
paired it returns False and the signal is held for the digest as before.

## Settings

`channels.remote_approval_physical` (bool, default false): allow the physical-security class
to be approved from a paired channel.

## Routes (owner-only, never model tools)

- `channels_status {}` -> `{ok, channels: [{name, paired, state}]}`.
- `channel_messages_list {limit?}` (1-200, default 50) -> `{ok, messages: [{id, channel,
  sender, sender_name, person_id, person_name, text, media, at, received_at}]}`, newest first.

Both are in `docs/ROUTE_POLICY_MATRIX.json`.

## Privacy

Logs carry channel names, outcome codes, tool names and counts only: never message text,
sender names or addresses, chat ids, conversation ids, approval handles or signatures.
