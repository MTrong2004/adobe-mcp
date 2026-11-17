# Kiểm thử và mức độ sẵn sàng

Lượt xác minh ngày 2026-11-17: aggregate **exit 0**, 42 Python + 39 Node = **81 unit tests PASS**, kèm Premiere schema check và MCP SDK stdio thật cho cả ba app (AE 9 / Premiere 8 / Photoshop 25 tools). Live Premiere **exit 1, disconnected**; AE chưa có host được phát hiện. Xem [báo cáo kết quả thực tế](TEST-REPORT.md) để phân biệt giao thức PASS với live chưa đạt.

## Lệnh tổng hợp

```powershell
python "C:/Users/trong/VS Code/adobe-mcp/scripts/adobe.py" test
```

Runner gom unittest của CLI, core, AE và Photoshop; script SDK/schema Premiere được chạy thực sự bằng uv (không nạp nhầm dưới unittest rồi báo 0 test). Node `--test` chạy cả suite `.test.js` và `.test.cjs` của panel, sau đó chạy MCP SDK stdio thật cho ba app. Suite Node thiếu hoặc uv thiếu là lỗi; không âm thầm bỏ qua. Nếu cần kiểm tra offline: thêm `--skip-protocol`; kết quả này không chứng minh giao thức MCP. Chạy mặc định khi bridge/plugin AE và Premiere đang ngắt kết nối; nếu panel đang live hãy dùng smoke live riêng.

```powershell
python "C:/Users/trong/VS Code/adobe-mcp/scripts/adobe.py" test --skip-protocol
uv run --script "C:/Users/trong/VS Code/adobe-mcp/scripts/mcp_smoke.py"
uv run --script "C:/Users/trong/VS Code/adobe-mcp/scripts/mcp_smoke.py" --app premiere --live
uv run --script "C:/Users/trong/VS Code/adobe-mcp/scripts/mcp_smoke.py" --app aftereffects --live
```

MCP smoke dùng SDK `mcp==1.30.0`, khởi động server con bằng uv/stdin/stdout, thực hiện `initialize`, `tools/list`. AE/Premiere gọi `*_session_info` không sửa tài liệu và kiểm tra lỗi có cấu trúc `disconnected` ở chế độ mặc định. Không dùng stub để thay giao thức. Photoshop chỉ initialize/list để tránh tự khởi động Photoshop qua COM. `--live` AE/Premiere bắt buộc tool trả `success: true`; thiếu app/plugin là FAIL, không chuyển thành PASS hay skip. Kết quả không in payload dự án hoặc bearer token.

## Các tầng bằng chứng

| Kiểm tra | Chứng minh | Không chứng minh |
|---|---|---|
| Python/Node unit tests | Validation, hàng đợi, dispatcher, lỗi và hợp đồng CLI theo fixture | API Adobe thực chạy |
| MCP protocol mặc định | SDK thật kết nối server stdio, tool schemas và lỗi disconnected rõ ràng | Plugin đã cài/Load hoặc xử lý job thật |
| Doctor | Công cụ, registry Adobe, manifest, bridge có xác thực, poll gần đây | Lệnh Adobe đã hoàn thành |
| Live session_info | Plugin nhận và trả lệnh đọc trong Adobe | Mọi thao tác ghi/export đã được xác minh |
| Scratch thao tác ghi | Chỉ nghiệp vụ đã thực sự chạy trên host đó | Tất cả tính năng hoặc mọi phiên bản Adobe |

## Scratch suite thủ công

Chưa có bằng chứng live AE khi AE chưa cài và chưa có bằng chứng Premiere khi UDT chưa Load plugin. Để kiểm thử thao tác ghi an toàn: tạo dự án scratch riêng trong Adobe, lưu bản sao vào thư mục cục bộ được chỉ định, chuẩn bị một clip hợp lệ và thư mục xuất ghi được, đóng modal, mở đúng panel và chạy live session_info trước. Sau đó thử lần lượt tạo/import/list/đổi tên/undo/lưu hoặc export đúng các tool của app, quan sát kết quả trực tiếp trong UI, mở file xuất để xác nhận. Ghi lại phiên bản host, tool/args đã bỏ thông tin riêng, file output, quan sát và lỗi. Chưa chạy thì ghi “chưa kiểm thử”, không gán PASS.

Nếu cần media nhỏ hoàn toàn cục bộ, dùng ffmpeg, không gọi dịch vụ tạo media:

```powershell
ffmpeg -f lavfi -i "testsrc2=size=320x180:rate=24" -t 2 -c:v libx264 -pix_fmt yuv420p "C:/scratch/adobe-mcp-test.mp4"
ffprobe -v error -show_format -show_streams -of json "C:/scratch/adobe-mcp-test.mp4"
```

Tự tạo `C:/scratch` trước và chọn tên file mới; ffmpeg không ghi đè nếu chưa xác nhận. Các lệnh này chỉ tạo/đọc fixture cục bộ, không chứng minh import/export Adobe. Không chạy scratch suite trên dự án sản xuất đang mở. Khi timeout có `outcome_unknown`, kiểm tra app trước khi gọi lại; tuyệt đối không retry thao tác ghi tự động.
