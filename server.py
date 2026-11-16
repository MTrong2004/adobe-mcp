# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "mcp==1.30.0",
#     "comtypes==1.5.0",
# ]
# [tool.uv]
# exclude-newer = "2026-11-15T00:00:00Z"
# ///
"""MCP server điều khiển Photoshop qua COM (Windows).

Khác bản gốc photoshop-mcp-server 0.1.14:
- Khoá phiên bản toàn bộ thư viện (khối script ở trên + exclude-newer).
- Mọi toạ độ / kích thước tính bằng pixel, không phụ thuộc đơn vị thước của Photoshop.
- Mỗi lệnh chạy bằng một script JSX duy nhất -> nhanh; mỗi lệnh sửa file là 1 bước Undo.
- Tự nối lại khi Photoshop khởi động lại; tự đợi khi Photoshop đang bận; có giới hạn thời gian.
- Giữ nguyên tên + tham số 9 công cụ cũ, thêm công cụ layer / mask / vùng chọn / xuất ảnh / undo.

Chạy: uv run --script server.py
Biến môi trường: PS_MCP_TIMEOUT (giây, mặc định 120).
"""

from __future__ import annotations

import asyncio
import concurrent.futures as cf
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Literal, Optional

import comtypes
import comtypes.client
from comtypes import COMError
from mcp.server.fastmcp import FastMCP, Image

LIB = (Path(__file__).with_name("lib.jsx")).read_text(encoding="utf-8")
TIMEOUT = float(os.environ.get("PS_MCP_TIMEOUT", "120"))
PROGID = "Photoshop.Application"

# HRESULT: mất kết nối (Photoshop đã đóng / khởi động lại)
DISCONNECTED = {-2147417848, -2147023174, -2147023170, -2147221251, -2147220995}
# HRESULT: Photoshop đang bận (hộp thoại / đang gõ chữ / script khác đang chạy)
BUSY = {-2147418111, -2147417846}


def log(msg: str) -> None:
    print(f"[photoshop-mcp] {msg}", file=sys.stderr, flush=True)


def _hr(e: BaseException) -> Optional[int]:
    if isinstance(e, COMError):
        return e.hresult
    if isinstance(e, OSError) and getattr(e, "winerror", None) is not None:
        return e.winerror
    return None


class PS:
    """Giữ kết nối COM trong một luồng riêng; tự nối lại, đợi khi bận, giới hạn thời gian."""

    def __init__(self) -> None:
        self._app = None
        self._pool = self._new_pool()

    @staticmethod
    def _new_pool() -> cf.ThreadPoolExecutor:
        return cf.ThreadPoolExecutor(max_workers=1, thread_name_prefix="ps-com", initializer=comtypes.CoInitialize)

    def _connect(self):
        try:
            return comtypes.client.GetActiveObject(PROGID, dynamic=True)
        except (COMError, OSError):
            log("Photoshop chưa chạy, đang mở Photoshop...")
            return comtypes.client.CreateObject(PROGID, dynamic=True)

    def _get_app(self):
        if self._app is not None:
            try:
                _ = self._app.Name  # kiểm tra kết nối còn sống
                return self._app
            except Exception as e:  # noqa: BLE001
                if _hr(e) in BUSY:
                    return self._app
                log(f"Mất kết nối Photoshop ({e}); nối lại.")
                self._app = None
        self._app = self._connect()
        return self._app

    def _run_sync(self, code: str) -> str:
        deadline = time.monotonic() + 15
        delay = 0.25
        reconnected = False
        while True:
            try:
                return self._get_app().DoJavaScript(code)
            except Exception as e:  # noqa: BLE001
                hr = _hr(e)
                if hr in BUSY and time.monotonic() < deadline:
                    time.sleep(delay)
                    delay = min(delay * 2, 2)
                    continue
                if hr in DISCONNECTED and not reconnected:
                    self._app = None
                    reconnected = True
                    continue
                if hr in BUSY:
                    raise RuntimeError("Photoshop đang bận (có hộp thoại đang mở hoặc đang sửa chữ?). Đóng hộp thoại rồi thử lại.") from e
                raise

    async def run(self, code: str, timeout: float = TIMEOUT) -> str:
        loop = asyncio.get_running_loop()
        fut = loop.run_in_executor(self._pool, self._run_sync, code)
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            # Luồng cũ đang kẹt chờ Photoshop: bỏ nó, tạo luồng + kết nối mới cho lệnh sau.
            self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = self._new_pool()
            self._app = None
            raise RuntimeError(
                f"Photoshop không trả lời sau {timeout:.0f}s (có thể đang mở hộp thoại hoặc lệnh quá nặng)."
            )


