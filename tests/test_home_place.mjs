import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import {
  HOME_PLACE_HELP, HOME_PLACE_MAX, HOME_PLACE_PLACEHOLDER, HOME_PLACE_UNSET,
  homePlaceInput, homePlaceName, homePlaceStatus,
} from '../src/features/settings/aiSettingsModel.js';
import { createSecretsClient } from '../src/transport/secretsClient.ts';

const KL = { name: 'Kuala Lumpur, Malaysia', lat: 3.1412, lon: 101.68653 };

test('home town status reads the saved place or Not set', () => {
  assert.equal(homePlaceStatus({ home_place: KL }), 'Kuala Lumpur, Malaysia');
  assert.equal(homePlaceName({ home_place: KL }), 'Kuala Lumpur, Malaysia');
  for (const assistant of [undefined, null, {}, { home_place: null }, { home_place: { name: 'KL' } },
    { home_place: { name: 'KL', lat: '3', lon: 101 } }, { home_place: { name: 5, lat: 3, lon: 101 } }]) {
    assert.equal(homePlaceStatus(assistant), HOME_PLACE_UNSET);
    assert.equal(homePlaceName(assistant), '');
  }
  assert.equal(HOME_PLACE_UNSET, 'Not set');
  assert.equal(HOME_PLACE_PLACEHOLDER, 'e.g. Kuala Lumpur');
  assert.equal(HOME_PLACE_HELP, "Used for weather when you don't name a place.");
});

test('home town input collapses spaces and caps the length', () => {
  assert.equal(homePlaceInput('  Kuala   Lumpur \n'), 'Kuala Lumpur');
  assert.equal(homePlaceInput('   '), '');
  assert.equal(homePlaceInput(undefined), '');
  assert.equal(homePlaceInput('x'.repeat(200)).length, HOME_PLACE_MAX);
});

class Socket extends EventEmitter {
  connected = true;
  requests = [];
  emit(event, ...args) {
    if (event === 'weather_home_set') { this.requests.push({ event, data: args[0], ack: args[1] }); return true; }
    return super.emit(event, ...args);
  }
}

test('setHomePlace sends the place, returns the saved value and surfaces failures', async () => {
  const socket = new Socket();
  const client = createSecretsClient(socket);
  const saved = client.setHomePlace('Kuala Lumpur');
  assert.deepEqual(socket.requests[0].data, { place: 'Kuala Lumpur' });
  socket.requests[0].ack({ ok: true, home_place: KL });
  assert.deepEqual(await saved, KL);

  const cleared = client.setHomePlace(null);
  assert.deepEqual(socket.requests[1].data, { place: null });
  socket.requests[1].ack({ ok: true, home_place: null });
  assert.equal(await cleared, null);

  const missing = client.setHomePlace('Nowhere');
  socket.requests[2].ack({ ok: false, code: 'not_found', message: 'No place called Nowhere was found. Check the spelling.' });
  await assert.rejects(missing, { code: 'not_found', message: 'No place called Nowhere was found. Check the spelling.' });

  const broken = client.setHomePlace('KL');
  socket.requests[3].ack({ ok: true, home_place: { name: 'KL' } });
  await assert.rejects(broken, { code: 'invalid_response' });
  client.dispose();
});
