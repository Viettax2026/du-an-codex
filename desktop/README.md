# ZaloFlow Windows

Mở `ZaloFlow.exe` để dùng giao diện trong cửa sổ Windows. Bộ lịch chỉ khởi động sau khi cửa sổ hiện ra. Đóng tool chặn lượt mới ngay, chờ lượt hiện tại kết thúc rồi dừng web/bộ lịch/worker QR. Dữ liệu, kết quả và hạn mức lưu trong `%LOCALAPPDATA%\ZaloFlow\instance`; mở lại tiếp tục bước chờ. Thu nhỏ vẫn chạy; máy ngủ/tắt không chạy.

Tải bản dựng tại [Build Windows desktop](https://github.com/Viettax2026/du-an-codex/actions/workflows/windows-desktop.yml), mở lượt có dấu xanh rồi tải **Artifacts → ZaloFlow-Setup-Windows-x64**. Cần đăng nhập GitHub để tải artifact. Mở ZIP tải về, lấy **ZaloFlow-Setup-x64.exe** rồi chạy để cài. Bộ cài tạo sẵn biểu tượng **ZaloFlow** ngoài Desktop và trong Start menu; mở ứng dụng bằng biểu tượng này. Chương trình nằm trong `%LOCALAPPDATA%\Programs\ZaloFlow`; không cần quyền quản trị. Các tệp hỗ trợ nằm trong thư mục `_internal` được ẩn mặc định. Gói gồm Python và Node.js/SDK; cần Windows 10/11 x64, Microsoft Edge WebView2 Runtime và Internet. Lần đầu kích hoạt key, tạo tài khoản ứng dụng rồi đăng nhập QR. Không tự cài dịch vụ hoặc tác vụ khởi động Windows.

Ẩn tệp giúp thư mục gọn hơn, không phải cơ chế chống sao chép: người dùng vẫn có thể bật **Hidden items** hoặc trích xuất bộ cài. Kiểm tra key một máy và xác thực định kỳ mới kiểm soát quyền sử dụng bản phân phối. Kho mã hiện công khai; đóng gói không biến mã nguồn đã công khai thành bí mật. Không phát gói thư mục phát triển hoặc dữ liệu thật cho khách; chỉ gửi bộ cài EXE.

Nâng cấp: đóng ZaloFlow hoàn toàn rồi chạy bộ cài mới trong cùng tài khoản Windows. Dữ liệu, phiên Zalo và kích hoạt ở `%LOCALAPPDATA%\ZaloFlow`, ngoài thư mục chương trình, được giữ lại khi nâng cấp hoặc gỡ ứng dụng. Gỡ ứng dụng không hủy kích hoạt key; muốn chuyển máy, dùng **Bản quyền → Hủy kích hoạt máy này** trước. Nếu trước đây dùng gói ZIP, đóng bản cũ trước khi cài; dùng cùng tài khoản Windows sẽ tiếp tục dữ liệu đã lưu ở vị trí mặc định. Sau khi kiểm tra bản mới, có thể xóa thư mục chương trình ZIP cũ; giữ nguyên thư mục dữ liệu.

Gói không chứa database, mật khẩu hoặc phiên QR từ VPS. Không đồng bộ dữ liệu giữa máy tính và VPS. Muốn chuyển dữ liệu cần dừng bộ lịch VPS, sao lưu đầy đủ `instance` khi web/bộ lịch đã dừng rồi chép vào thư mục dữ liệu của tool đang đóng; xem [hướng dẫn](HUONG-DAN.txt). Không bật hai bộ chạy trên hai bản sao cùng chiến dịch.

Bản mới yêu cầu **key sử dụng cho một máy** trước khi tạo tài khoản và chạy chiến dịch. Chủ phần mềm cài máy chủ key, lấy cấu hình **công khai** rồi dựng bản Windows theo [hướng dẫn quản lý bản quyền](../deployment/LICENSES.md). Gói khách không chứa khóa ký riêng. Workflow chưa có cấu hình chỉ kiểm thử, không phát artifact cho khách. Dữ liệu kích hoạt nằm ngoài `instance`, trong `%LOCALAPPDATA%\ZaloFlow\license`; sao chép dữ liệu chiến dịch không chuyển được bản quyền sang máy khác.

Dựng lại trên Windows x64 với Python 3.12, Node.js 22 và Inno Setup 6:

```powershell
powershell -ExecutionPolicy Bypass -File desktop/build-windows.ps1
powershell -ExecutionPolicy Bypass -File desktop/build-installer.ps1 -AppVersion 1.0.0
```

Kết quả phát cho khách: `desktop/dist/installer/ZaloFlow-Setup-x64.exe` và SHA-256 bên cạnh. `desktop/dist/ZaloFlow/` chỉ là đầu vào của bộ cài. Thư mục chương trình và dữ liệu tách riêng. Gói Windows chưa ký chứng thư. Workflow kiểm tra khóa Windows, chạy bản EXE với database tạm, xác nhận web/bộ lịch mở–đóng và Node đi kèm, rồi mở/đóng cửa sổ Edge WebView2. Sau đó cài thật trong thư mục có dấu cách, kiểm tra icon Desktop/Start, thư mục hỗ trợ ẩn, chạy EXE đã cài, cài đè và gỡ; xác nhận dữ liệu và kích hoạt thử được giữ nguyên. Không gửi tin Zalo. Máy người dùng cần WebView2 Runtime để mở cửa sổ.

Chạy mã nguồn (đã cài Node, `npm ci` trong `connector`, và `pip install -r desktop/requirements.txt`):

```powershell
python -m desktop.main
```

`--data-dir` chọn thư mục dữ liệu khác khi cần. Giữ nguyên khóa theo database để không mở hai tool hoặc hai bộ lịch cùng lúc. Dữ liệu VPS cũ không tự đổi vị trí hay tự khởi chạy trên máy tính.
