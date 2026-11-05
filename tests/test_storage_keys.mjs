import test from 'node:test';
import assert from 'node:assert/strict';
import { readMigrated } from '../src/services/storageKeys.js';
import { loadView, saveView } from '../src/features/cad/views.js';

const memory = (entries = {}) => {
  const data = new Map(Object.entries(entries));
  return {
    data,
    getItem: key => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => { data.set(key, String(value)); },
    removeItem: key => { data.delete(key); },
  };
};

test('a pre-rename key moves to its JARVIS name once and keeps its value', () => {
  const storage = memory({ inara_client_id: 'client-1', 'inara_conversation:temp': 'conv-1', 'inara.calls.forwardingConfirmed': '1' });
  assert.equal(readMigrated(storage, 'jarvis_client_id'), 'client-1');
  assert.equal(readMigrated(storage, 'jarvis_conversation:temp'), 'conv-1');
  assert.equal(readMigrated(storage, 'jarvis.calls.forwardingConfirmed'), '1');
  assert.deepEqual([...storage.data.entries()].sort(), [
    ['jarvis.calls.forwardingConfirmed', '1'], ['jarvis_client_id', 'client-1'], ['jarvis_conversation:temp', 'conv-1'],
  ], 'the legacy keys are removed');
  storage.setItem('inara_client_id', 'stale');
  assert.equal(readMigrated(storage, 'jarvis_client_id'), 'client-1', 'the JARVIS key wins once set');
});

test('missing keys, unrelated keys and blocked storage read as null or as stored', () => {
  assert.equal(readMigrated(memory(), 'jarvis_client_id'), null);
  assert.equal(readMigrated(memory({ selectedMicId: 'mic' }), 'selectedMicId'), 'mic');
  assert.equal(readMigrated(memory({ inara_x: 'old' }), 'other_x'), null, 'only jarvis… keys have a legacy name');
  assert.equal(readMigrated({ getItem: () => { throw Error('blocked'); } }, 'jarvis_client_id'), null);
  const full = memory({ inara_client_id: 'client-1' });
  full.setItem = () => { throw Error('quota'); };
  assert.equal(readMigrated(full, 'jarvis_client_id'), 'client-1', 'a failed move still returns the legacy value');
});

test('saved 3D views survive the rename', () => {
  const view = { position: [1, 2, 3], target: [0, 0, 0] };
  const storage = memory({ 'inara:cad-view:demo:req-1': JSON.stringify(view) });
  assert.deepEqual(loadView(storage, 'jarvis:cad-view:demo:req-1'), view);
  assert.equal(storage.getItem('inara:cad-view:demo:req-1'), null);
  assert.equal(saveView(storage, 'jarvis:cad-view:demo:req-2', view), true);
  assert.deepEqual(loadView(storage, 'jarvis:cad-view:demo:req-2'), view);
});
