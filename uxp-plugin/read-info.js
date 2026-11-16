'use strict';

// COM-compatible read projections. No setters, modal acquisition, preference changes or retries.
// Adobe: /ps-reference/media/batchplay (property-specific get; returned error descriptors)
// /ps-reference/classes/{document,layer,selection}, /classes/preferences/preferencesunitsandrulers
const OPERATIONS = ['get_session_info', 'get_active_document_info', 'get_selection_info'];
const BUSY = 'Photoshop đang bận. Hãy kết thúc hộp thoại hoặc thao tác hiện tại rồi gọi lại.';
function isBusy(error) {
  return error && (error.number === 9 || error.result === 9 || /modal|busy|đang bận/i.test(error.message || ''));
}
function normalize(value, table) {
  const key = Object.keys(table || {}).find(name => table[name] === value);
  return (key || String(value).split('.').pop()).replace(/[_\s]/g, '').toLowerCase();
}
function px(number) {
  if (typeof number !== 'number' || !Number.isFinite(number)) throw new Error('Không đọc được tọa độ pixel từ Photoshop.');
  return Math.round(number * 100) / 100;
}
function bounds(rect, size = true) {
  const result = { left: px(rect.left), top: px(rect.top), right: px(rect.right), bottom: px(rect.bottom) };
  if (size) { result.width = result.right - result.left; result.height = result.bottom - result.top; }
  return result;
}
function createReadInfo({ app, core, action, constants }) {
  async function available() {
    if (core.isModal || (await core.getActiveTool()).isModal) throw new Error(BUSY);
  }
  async function get(property, target, optional = false) {
    await available();
    const values = await action.batchPlay([{
      _obj: 'get', _target: [{ _property: property }, ...target], _options: { dialogOptions: 'silent' }
    }], {});
    const value = values && values[0];
    if (!value) throw new Error('Photoshop trả về dữ liệu không hợp lệ.');
    if (String(value._obj).toLowerCase() === 'error') {
      if (isBusy(value)) throw new Error(BUSY);
      // COM optional build/mask properties use null/false when the property is unavailable.
      if (optional && value.result === -25922) return undefined;
      throw new Error(value.message || 'Không đọc được thuộc tính Photoshop.');
    }
    return value[property];
  }
  function current() {
    if (!app.documents.length) throw new Error('No open document');
    return app.activeDocument;
  }
  function stable(documentId) {
    if (!app.documents.length || app.activeDocument.id !== documentId || !Array.from(app.documents).some(doc => doc.id === documentId)) {
      throw new Error('Tài liệu đang hoạt động đã thay đổi. Hãy gọi lại để đọc trạng thái mới.');
    }
  }
  function docInfo(doc, activeId) {
    const bitName = normalize(doc.bitsPerChannel, constants.BitsPerChannelType);
    const bits = { one: 1, eight: 8, sixteen: 16, thirtytwo: 32, 1: 1, 8: 8, 16: 16, 32: 32 };
    // UXP path is already a native path; cloud identifiers are not COM filesystem paths.
    let path = null;
    try { if (!doc.cloudDocument) path = doc.path || null; } catch (error) { if (isBusy(error)) throw error; }
    return { name: doc.name, width: px(doc.width), height: px(doc.height), resolution: doc.resolution,
      mode: normalize(doc.mode, constants.DocumentMode), bit_depth: bits[bitName] || null,
      path, saved: doc.saved, is_active: doc.id === activeId };
  }
  function flatten(layers) {
    const result = [];
    for (const layer of Array.from(layers)) {
      result.push(layer);
      if (layer.kind === constants.LayerKind.GROUP) result.push(...flatten(layer.layers));
    }
    return result;
  }
  async function layerInfo(layer, path, depth, maxDepth, documentId) {
    const info = { id: layer.id, name: layer.name, path, visible: layer.visible,
      opacity: Math.round(layer.opacity * 10) / 10, blend_mode: normalize(layer.blendMode, constants.BlendMode), bounds: bounds(layer.bounds) };
    if (layer.kind === constants.LayerKind.GROUP) {
      info.kind = 'group';
      if (maxDepth < 0 || depth < maxDepth) {
        info.children = [];
        for (const child of Array.from(layer.layers)) info.children.push(await layerInfo(child, path + '/' + child.name, depth + 1, maxDepth, documentId));
      } else info.child_count = layer.layers.length;
    } else {
      info.kind = normalize(layer.kind, constants.LayerKind);
      info.is_background = layer.isBackgroundLayer;
      info.fill_opacity = Math.round(layer.fillOpacity * 10) / 10;
      info.clipped = layer.isClippingMask;
      if (info.kind === 'text') {
        try { info.text = String(layer.textItem.contents).slice(0, 200); }
        catch (error) { if (isBusy(error)) throw error; }
      }
    }
    const target = [{ _ref: 'layer', _id: layer.id }, { _ref: 'document', _id: documentId }];
    info.has_mask = (await get('hasUserMask', target, true)) === true;
    info.has_vector_mask = (await get('hasVectorMask', target, true)) === true;
    stable(documentId);
    return info;
  }
  return async (operation, args) => {
    try {
      await available();
      let result;
      if (operation === 'get_session_info') {
        const docs = Array.from(app.documents);
        const activeId = docs.length ? app.activeDocument.id : null;
        const documents = docs.map(doc => docInfo(doc, activeId));
        const build = await get('buildNumber', [{ _ref: 'application', _enum: 'ordinal', _value: 'targetEnum' }], true);
        if (activeId !== null) stable(activeId);
        else if (app.documents.length) throw new Error('Danh sách tài liệu đã thay đổi. Hãy gọi lại.');
        result = { is_running: true, version: app.version, build: build === undefined ? null : build,
          ruler_units: ({ centimeters: 'cm', millimeters: 'mm' })[normalize(app.preferences.unitsAndRulers.rulerUnits, constants.RulerUnits)] || normalize(app.preferences.unitsAndRulers.rulerUnits, constants.RulerUnits),
          has_active_document: activeId !== null, documents, active_document: documents.find(doc => doc.is_active) || null };
      } else {
        const doc = current();
        const documentId = doc.id;
        if (operation === 'get_selection_info') {
          const rect = doc.selection.bounds;
          result = rect === null ? { has_selection: false } : { has_selection: true, bounds: bounds(rect) };
        } else if (operation === 'get_active_document_info') {
          result = docInfo(doc, documentId);
          const activeId = await get('layerID', [{ _ref: 'layer', _enum: 'ordinal', _value: 'targetEnum' }, { _ref: 'document', _id: documentId }]);
          const activeLayer = flatten(doc.layers).find(layer => layer.id === activeId);
          if (!activeLayer) throw new Error('Lớp đang hoạt động đã thay đổi. Hãy gọi lại.');
          result.active_layer = { id: activeLayer.id, name: activeLayer.name, bounds: bounds(activeLayer.bounds, false) };
          if (args.include_layers !== false) {
            result.layers = [];
            const maxDepth = args.max_depth === undefined ? -1 : args.max_depth;
            for (const layer of Array.from(doc.layers)) result.layers.push(await layerInfo(layer, layer.name, 0, maxDepth, documentId));
          }
        } else throw new Error('Unsupported read operation');
        stable(documentId);
      }
      return { success: true, ...result };
    } catch (error) {
      if (isBusy(error)) throw new Error(BUSY);
      throw error;
    }
  };
}
module.exports = { OPERATIONS, createReadInfo };
