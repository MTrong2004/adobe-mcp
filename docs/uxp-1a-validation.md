# Roadmap 1a — đọc thông tin bằng UXP

## Phạm vi

Ba tên tool và tham số không thay đổi:

- `photoshop_get_session_info()`
- `photoshop_get_active_document_info(include_layers=True, max_depth=-1)`
- `photoshop_get_selection_info()`

Không có `PS_UXP_ENABLED=1`: chạy COM như trước. Khi bật: gửi các operation `get_session_info`, `get_active_document_info`, `get_selection_info` tới plugin UXP. Các thao tác khác vẫn dùng COM. Lỗi UXP trả về người gọi, không tự fallback hoặc retry. Bản pilot `photoshop_uxp_*` giữ nguyên schema cũ.

Kết quả tương thích là object phẳng có `success`, không bọc thêm `result`. Các trường document/layer theo `lib.jsx`: đơn vị pixel, làm tròn bounds hai chữ số, opacity một chữ số, tên enum theo ExtendScript, `child_count` tại giới hạn độ sâu. Mọi số âm của `max_depth` nghĩa là không giới hạn. Không đổi ruler units, tài liệu đang chọn, vùng chọn hoặc History để đọc thông tin.

Kiểm tra ID phát hiện tài liệu đang hoạt động bị chuyển và danh sách tài liệu mở thay đổi (kể cả thứ tự) trong lúc đọc. Đây không phải snapshot nguyên tử của các chỉnh sửa bên trong cùng một tài liệu; ID không đổi không bảo đảm nội dung tài liệu không đổi trong lúc đọc.

## Kiểm thử tự động

Chạy từ gốc repo:

```powershell
python -m unittest discover -s photoshop -p "test_uxp*.py" -v
node --test photoshop/uxp-plugin/tests/*.test.js
python scripts/adobe.py test
```

Python kiểm tra COM mặc định, opt-in truyền nguyên tham số/kết quả, không fallback khi lỗi, allowlist bridge và timeout. Node kiểm tra dispatcher với dữ liệu giả lập; không chứa PSD, hình hoặc thông tin khách hàng.

## Nghiệm thu Photoshop thật: CHƯA THỰC HIỆN

UXP Developer Tool chưa được phát hiện trong môi trường kiểm thử này, nên không thể nạp plugin để nghiệm thu trực tiếp trong Photoshop. Các kiểm thử tự động chỉ chạy với dữ liệu giả lập; chưa có bằng chứng output COM/UXP khớp trên PSD thật, ảnh export hoặc xác nhận độ tương thích action descriptor với Photoshop 2027. PR cần được giữ ở trạng thái chờ nghiệm thu trước khi duyệt chuyển mặc định.

Các bước nghiệm thu còn lại:

1. Tạo PSD mẫu không chứa dữ liệu riêng: ít nhất 3 layer, 1 group, 1 Smart Object; thêm text, mask và vector mask để kiểm tra đủ trường. Không dùng ảnh của khách.
2. Nạp plugin bằng UXP Developer Tool, chạy bridge và kết nối panel theo `photoshop/UXP-SETUP.md`. Dùng profile MCP riêng để thử UXP, không thay profile COM đang sử dụng.
3. Với cùng PSD và trạng thái không đổi, gọi ba tool trên profile COM rồi profile UXP. So sánh JSON đầy đủ, kể cả khi ruler là inches/points và ảnh 300 ppi. Chỉ lưu output đã kiểm tra không chứa đường dẫn riêng.
4. Kiểm tra `include_layers=False`, `max_depth=0/1/-1/-2`, nhóm lồng nhau, group rỗng, nhiều layer được chọn, text dài, layer ẩn, opacity lẻ, mask, vector mask, các blend mode và Smart Object.
5. So sánh selection rỗng/có selection; không tài liệu; tài liệu mới chưa lưu/đã lưu/đang có sửa chưa lưu. Kiểm tra path, saved, build, ruler_units và bit_depth.
6. Mở modal hoặc đang thao tác công cụ: yêu cầu đọc phải báo bận; không tự thử lại. Sau khi đóng modal thử lại theo yêu cầu người dùng.
7. Dùng tool export COM sẵn có để xuất JPEG mẫu; tự xem ảnh và đính kèm bản không có dữ liệu riêng cùng output so sánh vào PR. Xuất ảnh không thuộc triển khai 1a.

Chỉ mock tests đạt không đồng nghĩa nghiệm thu trong Photoshop đạt. Không tự lưu đè hoặc chỉnh tài liệu của người dùng để thực hiện kiểm tra.