INSTRUCTIONS = """\
Photoshop MCP — quy tắc làm việc (đọc trước khi thao tác). Trả lời chủ dự án bằng tiếng Việt.

LÀM NGAY: việc nhỏ (1-3 thao tác) làm luôn, không trình bày kế hoạch. Chưa rõ thì làm bước đầu rồi nhìn kết quả.
KIỂM TRA MỘT LẦN: chỉ ở cuối, 1 ảnh toàn cảnh + 1 crop 100% vùng quan trọng (mọi chỗ "xuất ảnh xem" bên dưới là chỗ này).
Chỉnh lại tối đa 2 lượt; chưa ổn thì dừng, báo chủ dự án cái còn sai.

CÁCH LÀM
1. Việc nhiều bước (chèn nhiều logo/chữ, dàn trang): viết MỘT script cho photoshop_execute_jsx làm hết,
   bọc trong activeDocument.suspendHistory("Tên bước", "...") để thành 1 bước Undo. Không gọi từng công cụ lẻ hàng chục lần.
2. Dàn bố cục ngoài Photoshop trước (vd Python/PIL vẽ lên ảnh nền xuất từ PSD), xem ổn rồi mới áp vào PSD một lần.
3. Trước khi báo xong: xuất ảnh (photoshop_export_image) và tự mở xem, xem cả ở 100% nếu cần độ nét.
4. Thêm nhiều layer -> luôn gom vào group lồng nhau theo cấu trúc nội dung, tên tiếng Việt rõ nghĩa
   (vd "Logo NTT" > "Hàng 1" > "Nhà tài trợ Vàng"). Không để layer rời rạc.
5. KHÔNG tự lưu đè file (save/Ctrl+S, close save=True) khi chủ dự án chưa đồng ý. Không xoá layer cũ: ẩn đi.

KHÔNG ĐỤNG NGƯỜI DÙNG
6. Người dùng có thể đang thao tác trong Photoshop cùng lúc. Lỗi "Photoshop đang bận" = họ đang dùng / có hộp thoại: báo họ, đừng thử dồn dập.
7. photoshop_undo / đổi activeHistoryState: chỉ khi bước cuối đúng là của bạn (kiểm tra tên bước trong historyStates);
   nếu người dùng đã thao tác sau đó thì sửa trực tiếp, đừng lùi History.
8. Ảnh xuất phụ thuộc layer đang ẩn/hiện do người dùng bật tắt; để kiểm tra vị trí thì đọc bounds layer, đừng so ảnh.

BẪY KỸ THUẬT
9. Chỉ định layer bằng id (file thường có nhiều layer trùng tên). Lấy id từ photoshop_get_active_document_info.
10. Toạ độ/kích thước của server này luôn là pixel. File 300 ppi: cỡ chữ pt = px * 72 / 300.
11. Logo/ảnh: chèn bằng photoshop_place_image (Smart Object nhúng từ file gốc), co một lần tới kích thước cuối,
    KHÔNG phóng to quá kích thước file gốc (mờ). Không lồng Smart Object rồi co thêm. Logo tối màu trên nền tối: làm bản sáng màu.
12. Sửa nội dung Smart Object (.psb mở trong Temp) phải lưu .psb thì file chính mới cập nhật.
13. ExtendScript: layer.move(group, ElementPlacement.PLACEATEND) lỗi "Illegal Argument" -> dùng ElementPlacement.INSIDE
    (đưa lên đầu group, nên duyệt ngược thứ tự). Group con tạo bằng group.layerSets.add().
14. Layer tô màu (Solid Color) / adjustment luôn có sẵn mask trắng; photoshop_layer_mask sẽ thay mask cũ.
15. Script lỗi giữa chừng trong suspendHistory vẫn có thể để lại thay đổi dở (vd group rỗng): kiểm tra và dọn lại.

GHÉP VẬT VÀO ẢNH (composite)
0. DÙNG photoshop_composite_object: 1 lần gọi dựng đủ group (bóng tiếp xúc, bóng tán xạ, bóng đổ, hạ sáng, ám màu, hạt nhiễu,
   blur), tự lấy mẫu màu nền, trả kèm ảnh xem trước. Quy trình chuẩn: get_active_document_info + 1 ảnh toàn cảnh
   (export max_size=1600) -> chọn vị trí/góc/hướng sáng -> composite_object -> xem ảnh trả về -> gọi lại chỉnh tham số
   tối đa 2 lượt (group cũ tự ẩn). Tổng ~4-6 lần gọi. Chỉ tự dựng layer bằng execute_jsx khi công cụ thiếu thứ cần.
   Các mục dưới là cách chọn tham số cho đúng.
16. Khớp phối cảnh + tỉ lệ thật của vật trước tiên. Biến dạng NGAY TRÊN Smart Object trong Photoshop (photoshop_distort_layer
    bóp 4 góc; photoshop_transform_layer để co/xoay); KHÔNG xuất vật ra Python/OpenCV bẻ rồi dán lại (mất Smart Object, không chỉnh lại được).
    Vật cứng không uốn theo nền gồ ghề: nó chỉ chạm nền ở vài điểm.
16b. Ảnh tỉ lệ 2:1 (vd 7776x3888) gần như chắc là ảnh 360° equirectangular: đường thẳng bị cong, mặt đất phía dưới bị kéo giãn.
    Không dùng công thức phối cảnh camera thường. Đặt vật ở dải đất ngay dưới đường chân trời (ít méo), nén dẹt theo chiều dọc
    tương ứng độ xa; vật càng xuống thấp càng phải kéo giãn ngang. Nói rõ với chủ dự án là đang xử lý ảnh 360°.
17. Bóng theo hình dạng vật, không theo khuôn: luôn có bóng tiếp xúc (đậm, sát, đứt đoạn ở chỗ vật không chạm nền)
    + bóng mờ xung quanh. Bóng đổ dài chỉ khi vật có độ cao (cắm nghiêng, kênh lên); vật mỏng nằm bệt thì gần như không có.
18. Khớp màu/sáng: Curves cho điểm đen-trắng, màu môi trường hắt lên vật. Kim loại bóng phản chiếu môi trường
    (nằm dưới đất thường tối, xám, ngả màu nền), giữ điểm sáng chói ở mép vát, đúng hướng sáng.
19. Khớp độ nét (blur nhẹ theo DOF) và HẠT NHIỄU (layer noise) — thiếu bước này nhìn vẫn như dán.
20. Thứ đè lên vật (cỏ, sỏi, hạt đất) script không mask đẹp được: nói rõ phần này cần chấm cọ tay hoặc Select Subject trên nền.
21. Có thể thử Harmonize của Photoshop trước, nhưng ảnh lớn phải hạ xuống ~3000px (tính năng AI hay treo với ảnh to).
22. Xong: xuất ảnh, tự xem cả toàn cảnh và crop 100% vùng tiếp xúc rồi mới báo.

MASK NGƯỜI/VẬT: tách nhiều chủ thể (để Generative Fill, chỉnh màu...) -> photoshop_subject_masks 1 lần gọi với danh sách khung,
   không tự viết Select Subject/crop/paste bằng execute_jsx. Xem ảnh trả về, báo chủ thể nào bị dính nhau để người dùng sửa.
   Đặt name ("Tượng 4") + desc ngắn ("Tù nhân áo nâu giơ tay") + z (lớn = đứng trước) cho mọi khung chồng nhau.
   Mask gồm cả đồ cầm tay; không gồm bóng dưới đất và người thật đi ngang. Có `stuck_together` -> báo người dùng cặp nào cần sửa tay.

BIẾN TƯỢNG THÀNH NGƯỜI THẬT (cách chủ dự án đã duyệt)
- KHÔNG dùng Generative Fill (xoá sạch pixel, mất form áo; script cũng không gọi được nó). KHÔNG "chỉnh tay" bằng
  Dust&Scratches/Add Noise lên tượng (làm nát bề mặt). Chỉnh màu/texture chỉ đổi màu, không hết chất tượng.
- Làm: gửi NGUYÊN NGƯỜI kèm nền xung quanh cho Copilot gen (tool gen hàng loạt: C:/Users/trong/.gemini/tools/copilot-imagegen/README.md).
  1) Ẩn các group mask màu, photoshop_export_image region quanh tượng cắt ĐÚNG tỉ lệ 2:3 (dọc) -> Copilot trả 1024x1536 / 1365x2048
     nên đặt lại chỉ cần scale. Lưu JPG (<10MB) vào thư mục gen/ của dự án.
  2) File task: mỗi phương án 1 task riêng (`--variants` của gen-parallel đang lỗi), attach = ảnh crop. Prompt: biến tượng thành
     người thật, GIỮ NGUYÊN dáng, tỉ lệ, vị trí, khung hình, nền; vải cotton MỜ không bóng, không nếp điêu khắc; da có lỗ chân lông,
     không bóng sáp. Chạy 3-4 phương án, ghép thành 1 ảnh so sánh xem 1 lần, chọn bản tốt nhất. Ảnh ra giống hệt ảnh gửi = tool tải nhầm
     ảnh đính kèm (đã sửa 2026-11-16), so pixel để phát hiện.
     Vải/da còn bóng như tượng -> lượt 2: gửi chính ảnh người thật vừa gen, prompt NGẮN chỉ xin vải cotton mờ + da tự nhiên.
  3) photoshop_place_image vào đúng góc trên-trái của vùng crop, width = chiều rộng crop. Group riêng "Tượng N người thật (Copilot)".
  4) Mask: lấy từ layer "Mask tượng N (sửa mask ở đây)" CHỦ DỰ ÁN ĐÃ SỬA TAY (đọc lại trong PSD, không dùng mask tự tính cũ),
     nới ~30px + feather ~10px để không lộ viền tượng cũ (siết sát mép -> lộ bóng ma tượng quanh đầu/ngón tay).
  5) Xuất ảnh xem toàn cảnh + crop 100% đầu/tay/chân. Không xoá bản cũ, chỉ ẩn. Không lưu file khi chưa được đồng ý.
- Chỉ cần đổi trang phục: vẫn gửi nguyên người (để Copilot giữ đúng dáng), rồi chỉ lấy phần áo bằng mask quần áo chủ dự án sửa tay.
- MẪU CODE CHUẨN (chép dùng, đừng tự mò). Toàn bộ 1 lượt ghép = 1 lần gọi photoshop_execute_jsx:
    function sid(s){return stringIDToTypeID(s)}
    function selLayer(id){var r=new ActionReference();r.putIdentifier(sid("layer"),id);var d=new ActionDescriptor();
      d.putReference(sid("null"),r);executeAction(sid("select"),d,DialogModes.NO);}
    // nạp mask của layer id thành vùng chọn; add=true để cộng dồn nhiều tượng
    function loadMask(id,add){selLayer(id);var sel=new ActionReference();sel.putProperty(sid("channel"),sid("selection"));
      var m=new ActionReference();m.putEnumerated(sid("channel"),sid("channel"),sid("mask"));var d=new ActionDescriptor();
      if(add){d.putReference(sid("null"),m);d.putReference(sid("to"),sel);executeAction(sid("add"),d,DialogModes.NO);}
      else{d.putReference(sid("null"),sel);d.putReference(sid("to"),m);executeAction(sid("set"),d,DialogModes.NO);}}
    // đặt ảnh: placeEvent, rồi resize theo % để khớp đúng w x h vùng crop, rồi translate về góc trên-trái crop
    // tạo mask từ vùng chọn: make channel mask, using userMaskEnabled = revealSelection
  Crop gửi Copilot: doc.duplicate("tmp",true) -> crop([l,t,r,b]) -> saveAs PNG/JPG -> close không lưu. 1 script cho mọi vùng.
- BẪY ĐẶT ẢNH CÓ NỀN TRONG SUỐT: Smart Object đặt vào có bounds = phần CÓ PIXEL, không phải cả khung PNG.
  Muốn đặt đúng chỗ phải tính bbox alpha (python numpy nonzero) rồi translate tới (gốc crop + bbox.x, gốc crop + bbox.y).
- NHIỀU TƯỢNG NHỎ ĐỨNG GẦN NHAU: gộp chung 1 vùng crop 2:3, 1 task, mask = cộng dồn mask tay của tất cả tượng trong vùng.
- BỐI CẢNH LỊCH SỬ: trước khi viết prompt, hỏi/tra bối cảnh (nơi, năm). Ảnh này: Nhà lao Thiếu nhi Đà Lạt 1971-1973.
  Prompt ghi rõ năm + nơi + kiểu đồ thời đó; tù: quần áo cũ, ố, nhăn, vá, bụi bẩn (KHÔNG sạch đẹp). Nhìn kỹ tượng gốc mặc gì
  rồi tả đúng (vd áo sơ mi tối bỏ ngoài quần, KHÔNG phải vest) và viết "NOT a suit" khi model hay đoán sai.
  Chủ dự án đã duyệt cụm nào thì giữ nguyên, chỉ gen lại phần bị chê.
- MÁU / BẠO LỰC: Copilot chặn. Cách đã chạy được:
  1) Tẩy máu khỏi ảnh crop trước khi gửi (python cv2: mask pixel đỏ hue<20|>160, sat>60 trong vùng máu, dilate, cv2.inpaint).
  2) Prompt trung tính: không dùng các chữ blood, prisoner, torture, beat, fight, prison.
  3) Gen RIÊNG một ảnh "vải xám có vết rượu vang đỏ chảy dọc" (wine stains dripping) -> tách vết = ảnh / medianBlur(ảnh,81),
     alpha = (1 - kênh G) có ngưỡng; median 5-7 để bỏ hạt vải; co/đặt lên chỗ cần (đũng, đùi, chỗ tay nắm), chỉ hiện trên vải
     sáng (nhân alpha với mask độ sáng) + polygon giới hạn để không lem nền/người khác. Đặt layer Multiply. Ít quá thì tăng alpha.
  4) Layer máu tách từ tượng gốc thường KHÔNG khớp người mới (tư thế lệch) -> đừng dùng, làm theo bước 3.
- TOOL GEN COPILOT: chạy gen-parallel ở chế độ nền, KHÔNG ngồi chờ/hỏi tiến độ liên tục. Khi huỷ giữa chừng phải tắt hết tiến
  trình node gen-assets/gen-parallel (PowerShell: Get-CimInstance Win32_Process name=node.exe, lọc CommandLine, Stop-Process),
  nếu không lượt sau báo "Tài khoản N đang được một lượt gen khác dùng". Đổi file task trong gen.config.json ở GỐC dự án.
  Ghép xong nhiều ảnh: dán 3-4 bản cạnh nhau thành 1 ảnh so sánh (PIL) rồi xem 1 lần, không mở từng file.
- CHI TIẾT NHỎ (ánh bén lưỡi lam...): vẽ vệt sáng giả nhìn rất xấu, chủ dự án đã bỏ. Không tự vẽ highlight bằng tay; nếu cần thì
  gen bằng Copilot cả vùng nhỏ đó hoặc hỏi trước.

XEM ẢNH NHANH
23. File lớn (> 4000px): xem toàn cảnh bằng photoshop_export_image max_size=1600-2000; xem chi tiết 100% bằng region=[l,t,r,b]
    (không xuất cả ảnh rồi tự cắt). Không dùng photoshop_save_document để lấy ảnh xem trước.
24. Vật đã nằm trong PSD (Smart Object) thì làm việc trên layer đó; không quét ổ đĩa tìm file gốc.
25. Mô tả công cụ + hướng dẫn này là đủ; không đọc mã nguồn server. Lỗi quá giờ: kiểm tra Photoshop còn bận (get_session_info)
    rồi thử lại MỘT lần với ảnh nhỏ hơn, đừng dò code.
27. GỌI ÍT, NHANH: mỗi lần gọi công cụ tốn thời gian chủ dự án chờ. Trước khi gọi, viết sẵn cả chuỗi việc vào 1 script
    (đặt layer + mask + đổi blend + xuất ảnh kiểm tra trong CÙNG một execute_jsx). Không gọi get_active_document_info lặp lại
    (gọi 1 lần đầu, nhớ id). Không xuất cả ảnh 7776px để xem 1 góc: crop bằng duplicate+crop trong script. Không đọc lại file
    vừa ghi. Lệnh chạy lâu (gen Copilot) chạy nền, làm việc khác hoặc báo chủ dự án rồi chờ thông báo.
26. Gộp việc: thường 1 script xem trạng thái + 1-3 script dựng + 1-2 lần xuất ảnh kiểm tra. Quá ~10 lần gọi công cụ mà
    chưa có kết quả = đang đi sai, dừng lại báo chủ dự án hướng đang làm.
"""

