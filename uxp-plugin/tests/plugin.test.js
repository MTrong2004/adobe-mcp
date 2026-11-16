'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createDispatcher } = require('../dispatcher.js');
const { createClient } = require('../client.js');
function fixture() {
  let time = 1000;
  let fail = false;
  const layer = { id: 2, name: 'Before', visible: true, kind: 'pixel' };
  let opacity = 100;
  Object.defineProperty(layer, 'opacity', { get: () => opacity, set: value => { if (fail) throw new Error('locked'); opacity = value; } });
  const doc = { id: 1, name: 'Test', width: 1200, height: 800, resolution: 300, mode: 'RGB', layers: [{ id: 3, name: 'Group', visible: true, opacity: 100, kind: 'group', layers: [layer] }] };
  const history = [];
  let snapshot;
  const context = { isCancelled: false, hostControl: {
    async suspendHistory(options) { history.push(['suspend', options.documentID]); snapshot = { name: layer.name, visible: layer.visible, opacity }; return 7; },
    async resumeHistory(suspension, commit) { history.push(['resume', suspension, commit]); if (!commit) { layer.name = snapshot.name; layer.visible = snapshot.visible; opacity = snapshot.opacity; } }
  } };
  const ps = { app: { documents: [doc], activeDocument: doc, version: '27.0' }, constants: { LayerKind: { GROUP: 'group' } }, core: { async executeAsModal(fn) { return fn(context); } } };
  return { ps, doc, layer, history, context, dispatch: createDispatcher(ps, () => time), setTime: n => { time = n; }, fail: () => { fail = true; } };
}
const job = (operation, args = {}) => ({ id: 'j1', operation, args, expires_at: 2000 });
test('DOM dimensions remain pixels and tree respects max depth', async () => {
  const f = fixture();
  const full = await f.dispatch(job('document_info'));
  assert.equal(full.document.width, 1200);
  assert.equal(full.document.layers[0].children[0].id, 2);
  const limited = await f.dispatch(job('document_info', { max_depth: 0 }));
  assert.equal(limited.document.layers[0].children_truncated, true);
  assert.deepEqual(limited.document.layers[0].children, []);
  assert.equal((await f.dispatch(job('document_info', { include_layers: false }))).document.layers, undefined);
});
test('validation rejects unsafe operations, IDs, types, expiry and unknown fields', async () => {
  const f = fixture();
  for (const request of [job('eval', {}), job('update_layer', { layer_id: 2, name: 'X' }), job('update_layer', { document_id: 1, layer_id: 2, opacity: NaN }), job('update_layer', { document_id: 1, layer_id: 2, visible: 'false' }), job('update_layer', { document_id: 1, layer_id: 2, name: 'X', save: true }), job('document_info', { max_depth: -2 }), job('document_info', { document_id: 99 }), { ...job('session_info'), expires_at: 1000 }]) await assert.rejects(f.dispatch(request));
  assert.deepEqual(f.history, []);
});
test('update uses one history state and returns actual layer properties', async () => {
  const f = fixture();
  const result = await f.dispatch(job('update_layer', { document_id: 1, layer_id: 2, name: 'After', visible: false, opacity: 40 }));
  assert.equal(result.layer.name, 'After');
  assert.equal(result.layer.opacity, 40);
  assert.deepEqual(f.history, [['suspend', 1], ['resume', 7, true]]);
});
test('partial update error rolls back earlier successful writes', async () => {
  const f = fixture(); f.fail();
  await assert.rejects(f.dispatch(job('update_layer', { document_id: 1, layer_id: 2, name: 'Changed', visible: false, opacity: 20 })), /locked/);
  assert.equal(f.layer.name, 'Before'); assert.equal(f.layer.visible, true);
  assert.deepEqual(f.history, [['suspend', 1], ['resume', 7, false]]);
});
test('document and expiry rechecked inside modal before mutation', async () => {
  for (const expire of [true, false]) {
    const f = fixture();
    f.ps.core.executeAsModal = async fn => { if (expire) f.setTime(2000); else f.ps.app.documents = []; return fn(f.context); };
    await assert.rejects(f.dispatch(job('update_layer', { document_id: 1, layer_id: 2, name: 'Changed' })));
    assert.deepEqual(f.history, []);
  }
});
test('expiry during history suspension rolls back without setters', async () => {
  const f = fixture();
  const suspend = f.context.hostControl.suspendHistory;
  f.context.hostControl.suspendHistory = async options => { const value = await suspend(options); f.setTime(2000); return value; };
  await assert.rejects(f.dispatch(job('update_layer', { document_id: 1, layer_id: 2, name: 'Changed' })), /expired/);
  assert.equal(f.layer.name, 'Before');
  assert.deepEqual(f.history, [['suspend', 1], ['resume', 7, false]]);
});
function clientFixture(transport, dispatch) {
  const messages = [];
  const client = createClient({ transport, dispatch, status: (...args) => messages.push(args), schedule: () => 1, cancel: () => {} });
  return { client, messages };
}
test('failed result delivery retries only result; repeated ID never reruns', async () => {
  let executed = 0; let posts = 0;
  const calls = [];
  const { client } = clientFixture(async (path, token, body) => {
    calls.push(path); assert.equal(token, 'secret');
    if (path === '/health') return { success: true, protocol: 1 };
    if (path === '/next') return { job: job('session_info') };
    posts++; if (posts === 1) throw new Error('network');
    assert.equal(body.result.success, true); return { success: true };
  }, async () => { executed++; return { success: true }; });
  await client.connect('secret'); await client.tick(); await client.tick(); await client.tick();
  assert.equal(executed, 1);
  assert.deepEqual(calls, ['/health', '/next', '/result', '/result', '/next', '/result']);
});
test('polling is sequential and disconnect prevents newly received job execution', async () => {
  let resolveNext; let count = 0;
  const { client } = clientFixture(async path => {
    if (path === '/health') return { success: true, protocol: 1 };
    count++; return new Promise(resolve => { resolveNext = resolve; });
  }, async () => { throw new Error('Must not execute'); });
  await client.connect('secret');
  const first = client.tick(); await client.tick();
  assert.equal(count, 1); client.disconnect();
  resolveNext({ job: job('session_info') }); await first;
  assert.equal(count, 1);
});
test('HTTP 400 result rejection stops polling after broker restart', async () => {
  let requests = 0;
  const { client, messages } = clientFixture(async path => {
    requests++;
    if (path === '/health') return { success: true, protocol: 1 };
    if (path === '/next') return { job: job('session_info') };
    throw Object.assign(new Error('stale'), { status: 400 });
  }, async () => ({ success: true }));
  await client.connect('secret'); await client.tick(); await client.tick();
  assert.equal(requests, 3);
  assert.equal(messages.at(-1)[1], false);
});
test('invalid health protocol never polls', async () => {
  let calls = 0;
  const { client } = clientFixture(async () => { calls++; return { success: true, protocol: 2 }; }, async () => ({}));
  await client.connect('secret'); await client.tick(); assert.equal(calls, 1);
});
