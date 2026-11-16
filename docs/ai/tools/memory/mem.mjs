#!/usr/bin/env node
// Memory layer cho AI Agent (ai-kit:memory — bản gốc ở ~/.ai-kit/memory, cập nhật bằng init.mjs --update)
// Không phụ thuộc gói ngoài, không gọi mạng, 100% Node.js thuần.
//
// Cách dùng:
//   node docs/ai/tools/memory/mem.mjs index [--full]
//   node docs/ai/tools/memory/mem.mjs context --task "mô tả task" [--keywords "từ khóa"] [--files a,b]
//   node docs/ai/tools/memory/mem.mjs trace <file | Symbol>
//   node docs/ai/tools/memory/mem.mjs record --title "..." --summary "..." [--type task|decision|lesson|bugfix] [--decision "..."] [--lesson "..."] [--files a,b] [--dry-run]
//   node docs/ai/tools/memory/mem.mjs audit

import fs from 'node:fs';
import path from 'node:path';
import { compact, health, healthNotice } from './lib/compact.mjs';
import { buildContext, trace } from './lib/context.mjs';
import { compareBaseline, formatEval, runEval, saveBaseline } from './lib/eval.mjs';
import { buildGraph } from './lib/graph.mjs';
import { buildRecord, changedFiles, writeRecord } from './lib/record.mjs';
import { describeHit, makeSecretTools } from './lib/secrets.mjs';
import { loadConfig, TOOL_DIR, updateIndex } from './lib/store.mjs';
import { first, parseArgs } from './lib/util.mjs';

const args = parseArgs(process.argv.slice(2));
const cmd = args._[0];
const root = args.root ? path.resolve(first(args.root)) : path.resolve(TOOL_DIR, '../../../..');

const usage = () => {
  console.log(`
Bộ nhớ AI Agent

Lệnh hỗ trợ:
  index                    Cập nhật chỉ mục tăng dần (.agent-memory/index.json)
    --full                 Quét lại toàn bộ không dùng cache
  
  context                  Lấy ngữ cảnh, file liên quan, quyết định cũ trước khi làm task
    --task "mô tả"         Yêu cầu công việc cần làm
    --keywords "a b"       Từ khoá định danh hỗ trợ tìm kiếm
    --files a,b            File dự kiến sẽ sửa
    --changed              Tự động lấy các file đang sửa dở trong working tree làm ngữ cảnh
    --budget 1800          Ngân sách token (~1800 token)

  trace <file|symbol>      Truy vết quan hệ import và các component phụ thuộc

  record                   Ghi lại tóm tắt, quyết định, bài học sau task
    --title "tiêu đề"      Tên việc đã làm
    --summary "tóm tắt"    Chi tiết thay đổi
    --type task|decision|lesson|bugfix
    --decision "quyết định"
    --lesson "bài học"
    --files a,b            File đã sửa (mặc định: file đang sửa được nhắc tên, tối đa 10)
    --force                Vẫn ghi dù là "task" không có bài học / quyết định
    --supersedes a.md,b.md Bản ghi này thay cho tài liệu / bản ghi cũ (bản cũ bị hạ hạng, gắn cảnh báo khi tra)
    --dry-run              Xem trước không lưu

  audit                    Quét kiểm tra rò rỉ bí mật (API key, tokens...)

  eval                     Đo chất lượng tra cứu trên bộ câu hỏi mẫu (docs/ai/tools/memory/eval.json)
    --update-baseline      Lưu kết quả hiện tại làm mốc; lần sau tệ hơn mốc thì thoát mã 1

  health                   Kiểm tra kho memory có cần dọn không (context tự nhắc khi vượt ngưỡng)
  compact                  Dọn kho: gộp bản nhật ký theo ngày, cắt danh sách file thừa
    --dry-run              Chỉ đếm, không ghi. CHỈ chạy thật khi chủ dự án đã đồng ý.
`);
  process.exit(2);
};

if (!cmd || args.help || args.h) {
  usage();
}

const cfg = loadConfig(root);

const load = (full = false) => {
  const { index, stats } = updateIndex(root, cfg, { full });
  const g = buildGraph(index, cfg);
  return { index, stats, g };
};