ps = PS()
mcp = FastMCP("Photoshop", instructions=INSTRUCTIONS)


async def jsx(title: str, body: str, args: dict[str, Any] | None = None, history: bool = False,
              timeout: float = TIMEOUT) -> dict[str, Any]:
    """Chạy `body` (thân hàm JS nhận ARGS) trong Photoshop và trả về dict."""
    code = (
        LIB + "\n__mcpRun(" + json.dumps(title) + "," + json.dumps(args or {}) +
        ",function(ARGS){\n" + body + "\n}," + ("true" if history else "false") + ");"
    )
    try:
        raw = await ps.run(code, timeout)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e)}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {"success": True, "result": raw}
    if data.get("success") and isinstance(data.get("result"), dict):
        return {"success": True, **data["result"]}
    if data.get("line") is None:
        data.pop("line", None)
    return data


# ---------------------------------------------------------------- thông tin

@mcp.tool()
async def photoshop_get_session_info() -> dict:
    """Thông tin phiên Photoshop: phiên bản, các file đang mở, file đang chọn. Kích thước tính bằng pixel."""
    if os.environ.get("PS_UXP_ENABLED") == "1":
        from uxp_tools import call
        return await call("get_session_info", {})
    return await jsx("info", r"""
var docs = [];
for (var i = 0; i < app.documents.length; i++) docs.push(__docInfo(app.documents[i]));
var a = app.documents.length ? __docInfo(app.activeDocument) : null;
return { is_running: true, version: app.version, build: (function(){try{return app.build;}catch(e){return null;}})(),
  ruler_units: __enum($.global.__mcpRU, "Units."), has_active_document: !!a, documents: docs, active_document: a };
""")


@mcp.tool()
async def photoshop_get_active_document_info(include_layers: bool = True, max_depth: int = -1) -> dict:
    """Thông tin file đang mở: kích thước (px), độ phân giải, hệ màu, cây layer (id, tên, đường dẫn Group/Layer,
    loại, hiện/ẩn, opacity, blend, khung bao px, có mask không, chữ của layer text).

    Args:
        include_layers: có trả cây layer không.
        max_depth: độ sâu tối đa trong group (-1 = không giới hạn, 0 = chỉ cấp trên cùng).
    """
    if os.environ.get("PS_UXP_ENABLED") == "1":
        from uxp_tools import call
        return await call("get_active_document_info", {"include_layers": include_layers, "max_depth": max_depth})
    return await jsx("doc", r"""
var d = __doc(), o = __docInfo(d);
o.active_layer = __brief(d.activeLayer);
if (ARGS.include_layers) o.layers = __layerTree(d, ARGS.max_depth);
return o;
""", {"include_layers": include_layers, "max_depth": max_depth})


@mcp.tool()
async def photoshop_get_selection_info() -> dict:
    """Vùng chọn hiện tại (khung bao bằng pixel), nếu có."""
    if os.environ.get("PS_UXP_ENABLED") == "1":
        from uxp_tools import call
        return await call("get_selection_info", {})
    return await jsx("sel", r"""
var d = __doc();
try { var b = d.selection.bounds; return { has_selection: true, bounds: { left: __px(b[0]), top: __px(b[1]), right: __px(b[2]), bottom: __px(b[3]),
  width: __px(b[2]) - __px(b[0]), height: __px(b[3]) - __px(b[1]) } }; }
catch (e) { return { has_selection: false }; }
""")


# ---------------------------------------------------------------- file

@mcp.tool()
async def photoshop_create_document(width: int = 1000, height: int = 1000, name: str = "Untitled",
                                    mode: str = "rgb", resolution: float = 72,
                                    fill: Literal["white", "transparent", "background"] = "white") -> dict:
    """Tạo file mới. width/height bằng pixel; mode: rgb | cmyk | grayscale | lab."""
    return await jsx("new", r"""
var modes = { rgb: NewDocumentMode.RGB, cmyk: NewDocumentMode.CMYK, grayscale: NewDocumentMode.GRAYSCALE, lab: NewDocumentMode.LAB };
var fills = { white: DocumentFill.WHITE, transparent: DocumentFill.TRANSPARENT, background: DocumentFill.BACKGROUNDCOLOR };
var m = modes[String(ARGS.mode).toLowerCase()]; if (!m) throw new Error("Unknown mode: " + ARGS.mode);
var d = app.documents.add(UnitValue(ARGS.width, "px"), UnitValue(ARGS.height, "px"), ARGS.resolution, ARGS.name, m, fills[ARGS.fill]);
return { document: __docInfo(d) };
""", {"width": width, "height": height, "name": name, "mode": mode, "resolution": resolution, "fill": fill})


@mcp.tool()
async def photoshop_open_document(file_path: str) -> dict:
    """Mở file (PSD, PNG, JPG...). Nếu file đã mở thì chỉ chuyển sang file đó."""
    return await jsx("open", r"""
var f = new File(ARGS.file_path); if (!f.exists) throw new Error("File not found: " + ARGS.file_path);
for (var i = 0; i < app.documents.length; i++) { try { if (app.documents[i].fullName.fsName.toLowerCase() == f.fsName.toLowerCase()) { app.activeDocument = app.documents[i]; return { document: __docInfo(app.documents[i]), already_open: true }; } } catch (e) {} }
var d = app.open(f); return { document: __docInfo(d) };
""", {"file_path": file_path})


@mcp.tool()
async def photoshop_save_document(file_path: str = "", format: Literal["psd", "jpg", "png"] = "psd",
                                  quality: int = 10) -> dict:
    """Lưu file đang mở. file_path rỗng + psd = lưu đè (Ctrl+S).
    psd: Save As (file đang mở chuyển sang đường dẫn mới). jpg/png: lưu một bản sao, file đang mở giữ nguyên.
    quality: chất lượng JPG 0-12. Muốn xuất ảnh thu nhỏ / cắt viền trong suốt thì dùng photoshop_export_image."""
    return await jsx("save", r"""
var d = __doc(), fmt = String(ARGS.format).toLowerCase();
if (!ARGS.file_path) { if (fmt != "psd") throw new Error("file_path is required for " + fmt); d.save(); return { file_path: d.fullName.fsName }; }
var f = new File(ARGS.file_path), o;
if (fmt == "psd") { o = new PhotoshopSaveOptions(); o.layers = true; o.embedColorProfile = true; d.saveAs(f, o, false, Extension.LOWERCASE); }
else if (fmt == "jpg" || fmt == "jpeg") { o = new JPEGSaveOptions(); o.quality = ARGS.quality; o.embedColorProfile = true; d.saveAs(f, o, true, Extension.LOWERCASE); }
else if (fmt == "png") { o = new PNGSaveOptions(); d.saveAs(f, o, true, Extension.LOWERCASE); }
else throw new Error("Unknown format: " + fmt);
return { file_path: f.fsName, format: fmt };
""", {"file_path": file_path, "format": format, "quality": max(0, min(12, quality))})


