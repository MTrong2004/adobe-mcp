# Adobe MCP

Bộ server MCP tự viết để agent AI điều khiển ứng dụng Adobe trên máy (Windows). Mỗi app là **một server MCP riêng** để agent chỉ bật app cần dùng.

| Thư mục | App | Trạng thái |
|---|---|---|
| [`photoshop/`](photoshop/) | Photoshop 2027 | Đang dùng (COM/ExtendScript); đang chuyển sang UXP theo [`photoshop/UXP-ROADMAP.md`](photoshop/UXP-ROADMAP.md) |
| [`core/`](core/) | — | Phần dùng chung, tách dần khi có app thứ hai |

Chạy server Photoshop:

```
uv run --script "C:/Users/trong/VS Code/adobe-mcp/photoshop/server.py"
```

Không phải sản phẩm của Adobe.
