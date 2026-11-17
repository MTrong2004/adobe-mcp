'use strict';
const test=require('node:test'), assert=require('node:assert/strict'), fs=require('node:fs'), path=require('node:path'), vm=require('node:vm');
const {createClient,createHost,literal}=require('../cep/client.js');
function host() {
  const files=Object.create(null), events=[], old={render:true}, old2={render:false};
  function File(name) { this.fsName=name; this.name=name.split('/').pop(); this.parent={exists:true}; Object.defineProperty(this,'exists',{get:()=>!!files[name]}); Object.defineProperty(this,'length',{get:()=>files[name]||0}); }
  function AVItem(){} function CompItem(){} CompItem.prototype=Object.create(AVItem.prototype); function FootageItem(){} FootageItem.prototype=Object.create(AVItem.prototype);
  const comp=new CompItem(); Object.assign(comp,{id:7,name:'Comp',numLayers:1,width:100,height:100,duration:2,frameRate:25});
  const values={'ADBE Position':[1,2],'ADBE Scale':[100,100],'ADBE Rotate Z':0,'ADBE Opacity':100};
  const properties={}; for(const key of Object.keys(values)) properties[key]={value:values[key],numKeys:0,setValue(v){this.value=v;}};
  const layer={index:1,name:'Layer',property:()=>({property:key=>properties[key]})}; comp.layer=()=>layer; comp.layers={add:()=>layer};
  const queue={numItems:2,rendering:false,item:i=>[old,old2][i-1],items:{add(){ const om={templates:['Movie','Sequence'],applyTemplate(name){this.format=name==='Sequence'?'PNG Sequence':'QuickTime';},format:'QuickTime',getSettings(){return {Format:this.format};}}; const rq={status:1,render:true,outputModule:()=>om,remove(){events.push('remove');}}; queue.current=rq; return rq;}},render(){assert.equal(old.render,false); assert.equal(old2.render,false); events.push('render'); if(queue.throwRender) throw new Error('render failed'); const f=queue.current.outputModule().file; files[f.fsName]=128; queue.current.status=2;}};
  const app={version:'25.0',beginUndoGroup(){events.push('begin');},endUndoGroup(){events.push('end');},project:{numItems:1,item:()=>comp,renderQueue:queue,file:null,save(f){files[f.fsName]=100;},items:{addComp(name,w,h,pa,d,fps){return Object.assign(new CompItem(),{id:8,name,width:w,height:h,pixelAspect:pa,duration:d,frameRate:fps});}}}};
  const ctx=vm.createContext({app,File,CompItem,FootageItem,AVItem,ImportOptions:function(f){this.file=f;},RQItemStatus:{DONE:2},GetSettingsFormat:{STRING:1},JSON:undefined});
  for(const f of ['json.jsx','dispatcher.jsx']) vm.runInContext(fs.readFileSync(path.join(__dirname,'../cep/jsx',f),'utf8'),ctx);
  const call=(operation,args={},expires_at=Date.now()/1000+60)=>JSON.parse(ctx.AEMCP.dispatch(JSON.stringify({operation,args,expires_at})));
  return {ctx,call,files,events,queue,old,old2,properties,app};
}
test('ES3 codec round trips unicode/escapes without native JSON and rejects executable JSON',()=>{
  const {ctx}=host(); const input='quote" slash\\ newline\n tiếng Việt \u2028';
  assert.equal(ctx.AEMCPJSON.parse(ctx.AEMCPJSON.stringify(input)),input);
  for(const raw of ['{"x":1,"x":2}','{"__proto__":{}}','(function(){return 1})()','[1,]','1e999','{"a":01}','"a\n"']) assert.throws(()=>ctx.AEMCPJSON.parse(raw));
});
test('read-only calls use explicit IDs and mutations balance undo, reject invalid values',()=>{
 const h=host(); assert.equal(h.call('session_info').data.version,'25.0'); assert.equal(h.call('project_info').data.items[0].id,7); assert.deepEqual(h.events,[]);
 assert.equal(h.call('create_comp',{name:'A',width:1920,height:1080,pixel_aspect:1,duration:3,frame_rate:25}).data.id,8);
 assert.deepEqual(h.events,['begin','end']); assert.equal(h.call('execute_jsx',{code:'evil'}).success,false);
 assert.equal(h.call('save_project',{path:'relative.aep'}).success,false); assert.equal(h.call('add_layer',{comp_id:0,item_id:7}).success,false);
 assert.equal(h.call('create_comp',{name:'A',width:1,height:1,pixel_aspect:1,duration:3,frame_rate:25}).success,false);
 assert.equal(h.call('session_info',{},1).success,false);
});
test('transform validates all properties before writing and rejects keyframed values',()=>{
 const h=host(); assert.equal(h.call('set_layer_transform',{comp_id:7,layer_index:1,position:[9,8],opacity:101}).success,false); assert.deepEqual(h.properties['ADBE Position'].value,[1,2]);
 assert.equal(h.call('set_layer_transform',{comp_id:7,layer_index:1,position:[9,8],opacity:50}).data.opacity,50);
 h.properties['ADBE Position'].numKeys=1; assert.equal(h.call('set_layer_transform',{comp_id:7,layer_index:1,position:[9,8]}).success,false);
});
test('save refuses overwrite by default and requires explicit true',()=>{
 const h=host(); h.files['C:/old.aep']=10;
 assert.equal(h.call('save_project',{path:'C:/old.aep'}).success,false);
 assert.equal(h.call('save_project',{path:'C:/old.aep',overwrite:true}).data.saved,true);
});
test('render isolates queue, checks output, removes temporary item and restores flags',()=>{
 const h=host(); const result=h.call('render_comp',{comp_id:7,output_path:'C:/new.mov'}); assert.equal(result.success,true); assert.equal(result.data.bytes,128); assert.equal(h.old.render,true); assert.equal(h.old2.render,false); assert.deepEqual(h.events,['begin','render','remove','end']);
 assert.equal(h.call('render_comp',{comp_id:7,output_path:'C:/new.mov'}).success,false);
 assert.equal(h.call('render_comp',{comp_id:7,output_path:'C:/new.png'}).success,false);
 assert.equal(h.call('render_comp',{comp_id:7,output_path:'C:/sequence.mov',output_module_template:'Sequence'}).success,false);
});
test('render restores queue after thrown render, missing file, or non-DONE status',()=>{
 for(const mode of ['throw','missing','cancel']) {const h=host(); if(mode==='throw') h.queue.throwRender=true; else h.queue.render=()=>{h.queue.current.status=mode==='cancel'?1:2;};
 assert.equal(h.call('render_comp',{comp_id:7,output_path:'C:/new.mov'}).success,false); assert.equal(h.old.render,true); assert.equal(h.old2.render,false); assert.ok(h.events.includes('remove')); assert.equal(h.events.at(-1),'end');}
});
test('host evalScript serializes hostile data as literals and loads only packaged files',async()=>{
 const scripts=[],evil='\");app.quit();//\u2028'; const cep={getSystemPath:()=> 'file:///C:/panel',evalScript:(script,cb)=>{scripts.push(script);cb(scripts.length===1?'ready':'{"success":true}');}}; const h=createHost(cep); await h.load(); await h.dispatch({operation:'create_comp',args:{name:evil}});
 assert.ok(scripts[0].includes('C:/panel/jsx/json.jsx')); let captured; vm.runInNewContext(scripts[1],{AEMCP:{dispatch:x=>{captured=x;}}}); assert.equal(JSON.parse(captured).args.name,evil); assert.ok(literal('\u2028').includes('\\u2028'));
});
test('panel retains receipt through lost ACK and reconnect, never redispatches duplicate',async()=>{
 let calls=0,posts=0,fail=true; const job={id:'j1',operation:'create_comp',args:{},expires_at:Date.now()/1000+60};
 const client=createClient({dispatch:async()=>{calls++;return {success:true,data:{id:8}};},schedule:()=>1,cancel:()=>{},transport:async(route,token,body)=>{if(route==='/health')return {success:true,protocol:1,app:'aftereffects'};if(route==='/next')return {job}; posts++;assert.equal(body.id,'j1');assert.equal(body.result.success,true);if(fail){fail=false;throw null;}return {success:true};}});
 await client.connect('01234567890123456789012345678901'); await client.tick(); client.disconnect(); await client.connect('01234567890123456789012345678901'); await client.tick(); await client.tick(); assert.equal(calls,1); assert.equal(posts,3); client.disconnect();
});
test('panel expiration and rejection receipts always use result dictionary; polling serial',async()=>{
 for(const expired of [true,false]) {let calls=0,body;const client=createClient({dispatch:()=>{calls++;return Promise.reject(undefined);},schedule:()=>1,cancel:()=>{},transport:async(route,token,value)=>route==='/health'?{success:true,protocol:1,app:'aftereffects'}:route==='/next'?{job:{id:'x',expires_at:expired?1:Date.now()/1000+60}}:(body=value,{success:true})});await client.connect('01234567890123456789012345678901'); await Promise.all([client.tick(),client.tick()]); assert.equal(calls,expired?0:1); assert.equal(body.result.success,false); assert.equal(body.result.error.code,expired?'expired':'host_error');client.disconnect();}
});

