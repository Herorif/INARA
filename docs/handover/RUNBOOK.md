# Runbook — "continue finishing jarvis"

This is the protocol for building everything left in JARVIS in one unattended run. It is
written for any capable model. Follow it literally. Do not re-plan, re-research or change
a decision; the decisions are in `9NovWork.md` section 3 and the owner's answers in
section 5.

Files: `9NovWork.md` (index) · `PROGRESS.md` (ordered tasks, the source of truth for
"what is next") · `9NovWork-specs.md` (how to build each item) · `9NovWork-audit.md`
(why; needed only for UI work).

---

## 1. What "done" means for this run

Every task in `PROGRESS.md` is either ticked with a commit hash, or marked blocked with a
reason. All code is built and tested with fakes. Things only the owner can do (hardware,
accounts, pairing, the live check) are prepared and listed in the owner checklist at the
bottom of `PROGRESS.md`. The run cannot prove live behaviour; say so plainly in the final
report.

## 2. Start of every session (first start and every resume)

1. Read `9NovWork.md`, then `PROGRESS.md`. The next task is the first unticked line whose
   dependencies are ticked.
2. Check the tree: `git status --short` must show only `?? .claude/`. If a task was left
   half-done, finish it or `git restore` it; never build on a red tree.
3. Baseline once per session: `ruff check`, then the fast test subset for the area you
   are about to touch. Run the full `pytest` at the end of each wave, not at each start.
4. **Launch approvals (first session only, one message).** Ask the owner once for:
   - the download list in section 6 below, with each file name, source and size measured
     just before asking (helpers in `docs/handover/tools/`);
   - nothing else. The design gate, WhatsApp, Telegram and the modem route are already
     decided in `9NovWork.md` section 5.
   If the owner does not answer or declines an item, use that item's fallback from
   section 6 and carry on. Never download anything that was not approved in this session.

## 3. The task loop

For each task, in ledger order:

