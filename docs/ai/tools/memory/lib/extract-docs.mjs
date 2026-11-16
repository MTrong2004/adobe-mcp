// Trích xuất tài liệu markdown và memory entries: frontmatter, các khối heading, quyết định, bài học.

import { fold, tokenize } from './util.mjs';

const MAX_CHUNK = 2000;

export function parseFrontmatter(src) {
  const m = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(src);
  if (!m) return { meta: {}, body: src, offset: 0 };
  const meta = {};
  for (const line of m[1].split(/\r?\n/)) {
    const kv = /^([\w-]+)\s*:\s*(.*)$/.exec(line);
    if (!kv) continue;
    let v = kv[2].trim();
    if (/^\[.*\]$/.test(v)) {
      v = v.slice(1, -1).split(',').map((x) => x.trim().replace(/^['"]|['"]$/g, '')).filter(Boolean);
    } else {
      v = v.replace(/^['"]|['"]$/g, '');
    }
    if (v === 'null' || v === '~' || v === '') v = null;
    meta[kv[1]] = v;
  }
  return { meta, body: src.slice(m[0].length), offset: m[1].split('\n').length + 2 };
}

/** Cắt markdown thành các chunk logic theo heading (#, ##, ###). */
export function chunkMarkdown(rel, src, type, redact) {
  const { meta, body, offset } = parseFrontmatter(src);
  const chunks = [];
  const lines = body.split(/\r?\n/);
  
  let curHeading = meta.title || rel.split('/').pop().replace(/\.md$/, '');
  let curLines = [];
  let curStart = offset + 1;

  const flush = (nextHeading, nextStart) => {
    const rawText = curLines.join('\n').trim();
    if (rawText) {
      const cleaned = redact ? redact(rawText).text : rawText;
      const headingTokens = tokenize(curHeading);
      const textTokens = tokenize(cleaned);
      // Tiêu đề bản ghi (frontmatter title) cũng được tính để tìm theo tên việc ra đúng khối Tóm tắt / Bài học.
      const titleTokens = meta.title ? tokenize(String(meta.title)) : [];
      const allTokens = [...new Set([...headingTokens, ...titleTokens, ...textTokens])];
      
      chunks.push({
        rel,
        type: meta.type || type || 'doc',
        heading: curHeading,
        startLine: curStart,
        text: cleaned.slice(0, MAX_CHUNK),
        meta,
        tokens: allTokens,
      });
    }
    curHeading = nextHeading;
    curStart = nextStart;
    curLines = [];
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const m = /^(#{1,3})\s+(.+)$/.exec(line);
    if (m) {
      flush(m[2].trim(), offset + i + 1);
    } else {
      curLines.push(line);
    }
  }
  flush('', offset + lines.length);

  return { meta, chunks };
}
