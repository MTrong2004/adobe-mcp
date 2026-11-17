'use strict';
const {fail} = require('./dispatcher.js');
// No host operation retry. Receipt retries only, until authenticated broker acknowledgment.
class BridgeLoop {
  constructor({fetch, dispatch, status = () => {}, now = () => Date.now()/1000}) {
    this.fetch = fetch; this.dispatch = dispatch; this.status = status; this.now = now;
    this.pending = null; this.seen = new Set(); this.running = false; this.inFlight = false; this.loopActive = false; this.generation = 0;
    this.token = ''; this.base = 'http://127.0.0.1:8768';
  }
  configure(token) {
    if (this.inFlight || this.running || this.loopActive) throw new Error('Stop connection and wait for the current operation first');
    if (this.pending && this.token !== token) throw new Error('A result awaits acknowledgment; reconnect with the same token');
    if (typeof token !== 'string' || token.length < 32 || /\s/.test(token)) throw new Error('Mã kết nối không hợp lệ');
    this.token = token;
  }
  async request(endpoint, payload) {
    // UXP compatibility: prefer modern deadline API; older embedded engines need a controller.
    let timer;
    const options = {method:payload ? 'POST':'GET', headers:{Authorization:'Bearer '+this.token, 'Content-Type':'application/json'}};
    if (payload) options.body = JSON.stringify(payload);
    if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') options.signal = AbortSignal.timeout(5000);
    else if (typeof AbortController !== 'undefined') {
      const controller = new AbortController(); options.signal = controller.signal;
      timer = setTimeout(() => controller.abort(), 5000);
    }
    // With no AbortController at all, keep the serial request pending rather than racing it and polling twice.
    try {
      const response = await this.fetch(this.base+endpoint, options);
      if (!response.ok) throw new Error('Không thể kết nối ('+response.status+')');
      return await response.json();
    } finally { if (timer) clearTimeout(timer); }
  }
  async tick() {
    if (this.inFlight) return;
    this.inFlight = true;
    const generation = this.generation;
    try {
      if (this.pending) {
        const ack = await this.request('/result', this.pending);
        if (!ack || ack.success !== true) throw new Error('Đang giữ kết quả; chưa được xác nhận');
        this.pending = null;
        return;
      }
      const health = await this.request('/health');
      if (!health || health.success !== true || health.app !== 'premiere' || health.protocol !== 1) throw new Error('Dịch vụ không đúng ứng dụng hoặc phiên bản');
      const next = await this.request('/next');
      if (!next || !Object.prototype.hasOwnProperty.call(next,'job')) throw new Error('Phản hồi công việc không hợp lệ');
      const job = next.job;
      if (!job) { this.status('Đã kết nối. Sẵn sàng nhận thao tác.'); return; }
      if (!job || typeof job.id !== 'string' || !job.id || typeof job.operation !== 'string' || !job.args || typeof job.args !== 'object' || Array.isArray(job.args) || typeof job.expires_at !== 'number' || !Number.isFinite(job.expires_at)) throw new Error('Công việc không hợp lệ');
      if (this.seen.has(job.id)) {
        // Cannot reconstruct an acknowledged result; never execute a duplicate ID.
        this.pending = {id:job.id,result:fail('duplicate_job','Job ID already executed in this panel session',true)};
        return;
      }
      this.seen.add(job.id);
      if (this.seen.size > 20000) { this.running = false; this.status('Phiên đã đạt giới hạn; dừng kết nối sau khi gửi kết quả.'); }
      let result;
      if (generation !== this.generation) result = fail('cancelled','Stopped before host execution',false);
      else if (job.expires_at <= this.now()) result = fail('expired','Job expired before execution',false);
      else {
        this.status('Đang thực hiện thao tác trong Premiere…');
        try { result = await this.dispatch(job.operation,job.args); }
        catch (_) { result = fail('host_error','Host execution rejected; inspect Premiere before retrying',true); }
        if (!result || typeof result !== 'object' || Array.isArray(result)) result = fail('invalid_result','Host returned an invalid result',true);
      }
      this.pending = {id:job.id,result};
      this.status('Đang chờ xác nhận kết quả…');
    } finally { this.inFlight = false; }
  }
  async start() {
    if (this.running || this.loopActive) return;
    this.running = true;
    this.loopActive = true;
    try { while (this.running) {
      try { await this.tick(); }
      catch (_) { this.status(this.pending ? 'Mất kết nối. Kết quả đang được giữ; sẽ gửi lại khi kết nối phục hồi.' : 'Chưa kết nối. Kiểm tra dịch vụ và mã kết nối.'); }
      if (this.running) await new Promise(resolve => setTimeout(resolve,500));
    } } finally { this.loopActive = false; }
  }
  stop() { this.running = false; this.generation++; }
}
module.exports = {BridgeLoop};
