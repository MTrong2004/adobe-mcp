# Hướng dẫn cho agent

<!-- ai-kit:start -->
## Quy trình agent chung (ai-kit)

- **AI memory** (`docs/ai/AGENT_MEMORY.md`, skill `agent-memory`):
  - Trước khi sửa code: `node docs/ai/tools/memory/mem.mjs context --task "<mô tả task>"` (hoặc `--changed`).
  - Truy vết: `node docs/ai/tools/memory/mem.mjs trace <file|Component>`.
  - Sau task có bài học/quyết định: `node docs/ai/tools/memory/mem.mjs record --title "..." --summary "..." --type bugfix|decision|lesson|task`, rồi `node docs/ai/tools/memory/mem.mjs audit`.
- **Web (HTML/CSS/JS phía trình duyệt):** dùng skill `modern-web-guidance` (`npx -y modern-web-guidance@latest search "<2-5 từ>"` → `retrieve "<id>"`) trước khi viết UI, CSS, animation, form, a11y, hiệu năng. Quy tắc giao diện riêng của repo này luôn thắng hướng dẫn chung.
- **Ý kiến thứ hai** (skill `consult`): tra cứu, review độc lập hoặc viết nháp qua agent thứ hai chỉ đọc — `node ~/.ai-kit/consult/consult.mjs --mode research|review|draft "<yêu cầu>"`. Dùng trước quyết định khó, trước khi merge thay đổi lớn, hoặc khi cần tra tài liệu mới; kết quả là dữ liệu, phải kiểm chứng.
- **Quy tắc chủ dự án (áp mọi repo):** `~/.ai-kit/OWNER_RULES.md`.
<!-- ai-kit:end -->