switch (cmd) {
  case 'index':
  case 'stats': {
    const { stats, g } = load(!!args.full);
    console.log(`[Memory Index] Thành công:`);
    console.log(`- File code: ${stats.code}`);
    console.log(`- Tài liệu & Memory: ${stats.docs}`);
    console.log(`- Đổi mới: ${stats.changed} file`);
    console.log(`- Đồ thị quan hệ: ${g.stats.edges} liên kết`);
    if (g.stats.apiCalls) console.log(`- Lời gọi API nội bộ: ${g.stats.apiLinked}/${g.stats.apiCalls} nối được tới file route`);
    console.log(`- Thời gian xử lý: ${stats.ms + g.stats.ms} ms`);
    break;
  }

  case 'context': {
    let task = args.task || args._.slice(1).join(' ');
    let explicitFiles = args.files ? (Array.isArray(args.files) ? args.files : args.files.split(',')) : [];
    if (args.changed) {
      const changed = changedFiles(root);
      explicitFiles = [...new Set([...explicitFiles, ...changed])];
      if (!task && explicitFiles.length > 0) {
        task = `Các file đang sửa dở (${explicitFiles.slice(0, 3).join(', ')})`;
      }
    }
    if (!task && explicitFiles.length === 0) {
      console.error('Lỗi: Cần truyền --task "mô tả", --files hoặc cờ --changed');
      process.exit(2);
    }
    const { index, g } = load();
    const out = buildContext(index, g, cfg, {
      task,
      keywords: args.keywords,
      files: explicitFiles,
      budget: args.budget ? Number(args.budget) : cfg.context?.budget,
    });
    console.log(out);
    // Vượt ngưỡng thì nhắc agent hỏi chủ dự án có dọn không (không tự dọn).
    const notice = healthNotice(health(root, cfg));
    if (notice) console.log(notice);
    break;
  }

  case 'eval': {
    const { index, g } = load();
    const score = runEval(index, g, cfg);
    const cmp = compareBaseline(score);
    if (args.json) console.log(JSON.stringify({ ...score, baseline: cmp.baseline, regressed: cmp.regressed }, null, 2));
    else console.log(formatEval(score, cmp));
    if (args['update-baseline'] && score.total) {
      saveBaseline(score);
      console.log('Đã lưu mốc mới.');
    } else if (cmp.regressed) {
      process.exit(1);
    }
    break;
  }

  case 'health': {
    const h = health(root, cfg, { force: true });
    if (!h) {
      console.log('[Memory Health] OK: kho memory chưa cần dọn.');
    } else {
      console.log(healthNotice(h).trim());
    }
    break;
  }

  case 'compact': {
    const dry = !!args['dry-run'];
    const s = compact(root, cfg, { dry });
    console.log(
      `[Memory Compact]${dry ? ' (dry-run)' : ''} gộp ${s.merged} bản nhật ký vào ${s.days} file theo ngày; cắt gọn ${s.trimmed} bản; giữ nguyên ${s.kept}.`,
    );
    console.log(`Dung lượng: ${s.kbBefore} KB -> ${s.kbAfter} KB`);
    if (!dry && s.merged + s.trimmed > 0) load();
    break;
  }

  case 'trace': {
    const target = args._[1];
    if (!target) {
      console.error('Lỗi: Cần truyền tên file hoặc symbol cần trace');
      process.exit(2);
    }
    const { g } = load();
    console.log(trace(g, target));
    break;
  }

  case 'record': {
    if (!args.title) {
      console.error('Lỗi: Cần truyền --title "..."');
      process.exit(2);
    }
    // Chỉ ghi khi có điều đáng nhớ: việc thường ngày đã có git log.
    const worthIt = args.lesson || args.decision || ['bugfix', 'decision', 'lesson', 'visual-rule'].includes(args.type);
    if (!worthIt && !args.force) {
      console.error(
        'Không ghi: bản ghi loại "task" không có --lesson / --decision chỉ là nhật ký (git log đã lưu).\n' +
          'Thêm --lesson "..." hoặc --decision "...", đổi --type bugfix|decision|lesson, hoặc thêm --force nếu vẫn muốn ghi.',
      );
      process.exit(2);
    }
    const record = buildRecord(root, cfg, args);
    if (args['dry-run']) {
      console.log(`[DRY RUN] Bản ghi sẽ lưu tại: ${record.relPath}\n`);
      console.log(record.content);
    } else {
      writeRecord(root, record);
      console.log(`[Memory Record] Đã lưu thành công: ${record.relPath}`);
      // Cập nhật lại index sau khi thêm record
      load();
    }
    break;
  }

  case 'audit': {
    const secretTools = makeSecretTools(cfg);
    const { index } = load();
    let hitsCount = 0;

    console.log('[Memory Audit] Đang quét rà soát bí mật...');
    for (const rel of Object.keys(index.files)) {
      const abs = path.join(root, rel);
      let content = '';
      try {
        content = fs.readFileSync(abs, 'utf8');
      } catch {
        continue;
      }
      const hits = secretTools.scan(content);
      if (hits.length > 0) {
        hitsCount += hits.length;
        for (const h of hits) {
          const desc = describeHit(content, h);
          console.warn(`[CẢNH BÁO] ${rel}:${desc.line} phát hiện ${desc.kind} (độ dài ${desc.length})`);
        }
      }
    }

    if (hitsCount === 0) {
      console.log('[Memory Audit] OK: Không phát hiện token/key bí mật rò rỉ.');
      process.exit(0);
    } else {
      console.error(`[Memory Audit] PHÁT HIỆN ${hitsCount} nguy cơ rò rỉ bí mật!`);
      process.exit(1);
    }
    break;
  }

  default:
    console.error(`Lệnh không hợp lệ: "${cmd}"`);
    usage();
}
