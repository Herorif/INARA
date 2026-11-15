import test from 'node:test';
import assert from 'node:assert/strict';
import {
  FLASH_MS, GLB_CACHE_SIZE, PAUSED_TEXT, STARTING_TEXT, UNAVAILABLE_TEXT, UPDATING_TEXT,
  artifactMatches, boxFraming, createGlbCache, createLoadSequencer, cubicCentimetres, factsBox, factsLine,
  flashFor, kernelPreview, previewChip, sanitizePreview, shouldRefit, stableFraming, wantedGlb, warningRows,
} from '../src/features/liveDesign/liveDesignKernelModel.js';
import { HIGHLIGHT_MS, sanitizeDesignSnapshot } from '../src/features/liveDesign/model.js';

const SHA = 'a'.repeat(64), SHA2 = 'b'.repeat(64);
const RID = '6f1c2d3e-4b5a-5c6d-8e7f-0a1b2c3d4e5f';
const facts = { volume_mm3: 11538.63, bbox_mm: [60, 40, 5], min_mm: [-30, -20, 0], faces: 14, edges: 36, solids: 1, valid: true };
const preview = fields => ({
  engine: 'kernel', state: 'ready', message: null, current: true,
  glb: { request_id: RID, format: 'glb', bytes: 28756, sha256: SHA }, facts, warnings: [], seconds: 0.09, cached: false, ...fields,
});

test('the preview contract: kernel only, malformed parts dropped one by one', () => {
  assert.deepEqual(sanitizePreview(preview()), preview());
  assert.equal(sanitizePreview(null), null);
  assert.equal(sanitizePreview(preview({ engine: 'box' })), null);
  assert.equal(sanitizePreview(preview({ state: 'exploded' })), null);
  assert.equal(sanitizePreview(preview({ glb: { ...preview().glb, sha256: 'xyz' } })).glb, null);
  assert.equal(sanitizePreview(preview({ glb: { ...preview().glb, request_id: '../etc' } })).glb, null);
  assert.equal(sanitizePreview(preview({ glb: { ...preview().glb, bytes: 0 } })).glb, null);
  assert.equal(sanitizePreview(preview({ facts: { ...facts, bbox_mm: [1, 2] } })).facts, null);
  assert.equal(sanitizePreview(preview({ facts: { ...facts, min_mm: null } })).facts.min_mm, null);
  const clean = sanitizePreview(preview({ message: `  bad\u0000 ${'x'.repeat(400)}`, current: 'yes', warnings: [{ code: 'no_effect', index: 2, message: 'Hole 1 doesn’t change the part.' }, { message: '' }, 7, ...Array(10).fill({ code: 'w', message: 'm' })] }));
  assert.equal(clean.message.length, 300);
  assert.ok(clean.message.startsWith('bad x'));
  assert.equal(clean.current, false);
  assert.equal(clean.warnings.length, 6); // the first 8 entries, of which 2 are malformed
  assert.deepEqual(clean.warnings[0], { code: 'no_effect', index: 2, message: 'Hole 1 doesn’t change the part.' });
});

test('the design snapshot keeps a valid preview and omits it on the box path', () => {
  const part = { name: 'plate', shape: 'box', width: 60, depth: 40, height: 5, thickness: 3, position: [0, 0, 0], rotation: [0, 0, 0], scale: [1, 1, 1], material: 'titanium' };
  const design = fields => ({ id: '7d0f8a52-3c1e-4b8e-9a51-0b6f2c9d4e11', project: 'temp', name: 'Plate', status: 'draft', recipe: { name: 'Plate', shape: 'scene', engine: 'offline', objects: [part] }, steps: [], job: null, updated: 1, ...fields });
  assert.equal('preview' in sanitizeDesignSnapshot({ design: design() }).design, false);
  assert.equal('preview' in sanitizeDesignSnapshot({ design: design({ preview: { engine: 'box' } }) }).design, false);
  const kept = sanitizeDesignSnapshot({ design: design({ preview: preview() }) }).design;
  assert.deepEqual(kept.preview, preview());
  assert.equal(kernelPreview(kept), kept.preview);
  assert.equal(kernelPreview(design()), null);
  assert.deepEqual(wantedGlb(kept.preview), { request_id: RID, sha256: SHA, bytes: 28756 });
  assert.equal(wantedGlb(preview({ glb: null })), null);
});

test('chip text per state', () => {
  assert.equal(previewChip(null), null);
  assert.equal(previewChip(preview()), null);
  assert.deepEqual(previewChip(preview({ state: 'starting', message: STARTING_TEXT, current: false })), { text: 'Starting the CAD engine…', tone: 'accent' });
  assert.deepEqual(previewChip(preview({ state: 'starting', message: null, current: false })), { text: STARTING_TEXT, tone: 'accent' });
  assert.deepEqual(previewChip(preview({ state: 'building', current: false })), { text: UPDATING_TEXT, tone: 'accent' });
  assert.equal(UPDATING_TEXT, 'Updating…');
  assert.equal(previewChip(preview({ state: 'building', current: true })), null);
  assert.deepEqual(previewChip(preview({ state: 'failed', message: 'A 3 mm fillet does not fit a 4 mm edge', current: false })), { text: 'A 3 mm fillet does not fit a 4 mm edge', tone: 'warn' });
  assert.equal(previewChip(preview({ state: 'failed', message: null, current: false })).tone, 'warn');
  assert.deepEqual(previewChip(preview({ state: 'paused', current: false })), { text: 'Paused in gaming mode', tone: 'muted' });
  assert.equal(PAUSED_TEXT, 'Paused in gaming mode');
  assert.deepEqual(previewChip(preview({ state: 'unavailable', message: 'The CAD engine isn’t installed (.venv-cad is missing).', current: false })), { text: 'The CAD engine isn’t installed (.venv-cad is missing).', tone: 'muted' });
  assert.equal(previewChip(preview({ state: 'unavailable', message: null })).text, UNAVAILABLE_TEXT);
});