@mcp.tool()
async def photoshop_export_image(file_path: str, format: Literal["png", "jpg"] = "png", quality: int = 10,
                                 max_size: int = 0, trim_transparent: bool = False,
                                 region: list[int] | None = None) -> dict:
    """Xuất ảnh ghép các layer đang hiện ra PNG/JPG, file PSD không bị đổi.
    max_size: thu cạnh dài nhất về số pixel này (0 = giữ nguyên). Xem trước file lớn: dùng 1600-2000.
    region: [trái, trên, phải, dưới] px trên file gốc = chỉ xuất vùng đó (xem chi tiết 100% mà không xuất cả ảnh).
    trim_transparent: cắt viền trong suốt (PNG)."""
    if region is not None and len(region) != 4:
        return {"success": False, "error": "region phải là [trái, trên, phải, dưới]"}
    return await jsx("export", r"""
var src = __doc(), fmt = String(ARGS.format).toLowerCase();
// Nhân bản dạng đã gộp sẵn (mergeLayersOnly=true): nhanh hơn nhiều so với nhân bản đủ layer rồi mới gộp.
var d = src.duplicate("mcp_export_tmp", true);
app.activeDocument = d;  // PS 28: bản sao không tự lên trước -> crop báo "not frontmost"
try {
  if (ARGS.region) {
    var r = ARGS.region, W = __px(d.width), H = __px(d.height);
    r = [Math.max(0, r[0]), Math.max(0, r[1]), Math.min(W, r[2]), Math.min(H, r[3])];
    d.crop([UnitValue(r[0], "px"), UnitValue(r[1], "px"), UnitValue(r[2], "px"), UnitValue(r[3], "px")]);
  }
  var w = __px(d.width), h = __px(d.height), m = ARGS.max_size;
  if (m > 0 && Math.max(w, h) > m) { var s = m / Math.max(w, h); d.resizeImage(UnitValue(Math.round(w * s), "px"), UnitValue(Math.round(h * s), "px"), null, ResampleMethod.BICUBIC); }
  if (d.mode != DocumentMode.RGB && d.mode != DocumentMode.GRAYSCALE) d.changeMode(ChangeMode.RGB);
  if (d.bitsPerChannel != BitsPerChannelType.EIGHT) d.bitsPerChannel = BitsPerChannelType.EIGHT;
  if (ARGS.trim && fmt == "png") d.trim(TrimType.TRANSPARENT);
  var f = new File(ARGS.file_path), o;
  if (fmt == "png") { o = new PNGSaveOptions(); }
  else { d.flatten(); o = new JPEGSaveOptions(); o.quality = ARGS.quality; o.embedColorProfile = true; }
  d.saveAs(f, o, true, Extension.LOWERCASE);
  var out = { file_path: f.fsName, format: fmt, width: __px(d.width), height: __px(d.height) };
} finally { d.close(SaveOptions.DONOTSAVECHANGES); app.activeDocument = src; }
return out;
""", {"file_path": file_path, "format": format, "quality": max(0, min(12, quality)), "max_size": max_size,
      "trim": trim_transparent, "region": region}, timeout=max(TIMEOUT, 300))


@mcp.tool()
async def photoshop_activate_document(name: str) -> dict:
    """Chuyển sang file đang mở có tên `name` (vd "Poster.psd")."""
    return await jsx("activate", r"""
for (var i = 0; i < app.documents.length; i++) if (app.documents[i].name == ARGS.name) { app.activeDocument = app.documents[i]; return { document: __docInfo(app.documents[i]) }; }
throw new Error("Document not open: " + ARGS.name);
""", {"name": name})


@mcp.tool()
async def photoshop_close_document(save: bool = False) -> dict:
    """Đóng file đang mở. save=False bỏ thay đổi chưa lưu; save=True lưu đè trước khi đóng."""
    return await jsx("close", r"""
var d = __doc(), n = d.name; d.close(ARGS.save ? SaveOptions.SAVECHANGES : SaveOptions.DONOTSAVECHANGES);
return { closed: n };
""", {"save": save})


# ---------------------------------------------------------------- tạo layer

@mcp.tool()
async def photoshop_create_text_layer(text: str, x: int = 100, y: int = 100, size: int = 24,
                                      color_r: int = 0, color_g: int = 0, color_b: int = 0,
                                      font: str = "", name: str = "") -> dict:
    """Tạo layer chữ. x, y: điểm đặt chữ (đường chân chữ dòng đầu), pixel. size: cỡ chữ bằng pixel.
    font: tên PostScript (vd "Arial-BoldMT"); rỗng = font hiện tại."""
    return await jsx("Thêm chữ", r"""
var d = __doc(), l = d.artLayers.add(); l.kind = LayerKind.TEXT;
var t = l.textItem; t.contents = ARGS.text; t.size = UnitValue(ARGS.size * 72 / d.resolution, "pt");
t.color = __rgb(ARGS.r, ARGS.g, ARGS.b); if (ARGS.font) t.font = ARGS.font;
t.position = [UnitValue(ARGS.x, "px"), UnitValue(ARGS.y, "px")];
if (ARGS.name) l.name = ARGS.name;
return { layer: __brief(l) };
""", {"text": text, "x": x, "y": y, "size": size, "r": color_r, "g": color_g, "b": color_b, "font": font,
      "name": name}, history=True)


@mcp.tool()
async def photoshop_create_solid_color_layer(color_r: int = 255, color_g: int = 0, color_b: int = 0,
                                             name: str = "Color Fill") -> dict:
    """Tạo layer tô màu (Solid Color fill layer) phủ toàn file."""
    return await jsx("Thêm layer màu", r"""
var d = __doc();
var desc = new ActionDescriptor(), ref = new ActionReference(); ref.putClass(sTID("contentLayer")); desc.putReference(cTID("null"), ref);
var ld = new ActionDescriptor(); ld.putString(cTID("Nm  "), ARGS.name);
var sc = new ActionDescriptor(), c = new ActionDescriptor();
c.putDouble(cTID("Rd  "), ARGS.r); c.putDouble(cTID("Grn "), ARGS.g); c.putDouble(cTID("Bl  "), ARGS.b);
sc.putObject(cTID("Clr "), cTID("RGBC"), c); ld.putObject(cTID("Type"), sTID("solidColorLayer"), sc);
desc.putObject(cTID("Usng"), sTID("contentLayer"), ld); executeAction(cTID("Mk  "), desc, DialogModes.NO);
return { layer: __brief(d.activeLayer) };
""", {"r": color_r, "g": color_g, "b": color_b, "name": name}, history=True)


@mcp.tool()
async def photoshop_place_image(file_path: str, name: str = "", x: Optional[int] = None, y: Optional[int] = None,
                                width: Optional[int] = None, height: Optional[int] = None) -> dict:
    """Chèn ảnh từ file thành Smart Object nhúng. x, y: góc trên-trái (px). width/height: kích thước mới (px);
    chỉ cho một trong hai thì giữ tỉ lệ. Không cho gì thì giữ kích thước/vị trí Photoshop tự đặt."""
    return await jsx("Chèn ảnh", r"""
var d = __doc(), f = new File(ARGS.file_path); if (!f.exists) throw new Error("File not found: " + ARGS.file_path);
var desc = new ActionDescriptor(); desc.putPath(cTID("null"), f);
desc.putEnumerated(cTID("FTcs"), cTID("QCSt"), cTID("Qcsa"));
executeAction(cTID("Plc "), desc, DialogModes.NO);
var l = d.activeLayer; if (ARGS.name) l.name = ARGS.name;
__transform(l, ARGS);
return { layer: __brief(l) };
""", {"file_path": file_path, "name": name, "x": x, "y": y, "width": width, "height": height}, history=True)


@mcp.tool()
async def photoshop_create_group(name: str = "Group", layers: list[str] | None = None) -> dict:
    """Tạo group mới (đặt trên layer đang chọn); `layers` (id/tên/đường dẫn) sẽ được chuyển vào group."""
    return await jsx("Tạo group", r"""
var d = __doc(), list = [], i;
for (i = 0; i < ARGS.layers.length; i++) list.push(__find(d, ARGS.layers[i]));
var g = d.layerSets.add(); g.name = ARGS.name;
if (list.length) { g.move(list[0], ElementPlacement.PLACEBEFORE); for (i = list.length - 1; i >= 0; i--) list[i].move(g, ElementPlacement.INSIDE); }
return { group: __brief(g) };
""", {"name": name, "layers": layers or []}, history=True)


# ---------------------------------------------------------------- sửa layer

