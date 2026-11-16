'use strict';

const { OPERATIONS: READ_OPERATIONS, createReadInfo } = require('./read-info.js');
const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
function object(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} must be an object`);
}
function keys(value, allowed) {
  for (const key of Object.keys(value)) if (!allowed.includes(key)) throw new Error(`Unknown argument: ${key}`);
}
function id(value, label) {
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error(`${label} must be a positive integer`);
}
function assertFresh(job, now) {
  if (!Number.isSafeInteger(job.expires_at) || job.expires_at <= now()) throw new Error('Job expired or invalid expires_at');
}
function validate(job, now) {
  object(job, 'job');
  if (typeof job.id !== 'string' || !job.id || job.id.length > 256) throw new Error('Invalid job id');
  assertFresh(job, now);
  const args = job.args;
  object(args, 'args');
  switch (job.operation) {
    case 'get_session_info':
    case 'get_selection_info':
    case 'session_info': keys(args, []); break;
    case 'get_active_document_info':
      keys(args, ['include_layers', 'max_depth']);
      if (own(args, 'include_layers') && typeof args.include_layers !== 'boolean') throw new Error('include_layers must be boolean');
      if (own(args, 'max_depth') && !Number.isSafeInteger(args.max_depth)) throw new Error('max_depth must be an integer');
      break;
    case 'document_info':
      keys(args, ['document_id', 'include_layers', 'max_depth']);
      if (own(args, 'document_id')) id(args.document_id, 'document_id');
      if (own(args, 'include_layers') && typeof args.include_layers !== 'boolean') throw new Error('include_layers must be boolean');
      if (own(args, 'max_depth') && (!Number.isSafeInteger(args.max_depth) || args.max_depth < -1)) throw new Error('max_depth must be -1 or a nonnegative integer');
      break;
    case 'update_layer':
      keys(args, ['document_id', 'layer_id', 'name', 'visible', 'opacity']);
      id(args.document_id, 'document_id');
      id(args.layer_id, 'layer_id');
      if (!['name', 'visible', 'opacity'].some(key => own(args, key))) throw new Error('At least one layer property is required');
      if (own(args, 'name') && (typeof args.name !== 'string' || !args.name.trim() || args.name.length > 255 || /[\x00-\x1f\x7f]/.test(args.name))) throw new Error('name must be 1–255 characters without control characters');
      if (own(args, 'visible') && typeof args.visible !== 'boolean') throw new Error('visible must be boolean');
      if (own(args, 'opacity') && (typeof args.opacity !== 'number' || !Number.isFinite(args.opacity) || args.opacity < 0 || args.opacity > 100)) throw new Error('opacity must be a number from 0 to 100');
      break;
    default: throw new Error('Unsupported operation');
  }
  return args;
}
function findDocument(app, documentId) {
  const docs = Array.from(app.documents);
  const target = documentId === undefined ? app.activeDocument : docs.find(doc => doc.id === documentId);
  if (!target || !docs.some(doc => doc.id === target.id)) throw new Error('Document is no longer open');
  return target;
}
function children(layer, constants) {
  return layer.kind === constants.LayerKind.GROUP ? Array.from(layer.layers) : [];
}
function findLayer(doc, layerId, constants) {
  const stack = Array.from(doc.layers);
  while (stack.length) {
    const layer = stack.pop();
    if (layer.id === layerId) return layer;
    stack.push(...children(layer, constants));
  }
  throw new Error('Layer is no longer present in the specified document');
}
function layerInfo(layer) {
  return { id: layer.id, name: layer.name, visible: layer.visible, opacity: layer.opacity, kind: layer.kind };
}
function layerTree(layers, maxDepth, constants, depth = 0) {
  return Array.from(layers, layer => {
    const result = layerInfo(layer);
    if (layer.kind === constants.LayerKind.GROUP) {
      const nested = children(layer, constants);
      result.children = maxDepth === -1 || depth < maxDepth ? layerTree(nested, maxDepth, constants, depth + 1) : [];
      result.children_truncated = maxDepth !== -1 && depth >= maxDepth && nested.length > 0;
    }
    return result;
  });
}
function createDispatcher(photoshop, now = Date.now) {
  const { app, core, constants } = photoshop;
  const readInfo = createReadInfo(photoshop);
  return async job => {
    const args = validate(job, now);
    if (READ_OPERATIONS.includes(job.operation)) return await readInfo(job.operation, args);
    if (job.operation === 'session_info') {
      const documents = Array.from(app.documents, doc => ({ id: doc.id, name: doc.name }));
      return { success: true, version: app.version, active_document_id: documents.length ? app.activeDocument.id : null, documents };
    }
    const doc = findDocument(app, args.document_id);
    if (job.operation === 'document_info') {
      const document = { id: doc.id, name: doc.name, width: doc.width, height: doc.height, resolution: doc.resolution, mode: doc.mode };
      if (args.include_layers !== false) document.layers = layerTree(doc.layers, args.max_depth === undefined ? -1 : args.max_depth, constants);
      return { success: true, document };
    }
    findLayer(doc, args.layer_id, constants);
    return await core.executeAsModal(async context => {
      assertFresh(job, now);
      if (context.isCancelled) throw new Error('Operation cancelled');
      // Re-resolve IDs after waiting for the modal lock; never fall back to active document.
      const liveDoc = findDocument(app, args.document_id);
      const layer = findLayer(liveDoc, args.layer_id, constants);
      const suspension = await context.hostControl.suspendHistory({ documentID: liveDoc.id, name: 'AI Kit: cập nhật lớp' });
      try {
        assertFresh(job, now);
        if (context.isCancelled) throw new Error('Operation cancelled');
        if (own(args, 'name')) layer.name = args.name;
        if (own(args, 'visible')) layer.visible = args.visible;
        if (own(args, 'opacity')) layer.opacity = args.opacity;
        if (context.isCancelled) throw new Error('Operation cancelled');
        const result = { success: true, document_id: liveDoc.id, layer: layerInfo(layer) };
        await context.hostControl.resumeHistory(suspension, true);
        return result;
      } catch (error) {
        try { await context.hostControl.resumeHistory(suspension, false); }
        catch (_) { throw new Error('Update failed; explicit rollback failed. Photoshop will cancel suspended history when this modal throws.'); }
        throw error;
      }
    }, { commandName: 'AI Kit: cập nhật lớp', timeOut: 1 });
  };
}
module.exports = { createDispatcher, validate };
