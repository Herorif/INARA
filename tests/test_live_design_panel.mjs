import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import {
  DROP_MM, GHOST_MS, HIGHLIGHT_MS, MAX_STEPS, REVEAL_GAP_MS, REVEAL_MS,
  approvalCard, approvalLines, bannerVisible, bounds, buildPhase, calloutView, chipView, emptyTimeline, footerKind,
  formatNumber, ghostAlive, ghostFor, highlightMix, hudLine, latestStep, matchingApproval, nextTimeline, partMotion,
  pendingSteps, phaseRows, popupQueue, projectNote, revealProgress, revealQueue, sanitizeDesignSnapshot, snapshotPatch,
  studioDraft, summaryLine, unseenSteps, whoLabel,
} from '../src/features/liveDesign/model.js';
import { approvalView } from '../src/components/approvalView.js';
import { snapshotView } from '../src/overlay/overlayModel.js';

const require = createRequire(import.meta.url);
const policy = require('../electron/overlay-policy.cjs');

const ID = '7d0f8a52-3c1e-4b8e-9a51-0b6f2c9d4e11';
const part = fields => ({
  name: 'part', shape: 'box', width: 10, depth: 10, height: 10, thickness: 3,
  position: [0, 0, 0], rotation: [0, 0, 0], scale: [1, 1, 1], material: 'cyan', ...fields,
});
// The NAS case: an open shell, four amber drive bays 40 mm apart, then a change and an unsupported request.
const shell = part({ name: 'shell', shape: 'enclosure', width: 160, depth: 200, height: 180, material: 'titanium' });
const bay = i => part({ name: `drive bay ${i + 1}`, width: 150, depth: 190, height: 30, position: [5, 5, 3 + 40 * i], material: 'amber' });
const add = (n, index, object) => ({ n, who: 'jarvis', kind: 'add', title: `+ ${object.name}`, detail: 'box', added: [index], changed: [], removed: [], before: {}, undoable: n > 1 });
const startSteps = [add(1, 0, shell), ...[0, 1, 2, 3].map(i => add(i + 2, i + 1, bay(i)))];
const design = fields => ({
  id: ID, project: 'temp', name: 'NAS case', status: 'draft',
  recipe: { name: 'NAS case', shape: 'scene', engine: 'offline', objects: [shell, ...[0, 1, 2, 3].map(bay)] },
  steps: startSteps, job: null, updated: 1, ...fields,
});
const change = {
  n: 6, who: 'owner', kind: 'change', title: '“Make it 20 mm taller and add a stand”',
  detail: 'shell 180 → 200 mm tall · + stand 150 × 190 × 10 mm, cyan', added: [5], changed: [0], removed: [],
  before: { 0: shell }, undoable: true,
};
const unsupported = { n: 7, who: 'owner', kind: 'unsupported', title: '“Add holes for a fan on the back”', detail: 'not possible yet: the offline engine can’t cut holes', added: [], changed: [], removed: [], before: {}, undoable: false };

// --- bounds: the same examples as tests/test_live_design.py

test('the bounds port matches the core', () => {
  const stand = part({ width: 150, depth: 190, height: 10 });
  assert.deepEqual(bounds([{ ...stand, rotation: [0, 0, 90], scale: [2, 1, 1] }]), [190, 300, 10]);
  assert.deepEqual(bounds([shell, { ...stand, position: [5, 5, -10] }]), [160, 200, 190]);
  assert.deepEqual(bounds(design().recipe.objects), [160, 200, 180]);
  assert.equal(formatNumber(40.5), '40.5');
  assert.equal(formatNumber(160), '160');
  assert.equal(formatNumber(1.005e2), '100.5');
});

// --- snapshot validation

