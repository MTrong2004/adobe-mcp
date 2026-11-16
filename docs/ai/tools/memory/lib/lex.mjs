// Lexer tối giản: che comment và chuỗi trong code JS/TS/TSX bằng khoảng trắng.

const blank = (s) => s.replace(/[^\n]/g, ' ');

/** Che comment và nội dung chuỗi trong mã TypeScript / JSX / JS, giữ nguyên vị trí ký tự và xuống dòng. */
export function maskTs(src) {
  const n = src.length;
  let out = '';
  let i = 0;
  let last = 0;

  while (i < n) {
    const c = src[i];
    const next = src[i + 1];

    // Single-line comment
    if (c === '/' && next === '/') {
      out += src.slice(last, i);
      const end = src.indexOf('\n', i + 2);
      const stop = end === -1 ? n : end;
      out += blank(src.slice(i, stop));
      last = stop;
      i = stop;
      continue;
    }

    // Multi-line comment
    if (c === '/' && next === '*') {
      out += src.slice(last, i);
      const end = src.indexOf('*/', i + 2);
      const stop = end === -1 ? n : end + 2;
      out += blank(src.slice(i, stop));
      last = stop;
      i = stop;
      continue;
    }

    // String literals: '...', "..."
    if (c === "'" || c === '"') {
      out += src.slice(last, i);
      let j = i + 1;
      while (j < n) {
        if (src[j] === '\\') {
          j += 2;
          continue;
        }
        if (src[j] === c || src[j] === '\n') {
          j++;
          break;
        }
        j++;
      }
      out += blank(src.slice(i, j));
      last = j;
      i = j;
      continue;
    }

    // Template literal `...`
    if (c === '`') {
      out += src.slice(last, i);
      let j = i + 1;
      let depth = 0;
      while (j < n) {
        if (src[j] === '\\') {
          j += 2;
          continue;
        }
        if (src[j] === '$' && src[j + 1] === '{') {
          j += 2;
          depth++;
          continue;
        }
        if (depth > 0 && src[j] === '}') {
          depth--;
          j++;
          continue;
        }
        if (depth === 0 && src[j] === '`') {
          j++;
          break;
        }
        j++;
      }
      out += blank(src.slice(i, j));
      last = j;
      i = j;
      continue;
    }

    i++;
  }

  out += src.slice(last);
  return out;
}

export function lineOf(src, index) {
  return src.slice(0, index).split('\n').length;
}
