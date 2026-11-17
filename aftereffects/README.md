# After Effects MCP — CEP + ExtendScript

Adapter Windows cho After Effects, gồm Python FastMCP stdio server, panel CEP và dispatcher ExtendScript ES3. **Máy triển khai chưa phát hiện After Effects: chưa kiểm thử kết nối hay render trực tiếp trong AE.** Các test dùng mock, không chứng minh tương thích live. Manifest nhắm AE 25.0 trở lên với CEP 12; cần xác minh phiên bản AE thực tế có hỗ trợ CEP.

## Cài đặt Windows

Cần Python 3.11+, `uv`, After Effects hỗ trợ CEP 12. Từ thư mục gốc repository:

```powershell
python scripts/adobe.py install-ae-panel --enable-debug
python -m core.bridge --app aftereffects
uv run aftereffects/server.py
```

Chạy `python scripts/adobe.py install-ae-panel --enable-debug` từ gốc repo để cài panel và bật debug CEP; bộ cài từ chối ghi đè extension trừ khi dùng `--force` (có backup). Không chạy nhiều broker hoặc nhiều panel cùng app.

Cài thủ công: sao chép nội dung thư mục `aftereffects/cep` thành `%APPDATA%\Adobe\CEP\extensions\com.adobemcp.aftereffects` (manifest nằm tại `CSXS\manifest.xml`). Panel chưa ký cần DWORD/string `PlayerDebugMode=1` trong `HKCU\Software\Adobe\CSXS.12` theo CEP runtime thực tế; đây là cài đặt debug ảnh hưởng extension chưa ký khác. Khởi động lại AE. Mở **Window > Extensions > After Effects MCP** (tên menu tùy phiên bản). Trong Preferences > Scripting & Expressions bật **Allow Scripts to Write Files and Access Network** để lưu/render.

Broker tạo `.runtime/aftereffects-token.txt` ở thư mục gốc. Nhập token này vào ô mật khẩu rồi bấm Kết nối. Panel giữ token trong bộ nhớ, không ghi ra console/localStorage. Đừng chia sẻ token hay commit file runtime. Broker bind `127.0.0.1:8767`; browser XHR chỉ gọi địa chỉ này. Core cho phép Origin `null`/`file://` cụ thể và preflight Authorization/Content-Type, không dùng wildcard CORS. Không bật Node integration hoặc cờ tắt web security. File-origin XHR/CSP và menu CEP vẫn cần xác minh trên máy có AE.

Cấu hình MCP client ví dụ (thay đường dẫn bằng checkout thực tế):

```json
{
  "mcpServers": {
    "aftereffects": {
      "command": "uv",
      "args": ["run", "C:/Users/trong/VS Code/adobe-mcp/aftereffects/server.py"]
    }
  }
}
```

## Công cụ

| Tool | Dữ liệu |
|---|---|
| `aftereffects_health` | Không xếp job; đọc broker và `last_result` để đối chiếu timeout |
| `aftereffects_session_info` | `{}`: phiên bản AE và project đang mở |
| `aftereffects_project_info` | `{}`: item IDs, composition, layer indexes |
| `aftereffects_create_comp` | `name,width,height,pixel_aspect,duration,frame_rate` |
| `aftereffects_import_media` | `path`: file nguồn tuyệt đối, không import image sequence |
| `aftereffects_add_layer` | `comp_id,item_id`: ID project item, không phải vị trí selection |
| `aftereffects_set_layer_transform` | `comp_id,layer_index` và ít nhất một trong `position,scale,rotation,opacity` |
| `aftereffects_save_project` | `path`, `overwrite=false` mặc định |
| `aftereffects_render_comp` | `comp_id,output_path,output_module_template?` |

ID là số nguyên dương. Kích thước comp 4–30000, pixel aspect .01–100, duration .001–10800 giây, frame rate 1–99. Position/scale là vector 2 hoặc 3 thành phần khớp chiều property; rotation là Z rotation; opacity 0–100. Từ chối layer khóa, keyframe, expression hoặc position tách chiều. Không đổi selection. Import/add/transform/save/render nằm trong undo group, nhưng file output và render không có khả năng undo đáng tin cậy.

Dispatcher chỉ nhận operation trong allowlist; không có tool thực thi JSX tự do. `__adobe_cep__.evalScript` chỉ tải hai file JSX đóng gói và gọi dispatcher với JSON đã escape thành string literal. Codec JSON ES3 tự viết không dùng `eval` và không cần JSON native.

