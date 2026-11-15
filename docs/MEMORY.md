# Long-term memory ("What JARVIS knows")

JARVIS remembers lasting facts about the owner across conversations: who they are, what they
like, the people and places in their life, their routines and notable past episodes. This
page covers the store and the brain's tools (S6.1). Automatic extraction after a
conversation, the per-turn read path and the Preferences page are later steps; they build on
the methods below.

This is separate from **project memory** (`docs/PROJECT_MEMORY.md`,
`services/project_memory.py`, the `memory_*` socket routes): project notes are per project
and never written by the model. Long-term memory is the owner's, across all projects.

## Where it is stored

In the core's database (`<user data>\data-v1\assistant.sqlite3`), next to every other
private record. `backend/services/memory_facts.py` (`FactStore`) owns two tables:

`memory_facts`, one row per fact:

| column | |
| --- | --- |
| `id` | UUID, never changes, also across edits |
| `kind` | `profile`, `preference`, `person`, `place`, `routine` or `episode` (CHECK) |
| `subject` | a few words naming what the fact is about; **DPAPI ciphertext** |
| `text` | the fact, one short sentence; **DPAPI ciphertext** |
| `confidence` | 0 to 1 (CHECK), 1 for facts the owner gave |
| `pinned` | 0 or 1 (CHECK): part of the owner's profile block |
| `sensitivity` | `normal`, `personal` or `sensitive` (CHECK) |
| `source_conversation_id`, `source_turn` | where it was learned, when known |
| `created_at`, `updated_at` | UTC ISO timestamps; `updated_at` records the last edit |
| `valid_from`, `valid_to` | when the fact holds, when known |
| `superseded_by` | the id of the fact that replaced this one |

`memory_facts_fts`, an FTS5 table (`fact_id UNINDEXED, subject, text`) used for BM25 ranking.

**Nothing is stored in plain text.** Like every private payload in this database
(`docs/PERSISTENCE.md`), `subject` and `text` are protected with Windows DPAPI before SQLite
sees them. The FTS5 table never holds the words either: each word is NFKC-normalised and
casefolded, common English and Malay words are dropped, and every remaining word is replaced
by the first 80 bits of HMAC-SHA256 under a random 256-bit key. That key is itself stored
DPAPI-protected (document `memory_facts_key`). BM25 only needs term and document
frequencies, which survive hashing. What the index does reveal is that two facts share a
word, and how often; not which word.

The migration `memory_facts:v1` is recorded in the shared `migrations` table with the
SHA-256 of its statements. It runs once and is idempotent; a later change adds a new entry
(`memory_facts:v2`), never edits a shipped one, and a mismatching record stops the store
with a clear error. FTS5 is checked first (SQLite 3.45.3 in the core's Python 3.13 has it);
without it the store refuses to open with a clear message, and the tools and routes answer
`memory_unavailable` while the rest of JARVIS keeps working.

Limits: subject 120 characters, text 1,000, at most 5,000 facts.

## The rules

- **Superseded, never overwritten.** `supersede(old_id, text, ...)` adds the new fact
  (`valid_from` now) and closes the old one (`valid_to` now, `superseded_by` the new id) in
  one transaction. Kind, subject, pin and sensitivity carry over unless given. A fact can be
  superseded once. `update(id, ...)` is for corrections: same id, `updated_at` set.
- **Current facts** are those not superseded and not past their `valid_to`. Search, the
  list and the pinned block show current facts; `include_superseded=True` and the export
  show history too.
- **Forget is a hard delete** of the row and its index entry. As with every SQLite record,
  this is not forensic erasure of old database or WAL pages, backups or earlier chats.
- **Pause.** `set_paused(True)` stores a switch in the database (document
  `memory_facts_state`, DPAPI-protected). While paused, writes from automatic extraction
  (`origin="extractor"`) and from the brain's `memory_remember` (`origin="assistant"`) are
  refused with `memory_paused`. The owner's own edits, pins and deletes (`origin="owner"`,
  the `facts_*` routes) still work.
