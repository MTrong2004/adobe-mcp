// Ghi nhận memory sau task: tổng hợp thay đổi git, quyết định, bài học.

import fs from 'node:fs';
import path from 'node:path';
import { makeSecretTools } from './secrets.mjs';
import { fold, git, toPosix } from './util.mjs';

export const slugify = (s) =>
  fold(s).replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) || 'entry';

/** Lấy danh sách file thay đổi trong git (staged + unstaged + untracked). */
export function changedFiles(root, since = null) {
  const out = new Set();
  if (since) {
    const lines = git(root, ['diff', '--name-only', since]) ?? '';
    for (const l of lines.split('\n')) if (l.trim()) out.add(toPosix(l.trim()));
  }
  const status = git(root, ['status', '--porcelain']) ?? '';
  for (const l of status.split('\n')) {
    if (l.length >= 4) {
      out.add(toPosix(l.slice(3).trim()));
    }
  }
  return [...out];
}

const MEDIA_RE = /\.(png|jpe?g|webp|gif|avif|svg|ico|psd|ai|mp4|webm|mov|mp3|wav|woff2?|ttf|otf|zip|pdf|lock|log)$/i;
export const MAX_RECORD_FILES = 10;

/**
 * Lọc danh sách file từ working tree: bỏ thư mục, ảnh/media, file nháp, cache và chính các bản ghi memory;
 * ưu tiên file được nhắc tên trong nội dung bản ghi; giữ tối đa MAX_RECORD_FILES.
 * (Working tree bẩn từng khiến mỗi bản ghi kèm hàng trăm file không liên quan.)
 */
export function relevantFiles(files, text = '', cfg = {}) {
  const memDir = (cfg.memoryDir || 'docs/ai/memory/entries').replace(/\/$/, '');
  const kept = [...new Set(files)].filter(
    (f) =>
      f &&
      !f.endsWith('/') &&
      !MEDIA_RE.test(f) &&
      !f.startsWith(memDir + '/') &&
      !f.startsWith('.agent-memory/') &&
      !/(^|\/)(scratch|tmp|temp)[^/]*$/i.test(f) &&
      !/(^|\/)(node_modules|\.next|dist|build)\//.test(f),
  );
  const hay = fold(text);
  const stem = (f) => fold(f.split('/').pop().replace(/\.[^.]+$/, ''));
  const named = kept.filter((f) => stem(f).length > 2 && hay.includes(stem(f)));
  // Có file được nhắc tên thì chỉ giữ các file đó; không thì chỉ giữ khi danh sách đủ ngắn để còn ý nghĩa.
  const picked = named.length ? named : kept.length <= MAX_RECORD_FILES ? kept : [];
  return picked.slice(0, MAX_RECORD_FILES);
}

/** Tạo nội dung bản ghi markdown. */
export function buildRecord(root, cfg, opts = {}) {
  const secretTools = makeSecretTools(cfg);
  const title = String(opts.title || 'Cập nhật tác vụ').trim();
  const summary = String(opts.summary || '').trim();
  const type = opts.type || 'task';
  const decisions = opts.decision ? (Array.isArray(opts.decision) ? opts.decision : [opts.decision]) : [];
  const lessons = opts.lesson ? (Array.isArray(opts.lesson) ? opts.lesson : [opts.lesson]) : [];
  const explicitFiles = opts.files
    ? (Array.isArray(opts.files) ? opts.files : opts.files.split(',')).map((f) => toPosix(f.trim()))
    : null;

  const targetFiles =
    explicitFiles && explicitFiles.length > 0
      ? explicitFiles
      : relevantFiles(changedFiles(root), [title, summary, ...decisions, ...lessons].join(' '), cfg);
  // Ngày theo giờ máy (toISOString là UTC nên lệch ngày vào sáng sớm ở UTC+7).
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  const slug = slugify(title);
  const fileName = `${today}-${slug}.md`;
  const relPath = path.posix.join(cfg.memoryDir, fileName);

  const clean = (s) => secretTools.redact(s).text.trim();

  const lines = [];
  lines.push('---');
  lines.push(`type: ${type}`);
  lines.push(`date: ${today}`);
  lines.push(`title: "${clean(title).replace(/"/g, '\\"')}"`);
  lines.push(`files: [${targetFiles.map((f) => `"${f}"`).join(', ')}]`);
  lines.push(`tags: [${type}, memory]`);
  // Bản ghi này thay cho tài liệu / bản ghi cũ nào: khi tra, bản cũ bị hạ hạng và gắn cảnh báo.
  const supersedes = opts.supersedes
    ? (Array.isArray(opts.supersedes) ? opts.supersedes : String(opts.supersedes).split(',')).map((f) => toPosix(f.trim())).filter(Boolean)
    : [];
  if (supersedes.length) lines.push(`supersedes: [${supersedes.map((f) => `"${f}"`).join(', ')}]`);
  lines.push('---');
  lines.push('');
  lines.push(`# ${clean(title)}`);
  lines.push('');

  lines.push('## Tóm tắt');
  lines.push(clean(summary) || '_Không có mô tả chi tiết._');
  lines.push('');

  if (targetFiles.length > 0) {
    lines.push('## File liên quan');
    for (const f of targetFiles) {
      lines.push(`- \`${f}\``);
    }
    lines.push('');
  }

  if (decisions.length > 0) {
    lines.push('## Quyết định');
    for (const d of decisions) {
      lines.push(`- ${clean(d)}`);
    }
    lines.push('');
  }

  if (lessons.length > 0) {
    lines.push('## Bài học');
    for (const l of lessons) {
      lines.push(`- ${clean(l)}`);
    }
    lines.push('');
  }

  const content = lines.join('\n');
  return { relPath, fileName, content };
}

/** Lưu bản ghi vào đĩa. */
export function writeRecord(root, record) {
  const absPath = path.join(root, record.relPath);
  fs.mkdirSync(path.dirname(absPath), { recursive: true });
  fs.writeFileSync(absPath, record.content, 'utf8');
}
