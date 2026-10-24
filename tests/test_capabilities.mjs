import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { createCapabilityClient } from '../src/transport/capabilityClient.ts';
import { createCadClient } from '../src/transport/cadClient.ts';
import { searchCommands } from '../src/app/features.js';
import { recordActivity } from '../src/store/activitySlice.js';

class Socket extends EventEmitter {
  connected = true;
  requests = [];
  emit(event, ...args) {
    if (['capability_diagnostics','cad_lifetime'].includes(event)) {
      this.requests.push({ event, data: args[0], ack: args[1] }); return true;
    }
    return super.emit(event, ...args);
  }
}
const report = () => ({ ok: true, checked_at: 100, hardware: { cpu_count: 8, ram_available_mb: 16000, ram_total_mb: 32000, vram_mb: null }, resources: { state: 'chat', running: 0, waiting: 0, queue_limit: 4, budget: { cpu: 2, ram_mb: 8192, vram_mb: 0 } }, capabilities: [{ id: 'cad_offline', title: '3D', installed: true, configured: true, verified: false, blocked: null, reason: 'Offline', status: 'available', model: null, profile: null, last_duration_seconds: null }] });

test('capability command remains available in gaming mode', () => {
  assert.equal(searchCommands('diagnostics', true)[0].id, 'capabilities');
  assert.equal(searchCommands('diagnostics', true)[0].disabled, false);
});

test('diagnostics preserve unknown values and dispose listeners', async () => {
  const socket = new Socket(), client = createCapabilityClient(socket);
  const pending = client.inspect();
  assert.deepEqual(socket.requests[0].data, {});
  socket.requests[0].ack(report());
  assert.equal((await pending).hardware.vram_mb, null);
  client.dispose(); assert.equal(socket.listenerCount('disconnect'), 0);
});

test('diagnostics reject invalid readiness and memory values', async () => {
  for (const corrupt of [r => { r.hardware.vram_mb = -1; }, r => { r.capabilities[0].verified = 'yes'; }, r => { delete r.resources; }]) {
    const socket = new Socket(), client = createCapabilityClient(socket), pending = client.inspect();
    const value = report(); corrupt(value); socket.requests[0].ack(value);
    await assert.rejects(pending, { code: 'invalid_response' }); client.dispose();
  }
});

test('disconnect abandons diagnostics; reconnect does not replay the probe', async () => {
  const socket = new Socket(), client = createCapabilityClient(socket), pending = client.inspect();
  socket.connected = false; socket.emit('disconnect');
  await assert.rejects(pending, { code: 'disconnected' });
  socket.connected = true; socket.emit('connect');
  assert.equal(socket.requests.length, 1); client.dispose();
});

test('lifetime ACK is guarded and Activity retains the explicit background choice', async () => {
  const socket = new Socket(), client = createCadClient(socket);
  const pending = client.call('cad_lifetime', { request_id: 'one', background: true });
  const job = { request_id: 'one', project: 'temp', state: 'running', phase: 'building', background: true, resources: { profile: 'cad_offline', estimate: { cpu: 2, ram_mb: 512, vram_mb: 0 } } };
  socket.requests[0].ack({ ok: true, job });
  const result = await pending;
  const entries = recordActivity([], 'cad', result.job, 'temp');
  assert.equal(entries[0].background, true);
  assert.equal(entries[0].resources.estimate.ram_mb, 512);
  const invalid = client.call('cad_lifetime', { request_id: 'one', background: false });
  socket.requests[1].ack({ ok: true, job: {} });
  await assert.rejects(invalid, { code: 'invalid_response' }); client.dispose();
});
