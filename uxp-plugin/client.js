'use strict';
const BASE_URL = 'http://127.0.0.1:8766';

// UXP supports XHR; use its native timeout instead of assuming AbortController support.
function request(path, token, body) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(body === undefined ? 'GET' : 'POST', BASE_URL + path);
    xhr.timeout = 5000;
    xhr.setRequestHeader('Authorization', 'Bearer ' + token);
    if (body !== undefined) xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        const error = new Error('HTTP request failed');
        error.status = xhr.status;
        reject(error);
        return;
      }
      try { resolve(JSON.parse(xhr.responseText)); }
      catch (_) { reject(new Error('Invalid bridge JSON')); }
    };
    xhr.onerror = () => reject(new Error('Bridge unavailable'));
    xhr.ontimeout = () => reject(new Error('Bridge timeout'));
    xhr.onabort = () => reject(new Error('Request cancelled'));
    xhr.send(body === undefined ? null : JSON.stringify(body));
  });
}
function createClient({ dispatch, transport = request, status = () => {}, schedule = setTimeout, cancel = clearTimeout }) {
  let token = '';
  let running = false;
  let busy = false;
  let timer = null;
  let generation = 0;
  let pending = null;
  // In-memory receipts survive disconnect/reconnect and prevent accidental job replay.
  const receipts = new Map();
  function report(message) { status(message, running, busy); }
  function disconnect() {
    running = false;
    token = '';
    generation++;
    if (timer !== null) cancel(timer);
    timer = null;
    report(pending ? 'Đã ngắt kết nối. Kết quả đang chờ gửi được giữ trong bộ nhớ.' : 'Đã ngắt kết nối.');
  }
  async function connect(secret) {
    if (running || busy) return;
    if (typeof secret !== 'string' || !secret || /[\s\x00-\x1f\x7f]/.test(secret)) throw new Error('Token không hợp lệ.');
    token = secret;
    running = true;
    const epoch = ++generation;
    busy = true;
    report('Đang kiểm tra kết nối…');
    try {
      const health = await transport('/health', token);
      if (epoch !== generation) return;
      if (health.success !== true || health.protocol !== 1) throw new Error('Incompatible protocol');
      report('Đã kết nối. Đang chờ yêu cầu.');
    } catch (_) {
      if (epoch === generation) {
        running = false;
        token = '';
        report('Không kết nối được. Kiểm tra bridge và token.');
      }
    } finally {
      busy = false;
      if (epoch === generation && running) timer = schedule(tick, 500);
      reportCurrent();
    }
  }
  // Do not replace useful status text when only button availability changes.
  function reportCurrent() { status(null, running, busy); }
  async function tick() {
    timer = null;
    if (!running || busy) return;
    const epoch = generation;
    busy = true;
    reportCurrent();
    try {
      if (!pending) {
        const response = await transport('/next', token);
        if (epoch !== generation) return;
        if (!response || !Object.prototype.hasOwnProperty.call(response, 'job')) throw new Error('Invalid next response');
        if (response.job !== null) {
          const job = response.job;
          if (!job || typeof job.id !== 'string' || !job.id || job.id.length > 256) {
            disconnect();
            report('Bridge trả về mã yêu cầu không hợp lệ. Đã dừng.');
            return;
          }
          if (receipts.has(job.id)) pending = receipts.get(job.id);
          else {
            try { pending = { id: job.id, result: await dispatch(job) }; }
            catch (error) { pending = { id: job.id, error: String(error.message || 'Operation failed').slice(0, 1000) }; }
            receipts.set(job.id, pending);
          }
        }
      }
      if (epoch !== generation) return;
      if (pending) {
        const receipt = await transport('/result', token, pending);
        if (epoch !== generation) return;
        if (!receipt || receipt.success !== true) throw new Error('Invalid result acknowledgement');
        pending = null;
        report('Đã gửi kết quả. Đang chờ yêu cầu.');
      }
    } catch (error) {
      if (epoch !== generation) return;
      if (error.status >= 400 && error.status < 500) {
        disconnect();
        report('Bridge từ chối yêu cầu. Đã dừng; kiểm tra token hoặc bridge vừa khởi động lại.');
      } else report(pending ? 'Mất kết nối. Chỉ thử gửi lại kết quả, không chạy lại thao tác.' : 'Chưa liên lạc được với bridge. Đang thử lại.');
    } finally {
      busy = false;
      reportCurrent();
      if (running && epoch === generation) timer = schedule(tick, 500);
    }
  }
  return { connect, disconnect, tick };
}
module.exports = { createClient, BASE_URL };
