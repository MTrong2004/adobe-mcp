// Quản lý lưu trữ index: lưu cache tăng dần (incremental) tại .agent-memory/index.json bằng hash content.

import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chunkMarkdown } from './extract-docs.mjs';
import { extractCode } from './extract-ts.mjs';
import { makeSecretTools } from './secrets.mjs';
import { git, matcher, readJson, toPosix } from './util.mjs';

export const TOOL_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const INDEX_VERSION = 2;
const MAX_FILE_BYTES = 500_000;

function contentHash(src) {
  return crypto.createHash('sha256').update(src).digest('hex').slice(0, 24);
}

/** Đọc alias import từ tsconfig.json / jsconfig.json (paths). Trả về { "@/": ["", "src/"] }. */
function readTsAliases(root) {
  const out = {};
  for (const name of ["tsconfig.json", "jsconfig.json"]) {
    let txt;
    try {
      txt = fs.readFileSync(path.join(root, name), "utf8");
    } catch {
      continue;
    }
    let json;
    try {
      // tsconfig cho phép comment và dấu phẩy thừa
      // Bỏ comment nhưng giữ nguyên chuỗi (chuỗi như "@/*" hay "**/*.ts" chứa ký tự giống comment).
      const noComments = txt.replace(/"(?:[^"\\]|\\.)*"|\/\/.*|\/\*[\s\S]*?\*\//g, (m) => (m[0] === '"' ? m : ''));
      json = JSON.parse(noComments.replace(/,(\s*[}\]])/g, '$1'));
    } catch {
      continue;
    }
    const co = json.compilerOptions || {};
    const clean = (p) => {
      const n = path.posix.normalize(toPosix(p));
      return n === '.' || n === './' ? '' : n;
    };
    const base = clean(co.baseUrl || '.');
    for (const [key, targets] of Object.entries(co.paths || {})) {
      if (!key.endsWith("/*")) continue;
      const prefix = key.slice(0, -1);
      const list = (targets || [])
        .filter((t) => t.endsWith("/*") || t === "*")
        .map((t) => clean(path.posix.join(base || '.', t.slice(0, -1) || '.')))
        .map((t) => (t && !t.endsWith("/") ? t + "/" : t));
      if (list.length) out[prefix] = [...new Set([...(out[prefix] || []), ...list])];
    }
    break;
  }
  // Mặc định phổ biến khi repo không khai báo paths
  if (!Object.keys(out).length) Object.assign(out, { "@/": ["", "src/"], "~/": ["", "src/"] });
  return out;
}

export function loadConfig(root) {
  const configFile = path.join(TOOL_DIR, 'memory.config.json');
  const raw = readJson(configFile) || {};
  return {
    cacheDir: raw.cacheDir || '.agent-memory',
    memoryDir: raw.memoryDir || 'docs/ai/memory/entries',
    code: raw.code?.include || ['app/**/*.{ts,tsx,css}', 'components/**/*.{ts,tsx}', 'lib/**/*.{ts,tsx}', 'scripts/**/*.{mjs,cjs,js}'],
    docs: raw.docs || [{ glob: 'docs/**/*.md', type: 'doc' }, { glob: 'AGENTS.md', type: 'rule' }],
    exclude: raw.exclude || ['node_modules/**', '.next/**', 'public/gen/**'],
    context: raw.context || { budget: 1800, uiLambda: 0.45, docLambda: 0.55 },
    superseded: raw.superseded || [],
    secretKeys: raw.secretKeys || ['token', 'secret', 'password', 'apiKey', 'auth'],
    synonyms: raw.synonyms || {},
    maintenance: raw.maintenance || {},
    aliases: raw.aliases || readTsAliases(root),
  };
}

export function indexPath(root, cfg) {
  return path.join(root, cfg.cacheDir, 'index.json');
}

