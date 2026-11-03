# Kiểm tra dấu vết chủ phần mềm — ZaloFlow và ZaloFlow Local

Ngày kiểm tra cập nhật: 03/11/2026; các kết quả ngày 02/11 được giữ bên dưới. Đây là kiểm tra **bộ cài đã phát hành**, không chỉ mã nguồn hoặc ảnh giao diện.

## Kết luận

**Bản riêng ZaloFlow Local 1.0.2** không cần key và không đóng kèm các mô-đun bản quyền. Đã tải lại EXE/ZIP và quét nghiêm ngặt: không có phát hiện/lỗi hoặc ngoại lệ URL máy chủ. Đây là bản độc lập theo yêu cầu chủ phần mềm ngày 03/11/2026; không thay cơ chế kiểm tra key của bản chuẩn.

Bản **có key 1.0.21 đã phát hành và được tải lại để kiểm tra độc lập**, tiếp tục giữ sửa đổi của 1.0.19 và 1.0.20. Không phát hiện các chuỗi nhận diện đã kiểm tra ngoài URL máy chủ key được phép giữ. Email quản trị cũ đã được loại khỏi mã nén desktop. **Chủ phần mềm đã xác nhận giữ địa chỉ máy chủ kiểm tra key hiện tại cho bản có key**: địa chỉ này là ngoại lệ được phép trong cấu hình và mô-đun nhận diện bản quyền, không phải trong hướng dẫn hoặc giao diện thông thường. Phạm vi sửa của bản có key là loại các dấu vết khác, không phải ẩn toàn bộ nguồn gốc máy chủ.

## Kết quả ZaloFlow Local 1.0.2