test('facts line: mm³ to cm³ with one decimal, sizes as the panel prints them', () => {
  assert.equal(factsLine(facts), 'Volume 11.5 cm³ · 60 × 40 × 5 mm');
  assert.equal(factsLine({ ...facts, volume_mm3: 11600 }), 'Volume 11.6 cm³ · 60 × 40 × 5 mm');
  assert.equal(factsLine({ ...facts, volume_mm3: 12000, bbox_mm: [60.25, 40.5, 5.123] }), 'Volume 12.0 cm³ · 60.25 × 40.5 × 5.12 mm');
  assert.equal(cubicCentimetres(49), '0.0');
  assert.equal(cubicCentimetres(50), '0.1');
  assert.equal(cubicCentimetres(1234567), '1234.6');
  assert.equal(factsLine(null), null);
  assert.deepEqual(warningRows(preview({ warnings: [{ code: 'no_effect', index: 1, message: 'Fillet doesn’t change the part.' }] })), [{ key: 'no_effect:1:0', text: 'Fillet doesn’t change the part.' }]);
  assert.deepEqual(warningRows(null), []);
});

test('refit thresholds: holes and fillets keep the view, a real resize refits', () => {
  const plate = boxFraming(factsBox(facts));
  assert.deepEqual(plate.center, [0, 0, 2.5]);
  assert.equal(plate.floor, 0);
  assert.ok(Math.abs(plate.radius - Math.hypot(60, 40, 5) / 2) < 1e-9);
  assert.equal(shouldRefit(null, plate), true);
  assert.equal(shouldRefit(plate, null), false);
  const same = boxFraming({ min: [-30, -20, 0], size: [60, 40, 5] });
  assert.equal(shouldRefit(plate, same), false);
  // An embossed 0.6 mm text and a 1 mm offset: small next to the 60 mm side.
  assert.equal(shouldRefit(plate, boxFraming({ min: [-30, -20, 0], size: [60, 40, 5.6] })), false);
  // A side grows by 12 mm = 20 % of 60: not more than 20 %, so no refit; 13 mm refits.
  assert.equal(shouldRefit(plate, boxFraming({ min: [-30, -20, 0], size: [72, 40, 5] })), false);
  assert.equal(shouldRefit(plate, boxFraming({ min: [-30, -20, 0], size: [73, 40, 5] })), true);
  assert.equal(shouldRefit(plate, boxFraming({ min: [-30, -20, 0], size: [30, 40, 5] })), true);
  // The centre moves by more than 20 % of the radius.
  assert.equal(shouldRefit(plate, boxFraming({ min: [-20, -20, 0], size: [60, 40, 5] })), true);
  assert.equal(shouldRefit(plate, boxFraming({ min: [-28, -20, 0], size: [60, 40, 5] })), false);
  assert.equal(stableFraming(plate, same), plate);
  const big = boxFraming({ min: [0, 0, 0], size: [200, 40, 5] });
  assert.equal(stableFraming(plate, big), big);
  assert.equal(boxFraming(null), null);
  assert.equal(factsBox({ ...facts, min_mm: null }), null);
});

test('edge flash: only when a new GLB replaces a shown one, never with reduced motion', () => {
  assert.equal(FLASH_MS, HIGHLIGHT_MS);
  assert.deepEqual(flashFor(SHA, SHA2, { now: 1000 }), { from: 1000, until: 1000 + 1200 });
  assert.equal(flashFor(null, SHA, { now: 1000 }), null);
  assert.equal(flashFor(SHA, SHA, { now: 1000 }), null);
  assert.equal(flashFor(SHA, SHA2, { now: 1000, reducedMotion: true }), null);
});

test('stale-response rule: only the newest ticket is used', () => {
  const sequencer = createLoadSequencer();
  const first = sequencer.next(SHA);
  assert.equal(sequencer.accept(first), true);
  const second = sequencer.next(SHA2);
  assert.equal(sequencer.accept(first), false, 'an older response is dropped while a newer one is pending');
  assert.equal(sequencer.accept(second), true);
  sequencer.cancel();
  assert.equal(sequencer.accept(second), false, 'nothing is used after unmount');
  assert.equal(sequencer.accept(null), false);
  const want = { request_id: RID, sha256: SHA, bytes: 10 };
  assert.equal(artifactMatches({ sha256: SHA, bytes: 10 }, want), true);
  assert.equal(artifactMatches({ sha256: SHA2, bytes: 10 }, want), false);
  assert.equal(artifactMatches({ sha256: SHA, bytes: 11 }, want), false);
  assert.equal(artifactMatches(null, want), false);
});

test('GLB cache: least recently used evicted beyond the limit', () => {
  assert.equal(GLB_CACHE_SIZE, 4);
  const cache = createGlbCache(3);
  cache.set('a', 1); cache.set('b', 2); cache.set('c', 3);
  assert.equal(cache.get('a'), 1); // a is now the newest use
  cache.set('d', 4);
  assert.deepEqual(cache.keys(), ['c', 'a', 'd']);
  assert.equal(cache.has('b'), false);
  assert.equal(cache.get('b'), undefined);
  cache.set('c', 30);
  assert.deepEqual(cache.keys(), ['a', 'd', 'c']);
  assert.equal(cache.size, 3);
  assert.equal(cache.get('c'), 30);
});
