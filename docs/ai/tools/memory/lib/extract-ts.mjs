// Trích xuất mã nguồn TS / TSX / JS / CSS: imports, exports, JSX tags, UI tokens, endpoints, assets.

import { lineOf, maskTs } from './lex.mjs';
import { looksSecret } from './secrets.mjs';
import { tokenize, toPosix } from './util.mjs';

const UI_TOKENS_LIMIT = 60;

/** Phân loại file mã nguồn. */
export function codeKind(rel) {
  if (rel.endsWith('.css')) return 'css';
  if (/scripts\//.test(rel)) return 'script';
  if (/app\/.*\/route\.(ts|js)$/.test(rel)) return 'route';
  if (/app\/.*page\.(tsx|jsx)$/.test(rel)) return 'page';
  if (/app\/.*layout\.(tsx|jsx)$/.test(rel)) return 'layout';
  if (/components\//.test(rel)) return 'component';
  if (/lib\//.test(rel)) return 'lib';
  return 'code';
}

/** Trích xuất chữ tiếng Việt và text người dùng nhìn thấy trong JSX / Strings. */
export function extractUiTokens(src) {
  // Bắt các chuỗi JSX text và thuộc tính nhãn (placeholder, title, aria-label, alt)
  const texts = [];
  
  // Thuộc tính nhãn trong JSX
  for (const m of src.matchAll(/\b(?:placeholder|title|aria-label|alt|label)\s*=\s*["']([^"']+)["']/gi)) {
    texts.push(m[1]);
  }
  
  // Chuỗi tiếng Việt trong string literals (có dấu tiếng Việt)
  for (const m of src.matchAll(/["'`]([^"'`\n]*[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ][^"'`\n]*)["'`]/gi)) {
    texts.push(m[1]);
  }

  // Tách từ, loại bỏ từ bí mật/placeholder, lấy tối đa UI_TOKENS_LIMIT token duy nhất
  const words = texts.join(' ').split(/\s+/).filter((w) => w && !looksSecret(w));
  return [...new Set(tokenize(words.join(' '), { bigrams: false }))].slice(0, UI_TOKENS_LIMIT);
}

/** Trích xuất file CSS. */
export function extractCss(rel, src) {
  const vars = [];
  for (const m of src.matchAll(/(--[\w-]+)\s*:/g)) {
    vars.push(m[1]);
  }
  return {
    l: 'style',
    k: 'css',
    mod: 'styles',
    sym: [...new Set(vars)].slice(0, 30),
    imports: [],
    tags: [],
    assets: [],
    ui: [],
    tokens: tokenize(rel + ' ' + vars.join(' ')),
  };
}

/** Trích xuất file TS/TSX/JS/MJS. */
export function extractCode(rel, src) {
  if (rel.endsWith('.css')) return extractCss(rel, src);

  const kind = codeKind(rel);
  const masked = maskTs(src);

  // 1. Imports
  const imports = [];
  // maskTs che cả nội dung chuỗi nên regex chạy trên src gốc; chỉ nhận vị trí không nằm trong comment/chuỗi.
  for (const m of src.matchAll(/\b(?:import|export)\s+(?:[\w\s{},*]+from\s+)?["']([^"']+)["']/g)) {
    if (masked[m.index] !== src[m.index]) continue;
    imports.push(m[1]);
  }
  for (const m of src.matchAll(/\b(?:require|import)\s*\(\s*["']([^"']+)["']\s*\)/g)) {
    if (masked[m.index] !== src[m.index]) continue;
    imports.push(m[1]);
  }

  // 2. Exported symbols
  const sym = [];
  for (const m of masked.matchAll(/\bexport\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|let|var|type|interface)\s+([A-Za-z0-9_$]+)/g)) {
    sym.push(m[1]);
  }

  // 3. JSX Tags được gọi (Custom Components: <Landing />, <GrowLeaves ...>)
  const tags = new Set();
  for (const m of masked.matchAll(/<([A-Z][a-zA-Z0-9_]*)\b/g)) {
    tags.add(m[1]);
  }

  // 4. Đường dẫn assets được dùng (/assets/..., public/assets/..., docs/ref/...)
  const assets = new Set();
  for (const m of src.matchAll(/(?:public\/|\/|\b)(assets\/[a-zA-Z0-9_\-.]+\.(?:png|jpg|jpeg|webp|svg|mp4|json))/gi)) {
    assets.add('public/' + m[1]);
  }
  for (const m of src.matchAll(/(docs\/ref\/[a-zA-Z0-9_\-.]+\.(?:png|jpg|jpeg|webp|svg))/gi)) {
    assets.add(m[1]);
  }

  // 5. API calls (fetch('/api/...'))
  const endpoints = [];
  for (const m of src.matchAll(/fetch\s*\(\s*["'`]([^"'`?#]+)["'`]/g)) {
    endpoints.push(m[1]);
  }

  // 6. UI tokens
  const ui = extractUiTokens(src);

  // 7. Tokens cho BM25
  const docTokens = tokenize(`${rel} ${sym.join(' ')} ${[...tags].join(' ')}`);

  return {
    l: rel.startsWith('scripts/') ? 'script' : 'fe',
    k: kind,
    mod: rel.split('/')[0],
    sym: [...new Set(sym)],
    imports: [...new Set(imports)],
    tags: [...tags],
    assets: [...assets],
    endpoints,
    ui,
    tokens: docTokens,
  };
}
