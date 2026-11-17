# Triển khai trên Windows

Mỗi app có server MCP riêng. Photoshop dùng COM/ExtendScript mặc định; AE dùng CEP; Premiere dùng UXP trực tiếp. Không cần chạy thêm web server. Lệnh dưới đây chạy được từ bất kỳ thư mục PowerShell nào, kể cả đường dẫn có dấu cách.

## Kiểm tra và cấu hình

```powershell
python "C:/Users/trong/VS Code/adobe-mcp/scripts/adobe.py" doctor --json
python "C:/Users/trong/VS Code/adobe-mcp/scripts/adobe.py" config --app photoshop --app premiere --app aftereffects
```

Cài Python 3.11+, uv, Node.js; ffmpeg/ffprobe chỉ cần cho công việc media ngoài Adobe. `config` in JSON để đưa vào cấu hình MCP của client, không sửa client tự động. Mỗi server dùng `uv run --script` với đường dẫn tuyệt đối và dependency MCP SDK `mcp==1.30.0`. Lần đầu uv có thể cần mạng để tải dependency. Không dùng bare Python cho server nếu môi trường chưa cài dependency trong metadata của script.

`doctor` chỉ đọc uninstall registry Adobe và hai gốc `C:/Program Files/Adobe`, `D:/Default_app` với độ sâu giới hạn; không quét home/OneDrive. Nó kiểm tra executable Premiere chính xác `D:/Default_app/Adobe Premiere Pro 2026/Adobe Premiere Pro.exe`, phiên bản qua uninstall registry, công cụ trên PATH, manifest và health có xác thực. Trên máy triển khai: Premiere 26.0.1 và Photoshop 28 được phát hiện, AE chưa được phát hiện. Kiểm tra lại bằng doctor vì môi trường có thể thay đổi.

`reachable: true` chỉ xác nhận bridge trả lời có xác thực. `plugin_connected: true` nghĩa panel vừa poll; chỉ live smoke thành công mới chứng minh một lệnh đọc thực sự chạy trong Adobe. Có manifest không đồng nghĩa plugin đã được cài hoặc Load. Doctor không in token, payload dự án hoặc kết quả lệnh gần nhất.

## Photoshop

```powershell
uv run --script "C:/Users/trong/VS Code/adobe-mcp/photoshop/server.py"
```

MCP client phải quản lý stdio; chạy tay chỉ để chẩn đoán, không gõ văn bản vào stdio. COM mặc định có thể khởi động Photoshop khi gọi tool. Hướng dẫn UXP tùy chọn giữ tại [Photoshop UXP setup](../photoshop/UXP-SETUP.md); UXP Photoshop là đường riêng, không dùng token AE/Premiere.

## After Effects CEP

1. Cài After Effects bản hỗ trợ runtime trong manifest CEP. AE hiện chưa được phát hiện trên máy này, nên chưa thể xác nhận live.
2. Cài panel; chỉ bật chế độ extension unsigned bằng cờ tường minh:

```powershell
python "C:/Users/trong/VS Code/adobe-mcp/scripts/adobe.py" install-ae-panel --enable-debug
python "C:/Users/trong/VS Code/adobe-mcp/scripts/adobe.py" bridge --app aftereffects
```

Installer chỉ copy panel từ `aftereffects/cep` vào `%APPDATA%/Adobe/CEP/extensions/com.adobemcp.aftereffects`. Nếu đã có target, mặc định từ chối; `--force` đổi tên bản cũ thành thư mục `.backup-<UTC>` trước khi copy. Không dùng `--force` để sửa extension của ứng dụng khác. Không có `--enable-debug` thì registry giữ nguyên; có cờ thì chỉ set `HKCU/Software/Adobe/CSXS.<major>/PlayerDebugMode=1` theo manifest.

3. Khởi động lại AE, mở Window > Extensions > panel Adobe MCP. Đọc token tại `.runtime/aftereffects-token.txt` bằng editor cục bộ và nhập riêng vào panel; không dùng lệnh in token, không gửi token qua chat. Chỉ mở một panel cho mỗi app. Sau đó bật server MCP trong client và chạy live smoke bên dưới.

## Premiere UXP

Premiere 25.6+ có API UXP; bản 26.0.1 trên máy đáp ứng yêu cầu phiên bản. **UXP Developer Tool (UDT) chưa được phát hiện; plugin chưa được xác nhận đã Add/Load hoặc kết nối.** Không copy plugin vào thư mục Adobe nội bộ để giả lập cài đặt.

1. Cài [UXP Developer Tool](https://creativecloud.adobe.com/apps/download/uxp-developer-tools) phiên bản 2.2+ qua Creative Cloud. Trong Premiere: Settings > Plugins > Enable developer mode, rồi khởi động lại Premiere.
2. Trong UDT chọn Add Plugin, chọn manifest tuyệt đối `C:/Users/trong/VS Code/adobe-mcp/premiere/uxp-plugin/manifest.json`, chọn Load & Watch. Mở panel từ Window > UXP Plugins.
3. Chạy bridge, nhập token `.runtime/premiere-token.txt` riêng trong panel và chọn Connect. Mỗi app chỉ một panel đang poll.

```powershell
python "C:/Users/trong/VS Code/adobe-mcp/scripts/adobe.py" bridge --app premiere
uv run --script "C:/Users/trong/VS Code/adobe-mcp/scripts/mcp_smoke.py" --app premiere --live
```

Lệnh live trả mã khác 0 khi app/plugin chưa kết nối; không chấp nhận disconnected như một lần triển khai thành công. Cách Add/Load chính thức: [Adobe Premiere UXP plugins](https://developer.adobe.com/premiere-pro/uxp/plugins/).

## Vận hành và khôi phục

Bridge AE/Premiere bind loopback lần lượt 8767/8768, bearer token riêng và journal trong `.runtime/` được gitignore. Không public port hoặc proxy bridge ra mạng. Chạy bridge bằng CLI sẽ dùng Python hiện tại, thư viện chuẩn, không cần MCP dependency. Dừng bằng Ctrl+C sau khi đảm bảo không còn job đang thực thi. Đừng tự chạy thêm bridge nếu port đã có chủ.

Timeout sau khi job đã được nhận có thể là `outcome_unknown`: đọc trạng thái app và kiểm tra kết quả trước khi làm lại. Bridge tuần tự hóa thao tác, giữ claim chưa rõ kết quả qua restart và cache receipt giới hạn. Không xóa journal/token để thử lại một thao tác có thể đã sửa dự án. Token sai, app đóng, panel chưa mở và modal đang chặn đều cần xử lý nguyên nhân trước khi retry. `.runtime` có thể chứa đường dẫn/nội dung dự án; không upload cả thư mục để debug.

Các lệnh ghi/import/export cần dự án hoặc media thật và có thể thay đổi tài liệu đang mở. Kiểm thử trên bản sao scratch và xác nhận đường dẫn output trước khi dùng. Không đưa thao tác ghi vào smoke mặc định.
