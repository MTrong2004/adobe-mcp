# Shared app bridge

Core cung cấp broker HTTP loopback và Python client cho After Effects CEP, Premiere UXP. Photoshop giữ đường COM/bridge riêng để bảo toàn tương thích.

```powershell
python "C:/Users/trong/VS Code/adobe-mcp/scripts/adobe.py" bridge --app aftereffects
python "C:/Users/trong/VS Code/adobe-mcp/scripts/adobe.py" bridge --app premiere
```

Chạy mỗi lệnh trong terminal riêng nếu cần cả hai app. Tương đương `python -m core.bridge --app <app>` khi cwd là root repo. Port mặc định AE 8767, Premiere 8768; chỉ bind `127.0.0.1`. Token riêng mỗi app tại `.runtime/<app>-token.txt`. Không đưa token vào command line hoặc output chẩn đoán. Chỉ một panel đang poll cho mỗi app.

Client nội bộ: `BridgeClient(app, port=None).health()` và `.call(operation, args, timeout=30)` trả dict; thành công dùng `success: true`, lỗi có `success: false`, `error.code` và thông tin outcome. Health có xác thực, `plugin_connected` kiểm tra poll gần đây; `last_result` chứa `{job_id, result}` hoặc null để đối chiếu receipt khi cần, không in nó vào doctor vì có thể chứa dữ liệu dự án. Không dùng health thay một live call hoàn chỉnh.

Bridge giới hạn kích thước payload, timeout và hàng đợi một job; job đã claim không bị tự dispatch lại khi timeout. Journal trong `.runtime` bảo toàn claim chưa rõ qua restart; receipt cho phép xác nhận lại việc gửi kết quả mà không chạy lại thao tác Adobe. Kiểm tra trạng thái host và receipt trước khi thử lại khi `outcome_unknown`. Không xóa journal chỉ để xóa trạng thái busy. Token/journal và payload có thể chứa dữ liệu riêng; không upload nguyên thư mục runtime.

Xem [deployment](../docs/DEPLOYMENT.md), [testing](../docs/TESTING.md) và test core bằng `python -m unittest core.test_bridge -v` từ root repo. Unit tests mô phỏng panel không chứng minh API Adobe live.
