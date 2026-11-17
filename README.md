# Adobe MCP

Bộ server MCP để agent AI điều khiển ứng dụng Adobe trên Windows. Mỗi app là **một server MCP riêng**, chỉ bật app cần dùng. Không phải sản phẩm của Adobe.

| Thư mục | Host / kết nối | Mức sẵn sàng |
|---|---|---|
| [photoshop](photoshop/) | Photoshop 28; COM/ExtendScript mặc định, UXP tùy chọn | Đường COM đang dùng; giữ nguyên hướng dẫn [UXP roadmap](photoshop/UXP-ROADMAP.md) và [setup](photoshop/UXP-SETUP.md) |
| [aftereffects](aftereffects/) | AE CEP + ExtendScript qua bridge 8767 | Có server/panel/tests; AE chưa được phát hiện trên máy, cần cài host và live smoke |
| [premiere](premiere/) | Premiere UXP trực tiếp qua bridge 8768 | Premiere 26.0.1 được phát hiện; cần UDT Add/Load và live smoke trước khi coi là kết nối |
| [core](core/) | Broker/client dùng chung AE và Premiere | Loopback auth, hàng đợi tuần tự, journal bảo vệ outcome chưa rõ |

Chạy từ PowerShell ở bất kỳ thư mục nào; giữ dấu nháy quanh đường dẫn có dấu cách:

```powershell
python "C:/Users/trong/VS Code/adobe-mcp/scripts/adobe.py" doctor --json
python "C:/Users/trong/VS Code/adobe-mcp/scripts/adobe.py" config --app photoshop --app premiere
python "C:/Users/trong/VS Code/adobe-mcp/scripts/adobe.py" test
```

Cần Python 3.11+, uv và Node.js cho kiểm thử panel; ffmpeg/ffprobe tùy công việc media. `config` in JSON với executable uv và đường dẫn server tuyệt đối để dán vào cấu hình MCP client. Dependency MCP SDK được pin `mcp==1.30.0` trong script metadata. Lệnh chạy Photoshop cũ vẫn dùng được:

```powershell
uv run --script "C:/Users/trong/VS Code/adobe-mcp/photoshop/server.py"
```

AE/Premiere cần bridge riêng và panel/plugin thực sự mở trong host:

```powershell
python "C:/Users/trong/VS Code/adobe-mcp/scripts/adobe.py" bridge --app premiere
```

Đọc [triển khai](docs/DEPLOYMENT.md) để cài panel AE, bật debug có chủ đích và Add/Load Premiere bằng UXP Developer Tool. Chỉ có manifest hoặc bridge đang chạy chưa chứng minh app đã kết nối. [Kiểm thử](docs/TESTING.md) phân biệt unit/mock, giao thức MCP thật và live Adobe; lệnh live thiếu plugin sẽ FAIL rõ ràng. [Nguồn tham khảo](docs/REFERENCES.md) ghi API chính thức và các dự án cảm hứng.

Token/journal lưu trong `.runtime/` được gitignore. Không in hoặc chia sẻ token. Khi thao tác timeout báo outcome chưa rõ, kiểm tra trạng thái Adobe trước khi thử lại; không tự retry thao tác sửa dự án. Không cần chạy web server riêng cho bộ công cụ này.
