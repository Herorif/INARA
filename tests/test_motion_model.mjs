import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  MOTION_TOKENS, RISE_PX, frameLabel, materialisePlan, motionMode, parseDuration, parseEase, readTimings, reverseEase,
  staggerDelay, staggerTotal,
} from '../src/shared/motion/motionModel.js';
import { CLIP_HIDDEN, CLIP_SHOWN, materialiseVariants } from '../src/shared/motion/materialise.js';

// The real tokens: the timings must come from src/app/tokens.css and nowhere else.
const css = fs.readFileSync(new URL('../src/app/tokens.css', import.meta.url), 'utf8');
const token = name => {
  const match = new RegExp(`${name.replace(/[-]/g, '\\-')}\\s*:\\s*([^;]+);`).exec(css);
  return match ? match[1].trim() : '';
};
const timings = readTimings(token);

test('the motion mode follows gaming, then reduced motion or low battery', () => {
  assert.equal(motionMode(), 'full');
  assert.equal(motionMode({}), 'full');
  assert.equal(motionMode({ reducedMotion: true }), 'fade');
  assert.equal(motionMode({ lowBattery: true }), 'fade');
  assert.equal(motionMode({ reducedMotion: true, lowBattery: true }), 'fade');
  assert.equal(motionMode({ gaming: true }), 'instant');
  assert.equal(motionMode({ gaming: true, reducedMotion: true, lowBattery: true }), 'instant');
});

test('durations and curves parse from CSS values', () => {
  assert.equal(parseDuration('160ms'), 160);
  assert.equal(parseDuration(' 0.2s '), 200);
  assert.equal(parseDuration('.12s'), 120);
  assert.equal(parseDuration('0ms'), 0);
  for (const bad of ['', '160', 'fast', '-1ms', null, undefined, 'calc(1ms)']) assert.equal(parseDuration(bad), null, String(bad));
  assert.deepEqual(parseEase('cubic-bezier(.2,.8,.2,1)'), [0.2, 0.8, 0.2, 1]);
  assert.deepEqual(parseEase(' cubic-bezier(0.4, 0, 0.2, 1) '), [0.4, 0, 0.2, 1]);
  for (const bad of ['ease-out', 'cubic-bezier(1,2,3)', 'cubic-bezier(2,0,0,1)', '', null]) assert.equal(parseEase(bad), null, String(bad));
  assert.deepEqual(reverseEase([0.2, 0.8, 0.2, 1]), [0.8, 0, 0.8, 0.2]);
  assert.equal(reverseEase(null), null);
});

test('the timings are the tokens in tokens.css', () => {
  assert.deepEqual(Object.values(MOTION_TOKENS), ['--dur-draw', '--dur-fill', '--dur-exit', '--stagger', '--dur-fast', '--ease-out']);
  assert.deepEqual(timings, { draw: 160, fill: 200, exit: 120, stagger: 40, fade: 120, ease: [0.2, 0.8, 0.2, 1] });
});

test('unreadable tokens mean no animation, never invented numbers', () => {
  const none = { draw: 0, fill: 0, exit: 0, stagger: 0, fade: 0, ease: null };
  assert.deepEqual(readTimings(null), none);
  assert.deepEqual(readTimings(() => ''), none);
  assert.deepEqual(readTimings(() => { throw new Error('no style'); }), none);
  assert.deepEqual(readTimings(name => (name === '--dur-draw' ? '90ms' : 'junk')), { ...none, draw: 90 });
});

test('full mode: border draws, then the content fills and rises, exit reversed in --dur-exit', () => {
  const plan = materialisePlan('full', timings);
  assert.equal(plan.rise, RISE_PX);
  assert.equal(RISE_PX, 8);
  assert.deepEqual(plan.enter.border, { delay: 0, duration: 160 });
  assert.deepEqual(plan.enter.content, { delay: 160, duration: 200 });
  assert.deepEqual(plan.enter.fade, { delay: 0, duration: 0 });
  assert.equal(plan.enter.stagger, 40);
  assert.equal(plan.enter.total, 360);
  // Reverse order: content leaves first, then the border, all within 120 ms.
  assert.deepEqual(plan.exit.content, { delay: 0, duration: 60 });
  assert.deepEqual(plan.exit.border, { delay: 60, duration: 60 });
  assert.equal(plan.exit.total, 120);
  assert.ok(plan.exit.total < plan.enter.total, 'out is faster than in');
  assert.deepEqual(plan.ease, [0.2, 0.8, 0.2, 1]);
  assert.deepEqual(plan.exitEase, [0.8, 0, 0.8, 0.2]);
});