test('snapshots are validated, bounded and clipped', () => {
  assert.deepEqual(sanitizeDesignSnapshot({ design: null }), { design: null });
  const clean = sanitizeDesignSnapshot({ design: { ...design(), extra: 'x', name: `  NAS\u0000 ${'x'.repeat(80)}` } });
  assert.equal(clean.design.name.length, 60);
  assert.ok(clean.design.name.startsWith('NAS x') && clean.design.name.endsWith('…'));
  assert.equal('extra' in clean.design, false);
  assert.equal(clean.design.recipe.objects.length, 5);
  const many = Array.from({ length: 50 }, (_, i) => ({ ...unsupported, n: i + 1, title: 't'.repeat(200) }));
  const bounded = sanitizeDesignSnapshot({ design: design({ steps: many }) }).design;
  assert.equal(bounded.steps.length, MAX_STEPS);
  assert.equal(bounded.steps[0].n, 11);
  assert.equal(bounded.steps[0].title.length, 80);
  for (const bad of [
    null, [], {}, { design: 'x' }, { design: design({ status: 'done' }) }, { design: design({ id: '<b>' }) },
    { design: design({ recipe: { shape: 'box', objects: [] } }) },
    { design: design({ recipe: { shape: 'scene', objects: Array(9).fill(shell) } }) },
    { design: design({ recipe: { shape: 'scene', objects: [{ ...shell, width: 0 }] } }) },
    { design: design({ recipe: { shape: 'scene', objects: [{ ...shell, material: 'gold' }] } }) },
    { design: design({ steps: [{ ...unsupported, kind: 'delete' }] }) },
    { design: design({ job: { request_id: 5 } }) },
  ]) assert.equal(sanitizeDesignSnapshot(bad), null, JSON.stringify(bad)?.slice(0, 80));
  const job = sanitizeDesignSnapshot({ design: design({ status: 'building', job: { request_id: 'abc', state: 'running', phase: 'validating', error: null } }) });
  assert.deepEqual(job.design.job, { request_id: 'abc', state: 'running', phase: 'validating', error: null });
});

test('the first snapshot after a reload marks every step seen', () => {
  const first = snapshotPatch({ liveDesignReady: false }, { design: design() });
  assert.deepEqual(first.liveDesignSeen, { id: ID, n: 5 });
  assert.equal(unseenSteps(first.liveDesign, first.liveDesignSeen).length, 0);
  const later = snapshotPatch({ liveDesignReady: true }, { design: design() });
  assert.equal('liveDesignSeen' in later, false);
  assert.equal(snapshotPatch({}, { bad: 1 }), null);
  assert.equal(latestStep(design()), 5);
  // A new design shows all its steps; the same design only those after the last seen.
  assert.equal(unseenSteps(design(), { id: 'other', n: 9 }).length, 5);
  assert.deepEqual(unseenSteps(design({ steps: [...startSteps, change] }), { id: ID, n: 5 }).map(step => step.n), [6]);
});

// --- reveal queue

test('new parts reveal one at a time, 400 ms apart, in step order', () => {
  const queue = revealQueue(startSteps, 5, { start: 1000 });
  assert.deepEqual(queue.map(item => [item.n, item.index, item.at]), [[1, 0, 1000], [2, 1, 1400], [3, 2, 1800], [4, 3, 2200], [5, 4, 2600]]);
  assert.equal(REVEAL_GAP_MS, 400);
  assert.deepEqual(revealProgress(queue, 1850), { active: true, k: 3, n: 5, step: 3 });
  assert.deepEqual([...pendingSteps(queue, 1850)], [4, 5]);
  assert.equal(revealProgress(queue, 2600 + REVEAL_MS).active, false);
  // Reduced motion, a following change, or no adds: everything at once.
  assert.deepEqual(revealQueue(startSteps, 5, { start: 0, reducedMotion: true }), []);
  assert.deepEqual(revealQueue([...startSteps, change], 6, { start: 0 }), []);
  assert.deepEqual(revealQueue([unsupported], 5, { start: 0 }), []);
  assert.deepEqual(revealQueue(startSteps, 2, { start: 0 }).length, 2);
});

test('each part fades in and drops 8 mm over 300 ms', () => {
  assert.deepEqual(partMotion(undefined, 5), { opacity: 1, drop: 0 });
  assert.deepEqual(partMotion(100, 50), { opacity: 0, drop: DROP_MM });
  const half = partMotion(100, 250);
  assert.ok(half.opacity > 0.5 && half.opacity < 1 && half.drop > 0 && half.drop < 4);
  assert.deepEqual(partMotion(100, 400), { opacity: 1, drop: 0 });
});

test('the timeline: reveal, highlights and the first snapshot', () => {
  const first = nextTimeline(emptyTimeline(), startSteps, design(), { now: 0 });
  assert.equal(first.reveal.length, 5);
  assert.deepEqual(first.highlight[2], { from: 800, until: 800 + HIGHLIGHT_MS });
  assert.equal(first.ghost, null);
  // Nothing unseen: unchanged.
  assert.equal(nextTimeline(first, [], design(), { now: 10 }), first);
  // Reduced motion: no reveal, the newest step still highlights.
  const reduced = nextTimeline(emptyTimeline(), startSteps, design(), { now: 0, reducedMotion: true });
  assert.deepEqual(reduced.reveal, []);
  assert.deepEqual(Object.keys(reduced.highlight), ['4']);
  // A change highlights its changed and added parts for 1.2 s, then fades over the last 300 ms.
  const changed = nextTimeline(first, [change], design({ steps: [...startSteps, change] }), { now: 5000 });
  assert.deepEqual(changed.reveal, []);
  assert.deepEqual(changed.highlight[0], { from: 5000, until: 6200 });
  assert.deepEqual(changed.highlight[5], { from: 5000, until: 6200 });
  assert.equal(highlightMix(6200, 5500, 5000), 1);
  assert.ok(highlightMix(6200, 6050, 5000) > 0 && highlightMix(6200, 6050, 5000) < 1);
  assert.equal(highlightMix(6200, 6200, 5000), 0);
  assert.equal(highlightMix(6200, 4000, 5000), 0);
});

