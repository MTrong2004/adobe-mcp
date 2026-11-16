// Dọn kho memory: gộp bản ghi nhật ký (type: task, không có Quyết định / Bài học) thành file theo ngày,
// cắt gọn danh sách file thừa; và kiểm tra ngưỡng để nhắc chủ dự án dọn.

import fs from 'node:fs';
import path from 'node:path';
import { relevantFiles, MAX_RECORD_FILES } from './record.mjs';

const VALUE_TYPES = new Set(['bugfix', 'decision', 'lesson', 'visual-rule']);
const LIST_HEADING = /^(thay đổi|file liên quan)$/i;

function parse(src) {
  const m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(src);
  if (!m) return null;
  const meta = {};
  for (const line of m[1].split(/\r?\n/)) {
    const kv = /^(\w[\w-]*):\s*(.*)$/.exec(line);
    if (kv) meta[kv[1]] = kv[2];
  }
  const sections = [];
  let cur = { heading: '', lines: [] };
  for (const line of src.slice(m[0].length).split(/\r?\n/)) {
    const h = /^##\s+(.+)$/.exec(line);
    if (h) {
      sections.push(cur);
      cur = { heading: h[1].trim(), lines: [] };
    } else cur.lines.push(line);
  }
  sections.push(cur);
  return { meta, sections };
}

