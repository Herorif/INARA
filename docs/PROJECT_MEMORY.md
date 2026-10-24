# Project memory

The first post-revamp implementation is complete: an owner-reviewed project memory collection with local search, editable provenance, expiry, archive, forget, encrypted backup/recovery and optional bounded assistant context. No provider configuration, dependencies, model downloads, real phone notifications or physical-device setup was performed.

## Use

Open **Project memory** from the Command quick-launch row or command palette. New memory records a fact, preference or design decision, with a title, note, source and optional tags. Preferences remain project-specific. Saving is explicit; chats, files, phone notifications and creative jobs are never automatically mined for memories.

Each note shows its source, version counter, creation/update times, expiry and assistant-sharing state. Editing corrects the current note and increments its version; previous note bodies are not retained as an edit-history archive. Archive removes the note from ordinary search/assistant retrieval while keeping it available through Show archived notes. Forget requires a concrete note review and removes it from the live collection.

The project retention limit defaults to 90 days, configurable from one to 365. Notes can choose a shorter duration. Shortening the project limit shortens existing expiry; increasing it never silently extends notes. Saving an edit explicitly renews that note's duration under the current project limit. Archived notes still expire and count toward capacity. Logical expiry runs during reads and at startup/every minute through an owned core task, even with the workspace closed.

## Assistant use and sources

Assistant sharing is **off by default for every note**. Checking the consent box permits relevant excerpts to reach the configured AI provider during a desktop typed or reviewed-speech request. The normal source/permission policy still governs all tools. No model-facing memory write/forget/export tools or Android memory grants were added.

Retrieval uses Unicode-normalized local word matching, title/tag weights and document-frequency scoring. It is lexical search, not embedding-based semantic search; synonyms without shared words are not guaranteed to match. No embedding model, vector database, plaintext index, background inference or provider call is needed to save/search notes. The bounded collection is searched on demand rather than introducing another index/migration/cache authority.

Only unarchived, unexpired, explicitly enabled notes participate. At most four notes and approximately 6 KB of serialized reference data are selected per provider step. The current user-message copy contains clearly labeled untrusted reference data; original user text, tool call ordering and durable request IDs remain intact. Memory data is never inserted into system instructions as authority, never grants permission and is not saved as an extra raw context message in chat history.

Authorization and the collection revision are checked again after each provider response, before an answer or proposed tool call is accepted. Forget, expiry, edit, archive or sharing changes during a pending request reject its stale result. This cannot retract data already transmitted to a configured provider. Replies show the titles/versions of memory excerpts **supplied as context**; these labels do not prove that the model used every excerpt correctly. Source metadata survives protected conversation restoration. Earlier answers and source labels remain historical records when a live note is forgotten.

## Protected storage and recovery

Each owner/resolved-project collection occupies an independently scoped DPAPI-protected document in the existing SQLite database. There are at most 200 notes and a 750,000-byte serialized item budget per collection. Notes are bounded to 4,000 characters, titles to 100, sources to 200 and tags to eight short strings. No plaintext search index or project memory file is written by this feature. Locked/foreign/resident/control channels cannot use the seven direct memory routes. R7/R8 mobile access remains separate.

Writes, forget, retention changes and restore use collection revision checks in transactions. Stale requests cannot overwrite a newer correction or silently replay a forgotten note. The UI binds an edit to the revision captured when editing began, clears unsent state on disconnect/project change, drops late acknowledgements and never automatically retries mutations.

Protected backup downloads an encrypted `.dpapi` file. Recovery requires the original Windows user profile and project scope; this is **not a portable cross-account recovery key workflow**. Preview decrypts and validates the backup, shows only missing/unexpired notes, checks count/byte capacity and creates a bounded two-minute review token. Apply requires that token and the unchanged collection revision. Existing notes are never overwritten. Restored copies start at version one, with fresh creation/update times, the original text/source and a bounded original expiry; **assistant sharing is always reset to off**. Reviewed restore can deliberately recover a previously forgotten note from a retained backup.

Forget/expiry remove live collection data logically. They do not promise forensic erasure of encrypted SQLite/WAL/migration backups, earlier conversations, exported files or provider-side copies. User-visible controls explain that earlier chats and backup copies are separate. Existing legacy `save_memory` transcript exports remain a separate compatibility path and are neither imported nor represented as protected project notes.

## Implementation and verification

Contracts live in `backend/services/memory_contracts.py`; `project_memory.py` owns collection/search/context/recovery; `transport/memory.py` owns strict renderer acknowledgements. Generated schemas/types and the scoped client feed the lazy JARVIS panel. Conversation and reviewed speech share the same optional retrieval integration. The existing common dispatcher, approvals, protected conversations/reminders, mobile grants and creative resource controls remain authoritative.

The supported regression suite passed 865 Python checks with one Blender skip, and all 72 Node checks passed. Final memory/conversation/speech checks also cover the provider-message ordering refinement and reviewed-speech source metadata. Types, generated-contract drift, Ruff and the production build pass; no hosted CI run is claimed. Deterministic tests cover ownership/roles/lock, project boundaries, strict limits, protected persistence/restart, ranking, stale writes, expiry/clock rollback, archive, backup scope/preview expiry/conflicts, capacity rollback, consent, bounded provider context, source persistence and forget during a request. No paid provider calls or real user data are involved.

Actual hidden Electron/native-host acceptance exercised save/edit/search, encrypted download, forget, recovery preview/apply with sharing off, re-enabling a reviewed note, a fixture assistant answer with visible citation, retention controls and workspace/core cleanup. Desktop and 390px captures are in `docs/qa/project-memory-*`. Resident working set was about 65 MB before opening and 68 MB after closing in the short fixture run. No heavy model modules loaded; the mobile listener remained off. This is not a long-run hardware/game benchmark or real provider-quality evaluation.

Optional embedding retrieval, cross-account encrypted recovery keys, global owner preferences and automatic memory proposals are separate future capabilities. The next planned source implementation is usage budgets and repeatable assistant/CAD/image quality evaluations. Existing Android, signing/distribution, device/provider and game deferrals remain unchanged.