@mcp.tool()
async def photoshop_update_layer(layer: str = "", name: Optional[str] = None, visible: Optional[bool] = None,
                                 opacity: Optional[float] = None, fill_opacity: Optional[float] = None,
                                 blend_mode: Optional[str] = None, clipped: Optional[bool] = None,
                                 text: Optional[str] = None, select: bool = False) -> dict:
    """Sửa thuộc tính layer. layer: id, tên, hoặc đường dẫn "Group/Layer"; rỗng = layer đang chọn.
    blend_mode: normal, multiply, screen, overlay, softlight, hardlight, colordodge, lineardodge, darken, lighten,
    color, luminosity, hue, saturation, difference... clipped: bật/tắt clipping mask.
    text: đổi nội dung layer chữ. select=True: chọn layer này làm layer đang chọn."""
    return await jsx("Sửa layer", r"""
var d = __doc(), l = __find(d, ARGS.layer);
if (__has(ARGS.name)) l.name = ARGS.name;
if (ARGS.visible !== null) l.visible = ARGS.visible;
if (ARGS.opacity !== null) l.opacity = ARGS.opacity;
if (ARGS.fill_opacity !== null) l.fillOpacity = ARGS.fill_opacity;
if (__has(ARGS.blend_mode)) { var bm = BlendMode[String(ARGS.blend_mode).toUpperCase().replace(/[ _-]/g, "")]; if (!bm) throw new Error("Unknown blend mode: " + ARGS.blend_mode); l.blendMode = bm; }
if (ARGS.clipped !== null) l.grouped = ARGS.clipped;
if (ARGS.text !== null) { if (l.kind != LayerKind.TEXT) throw new Error("Not a text layer"); l.textItem.contents = ARGS.text; }
if (ARGS.select) d.activeLayer = l;
return { layer: __layerInfo(l, l.name, 0, 0) };
""", {"layer": layer, "name": name, "visible": visible, "opacity": opacity, "fill_opacity": fill_opacity,
      "blend_mode": blend_mode, "clipped": clipped, "text": text, "select": select}, history=True)


@mcp.tool()
async def photoshop_transform_layer(layer: str = "", x: Optional[float] = None, y: Optional[float] = None,
                                    dx: float = 0, dy: float = 0, width: Optional[float] = None,
                                    height: Optional[float] = None, scale_percent: Optional[float] = None,
                                    rotate: float = 0) -> dict:
    """Di chuyển / co giãn / xoay layer (hoặc group). Đơn vị pixel.
    x, y: đưa góc trên-trái khung bao tới toạ độ này. dx, dy: dịch thêm.
    width/height: kích thước mới (chỉ một giá trị = giữ tỉ lệ); scale_percent: co giãn theo %. rotate: độ, quanh tâm."""
    return await jsx("Biến đổi layer", r"""
var d = __doc(), l = __find(d, ARGS.layer);
__transform(l, ARGS);
return { layer: __brief(l) };
""", {"layer": layer, "x": x, "y": y, "dx": dx, "dy": dy, "width": width, "height": height,
      "scale": scale_percent, "rotate": rotate}, history=True)


@mcp.tool()
async def photoshop_distort_layer(corners: list[list[float]], layer: str = "") -> dict:
    """Bóp 4 góc layer (Distort / phối cảnh) — dùng để đặt vật lên mặt phẳng nghiêng như mặt đất, tường.
    corners: 4 điểm [x, y] pixel trên file, theo thứ tự góc trên-trái, trên-phải, dưới-phải, dưới-trái
    của khung bao hiện tại của layer. Smart Object vẫn là Smart Object (chỉnh lại được, không mất nét).
    Gọi lại nhiều lần được; mỗi lần tính theo khung bao lúc đó."""
    if len(corners) != 4 or any(len(c) != 2 for c in corners):
        return {"success": False, "error": "corners phải gồm 4 điểm [x, y]: trên-trái, trên-phải, dưới-phải, dưới-trái"}
    return await jsx("Bóp góc layer", r"""
var d = __doc(), l = __find(d, ARGS.layer);
if (l.typename == "LayerSet") throw new Error("Không bóp góc được group; chọn layer hoặc chuyển group thành Smart Object.");
__distort(l, ARGS.corners);
return { layer: __brief(l) };
""", {"layer": layer, "corners": corners}, history=True)


@mcp.tool()
async def photoshop_composite_object(
        layer: str, corners: Optional[list[list[float]]] = None, x: Optional[float] = None, y: Optional[float] = None,
        width: Optional[float] = None, rotate: float = 0, light_angle: float = 90, contact_opacity: float = 80,
        ambient_opacity: float = 15, cast_length: float = 0, cast_opacity: float = 40, tone_strength: float = 1.0,
        tint_opacity: float = 18, noise: float = 4, blur: float = 0, group_name: str = "",
        preview: bool = True) -> Any:
    """GHÉP VẬT VÀO ẢNH TRONG MỘT LẦN GỌI (dùng cái này thay vì tự dựng từng layer).
    Nhân bản `layer` (ẩn bản gốc, không xoá), gom vào group "Ghép <tên>" gồm:
      Hạt nhiễu / Ám màu môi trường / Hạ sáng (clip vào vật) > Vật (Smart Object) > Bóng tiếp xúc > Bóng tán xạ > [Bóng đổ].
    Màu nền quanh vật được lấy mẫu tự động để làm bóng và cân sáng.
    Đặt vị trí: x, y (góc trên-trái), width (giữ tỉ lệ), rotate (độ) làm trước; rồi corners (4 điểm [x,y]
      trên-trái, trên-phải, dưới-phải, dưới-trái) để bóp phối cảnh. Vật nằm bệt trên đất: nén dẹt chiều dọc bằng corners.
    light_angle: hướng ánh sáng TỚI, độ như Global Light (90 = từ trên xuống, 0 = từ phải, 180 = từ trái).
    cast_length: độ dài bóng đổ px (0 = không có; vật mỏng nằm bệt để 0). tone_strength: 0-1 mức hạ sáng vật cho khớp nền.
    tint_opacity: % ám màu nền lên vật. noise: % hạt nhiễu (0 = tắt). blur: px làm mềm vật cho khớp độ nét (0 = tắt).
    Làm lại: gọi lại với cùng layer gốc; group cũ cùng tên bị ẩn, tạo group mới.
    preview: trả kèm ảnh vùng quanh vật (đã ghép) để tự xem ngay, không cần xuất ảnh riêng."""
    res = await jsx("Ghép vật", r"""
var d = __doc(), src = __find(d, ARGS.layer);
if (src.typename == "LayerSet") throw new Error("Chọn layer vật (Smart Object), không chọn group.");
var gname = ARGS.group_name || ("Ghép " + src.name);
var all = __all(d, [], ""), hidden_old = [];
for (var i = 0; i < all.length; i++) if (all[i].l.typename == "LayerSet" && all[i].l.name == gname && all[i].l.visible) { all[i].l.visible = false; hidden_old.push(all[i].l.id); }
var obj = src.duplicate(); obj.name = "Vật"; obj.visible = true; src.visible = false;
var g = d.layerSets.add(); g.name = gname; g.move(src, ElementPlacement.PLACEBEFORE); obj.move(g, ElementPlacement.INSIDE);
__transform(obj, { x: ARGS.x, y: ARGS.y, width: ARGS.width, rotate: ARGS.rotate });
if (ARGS.corners) __distort(obj, ARGS.corners);
var b = obj.bounds, L = __px(b[0]), T = __px(b[1]), R = __px(b[2]), B = __px(b[3]), w = R - L, h = B - T;
if (w <= 0 || h <= 0) throw new Error("Vật rỗng sau khi biến đổi");
var size = Math.sqrt(w * h), W = __px(d.width), H = __px(d.height);
// lấy mẫu màu nền quanh vật (ẩn vật khi lấy)
var ring = Math.max(8, size * 0.6);
obj.visible = false;
d.selection.select([[Math.max(0, L - ring), Math.max(0, T - ring)], [Math.min(W, R + ring), Math.max(0, T - ring)],
                    [Math.min(W, R + ring), Math.min(H, B + ring)], [Math.max(0, L - ring), Math.min(H, B + ring)]]);
var ground = __selMean(d); obj.visible = true;
__selectAlpha(obj); var objc = __selMean(d); d.selection.deselect();
var gY = __lum(ground), oY = __lum(objc);
var a = ARGS.light_angle * Math.PI / 180, sdx = -Math.cos(a), sdy = Math.sin(a);
var sh = __rgb(Math.round(ground[0] * 0.2), Math.round(ground[1] * 0.2), Math.round(ground[2] * 0.2));
function under(name) { var l = d.artLayers.add(); l.name = name; l.move(obj, ElementPlacement.PLACEAFTER); return l; }
// layer phủ chồng dần lên trên (Hạ sáng > Ám màu > Hạt nhiễu); chèn xen vào giữa làm PS bỏ clip layer trên -> luôn đặt trên cùng chồng clip
var overTop = obj, overs = [];
function over(name) { d.activeLayer = overTop; var l = d.artLayers.add(); l.name = name; l.move(overTop, ElementPlacement.PLACEBEFORE); l.grouped = true; overTop = l; overs.push(l); return l; }
function fillFrom(l, spread, color) { __selectAlpha(obj); if (spread > 0) d.selection.expand(UnitValue(spread, "px")); d.activeLayer = l; d.selection.fill(color); d.selection.deselect(); }
var made = {};
// bóng: tạo từ xa tới gần, mỗi layer mới nằm ngay dưới vật -> Bóng tiếp xúc sát vật nhất
if (ARGS.cast_length > 0) {
  var cst = under("Bóng đổ"); fillFrom(cst, 0, sh);
  cst.translate(sdx * ARGS.cast_length, sdy * ARGS.cast_length);
  cst.applyGaussianBlur(Math.max(1, ARGS.cast_length * 0.25)); cst.blendMode = BlendMode.MULTIPLY; cst.opacity = ARGS.cast_opacity; made.cast = cst.id;
}
if (ARGS.ambient_opacity > 0) {
  var amb = under("Bóng tán xạ"); fillFrom(amb, Math.max(1, size * 0.06), sh);
  amb.translate(sdx * size * 0.03, sdy * size * 0.03);
  amb.applyGaussianBlur(Math.max(1.5, size * 0.12)); amb.blendMode = BlendMode.MULTIPLY; amb.opacity = ARGS.ambient_opacity; made.ambient = amb.id;
}
if (ARGS.contact_opacity > 0) {
  var con = under("Bóng tiếp xúc"); fillFrom(con, 0, sh);
  var co = Math.max(1, size * 0.015);
  con.translate(sdx * co, sdy * co);
  con.applyGaussianBlur(Math.max(0.6, size * 0.012)); con.blendMode = BlendMode.MULTIPLY; con.opacity = ARGS.contact_opacity; made.contact = con.id;
}
// cân sáng + màu (clip vào vật)
var gc = __rgb(Math.round(ground[0]), Math.round(ground[1]), Math.round(ground[2]));
var darken = oY > gY ? Math.min(0.7, (oY - gY) / Math.max(oY, 1)) * ARGS.tone_strength : 0;
if (darken > 0.01) { var tn = over("Hạ sáng"); fillFrom(tn, 0, gc); tn.blendMode = BlendMode.MULTIPLY; tn.opacity = Math.round(darken * 100); made.tone = tn.id; }
if (ARGS.tint_opacity > 0) { var tt = over("Ám màu môi trường"); fillFrom(tt, 0, gc); tt.blendMode = BlendMode.COLORBLEND; tt.opacity = ARGS.tint_opacity; made.tint = tt.id; }
if (ARGS.noise > 0) {
  var nz = over("Hạt nhiễu"); fillFrom(nz, 2, __rgb(128, 128, 128));
  nz.applyAddNoise(ARGS.noise, NoiseDistribution.GAUSSIAN, true); nz.blendMode = BlendMode.OVERLAY; made.noise = nz.id;
}
if (ARGS.blur > 0) { d.activeLayer = obj; var gb = new ActionDescriptor(); gb.putUnitDouble(cTID("Rds "), cTID("#Pxl"), ARGS.blur); executeAction(cTID("GsnB"), gb, DialogModes.NO); }
for (var oi = 0; oi < overs.length; oi++) if (!overs[oi].grouped) overs[oi].grouped = true;
var unclipped = []; for (oi = 0; oi < overs.length; oi++) if (!overs[oi].grouped) unclipped.push(overs[oi].name);
if (unclipped.length) throw new Error("Không clip được: " + unclipped.join(", "));
d.activeLayer = obj;
return { group: __brief(g), object: __brief(obj), source_hidden: src.id, older_groups_hidden: hidden_old, layers: made,
         ground_rgb: [Math.round(ground[0]), Math.round(ground[1]), Math.round(ground[2])], object_lum: Math.round(oY),
         ground_lum: Math.round(gY), darken_percent: Math.round(darken * 100),
         bounds: { left: L, top: T, right: R, bottom: B } };
""", {"layer": layer, "corners": corners, "x": x, "y": y, "width": width, "rotate": rotate,
      "light_angle": light_angle, "contact_opacity": contact_opacity, "ambient_opacity": ambient_opacity,
      "cast_length": cast_length, "cast_opacity": cast_opacity, "tone_strength": tone_strength,
      "tint_opacity": tint_opacity, "noise": noise, "blur": blur, "group_name": group_name},
        history=True, timeout=max(TIMEOUT, 300))
    if not preview or not res.get("success"):
        return res
    bb = res["bounds"]
    w, h = bb["right"] - bb["left"], bb["bottom"] - bb["top"]
    m = max(150, 1.5 * max(w, h))
    region = [int(bb["left"] - m), int(bb["top"] - m), int(bb["right"] + m), int(bb["bottom"] + m)]
    path = str(Path(os.environ.get("TEMP", ".")) / f"ps_mcp_composite_{int(time.time())}.png")
    ex = await photoshop_export_image(path, "png", max_size=900, region=region)
    if not ex.get("success"):
        res["preview_error"] = ex.get("error")
        return res
    res["preview_file"] = path
    res["preview_note"] = "Ảnh kèm theo: vùng quanh vật (tối đa 900px). Xem toàn cảnh: photoshop_export_image max_size=1600."
    return [res, Image(path=path)]


