'use strict';
// API provenance/version decisions: ../API-NOTES.md. Dependencies injected for unit tests.
const fail = (code, message, unknown = false) => ({success: false, error: {code, message}, outcome_unknown: unknown});
const norm = p => String(p).replace(/\\/g, '/').toLowerCase();
function createDispatcher(ppro, io, host = {}) {
  async function ensureProject(project) {
    const active = await ppro.Project.getActiveProject();
    if (!active || active.guid.toString() !== project.guid.toString()) throw new Error('Active project changed; inspect Premiere before submitting again');
  }
  function transaction(project, label, makeAction) {
    let ok = false;
    project.lockedAccess(() => {
      ok = project.executeTransaction(compound => { compound.addAction(makeAction()); }, label);
    });
    if (!ok) throw new Error('Premiere rejected transaction');
  }
  async function inventory(project) {
    const result = [];
    const queue = [{folder: await project.getRootItem(), parent: null}];
    while (queue.length) {
      const {folder, parent} = queue.shift();
      for (const item of await folder.getItems()) {
        if (result.length >= 10000) throw new Error('Project inventory exceeds 10000 items');
        const id = item.getId();
        const bin = ppro.FolderItem.cast(item);
        const clip = bin ? null : ppro.ClipProjectItem.cast(item);
        result.push({item, id, name: item.name, parent_id: parent, kind: bin ? 'bin' : clip ? 'clip' : 'other', clip,
          media_path: clip && !(await clip.isSequence()) ? await clip.getMediaFilePath() : null});
        if (bin) queue.push({folder: bin, parent: id});
      }
    }
    return result;
  }
  const publicItem = ({item, clip, ...rest}) => rest;
  async function sequenceInfo(s) {
    return {sequence_id: s.guid.toString(), name: s.name, video_tracks: await s.getVideoTrackCount(), audio_tracks: await s.getAudioTrackCount(), duration_seconds: (await s.getEndTime()).seconds};
  }
  async function findSequence(project, id) {
    // Compare actual live GUIDs rather than assuming string->object coercion.
    return (await project.getSequences()).find(s => s.guid.toString() === id);
  }
  async function trackItems(s, kind, index) {
    const count = await (kind === 'video' ? s.getVideoTrackCount() : s.getAudioTrackCount());
    if (index >= count) return [];
    const track = await (kind === 'video' ? s.getVideoTrack(index) : s.getAudioTrack(index));
    return track.getTrackItems(ppro.Constants.TrackItemType.CLIP, false);
  }
  async function matching(s, kind, index, id, time) {
    let n = 0;
    for (const item of await trackItems(s, kind, index)) {
      if ((await item.getProjectItem()).getId() === id && Math.abs((await item.getStartTime()).seconds - time) < 0.05) n++;
    }
    return n;
  }
  return async function dispatch(operation, args = {}) {
    let mutated = false;
    try {
      const supported = ['session_info','project_info','import_media','create_sequence','insert_clip','export_sequence','save_project'];
      if (!supported.includes(operation)) return fail('unsupported', 'Unknown Premiere operation');
      if (!host.version || !/^\d+\.\d+/.test(String(host.version)) || Number(String(host.version).split('.')[0]) < 26) return fail('unsupported', 'Premiere version 26 or newer is required');
      const project = await ppro.Project.getActiveProject();
      if (operation === 'session_info') return {success: true, app: 'premiere', protocol: 1, runtime: 'UXP', version: host.version, project_open: !!project,
        capabilities: {project_info: !!ppro.Project && typeof ppro.Project.getActiveProject === 'function', import_media: !!project && typeof project.importFiles === 'function', create_sequence: !!project && typeof project.createSequenceFromMedia === 'function', insert_clip: !!ppro.SequenceEditor && typeof ppro.SequenceEditor.getEditor === 'function', export_sequence: !!ppro.EncoderManager && typeof ppro.EncoderManager.getManager === 'function', save_project: !!project && typeof project.saveAs === 'function'}, constraints: {insert_clip: 'mixed AV requires companion_track_index; existing tracks only', export_sequence: 'IMMEDIATELY; output verified'}};
      if (!project) return fail('no_project', 'Open a Premiere project first');
      if (operation === 'project_info') return {success: true, project: {name: project.name, path: project.path, id: project.guid.toString()},
        items: (await inventory(project)).map(publicItem), sequences: await Promise.all((await project.getSequences()).map(sequenceInfo))};
      if (operation === 'import_media') {
        const before = await inventory(project);
        let target = await project.getRootItem();
        if (args.bin_name) {
          const bins = before.filter(i => i.kind === 'bin' && i.name === args.bin_name && i.parent_id === null);
          if (bins.length > 1) return fail('ambiguous_bin', 'Multiple root bins have that name');
          if (bins.length) target = ppro.FolderItem.cast(bins[0].item);
          else {
            await ensureProject(project);
            mutated = true;
            transaction(project, 'MCP: create import bin', () => target.createBinAction(args.bin_name, false));
            const found = (await target.getItems()).filter(i => i.name === args.bin_name && ppro.FolderItem.cast(i));
            if (found.length !== 1) return fail('verification_failed', 'Bin creation could not be verified', true);
            target = ppro.FolderItem.cast(found[0]);
          }
        }
        await ensureProject(project);
        mutated = true;
        const accepted = await project.importFiles(args.paths, true, ppro.ProjectItem.cast(target), false);
        const after = await inventory(project);
        const oldIds = new Set(before.map(i => i.id));
        const added = after.filter(i => i.kind === 'clip' && !oldIds.has(i.id));
        const missing = args.paths.filter(path => !added.some(i => i.media_path && norm(i.media_path) === norm(path)));
        if (!accepted || missing.length) return {...fail('verification_failed', 'Import incomplete or new items could not all be verified; inspect project before retrying', true), imported: added.map(publicItem), unverified_paths: missing};
        return {success: true, imported: added.map(publicItem)};
      }
      if (operation === 'create_sequence') {
        const items = await inventory(project);
        const clips = args.item_node_ids.map(id => items.find(i => i.id === id));
        if (clips.some(i => !i || !i.clip)) return fail('not_found', 'Every item_node_ids entry must identify a live clip project item');
        const before = new Set((await project.getSequences()).map(s => s.guid.toString()));
        const root = ppro.ProjectItem.cast(await project.getRootItem());
        await ensureProject(project);
        mutated = true;
        const s = await project.createSequenceFromMedia(args.name, clips.map(i => i.clip), root);
        const found = s && await findSequence(project, s.guid.toString());
        if (!found || before.has(s.guid.toString()) || found.name !== args.name) return fail('verification_failed', 'Sequence creation could not be verified', true);
        return {success: true, sequence: await sequenceInfo(found)};
      }
      if (operation === 'insert_clip') {
        const s = await findSequence(project, args.sequence_id);
        const entry = (await inventory(project)).find(i => i.id === args.project_item_id);
        if (!s || !entry || !entry.clip) return fail('not_found', 'Sequence or clip project item not found');
        const video = !!await entry.clip.getComponentChain(ppro.Constants.MediaType.VIDEO);
        const audio = !!await entry.clip.getComponentChain(ppro.Constants.MediaType.AUDIO);
        if (!(args.track_type === 'video' ? video : audio)) return fail('unsupported', 'Source has no stream of the requested media type');
        if (video && audio && args.companion_track_index === undefined) return fail('unsupported', 'Mixed AV insertion requires explicit companion_track_index for the opposite media type');
        const vi = args.track_type === 'video' ? args.track_index : (args.companion_track_index === undefined ? 0 : args.companion_track_index);
        const ai = args.track_type === 'audio' ? args.track_index : (args.companion_track_index === undefined ? 0 : args.companion_track_index);
        // Restrict to existing tracks: Premiere's implicit new-track placement is not sufficiently precise for this contract.
        if ((video && vi >= await s.getVideoTrackCount()) || (audio && ai >= await s.getAudioTrackCount())) return fail('unsupported', 'Create the requested destination tracks in Premiere first');
        const checks = [];
        if (video) checks.push({kind:'video', index:vi});
        if (audio) checks.push({kind:'audio', index:ai});
        for (const c of checks) c.before = await matching(s,c.kind,c.index,entry.id,args.time_seconds);
        const editor = ppro.SequenceEditor.getEditor(s);
        await ensureProject(project);
        mutated = true;
        transaction(project, 'MCP: insert clip', () => editor.createInsertProjectItemAction(entry.item, ppro.TickTime.createWithSeconds(args.time_seconds), vi, ai, true));
        for (const c of checks) {
          if (await matching(s,c.kind,c.index,entry.id,args.time_seconds) <= c.before) return fail('verification_failed', 'Inserted clip could not be verified on each destination track', true);
        }
        return {success:true, sequence_id:args.sequence_id, project_item_id:entry.id, tracks: checks.map(({kind,index}) => ({type:kind,index})), time_seconds:args.time_seconds};
      }
      if (operation === 'export_sequence') {
        const s = await findSequence(project, args.sequence_id);
        if (!s) return fail('not_found', 'Sequence not found');
        if (await io.stat(args.output_path)) return fail('file_exists', 'Choose a new output path');
        if (!await io.stat(args.preset_path)) return fail('not_found', 'Export preset does not exist');
        const manager = ppro.EncoderManager.getManager();
        if (!manager || typeof manager.exportSequence !== 'function' || ppro.Constants.ExportType.IMMEDIATELY === undefined) return fail('unsupported', 'Immediate export API unavailable');
        await ensureProject(project);
        if (await io.stat(args.output_path)) return fail('file_exists', 'Output path now exists; choose a new path');
        mutated = true;
        const accepted = await manager.exportSequence(s, ppro.Constants.ExportType.IMMEDIATELY, args.output_path, args.preset_path, true);
        const output = await io.stat(args.output_path);
        if (!accepted || !output || output.size <= 0) return {...fail('export_unverified', 'Export has not produced a nonempty file; inspect Premiere before retrying', true), output_path:args.output_path};
        return {success:true, output_path:args.output_path, bytes:output.size, verification:'API returned and nonempty output exists; media integrity not decoded'};
      }
      if (operation === 'save_project') {
        const existing = await io.stat(args.path);
        if (existing && !args.overwrite) return fail('file_exists', 'Use a new path or explicitly set overwrite');
        await ensureProject(project);
        if (!args.overwrite && await io.stat(args.path)) return fail('file_exists', 'Save path now exists; choose a new path');
        mutated = true;
        const accepted = await project.saveAs(args.path);
        const active = await ppro.Project.getActiveProject();
        const file = await io.stat(args.path);
        if (!accepted || !active || norm(active.path) !== norm(args.path) || !file || file.size <= 0) return fail('verification_failed', 'Saved project path/file could not be verified', true);
        return {success:true, path:active.path, bytes:file.size};
      }
    } catch (err) {
      return fail('host_error', err && err.message ? err.message : 'Premiere operation failed', mutated);
    }
  };
}
module.exports = {createDispatcher, fail};
