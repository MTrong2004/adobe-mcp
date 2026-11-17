/* Only this dispatcher is callable by the panel. All arguments are data. */
var AEMCP = (function () {
    function fail(message) { throw new Error(message); }
    function own(o,k) { return Object.prototype.hasOwnProperty.call(o,k); }
    function number(v,name,min,max,integer) {
        if (typeof v !== 'number' || !isFinite(v) || v < min || v > max || (integer && Math.floor(v) !== v)) fail('Invalid ' + name);
        return v;
    }
    function text(v,name) { if (typeof v !== 'string' || !v.length || v.length > 32768 || /[\x00-\x1f]/.test(v)) fail('Invalid ' + name); return v; }
    function filePath(v) { text(v,'path'); if (!/^(?:[A-Za-z]:[\\/]|\/)/.test(v) || /^[/\\]{2}/.test(v)) fail('Absolute local path required'); return new File(v); }
    function project() { if (!app.project) fail('No project is open'); return app.project; }
    function item(id,comp) {
        number(id,'item ID',1,2147483647,true); var p=project(), i, found;
        for(i=1;i<=p.numItems;i++) { found=p.item(i); if(found.id===id) { if(comp && !(found instanceof CompItem)) fail('Item is not a composition'); return found; } }
        fail('Project item ID not found');
    }
    function info(i) { return {id:i.id,name:i.name,type:i instanceof CompItem?'composition':i instanceof FootageItem?'footage':'folder'}; }
    function args(a,required,optional) {
        if (!a || typeof a !== 'object' || a instanceof Array) fail('Arguments must be an object');
        var k,i; for(i=0;i<required.length;i++) if(!own(a,required[i])) fail('Missing '+required[i]);
        for(k in a) if(own(a,k)) { var ok=false; for(i=0;i<required.length;i++) if(k===required[i]) ok=true; for(i=0;i<optional.length;i++) if(k===optional[i]) ok=true; if(!ok) fail('Unknown argument '+k); }
    }
    var touched=false;
    function touch() { touched=true; }
    var operations = {
        session_info:function(a) { args(a,[],[]); return {application:'After Effects',version:app.version,project_open:!!app.project}; },
        project_info:function(a) {
            args(a,[],[]); var p=project(), items=[],i,layers,j,c;
            if(p.numItems>1000) fail('Project contains more than 1000 items; inspection limit exceeded');
            if(p.numItems>1000) fail('Project contains more than 1000 items; inspection limit exceeded');
            var totalLayers=0;
            for(i=1;i<=p.numItems;i++) { c=p.item(i); if(c instanceof CompItem) { totalLayers+=c.numLayers; if(totalLayers>3000) fail('Project contains more than 3000 layers; inspection limit exceeded'); } var record=info(c); if(c instanceof CompItem) { layers=[]; for(j=1;j<=c.numLayers;j++) layers.push({index:j,name:c.layer(j).name,source_id:c.layer(j).source?c.layer(j).source.id:null}); record.layers=layers; record.width=c.width; record.height=c.height; record.duration=c.duration; record.frame_rate=c.frameRate; } items.push(record); }
            return {path:p.file?p.file.fsName:null,num_items:p.numItems,items:items};
        },
        create_comp:function(a) {
            args(a,['name','width','height','pixel_aspect','duration','frame_rate'],[]); text(a.name,'name'); number(a.width,'width',4,30000,true); number(a.height,'height',4,30000,true); number(a.pixel_aspect,'pixel_aspect',0.01,100); number(a.duration,'duration',0.001,10800); number(a.frame_rate,'frame_rate',1,99);
            var p=project(); touch(); return info(p.items.addComp(a.name,a.width,a.height,a.pixel_aspect,a.duration,a.frame_rate));
        },
        import_media:function(a) { args(a,['path'],[]); var f=filePath(a.path); if(!f.exists) fail('Media file does not exist'); var options=new ImportOptions(f); options.sequence=false; var p=project(); touch(); return info(p.importFile(options)); },
        add_layer:function(a) { args(a,['comp_id','item_id'],[]); var c=item(a.comp_id,true), source=item(a.item_id,false); if(!(source instanceof AVItem)) fail('Layer source must be footage or composition'); if(source===c) fail('Cannot add composition to itself'); touch(); var layer=c.layers.add(source); return {comp_id:c.id,layer_index:layer.index,name:layer.name}; },
        set_layer_transform:function(a) {
            args(a,['comp_id','layer_index'],['position','scale','rotation','opacity']); var c=item(a.comp_id,true); number(a.layer_index,'layer_index',1,c.numLayers,true); var l=c.layer(a.layer_index), t=l.property('ADBE Transform Group'), changes=[], keys=['position','scale','rotation','opacity'], names=['ADBE Position','ADBE Scale','ADBE Rotate Z','ADBE Opacity'],i,j,p,v;
            if(l.locked) fail('Layer is locked');
            for(i=0;i<keys.length;i++) if(own(a,keys[i])) {
                p=t.property(names[i]); v=a[keys[i]]; if(!p || p.expressionEnabled || p.numKeys>0 || p.dimensionsSeparated) fail('Animated, expression, or separated transform unsupported');
                if(i<2) { if(!(v instanceof Array) || v.length!==p.value.length) fail('Transform dimensions must match layer'); for(j=0;j<v.length;j++) number(v[j],keys[i],-1000000,1000000); }
                else number(v,keys[i],i===3?0:-1000000,i===3?100:1000000);
                changes.push({property:p,value:v});
            }
            if(!changes.length) fail('Provide at least one transform');
            touch(); for(i=0;i<changes.length;i++) changes[i].property.setValue(changes[i].value);
            var out={comp_id:c.id,layer_index:l.index}; for(i=0;i<keys.length;i++) if(own(a,keys[i])) out[keys[i]]=t.property(names[i]).value; return out;
        },
        save_project:function(a) { args(a,['path'],['overwrite']); if(own(a,'overwrite') && typeof a.overwrite!=='boolean') fail('overwrite must be boolean'); var f=filePath(a.path); if(!/\.aep$/i.test(f.name)) fail('Project path must end in .aep'); if(!f.parent.exists) fail('Parent directory does not exist'); if(f.exists && a.overwrite!==true) fail('Output exists; overwrite is disabled'); var p=project(); touch(); p.save(f); f=new File(f.fsName); if(!f.exists || f.length<=0) fail('Save did not create a nonempty project file'); return {path:f.fsName,saved:true}; },
        render_comp:function(a) {
            args(a,['comp_id','output_path'],['output_module_template']); var c=item(a.comp_id,true), f=filePath(a.output_path), q=project().renderQueue, saved=[],rq=null,i,om,status,actual;
            if(q.rendering) fail('Render queue is busy');
            if(!f.parent.exists) fail('Output directory does not exist');
            // Single-file movie outputs only: sequence and sidecar names cannot be safely preflighted.
            if(!/\.(mov|avi|mp4|mxf)$/i.test(f.name)) fail('Only single-file mov/avi/mp4/mxf output is supported');
            if(f.exists) fail('Output exists; render never overwrites files');
            if(own(a,'output_module_template')) text(a.output_module_template,'output_module_template');
            try {
                for(i=1;i<=q.numItems;i++) saved.push({item:q.item(i),render:q.item(i).render});
                touch(); rq=q.items.add(c); om=rq.outputModule(1);
                if(own(a,'output_module_template')) { var templates=om.templates,found=false; for(i=0;i<templates.length;i++) if(templates[i]===a.output_module_template) found=true; if(!found) fail('Output module template not found'); om.applyTemplate(a.output_module_template); }
                // Reject sequence/audio templates even if the caller gives them a movie suffix.
                if(typeof om.getSettings!=='function' || typeof GetSettingsFormat==='undefined') fail('Cannot verify output module format on this AE version');
                var settings=om.getSettings(GetSettingsFormat.STRING), format=settings['Format'];
                if(format!=='QuickTime' && format!=='AVI' && format!=='H.264' && format!=='MXF OP1a') fail('Unsupported output format; choose a single-file movie template');
                om.file=f; actual=om.file;
                if(!actual || actual.fsName!==f.fsName) fail('Output module changed requested filename; choose matching template and extension');
                if(actual.exists) fail('Output exists; render never overwrites files');
                for(i=0;i<saved.length;i++) if(saved[i].render) saved[i].item.render=false;
                rq.render=true; q.render(); status=rq.status;
                if(status!==RQItemStatus.DONE) fail('Render did not finish successfully');
                actual=new File(f.fsName); if(!actual.exists || actual.length<=0) fail('Render finished without a nonempty file at the requested path');
                return {comp_id:c.id,output_path:actual.fsName,bytes:actual.length,rendered:true};
            } finally {
                try { if(rq) rq.remove(); }
                finally { for(i=0;i<saved.length;i++) if(saved[i].item.render!==saved[i].render) saved[i].item.render=saved[i].render; }
            }
        }
    };
    function dispatch(raw) {
        var op,undo=false,result; touched=false;
        try {
            var job=AEMCPJSON.parse(raw); op=job.operation;
            if(typeof op!=='string' || !own(operations,op)) fail('Operation is not allowed');
            if(typeof job.expires_at!=='number' || !isFinite(job.expires_at) || job.expires_at<=new Date().getTime()/1000) fail('Job has expired');
            if(op!=='session_info' && op!=='project_info') { app.beginUndoGroup('Adobe MCP: '+op); undo=true; }
            result={success:true,data:operations[op](job.args)};
            if(AEMCPJSON.stringify(result).length>150000) fail('Project response exceeds limit; reduce project size before inspecting');
        } catch(e) { result={success:false,error:{code:'ae_error',message:String(e && e.message?e.message:e).slice(0,1000)},outcome_unknown:touched}; }
        finally { if(undo) { try { app.endUndoGroup(); } catch(undoError) { result={success:false,error:{code:'undo_error',message:'Undo group cleanup failed; inspect After Effects'},outcome_unknown:touched}; } } }
        return AEMCPJSON.stringify(result);
    }
    return {dispatch:dispatch};
}());
