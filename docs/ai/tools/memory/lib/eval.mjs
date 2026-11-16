// Bộ đo chất lượng tra cứu: chạy `context` trên các câu hỏi mẫu và kiểm tra kết quả mong đợi có xuất hiện không.
// Mục đích: mỗi lần sửa công cụ / từ đồng nghĩa / dọn kho thì biết tốt lên hay tệ đi bằng con số, không đoán.
//
// File câu hỏi (riêng từng repo): docs/ai/tools/memory/eval.json
//   { "cases": [ { "task": "sửa form đăng ký", "expect": ["RegisterForm.tsx"], "top": "tên-bản-ghi-phải-đứng-đầu" } ] }
//   - expect: mọi chuỗi phải có trong kết quả (đường dẫn file, tên bản ghi, hoặc một cụm chữ).
//   - top (không bắt buộc): chuỗi phải nằm ở mục đầu tiên của phần quyết định / quy tắc.

import fs from 'node:fs';
import path from 'node:path';
import { buildContext } from './context.mjs';
import { TOOL_DIR } from './store.mjs';
import { fold } from './util.mjs';

export const EVAL_FILE = path.join(TOOL_DIR, 'eval.json');
export const BASELINE_FILE = path.join(TOOL_DIR, 'eval-baseline.json');

const readJson = (f) => {
  try {
    return JSON.parse(fs.readFileSync(f, 'utf8'));
  } catch {
    return null;
  }
};

export function runEval(index, g, cfg) {
  const spec = readJson(EVAL_FILE);
  const cases = spec?.cases || [];
  const results = [];
  for (const c of cases) {
    const out = buildContext(index, g, cfg, { task: c.task, keywords: c.keywords, files: c.files || [] });
    // Bỏ dòng tiêu đề (nó lặp lại chính câu hỏi nên sẽ khớp giả).
    const body = out.split('\n').slice(1).join('\n');
    const hay = fold(body);
    const missing = (c.expect || []).filter((e) => !hay.includes(fold(e)));
    let topOk = null;
    if (c.top) {
      const sec = body.split(/^## 2\..*$/m)[1] || '';
      const first = (sec.split(/^- \*\*/m)[1] || '').split(/^## /m)[0];
      topOk = fold(first).includes(fold(c.top));
    }
    results.push({ task: c.task, pass: missing.length === 0, missing, top: c.top || null, topOk });
  }
  const total = results.length;
  const passed = results.filter((r) => r.pass).length;
  const topTotal = results.filter((r) => r.top).length;
  const topPassed = results.filter((r) => r.topOk).length;
  return { total, passed, topTotal, topPassed, results };
}

/** So với mốc đã lưu. Trả về { regressed, baseline }. */
export function compareBaseline(score) {
  const baseline = readJson(BASELINE_FILE);
  if (!baseline) return { regressed: false, baseline: null };
  // Chỉ so khi bộ câu hỏi không bị rút bớt.
  const comparable = score.total >= baseline.total;
  const regressed = comparable && (score.passed < baseline.passed || score.topPassed < baseline.topPassed);
  return { regressed, baseline };
}

export function saveBaseline(score) {
  const { total, passed, topTotal, topPassed } = score;
  fs.writeFileSync(BASELINE_FILE, JSON.stringify({ total, passed, topTotal, topPassed }, null, 2) + '\n');
}

export function formatEval(score, cmp) {
  const lines = [];
  if (!score.total) {
    lines.push('[Memory Eval] Chưa có câu hỏi mẫu.');
    lines.push('Tạo docs/ai/tools/memory/eval.json dạng:');
    lines.push('  { "cases": [ { "task": "mô tả việc", "expect": ["tên-file-hoặc-bản-ghi"], "top": "bản-ghi-phải-đứng-đầu" } ] }');
    return lines.join('\n');
  }
  lines.push(`[Memory Eval] Tìm đủ kết quả mong đợi: ${score.passed}/${score.total} câu` + (score.topTotal ? ` · đúng mục đứng đầu: ${score.topPassed}/${score.topTotal}` : ''));
  for (const r of score.results) {
    if (r.pass && r.topOk !== false) continue;
    const why = [];
    if (!r.pass) why.push(`thiếu: ${r.missing.join(', ')}`);
    if (r.topOk === false) why.push(`"${r.top}" không đứng đầu`);
    lines.push(`  ✗ "${r.task}" — ${why.join('; ')}`);
  }
  if (cmp.baseline) {
    const b = cmp.baseline;
    lines.push(`Mốc đã lưu: ${b.passed}/${b.total}` + (b.topTotal ? ` · đứng đầu ${b.topPassed}/${b.topTotal}` : '') + (cmp.regressed ? '  → TỆ ĐI so với mốc' : '  → không tệ đi'));
  } else {
    lines.push('Chưa có mốc. Lưu mốc: node docs/ai/tools/memory/mem.mjs eval --update-baseline');
  }
  return lines.join('\n');
}
