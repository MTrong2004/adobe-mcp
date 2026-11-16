'use strict';
const { entrypoints } = require('uxp');
const { createDispatcher } = require('./dispatcher.js');
const { createClient } = require('./client.js');
const tokenInput = document.getElementById('token');
const connectButton = document.getElementById('connect');
const disconnectButton = document.getElementById('disconnect');
const statusText = document.getElementById('status');
const client = createClient({
  dispatch: createDispatcher(require('photoshop')),
  status(message, running, busy) {
    if (message !== null && statusText.textContent !== message) statusText.textContent = message;
    connectButton.disabled = running || busy;
    disconnectButton.disabled = !running;
    tokenInput.disabled = running || busy;
  }
});
connectButton.addEventListener('click', async () => {
  const secret = tokenInput.value;
  tokenInput.value = '';
  if (!secret || /[\s\x00-\x1f\x7f]/.test(secret)) {
    tokenInput.setAttribute('aria-invalid', 'true');
    statusText.textContent = 'Nhập token không chứa khoảng trắng từ bridge Python.';
    tokenInput.focus();
    return;
  }
  tokenInput.removeAttribute('aria-invalid');
  await client.connect(secret);
});
tokenInput.addEventListener('input', () => tokenInput.removeAttribute('aria-invalid'));
function disconnect() {
  tokenInput.value = '';
  client.disconnect();
}
disconnectButton.addEventListener('click', disconnect);
entrypoints.setup({
  plugin: { destroy: disconnect },
  panels: { bridgePanel: { hide: disconnect, destroy: disconnect } }
});
