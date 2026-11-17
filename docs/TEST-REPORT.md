# Báo cáo kiểm thử triển khai — 2026-11-17

Kết quả cuối: **aggregate PASS, exit 0**. Đây là bằng chứng unit tests và giao thức MCP thật hoạt động. **Chưa đạt live AE/Premiere**: bridge có kết nối HTTP nhưng chưa có panel/plugin đang kết nối; live Premiere đã thử và FAIL rõ ràng với `disconnected`.

## Lệnh đã chạy và kết quả

Từ root repo trên Windows:

```powershell
python scripts/adobe.py test
```

Runner đã thực sự chạy các suite sau, không có suite unittest 0 test:

| Suite | Kết quả |
|---|---|
| CLI operational contracts — `python -m unittest discover -s tests -p test_*.py` | 6/6 PASS |
| Core bridge/client — `python -m unittest discover -s core -p test_*.py` | 15/15 PASS |
| AE MCP schemas/dispatch — `python -m unittest discover -s aftereffects/tests -p test_*.py` | 3/3 PASS |
| Photoshop Python runtime/bridge — `python -m unittest discover -s photoshop -p test_*.py` | 18/18 PASS |
| Premiere SDK schemas — `uv run --script premiere/test_server.py` | PASS, 8 tool schemas qua stdio thật |
| AE adapter/panel — `node --test aftereffects/tests/adapter.test.cjs` | 11/11 PASS |
| Premiere UXP dispatcher/client — `node --test premiere/tests/plugin.test.js` | 16/16 PASS |
| Photoshop UXP dispatcher/client — `node --test photoshop/uxp-plugin/tests/plugin.test.js` | 12/12 PASS |
| MCP SDK integration — `uv run --script scripts/mcp_smoke.py` | PASS cho cả ba app |

Tổng unit tests: **42 Python + 39 Node = 81 PASS**; thêm Premiere schema protocol và ba phiên MCP integration thật. Các unit test adapter mô phỏng API Adobe, không phải kiểm thử host live.

## MCP integration thật

Dùng Python MCP SDK `mcp==1.30.0`, SDK client khởi động server subprocess bằng uv/stdin/stdout, gọi `initialize` rồi `tools/list`. Protocol version thương lượng: `2025-11-25`.

| App | Tools | Kết quả đọc |
|---|---|---|
| After Effects | 9 | `aftereffects_session_info` trả lỗi có cấu trúc `disconnected` đúng kỳ vọng của protocol smoke |
| Premiere | 8 | `premiere_session_info` trả lỗi có cấu trúc `disconnected` đúng kỳ vọng của protocol smoke |
| Photoshop | 25 | Initialize/list PASS; không gọi COM và không sửa tài liệu |

Protocol smoke dùng server và SDK thật, không thay bằng stub. PASS disconnected xác nhận cơ chế lỗi hoạt động; không có nghĩa Adobe đã chạy thành công một lệnh.

## Live Photoshop bổ sung sau aggregate

```powershell
python -m unittest discover -s tests -v
uv run --script scripts/mcp_smoke.py --app photoshop --live
```

Focused operational tests: **8/8 PASS**, gồm hai regression tests mới cho hợp đồng `success/is_running/version`, phản hồi MCP lỗi và unwrap lỗi do smoke sở hữu mà không lộ nội dung lỗi bên ngoài. Đây là lượt focused bổ sung; không gộp sai thành một lần aggregate 83 tests chưa thực chạy.

Live Photoshop: **exit 0**, kết quả quan sát thực:

```text
PASS photoshop: SDK initialize (2025-11-25), tools/list (25 tools), photoshop_get_session_info live read-only; version 28.0.0; success/is_running/version checks passed
```

Server báo Photoshop chưa chạy và khởi động app qua COM, sau đó gọi tool đọc session trên host thật. Smoke có timeout tổng 90 giây, kiểm tra `success: true`, `is_running: true`, phiên bản hợp lệ; không dùng mock để báo live thành công. Không in thông tin tài liệu, tên file, payload session hoặc credential. Không tạo/sửa/lưu/xuất tài liệu. Kết quả chỉ chứng minh đường MCP → COM → đọc session trên Photoshop 28.0.0; chưa chứng minh tính năng ghi hoặc UXP Photoshop.

## Live và triển khai thực tế AE/Premiere

```powershell
uv run --script scripts/mcp_smoke.py --app premiere --live
```

Kết quả **exit 1**, thông báo:

```text
FAIL: LIVE FAIL premiere: disconnected; start bridge and load panel/plugin
```

Doctor được chạy bằng `python scripts/adobe.py doctor --json` sau khi lead khởi động hai bridge:

| Hạng mục | Quan sát |
|---|---|
| Bridge AE 8767 | `token_present: true`, `reachable: true`, `plugin_connected: false` |
| Bridge Premiere 8768 | `token_present: true`, `reachable: true`, `plugin_connected: false` |
| Manifest AE, Premiere, Photoshop | Cả ba parse hợp lệ |
| Premiere | 26.0.1, executable `D:/Default_app/Adobe Premiere Pro 2026/Adobe Premiere Pro.exe` tồn tại |
| Photoshop | 28.0.0.20 qua uninstall registry |
| After Effects | Chưa được phát hiện trong registry Adobe/hai gốc được phép |
| UXP Developer Tool | Chưa được phát hiện qua registry và các executable mục tiêu |
| Công cụ | uv 0.12.15, Python 3.11.9, Node 24.19.0, ffmpeg/ffprobe 9.0.1 có sẵn |

Lead đã copy panel AE vào target CEP được chỉ định bằng installer, **không bật debug**, và tạo cấu hình MCP/doctor cục bộ trong thư mục runtime được gitignore. Copy panel chưa đủ để chạy live khi host AE chưa được phát hiện. Không có token hoặc payload dự án trong báo cáo này.

Để hoàn tất live Premiere: cài UDT 2.2+; bật developer mode trong Premiere và restart; UDT Add manifest, Load & Watch rồi mở panel, nhập token riêng và Connect. Sau đó chạy lại lệnh `--live`. AE cần host được cài/khởi chạy, cho phép panel theo hướng dẫn triển khai, mở panel và Connect. Chỉ coi live đạt khi `session_info` thành công từ plugin thực.

Chưa chạy scratch suite ghi/import/export trên Adobe host trong lượt kiểm thử này. Không có cam kết mọi thao tác ghi đã kiểm chứng live. Xem [quy trình kiểm thử](TESTING.md) và [triển khai](DEPLOYMENT.md) để hoàn thành các điều kiện còn thiếu.