test('disconnect during claimed next retains cancellation and requires original token',async()=>{
 let release, calls=0, posted; const secret='01234567890123456789012345678901';
 const waiting=new Promise(resolve=>{release=resolve;});
 const client=createClient({dispatch:()=>{calls++;return {success:true};},schedule:()=>1,cancel:()=>{},transport:async(route,token,body)=>route==='/health'?{success:true,protocol:1,app:'aftereffects'}:route==='/next'?waiting:(posted=body,{success:true})});
 await client.connect(secret); const tick=client.tick(); await Promise.resolve(); client.disconnect();
 release({job:{id:'claimed',expires_at:Date.now()/1000+60}}); await tick;
 await assert.rejects(client.connect('abcdefghijklmnopqrstuvwxyz123456'));
 await client.connect(secret); await client.tick();
 assert.equal(calls,0); assert.equal(posted.result.error.code,'cancelled'); assert.equal(posted.result.outcome_unknown,false); client.disconnect();
});
test('partial mutation and undo cleanup errors preserve unknown outcome',()=>{
 const h=host(); h.app.project.items.addComp=()=>{throw new Error('partial failure');};
 assert.equal(h.call('create_comp',{name:'a',width:100,height:100,pixel_aspect:1,duration:1,frame_rate:25}).outcome_unknown,true);
 assert.equal(h.call('add_layer',{comp_id:0,item_id:7}).outcome_unknown,false);
 h.app.endUndoGroup=()=>{throw new Error('cleanup');};
 assert.equal(h.call('save_project',{path:'C:/new.aep'}).error.code,'undo_error');
});
