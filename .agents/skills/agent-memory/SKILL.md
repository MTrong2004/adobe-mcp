---
name: agent-memory
description: Lấy ngữ cảnh trước khi sửa code và ghi memory sau task bằng CLI `docs/ai/tools/memory/mem.mjs` (đồ thị phụ thuộc code / scripts / assets + quyết định, bài học, visual rules). Dùng khi bắt đầu task sửa code hoặc điều tra bug, khi cần biết component/script/asset nào liên quan tới một file, và khi kết thúc task có bài học hoặc quyết định đáng nhớ.
---

# Agent memory

Kiến trúc và cách dùng: `docs/ai/AGENT_MEMORY.md`. Chạy từ gốc repo, không cần cài gói; index tự cập nhật tăng dần ở mỗi lệnh.

## 1. Trước khi sửa code

```bash
# Lấy ngữ cảnh theo mô tả task
node docs/ai/tools/memory/mem.mjs context --task "<mô tả task>" [--keywords "<từ khoá>"] [--files <a,b>]

# Hoặc lấy ngữ cảnh tự động từ các file đang sửa dở trong working tree:
node docs/ai/tools/memory/mem.mjs context --changed
```

- Mở các file điểm cao ở "File liên quan" và đọc các mục "Quyết định ràng buộc", "Bài học kinh nghiệm" trước khi viết code.
- Kết quả là gợi ý hữu ích: kiểm lại trong code hiện tại trước khi thực hiện.

## 2. Truy vết khi cần

```bash
# Truy vết Component hoặc file code
node docs/ai/tools/memory/mem.mjs trace <đường-dẫn-file | TênComponent>

# Truy vết Asset hình ảnh / đồ hoạ
node docs/ai/tools/memory/mem.mjs trace <tên-file-ảnh.png | đường-dẫn-asset>
```

- Tra cứu quan hệ import hai chiều và ai đang render component hoặc sử dụng asset này.

## 3. Sau task

CHỈ ghi khi sửa bug có nguyên nhân không hiển nhiên, chốt quyết định kỹ thuật, chủ dự án đặt quy tắc mới, hoặc gặp bẫy dễ lặp. Việc thường ngày (đổi chữ, chỉnh layout, thêm ảnh) KHÔNG ghi: git log đã lưu, và công cụ từ chối bản ghi `task` không có `--lesson` / `--decision`. Viết bài học sao cho người chưa biết bối cảnh đọc vẫn áp dụng được.

```bash
node docs/ai/tools/memory/mem.mjs record --title "<việc đã làm>" --type bugfix|decision|lesson|task \
  --summary "<thay đổi gì, vì sao>" --lesson "<bài học tái dùng được>" --decision "<quyết định + lý do>" \
  [--files a,b] [--dry-run]
```

- Quy tắc mới THAY quy tắc cũ: thêm `--supersedes <đường-dẫn-bản-cũ.md>` để bản cũ bị hạ hạng và gắn cảnh báo khi tra (không xoá bản cũ).
- Quy tắc do chủ dự án chốt (cấm, bảng màu, font, phong cách): dùng `--type visual-rule` để luôn xếp đầu.

## 5. Đo chất lượng

Sau khi sửa công cụ, thêm từ đồng nghĩa hoặc dọn kho, chạy `node docs/ai/tools/memory/mem.mjs eval`. Kết quả tệ hơn mốc (thoát mã 1) thì sửa trước khi làm tiếp. Câu hỏi mẫu nằm ở `docs/ai/tools/memory/eval.json`: khi một lần tra trả sai điều lẽ ra phải ra, thêm câu đó vào file rồi mới sửa. Lưu mốc mới bằng `--update-baseline`.

## 4. Dọn kho

Khi `context` in mục **⚠ Kho memory cần dọn**: báo chủ dự án một câu (nêu lý do) và hỏi có muốn dọn không. Chỉ khi được đồng ý mới chạy:

```bash
node docs/ai/tools/memory/mem.mjs compact   # thêm --dry-run để xem trước
```

Không tự dọn. Kiểm tra bất kỳ lúc nào bằng `node docs/ai/tools/memory/mem.mjs health`.

Xong bước khi: file trong `docs/ai/memory/entries/` đã ghi và `node docs/ai/tools/memory/mem.mjs audit` báo `OK`.