const unquote = (s) => String(s || '').replace(/^"|"$/g, '').replace(/\\"/g, '"');
const listOf = (s) => [...String(s || '').matchAll(/"([^"]+)"/g)].map((x) => x[1]);
const textOf = (p, re) => {
  const s = p.sections.find((x) => re.test(x.heading));
  return s ? s.lines.join('\n').trim() : '';
};

/** Gộp và cắt gọn. dry = true thì chỉ đếm, không ghi. */
export function compact(root, cfg, { dry = false } = {}) {
  const dir = path.join(root, cfg.memoryDir);
  const stats = { merged: 0, trimmed: 0, kept: 0, days: 0, total: 0, kbBefore: 0, kbAfter: 0 };
  if (!fs.existsSync(dir)) return stats;
  const digests = new Map();
  let before = 0;
  let after = 0;

  for (const name of fs.readdirSync(dir).filter((f) => f.endsWith('.md')).sort()) {
    const file = path.join(dir, name);
    const src = fs.readFileSync(file, 'utf8');
    stats.total++;
    before += src.length;
    const p = parse(src);
    if (!p || p.meta.type === 'log') {
      stats.kept++;
      after += src.length;
      continue;
    }
    const title = unquote(p.meta.title) || name.replace(/\.md$/, '');
    const date = p.meta.date || name.slice(0, 10);
    const summary = textOf(p, /^tóm tắt$/i);
    const decision = textOf(p, /quyết định/i);
    const lesson = textOf(p, /bài học/i);
    const rawFiles = listOf(p.meta.files);
    const valuable = VALUE_TYPES.has(p.meta.type) || decision || lesson;

    if (!valuable) {
      const files = relevantFiles(rawFiles, [title, summary].join(' '), cfg);
      if (!digests.has(date)) digests.set(date, []);
      digests.get(date).push({ title, summary, files });
      stats.merged++;
      if (!dry) fs.unlinkSync(file);
      continue;
    }

    // Danh sách file đã gọn (bản ghi mới hoặc đã dọn) thì giữ nguyên, không lọc lại.
    const hasList = p.sections.some((s) => LIST_HEADING.test(s.heading));
    const oldStyle = p.sections.some((s) => /^thay đổi$/i.test(s.heading));
    if (rawFiles.length <= MAX_RECORD_FILES && !oldStyle) {
      stats.kept++;
      after += src.length;
      continue;
    }
    const files = relevantFiles(rawFiles, [title, summary, decision, lesson].join(' '), cfg);
    const out = ['---'];
    for (const [k, v] of Object.entries(p.meta)) {
      out.push(k === 'files' ? `files: [${files.map((f) => `"${f}"`).join(', ')}]` : `${k}: ${v}`);
    }
    out.push('---', '');
    for (const s of p.sections) {
      if (LIST_HEADING.test(s.heading)) {
        if (files.length) out.push('## File liên quan', ...files.map((f) => `- \`${f}\``), '');
        continue;
      }
      if (s.heading) out.push(`## ${s.heading}`);
      out.push(...s.lines);
    }
    if (!hasList && files.length) out.push('', '## File liên quan', ...files.map((f) => `- \`${f}\``));
    const next = out.join('\n').replace(/\n{3,}/g, '\n\n').trimEnd() + '\n';
    after += next.length;
    if (next !== src) {
      stats.trimmed++;
      if (!dry) fs.writeFileSync(file, next);
    } else stats.kept++;
  }

  for (const [date, items] of digests) {
    const file = path.join(dir, `${date}-nhat-ky.md`);
    // Đã có nhật ký ngày đó thì nối thêm, không ghi đè.
    const prev = fs.existsSync(file) ? fs.readFileSync(file, 'utf8').trimEnd() : null;
    const out = prev
      ? [prev, '']
      : ['---', 'type: log', `date: ${date}`, `title: "Nhat ky ${date}"`, 'tags: [log, memory]', '---', '', `# Nhật ký ${date} (đã gộp)`, ''];
    for (const it of items) {
      out.push(`### ${it.title}`, it.summary || '_Không có mô tả._');
      if (it.files.length) out.push(`File: ${it.files.map((f) => `\`${f}\``).join(', ')}`);
      out.push('');
    }
    const body = out.join('\n');
    after += body.length - (prev ? prev.length : 0);
    if (!dry) fs.writeFileSync(file, body);
  }
  stats.days = digests.size;
  stats.kbBefore = Math.round(before / 1024);
  stats.kbAfter = Math.round(after / 1024);
  return stats;
}

const DEFAULT_LIMITS = { cleanable: 10, sizeKb: 600, entries: 400, remindEveryDays: 3 };

/**
 * Kiểm tra kho có cần dọn không. Trả về null nếu chưa tới ngưỡng hoặc vừa nhắc gần đây.
 * Ngưỡng chỉnh trong memory.config.json: "maintenance": { cleanable, sizeKb, entries, remindEveryDays }.
 */
export function health(root, cfg, { force = false } = {}) {
  const limits = { ...DEFAULT_LIMITS, ...(cfg.maintenance || {}) };
  const s = compact(root, cfg, { dry: true });
  const cleanable = s.merged + s.trimmed;
  const reasons = [];
  if (cleanable >= limits.cleanable) {
    reasons.push(`${cleanable} bản ghi dọn tự động được (gộp ${s.merged} bản nhật ký, cắt gọn ${s.trimmed} bản), giảm khoảng ${s.kbBefore - s.kbAfter} KB`);
  }
  const autoFix = reasons.length > 0;
  if (s.kbAfter > limits.sizeKb) reasons.push(`kho nặng ${s.kbBefore} KB (ngưỡng ${limits.sizeKb} KB)`);
  if (s.total - s.merged > limits.entries) reasons.push(`kho có ${s.total} bản ghi (ngưỡng ${limits.entries})`);
  if (!reasons.length) return null;

  // Không nhắc dồn dập: mỗi remindEveryDays ngày một lần.
  const stamp = path.join(root, cfg.cacheDir, 'maintenance.json');
  if (!force) {
    try {
      const last = JSON.parse(fs.readFileSync(stamp, 'utf8')).lastReminder;
      if (Date.now() - last < limits.remindEveryDays * 86_400_000) return null;
    } catch {}
    try {
      fs.mkdirSync(path.dirname(stamp), { recursive: true });
      fs.writeFileSync(stamp, JSON.stringify({ lastReminder: Date.now() }));
    } catch {}
  }
  return { reasons, autoFix, stats: s };
}

/** Lời nhắc chèn vào cuối kết quả `context` để agent hỏi chủ dự án. */
export function healthNotice(h) {
  if (!h) return '';
  const lines = ['', '## ⚠ Kho memory cần dọn', `Lý do: ${h.reasons.join('; ')}.`];
  lines.push(
    '**Việc của agent:** báo chủ dự án một câu ngắn bằng tiếng Việt (nêu lý do trên) và HỎI có muốn dọn không. KHÔNG tự chạy lệnh dọn khi chưa được đồng ý.',
  );
  if (h.autoFix) {
    lines.push('Nếu chủ dự án đồng ý: chạy `node docs/ai/tools/memory/mem.mjs compact`, rồi `node docs/ai/tools/memory/mem.mjs audit`, và báo lại số bản đã gộp/cắt.');
  }
  if (h.reasons.length > (h.autoFix ? 1 : 0)) {
    lines.push('Phần vượt ngưỡng không dọn tự động được: đề xuất với chủ dự án danh sách bản ghi cũ, trùng ý hoặc đã lỗi thời để gộp/xoá; chỉ làm sau khi chủ dự án duyệt danh sách.');
  }
  return lines.join('\n');
}
