'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createDispatcher } = require('../dispatcher.js');
// Entirely synthetic fixtures; no customer documents, paths, or host captures.
function fixture() {
  const calls = [];
  const constants = {
    DocumentMode: { RGB: 'RGBColorMode', GRAYSCALE: 'grayscaleMode' },
    BitsPerChannelType: { EIGHT: 'eight', SIXTEEN: 'sixteen' },
    RulerUnits: { INCHES: 'rulerInches', PIXELS: 'rulerPixels' },
    LayerKind: { GROUP: 'group', TEXT: 'text', SMARTOBJECT: 'smartObject', NORMAL: 'pixel' },
    BlendMode: { NORMAL: 'normal', PASSTHROUGH: 'passThrough', SOFTLIGHT: 'softLight' }
  };
  const rect = { left: -1.234, top: 2.346, right: 10.004, bottom: 20.006 };
  const text = { id: 4, name: 'Caption', kind: 'text', visible: true, opacity: 88.86, blendMode: 'softLight', bounds: rect,
    isBackgroundLayer: false, fillOpacity: 67.74, isClippingMask: true, textItem: { contents: 'a'.repeat(201) } };
  const smart = { ...text, id: 5, name: 'Object', kind: 'smartObject', isClippingMask: false };
  const group = { id: 3, name: 'Group', kind: 'group', visible: true, opacity: 100, blendMode: 'passThrough', bounds: rect, layers: [text, smart] };
  const doc = { id: 11, name: 'Synthetic.psd', width: 1200.126, height: 800.444, resolution: 300, mode: 'RGBColorMode',
    bitsPerChannel: 'sixteen', path: '/synthetic/example.psd', saved: false, cloudDocument: false, layers: [group],
    activeLayers: [smart, text], selection: { bounds: null } };
  const rulers = {};
  Object.defineProperty(rulers, 'rulerUnits', { get: () => 'rulerInches', set: () => { throw new Error('Must never change ruler units'); } });
  const ps = { constants, app: { documents: [doc], activeDocument: doc, version: '27.synthetic', preferences: { unitsAndRulers: rulers } },
    core: { isModal: false, getActiveTool: async () => ({ isModal: false }), executeAsModal: () => { throw new Error('Reads must not acquire modal state'); } },
    action: { batchPlay: async (descriptors, options) => {
      calls.push(...descriptors);
      assert.deepEqual(options, {});
      return descriptors.map(command => {
        assert.equal(command._obj, 'get');
        assert.equal(command._options.dialogOptions, 'silent');
        const property = command._target[0]._property;
        const layer = command._target.find(ref => ref._ref === 'layer');
        if (property === 'buildNumber') return { buildNumber: 'synthetic-build' };
        if (property === 'layerID') return { layerID: 4 };
        if (property === 'hasUserMask') return { hasUserMask: layer._id === 3 };
        if (property === 'hasVectorMask') return { hasVectorMask: layer._id === 5 };
        throw new Error('Unexpected query');
      });
    } }
  };
  return { ps, doc, text, smart, group, calls, dispatch: createDispatcher(ps, () => 1000) };
}
const job = (operation, args = {}) => ({ id: 'synthetic-job', operation, args, expires_at: 2000 });
const expectedDoc = { name: 'Synthetic.psd', width: 1200.13, height: 800.44, resolution: 300, mode: 'rgb', bit_depth: 16,
  path: '/synthetic/example.psd', saved: false, is_active: true };
