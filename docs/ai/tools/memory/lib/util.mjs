// Tiện ích dùng chung: glob, tách từ (bỏ dấu tiếng Việt), git, chuẩn hoá đường dẫn, parse args.

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

/** glob tối giản: ** (nhiều cấp), * (một cấp), ? — so trên đường dẫn dùng '/'. */
export function globToRegex(glob) {
  let re = '';
  for (let i = 0; i < glob.length; i++) {
    const c = glob[i];
    if (c === '*') {
      if (glob[i + 1] === '*') {
        const slash = glob[i + 2] === '/';
        re += slash ? '(?:.*/)?' : '.*';
        i += slash ? 2 : 1;
      } else re += '[^/]*';
    } else if (c === '?') re += '[^/]';
    else if (c === '{') {
      const close = glob.indexOf('}', i);
      re += '(?:' + glob.slice(i + 1, close).split(',').map(escapeRe).join('|') + ')';
      i = close;
    } else re += escapeRe(c);
  }
  return new RegExp('^' + re + '$', 'i');
}

export const escapeRe = (s) => s.replace(/[.+^$()|[\]\\]/g, '\\$&');

export function matcher(globs = []) {
  const res = globs.map(globToRegex);
  return (rel) => res.some((r) => r.test(rel));
}

const STOP = new Set((
  'va cua cho la co khong duoc trong mot nhung cac de khi thi nay do voi tu se da dang ra vao lai nua hay neu nhu ' +
  've theo phai can bang tai nao gi viec cung chi con roi moi hon rat qua ma mo ' +
  'the and for with from this that are is to of in on an it be as by or not if at into via use ' +
  'ts tsx js mjs cjs md html css src app'
).split(' '));

export const fold = (s) =>
  String(s ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[đĐ]/g, 'd').toLowerCase();

/** Tách từ: tách camelCase/PascalCase, bỏ dấu, bỏ stopword; thêm bigram để cụm từ xếp hạng cao hơn. */
export function tokenize(text, { bigrams = true } = {}) {
  const spaced = String(text ?? '')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2');
  const words = fold(spaced).split(/[^a-z0-9]+/).filter((t) => t.length > 1 && !STOP.has(t));
  if (!bigrams) return words;
  const out = words.slice();
  for (let i = 0; i + 1 < words.length; i++) out.push(words[i] + '_' + words[i + 1]);
  return out;
}

/** Mở rộng truy vấn bằng bảng đồng nghĩa Việt ↔ Anh. */
export function expandQuery(text, synonyms = {}) {
  const f = ' ' + fold(text).replace(/[^a-z0-9]+/g, ' ') + ' ';
  const extra = [];
  for (const [vi, ens] of Object.entries(synonyms)) {
    const key = ' ' + fold(vi) + ' ';
    const list = Array.isArray(ens) ? ens : [ens];
    let matched = f.includes(key);
    if (matched) extra.push(...list);
    else if (list.some((en) => f.includes(' ' + fold(en).replace(/[^a-z0-9]+/g, ' ') + ' '))) extra.push(vi);
  }
  return extra.length ? `${text} ${extra.join(' ')}` : text;
}

export function git(root, args, opts = {}) {
  try {
    return execFileSync('git', args, {
      cwd: root, encoding: 'utf8', maxBuffer: 512 * 1024 * 1024, stdio: ['ignore', 'pipe', 'ignore'], ...opts,
    });
  } catch {
    return null;
  }
}

export const toPosix = (p) => String(p ?? '').replace(/\\/g, '/');

/** Chuẩn hoá đường dẫn file tương đối so với gốc repo. */
export function relPath(root, p) {
  const abs = path.isAbsolute(p) ? p : path.resolve(root, p);
  return toPosix(path.relative(root, abs));
}

/** Chuẩn hoá route/url. */
export function normPath(p) {
  let s = String(p ?? '').trim().replace(/^~?\//, '/').replace(/^https?:\/\/[^/]+/i, '');
  s = s.replace(/[?#].*$/, '');
  return s.toLowerCase().replace(/\/+$/, '') || '/';
}

export const first = (v) => (Array.isArray(v) ? v[0] : v);
export const list = (v) => (Array.isArray(v) ? v : v == null ? [] : [v]);

/** CLI args parser đơn giản: --foo bar, --foo=bar, --flag, positional args. */
export function parseArgs(argv) {
  const args = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg.startsWith('--')) {
      const eq = arg.indexOf('=');
      if (eq > 2) {
        const key = arg.slice(2, eq);
        const val = arg.slice(eq + 1);
        if (args[key] !== undefined) {
          args[key] = Array.isArray(args[key]) ? [...args[key], val] : [args[key], val];
        } else {
          args[key] = val;
        }
      } else {
        const key = arg.slice(2);
        const next = argv[i + 1];
        if (next !== undefined && !next.startsWith('--')) {
          if (args[key] !== undefined) {
            args[key] = Array.isArray(args[key]) ? [...args[key], next] : [args[key], next];
          } else {
            args[key] = next;
          }
          i++;
        } else {
          args[key] = true;
        }
      }
    } else if (arg.startsWith('-') && arg.length > 1) {
      args[arg.slice(1)] = true;
    } else {
      args._.push(arg);
    }
  }
  return args;
}

export function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return null;
  }
}
