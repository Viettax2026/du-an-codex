# Gói mã nguồn ZaloFlow để lưu dự phòng

## Tool Windows ngày 01/11/2026

- [Tải bộ cài Windows EXE](https://github.com/Viettax2026/du-an-codex/releases/download/windows-tool-admin-20261101/ZaloFlow-Setup-x64.exe)
- [Tải ZIP bộ cài kèm hướng dẫn](https://github.com/Viettax2026/du-an-codex/releases/download/windows-tool-admin-20261101/ZaloFlow-Tool-Windows-2026-11-01.zip)

Nguồn ứng dụng `ac4e5fb3c177dc46df5ea4d33a21131a43fdb98b`: key mới dùng trong một tool tại một thời điểm, không khóa máy; cấp key kèm quản trị tool để tạo nhiều tài khoản thường. Bộ cài đã được dựng và kiểm tra trên Windows, gồm cửa sổ WebView2, tài khoản/quyền, icon Desktop, cài đè và gỡ giữ dữ liệu. Đóng tool cũ rồi cài đè bằng cùng tài khoản Windows.

Cần cập nhật máy chủ key theo `HUONG-DAN.txt` trong ZIP. Chưa có kết quả xác nhận kiểm tra VPS thật từ chủ phần mềm; bản này được đóng gói theo yêu cầu trực tiếp ngày 01/11/2026. Bộ cài không chứa tài khoản khách hàng, mật khẩu SMTP hoặc khóa ký riêng. Các gói mã nguồn bên dưới là bản lưu theo đúng ngày, không tự thêm thay đổi mới.

SHA256 ZIP: `33dd8c62941a5019237e63b6ce3b323d1d7d158430d576df11a0ae7c2b65623c`.

## Bản ngày 30/10/2026

[Tải mã nguồn và bộ cài VPS mới](https://github.com/Viettax2026/du-an-codex/raw/refs/heads/main/downloads/ZaloFlow-toan-bo-code-va-cai-VPS-2026-10-30.zip)

Mã ứng dụng `73f38a058680535486990dfcc1a4890ae4e2726e`: Windows tự đăng ký sau khi kích hoạt key hợp lệ, mật khẩu từ 8 ký tự, web giữ bước duyệt; có bản sửa nhận xác nhận upload PDF/MP4. SHA256: `8db6a712134e8e2b089770c8e9f5b7fafa1b8a971f27e6832d8c94214602b0ef`.

Theo yêu cầu đóng gói trực tiếp ngày 30/10/2026, mốc `windows-owner-package-20261030-r2` dựng Windows từ đúng mã này và phát [gói mã nguồn + bộ cài Windows để tải trực tiếp](https://github.com/Viettax2026/du-an-codex/releases/tag/windows-owner-package-20261030-r2) sau khi kiểm tra bộ cài. Kết quả gửi/nhận PDF trên Zalo thật chưa được chủ ứng dụng xác nhận; trạng thái này được ghi trong manifest và hướng dẫn, không đánh dấu là đã thử VPS thật.

Gói mới loại riêng thư mục `downloads/` khỏi ZIP mã nguồn vì đó là các gói phát hành đã tạo trước, không phải thành phần chạy ứng dụng. Toàn bộ mã web, Windows, connector, máy chủ key, kiểm thử và hướng dẫn triển khai vẫn có trong ZIP nguồn. Không đưa dữ liệu hoặc bí mật vận hành vào gói.

## Bản lưu ngày 29/10/2026

[Tải ZIP toàn bộ mã nguồn và bộ cài VPS mới](https://github.com/Viettax2026/du-an-codex/raw/refs/heads/main/downloads/ZaloFlow-toan-bo-code-va-cai-VPS-2026-10-29.zip)

Gói ngày 29/10/2026 chứa mã nguồn đầy đủ tại commit `03e95b56f7dea9bfaae4676db099cb029108c82a` (263 tệp), gói web có manifest đã kiểm tra, hướng dẫn cài Ubuntu 24.04 với domain mới và hướng dẫn sao lưu/khôi phục dữ liệu. Giải nén rồi đọc `ZaloFlow-backup/HUONG-DAN.txt`. Đây là bản chụp mã nguồn cố định; không tự thay đổi khi main có cập nhật sau đó.

SHA256 của ZIP: `548582781b0b4dff2adec6f4e20718e6729b01ffab5f16c62d809f584116f62b`.

Không chứa dữ liệu khách hàng đang chạy, phiên Zalo, mật khẩu Gmail hoặc kho key/khóa ký riêng của VPS. Muốn chuyển cả công việc đang dùng, cần sao lưu riêng toàn bộ `instance`; máy chủ cấp key cần sao lưu riêng kho authority. Các bước nằm trong hướng dẫn bên trong. Không đưa các bản sao dữ liệu riêng tư lên kho mã công khai này.