test('ghosts last 6 s and clear at the next step or on undo', () => {
  const ghost = ghostFor([change], 1000);
  assert.deepEqual(ghost, { n: 6, objects: [shell], until: 1000 + GHOST_MS });
  const withChange = design({ steps: [...startSteps, change] });
  assert.equal(ghostAlive(ghost, withChange, 6999), true);
  assert.equal(ghostAlive(ghost, withChange, 7000), false);
  assert.equal(ghostAlive(ghost, design(), 2000), false); // the change was undone
  // The next step clears it; a change with an unsupported part in the same batch keeps it.
  const timeline = nextTimeline(emptyTimeline(ID), [change], withChange, { now: 1000 });
  assert.equal(timeline.ghost.n, 6);
  assert.equal(nextTimeline(timeline, [unsupported], design({ steps: [...startSteps, change, unsupported] }), { now: 2000 }).ghost, null);
  assert.equal(nextTimeline(emptyTimeline(ID), [change, unsupported], withChange, { now: 0 }).ghost.n, 6);
  const removal = { ...change, before: {}, removed: [bay(0)] };
  assert.deepEqual(ghostFor([removal], 0).objects, [bay(0)]);
});

// --- labels

test('chip text for every state', () => {
  assert.deepEqual(chipView({ status: 'draft', reveal: { active: true, k: 3, n: 5 } }), { text: 'Drafting · 3 of 5', tone: 'accent' });
  assert.deepEqual(chipView({ status: 'draft' }), { text: 'Draft · not built', tone: 'muted' });
  assert.deepEqual(chipView({ status: 'draft', approval: true }), { text: 'Needs your approval', tone: 'warn' });
  assert.deepEqual(chipView({ status: 'building' }), { text: 'Building', tone: 'accent' });
  assert.deepEqual(chipView({ status: 'saved' }), { text: 'Saved', tone: 'ok' });
  assert.deepEqual(chipView({ status: 'failed' }), { text: 'Failed', tone: 'danger' });
});

test('footer kind, lines and phases for every state', () => {
  assert.equal(footerKind({ connected: false, status: 'draft', approval: true }), 'offline');
  assert.equal(footerKind({ connected: true, status: 'draft', approval: true }), 'approval');
  for (const status of ['draft', 'building', 'saved', 'failed']) assert.equal(footerKind({ connected: true, status }), status);
  assert.equal(summaryLine(design()), '5 parts · 160 × 200 × 180 mm · draft');
  assert.equal(summaryLine(design(), 'saved'), '5 closed parts · 160 × 200 × 180 mm');
  assert.deepEqual(approvalLines(design()), { title: 'Build “NAS case”?', detail: '5 parts · STL and GLB on this PC · about 10 s' });
  assert.deepEqual(['queued', 'building', 'validating', 'saving', 'blender', undefined].map(phase => buildPhase({ phase })), [1, 1, 2, 3, 3, 1]);
  assert.deepEqual(phaseRows({ phase: 'validating' }).map(row => row.state), ['done', 'active', 'pending']);
  assert.deepEqual(phaseRows({ phase: 'saving' }).map(row => row.label), ['Building geometry', 'Checking the solid', 'Saving exports']);
  assert.equal(hudLine('draft'), 'Draft blockout · not built');
  assert.equal(hudLine('failed'), 'Draft blockout · not built');
  assert.equal(hudLine('building'), 'Building on this PC');
  assert.equal(hudLine('saved'), 'Saved geometry · validated');
  assert.equal(projectNote(design(), 'temp'), '');
  assert.equal(projectNote(design(), null), '');
  assert.equal(projectNote(design(), 'Garage'), '· in temp');
  assert.deepEqual([whoLabel('owner'), whoLabel('jarvis')], ['YOU', 'JARVIS']);
});

