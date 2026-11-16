# Bộ nhớ AI Agent (AI Memory Layer)

Hệ thống bộ nhớ dành riêng cho AI Agent (Antigravity IDE, Claude Code, subagents), hoạt động dựa trên đồ thị phụ thuộc mã nguồn tĩnh kết hợp tìm kiếm BM25 và lưu trữ bằng Markdown trong Git.

- **Vị trí công cụ:** `docs/ai/tools/memory/mem.mjs`
- **Thư mục cache:** `.agent-memory/index.json` (tự động tạo, 0 external deps)
- **Thư mục lưu bài học & quyết định:** `docs/ai/memory/entries/`
- **Skill hỗ trợ:** `.claude/skills/agent-memory/SKILL.md`

---

## 1. Mục tiêu và Triết lý

1. **Không mất ngữ cảnh:** Agent mới vào phiên không cần tốn hàng chục ngàn token quét lại toàn bộ file.
2. **Kế thừa quyết định cũ:** Tránh lặp lại lỗi đã giải quyết.
3. **Truy vết hai chiều (Component & Asset):** Nhanh chóng biết một component hay file script được gọi từ đâu, và một ảnh asset đang hiển thị ở component nào.
4. **Cơ chế Supersedes (Chống hồi quy tài liệu):** Tự động hạ hạng và cảnh báo khi tài liệu cũ đã bị thay thế (khai báo trong `superseded` của `memory.config.json`).
5. **100% Nội bộ & Git-native:** Không phụ thuộc vector database hay dịch vụ đám mây, 0 cài đặt thêm gói npm, lưu trữ dưới dạng markdown có thể review được qua git diff.

---

## 2. Hướng dẫn sử dụng cho Agent

### 2.1. Trước khi sửa code: Lấy ngữ cảnh (`context`)

```bash
# Lấy ngữ cảnh theo mô tả task
node docs/ai/tools/memory/mem.mjs context --task "<mô tả task>" [--keywords "<từ khoá tiếng Anh/Việt>"] [--files <file1,file2>]

# Hoặc tự động lấy các file đang sửa dở trong working tree làm ngữ cảnh:
node docs/ai/tools/memory/mem.mjs context --changed [--task "<mô tả bổ sung>"]
```

- Nhận diện các file liên quan trọng tâm nhất (điểm BM25 + mở rộng đồ thị).
- Cung cấp các quyết định kiến trúc và bài học có liên quan trực tiếp đến task.
- Gói gọn trong ngân sách ~1800 token để nạp trực tiếp vào ngữ cảnh làm việc.

### 2.2. Khi điều tra bug hoặc phụ thuộc: Truy vết (`trace`)

```bash
# Truy vết Component hoặc file code
node docs/ai/tools/memory/mem.mjs trace src/components/Header.tsx
node docs/ai/tools/memory/mem.mjs trace Header

# Truy vết Asset hình ảnh / đồ hoạ
node docs/ai/tools/memory/mem.mjs trace logo.png
```

- Với file code: Liệt kê ai đang dùng file này (`in` edges), và file này import/render component nào (`out` edges).
- Với asset hình ảnh: Liệt kê component nào đang hiển thị ảnh đó, script nào tạo ra nó.

### 2.3. Sau khi hoàn thành task: Ghi nhớ (`record`)

```bash
node docs/ai/tools/memory/mem.mjs record \
  --title "<tiêu đề việc đã làm>" \
  --summary "<thay đổi gì, vì sao>" \
  --type task|decision|lesson|bugfix \
  --decision "<quyết định kỹ thuật>" \
  --lesson "<bài học kinh nghiệm>" \
  [--files <file1,file2>] \
  [--dry-run]
```

- Mặc định `--files` sẽ tự động quét qua `git status` / `git diff`.
- Thêm `--dry-run` để kiểm tra trước khi ghi.

### 2.4. Quét kiểm tra an toàn (`audit`)

```bash
# Quét rò rỉ secret / token
node docs/ai/tools/memory/mem.mjs audit
```

### 2.5. Truy vết API, quy tắc bị thay, đo chất lượng

```bash
# Lời gọi fetch('/api/x') được nối tới file route; tra theo đường dẫn API:
node docs/ai/tools/memory/mem.mjs trace "POST /api/register"

# Quy tắc mới thay quy tắc cũ (bản cũ bị hạ hạng, gắn cảnh báo):
node docs/ai/tools/memory/mem.mjs record --type visual-rule --title "..." --summary "..." --decision "..." --supersedes docs/ai/memory/entries/<bản-cũ>.md

# Đo chất lượng tra cứu trên bộ câu hỏi mẫu (eval.json); tệ hơn mốc thì thoát mã 1:
node docs/ai/tools/memory/mem.mjs eval [--update-baseline]

# Kiểm tra / dọn kho (chỉ dọn khi chủ dự án đồng ý):
node docs/ai/tools/memory/mem.mjs health
node docs/ai/tools/memory/mem.mjs compact [--dry-run]
```
