import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { createRpcScope } from '../src/transport/rpc.ts';
import { createImageClient } from '../src/transport/imageClient.ts';
import { reconcileHistory } from '../src/transport/history.ts';

class Socket extends EventEmitter {
  connected = true;
  requests = [];
  emit(event, ...args) {
    if (event.startsWith('image_')) { this.requests.push({ event, data: args[0], ack: args[1] }); return true; }
    return super.emit(event, ...args);
  }
  disconnect() { this.connected = false; this.emit('disconnect'); }
}

test('disconnect settles pending requests; late ACK cannot affect the reconnect session', async () => {
  const socket = new Socket(), scope = createRpcScope(socket);
  const pending = scope.call('image_submit', { request_id: 'first' });
  const rejected = assert.rejects(pending, { code: 'disconnected', uncertain: true });
  socket.disconnect(); await rejected;
  socket.connected = true;
  const replacement = scope.call('image_list');
  socket.requests[0].ack({ ok: true, job: { state: 'succeeded' } });
  socket.requests[1].ack({ ok: true, jobs: [] });
  assert.deepEqual(await replacement, { ok: true, jobs: [] });
  assert.equal(socket.requests.length, 2); // No automatic replay.
  scope.dispose(); assert.equal(socket.listenerCount('disconnect'), 0);
});

test('closing one scope releases its listeners and pending work without disturbing another', async () => {
  const socket = new Socket(), first = createRpcScope(socket), second = createRpcScope(socket);
  let received = 0;
  first.on('connect', () => { throw Error('closed listener'); });
  second.on('connect', () => received++);
  const pending = first.call('image_artifact');
  const rejected = assert.rejects(pending, { code: 'scope_closed' });
  first.dispose(); first.dispose(); await rejected;
  socket.emit('connect'); assert.equal(received, 1);
  socket.requests[0].ack({ ok: true });
  await assert.rejects(first.call('image_list'), { code: 'scope_closed' });
  second.dispose(); assert.equal(socket.eventNames().length, 0);
});

test('timeouts remain uncertain and an offline request sends nothing', async () => {
  const socket = new Socket(), scope = createRpcScope(socket);
  await assert.rejects(scope.call('image_submit', {}, 5), { code: 'timeout', uncertain: true });
  socket.requests[0].ack({ ok: true });
  socket.connected = false;
  await assert.rejects(scope.call('image_list'), { code: 'offline', uncertain: false });
  assert.equal(socket.requests.length, 1);
  scope.dispose();
});

test('structured denials and malformed acknowledgements are distinct', async () => {
  const socket = new Socket(), scope = createRpcScope(socket);
  const denied = scope.call('image_submit');
  socket.requests.at(-1).ack({ ok: false, code: 'permission_denied', message: 'Denied.' });
  await assert.rejects(denied, { code: 'permission_denied', uncertain: false });
  for (const response of [null, {}, { ok: 'yes' }]) {
    const pending = scope.call('image_list');
    socket.requests.at(-1).ack(response);
    await assert.rejects(pending, { code: 'invalid_response', uncertain: true });
  }
  scope.dispose();
});

test('image client rejects unusable history before the panel renders it', async () => {
  const socket = new Socket(), client = createImageClient(socket);
  const pending = client.call('image_list', {});
  socket.requests.at(-1).ack({ ok: true, jobs: 'bad', capabilities: {} });
  await assert.rejects(pending, /history could not be read/);
  client.dispose(); assert.equal(socket.eventNames().length, 0);
});


test('a list snapshot cannot erase a revision delivered while it was in flight', () => {
  const ready = { request_id: 'one', project: 'temp', state: 'succeeded', phase: 'ready' };
  const fresh = { request_id: 'two', project: 'temp', state: 'running', phase: 'generating' };
  const merged = reconcileHistory([fresh, ready], [{ ...ready, state: 'queued' }], new Set(['two']));
  assert.deepEqual(merged, [fresh, ready]);
  assert.deepEqual(reconcileHistory([fresh], [], new Set()), []);
});

test('image events and export responses are guarded before use', async () => {
  const socket = new Socket(), client = createImageClient(socket);
  let delivered = 0;
  client.on('image_job', () => delivered++);
  // Use EventEmitter to simulate inbound Socket.IO events rather than outgoing calls.
  EventEmitter.prototype.emit.call(socket, 'image_job', null);
  EventEmitter.prototype.emit.call(socket, 'image_job', { request_id: 'x', project: 'p', state: 'queued', phase: 'queued' });
  assert.equal(delivered, 1);
  const pending = client.call('image_artifact', { request_id: 'x' });
  socket.requests.at(-1).ack({ ok: true, artifact: { bytes: -1 } });
  await assert.rejects(pending, { code: 'invalid_response' });
  client.dispose();
});

test('synchronous send failure settles once and releases the request timer', async () => {
  const socket = new Socket(), scope = createRpcScope(socket);
  socket.emit = () => { throw Error('transport closed'); };
  await assert.rejects(scope.call('image_submit'), { code: 'send_failed', uncertain: true });
  scope.dispose();
});
