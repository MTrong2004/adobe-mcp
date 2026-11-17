(function () {
    'use strict';
    var status=document.getElementById('status'), token=document.getElementById('token'), connect=document.getElementById('connect'), disconnect=document.getElementById('disconnect');
    var host=AEMCPPanel.createHost(window.__adobe_cep__);
    var client=AEMCPPanel.createClient({dispatch:host.dispatch,status:function(message,running,busy) {
        if(message!==null) status.textContent=message;
        connect.disabled=running||busy; disconnect.disabled=!running; token.disabled=running||busy;
    }});
    document.getElementById('connection').addEventListener('submit',function(e) { e.preventDefault(); client.connect(token.value).then(function() { token.value=''; }).catch(function() { status.textContent='Token không hợp lệ. Kiểm tra token và thử lại.'; }); });
    disconnect.addEventListener('click',client.disconnect);
    host.load().then(function() { connect.disabled=false; status.textContent='Sẵn sàng. Nhập token để kết nối.'; }).catch(function() { status.textContent='Không tải được After Effects. Mở panel từ menu Window > Extensions trong After Effects.'; });
}());
