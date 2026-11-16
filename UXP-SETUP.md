# Photoshop MCP — cầu nối UXP thử nghiệm

Bản này dùng Photoshop UXP API chính thức nhưng là phần mềm tùy chỉnh, không phải connector Adobe for Creativity. Không cần Adobe OAuth hay dịch vụ cloud để cầu nối cục bộ giao tiếp; Photoshop và UXP Developer Tool vẫn phải cài/chạy hợp lệ trên máy.

## Cài và bật

1. Mở Photoshop (plugin yêu cầu phiên bản 25.10 trở lên).
2. Cài **UXP Developer Tool** từ Creative Cloud. Nếu được yêu cầu, bật Developer Mode trong Preferences > Plugins rồi khởi động lại Photoshop.
3. Trong UXP Developer Tool: **Add Plugin** > chọn `uxp-plugin/manifest.json` > **Load**. Mở panel **MCP UXP Bridge** từ menu Plugins.
4. Chạy `start-uxp-bridge.cmd` trong thư mục này, giữ cửa sổ đó mở. Cầu nối dùng Python 3.11+ và thư viện chuẩn, chỉ nghe `127.0.0.1:8766`.
5. Lần chạy đầu tạo `bridge-token.txt`. Mở file và chép token vào panel, bấm kết nối. Token là bí mật cục bộ: không gửi lên chat, không đưa vào Git. Chỉ kết nối **một panel** vào cầu nối. Panel không lưu token.
6. **UXP đang tắt mặc định.** Để kiểm thử có chủ đích, thêm `"env": {"PS_UXP_ENABLED": "1"}` vào mục MCP `photoshop`, rồi khởi động lại kết nối MCP. Chỉ giữ thiết lập này sau khi các bước kiểm thử trong Photoshop bên dưới đạt. Hiện chưa sửa cấu hình đang dùng; COM/ExtendScript vẫn là mặc định.

Repo hiện tại: `C:\Users\trong\VS Code\photoshop-mcp`. Lệnh chạy MCP: `uv run --script "C:/Users/trong/VS Code/photoshop-mcp/server.py"`. Script `.cmd` dùng `%~dp0` có dấu ngoặc kép nên hỗ trợ đường dẫn có khoảng trắng.

Biến môi trường `PS_UXP_TOKEN` tùy chọn thay thế file token; nếu dùng phải đặt cùng giá trị cho cả tiến trình bridge và MCP. Token tối thiểu 32 ký tự. Dừng bridge bằng Ctrl+C. Bridge không tự khởi động cùng Windows.

## Công cụ mới

- `photoshop_uxp_status`: kiểm tra bridge và panel; không mở Photoshop.
- `photoshop_uxp_get_session_info`: phiên bản và danh sách tài liệu đang mở.
- `photoshop_uxp_get_document_info`: đọc tài liệu, cây layer, kích thước pixel. `document_id` tùy chọn, `include_layers`, `max_depth` (-1 không giới hạn, 0 chỉ cấp đầu).
- `photoshop_uxp_update_layer`: bắt buộc `document_id`, `layer_id` đọc từ công cụ UXP; tùy chọn `name`, `visible`, `opacity` (0..100). Gộp thành một History state; rollback khi lỗi trong modal. Không lưu file.

Dữ liệu UXP không có đầy đủ mask/text metadata như công cụ COM cũ. Không chuyển toàn bộ workflow sang UXP trong bản thử nghiệm này. Không có thực thi JavaScript tùy ý trên endpoint UXP.

## Kiểm thử trong Photoshop

Thử trên tài liệu mới không lưu, không trên PSD đang làm việc:

1. Gọi status: `success: true`, `protocol: 1`, `plugin_connected: true`.
2. Đọc session, document; kiểm tra tên, kích thước, ID và cây layer khớp giao diện.
3. Chọn một layer thường trong tài liệu thử, ghi nhận tên/opacity. Gọi update_layer đổi tên và opacity trong cùng lệnh.
4. Kiểm tra History có đúng một bước của MCP. Undo ngay bằng giao diện, xác nhận cả hai thuộc tính trở lại như cũ.
5. Thử ID layer không tồn tại, opacity ngoài 0..100: phải trả lỗi, không thay đổi tài liệu.
6. Ngắt panel, thử đọc UXP: phải báo chưa kết nối; công cụ COM vẫn hoạt động.

Không tự Undo nếu người dùng đã chỉnh tài liệu sau lệnh của MCP. Nếu timeout sau khi giao lệnh, **không tự thử lại hoặc chuyển sang COM**: lệnh có thể đã chạy. Bridge giữ trạng thái bận tới khi nhận kết quả muộn; nếu cần khởi động lại, ngắt panel và kiểm tra Photoshop trước.

## Thiết kế và giới hạn

- Giao tiếp JSON qua HTTP loopback, header Bearer token; không bật CORS cho web công cộng. Token được đọc từ file của người dùng, không được in trong log.
- Một yêu cầu đang chạy tại một thời điểm; plugin lấy mỗi job một lần. Chỉ gửi lại kết quả, không chạy lại mutation khi lỗi mạng.
- Job có hạn 30 giây, được kiểm tra trước khi thực thi và trong modal. Timeout HTTP không thể bảo đảm hủy thao tác Photoshop đã bắt đầu.
- Giới hạn body 8 MiB; không truyền ảnh/pixel trong bản này. Chưa tích hợp Select Subject, Generative Fill, batchPlay tùy ý, xuất file hoặc tự động lưu.
- Không có Photoshop đang chạy khi kiểm thử tự động trên máy; kiểm thử UXP DOM/History thực tế cần hoàn tất các bước ở trên sau khi nạp plugin. Mock tests không thay thế kiểm thử trong host.

## Kiểm tra mã

```powershell
python -m unittest test_uxp_bridge -v
python -m py_compile server.py uxp_bridge.py uxp_tools.py
node --test uxp-plugin/tests/plugin.test.js
```

Bản sao entry point trước tích hợp: `server.py.bak-before-uxp-20261117`. Muốn tắt UXP, bỏ biến `PS_UXP_ENABLED` khỏi môi trường MCP rồi khởi động lại MCP; không cần sửa mã hay `lib.jsx`. Giữ nguyên các file `.bak`.

## Tài liệu Adobe

- [UXP Developer Tool](https://developer.adobe.com/photoshop/uxp/2022/guides/devtool/)
- [executeAsModal và History suspension/rollback](https://developer.adobe.com/photoshop/uxp/2022/ps-reference/media/executeasmodal/)
- [Photoshop UXP API](https://developer.adobe.com/photoshop/uxp/2022/ps-reference/)
