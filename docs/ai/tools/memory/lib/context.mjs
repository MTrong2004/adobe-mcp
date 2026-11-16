// Lắp gói ngữ cảnh (context) trước khi sửa code và truy vết quan hệ (trace).

import { Bm25 } from './search.mjs';
import { expandQuery, normPath, tokenize } from './util.mjs';

/** Tìm file theo đường dẫn tương đối, tên ngắn, tên Component hoặc Asset. */
export function resolveFile(g, input) {
  const p = String(input).trim().replace(/^\.\//, '').replace(/\\/g, '/');
  if (g.files[p]) return p;

  // Khớp qua ánh xạ Tag Component (Landing -> components/v6/Landing.tsx)
  if (g.tagsToComponent?.has(p)) return g.tagsToComponent.get(p);

  // Khớp qua tên ngắn của asset (v6-border-trailer-v7-fill.png -> public/assets/v6-border-trailer-v7-fill.png)
  for (const rel of Object.keys(g.files)) {
    if (rel.endsWith('/' + p) || rel === p) return rel;
  }

  const exts = ['', '.tsx', '.ts', '.mjs', '.cjs', '.js', '.css', '.md'];
  for (const ext of exts) {
    const withExt = p + ext;
    if (g.files[withExt]) return withExt;
    const cands = Object.keys(g.files).filter((r) => r.endsWith('/' + withExt) || r === withExt);
    if (cands.length > 0) return cands.sort((a, b) => a.length - b.length)[0];
  }

  // Khớp symbol exported
  for (const [rel, f] of Object.entries(g.files)) {
    if (f.sym.includes(p)) return rel;
  }

  return null;
}

/** Lấy ánh xạ các tài liệu / quy tắc đã bị thay thế (superseded). */
export function getSupersededMap(index, cfg) {
  const map = new Map();
  for (const item of cfg.superseded || []) {
    map.set(item.glob, item.by);
  }
  for (const rel of Object.keys(index.files)) {
    const meta = index.files[rel].d?.meta;
    if (meta?.supersedes) {
      const list = Array.isArray(meta.supersedes) ? meta.supersedes : [meta.supersedes];
      for (const target of list) {
        map.set(target, rel);
      }
    }
  }
  return map;
}

/** Chuẩn bị các bộ tìm kiếm BM25 cho code và docs. */
function buildSearchEngines(index, g) {
  const codeRels = Object.keys(g.files);
  const codeTokens = codeRels.map((r) => {
    const f = g.files[r];
    return tokenize(`${r} ${f.sym.join(' ')} ${f.assets.join(' ')}`);
  });
  const uiTokens = codeRels.map((r) => g.files[r].ui || []);

  const docChunks = [];
  for (const rel of Object.keys(index.files)) {
    const d = index.files[rel].d;
    if (d && d.chunks) {
      for (const ch of d.chunks) {
        docChunks.push(ch);
      }
    }
  }
  const docTokens = docChunks.map((ch) => ch.tokens || []);

  return {
    codeRels,
    codeBm: new Bm25(codeTokens),
    uiBm: new Bm25(uiTokens),
    docChunks,
    docBm: new Bm25(docTokens),
  };
}

/** Lắp ngữ cảnh cho task. */
export function buildContext(index, g, cfg, opts = {}) {
  const taskText = String(opts.task || '');
  const keywords = String(opts.keywords || '');
  const explicitFiles = (opts.files || []).map((f) => resolveFile(g, f)).filter(Boolean);
  const budget = opts.budget || cfg.context?.budget || 1800;
  const uiLambda = cfg.context?.uiLambda ?? 0.45;
  const docLambda = cfg.context?.docLambda ?? 0.55;

  const fullQuery = expandQuery(`${taskText} ${keywords}`, cfg.synonyms);
  const qTokens = tokenize(fullQuery);

  const engines = buildSearchEngines(index, g);

  // 1. Điểm code (BM25 trên tên/symbol + UI tokens)
  const codeHits = engines.codeBm.search(qTokens, { limit: 15 });
  const uiHits = engines.uiBm.search(qTokens, { limit: 10 });

  const scoreMap = new Map();
  for (const h of codeHits) {
    const rel = engines.codeRels[h.i];
    scoreMap.set(rel, (scoreMap.get(rel) || 0) + h.score);
  }
  for (const h of uiHits) {
    const rel = engines.codeRels[h.i];
    scoreMap.set(rel, (scoreMap.get(rel) || 0) + h.score * uiLambda);
  }

  // File do người dùng chỉ định được cộng điểm ưu tiên cao
  for (const f of explicitFiles) {
    scoreMap.set(f, (scoreMap.get(f) || 0) + 100);
  }

  // Mở rộng đồ thị 1 bước: nếu A có điểm cao, cộng điểm cho file A import hoặc file dùng A
  const topSeeds = [...scoreMap.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map((e) => e[0]);

  for (const seed of topSeeds) {
    const baseScore = scoreMap.get(seed) || 0;
    for (const outEdge of g.out.get(seed) || []) {
      scoreMap.set(outEdge.to, (scoreMap.get(outEdge.to) || 0) + baseScore * 0.3);
    }
    for (const inEdge of g.in.get(seed) || []) {
      scoreMap.set(inEdge.from, (scoreMap.get(inEdge.from) || 0) + baseScore * 0.2);
    }
  }

  const sortedFiles = [...scoreMap.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 7)
    .map(([rel]) => rel);

  // 2. Tìm kiếm trong Docs và Memory entries
  const docHits = engines.docBm.search(qTokens, { limit: 24 });
  const supersededMap = getSupersededMap(index, cfg);
  const decisions = [];
  const lessons = [];
  const rules = [];

  for (const h of docHits) {
    const chunk = engines.docChunks[h.i];
    const isSupersededBy = supersededMap.get(chunk.rel);
    let heading = chunk.heading;
    if (isSupersededBy) {
      heading = `[⚠ ĐÃ BỊ THAY THẾ BỞI ${isSupersededBy}] ${heading}`;
    }
    const item = {
      rel: chunk.rel,
      heading,
      line: chunk.startLine,
      text: chunk.text,
      type: chunk.type,
      date: chunk.meta?.date,
      isSuperseded: !!isSupersededBy,
    };

    // Khối chỉ liệt kê file (không có nội dung để học) thì bỏ qua.
    if (/^(thay đổi|file liên quan)$/i.test((chunk.heading || '').trim())) continue;

    // Phân loại theo tiêu đề khối trước, rồi mới tới loại bản ghi.
    if (/bài học/i.test(chunk.heading) || chunk.type === 'lesson') {
      lessons.push(item);
    } else if (/quyết định/i.test(chunk.heading) || chunk.type === 'decision') {
      decisions.push(item);
    } else if (chunk.type === 'rule' || /quy tắc|hướng dẫn/i.test(chunk.heading)) {
      rules.push(item);
    } else {
      decisions.push(item);
    }
  }

  // Ưu tiên tài liệu còn hiệu lực; nhật ký gộp (type: log) xếp sau quyết định/bài học thật.
  // Quy tắc do chủ dự án chốt (visual-rule) luôn đứng đầu.
  const rank = (x) => (x.isSuperseded ? 2 : 0) + (x.type === 'log' ? 1 : 0) - (x.type === 'visual-rule' ? 1 : 0);
  decisions.sort((a, b) => rank(a) - rank(b));
  rules.sort((a, b) => (a.isSuperseded ? 1 : 0) - (b.isSuperseded ? 1 : 0));

  // 3. Ghép bản markdown dưới ngân sách token (~1 token ≈ 4 ký tự)
  const maxChars = budget * 4;
  const lines = [];

  lines.push(`# Ngữ cảnh dự án: ${taskText || 'Tra cứu'}`);
  lines.push('');

  // Phần 1: File liên quan
  lines.push('## 1. File liên quan (Code & Assets)');
  if (sortedFiles.length === 0) {
    lines.push('_Chưa phát hiện file trực tiếp khớp query._');
  } else {
    for (const rel of sortedFiles) {
      const f = g.files[rel];
      // Một file có thể nối tới file khác bằng nhiều loại cạnh (import + render): chỉ nêu tên một lần.
      const incoming = [...new Set((g.in.get(rel) || []).map((e) => e.from.split('/').pop()))].slice(0, 3);
      const outgoing = [...new Set((g.out.get(rel) || []).map((e) => e.to.split('/').pop()))].slice(0, 3);
      const tagInfo = incoming.length ? ` · được dùng bởi: ${incoming.join(', ')}` : '';
      const outInfo = outgoing.length ? ` · gọi tới: ${outgoing.join(', ')}` : '';
      lines.push(`- **\`${rel}\`** (${f.k || 'code'})${tagInfo}${outInfo}`);
    }
  }
  lines.push('');

  // Phần 2: Quyết định cũ
  if (decisions.length > 0) {
    lines.push('## 2. Quyết định kỹ thuật ràng buộc');
    for (const d of decisions.slice(0, 3)) {
      const dateStr = d.date ? ` (${d.date})` : '';
      lines.push(`- **[${d.heading || d.rel}](${d.rel}#L${d.line})**${dateStr}:`);
      const snippet = d.text.split('\n').filter(Boolean).slice(0, 3).join(' ');
      lines.push(`  ${snippet.slice(0, 250)}...`);
    }
    lines.push('');
  }

  // Phần 3: Bài học kinh nghiệm
  if (lessons.length > 0) {
    lines.push('## 3. Bài học kinh nghiệm');
    for (const l of lessons.slice(0, 3)) {
      lines.push(`- **${l.heading || l.rel}** (\`${l.rel}:${l.line}\`):`);
      const snippet = l.text.split('\n').filter(Boolean).slice(0, 2).join(' ');
      lines.push(`  ${snippet.slice(0, 220)}...`);
    }
    lines.push('');
  }

  // Phần 4: Quy chuẩn dự án
  if (rules.length > 0) {
    lines.push('## 4. Quy tắc & Lưu ý');
    for (const r of rules.slice(0, 2)) {
      lines.push(`- **${r.heading}** (\`${r.rel}:${r.line}\`): ${r.text.split('\n')[0].slice(0, 180)}`);
    }
    lines.push('');
  }

  let finalOutput = lines.join('\n');
  if (finalOutput.length > maxChars) {
    finalOutput = finalOutput.slice(0, maxChars) + '\n\n_(Đã rút gọn trong giới hạn token)_';
  }

  return finalOutput;
}

/** Truy vết phụ thuộc của một file, symbol hoặc asset đồ hoạ. */
export function trace(g, query) {
  // Cho phép truy vết theo đường dẫn API: "/api/register" hoặc "POST /api/register"
  const apiPath = /(\/[^\s]*)$/.exec(String(query).trim())?.[1];
  const routeHit = apiPath && (g.routes || []).find((r) => r.url === apiPath.replace(/\/$/, ''));
  const target = resolveFile(g, query) || routeHit?.rel || query;
  const f = g.files[target];
  const lines = [];

  lines.push(`# Truy vết phụ thuộc: \`${target}\``);
  lines.push('');

  if (!f) {
    lines.push(`_Không tìm thấy file khớp với \`${query}\` trong index._`);
    return lines.join('\n');
  }

  if (f.l === 'asset') {
    lines.push(`- **Loại:** Đồ hoạ / Asset`);
    lines.push('');
    const consumers = (g.in.get(target) || []).filter((e) => e.type === 'asset-consumer');
    lines.push(`## Component / Giao diện sử dụng (${consumers.length}):`);
    if (!consumers.length) lines.push('_Chưa phát hiện component nào tham chiếu trực tiếp._');
    else for (const c of consumers) lines.push(`- \`${c.from}\``);
    lines.push('');

    const producers = (g.in.get(target) || []).filter((e) => e.type === 'asset-producer');
    lines.push(`## Script tạo / xử lý (${producers.length}):`);
    if (!producers.length) lines.push('_Asset tĩnh hoặc chưa liên kết script tạo tự động._');
    else for (const p of producers) lines.push(`- \`${p.from}\``);

    return lines.join('\n');
  }

  lines.push(`- **Loại file:** ${f.k} (${f.l})`);
  lines.push(`- **Symbols:** ${f.sym.join(', ') || 'không'}`);
  lines.push('');

  const incoming = g.in.get(target) || [];
  lines.push(`## Các file dùng \`${target}\` (${incoming.length}):`);
  if (!incoming.length) {
    lines.push('_Không có file nào phụ thuộc vào file này._');
  } else {
    for (const e of incoming) {
      lines.push(`- \`${e.from}\` (${e.type}: ${e.label || 'direct'})`);
    }
  }
  lines.push('');

  const outgoing = g.out.get(target) || [];
  lines.push(`## File mà \`${target}\` gọi tới (${outgoing.length}):`);
  if (!outgoing.length) {
    lines.push('_Không có import nội bộ nào._');
  } else {
    for (const e of outgoing) {
      lines.push(`- \`${e.to}\` (${e.type}: ${e.label || 'direct'})`);
    }
  }

  return lines.join('\n');
}
