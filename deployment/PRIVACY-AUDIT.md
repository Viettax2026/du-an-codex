# Kiểm tra dấu vết chủ phần mềm — ZaloFlow 1.0.18

Ngày kiểm tra: 02/11/2026. Đây là kiểm tra **bộ cài đã phát hành**, không chỉ mã nguồn hoặc ảnh giao diện.

## Kết luận

Bản 1.0.18 đã đổi nội dung cài đặt/hướng dẫn sang ZaloFlow nhưng vẫn còn email quản trị cũ trong mã nén. **Chủ phần mềm đã xác nhận giữ địa chỉ máy chủ kiểm tra key hiện tại**: địa chỉ này là ngoại lệ được phép trong cấu hình và mô-đun nhận diện bản quyền, không phải trong hướng dẫn hoặc giao diện thông thường. Phạm vi sửa là loại các dấu vết khác, không phải ẩn toàn bộ nguồn gốc máy chủ.

## Mẫu và cách kiểm tra

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

## Sửa đã chuẩn bị trong mã nguồn

- Tách chuyển đổi tài khoản web cũ sang `legacy_web_accounts.py`, loại mô-đun đó khỏi bản desktop. Bản web tiếp tục chuyển đổi như trước; desktop giữ nguyên tên/mật khẩu tài khoản cũ.
- Bỏ tệp JSON cấu hình rõ khỏi gói cài. Danh tính máy chủ tin cậy vẫn được biên dịch và được kiểm chứng bằng fingerprint trong smoke test; vẫn cần tên miền trung lập trong cấu hình trước khi biên dịch.
- `desktop.privacy_audit`: quét tệp, đường dẫn, ZIP và mã Python sau giải nén. Thiếu công cụ/không đọc được mã/tệp đều đánh dấu không đạt.
- Chặn build khi còn dấu vết ngoài URL bản quyền được cho phép; quét sau build và quét lại **các tệp được cài ra thật** trong kiểm tra Windows.
- Bộ đóng gói cần báo cáo kiểm tra đạt, gắn SHA256 đúng bộ cài; thiếu báo cáo hoặc báo cáo không khớp thì dừng.
- Link GitHub dùng tài khoản chủ sở hữu vẫn là kênh phát hành cho chủ phần mềm. Hướng dẫn/giao diện của bản cài không chứa link đó; có thể giao khách trực tiếp file EXE. Một yêu cầu giấu cả kênh phân phối sẽ là phạm vi riêng.

Những sửa này chưa làm thay đổi EXE 1.0.18 đã phát hành. Cấu hình vẫn dùng máy chủ đang hoạt động như yêu cầu. Bộ kiểm tra chỉ miễn trừ URL API đã duyệt ở đúng phần bản quyền; một email, link GitHub hoặc dấu vết khác trong cùng mô-đun vẫn làm kiểm tra thất bại.

## Xác nhận bản sửa

Bộ kiểm tra đã đọc bộ cài 1.0.18 và báo đúng lỗi email trong mô-đun `app` sau khi áp dụng ngoại lệ URL; hai vị trí URL được liệt kê riêng là ngoại lệ được chấp thuận. Bản sửa phải vượt kiểm tra tệp và mã nén sau build, kiểm tra cài đặt thật trên Windows và đối chiếu checksum trước khi giao. Việc giữ địa chỉ máy chủ đồng nghĩa vẫn có thể nhận biết tên miền qua kiểm tra mạng; không tuyên bố ẩn danh tuyệt đối.