const edges = { left: -1.23, top: 2.35, right: 10, bottom: 20.01 };
const fullBounds = { ...edges, width: 11.23, height: 20.01 - 2.35 };
test('session exactly matches flat COM fields and original ruler units', async () => {
  const f = fixture();
  assert.deepEqual(await f.dispatch(job('get_session_info')), { success: true, is_running: true, version: '27.synthetic', build: 'synthetic-build', ruler_units: 'inches', has_active_document: true, documents: [expectedDoc], active_document: expectedDoc });
});
test('UXP centimeter/millimeter ruler names normalize to COM cm/mm', async () => {
  for (const [key, expected] of [['CENTIMETERS', 'cm'], ['MILLIMETERS', 'mm']]) {
    const f = fixture();
    f.ps.constants.RulerUnits = { [key]: 'metric' };
    f.ps.app.preferences.unitsAndRulers = Object.freeze({ rulerUnits: 'metric' });
    assert.equal((await f.dispatch(job('get_session_info'))).ruler_units, expected);
  }
});
test('empty session and missing build property match COM null values', async () => {
  const f = fixture(); f.ps.app.documents = [];
  f.ps.action.batchPlay = async () => [{ _obj: 'error', result: -25922, message: 'Property unavailable' }];
  assert.deepEqual(await f.dispatch(job('get_session_info')), { success: true, is_running: true, version: '27.synthetic', build: null, ruler_units: 'inches', has_active_document: false, documents: [], active_document: null });
  await assert.rejects(f.dispatch(job('get_selection_info')), /No open document/);
});
test('document tree exactly matches COM schema including masks, clipping and text truncation', async () => {
  const f = fixture();
  const common = { visible: true, opacity: 88.9, blend_mode: 'softlight', bounds: fullBounds, is_background: false, fill_opacity: 67.7 };
  assert.deepEqual(await f.dispatch(job('get_active_document_info')), { success: true, ...expectedDoc,
    active_layer: { id: 4, name: 'Caption', bounds: edges },
    layers: [{ id: 3, name: 'Group', path: 'Group', visible: true, opacity: 100, blend_mode: 'passthrough', bounds: fullBounds, kind: 'group', children: [
      { id: 4, name: 'Caption', path: 'Group/Caption', ...common, kind: 'text', clipped: true, text: 'a'.repeat(200), has_mask: false, has_vector_mask: false },
      { id: 5, name: 'Object', path: 'Group/Object', ...common, kind: 'smartobject', clipped: false, has_mask: false, has_vector_mask: true }
    ], has_mask: true, has_vector_mask: false }] });
  // Primary active layer comes from AM target, not the first selected DOM layer (5).
  assert.equal(f.calls.filter(call => call._target[0]._property === 'layerID').length, 1);
  for (const call of f.calls.filter(call => /Mask/.test(call._target[0]._property))) assert.equal(call._target[2]._id, 11);
});
test('depth zero uses child_count only; negative depths unlimited; omit layers explicitly', async () => {
  const f = fixture();
  const shallow = await f.dispatch(job('get_active_document_info', { max_depth: 0 }));
  assert.equal(shallow.layers[0].child_count, 2);
  assert.equal(Object.hasOwn(shallow.layers[0], 'children'), false);
  assert.equal((await f.dispatch(job('get_active_document_info', { max_depth: -7 }))).layers[0].children.length, 2);
  f.calls.length = 0;
  assert.deepEqual(await f.dispatch(job('get_active_document_info', { include_layers: false })), { success: true, ...expectedDoc, active_layer: { id: 4, name: 'Caption', bounds: edges } });
  assert.equal(f.calls.length, 1);
});
test('selection absence and rounded outside-canvas bounds match COM', async () => {
  const f = fixture();
  assert.deepEqual(await f.dispatch(job('get_selection_info')), { success: true, has_selection: false });
  f.doc.selection.bounds = f.text.bounds;
  assert.deepEqual(await f.dispatch(job('get_selection_info')), { success: true, has_selection: true, bounds: fullBounds });
  assert.equal(f.calls.length, 0);
});
test('unsaved/cloud path is null; saved flag is independent of path presence', async () => {
  const f = fixture(); f.doc.path = ''; f.doc.saved = false;
  assert.equal((await f.dispatch(job('get_active_document_info', { include_layers: false }))).path, null);
  f.doc.path = 'synthetic-cloud-id'; f.doc.cloudDocument = true;
  assert.equal((await f.dispatch(job('get_active_document_info', { include_layers: false }))).path, null);
});
test('busy rejects in Vietnamese without retry or false empty-selection response', async () => {
  const f = fixture(); f.ps.core.getActiveTool = async () => ({ isModal: true });
  await assert.rejects(f.dispatch(job('get_selection_info')), /Photoshop đang bận/);
  assert.equal(f.calls.length, 0);
  f.ps.core.getActiveTool = async () => ({ isModal: false });
  let attempts = 0;
  f.ps.action.batchPlay = async () => { attempts++; return [{ _obj: 'error', result: 9, message: 'modal' }]; };
  await assert.rejects(f.dispatch(job('get_session_info')), /Photoshop đang bận/);
  assert.equal(attempts, 1);
});
test('non-busy descriptor failures propagate and document switch rejects stale snapshot', async () => {
  const f = fixture();
  f.ps.action.batchPlay = async () => [{ _obj: 'error', result: -1, message: 'Read failed' }];
  await assert.rejects(f.dispatch(job('get_session_info')), /Read failed/);
  f.ps.action.batchPlay = async () => { f.ps.app.activeDocument = { id: 99 }; return { 0: { layerID: 4 } }; };
  await assert.rejects(f.dispatch(job('get_active_document_info', { include_layers: false })), /đã thay đổi/);
});
test('new operations reject extra IDs and malformed options; pilot stays separate', async () => {
  const f = fixture();
  for (const args of [{ document_id: 11 }, { include_layers: 1 }, { max_depth: 0.5 }]) await assert.rejects(f.dispatch(job('get_active_document_info', args)));
  await assert.rejects(f.dispatch(job('get_selection_info', { document_id: 11 })));
  assert.equal((await f.dispatch(job('session_info'))).active_document_id, 11);
});
