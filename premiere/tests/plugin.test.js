'use strict';
const test = require('node:test');
const vm = require('node:vm');
const nodeFs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {createDispatcher} = require('../uxp-plugin/dispatcher.js');
const {BridgeLoop} = require('../uxp-plugin/client.js');
function fixture({mixed=false, reject=false}={}) {
  const files = new Map([['preset.epr',{size:10}]]); const calls=[]; const children=[]; let locked=false;
  const guid = x => ({toString:()=>x});
  const clip = {name:'source', getId:()=> 'clip1', isSequence:async()=>false, getMediaFilePath:async()=> 'C:/source.mov', getComponentChain:async type => type==='VIDEO'||mixed ? {} : null};
  const tracks={video:[],audio:[]};
  const seq={guid:guid('seq1'),name:'Sequence',getVideoTrackCount:async()=>1,getAudioTrackCount:async()=>1,getEndTime:async()=>({seconds:5}),getVideoTrack:async()=>({getTrackItems:(type,empty)=>{assert.equal(type,'CLIP');assert.equal(empty,false);return tracks.video;}}),getAudioTrack:async()=>({getTrackItems:()=>tracks.audio})};
  const root={name:'root',getItems:async()=>children,createBinAction:(name,unique)=>{assert.equal(unique,false);return ()=>children.push({name,folder:true,getId:()=> 'bin',getItems:async()=>[],createBinAction:()=>{}});}};
  children.push(clip);
  let sequences=[seq];
  const project={guid:guid('project1'),name:'Test',path:'C:/old.prproj',getRootItem:async()=>root,getSequences:async()=>sequences,
    lockedAccess(fn){assert.equal(fn.constructor.name,'Function');locked=true;const returned=fn();assert.equal(returned,undefined);locked=false;},
    executeTransaction(fn,label){assert.equal(locked,true);assert.equal(fn.constructor.name,'Function');calls.push(label);fn({addAction(action){if(!reject)action();}});return !reject;},
    importFiles:async(paths,suppress,target,stills)=>{assert.equal(suppress,true);assert.equal(stills,false);assert.equal(target,root);children.push({...clip,getId:()=> 'clip2'});return true;},
    createSequenceFromMedia:async(name,clips,target)=>{assert.equal(clips[0],clip);assert.equal(target,root);const s={...seq,name,guid:guid('seq2')};sequences.push(s);return s;},
    saveAs:async path=>{project.path=path;files.set(path,{size:100});return true;}};
  let active=project;
  const ppro={Project:{getActiveProject:async()=>active},ProjectItem:{cast:x=>x},FolderItem:{cast:x=> x.folder?x:null},ClipProjectItem:{cast:x=>x.getComponentChain?x:null},
    Constants:{MediaType:{VIDEO:'VIDEO',AUDIO:'AUDIO'},TrackItemType:{CLIP:'CLIP'},ExportType:{IMMEDIATELY:'NOW'}},TickTime:{createWithSeconds:seconds=>({seconds})},
    SequenceEditor:{getEditor:s=>({createInsertProjectItemAction(item,time,vi,ai,limit){assert.equal(locked,true);assert.equal(vi,0);assert.equal(ai,0);assert.equal(limit,true);return ()=>{tracks.video.push({getProjectItem:async()=>item,getStartTime:async()=>time});if(mixed)tracks.audio.push({getProjectItem:async()=>item,getStartTime:async()=>time});};}})},
    EncoderManager:{getManager:()=>({exportSequence:async(s,type,path,preset,full)=>{assert.equal(type,'NOW');assert.equal(preset,'preset.epr');assert.equal(full,true);files.set(path,{size:42});return true;}})}};
  return {dispatch:createDispatcher(ppro,{stat:async p=>files.get(p)||null},{version:'26.0.1'}),ppro,files,calls,project,setActive:x=>{active=x;}};
}
test('session reports version; project IDs use getId, sequence uses GUID',async()=>{const f=fixture();assert.equal((await f.dispatch('session_info')).version,'26.0.1');const r=await f.dispatch('project_info');assert.equal(r.items[0].id,'clip1');assert.equal(r.sequences[0].sequence_id,'seq1');});
test('old/missing host version unsupported',async()=>{const f=fixture();assert.equal((await createDispatcher(f.ppro,{}, {version:'25.6'})('session_info')).error.code,'unsupported');});
test('official direct import and create sequence verify returned live state',async()=>{const f=fixture();const r=await f.dispatch('import_media',{paths:['C:/source.mov']});assert.equal(r.success,true);assert.equal(r.imported[0].id,'clip2');const s=await f.dispatch('create_sequence',{name:'Created',item_node_ids:['clip1']});assert.equal(s.sequence.sequence_id,'seq2');});
test('sync lock/compound-action insert and readback',async()=>{const f=fixture();const r=await f.dispatch('insert_clip',{sequence_id:'seq1',project_item_id:'clip1',track_type:'video',track_index:0,time_seconds:2});assert.equal(r.success,true);assert.equal(f.calls.length,1);});
test('mixed AV needs explicit companion and verifies both tracks',async()=>{const f=fixture({mixed:true});const a={sequence_id:'seq1',project_item_id:'clip1',track_type:'video',track_index:0,time_seconds:2};assert.equal((await f.dispatch('insert_clip',a)).error.code,'unsupported');assert.equal(f.calls.length,0);const r=await f.dispatch('insert_clip',{...a,companion_track_index:0});assert.equal(r.success,true);assert.equal(r.tracks.length,2);});
test('transaction rejection is failure with unknown mutation outcome',async()=>{const f=fixture({reject:true});const r=await f.dispatch('insert_clip',{sequence_id:'seq1',project_item_id:'clip1',track_type:'video',track_index:0,time_seconds:2});assert.equal(r.success,false);assert.equal(r.outcome_unknown,true);});
test('export uses immediate API + nonempty new file, save checks active path/file',async()=>{const f=fixture();assert.equal((await f.dispatch('export_sequence',{sequence_id:'seq1',output_path:'out.mp4',preset_path:'preset.epr'})).bytes,42);assert.equal((await f.dispatch('export_sequence',{sequence_id:'seq1',output_path:'out.mp4',preset_path:'preset.epr'})).error.code,'file_exists');assert.equal((await f.dispatch('save_project',{path:'new.prproj'})).success,true);assert.equal((await f.dispatch('save_project',{path:'new.prproj'})).error.code,'file_exists');});
test('export false never reports completed, even if file is present',async()=>{const f=fixture();f.ppro.EncoderManager.getManager=()=>({exportSequence:async()=>false});const r=await f.dispatch('export_sequence',{sequence_id:'seq1',output_path:'out.mp4',preset_path:'preset.epr'});assert.equal(r.error.code,'export_unverified');assert.equal(r.outcome_unknown,true);});
test('project change before mutation prevents execute',async()=>{const f=fixture();let n=0;f.ppro.Project.getActiveProject=async()=>++n===1?f.project:null;const r=await f.dispatch('save_project',{path:'new.prproj'});assert.equal(r.success,false);assert.equal(f.files.has('new.prproj'),false);assert.equal(r.outcome_unknown,false);});
const response = data => ({ok:true,json:async()=>data});
function loopFixture(job,dispatch){let rejectResult=true;let deliveries=0;const loop=new BridgeLoop({now:()=>100,dispatch,fetch:async(url,options)=>{if(url.endsWith('/health'))return response({success:true,app:'premiere',protocol:1});if(url.endsWith('/next'))return response({job});if(url.endsWith('/result')){deliveries++;if(rejectResult)throw new Error('offline');return response({success:true});}throw new Error(url);}});loop.configure('x'.repeat(48));return {loop,ack:()=>{rejectResult=false;},deliveries:()=>deliveries};}
test('lost result receipt retained; retry delivers result and never replays host',async()=>{let calls=0;const f=loopFixture({id:'j1',operation:'save_project',args:{},expires_at:200},async()=>{calls++;return {success:true};});await f.loop.tick();assert.equal(calls,1);await assert.rejects(f.loop.tick());assert.ok(f.loop.pending);f.ack();await f.loop.tick();assert.equal(f.loop.pending,null);assert.equal(calls,1);await f.loop.tick();assert.equal(calls,1);assert.equal(f.loop.pending.result.error.code,'duplicate_job');});
test('epoch seconds expiry checked before mutation',async()=>{let calls=0;const f=loopFixture({id:'expired',operation:'save_project',args:{},expires_at:99},async()=>{calls++;});await f.loop.tick();assert.equal(calls,0);assert.equal(f.loop.pending.result.error.code,'expired');});
test('null host rejection produces retained structured failure',async()=>{const f=loopFixture({id:'null',operation:'save_project',args:{},expires_at:200},async()=>{throw null;});await f.loop.tick();assert.equal(f.loop.pending.result.success,false);assert.equal(f.loop.pending.result.outcome_unknown,true);});
test('concurrent ticks do not dispatch concurrently',async()=>{let release;let calls=0;const f=loopFixture({id:'serial',operation:'save_project',args:{},expires_at:200},()=>{calls++;return new Promise(r=>{release=r;});});const a=f.loop.tick();while(!release)await new Promise(r=>setImmediate(r));await f.loop.tick();assert.equal(calls,1);release({success:true});await a;});
test('stop while next request awaits yields cancelled receipt without executing',async()=>{
  let release;let calls=0;
  const loop=new BridgeLoop({fetch:async url=>url.endsWith('/health')?response({success:true,app:'premiere',protocol:1}):new Promise(resolve=>{release=resolve;}),dispatch:async()=>{calls++;return {success:true};}});
  loop.configure('x'.repeat(48));const pending=loop.tick();while(!release)await new Promise(r=>setImmediate(r));loop.stop();release(response({job:{id:'stopped',operation:'save_project',args:{},expires_at:Date.now()/1000+60}}));await pending;
  assert.equal(calls,0);assert.equal(loop.pending.result.error.code,'cancelled');assert.equal(loop.pending.result.outcome_unknown,false);
});
test('entrypoint uses real UXP lstat and textContent, setup panel registration',async()=>{
  let io;let setup;const elements=new Map();const doc={getElementById(id){if(!elements.has(id))elements.set(id,{value:'',textContent:'',addEventListener(){}});return elements.get(id);}};
  const context={document:doc,require(name){if(name==='premierepro')return {};if(name==='fs')return {lstat:async p=>{if(p==='missing')throw {code:'ENOENT'};return {isFile:()=>true,size:42};}};if(name==='./dispatcher.js')return {createDispatcher(p,adapter,host){io=adapter;assert.equal(host.version,'26.0.1');return async()=>({success:true});}};if(name==='./client.js')return {BridgeLoop:class{constructor(){} }};if(name==='uxp')return {host:{version:'26.0.1'},entrypoints:{setup:x=>{setup=x;}}};throw new Error(name);}};
  vm.runInNewContext(nodeFs.readFileSync(path.join(__dirname,'../uxp-plugin/main.js'),'utf8'),context);
  assert.equal((await io.stat('present')).size,42);assert.equal(await io.stat('missing'),null);assert.ok(setup.panels.premiereMcp);
});
test('wrong broker identity prevents polling/execution',async()=>{let calls=0;const loop=new BridgeLoop({fetch:async()=>response({success:true,app:'aftereffects',protocol:1}),dispatch:async()=>{calls++;}});loop.configure('x'.repeat(48));await assert.rejects(loop.tick());assert.equal(calls,0);});
