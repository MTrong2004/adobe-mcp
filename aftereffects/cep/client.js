/* CEP Chromium client; Promise + XHR are supported by CEP 11/12. */
(function(root) {
    'use strict';
    var BASE='http://127.0.0.1:8767';
    function request(path,token,body) {
        return new Promise(function(resolve,reject) {
            var xhr=new XMLHttpRequest(); xhr.open(body===undefined?'GET':'POST',BASE+path); xhr.timeout=5000;
            xhr.setRequestHeader('Authorization','Bearer '+token);
            if(body!==undefined) xhr.setRequestHeader('Content-Type','application/json');
            xhr.onload=function() { if(xhr.status<200 || xhr.status>=300) { var e=new Error('Bridge HTTP error'); e.status=xhr.status; reject(e); return; } try { resolve(JSON.parse(xhr.responseText)); } catch(e) { reject(new Error('Invalid bridge JSON')); } };
            xhr.onerror=xhr.ontimeout=xhr.onabort=function() { reject(new Error('Bridge unavailable')); };
            xhr.send(body===undefined?null:JSON.stringify(body));
        });
    }
    function literal(value) { return JSON.stringify(value).replace(/\u2028/g,'\\u2028').replace(/\u2029/g,'\\u2029'); }
    function createHost(cep) {
        function evaluate(script) { return new Promise(function(resolve,reject) { if(!cep || typeof cep.evalScript!=='function') { reject(new Error('Open this panel inside After Effects')); return; } cep.evalScript(script,function(result) { if(result==='EvalScript error.') reject(new Error('After Effects script failed')); else resolve(result); }); }); }
        return {
            load:function() {
                var path=decodeURI(cep.getSystemPath('extension')).replace(/^file:\/\//,'').replace(/^\/(?:([A-Za-z]:))/, '$1');
                // Only fixed, packaged file names reach $.evalFile; no caller-supplied scripts.
                return evaluate('(function(){try{$.evalFile(new File('+literal(path+'/jsx/json.jsx')+'));$.evalFile(new File('+literal(path+'/jsx/dispatcher.jsx')+'));return "ready";}catch(e){return "load failed";}}())').then(function(v) { if(v!=='ready') throw new Error('Cannot load packaged After Effects dispatcher'); });
            },
            dispatch:function(job) { return evaluate('AEMCP.dispatch('+literal(JSON.stringify(job))+')').then(function(v) { var result=JSON.parse(v); if(!result || typeof result!=='object' || Array.isArray(result)) throw new Error('Invalid host result'); return result; }); }
        };
    }
    function createClient(options) {
        var transport=options.transport||request,schedule=options.schedule||setTimeout,cancel=options.cancel||clearTimeout,status=options.status||function(){},dispatch=options.dispatch;
        var running=false,busy=false,token='',timer=null,generation=0,pending=null,receipts=Object.create(null),receiptCount=0;
        function remember(job,result) { pending={id:job.id,result:result}; receipts[job.id]=pending; receiptCount++; }
        function failure(code,message,unknown) { return {success:false,error:{code:code,message:message},outcome_unknown:unknown}; }
        function report(message) { status(message,running,busy); }
        function disconnect() { running=false; generation++; if(timer!==null) cancel(timer); timer=null; report(pending?'Đã ngắt; kết quả chờ gửi vẫn được giữ.':'Đã ngắt kết nối.'); }
        function connect(secret) {
            if(running || busy) return Promise.resolve();
            if(typeof secret!=='string' || secret.length<32 || secret.length>512 || /[\s\x00-\x1f\x7f]/.test(secret)) return Promise.reject(new Error('Token không hợp lệ.'));
            if(pending && token!==secret) return Promise.reject(new Error('Kết quả đang chờ xác nhận; hãy dùng token cũ.'));
            token=secret; running=true; busy=true; var epoch=++generation; report('Đang kiểm tra kết nối…');
            return transport('/health',token).then(function(v) { if(epoch!==generation) return; if(!v || v.success!==true || v.protocol!==1 || v.app!=='aftereffects') throw new Error('Bridge protocol mismatch'); report('Đã kết nối. Đang chờ yêu cầu.'); }).catch(function() { if(epoch===generation) { running=false; if(!pending) token=''; report('Không kết nối được. Kiểm tra bridge và token.'); } }).then(function() { busy=false; report(null); if(running && epoch===generation) timer=schedule(tick,500); });
        }
        function tick() {
            timer=null; if(!running || busy) return Promise.resolve(); busy=true; report(null); var epoch=generation;
            return Promise.resolve().then(function() {
                if(pending) return;
                if(receiptCount>=2000) { disconnect(); report('Phiên đã đạt giới hạn. Mở lại panel sau khi kiểm tra mọi kết quả.'); return; }
                return transport('/next',token).then(function(response) {
                    if(!response || !Object.prototype.hasOwnProperty.call(response,'job')) throw new Error('Invalid next response');
                    var job=response.job; if(job===null) return;
                    if(!job || typeof job.id!=='string' || !job.id || job.id.length>256) { disconnect(); throw new Error('Invalid job ID'); }
                    if(receipts[job.id]) { pending=receipts[job.id]; return; }
                    return Promise.resolve().then(function() {
                        if(epoch!==generation) return failure('cancelled','Stopped before host execution',false);
                        if(typeof job.expires_at!=='number' || !isFinite(job.expires_at) || job.expires_at<=Date.now()/1000) return {success:false,error:{code:'expired',message:'Job expired before execution'}};
                        return dispatch(job);
                    }).catch(function() { return failure('host_error','After Effects operation failed; inspect app before retrying',true); }).then(function(result) { remember(job,result); });
                });
            }).then(function() {
                if(epoch!==generation || !pending) return;
                return transport('/result',token,pending).then(function(ack) { if(epoch!==generation) return; if(!ack || ack.success!==true) throw new Error('Invalid acknowledgement'); pending=null; report('Đã gửi kết quả. Đang chờ yêu cầu.'); });
            }).catch(function(e) {
                if(epoch!==generation) return;
                if(e && e.status>=400 && e.status<500) { disconnect(); report('Bridge từ chối. Kiểm tra token; kết quả chưa gửi vẫn được giữ.'); }
                else report(pending?'Mất kết nối; chỉ gửi lại kết quả, không chạy lại.':'Chưa liên lạc được với bridge. Đang thử lại.');
            }).then(function() { busy=false; report(null); if(running && epoch===generation) timer=schedule(tick,500); });
        }
        return {connect:connect,disconnect:disconnect,tick:tick};
    }
    var api={createClient:createClient,createHost:createHost,literal:literal,request:request};
    if(typeof module!=='undefined' && module.exports) module.exports=api;
    root.AEMCPPanel=api;
}(this));