1. Read its spec section. Read nothing else unless the spec points to it.
2. **Verify before you code.** Any fact tagged `[recall]` or `[web]`, and every external
   API, is checked first: introspect the installed package (`python -c "import x;
   help(x.y)"`, the package's README under `node_modules`), or read the official docs
   page. For the Claude API, load the `claude-api` skill and read the files the spec
   names. Never guess an SDK call. Write any difference from the spec under
   "Deviations" in `PROGRESS.md` and follow the real API.
3. Write the tests named in the ledger first, with fakes.
4. Build, following the pattern card (`9NovWork-specs.md` section 0).
5. Check, in this order: `ruff check` → the tests for the touched area → for UI work the
   client tests, `eslint`, `tsc` and `npm run build` (CSP intact) → for a new screen, the
   harness and captures under the QA lock into `.runtime/ui-qa/<feature>/`.
6. Update the feature's page in `docs/`, the route policy matrix, settings defaults and
   patch keys, as the pattern card says.
7. One local commit for the task, in the style of the existing history, ending with the
   session's co-author line. Never push.
8. Tick the ledger line with the commit hash and commit the ledger with the next task
   (or alone at a wave end).

At the end of each wave: full `pytest`, client tests, build. The wave is not finished
until they pass. The known flaky test
`test_legacy_cad_isolation::test_cancellation_kills_the_child_tree` may be re-run alone
once before counting as a failure.

## 4. When something does not work

- Two real attempts with different approaches. Then mark the line
  `- [!] … BLOCKED: <one-line reason, what was tried>`, restore the tree for that task,
  and move to the next task whose dependencies are met.
- A task that needs an unapproved download uses its fallback (section 6) or is marked
  `BLOCKED: download`.
- A task whose library turns out not to exist for Python 3.13 or Windows is marked
  blocked with the evidence; do not substitute a different library without a line under
  "Deviations" explaining the choice.
- Never weaken a safety rule to get a test green (approvals, taint, consent, secrets).
- If the full suite goes red and the cause is not found in two attempts, revert the last
  task's commit with a new revert commit, mark it blocked, and continue.

## 5. Things this run must never do

- Push, or change any system setting, or install drivers.
- Start the owner's live JARVIS, bind port 8000, or stop the dev server on 5173.
- Open a real microphone, speaker or camera in a test.
- Print, log or pass a key on a command line.
- Send any real message, place any real call, pair WhatsApp, create any account, or
  spend API credit on evals or live checks without the owner's OK in that session.
- Add the word INARA anywhere except in existing paths and the migration code.
- Download third-party code from inside the app.

## 6. Downloads to approve at launch, and the fallback for each

Measure sizes just before asking:
- npm: write a throwaway `package.json` in the scratchpad and run
  `npm install --package-lock-only --ignore-scripts` there with the portable Node 24
  (it resolves versions from registry metadata and downloads no packages), then
  `python -I docs/handover/tools/npm_lock_sizes.py <package-lock.json>`.
- pip: in the target venv run `python -m pip install --use-feature=truststore --dry-run
  --ignore-installed --quiet --report <report.json> <packages>`, then
  `python -I docs/handover/tools/pip_sizes.py <report.json>`.

| For | Package (source) | Fallback if not approved |
|---|---|---|
| S13a | npm `motion`, `@fontsource-variable/saira` (registry.npmjs.org) | CSS transitions and the Web Animations API; keep Inter for display text. |
| S13a | npm `uplot` | Hand-drawn SVG sparklines. |
| S13a | npm `@react-three/postprocessing` | The additive glow sprite only (this is the default anyway). |
| S8b | npm `@whiskeysockets/baileys` and its dependencies | Build 8a (Telegram) and the channel gateway; mark 8b–8c `BLOCKED: download`. |
| S9 | pip `pyserial` (pypi.org) | Build the seam and the Twilio wrapper; mark the modem transport blocked. |
| S6 v2 | pip `sqlite-vec`, `fastembed`, one embedding model | Stay on FTS5 (v1). This is acceptable as final. |
| S10b | pip `livekit` (or another WebRTC audio-processing wheel for cp313 win_amd64) | Keep wake-word barge-in; mark 10b blocked. |
| S10d | pip `sherpa-onnx` and models | Skip; 10d is owner-deferred anyway. |
| S11 | a Windows control MCP server; pip `mss` | Build S11.0 (screen help) only; mark 11.1–11.2 blocked. |
| S14 | pip `markitdown`; npm `@playwright/mcp` and Chromium | Index plain text and Markdown only; keep the existing web agent. |

Nothing else in the plan needs a download. `nvidia-ml-py` for GPU vitals is optional:
without it the Systems rail shows CPU, memory and disk from `psutil` (installed).

## 7. The design rule for this run

The owner asked for one uninterrupted run, so the usual "show a mockup and wait" gate is
replaced by this: build UI to the S13 spec and the direction in the audit (section B),
keep every existing reduced-motion, gaming-mode and low-battery switch, and save captures
of every new or changed screen. List the captures in the final report so the owner can
review them afterwards and ask for changes. If the owner says at launch that they want to
approve designs first, follow them.

## 8. Using workers

If the session was started through the savvy-flow orchestrator, use workers by the tier
on each ledger line (L light, M medium, C careful, H heavy): the task title goes verbatim
into the brief; the brief names the spec section, the files, the acceptance tests and the
rules in section 5; review each result adversarially, at most two return rounds; stage
only each worker's hunks when workers share a file; check each commit in a temporary
worktree. Tasks in the same wave that touch different files may run in parallel. If the
session was not started that way, build inline with the same loop.

## 9. Usage limits

A break can happen at any time. That is why the ledger is ticked after every commit. On
return the owner says "continue finishing jarvis" again; start at section 2.

## 10. The final report

When no unticked, unblocked task is left:
1. Full verification on the final tree; record the numbers.
2. Update `docs/IMPLEMENTATION_STATUS.md` and the memory note.
3. Report to the owner: what was built (by wave), what is blocked and why, the captures to
   review, the owner checklist from `PROGRESS.md`, and a plain statement that nothing was
   verified live.
