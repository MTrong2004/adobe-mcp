# Tài liệu và nguồn tham khảo

API host và quy trình nạp plugin phải được kiểm chứng bằng tài liệu Adobe cùng thử nghiệm trên phiên bản host thực tế. Nguồn cộng đồng hỗ trợ triển khai, không thay bằng chứng live.

| Nguồn | Cách dùng trong repo |
|---|---|
| [Premiere UXP API reference](https://developer.adobe.com/premiere-pro/uxp/ppro-reference/) | API project, sequence, media và transaction của Premiere UXP |
| [Premiere UXP changelog](https://developer.adobe.com/premiere-pro/uxp/changelog/) | Đối chiếu yêu cầu phiên bản và thay đổi API |
| [Premiere plugin development](https://developer.adobe.com/premiere-pro/uxp/plugins/) | Developer mode, UDT 2.2+, Add/Load & Watch |
| [Adobe UXP Premiere samples](https://github.com/AdobeDocs/uxp-premiere-pro-samples) | Tham khảo cách gọi API chính thức |
| [After Effects scripts](https://helpx.adobe.com/after-effects/using/scripts.html) | Scripting và giới hạn host AE |
| [AE scripting guide](https://ae-scripting.docsforadobe.dev/introduction/overview/) | Tài liệu cộng đồng về ExtendScript/AE object model |
| [Adobe CEP Resources](https://github.com/Adobe-CEP/CEP-Resources) | Manifest, CSInterface/evalScript và CEP cookbook |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) | FastMCP server và client stdio smoke thật; dependency pin 1.30.0 |
| [Adobe MCP của zachshallbetter](https://github.com/zachshallbetter/adobe-mcp) | Cảm hứng tổ chức công cụ; các tool AE/Premiere upstream không được xem là đã kiểm thử thực tế |
| [Pymiere](https://github.com/qmasingarbe/pymiere) | Tham khảo bài toán cầu nối Premiere cũ; hướng CEP cũ, upstream nêu bảo trì tới Premiere 23.1, không dùng làm nền tảng UXP mới |
| [Bolt CEP](https://github.com/hyperbrew/bolt-cep) | Ý tưởng tương thích ExtendScript ES3 và JSON; không sao chép mã nguồn |

Nguồn nội bộ AI Media Studio được dùng cho phản biện Muse về thiết kế và các mẫu vận hành: tách broker theo app, tuần tự hóa job, timeout không tự retry, kiểm tra mức độ sẵn sàng. Không sao chép credential, proxy, tài khoản, URL hội thoại hay mã công cụ nội bộ vào repo này. Các nhận định về lịch sunset/phiên bản chưa kiểm chứng độc lập không được dùng làm cam kết hỗ trợ.

Không có mã nguồn bên thứ ba được chép từ các dự án cảm hứng trong đợt triển khai này. Nếu bổ sung mã bên thứ ba về sau, giữ copyright/license và ghi rõ nguồn, phần được lấy và thay đổi; liên kết tham khảo đơn thuần không thay thế nghĩa vụ giấy phép.
