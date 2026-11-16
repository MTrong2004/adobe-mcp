# MCP Photoshop (bản tự viết)

Server MCP điều khiển Photoshop trên Windows qua COM. Thay cho `uvx photoshop-mcp-server` (0.1.14).

## UXP thử nghiệm — 2026-11-17

Đã thêm 4 công cụ `photoshop_uxp_*` dùng cầu nối tới plugin UXP, dựa trên Photoshop DOM và History API chính thức của Adobe. Đây vẫn là MCP tùy chỉnh, không do Adobe phát hành. Các công cụ COM cũ giữ nguyên; không tự động chuyển backend khi lỗi.

Xem [hướng dẫn cài và kiểm thử UXP](UXP-SETUP.md). **UXP mặc định tắt**; 25 công cụ COM/ExtendScript vẫn là mặc định. Chỉ bật `PS_UXP_ENABLED=1` trong môi trường MCP để thử nghiệm UXP có chủ đích; chưa bật trong cấu hình đang dùng và chưa kiểm thử trực tiếp trong Photoshop.

## Cấu hình MCP (Antigravity / Claude / Codex)

```json
"photoshop": {
  "command": "uv",
  "args": ["run", "--script", "C:/Users/trong/VS Code/adobe-mcp/photoshop/server.py"]
}
```

Claude Code: `claude mcp add photoshop -s user -- uv run --script "C:/Users/trong/VS Code/adobe-mcp/photoshop/server.py"`

## Khác bản gốc

- Phiên bản thư viện khoá cứng trong đầu `server.py` (`mcp==1.30.0`, `comtypes==1.5.0`, `exclude-newer`). Muốn nâng cấp: sửa số ở đó.
- Mọi toạ độ / kích thước bằng **pixel** (bản gốc trả số point sai: 4267 px báo thành 1024.08).
- Hệ màu trả đúng (`rgb`, `cmyk`...), không còn "Unknown".
- Mỗi lệnh là một script JSX duy nhất: đọc thông tin file 37 layer ~0,2 s (bản gốc ~4 s).
- Mỗi lệnh sửa file = 1 bước Undo (tên bước tiếng Việt trong History).
- Tự nối lại khi Photoshop khởi động lại; tự đợi tối đa 15 s khi Photoshop bận; quá `PS_MCP_TIMEOUT` (mặc định 120 s) thì báo lỗi thay vì treo.
- Giữ nguyên tên + tham số 9 công cụ cũ; thêm 13 công cụ:
  `export_image`, `activate_document`, `close_document`, `place_image`, `create_group`, `update_layer`,
  `transform_layer`, `duplicate_layer`, `delete_layer`, `arrange_layer`, `select`, `layer_mask`, `undo`.
- 2026-11-16: thêm `distort_layer` (bóp 4 góc, giữ Smart Object); `export_image` nhân bản dạng đã gộp + tham số `region`
  (xem trước file 7776px: ~2 s thay vì >120 s).
- 2026-11-16: thêm `composite_object` — ghép vật vào ảnh trong 1 lần gọi (bóng, cân sáng, ám màu, hạt nhiễu,
  group tiếng Việt) và trả kèm ảnh xem trước cho agent (~15 s trên file 7776px).

## Hướng dẫn cho agent

Quy tắc làm việc (gộp script, không lùi History khi người dùng đang sửa, id layer, không phóng to logo, bẫy ExtendScript...) nằm ở biến `INSTRUCTIONS` trong `server.py`. Server gửi nó cho mọi agent khi kết nối; sửa ở đó là mọi agent cùng nhận.

## Chỉ định layer

`layer` nhận: id (số), tên chính xác, hoặc đường dẫn `Group/Layer`. Bỏ trống = layer đang chọn.

## Thử nhanh

```bash
uv run --script "C:/Users/trong/VS Code/adobe-mcp/photoshop/server.py"
```
(chạy rồi đứng chờ là đúng; Ctrl+C để thoát).

## File

- `server.py` — server MCP (Python, chạy bằng `uv`).
- `lib.jsx` — hàm ExtendScript dùng chung, được ghép vào mỗi lệnh.
- 2026-11-16: thêm `subject_masks` — Select Subject theo từng khung (crop để nét), mỗi chủ thể 1 layer phủ màu có mask,
  trả ảnh xem trước. Sửa export cho PS 28 (bản sao phải được đặt làm activeDocument trước khi crop).
