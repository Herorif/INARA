"""The channel inbox (S8.1, docs/CHANNELS.md): messages from other people that reached a
paired channel, kept for the owner to read. There is no other inbox store for them (the
mobile ``NotificationInbox`` is a per-device notification ledger), so each message is one
DPAPI-protected document of kind ``channel_messages`` in the profile database
(services.storage), the newest ``MESSAGES_LIMIT`` kept.

Per-chat conversation ids for the owner's own chats live beside it (kind
``channel_conversations``), keyed by a hash of the channel and chat id, never the id itself.
"""

import datetime as dt
import uuid

from services.storage import scope_hash

MESSAGES_KIND = "channel_messages"
CONVERSATIONS_KIND = "channel_conversations"
MESSAGES_LIMIT = 500
TEXT_LIMIT = 4000
NAME_LIMIT = 80
UTC = dt.timezone.utc


def _clean(value, limit):
    if not isinstance(value, str):
        return None
    return " ".join(value.split())[:limit] or None


class ChannelMessages:
    def __init__(self, database, *, now=lambda: dt.datetime.now(UTC)):
        self.database, self.now = database, now

    def add(self, message, person=None):
        """Store one message from someone else; returns the stored entry."""
        entry = {
            "id": str(uuid.uuid4()),
            "channel": message.channel,
            "chat_id": message.chat_id,  # encrypted with the entry; never listed or logged
            "sender": _clean(message.sender, NAME_LIMIT),
            "sender_name": _clean(message.sender_name, NAME_LIMIT),
            "person_id": person.get("id") if isinstance(person, dict) else None,
            "person_name": person.get("name") if isinstance(person, dict) else None,
            "text": (message.text or "")[:TEXT_LIMIT],
            "media": [str(item.get("kind") or "file")[:32] for item in message.media][:10],
            "at": message.at.astimezone(UTC).isoformat(),
            "received_at": self.now().isoformat(),
        }
        database = self.database
        with database.transaction() as db:
            database.put(db, MESSAGES_KIND, entry["id"], entry)
            rows = database.all(db, MESSAGES_KIND)
            if len(rows) > MESSAGES_LIMIT:
                rows.sort(key=lambda item: (item.get("received_at") or "", item.get("id") or ""))
                for old in rows[: len(rows) - MESSAGES_LIMIT]:
                    db.execute("DELETE FROM documents WHERE kind=? AND id=?",
                               (MESSAGES_KIND, old["id"]))
        return entry

    def list(self, limit=50):
        """The newest ``limit`` entries, newest first, without chat ids."""
        database = self.database
        with database.connection() as db:
            rows = database.all(db, MESSAGES_KIND)
        rows.sort(key=lambda item: (item.get("received_at") or "", item.get("id") or ""),
                  reverse=True)
        keys = ("id", "channel", "sender", "sender_name", "person_id", "person_name", "text",
                "media", "at", "received_at")
        return [{key: item.get(key) for key in keys} for item in rows[:limit]]

    def conversation(self, channel, chat_id, project):
        """The owner's conversation id for this chat in this project (one per channel and
        chat, persisted); a project switch starts a new one, as the desktop does."""
        key = scope_hash(f"{channel}\n{chat_id}")
        database = self.database
        with database.transaction() as db:
            saved = database.get(db, CONVERSATIONS_KIND, key)
            if isinstance(saved, dict) and saved.get("project") == str(project):
                try:
                    return uuid.UUID(saved.get("conversation_id"))
                except (TypeError, ValueError):
                    pass
            value = uuid.uuid4()
            database.put(db, CONVERSATIONS_KIND, key,
                         {"conversation_id": str(value), "project": str(project)})
        return value
