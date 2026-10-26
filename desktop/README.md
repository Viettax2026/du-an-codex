# ZaloFlow Windows

Mở `ZaloFlow.exe` để dùng giao diện trong cửa sổ Windows. Bộ lịch chỉ khởi động sau khi cửa sổ hiện ra. Đóng tool chặn lượt mới ngay, chờ lượt hiện tại kết thúc rồi dừng web/bộ lịch/worker QR. Dữ liệu, kết quả và hạn mức lưu trong `%LOCALAPPDATA%\ZaloFlow\instance`; mở lại tiếp tục bước chờ. Thu nhỏ vẫn chạy; máy ngủ/tắt không chạy.

Tải bản dựng tại [Build Windows desktop](https://github.com/Viettax2026/du-an-codex/actions/workflows/windows-desktop.yml), mở lượt có dấu xanh rồi tải **Artifacts → ZaloFlow-Windows-x64**. Cần đăng nhập GitHub để tải artifact. Giải nén toàn bộ rồi mở `ZaloFlow.exe`, giữ thư mục `_internal` cạnh tệp EXE. Gói gồm Python và Node.js/SDK; cần Windows 10/11 x64, Microsoft Edge WebView2 Runtime và Internet. Lần đầu tạo tài khoản ứng dụng rồi đăng nhập QR. Không tự cài dịch vụ hoặc tác vụ khởi động Windows.

Gói không chứa database, mật khẩu hoặc phiên QR từ VPS. Không đồng bộ dữ liệu giữa máy tính và VPS. Muốn chuyển dữ liệu cần dừng bộ lịch VPS, sao lưu đầy đủ `instance` khi web/bộ lịch đã dừng rồi chép vào thư mục dữ liệu của tool đang đóng; xem [hướng dẫn](HUONG-DAN.txt). Không bật hai bộ chạy trên hai bản sao cùng chiến dịch.

Dựng lại trên Windows x64 với Python 3.12 và Node.js 22:

```powershell
powershell -ExecutionPolicy Bypass -File desktop/build-windows.ps1
```

Kết quả `desktop/dist/ZaloFlow/`. Thư mục chương trình và dữ liệu tách riêng. Gói Windows chưa ký chứng thư. Workflow kiểm tra khóa Windows, chạy bản EXE với database tạm, xác nhận web/bộ lịch mở–đóng và Node đi kèm, rồi mở/đóng cửa sổ Edge WebView2. Không gửi tin Zalo. Máy người dùng cần WebView2 Runtime để mở cửa sổ.

Chạy mã nguồn (đã cài Node, `npm ci` trong `connector`, và `pip install -r desktop/requirements.txt`):

```powershell
python -m desktop.main
```

`--data-dir` chọn thư mục dữ liệu khác khi cần. Giữ nguyên khóa theo database để không mở hai tool hoặc hai bộ lịch cùng lúc. Dữ liệu VPS cũ không tự đổi vị trí hay tự khởi chạy trên máy tính.
