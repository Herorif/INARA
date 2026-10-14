# Durable sessions and reminders

The supported Windows backend uses `%LOCALAPPDATA%\INARA\data-v1\assistant.sqlite3`. `INARA_DATA_DIR` optionally selects an isolated development location. Tests always select temporary storage before server import. Projects and existing artifacts stay in their original directories; the selected project is persisted separately. API credentials are unnecessary for storage and reminder delivery.

## Private storage

Private JSON is encrypted with Windows user-bound DPAPI before SQLite receives it. This covers typed histories, request text/results/errors, reminder tasks, routines, delivery snapshots, workspace selection, new legacy voice chat and migration backups. UUIDs, hashed scope identifiers, record kinds, schema version and migration hashes remain metadata. WAL mode is enabled with full synchronous commits. No pickle, executable object serialization, SQLCipher claim or plaintext encryption fallback is used.

DPAPI normally binds decryption to the same Windows account and machine. Copying this database alone is not a portable backup. Keep the Windows account recovery environment and the data directory together; design explicit encrypted export and device keys before Android sync. This does not protect data from a process already running as the same logged-in Windows user. Existing source records, settings, credentials and creative artifacts are preserved in their original formats; this milestone does not retroactively encrypt all project files. [Microsoft DPAPI example](https://learn.microsoft.com/en-us/windows/win32/SecCrypto/example-c-program-using-cryptprotectdata).

## Sessions

Sessions are bound to a stable desktop client identity and resolved project path. The UI retains only identity UUIDs in localStorage; private chat text stays in memory and protected backend storage. Reopening restores up to twenty completed text messages. Signed provider tool content remains transient within the active request and is never serialized as an SDK/Python object.

Each request is committed to the ledger before provider/tool execution. A completed duplicate returns its stored result or error. Reusing its ID with different text is rejected. An interrupted/running record is never automatically replayed; concurrent requests from another service cannot overwrite that conversation's history. After checking any effects, the user can choose **New chat**. This preserves the previous ledger. Request identities are retained; archival/retention controls and a full conversation browser are future work. The legacy voice and typed histories remain separate adapters.

## Migration and recovery

On first opening, legacy `backend/reminders.jsonl` and `backend/routines.json` are snapshotted into immutable encrypted backups, fully validated, then imported in one transaction. The source files are never rewritten or deleted. Project `chat_history.jsonl` imports on first session restoration. Conflicting IDs, invalid records, unsupported schemas and inaccessible protected data fail visibly rather than silently dropping records. Failed transactions leave no partial import or completed migration marker. Repair a copy of an invalid source, review it, replace the source deliberately, and retry. Migration markers prevent repeated imports; later edits to already-imported JSON are not live database edits.

Each legacy file is limited to 16 MiB for this importer. Larger files remain untouched and require a reviewed split/import. Links outside their source scope are rejected. Empty/missing reminder sources do not create a migration marker prematurely.

To recover a source snapshot, on the original Windows account, use an explicit new destination:

```powershell
.\.venv\Scripts\python.exe scripts/recover-storage.py "<data-dir>\migration-backups\<backup>.dpapi" "<new-recovery-file>"
```

The command validates its context and refuses to overwrite an existing destination. Its output is private plaintext. For a database backup, stop the backend before copying the entire data directory; do not copy just the main SQLite file while writes are active.

## Reminder delivery

A single `BEGIN IMMEDIATE` transaction claims due reminders, creates a deterministic occurrence delivery ID, and updates the schedule. It commits before network emission. Concurrent pollers see the same durable claim; notification transport is deliberately outside the transaction. Delivery leases expire after thirty seconds, allowing the same ID to retry if emission or receipt fails. The UI acknowledges receipt, deduplicates transport repeats and queues simultaneous alerts. Dismissal is a separate durable completion. Reconnect snapshots restore received but unfinished alerts. [SQLite transactions](https://www.sqlite.org/lang_transaction.html).

The first connected authenticated local client identity owns a new delivery. That identity persists with the delivery; retries cannot switch recipients. Multiple windows sharing that identity receive state snapshots. This is a local desktop ownership rule, not phone pairing or cross-device notification election. A cleared/replaced browser identity requires explicit future recovery/reassignment rather than disclosing previous sessions or silently retargeting alerts.

Snooze and cancellation retire outstanding deliveries and increment the reminder revision. An old acknowledgement or alert action cannot finish a newer reminder revision. Completion of a recurring occurrence does not cancel its next schedule. Direct snooze/cancel and typed reminder tools use the shared validated tool dispatcher and configured permission rules. Receipt and completion require the delivery's authenticated recipient.

## CAD job records

New CAD jobs use encrypted documents scoped to the desktop owner, resolved project path and request UUID. Recipe, state, errors and artifact metadata are protected before SQLite writes. Completed duplicate requests return their stored status; conflicts reject reuse, and interrupted claims are preserved without replay. A storage failure after a claim releases the worker and leaves the request uncertain. Project artifacts/recipes remain ordinary files in separate revision directories. See [CAD Studio lifecycle and limits](CAD_STUDIO.md).

## Time policy

Reminder instants are UTC epoch seconds plus an IANA timezone and preserved local wall clock. The default is `Asia/Kuala_Lumpur`. Daily, weekly and weekday recurrence follows local calendar dates. Missed occurrences coalesce into one overdue alert; the next schedule advances to a future date, avoiding a backlog of historical alerts. A nonexistent DST wall time advances to the first valid minute, and an ambiguous wall time uses the first occurrence (`fold=0`). A DST-adjusted occurrence does not shift the following day's original clock time. The installed `tzdata` dependency supplies IANA data on Windows. [Python zoneinfo](https://docs.python.org/3/library/zoneinfo.html).

The laptop must be awake and the backend running to emit reminders. Resident window lifetime, OS wake scheduling, Android offline scheduling, retention controls and resource measurements belong to subsequent milestones.

Scene assembly reuses the same scoped CAD documents and immutable artifact revisions. Old single-solid recipes normalize optional scene/engine defaults for deduplication without rewriting stored data. See [Scene Studio](SCENE_STUDIO.md).