- [EXE](https://github.com/Viettax2026/du-an-codex/releases/download/windows-local-20261103-r2/ZaloFlow-Local-Setup-x64.exe), [ZIP và báo cáo](https://github.com/Viettax2026/du-an-codex/releases/download/windows-local-20261103-r2/ZaloFlow-Local-Windows-2026-11-03.zip), nguồn chương trình `c685aca701158842013464369dcca7376108f85b`, `Edition: local`, phiên bản 1.0.2.
- [Lượt dựng 2](https://github.com/Viettax2026/du-an-codex/actions/runs/41583163759) vượt kiểm tra mã, quét EXE nghiêm ngặt và chạy WebView2; dừng ở cách gọi công cụ quét sau cài đặt không tạo được báo cáo. Sau khi thay lời gọi bằng tham số tường minh và giữ stdout/stderr, [lượt xác minh/phát hành](https://github.com/Viettax2026/du-an-codex/actions/runs/41584207008) dùng lại đúng artifact, vượt toàn bộ cài đặt/cài đè/gỡ, kiểm tra dữ liệu hai hồ sơ và quét tệp cài ra trước khi xuất bản. Không bỏ qua hoặc miễn trừ phát hiện để phát hành.
- Quét thực tế sau cài đặt Windows: **2060 tệp, 1033 mô-đun Python, 165 mục ZIP**, `passed: true`, `strict: true`, `findings: []`, `errors: []`, `accepted_exceptions: []`, `licensing_modules: []`.
- Tải riêng EXE và ZIP công khai; hash EXE trực tiếp khớp EXE trong ZIP và báo cáo cài đặt Windows. Đối chiếu từng tệp manifest, CRC và SOURCE; giải nén **chính EXE tải trực tiếp** rồi quét độc lập **2058 tệp, cùng 1033 mô-đun và 165 mục ZIP**, đạt cùng kết quả nghiêm ngặt. Cảnh báo chuyển mã innoextract và phạm vi bộ quét được ghi ở phần 1.0.19 bên dưới.
- Xác nhận có `desktop.local_runtime`, `desktop.local_smoke`, `desktop.window`; không có `license_system` và các mô-đun con, `desktop.licensing`, `desktop.license_identity`, `desktop.license_routes`, `desktop.main` hoặc `legacy_web_accounts`. Không có JSON cấu hình máy chủ. Bản Local không dựng license client, không có luồng kiểm tra key hoặc trang kích hoạt; đã kiểm tra trong EXE bằng dữ liệu giả.
- SHA256 chương trình chính: `0f183216450b6a5f5a54cc93f2930a9dbf6f8e482b3d4cf4e93fa3a5447d4c47`.
- SHA256 bộ cài: `7cd10f2f3a9fadcecd1768eb52d8e08a706d23c40c9352d2901b3a44f5ed0c15`.
- SHA256 ZIP (42827483 byte): `1cbb77f81f2d899ab2b3ed73ead2827313e173dd60b378c2ce23fb2478c2501f`.

Giới hạn: đây là kiểm tra các chuỗi nhận diện đã biết, cấu trúc gói và các mô-đun sau giải nén, không phải lời hứa không thể liên hệ nguồn gốc phần mềm. Tài khoản GitHub trên kênh tải vẫn hiển thị tên chủ sở hữu; có thể gửi khách trực tiếp file EXE đã tải. Hồ sơ Local mới độc lập, không đọc hoặc đổi tên dữ liệu riêng của người dùng trên bản khác. Không kiểm tra gửi Zalo thật trong lượt đóng gói này.

## Kết quả bản 1.0.21 đã phát hành

- [Bộ cài EXE](https://github.com/Viettax2026/du-an-codex/releases/download/windows-tool-customer-admin-20261103/ZaloFlow-Setup-x64.exe), [ZIP kèm hướng dẫn và báo cáo](https://github.com/Viettax2026/du-an-codex/releases/download/windows-tool-customer-admin-20261103/ZaloFlow-Tool-Windows-2026-11-03.zip).
- Nguồn ứng dụng `889383fa0f780fefe3884d904bb06a2bc044183b`, phiên bản 1.0.21. Mã máy chủ mới có gợi ý tên quản trị theo khách hàng; cần cập nhật VPS để dùng chức năng đó trên trang cấp key.
- [Lượt dựng Windows 21](https://github.com/Viettax2026/du-an-codex/actions/runs/41576000929) đạt toàn bộ kiểm tra và xuất bản thành công. Quét thực tế sau cài đặt/nâng cấp: **2060 tệp, 1036 mô-đun Python, 165 mục ZIP**, không có phát hiện ngoài ngoại lệ URL key và không có lỗi đọc. Có kiểm tra Windows/WebView2, xử lý trùng tên quản trị, cài đè và gỡ giữ dữ liệu/kích hoạt.
- Tải lại ZIP công khai, đối chiếu từng checksum/manifest/CRC và phiên bản trong SOURCE. Giải nén EXE tải về bằng innoextract, quét độc lập **2058 tệp, cùng 1036 mô-đun và 165 mục ZIP**, kết quả đạt. Cảnh báo chuyển mã và phạm vi bộ quét giống phần 1.0.19 bên dưới.
- Xác nhận `legacy_web_accounts` không có trong PYZ và không có JSON cấu hình rõ trong gói mới. Xử lý `local_username`, `resolve-admin-name` và biểu mẫu tạo quản trị bằng tên khác vẫn có trong bản tải về. Hash chương trình trích xuất khớp báo cáo cài đặt Windows.
- SHA256 chương trình chính: `bdbc75765e170490e104d0cc6c07693f81f43b6df696de0cfa71cf97eb8d1c68`.
- SHA256 bộ cài: `757c3bf219b3a2bc2cc99dddfcafcda64585129e00266f34dcfdd4edac0839ce`.
- SHA256 ZIP (42849438 byte): `eee6ca4ca55bc0add6b058b9b24a2526a0a3493b752acb86df3a58d7856fb8d5`.

## Kết quả bản 1.0.20 đã phát hành

- [Bộ cài EXE](https://github.com/Viettax2026/du-an-codex/releases/download/windows-tool-login-20261102/ZaloFlow-Setup-x64.exe), [ZIP kèm hướng dẫn và báo cáo](https://github.com/Viettax2026/du-an-codex/releases/download/windows-tool-login-20261102/ZaloFlow-Tool-Windows-2026-11-02-r3.zip).
- Nguồn ứng dụng `16b433662e3e27939bfc3286fb18b673ef897e49`, phiên bản 1.0.20. Thêm xử lý tên quản trị trùng bằng tên local mới và xác nhận mật khẩu khởi tạo của key; không thay dữ liệu hoặc tài khoản cũ.
- [Lượt dựng 20](https://github.com/Viettax2026/du-an-codex/actions/runs/41476572891) vượt kiểm tra mã, chương trình biên dịch, WebView2 và bộ cài, nhưng lỗi xuất bản. [Lượt khôi phục](https://github.com/Viettax2026/du-an-codex/actions/runs/41479183393) tải lại đúng artifact của lượt 20, kiểm tra cài đặt/nâng cấp/gỡ và quét mã nén trước khi phát hành thành công; không dựng lại một EXE khác.
- Quét thực tế cài đặt Windows: **2060 tệp, 1036 mô-đun Python, 165 mục ZIP**, kết quả đạt. Tải lại ZIP công khai, đối chiếu từng checksum/manifest/CRC, giải nén chính bộ cài rồi quét độc lập **2058 tệp, cùng 1036 mô-đun và 165 mục ZIP**, kết quả đạt. Cảnh báo chuyển mã của innoextract và phạm vi bộ quét giống phần 1.0.19 bên dưới.
- Không có mô-đun `legacy_web_accounts` hoặc JSON cấu hình rõ trong gói mới. Xác nhận mã nén có xử lý `local_username` và `resolve-admin-name`, biểu mẫu mới có trong tệp template. Chỉ URL key trong `desktop.license_identity` được ghi là ngoại lệ đã cho phép.
- SHA256 chương trình chính khớp báo cáo Windows: `b3697680f5a1809806f656e65f11ba61c2e8994571848d55f0f0f9ecd3ad7f98`.
- SHA256 bộ cài: `d078b738919ae7e33e3139d736885f12c1037dda6914e5835f982b03ecd033a7`.
- SHA256 ZIP (42840885 byte): `412e626f40bad661e7a21da558be0a928139c5ff63ed9932624ba37496454c48`.

## Kết quả bản 1.0.19 đã phát hành

- [Bộ cài EXE](https://github.com/Viettax2026/du-an-codex/releases/download/windows-tool-privacy-20261102/ZaloFlow-Setup-x64.exe), [ZIP kèm hướng dẫn và báo cáo](https://github.com/Viettax2026/du-an-codex/releases/download/windows-tool-privacy-20261102/ZaloFlow-Tool-Windows-2026-11-02-r2.zip).
- [Kiểm tra Windows đạt](https://github.com/Viettax2026/du-an-codex/actions/runs/41470005932): WebView2, tài khoản/quyền, cài đặt, nâng cấp, shortcut và gỡ giữ dữ liệu/kích hoạt. Quét thực tế sau cài đặt và nâng cấp: **2060 tệp, 1036 mô-đun Python, 165 mục ZIP**, không có phát hiện ngoài ngoại lệ đã cho phép và không có lỗi đọc.
- Tải ZIP công khai không cần đăng nhập, đối chiếu SHA256, CRC và từng tệp với manifest. Giải nén chính EXE tải về bằng innoextract, quét độc lập **2058 tệp, cùng 1036 mô-đun Python và 165 mục ZIP**, kết quả đạt. Bộ giải nén có cảnh báo chuyển mã Windows-1252/UTF-8 như mẫu cũ; chương trình, mã nén và cấu hình đều đọc được, không có lỗi quét. Số tệp trích xuất khác số tệp cài trên Windows; không coi hai cây thư mục là giống nhau hoàn toàn.
- SHA256 chương trình chính trích xuất khớp báo cáo cài đặt Windows: `84e15566c6600889be4488b2428927bdc648661ecacb320abd08e63fdda4c8b0`.
- Xác nhận `legacy_web_accounts` không có trong PYZ; bản cài mới không chứa `_internal/desktop/license-config.json`. Chỉ URL được duyệt trong `desktop.license_identity` được liệt kê là ngoại lệ.
- Nguồn ứng dụng: `5ab04a23d8fa5fd0e954d94d32b7e0c1c4231aae`; phiên bản trong `SOURCE.txt`: **1.0.19**.
- SHA256 EXE bộ cài: `47bb413dbe33ac852c5c744c3bfb39e5ebd4942bbc1831c0f600c2c25577e189`.
- SHA256 ZIP (42842942 byte): `83146e111e6581a1f2ea6bf1b250fc3a640961c60debe89b83b7df075cc4b7f3`.

`PRIVACY-AUDIT.json` trong ZIP gắn kết quả kiểm tra Windows với đúng SHA256 bộ cài. Kiểm tra tìm các chuỗi `viettax`, `du-an-codex` và IP máy chủ cũ, gồm UTF-8/UTF-16, đường dẫn, ZIP và mô-đun Python giải nén. Đây là phạm vi kiểm tra cụ thể, không phải cam kết không thể truy ra chủ sở hữu. URL key và tài khoản GitHub phát hành vẫn được nhận biết theo phạm vi đã thống nhất. Kiểm tra không truy cập VPS thật hoặc đọc dữ liệu riêng trên máy khách; những dữ liệu cũ đó không được xóa khi nâng cấp.

## Mẫu 1.0.18 trước khi sửa

- Nguồn ứng dụng: `bcd5cb298ab438ac487c236ced8f0caaa7af78d5`.
- SHA256 bộ cài EXE: `9ed2c8643537bccbfd521ded4828179fa41906edc3c088d9fdcae3ceee141dbf`.
- SHA256 chương trình cài ra: `4bb0252613dfdfcab588efe0d13c6eaa7cc693c5a0e512622055eb8a11b8b380`.
- Giải nén Inno Setup bằng innoextract 1.13, quét **2059 tệp**, giải nén/đọc **1036 mô-đun Python** trong PYZ và **165 mục** trong ZIP nội bộ. Không chạy mã trong các mô-đun được đọc.
- Quét chuỗi nhận diện ở UTF-8, UTF-16LE/BE, tên đường dẫn và dữ liệu sau giải nén; đọc cấu hình máy chủ từ gói đã cài ra. Giải nén hoàn tất với một cảnh báo chuyển mã tên/metadata Windows-1252 sang UTF-8; các phần chương trình và cấu hình nêu dưới đây đều đọc được.

## Dấu vết xác nhận

| Nơi | Kết quả |
| --- | --- |
| `_internal/desktop/license-config.json` | Có địa chỉ `cskh.viettaxco.com` dưới dạng rõ. |
| `ZaloFlow.exe!desktop.license_identity` | Cùng địa chỉ còn trong bytecode nén; bỏ JSON đơn thuần không giải quyết được. |
| `ZaloFlow.exe!app` | Có email quản trị cũ trong logic chuyển đổi dữ liệu web được đưa vào bản desktop. |
| Nơi phát hành công khai | URL tải hiện dùng tài khoản GitHub `Viettax2026`, nên link tải cũng cho biết chủ sở hữu. |

Hướng dẫn và Publisher hiển thị đã được đổi; điều đó chỉ chứng minh phần giao diện. Tên miền máy chủ còn quan sát được qua kết nối, đúng với ngoại lệ chủ phần mềm đã cho phép. Khóa công khai hiện tại cũng được công khai trong cùng kho mã; đây là thêm một dấu liên hệ giữa các bản đã phát hành. Việc thay khóa ký cho khách đang dùng cần kế hoạch cấp lại key riêng, không được thực hiện như thao tác đổi thương hiệu thông thường.

## Sửa đã đưa vào bản 1.0.19

- Tách chuyển đổi tài khoản web cũ sang `legacy_web_accounts.py`, loại mô-đun đó khỏi bản desktop. Bản web tiếp tục chuyển đổi như trước; desktop giữ nguyên tên/mật khẩu tài khoản cũ.
- Bỏ tệp JSON cấu hình rõ khỏi gói cài mới. Danh tính máy chủ tin cậy vẫn được biên dịch và được kiểm chứng bằng fingerprint trong smoke test; giữ máy chủ hiện tại theo yêu cầu, không yêu cầu tên miền mới.
- `desktop.privacy_audit`: quét tệp, đường dẫn, ZIP và mã Python sau giải nén. Thiếu công cụ/không đọc được mã/tệp đều đánh dấu không đạt.
- Chặn build khi còn dấu vết ngoài URL bản quyền được cho phép; quét sau build và quét lại **các tệp được cài ra thật** trong kiểm tra Windows.
- Bộ đóng gói cần báo cáo kiểm tra đạt, gắn SHA256 đúng bộ cài; thiếu báo cáo hoặc báo cáo không khớp thì dừng.
- Link GitHub dùng tài khoản chủ sở hữu vẫn là kênh phát hành cho chủ phần mềm. Hướng dẫn/giao diện của bản cài không chứa link đó; có thể giao khách trực tiếp file EXE. Một yêu cầu giấu cả kênh phân phối sẽ là phạm vi riêng.

EXE 1.0.18 đã phát hành không bị ghi đè; cần dùng bộ cài 1.0.19 ở trên. Cấu hình vẫn dùng máy chủ đang hoạt động như yêu cầu. Bộ kiểm tra chỉ miễn trừ URL API đã duyệt ở đúng phần bản quyền; một email, link GitHub hoặc dấu vết khác trong cùng mô-đun vẫn làm kiểm tra thất bại.

## Xác nhận bản sửa

Bộ kiểm tra đọc bộ cài 1.0.18 và báo đúng lỗi email trong mô-đun `app` sau khi áp dụng ngoại lệ URL; hai vị trí URL được liệt kê riêng là ngoại lệ được chấp thuận. Bản 1.0.19 đã vượt kiểm tra tệp và mã nén sau build, kiểm tra cài đặt thật trên Windows và đối chiếu checksum sau khi tải lại. Việc giữ địa chỉ máy chủ đồng nghĩa vẫn có thể nhận biết tên miền qua kiểm tra mạng; không tuyên bố ẩn danh tuyệt đối.