@mcp.tool()
async def photoshop_subject_masks(
        boxes: list[dict], group_name: str = "Người thật", opacity: float = 50,
        expand: float = 0, seam: float = 3, preview: bool = True) -> Any:
    """TẠO MASK NGƯỜI/VẬT HÀNG LOẠT TRONG MỘT LẦN GỌI (Select Subject theo từng khung).
    boxes: [{"name": "Tượng 1", "desc": "Lính vác gậy" (tuỳ chọn), "rect": [trái, trên, phải, dưới] (px),
             "z": số (tuỳ chọn, LỚN = ĐỨNG TRƯỚC), "color": [r,g,b] (tuỳ chọn),
             "group": "group có sẵn để đặt layer vào, không tạo group con" (tuỳ chọn)}].
    Cấu trúc mặc định: group `group_name` (dùng lại nếu đã có ở cấp trên cùng) > group "<name> – <desc>"
      > layer "Mask <name> (sửa mask ở đây)" (Solid Color, mờ `opacity`%, mỗi chủ thể 1 màu khác nhau).
    Mỗi khung: cắt riêng vùng đó (Select Subject chạy ở độ phân giải cao) -> mask đúng hình chủ thể, ngoài khung = đen.
    Che khuất: chủ thể có z nhỏ hơn (đứng sau) bị trừ phần mà chủ thể z lớn hơn che, nhưng giữ lại `seam` px
      chồng dưới mép chủ thể trước (mềm 1px) để không hở khe khi Generative Fill. Không cho z = không trừ.
      Nếu >60% chủ thể sau bị "che" thì Select Subject đã lấy dính cả hai: KHÔNG trừ, trả về trong
      `stuck_together` -> báo người dùng sửa tay mask chủ thể đứng trước (công cụ không tự tách được).
    Đồ cầm trên tay (gậy...) là một phần chủ thể; bóng dưới đất, người đi đường thì không -> nói người dùng sửa nếu dính.
    expand: nới mask thêm px (0 = giữ sát mép, nên để 0; nới vùng chọn lúc Generative Fill).
    Chủ thể chồng nhau trong cùng khung có thể bị lấy chung -> xem ảnh trả về, báo người dùng sửa tay trên mask.
    Chi tiết cần giữ sau Generative Fill (vd máu) nên tách thành layer riêng trong group của chủ thể đó.
    preview: trả kèm ảnh vùng chứa mọi khung (tối đa 1600px)."""
    res = await jsx("Tạo mask chủ thể", r"""
var d = __doc(), made = [], errs = [];
var palette = [[255,140,0],[0,170,255],[255,0,200],[255,0,0],[255,230,0],[0,255,120],[160,80,255],[0,230,230],[140,255,0],[255,110,150],[60,90,255],[200,150,90]];
var holder = null;
for (var i = 0; i < d.layerSets.length; i++) if (d.layerSets[i].name == ARGS.group_name) { holder = d.layerSets[i]; break; }
function lowFirst(s) { return s.charAt(0).toLowerCase() + s.substring(1); }
function maskToSel(l) { var ds = new ActionDescriptor(), r = new ActionReference(), t = new ActionReference();
  r.putProperty(cTID("Chnl"), cTID("fsel")); ds.putReference(cTID("null"), r);
  t.putEnumerated(cTID("Chnl"), cTID("Chnl"), cTID("Msk ")); t.putIdentifier(cTID("Lyr "), l.id); ds.putReference(cTID("T   "), t);
  executeAction(cTID("setd"), ds, DialogModes.NO); }
function solid(name, c3) {
  var ds = new ActionDescriptor(), ref = new ActionReference(); ref.putClass(sTID("contentLayer")); ds.putReference(cTID("null"), ref);
  var ly = new ActionDescriptor(), sc = new ActionDescriptor(), c = new ActionDescriptor();
  c.putDouble(cTID("Rd  "), c3[0]); c.putDouble(cTID("Grn "), c3[1]); c.putDouble(cTID("Bl  "), c3[2]);
  sc.putObject(cTID("Clr "), cTID("RGBC"), c); ly.putObject(cTID("Type"), sTID("solidColorLayer"), sc); ly.putString(cTID("Nm  "), name);
  ds.putObject(cTID("Usng"), sTID("contentLayer"), ly); executeAction(cTID("Mk  "), ds, DialogModes.NO); return d.activeLayer;
}
function selMask(l) { d.activeLayer = l; var ds = new ActionDescriptor(), ref = new ActionReference();
  ref.putEnumerated(cTID("Chnl"), cTID("Chnl"), cTID("Msk ")); ds.putReference(cTID("null"), ref); ds.putBoolean(cTID("MkVs"), false);
  executeAction(cTID("slct"), ds, DialogModes.NO); }
function applyFrom(src) { var ds = new ActionDescriptor(), w = new ActionDescriptor(), ref = new ActionReference();
  ref.putEnumerated(cTID("Chnl"), cTID("Chnl"), cTID("Rd  ")); ref.putIdentifier(cTID("Lyr "), src.id); w.putReference(cTID("T   "), ref);
  w.putEnumerated(cTID("Clcl"), cTID("Clcn"), cTID("Nrml")); w.putBoolean(cTID("PrsT"), false);
  ds.putObject(cTID("With"), cTID("Clcl"), w); executeAction(cTID("AppI"), ds, DialogModes.NO); }
// ẩn các layer mask đã có của công cụ khi lấy mẫu (để lớp phủ màu không làm sai Select Subject)
var all = __all(d, [], ""), hid = [];
for (var i = 0; i < all.length; i++) { var l = all[i].l; if (l.typename == "ArtLayer" && l.visible && /^Mask /.test(l.name)) { l.visible = false; hid.push(l); } }
for (var i = 0; i < ARGS.boxes.length; i++) {
  var bx = ARGS.boxes[i], r = bx.rect, L = Math.max(0, r[0]), T = Math.max(0, r[1]), R = Math.min(__px(d.width), r[2]), B = Math.min(__px(d.height), r[3]);
  var rect = [[L, T], [R, T], [R, B], [L, B]];
  try {
    app.activeDocument = d;
    var c = d.duplicate("tmp_mask_" + i, true); app.activeDocument = c;   // đừng sửa d khi c đang mở: d sẽ nhảy lên trước
    c.crop([UnitValue(L, "px"), UnitValue(T, "px"), UnitValue(R, "px"), UnitValue(B, "px")]);
    var ds = new ActionDescriptor(); ds.putBoolean(sTID("sampleAllLayers"), false); executeAction(sTID("autoCutout"), ds, DialogModes.NO);
    if (ARGS.expand > 0) c.selection.expand(UnitValue(ARGS.expand, "px"));
    c.artLayers.add(); c.selection.invert(); c.selection.fill(__rgb(0, 0, 0)); c.selection.invert(); c.selection.fill(__rgb(255, 255, 255));
    c.selection.selectAll(); c.selection.copy(); c.close(SaveOptions.DONOTSAVECHANGES); app.activeDocument = d;
    var g, nm = bx.name || ("Chủ thể " + (i + 1));
    if (bx.group) g = __find(d, bx.group);
    else {
      if (!holder) { holder = d.layerSets.add(); holder.name = ARGS.group_name; }
      g = holder.layerSets.add(); g.name = nm + (bx.desc ? " – " + bx.desc : "");
    }
    d.selection.deselect(); d.activeLayer = g;
    var s = solid("Mask " + lowFirst(nm) + " (sửa mask ở đây)", bx.color || palette[i % palette.length]);
    if (s.parent != g) s.move(g, ElementPlacement.INSIDE);
    s.opacity = ARGS.opacity;
    d.activeLayer = s; d.selection.select(rect); d.paste(true); var tmp = d.activeLayer; d.selection.deselect();
    selMask(s); applyFrom(tmp);
    d.selection.select(rect); d.selection.invert(); d.selection.fill(__rgb(0, 0, 0)); d.selection.deselect(); tmp.remove();
    made.push({ name: s.name, subject: nm, id: s.id, group: g.name, rect: [L, T, R, B], z: (typeof bx.z == "number") ? bx.z : null, _l: s });
  } catch (e) {
    errs.push({ box: i, name: bx.name, error: String(e.message || e) });
    try { if (app.activeDocument != d) app.activeDocument.close(SaveOptions.DONOTSAVECHANGES); } catch (e2) {}
    app.activeDocument = d;
  }
}
// che khuất: trừ chủ thể đứng trước (z lớn) khỏi mask chủ thể đứng sau, chừa `seam` px chồng mép
var occl = [], stuck = [];
function selArea() {   // diện tích vùng chọn hiện tại (px, tính cả độ mờ)
  var ch = d.channels.add(); d.selection.store(ch, SelectionType.REPLACE);
  var h = ch.histogram, s = 0; for (var k = 1; k < 256; k++) s += h[k] * k / 255;
  ch.remove(); d.activeChannels = d.componentChannels; return s;
}
for (var a = 0; a < made.length; a++) for (var b = 0; b < made.length; b++) {
  var A = made[a], B = made[b];
  if (A.z === null || B.z === null || !(B.z > A.z)) continue;
  if (A.rect[2] <= B.rect[0] || B.rect[2] <= A.rect[0] || A.rect[3] <= B.rect[1] || B.rect[3] <= A.rect[1]) continue;
  try {
    // đo trước: nếu chủ thể trước "nuốt" gần hết chủ thể sau = Select Subject lấy dính cả hai -> không trừ, báo sửa tay
    maskToSel(A._l); var aArea = selArea();
    var tB = d.channels.add(); maskToSel(B._l);
    if (ARGS.seam > 0) d.selection.contract(UnitValue(ARGS.seam, "px"));
    d.selection.feather(UnitValue(1, "px")); d.selection.store(tB, SelectionType.REPLACE);
    maskToSel(A._l); d.selection.load(tB, SelectionType.INTERSECT); d.activeChannels = d.componentChannels;
    var ov = selArea(), ratio = aArea > 0 ? ov / aArea : 1;
    if (ratio > ARGS.max_cover) {
      stuck.push(B.subject + " lấy dính cả " + A.subject + " (" + Math.round(ratio * 100) + "%) -> sửa tay: xoá phần " + A.subject + " khỏi mask " + B.subject);
    } else {
      d.selection.load(tB, SelectionType.REPLACE); d.activeChannels = d.componentChannels;
      selMask(A._l); d.selection.fill(__rgb(0, 0, 0));
      occl.push(A.subject + " bị " + B.subject + " che " + Math.round(ratio * 100) + "%");
    }
    d.selection.deselect(); tB.remove(); d.activeChannels = d.componentChannels;
  } catch (e) { try { d.selection.deselect(); d.activeChannels = d.componentChannels; } catch (e2) {}
    errs.push({ name: A.name, error: "trừ che khuất: " + String(e.message || e) }); }
}
for (var i = 0; i < made.length; i++) delete made[i]._l;
for (var i = 0; i < hid.length; i++) hid[i].visible = true;
var u = [1e9, 1e9, 0, 0];
for (var i = 0; i < made.length; i++) { var q = made[i].rect; u = [Math.min(u[0], q[0]), Math.min(u[1], q[1]), Math.max(u[2], q[2]), Math.max(u[3], q[3])]; }
return { masks: made, errors: errs, occlusion: occl, stuck_together: stuck, union: made.length ? u : null,
         note: "Sửa: tô đen/trắng trên ô mask của từng layer. Nạp vùng chọn: Ctrl+bấm ô mask. Tắt layer phủ màu trước khi Generative Fill." };
""", {"boxes": boxes, "group_name": group_name, "opacity": opacity, "expand": expand, "seam": seam, "max_cover": 0.6},
        timeout=max(TIMEOUT, 600))
    if not preview or not res.get("success") or not res.get("union"):
        return res
    u = res["union"]
    m = 60
    path = str(Path(os.environ.get("TEMP", ".")) / f"ps_mcp_masks_{int(time.time())}.jpg")
    ex = await photoshop_export_image(path, "jpg", max_size=1600, region=[u[0] - m, u[1] - m, u[2] + m, u[3] + m])
    if not ex.get("success"):
        res["preview_error"] = ex.get("error")
        return res
    res["preview_file"] = path
    return [res, Image(path=path)]


