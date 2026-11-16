# UXP Roadmap — Photoshop 2027 MCP

Mục tiêu: chuyển toàn bộ server sang UXP (API chính thức của Adobe) và bổ sung đủ công cụ để chỉnh ảnh chuyên nghiệp, **không làm hỏng bản ExtendScript (COM) đang dùng hằng ngày**.

## Luật chung (bắt buộc)

1. **COM là mặc định cho tới khi chủ dự án duyệt.** Mỗi tool UXP bật qua `PS_UXP_ENABLED=1`. Chỉ chuyển một tool sang dùng UXP mặc định khi đã test trong Photoshop thật và chủ dự án đồng ý.
2. **Giữ nguyên tên và tham số** của 25 tool hiện có. Bản UXP phải trả kết quả cùng dạng với bản COM (cùng key, toạ độ pixel, id layer).
3. **Một mục = một nhánh** (`uxp/<mục>`), có test, một commit gọn hoặc vài commit rõ nghĩa. Không push thẳng `master`; mở PR để Claude duyệt.
4. **Mỗi thao tác sửa tài liệu = 1 bước History** (`executeAsModal` + `historyStateInfo` đặt tên rõ). Không tự lưu đè file, không xoá layer của người dùng.
5. Layer chỉ định bằng **id**. Thêm nhiều layer → gom vào group lồng nhau, tên tiếng Việt (xem `~/.ai-kit/OWNER_RULES.md`).
6. Repo **công khai**: không commit token, đường dẫn chứa dữ liệu riêng, ảnh của khách.
7. Báo "Photoshop đang bận" khi có modal/người dùng thao tác; không thử lại dồn dập.

## Giai đoạn 1 — Chuyển 25 tool hiện có (đúng thứ tự)

| # | Nhóm | Tool | Ghi chú |
|---|---|---|---|
| 1a | Đọc | get_session_info, get_active_document_info, get_selection_info | Nền cho mọi bước sau; so khớp output với COM trên cùng 1 PSD |
| 1b | Tài liệu | create/open/activate/close/save_document, export_image | export phải nhanh hơn COM; giữ `max_size` |
| 1c | Layer cơ bản | update_layer, duplicate_layer, delete_layer, arrange_layer, create_group, create_text_layer, create_solid_color_layer | delete = ẩn theo luật chủ dự án nếu gọi từ agent |
| 1d | Ảnh & biến đổi | place_image (Smart Object nhúng), transform_layer, distort_layer | distort: kiểm tra bounds sau khi bóp (bẫy AM bị bỏ qua lặng lẽ) |
| 1e | Vùng chọn & mask | select, layer_mask, subject_masks | subject_masks giữ quy ước group/màu/che khuất hiện tại |
| 1f | Ghép vật | composite_object | Tool phức tạp nhất; làm cuối, so ảnh xem trước với bản COM |
| 1g | Khác | undo, execute_jsx → thêm `execute_uxp` (chạy JS UXP) | giữ execute_jsx qua COM làm lối thoát |

**Nghiệm thu mỗi mục:** test đơn vị cho dispatcher + chạy thật trong Photoshop 2027 trên một PSD mẫu (≥ 3 layer, 1 group, 1 Smart Object), ghi kết quả vào PR (lệnh, output, ảnh export).

## Giai đoạn 2 — Công cụ chỉnh ảnh chuyên nghiệp (mới)

1. **Adjustment layers:** Curves, Levels, Hue/Saturation, Color Balance, Brightness/Contrast, Vibrance, Black & White, Selective Color, Gradient Map, Photo Filter — tạo và sửa tham số, có clip vào layer dưới.
2. **Blend & style:** blend mode, fill/opacity, clipping mask, layer style (drop shadow, stroke, glow, overlay) đọc/ghi.
3. **Filters:** Gaussian/Motion/Lens blur, Unsharp/Smart Sharpen, High Pass, Noise, Camera Raw Filter (tham số chính) — ưu tiên áp lên Smart Object (smart filter).
4. **Chọn & mask nâng cao:** Select Subject/Sky, Color Range, Select and Mask (refine edge), chuyển kênh ↔ vùng chọn, lưu/đọc kênh alpha.
5. **Sửa ảnh:** Content-Aware Fill, Remove Tool, Generative Fill/Expand (khi API cho phép), Liquify cơ bản nếu UXP hỗ trợ.
6. **Màu & xuất:** chuyển profile màu, chế độ 8/16 bit, export nhiều kích thước/định dạng, export từng group/artboard.
7. **Văn bản:** sửa nội dung, font, cỡ, màu, căn lề của text layer có sẵn.
8. **Thông tin:** histogram, lấy mẫu màu tại điểm/vùng (phục vụ ghép vật và cân màu).

Mỗi tool mới: docstring rõ tham số + đơn vị pixel, test, ví dụ trong README.

## Giai đoạn 3 — Chuyển mặc định

Khi cả giai đoạn 1 đạt và chủ dự án duyệt: UXP thành backend mặc định, COM thành dự phòng (`PS_BACKEND=com`). Cập nhật README, UXP-SETUP.md.