/** Liệt kê file trong repo theo git ls-files (fallback duyệt đệ quy thư mục). */
export function listFiles(root, cfg) {
  const out = [];
  const gitOut = git(root, ['ls-files', '--cached', '--others', '--exclude-standard']);
  if (gitOut) {
    const lines = gitOut.split(/\r?\n/).filter(Boolean);
    out.push(...lines.map(toPosix));
    // Repo có thể để docs/ hoặc AGENTS.md ngoài git (.gitignore): tài liệu và bản ghi memory vẫn phải được đánh chỉ mục.
    const roots = [...new Set([cfg.memoryDir, ...cfg.docs.map((d) => d.glob.split(/[*?{[]/)[0].replace(/\/$/, ''))].filter(Boolean))];
    const ignored = git(root, ['ls-files', '--others', '--ignored', '--exclude-standard', '--', ...roots]) || '';
    const seen = new Set(out);
    for (const l of ignored.split(/\r?\n/)) {
      const rel = toPosix(l.trim());
      if (rel && /\.md$/i.test(rel) && !/(^|\/)node_modules\//.test(rel) && !seen.has(rel)) out.push(rel);
    }
  } else {
    // Duyệt thủ công nếu không có git
    const walk = (dir) => {
      for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, ent.name);
        const rel = toPosix(path.relative(root, full));
        if (ent.isDirectory()) {
          if (!rel.startsWith('.') && rel !== 'node_modules') walk(full);
        } else {
          out.push(rel);
        }
      }
    };
    walk(root);
  }
  return out;
}

/** Cập nhật index tăng dần. */
export function updateIndex(root, cfg, { full = false } = {}) {
  const t0 = Date.now();
  const file = indexPath(root, cfg);
  let oldIndex = !full && fs.existsSync(file) ? readJson(file) : null;
  if (oldIndex && oldIndex.version !== INDEX_VERSION) oldIndex = null;

  const isExcluded = matcher(cfg.exclude);
  const isCode = matcher(cfg.code);
  const docMatchers = cfg.docs.map((d) => ({ match: matcher([d.glob]), type: d.type }));

  const allFiles = listFiles(root, cfg);
  const secretTools = makeSecretTools(cfg);

  const newFiles = {};
  let changed = 0;
  let codeCount = 0;
  let docCount = 0;

  for (const rel of allFiles) {
    if (isExcluded(rel)) continue;

    const abs = path.join(root, rel);
    let stat;
    try {
      stat = fs.statSync(abs);
    } catch {
      continue;
    }
    if (!stat.isFile() || stat.size > MAX_FILE_BYTES) continue;

    let docType = null;
    for (const dm of docMatchers) {
      if (dm.match(rel)) {
        docType = dm.type;
        break;
      }
    }

    const codeTarget = isCode(rel);
    if (!docType && !codeTarget) continue;

    let src;
    try {
      src = fs.readFileSync(abs, 'utf8');
    } catch {
      continue;
    }

    const hash = contentHash(src);
    const cached = oldIndex?.files?.[rel];

    if (cached && cached.hash === hash) {
      newFiles[rel] = cached;
      if (cached.f) codeCount++;
      if (cached.d) docCount++;
      continue;
    }

    changed++;
    if (docType) {
      const { meta, chunks } = chunkMarkdown(rel, src, docType, secretTools.redact);
      newFiles[rel] = { hash, mtime: stat.mtimeMs, d: { meta, chunks } };
      docCount++;
    } else if (codeTarget) {
      const info = extractCode(rel, src);
      newFiles[rel] = { hash, mtime: stat.mtimeMs, f: info };
      codeCount++;
    }
  }

  const index = {
    version: INDEX_VERSION,
    updatedAt: new Date().toISOString(),
    files: newFiles,
  };

  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(index), 'utf8');

  return {
    index,
    stats: {
      total: Object.keys(newFiles).length,
      code: codeCount,
      docs: docCount,
      changed,
      ms: Date.now() - t0,
    },
  };
}
