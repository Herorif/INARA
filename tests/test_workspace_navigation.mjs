import test from 'node:test';
import assert from 'node:assert/strict';
import { flags, heavyFeatures } from '../src/app/features.js';
import { clearedFeatures, dialogFeatures, featureWorkspace } from '../src/app/workspaceNavigation.js';

test('closing a short dialog keeps the current creative workspace and unrelated state', () => {
  const state = {
    [flags.image]: true, [flags.settings]: true, [flags.memory]: true,
    studioSelection: { feature: 'image', requestId: 'selected-revision' },
    inputValue: 'Unsent assistant draft', project: 'workshop',
  };
  const next = { ...state, ...clearedFeatures('dialog') };
  assert.equal(next[flags.settings], false);
  assert.equal(next[flags.memory], false);
  assert.equal(next[flags.image], true);
  assert.equal(next.studioSelection, state.studioSelection);
  assert.equal(next.inputValue, state.inputValue);
  assert.equal(next.project, state.project);
});

test('closing or replacing a dock leaves short decisions intact and clears every old dock', () => {
  const state = Object.fromEntries(Object.values(flags).map(flag => [flag, true]));
  const next = { ...state, ...clearedFeatures('workspace'), [flags.cad]: true };
  assert.equal(next[flags.cad], true);
  assert.equal(next[flags.image], false);
  assert.equal(next[flags.phone], false);
  assert.equal(next[flags.tasks], false);
  assert.equal(next[flags.settings], true);
  assert.equal(next[flags.reminder], true);
  assert.equal(next[flags.memory], true);
  assert.equal(Object.entries(flags).filter(([feature, flag]) => !dialogFeatures.has(feature) && next[flag]).length, 1);
});

test('lock and Quick Assistant clearing covers all panels without a forgotten catalog flag', () => {
  const dialogs = clearedFeatures('dialog');
  const docked = clearedFeatures('workspace');
  assert.equal(Object.keys(dialogs).some(flag => Object.hasOwn(docked, flag)), false);
  assert.deepEqual({ ...dialogs, ...docked }, clearedFeatures());
  assert.deepEqual(Object.keys(clearedFeatures()).sort(), Object.values(flags).sort());
  assert.ok(Object.values(clearedFeatures()).every(value => value === false));
});

test('heavy tools always belong to Studio and never open as short dialogs', () => {
  for (const feature of heavyFeatures) {
    assert.equal(featureWorkspace(feature), 'studio', feature);
    assert.equal(dialogFeatures.has(feature), false, feature);
  }
  assert.equal(featureWorkspace('activity'), 'studio');
  assert.equal(featureWorkspace('tasks'), 'tasks');
  assert.equal(featureWorkspace('routines'), 'tasks');
  assert.equal(featureWorkspace('phone'), 'connections');
  assert.equal(featureWorkspace('inbox'), 'inbox');
});
