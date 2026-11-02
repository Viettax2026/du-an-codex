# Kiểm tra dấu vết chủ phần mềm — ZaloFlow 1.0.19

Ngày kiểm tra: 02/11/2026. Đây là kiểm tra **bộ cài đã phát hành**, không chỉ mã nguồn hoặc ảnh giao diện.

## Kết luận

Bản **1.0.19 đã phát hành và được tải lại để kiểm tra độc lập**. Không phát hiện các chuỗi nhận diện đã kiểm tra ngoài URL máy chủ key được phép giữ. Email quản trị cũ đã được loại khỏi mã nén desktop. **Chủ phần mềm đã xác nhận giữ địa chỉ máy chủ kiểm tra key hiện tại**: địa chỉ này là ngoại lệ được phép trong cấu hình và mô-đun nhận diện bản quyền, không phải trong hướng dẫn hoặc giao diện thông thường. Phạm vi sửa là loại các dấu vết khác, không phải ẩn toàn bộ nguồn gốc máy chủ.

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
