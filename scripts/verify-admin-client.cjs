// Isolated native admin RPC verification. Credentials arrive only over stdin.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { io } = require('socket.io-client');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const connect = async role => {
  const client = io('http://127.0.0.1:8000', {
    auth: { token: input.token, client_id: input.owner, role }, reconnection: false,
    transports: ['websocket'], timeout: 5000,
  });
  await new Promise((resolve, reject) => {
    client.once('connect', resolve);
    client.once('connect_error', reject);
  });
  return client;
};
(async () => {
  const clients = [];
  try {
    const renderer = await connect('renderer'); clients.push(renderer);
    const control = await connect('workspace'); clients.push(control);
    const snapshots = [];
    let leaked = false;
    renderer.on('settings', value => snapshots.push(value));
    control.on('settings', () => { leaked = true; });
    const call = (client, event, data = {}) => client.timeout(5000).emitWithAck(event, data);
    assert.equal((await call(renderer, 'get_settings')).ok, true);
    assert.equal((await call(control, 'get_settings')).ok, false);
    assert.equal((await call(renderer, 'update_settings', { camera_flipped: true })).ok, true);
    assert.equal(snapshots.at(-1).camera_flipped, true);
    assert.equal((await call(renderer, 'update_settings', { face_auth_enabled: 'false' })).code, 'invalid_arguments');
    assert.equal((await call(renderer, 'update_tool_permissions', { write_file: 'deny' })).ok, true);
    assert.equal((await call(renderer, 'get_settings')).ok, true);
    assert.equal(snapshots.at(-1).tool_permissions.write_file, 'deny');
    assert.equal((await call(control, 'desktop_control', { action: 'state' })).ok, true);
    assert.equal((await call(control, 'desktop_control', { action: 'gaming', gaming: 'false' })).code, 'invalid_arguments');
    assert.equal((await call(renderer, 'shutdown')).ok, false);
    assert.equal((await call(renderer, 'set_resource_state', { state: 'resident' })).ok, true);
    renderer.disconnect();
    const reopened = await connect('renderer'); clients.push(reopened);
    let restored;
    reopened.on('settings', value => { restored = value; });
    assert.equal((await call(reopened, 'get_settings')).ok, true);
    assert.equal(restored.camera_flipped, true);
    assert.equal(restored.tool_permissions.write_file, 'deny');
    assert.equal(leaked, false);
    process.stdout.write(JSON.stringify({ admin_rpc_settings_persisted: true,
      admin_rpc_role_and_schema_denials: true, admin_rpc_reconnect_and_scoped_settings: true }));
  } finally {
    clients.forEach(client => client.disconnect());
  }
})().catch(error => { process.stderr.write(error.message); process.exitCode = 1; });