@mcp.tool()
async def photoshop_duplicate_layer(layer: str = "", new_name: str = "", to_document: str = "") -> dict:
    """Nhân bản layer/group (bản sao nằm ngay trên bản gốc, giữ mask).
    to_document: tên file đang mở khác để chép sang (rỗng = cùng file)."""
    return await jsx("Nhân bản layer", r"""
var d = __doc(), l = __find(d, ARGS.layer), n;
if (ARGS.to_document) {
  var t = null; for (var i = 0; i < app.documents.length; i++) if (app.documents[i].name == ARGS.to_document) t = app.documents[i];
  if (!t) throw new Error("Document not open: " + ARGS.to_document);
  n = l.duplicate(t, ElementPlacement.PLACEATBEGINNING); app.activeDocument = t;
} else n = l.duplicate();
if (ARGS.new_name) n.name = ARGS.new_name;
return { layer: __brief(n) };
""", {"layer": layer, "new_name": new_name, "to_document": to_document}, history=True)


@mcp.tool()
async def photoshop_delete_layer(layer: str) -> dict:
    """Xoá layer/group (id, tên hoặc đường dẫn). Có thể hoàn tác bằng photoshop_undo."""
    return await jsx("Xoá layer", r"""
var d = __doc(), l = __find(d, ARGS.layer), info = __brief(l); l.remove(); return { deleted: info };
""", {"layer": layer}, history=True)


@mcp.tool()
async def photoshop_arrange_layer(layer: str, placement: Literal["above", "below", "inside", "top", "bottom"],
                                  target: str = "") -> dict:
    """Đổi thứ tự layer. above/below: đặt trên/dưới `target`; inside: cho vào group `target`;
    top/bottom: lên trên cùng / xuống dưới cùng của file."""
    return await jsx("Sắp xếp layer", r"""
var d = __doc(), l = __find(d, ARGS.layer), p = ARGS.placement, t;
if (p == "top") l.move(d.layers[0], ElementPlacement.PLACEBEFORE);
else if (p == "bottom") { var last = d.layers[d.layers.length - 1]; l.move(last, last.isBackgroundLayer ? ElementPlacement.PLACEBEFORE : ElementPlacement.PLACEAFTER); }
else {
  if (!__has(ARGS.target)) throw new Error("target is required for " + p);
  t = __find(d, ARGS.target);
  if (p == "inside") { if (t.typename != "LayerSet") throw new Error("target is not a group"); l.move(t, ElementPlacement.INSIDE); }
  else l.move(t, p == "above" ? ElementPlacement.PLACEBEFORE : ElementPlacement.PLACEAFTER);
}
return { layer: __brief(l) };
""", {"layer": layer, "placement": placement, "target": target}, history=True)


