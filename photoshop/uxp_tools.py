"""Optional additive MCP tools; existing COM tools remain unchanged."""
import asyncio
import json
import urllib.error
import urllib.request
from uxp_bridge import get_token, validate

BASE_URL = "http://127.0.0.1:8766"


def request(path, payload=None):
    try:
        token = get_token()
        data = None if payload is None else json.dumps(payload, allow_nan=False).encode("utf-8")
        req = urllib.request.Request(BASE_URL + path, data=data, headers={
            "Authorization": "Bearer " + token, "Content-Type": "application/json"})
        # Do not send loopback traffic through system-configured proxies.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=35) as response:
            return json.load(response)
    except FileNotFoundError:
        return {"success": False, "error": "Start uxp_bridge.py and connect the Photoshop UXP panel first."}
    except (OSError, ValueError, urllib.error.URLError):
        return {"success": False, "error": "UXP bridge unavailable, token invalid, or request interrupted. For a mutation, outcome may be unknown: inspect Photoshop before retrying."}


async def call(operation, args):
    try:
        validate(operation, args)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    return await asyncio.to_thread(request, "/call", {"operation": operation, "args": args})


def register_uxp_tools(mcp):
    @mcp.tool()
    async def photoshop_uxp_status() -> dict:
        """Trạng thái cầu nối UXP tùy chọn (không khởi động Photoshop, không sửa tài liệu)."""
        return await asyncio.to_thread(request, "/health")

    @mcp.tool()
    async def photoshop_uxp_get_session_info() -> dict:
        """Đọc danh sách tài liệu bằng API UXP chính thức. Cần mở panel MCP UXP Bridge và kết nối."""
        return await call("session_info", {})

    @mcp.tool()
    async def photoshop_uxp_get_document_info(document_id: int | None = None,
                                               include_layers: bool = True, max_depth: int = -1) -> dict:
        """Đọc tài liệu/cây layer qua UXP, kích thước pixel. Lấy ID từ công cụ UXP, không giả định ID COM tương đương."""
        args = {"include_layers": include_layers, "max_depth": max_depth}
        if document_id is not None:
            args["document_id"] = document_id
        return await call("document_info", args)

    @mcp.tool()
    async def photoshop_uxp_update_layer(document_id: int, layer_id: int, name: str | None = None,
                                          visible: bool | None = None, opacity: float | None = None) -> dict:
        """Đổi tên/hiện/ẩn/opacity layer qua UXP, một bước Undo, không lưu file.
        Cần ID tài liệu và layer đọc từ UXP. Khi timeout không tự gọi lại hoặc chuyển sang COM:
        kiểm tra tài liệu trước vì lệnh có thể đã chạy. Lỗi trong modal được rollback bằng History API.
        """
        args = {"document_id": document_id, "layer_id": layer_id}
        args.update({key: value for key, value in {"name": name, "visible": visible, "opacity": opacity}.items()
                     if value is not None})
        return await call("update_layer", args)
