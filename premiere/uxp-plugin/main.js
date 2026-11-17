'use strict';
const ppro = require('premierepro');
const fs = require('fs');
const {createDispatcher} = require('./dispatcher.js');
const {BridgeLoop} = require('./client.js');
// Official UXP FSAPI uses fs.lstat(path) returning a Promise (no Node promises namespace).
const io = {async stat(path) {
  try { const info = await fs.lstat(path); return {size: info.isFile() ? info.size : 0}; }
  catch (err) { if (err && err.code === 'ENOENT') return null; throw err; }
}};
const status = document.getElementById('status');
const token = document.getElementById('token');
const loop = new BridgeLoop({fetch: (...args) => fetch(...args), dispatch:createDispatcher(ppro,io,require('uxp').host), status:text => {status.textContent=text;}});
document.getElementById('connect').addEventListener('click', () => {
  try { loop.configure(token.value); token.value=''; void loop.start(); }
  catch (err) { status.textContent=err.message; }
});
document.getElementById('disconnect').addEventListener('click', () => {loop.stop(); status.textContent='Đã dừng nhận. Chờ thao tác đang chạy hoàn tất trước khi đóng bảng.';});
require('uxp').entrypoints.setup({panels:{premiereMcp:{show(){}, hide(){ /* Keep receipt and serial operation alive while panel hides. */ }}}});
