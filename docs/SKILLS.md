# Skills (S5.2)

A skill is a short set of instructions JARVIS loads when a request fits it, such as how the
owner likes a day planned. JARVIS lists every skill in its system prompt, one line each, and
reads a skill's full instructions only when it needs them.

Code: `backend/services/skills.py` (format, library, index, brain tools),
`backend/transport/skills.py` (owner-only routes), `src/components/approvalView.js` (the
"Teach JARVIS" card). Wiring: `backend/application.py` (`SkillLibrary`, `SkillsTransport`,
`conversation.skill_index`). Tests: `tests/test_skills.py`, `tests/test_skills_card.mjs`.

## Format

Skills use the open Agent Skills folder layout:

```
<slug>/
  SKILL.md        front matter, then Markdown instructions
  scripts/        optional; listed, never run (see "Scripts")
```

```markdown
---
name: plan-my-day
description: "Plan the owner's day from their calendar, reminders and the weather. Use when they ask to plan today or tomorrow."
---

# Plan my day
...
```

Limits, checked on every read and every save:

| | |
| --- | --- |
| slug (the folder name) | `[a-z0-9-]{1,48}` |
| `name` | required, one line, at most 64 characters |
| `description` | required, one line, at most 300 characters |
| instructions (the body) | required, at most 20,000 characters |
| file | UTF-8 (a leading BOM is allowed), at most 256 KiB, a plain file (no links) |

The core has no YAML library, so the front matter is a strict subset: one `key: value` per
line; plain, `"double-quoted"` (escapes `\" \\ \/ \n \t \r \uXXXX`) or `'single-quoted'`
(`''` for a quote) values; `#` comment lines and trailing ` # comments`. Nested values,
lists, multi-line values, a plain value containing `: ` or starting with a YAML symbol, and
a key given twice are refused. Keys other than `name` and `description` (for example
`license`) are read and ignored. A folder that breaks any rule is skipped with a warning
that names only the reason, never its content. Folders that are links or junctions are
ignored. At most 100 skills are read from each location.

## Locations

- `<user data>\skills\<slug>\SKILL.md`: the owner's skills ("yours"), beside the core's
  database (the folder the memory mirror uses).
- `<repo>\skills\<slug>\SKILL.md`: shipped with JARVIS ("built-in"). JARVIS ships one,
  `plan-my-day`: how to build a day plan from `calendar_events`, `list_reminders` and
  `weather`.

An owner skill overrides a built-in skill with the same slug. JARVIS re-reads the folders
only when something changed: before each turn it stats each `SKILL.md` and `scripts`
folder, which costs a directory listing and a few file stats.

## The index

After the persona, the system prompt carries:

```
Skills you can load with load_skill (load one when a request fits it, then follow its instructions):
- plan-my-day: Plan the owner's day from ...
```

There is one line per skill, sorted by slug, and the index is left out when there are no
skills. It depends only on each skill's slug and description, so the cached system prompt
(S6.3's explicit cache breakpoint on the static system block) stays byte-identical from turn
to turn. It changes only when a skill is added, removed or given a new description. Editing a
skill's instructions changes nothing in the prompt. Phone chat has no tools, so it gets no
index.

## Brain tools

- `load_skill {name}`: never asks (`load_skill: False` by default; deny still disables it).
  It accepts the slug, a name that turns into the slug, or the skill's name. It returns
  `{skill, name, instructions}`, the body without the front matter. A skill with a `scripts`
  folder also returns the file names and a note that they are not run. It is not untrusted
  output: an owner skill is the owner's own text, a built-in one is JARVIS's. It is a core
  tool, so it stays loaded when tool search defers others.
- `teach_skill {name, description, instructions}`: "Teach JARVIS". When the owner says
  "remember how to do this", JARVIS writes the skill up and the owner approves it on screen.
  - `always_ask`: every save asks, whatever the stored policy.
  - The card ("Teach JARVIS a skill?", "Save skill" / "Not now") shows the exact `SKILL.md`
    that will be written, in a monospace block.
  - The slug comes from the name ("Gym bag" becomes `gym-bag`). A slug that belongs to a
    built-in skill is refused before any card (`skill_built_in`, "Pick another name"). Saving
    over one of the owner's own skills says "Replaces your existing skill <slug>." on the
    card.
  - `outward`: after the turn has read untrusted content (a web page, an email), the card
    carries the taint line, so a page can't quietly plant a skill.
  - On approve, JARVIS writes `SKILL.md.partial` and then swaps it in atomically. The index
    changes on the next turn.

Both tools are for the authenticated desktop owner only.

## Owner routes

| route | |
| --- | --- |
| `skills_list` | `{ok, skills: [{slug, name, description, source: "yours" \| "built-in", path, scripts}]}`, sorted by slug |
| `skills_delete {slug}` | deletes one of the owner's skill folders; built-in skills can't be deleted |

Both need the authenticated, unlocked owner renderer (see `docs/ROUTE_POLICY_MATRIX.json`).

## Scripts

JARVIS never executes anything from a skill folder. `scripts/` is listed (at most 50 file
names, no links followed) and its files are never read or run. A script runs only if the
owner wants it, through JARVIS's existing approved local-action paths, which ask on screen
as usual. Skills add no new way to run code.

## Why there is no skill marketplace

JARVIS does not download skills, has no registry and never installs anything automatically.
Every skill is a file the owner wrote, approved on a "Teach JARVIS" card, or that ships with
JARVIS. An audit of public agent skills found 341 of 2,857 to be malicious. A skill is
instructions the brain follows, so a hostile one is a prompt injection with a head start.