test('children stagger by --stagger after the border', () => {
  const plan = materialisePlan('full', timings);
  assert.deepEqual([0, 1, 2, 3].map(i => staggerDelay(plan, i)), [160, 200, 240, 280]);
  assert.equal(staggerDelay(plan, -2), 160);
  assert.equal(staggerDelay(plan, 'x'), 160);
  assert.equal(staggerTotal(plan, 0), 360);
  assert.equal(staggerTotal(plan, 1), 360);
  assert.equal(staggerTotal(plan, 4), 480);
});

test('fade mode: no movement, one plain fade in and out', () => {
  const plan = materialisePlan('fade', timings);
  assert.equal(plan.rise, 0);
  assert.deepEqual(plan.enter.fade, { delay: 0, duration: 120 });
  assert.deepEqual(plan.exit.fade, { delay: 0, duration: 120 });
  for (const part of [plan.enter.border, plan.enter.content, plan.exit.border, plan.exit.content]) assert.deepEqual(part, { delay: 0, duration: 0 });
  assert.equal(plan.enter.stagger, 0);
  assert.equal(staggerDelay(plan, 5), 0);
  assert.equal(plan.enter.total, 120);
  assert.equal(plan.exit.total, 120);
});

test('instant mode (gaming): nothing animates', () => {
  const plan = materialisePlan('instant', timings);
  assert.equal(plan.rise, 0);
  assert.equal(plan.enter.total, 0);
  assert.equal(plan.exit.total, 0);
  assert.equal(plan.enter.fade.duration, 0);
  assert.equal(plan.exit.fade.duration, 0);
  assert.equal(staggerTotal(plan, 6), 0);
});

test('variants carry the plan in seconds and move nothing outside full mode', () => {
  const full = materialiseVariants(materialisePlan('full', timings));
  assert.equal(full.mode, 'full');
  assert.deepEqual(full.root.hidden, { opacity: 1 });
  assert.equal(full.border.hidden.clipPath, CLIP_HIDDEN);
  assert.equal(full.border.shown.clipPath, CLIP_SHOWN);
  assert.equal(full.border.shown.transition.duration, 0.16);
  assert.equal(full.border.gone.transition.delay, 0.06);
  assert.equal(full.border.gone.transition.duration, 0.06);
  assert.deepEqual([full.content.hidden.opacity, full.content.hidden.y], [0, 8]);
  assert.equal(full.content.shown.transition.delay, 0.16);
  assert.equal(full.content.shown.transition.duration, 0.2);
  assert.equal(full.content.shown.transition.staggerChildren, 0.04);
  assert.equal(full.content.gone.transition.duration, 0.06);
  assert.deepEqual(full.content.shown.transition.ease, [0.2, 0.8, 0.2, 1]);

  const fade = materialiseVariants(materialisePlan('fade', timings));
  assert.deepEqual([fade.root.hidden.opacity, fade.root.shown.opacity, fade.root.gone.opacity], [0, 1, 0]);
  assert.equal(fade.root.shown.transition.duration, 0.12);
  assert.equal(fade.root.gone.transition.duration, 0.12);
  assert.deepEqual([fade.border, fade.content, fade.item], [{}, {}, {}]);

  const instant = materialiseVariants(materialisePlan('instant', timings));
  assert.deepEqual([instant.root.hidden.opacity, instant.root.gone.opacity], [1, 1]);
  assert.equal(instant.root.shown.transition.duration, 0);
  assert.deepEqual([instant.border, instant.content, instant.item], [{}, {}, {}]);
});

test('frame index labels', () => {
  assert.equal(frameLabel('01', 'World'), '01 · World');
  assert.equal(frameLabel('02', ''), '02');
  assert.equal(frameLabel(null, ' Design '), 'Design');
  assert.equal(frameLabel(), '');
  assert.equal(frameLabel(3, 'Home'), '3 · Home');
});