test('callout text for every state', () => {
  assert.deepEqual(calloutView(design()), { text: '+ drive bay 4 · 150 × 190 × 30 mm', tone: 'primary' });
  assert.deepEqual(calloutView(design(), { step: 1 }), { text: '+ shell · 160 × 200 × 180 mm', tone: 'primary' });
  assert.deepEqual(calloutView(design({ steps: [...startSteps, change] })), { text: change.detail, tone: 'primary' });
  assert.deepEqual(calloutView(design({ steps: [...startSteps, change, unsupported] })), { text: unsupported.detail, tone: 'warn' });
  const long = { ...change, detail: 'x'.repeat(160) };
  assert.equal(calloutView(design({ steps: [long] })).text.length, 72);
  assert.deepEqual(calloutView(design({ status: 'saved', job: { request_id: '0123456789abcdef', state: 'succeeded', phase: 'ready', error: null } })), { text: 'Saved · revision 01234567', tone: 'ok' });
  assert.equal(calloutView(null), null);
});

// --- approvals

test('approvals match by design id; the visible panel answers its own', () => {
  const build = { id: 'a1', tool: 'build_live_design', args: { design_id: ID, summary: 'Build “NAS case”? 5 parts · STL and GLB on this PC' } };
  const other = { id: 'a2', tool: 'build_live_design', args: { design_id: 'other' } };
  const write = { id: 'a3', tool: 'write_file', args: {} };
  assert.equal(matchingApproval([write, other, build], ID), build);
  assert.equal(matchingApproval([write, other], ID), null);
  assert.equal(matchingApproval([build], null), null);
  assert.deepEqual(popupQueue([build, write], { panelVisible: true, designId: ID }), [write]);
  assert.deepEqual(popupQueue([build, other], { panelVisible: true, designId: ID }), [other]);
  assert.deepEqual(popupQueue([build, write], { panelVisible: false, designId: ID }), [build, write]);
  assert.deepEqual(approvalCard({ request: build, confirming: false, status: 'saved' }), { source: 'request', id: 'a1' });
  assert.deepEqual(approvalCard({ request: null, confirming: true, status: 'draft' }), { source: 'local', id: null });
  assert.deepEqual(approvalCard({ request: null, confirming: true, status: 'failed' }), { source: 'local', id: null });
  assert.equal(approvalCard({ request: null, confirming: true, status: 'building' }), null);
  assert.equal(approvalCard({ request: null, confirming: false, status: 'draft' }), null);
});

test('the approval popup has a live design layout', () => {
  const summary = 'Build “NAS case”? 5 parts · STL and GLB on this PC';
  assert.deepEqual(approvalView({ id: 'a', tool: 'build_live_design', args: { design_id: ID, summary, parts: 5 } }),
    { kind: 'live_design', title: 'Build live design', summary, approveLabel: 'Build', denyLabel: 'Not now', details: null });
  assert.equal(approvalView({ id: 'b', tool: 'build_live_design', args: {} }).details, null);
});

test('the banner shows only when the panel is out of sight and has news', () => {
  const d = design();
  assert.equal(bannerVisible({ design: d, seen: { id: ID, n: 5 }, panelVisible: false }), false);
  assert.equal(bannerVisible({ design: d, seen: { id: ID, n: 4 }, panelVisible: false }), true);
  assert.equal(bannerVisible({ design: d, seen: { id: 'old', n: 9 }, panelVisible: false }), true);
  assert.equal(bannerVisible({ design: d, seen: null, panelVisible: false }), true);
  assert.equal(bannerVisible({ design: d, seen: { id: ID, n: 4 }, panelVisible: true }), false);
  assert.equal(bannerVisible({ design: null, seen: null, panelVisible: false }), false);
});

test('the studio hand-off is a scene draft with copied parts', () => {
  const d = design();
  const draft = studioDraft(d);
  assert.equal(draft.shape, 'scene');
  assert.equal(draft.engine, 'offline');
  assert.equal(draft.name, 'NAS case');
  assert.deepEqual(draft.objects, d.recipe.objects);
  assert.notEqual(draft.objects[0].position, d.recipe.objects[0].position);
});

// --- the talking overlay while designing

test('the overlay offers Open JARVIS while JARVIS designs', () => {
  const snap = fields => ({ session: 's1', state: 'speaking', user: 'hi', user_final: true, jarvis: 'Placing the shell.', jarvis_final: false, approval: false, design: false, end: null, ...fields });
  assert.equal(snapshotView(snap()).showOpen, false);
  assert.equal(snapshotView(snap({ design: true })).showOpen, true);
  assert.equal(snapshotView(snap({ approval: true })).showOpen, true);
  assert.equal(snapshotView(snap({ design: true, state: 'ended', end: { kind: 'now', message: null } })).showOpen, false);
  assert.equal(policy.sanitizeSnapshot(snap({ design: true })).design, true);
  assert.equal(policy.sanitizeSnapshot(snap({ design: 'yes' })).design, false);
  const { design: _drop, ...missing } = snap();
  assert.equal(policy.sanitizeSnapshot(missing).design, false);
});
