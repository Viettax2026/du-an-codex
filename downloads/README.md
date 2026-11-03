# Gói mã nguồn ZaloFlow để lưu dự phòng

## Lưu ý về thông tin chủ phần mềm

Bản mới **1.0.21** giữ việc loại email quản trị cũ khỏi mã desktop và đã vượt kiểm tra cả tệp cài ra lẫn mã nén. Chủ phần mềm đã cho phép giữ URL máy chủ bản quyền hiện tại. Xem [báo cáo kiểm tra thực tế](../deployment/PRIVACY-AUDIT.md). Các bản 1.0.18 trở về trước bên dưới là bản lưu lịch sử, còn dấu vết cũ trong mã nén. Link phát hành GitHub vẫn hiển thị tài khoản chủ sở hữu; có thể gửi trực tiếp file EXE cho khách.

## Tool Windows ngày 03/11/2026 — bản mới 1.0.21

- [Tải bộ cài Windows EXE](https://github.com/Viettax2026/du-an-codex/releases/download/windows-tool-customer-admin-20261103/ZaloFlow-Setup-x64.exe)
- [Tải ZIP kèm hướng dẫn và báo cáo kiểm tra](https://github.com/Viettax2026/du-an-codex/releases/download/windows-tool-customer-admin-20261103/ZaloFlow-Tool-Windows-2026-11-03.zip)

Nguồn ứng dụng `889383fa0f780fefe3884d904bb06a2bc044183b`. Dựng lại từ mã mới nhất theo yêu cầu trực tiếp của chủ phần mềm. Máy chủ mới gợi ý tên quản trị theo khách hàng, ví dụ “Thảo Như” → `quantri-thaonhu`, cho phép sửa trước khi cấp key. Tên tự tạo bị trùng sẽ thêm `-2`, `-3`; tên nhập riêng bị trùng sẽ báo chọn lại. **Cần cập nhật VPS** theo [hướng dẫn bản quyền](../deployment/LICENSES.md) để trang cấp key có chức năng này; cài lại Windows không tự cập nhật VPS. Các key/tài khoản đã cấp không tự đổi tên hoặc mật khẩu.

[Lượt dựng Windows 21](https://github.com/Viettax2026/du-an-codex/actions/runs/41576000929) hoàn tất thành công: kiểm tra tài khoản, bản quyền, xử lý trùng tên, WebView2, bộ lịch, cài đặt/cài đè/gỡ giữ dữ liệu và quét tệp cài ra. Đã tải lại ZIP công khai không cần đăng nhập, kiểm tra CRC/checksum/manifest và phiên bản 1.0.21 trong SOURCE. Giải nén chính EXE tải về và quét độc lập 2058 tệp, 1036 mô-đun Python, 165 mục ZIP; hash chương trình khớp báo cáo Windows. Không phát hiện các dấu vết chủ sở hữu được kiểm tra ngoài URL key đã cho phép; báo cáo đi kèm ZIP.

Đóng tool cũ rồi cài đè trong cùng tài khoản Windows để giữ dữ liệu và kích hoạt. Chưa có kết quả kiểm tra VPS thật do chủ phần mềm cung cấp; trạng thái đó được ghi rõ trong manifest.

SHA256 ZIP: `eee6ca4ca55bc0add6b058b9b24a2526a0a3493b752acb86df3a58d7856fb8d5`.

## Tool Windows ngày 02/11/2026 — bản 1.0.20, xử lý trùng tên quản trị

- [Tải bộ cài Windows EXE](https://github.com/Viettax2026/du-an-codex/releases/download/windows-tool-login-20261102/ZaloFlow-Setup-x64.exe)
- [Tải ZIP kèm hướng dẫn và báo cáo kiểm tra](https://github.com/Viettax2026/du-an-codex/releases/download/windows-tool-login-20261102/ZaloFlow-Tool-Windows-2026-11-02-r3.zip)

Nguồn ứng dụng `16b433662e3e27939bfc3286fb18b673ef897e49`. Sửa trường hợp key có quản trị `test` nhưng trong tool đã có tài khoản `test` dùng mật khẩu khác. Vào **Bản quyền → Tạo quản trị bằng tên khác**, chọn tên chưa dùng (ví dụ `test-key-6`), xác nhận bằng mật khẩu khởi tạo đã cấp cùng key. Sau đó đăng nhập bằng tên mới và cùng mật khẩu đó. Giữ nguyên key, tài khoản, mật khẩu, quyền và dữ liệu cũ; dữ liệu cũ vẫn thuộc tài khoản cũ. Chỉ tạo một quản trị cho mỗi key trong hồ sơ tool, giữ ánh xạ tên mới khi mở lại/gia hạn và không đặt lại mật khẩu đã đổi.

Đã kiểm tra luồng qua trình duyệt với dữ liệu giả, chương trình biên dịch trên Windows/WebView2 và cài đặt/cài đè/gỡ giữ dữ liệu. Lượt dựng 20 vượt các kiểm tra nhưng lỗi ở bước xuất bản; [lượt khôi phục phát hành](https://github.com/Viettax2026/du-an-codex/actions/runs/41479183393) dùng lại chính bộ cài đó và kiểm tra lại trước khi phát hành. Đã tải ZIP công khai, đối chiếu CRC/checksum/manifest, giải nén EXE và quét 2058 tệp, 1036 mô-đun Python, 165 mục ZIP; không có phát hiện ngoài URL key đã cho phép và không có lỗi đọc. Hash chương trình khớp báo cáo cài đặt Windows.

Đóng tool cũ rồi cài đè trong cùng tài khoản Windows. Không cần cấp key mới hoặc cập nhật VPS cho sửa lỗi trùng tên này. Chưa có kết quả kiểm tra VPS thật do chủ phần mềm cung cấp.

SHA256 ZIP: `412e626f40bad661e7a21da558be0a928139c5ff63ed9932624ba37496454c48`.

## Tool Windows ngày 02/11/2026 — bản 1.0.19

- [Tải bộ cài Windows EXE](https://github.com/Viettax2026/du-an-codex/releases/download/windows-tool-privacy-20261102/ZaloFlow-Setup-x64.exe)
- [Tải ZIP kèm hướng dẫn và báo cáo kiểm tra](https://github.com/Viettax2026/du-an-codex/releases/download/windows-tool-privacy-20261102/ZaloFlow-Tool-Windows-2026-11-02-r2.zip)

Nguồn ứng dụng `5ab04a23d8fa5fd0e954d94d32b7e0c1c4231aae`. Bỏ mô-đun chuyển đổi email quản trị web cũ khỏi desktop và không đóng kèm JSON cấu hình rõ. Giữ máy chủ key và khóa công khai đang dùng; tài khoản và dữ liệu cũ được giữ nguyên. Không yêu cầu đổi tên miền.

Đã kiểm tra Windows/WebView2, tài khoản/quyền, cài đè, shortcut và gỡ giữ dữ liệu/kích hoạt. Quét sau cài đặt: 2060 tệp, 1036 mô-đun Python, 165 mục ZIP; không phát hiện chuỗi chủ sở hữu đã kiểm tra ngoài URL key được cho phép. Đã tải lại ZIP công khai, kiểm tra toàn bộ checksum/manifest, giải nén EXE và quét độc lập; hash chương trình khớp báo cáo Windows. `PRIVACY-AUDIT.json` đi kèm gắn kết quả với đúng bộ cài.

Đóng tool cũ rồi cài đè trong cùng tài khoản Windows. Các chức năng key một phiên, tự tạo quản trị và tạo nhiều tài khoản trong cùng tool được giữ nguyên. Chưa có kết quả kiểm tra VPS thật do chủ phần mềm cung cấp.

SHA256 ZIP: `83146e111e6581a1f2ea6bf1b250fc3a640961c60debe89b83b7df075cc4b7f3`.

## Tool Windows ngày 02/11/2026 — bản 1.0.18

- [Tải bộ cài Windows EXE](https://github.com/Viettax2026/du-an-codex/releases/download/windows-tool-neutral-20261102/ZaloFlow-Setup-x64.exe)
- [Tải ZIP bộ cài kèm hướng dẫn](https://github.com/Viettax2026/du-an-codex/releases/download/windows-tool-neutral-20261102/ZaloFlow-Tool-Windows-2026-11-02.zip)

Nguồn `bcd5cb298ab438ac487c236ced8f0caaa7af78d5`: màn hình cài đặt, nhà phát hành và hướng dẫn dùng thương hiệu ZaloFlow, không hiển thị thông tin đơn vị sở hữu trong hướng dẫn khách hàng. Máy chủ mới tự tạo đủ key, tài khoản và mật khẩu quản trị, hỗ trợ xem lại bộ thông tin khởi tạo và bổ sung quản trị cho key chưa có. Khách đã đổi/khôi phục mật khẩu trong tool vẫn dùng mật khẩu mới, không bị đặt lại.

Đã kiểm tra native Windows/WebView2, chức năng tài khoản, publisher/hướng dẫn sau cài đặt, icon Desktop, cài đè và gỡ giữ dữ liệu. Đóng tool cũ rồi cài đè trong cùng tài khoản Windows. Quản trị cần cập nhật máy chủ theo [hướng dẫn bản quyền](../deployment/LICENSES.md) để dùng tự tạo quản trị và xem bộ thông tin; hướng dẫn khách hàng trong ZIP không chứa địa chỉ quản trị riêng. Chưa có kết quả kiểm tra VPS thật do chủ phần mềm cung cấp; bản được đóng gói theo yêu cầu trực tiếp ngày 02/11/2026.

SHA256 ZIP: `bdee7827ab582e717f57c8f7d9633827f8c33a26c91982a84178ebe01a2f2eb1`.

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