- **No secrets**, whoever writes (owner, assistant or extractor): text or subject that
  looks like a password, card number, ID number or key is refused with `memory_secret`.
  The patterns are simple and catch the common cases, not every case:
  - a 13 to 19 digit run (spaces or dashes allowed) that passes the Luhn check;
  - `sk-ant-` followed by 8 or more key characters (Anthropic keys);
  - `AIza` followed by 20 or more (Google API keys); `AQ.` followed by 16 or more (Google
    tokens);
  - "password / passcode / passwd / passphrase / kata laluan" followed by is, was, `=`, `:`,
    ialah or adalah and a value; "PIN is 1234" (4 or more digits);
  - a Malaysian IC number, `\d{6}-\d{2}-\d{4}`.
- Health and money matters are stored only when the owner said to remember them, and
  details about other people are kept minimal (the tool description says so; extraction
  will follow the same rules).
- Logs carry codes only: never fact text, subjects or queries.

## Search and ranking

`search(query, limit=8)` splits the query into words exactly as facts are indexed, hashes
them and asks FTS5 for `"h1" OR "h2" OR ...`. User text never reaches the FTS5 query
parser, so quotes, `*`, `-`, `+`, `^`, `NEAR`, `AND`, `OR`, `NOT`, column filters and
brackets have no effect (they are dropped or become ordinary words); there are no prefix
queries. Up to 200 candidates come back in BM25 order and are re-ranked:

```
relevance = -bm25(memory_facts_fts, 0, 2.0, 1.0)      # subject counts twice as much as text
score     = relevance * (1 + 0.5 * 0.5 ** (age_days / 90))
```

`age_days` counts from the fact's last edit (or its creation). A fact learned today gets up
to 1.5x, one 90 days old 1.25x, a very old one 1x: recency breaks near-ties but never
outweighs a clearly better match. Ties go to the older fact.

Other reads: `list(kind=None)` (newest first), `get(id)`, `pinned()` (pinned current facts,
profile first; the read path's profile block) and `export()` (JSON text: `format`,
`version`, `exported_at`, `paused`, `facts`, current and superseded).

## The brain's tools

All three need the authenticated desktop owner (a phone chat or another principal gets
`permission_denied`) and have a 10 s execution timeout.

- `memory_search(query)`: permission `memory_search`, default `False`, never asks. Answers
  `{facts: [{id, kind, subject, text, when}]}` (up to 8; `when` is the date the fact was
  learned or became valid).
- `memory_remember(text, kind = "preference", subject?)`: permission `memory_remember`,
  default `False`, never asks. Stores the fact with the turn's `conversation_id` as
  `source_conversation_id`, then sends `memory_remembered {text}` (at most 80 characters,
  cut with "…") to the owner's renderer sockets for a "Remembered" notice. Refused with a
  plain message for secret-like text and while memory is paused. Without a subject the first
  words of the text are used.
- `memory_forget(query | id)`: `always_ask`, so the owner approves every call (`"deny"`
  still turns it off). The approval card's review lists the facts that will go (`count`,
  and each fact's subject and text up to 80 characters): the fact with that id, or the
  facts `memory_search` would find for the query (up to 8). After approval exactly those
  facts are deleted, even if a new matching fact arrived meanwhile. No match is refused
  before any card.

## Owner routes (for the Preferences page)

`backend/transport/facts.py`. Each needs the authenticated, unlocked desktop owner renderer
and answers `{ok: true, ...}` or `{ok: false, code, message}`:

| route | request | answer |
| --- | --- | --- |
| `facts_list` | `{kind?}` | `{ok, paused, facts}` (current facts, full rows) |
| `facts_update` | `{id, text?, subject?, kind?, pinned?}` (one or more) | `{ok, fact}` |
| `facts_delete` | `{id}` | `{ok, deleted: id}` |
| `facts_pause` | `{paused}` | `{ok, paused}` |
| `facts_export` | `{}` | `{ok, count, json}` |

The exported JSON is private plaintext for the owner; the core writes nothing to disk for it.

## Tests

`tests/test_memory_facts.py`: schema, migration idempotence and the FTS5 check; encryption
at rest and a hash-only index; add, update, supersede and forget with the index in sync;
BM25 with recency; query sanitising; pinned; pause; secret patterns; the three tools; the
owner-only routes; export.