# ---------------------------------------------------------------- vùng chọn & mask

@mcp.tool()
async def photoshop_select(mode: Literal["rect", "ellipse", "all", "none", "invert", "layer_pixels"],
                           x: float = 0, y: float = 0, width: float = 0, height: float = 0,
                           layer: str = "", feather: float = 0,
                           combine: Literal["replace", "add", "subtract", "intersect"] = "replace") -> dict:
    """Tạo vùng chọn. rect/ellipse: theo x, y, width, height (px). layer_pixels: chọn theo phần có điểm ảnh của layer.
    combine: thay mới / cộng / trừ / giao với vùng chọn cũ (cho rect, ellipse)."""
    return await jsx("Vùng chọn", r"""
var d = __doc(), m = ARGS.mode;
var st = { replace: SelectionType.REPLACE, add: SelectionType.EXTEND, subtract: SelectionType.DIMINISH, intersect: SelectionType.INTERSECT }[ARGS.combine];
if (m == "all") d.selection.selectAll();
else if (m == "none") d.selection.deselect();
else if (m == "invert") d.selection.invert();
else if (m == "rect") { var x = ARGS.x, y = ARGS.y, w = ARGS.width, h = ARGS.height; if (w <= 0 || h <= 0) throw new Error("width/height must be > 0"); d.selection.select([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], st, ARGS.feather, true); }
else if (m == "ellipse") {
  if (ARGS.width <= 0 || ARGS.height <= 0) throw new Error("width/height must be > 0");
  var ev = { replace: "setd", add: "AddT", subtract: "SbtF", intersect: "IntW" }[ARGS.combine];
  var desc = new ActionDescriptor(), ref = new ActionReference(); ref.putProperty(cTID("Chnl"), cTID("fsel")); desc.putReference(cTID("null"), ref);
  var r = new ActionDescriptor(); r.putUnitDouble(cTID("Top "), cTID("#Pxl"), ARGS.y); r.putUnitDouble(cTID("Left"), cTID("#Pxl"), ARGS.x);
  r.putUnitDouble(cTID("Btom"), cTID("#Pxl"), ARGS.y + ARGS.height); r.putUnitDouble(cTID("Rght"), cTID("#Pxl"), ARGS.x + ARGS.width);
  desc.putObject(cTID("T   "), cTID("Elps"), r); if (ARGS.feather > 0) desc.putUnitDouble(cTID("Fthr"), cTID("#Pxl"), ARGS.feather);
  desc.putBoolean(cTID("AntA"), true); executeAction(cTID(ev), desc, DialogModes.NO);
}
else if (m == "layer_pixels") {
  d.activeLayer = __find(d, ARGS.layer);
  var desc2 = new ActionDescriptor(), r1 = new ActionReference(); r1.putProperty(cTID("Chnl"), cTID("fsel")); desc2.putReference(cTID("null"), r1);
  var r2 = new ActionReference(); r2.putEnumerated(cTID("Chnl"), cTID("Chnl"), cTID("Trsp")); desc2.putReference(cTID("T   "), r2);
  executeAction(cTID("setd"), desc2, DialogModes.NO);
}
try { var b = d.selection.bounds; return { has_selection: true, bounds: { left: __px(b[0]), top: __px(b[1]), right: __px(b[2]), bottom: __px(b[3]) } }; }
catch (e) { return { has_selection: false }; }
""", {"mode": mode, "x": x, "y": y, "width": width, "height": height, "layer": layer, "feather": feather,
      "combine": combine}, history=True)


@mcp.tool()
async def photoshop_layer_mask(layer: str = "",
                               action: Literal["reveal_all", "hide_all", "from_selection", "delete", "apply",
                                               "to_selection", "enable", "disable"] = "from_selection") -> dict:
    """Mask của layer. reveal_all/hide_all/from_selection: tạo mask (trắng / đen / theo vùng chọn hiện tại);
    nếu layer đã có mask thì mask cũ bị thay (layer màu / adjustment luôn có sẵn mask trắng).
    delete: xoá mask; apply: áp mask vào ảnh; to_selection: nạp mask thành vùng chọn; enable/disable: bật/tắt mask."""
    return await jsx("Mask layer", r"""
var d = __doc(), l = __find(d, ARGS.layer), a = ARGS.action; d.activeLayer = l;
var has = __getBool(l.id, "hasUserMask"), replaced = false;
function maskRef() { var r = new ActionReference(); r.putEnumerated(cTID("Chnl"), cTID("Chnl"), cTID("Msk ")); return r; }
if (a == "reveal_all" || a == "hide_all" || a == "from_selection") {
  var u = { reveal_all: "RvlA", hide_all: "HdAl", from_selection: "RvlS" }[a];
  if (a == "from_selection") { try { d.selection.bounds; } catch (e) { throw new Error("No active selection"); } }
  if (has) { var rd = new ActionDescriptor(); rd.putReference(cTID("null"), maskRef()); executeAction(cTID("Dlt "), rd, DialogModes.NO); replaced = true; }
  var desc = new ActionDescriptor(); desc.putClass(cTID("Nw  "), cTID("Chnl")); desc.putReference(cTID("At  "), maskRef());
  desc.putEnumerated(cTID("Usng"), cTID("UsrM"), cTID(u)); executeAction(cTID("Mk  "), desc, DialogModes.NO);
} else {
  if (!has) throw new Error("Layer has no mask");
  if (a == "delete" || a == "apply") { var dd = new ActionDescriptor(); dd.putReference(cTID("null"), maskRef()); if (a == "apply") dd.putBoolean(cTID("Aply"), true); executeAction(cTID("Dlt "), dd, DialogModes.NO); }
  else if (a == "to_selection") { var sd = new ActionDescriptor(), sr = new ActionReference(); sr.putProperty(cTID("Chnl"), cTID("fsel")); sd.putReference(cTID("null"), sr); sd.putReference(cTID("T   "), maskRef()); executeAction(cTID("setd"), sd, DialogModes.NO); }
  else { var ed = new ActionDescriptor(), er = new ActionReference(); er.putEnumerated(cTID("Lyr "), cTID("Ordn"), cTID("Trgt")); ed.putReference(cTID("null"), er);
    var p = new ActionDescriptor(); p.putBoolean(cTID("UsrM"), a == "enable"); ed.putObject(cTID("T   "), cTID("Lyr "), p); executeAction(cTID("setd"), ed, DialogModes.NO); }
}
return { layer: __brief(l), has_mask: __getBool(l.id, "hasUserMask"), replaced_existing_mask: replaced };
""", {"layer": layer, "action": action}, history=True)


# ---------------------------------------------------------------- lịch sử & script

@mcp.tool()
async def photoshop_undo(steps: int = 1, redo: bool = False) -> dict:
    """Hoàn tác (hoặc làm lại nếu redo=True) `steps` bước trong History. Mỗi lệnh sửa của MCP này là 1 bước."""
    return await jsx("undo", r"""
var d = __doc(), h = d.historyStates, cur = d.activeHistoryState, idx = -1;
for (var i = 0; i < h.length; i++) if (h[i] == cur) { idx = i; break; }
var to = ARGS.redo ? idx + ARGS.steps : idx - ARGS.steps; to = Math.max(0, Math.min(h.length - 1, to));
d.activeHistoryState = h[to]; return { history_state: h[to].name, index: to, total: h.length };
""", {"steps": max(1, steps), "redo": redo})


@mcp.tool()
async def photoshop_execute_jsx(script: str, timeout_seconds: float = 0) -> dict:
    """Chạy JavaScript (ExtendScript/JSX) tuỳ ý trong Photoshop cho việc các công cụ khác chưa có.
    Trả về giá trị biểu thức cuối, hoặc giá trị `return` (nếu script có return ở cấp ngoài cùng).
    Có sẵn: JSON.stringify/parse, cTID(), sTID(); đơn vị thước tạm đặt là pixel khi chạy; hộp thoại bị tắt.
    Hàm tiện ích: __find(doc, idOrNameOrPath) tìm layer, __brief(layer), __px(UnitValue), __rgb(r,g,b),
    __transform(layer, {x,y,dx,dy,width,height,scale,rotate}).
    Việc nhiều bước nên gộp vào một script và bọc doc.suspendHistory(...) để thành 1 bước Undo.
    Chuyển layer vào group: dùng ElementPlacement.INSIDE (PLACEATEND với group sẽ lỗi).
    timeout_seconds: 0 = mặc định của server."""
    return await jsx("script", r"""
var c = ARGS.code;
return /(^|[^\w$.])return\b/.test(c) ? eval("(function(){" + c + "\n})()") : eval(c);
""", {"code": script}, timeout=timeout_seconds or TIMEOUT)


# UXP is opt-in until host validation; COM remains the default backend.
if os.environ.get("PS_UXP_ENABLED") == "1":
    from uxp_tools import register_uxp_tools
    register_uxp_tools(mcp)


def main() -> None:
    log(f"started (timeout {TIMEOUT:.0f}s)")
    mcp.run()


if __name__ == "__main__":
    main()
