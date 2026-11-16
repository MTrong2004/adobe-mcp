// Chặn dữ liệu nhạy cảm: che (redact) trước khi ghi index / memory, và quét (audit) sau khi ghi.

const STRONG = [
  ['jwt', /\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}/g],
  ['private-key', /-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)/g],
  ['github-token', /\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b/g],
  ['ai-api-key', /\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}/g],
  ['google-api-key', /\bAIza[0-9A-Za-z_-]{35}\b/g],
  ['bearer', /\bBearer\s+[A-Za-z0-9._~+/-]{24,}=*/g],
  ['supabase-key', /\bsbp_[a-zA-Z0-9]{30,}\b/g],
];

const PLACEHOLDER = /^(?:true|false|null|none|undefined|string|int|bool|changeme|change-me|todo|example\S*|your\S*|placeholder|redacted|\[redacted\]|x{3,}|\*{3,}|\.{3,}|<[^>]*>)$/i;

export function looksSecret(value) {
  const v = String(value ?? '').trim().replace(/^['"`]|['"`]$/g, '');
  if (v.length < 8 || /\s/.test(v)) return false;
  if (PLACEHOLDER.test(v)) return false;
  if (/^[$<{(\[%]/.test(v)) return false; // ${ENV}, <placeholder>, {config}
  if (/[()]/.test(v)) return false; // hàm
  if (/^(?:process|this|env|settings|environment|config|options|request|context)\b/i.test(v)) return false;
  if (/^[A-Z0-9_]+$/.test(v)) return false; // tên biến ENV
  if (/^[a-z][a-zA-Z0-9]*(?:\.[a-zA-Z_]\w*)+$/.test(v)) return false;
  if (/^https?:\/\/[^@\s]*$/i.test(v)) return false;
  if (v.includes('/') && /^[a-z0-9\-_/{}.:~]+$/.test(v)) return false;
  if (/^[\w./-]+\.(?:json|ts|tsx|mjs|cjs|js|css|png|jpg|webp|svg|md)$/i.test(v)) return false;
  const classes = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(v)).length;
  return classes >= 3 || (v.length >= 24 && classes >= 2);
}

export function makeSecretTools(cfg = {}) {
  const keys = (cfg.secretKeys ?? [
    'token', 'secret', 'password', 'apiKey', 'auth', 'private_key', 'SUPABASE_SERVICE_ROLE_KEY'
  ]).map((k) => k.replace(/[^A-Za-z0-9_]/g, '')).filter(Boolean);
  const keyAlt = keys.join('|');
  const kv = new RegExp(
    `(["'\`]?[A-Za-z0-9_.:-]*(?:${keyAlt})[A-Za-z0-9_]*["'\`]?\\s*(?:=>|:|=)\\s*)(["'\`]?)([^\\s"'\`;,}<>]{8,})\\2`,
    'gi',
  );
  const secretName = new RegExp(`(?:${keyAlt})`, 'i');

  function scan(text) {
    const hits = [];
    const s = String(text ?? '');
    for (const [kind, re] of STRONG) {
      re.lastIndex = 0;
      for (const m of s.matchAll(re)) hits.push({ kind, index: m.index, length: m[0].length });
    }
    kv.lastIndex = 0;
    for (const m of s.matchAll(kv)) {
      if (looksSecret(m[3])) hits.push({ kind: 'key-value', index: m.index + m[1].length + m[2].length, length: m[3].length });
    }
    return hits;
  }

  function redact(text) {
    let s = String(text ?? '');
    let count = 0;
    for (const [, re] of STRONG) {
      s = s.replace(re, () => {
        count++;
        return '[REDACTED]';
      });
    }
    s = s.replace(kv, (all, pre, q, val) => {
      if (!looksSecret(val)) return all;
      count++;
      return `${pre}${q}[REDACTED]${q}`;
    });
    return { text: s, count };
  }

  return { scan, redact, isSecretName: (name) => secretName.test(name) };
}

export const describeHit = (text, hit) => {
  const before = text.slice(0, hit.index);
  const line = before.split('\n').length;
  return { kind: hit.kind, line, length: hit.length };
};