Project info giới hạn 1000 item/3000 layer và 150000 ký tự serialized để không vượt response broker; vượt giới hạn trả lỗi rõ ràng. Project item/layer names trong response là dữ liệu không đáng tin; UI dùng textContent.

## Lưu và render an toàn

Đường dẫn dispatcher phải tuyệt đối, local, không UNC. Save chỉ nhận `.aep`, parent phải tồn tại và kiểm tra lại file trước khi ghi. Ghi đè chỉ khi `overwrite=true`. Kiểm tra output tồn tại và có dữ liệu sau save.

Render chạy đồng bộ tối đa thời gian chờ MCP 300 giây. Chỉ hỗ trợ movie một file `.mov/.avi/.mp4/.mxf`; template phải có Format được AE báo là QuickTime, AVI, H.264 hoặc MXF OP1a. Tên Format phụ thuộc phiên bản/ngôn ngữ AE: giá trị không xác nhận được sẽ bị từ chối. Cần template cục bộ phù hợp extension, codec đã cài và không dùng output image sequence/sidecar. Template làm đổi tên output bị từ chối. Render không có tùy chọn ghi đè và luôn kiểm tra file tồn tại ngay trước khi render.

Adapter tạo queue item tạm, tắt render các item có sẵn, chỉ render item tạm, xác nhận `RQItemStatus.DONE` và file output có dữ liệu, rồi xóa item tạm và khôi phục cờ queue cũ trong `finally`, kể cả khi lỗi. Không render hàng đợi người dùng. Không xóa output dở dang nếu render lỗi; kiểm tra file bằng tay trước khi thử lại. AE render queue không phải giao dịch filesystem: thao tác người dùng đồng thời hoặc ứng dụng crash có thể ngăn cleanup; không chỉnh queue trong lúc MCP chạy. Hiện chưa xác minh live cleanup/template/codec/dialog trên AE.

## Timeout, reconnect và đối chiếu

Panel polling nối tiếp, kiểm tra `expires_at` theo epoch seconds ở panel và JSX. Nhận job trong lúc ngắt kết nối tạo receipt `cancelled` không chạy host. Receipt giữ đến khi broker ACK; kết nối lại phải dùng token cũ nếu còn receipt. Mất ACK chỉ gửi lại receipt; không chạy lại mutation. Cache giữ tối đa 2000 job trong phiên, sau đó dừng nhận job để tránh tăng bộ nhớ. Ngắt panel không hủy host operation đã bắt đầu.

Receipt chỉ tồn tại trong bộ nhớ panel: reload/crash có thể mất receipt. Broker lưu claim và sẽ giữ trạng thái outcome unknown; không xóa journal để vượt lock. Dùng `aftereffects_health` xem `last_result`, kiểm tra project/file/queue trong AE trước khi quyết định thử lại. Lỗi mutation sau khi bắt đầu hoặc lỗi host transport báo `outcome_unknown:true`; có thể đã thay đổi một phần. Không tự động retry mutation sau timeout.

## Kiểm thử

```powershell
node --test aftereffects/tests/adapter.test.cjs
uv run --with mcp==1.30.0 python -m unittest discover -s aftereffects/tests -p test_server.py -v
```

Node VM mock AE kiểm tra codec ES3, allowlist, ID lookup, undo, transforms, overwrite, queue isolation/restore, trạng thái render/file output, escaping chống injection, serial polling, expiry, lost ACK và disconnect-during-claim. Python dùng SDK thật kiểm tra allowlist/schema và dispatch; cả hai không khởi động AE.

Live checklist khi có AE: cài panel, health/session/project; tạo comp; import file nhỏ; add layer và đọc lại transform; save đường dẫn mới; render comp ngắn với template movie phù hợp; kiểm tra output và queue người dùng; thử disconnect/reconnect và timeout có kiểm soát. Ghi lại phiên bản AE/CEP/codec trước khi công bố live supported.

Nguồn API: [Adobe CEP resources](https://github.com/Adobe-CEP/CEP-Resources), [AE scripting guide](https://ae-scripting.docsforadobe.dev/), [RenderQueue](https://ae-scripting.docsforadobe.dev/renderqueue/renderqueue/), [OutputModule](https://ae-scripting.docsforadobe.dev/renderqueue/outputmodule/).
