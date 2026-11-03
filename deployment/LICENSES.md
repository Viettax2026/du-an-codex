# Bản quyền ZaloFlow Windows

Key cấp mới dùng trong **một phiên tool tại một thời điểm, không khóa theo máy**. Khi key đang dùng ở tool A, tool B bị chặn, kể cả trên cùng máy. Đóng tool A rồi mới dùng ở B. Chủ phần mềm cấp key, gia hạn, thu hồi hoặc ngắt phiên qua trang quản trị riêng. Key khác với mật khẩu tài khoản ZaloFlow và mật khẩu root VPS.

Tool mới kiểm tra máy chủ khi mở và mỗi **20 giây**, bằng luồng riêng để vẫn gia hạn trong lúc chờ Zalo trả lời. Phiên có chữ ký Ed25519, gắn với mã ngẫu nhiên của lần mở tool, hiệu lực tối đa **60 giây** và không vượt hạn key. Hết phiên, mất kết nối quá 60 giây hoặc máy chủ từ chối thì dừng nhận lượt mới; lượt đã bắt đầu được kết thúc, giữ kết quả/tiến độ/hạn mức. Đóng tool bình thường: dừng nhận lượt, chờ lượt đang xử lý và yêu cầu HTTP xong rồi mới giải phóng phiên; lần mở sau vẫn nhớ kích hoạt. Nếu tắt đột ngột hoặc mất thông báo đóng, phiên dành chỗ tự hết sau tối đa **110 giây** (hướng dẫn khách chờ tối đa 2 phút), gồm khoảng chờ lượt gửi có thể đang xử lý. Khi tool B bị chặn, không tự ngắt tool A.

**Tương thích:** cần cập nhật cả máy chủ và bản Windows. Tool cũ bị từ chối với key theo phiên, không được cấp nhầm phiên 1 giờ. Key đã cấp trước nâng cấp vẫn giữ chế độ theo máy, kiểm tra 5 phút/phiên ngoại tuyến tối đa 1 giờ; không tự chuyển đổi hoặc thu hồi các key này. Danh sách hiển thị rõ chế độ từng key. Đăng xuất tài khoản ZaloFlow hoặc thu nhỏ cửa sổ không giải phóng phiên; đóng tool mới giải phóng. Chuyển key không đồng bộ khách hàng, tài khoản hoặc chiến dịch giữa máy.

## Cài máy chủ trên VPS hiện tại

Trong SSH root của VPS 103.77.172.174:

```bash
cd /opt/zaloflow
git pull --ff-only origin main
bash deployment/install-license-server.sh
```

Script yêu cầu tên miền đã có HTTPS, sao lưu cấu hình trước khi thêm đường dẫn `/licenses/`, tạo dịch vụ riêng `zaloflow-license` trên `127.0.0.1:8010`. Không mở cổng 8010 ra Internet. Script không bật/tắt bộ lịch chiến dịch trên VPS và không sửa database khách hàng. Khi cập nhật dịch vụ key, script sao lưu cả kho bản quyền trước; không tạo lại khóa ký đã có. Nếu Nginx không hợp lệ, cấu hình website được khôi phục và việc cài dịch vụ key dừng lại.

Sau cập nhật, kiểm tra giao thức trên chính VPS trước khi dựng Windows:

```bash
runuser -u zaloflow-license -- .venv/bin/python -m license_system.smoke_sessions
```

Kết quả phải có `"ok": true`. Lệnh dùng authority, key và hồ sơ tool hoàn toàn tạm trong thư mục riêng, tự xóa sau kiểm tra; không đọc/sửa kho key thật, dữ liệu khách hàng hoặc gửi tin Zalo. Kiểm tra tool A chặn B, đóng A cho B vào trên máy khác, hai tool cùng máy vẫn bị chặn, mở lại nhớ key và từ chối tool cũ. Sau đó mở `/licenses/admin` kiểm tra nút **Tạo key — 1 tool** và các key cũ vẫn hiển thị. Xác nhận VPS đạt rồi dựng/cài bản Windows mới và kiểm tra thực tế hai tool. Chỉ cập nhật VPS không thay đổi EXE đã cài.

Mở **https://cskh.viettaxco.com/licenses/admin**. Xem mật khẩu quản trị ban đầu bằng:

```bash
cat /var/lib/zaloflow-licenses/admin-password.txt
```

Chỉ chủ phần mềm giữ mật khẩu này. Khách hàng không có quyền quản trị bằng tài khoản ZaloFlow của họ. Đổi mật khẩu quản trị qua SSH (nhập kín, không đưa mật khẩu vào dòng lệnh):

```bash
cd /opt/zaloflow
runuser -u zaloflow-license -- .venv/bin/python -m license_system.admin set-admin-password
```

Sau khi đổi, các phiên quản trị cũ hết hiệu lực và tệp mật khẩu ban đầu được xóa.

## Cấu hình bản Windows trước khi phát cho khách

Trên VPS, lấy **duy nhất cấu hình công khai** này:

```bash
cat /var/lib/zaloflow-licenses/client-config.json
```

Tệp chỉ có `version`, `server_url`, `public_key`. Có thể gửi nội dung tệp cho người dựng phần mềm hoặc lưu thành `desktop/license-config.json` trong kho mã. **Không gửi `signing-private.pem`, `admin-password.txt`, `session-secret.txt`, database bản quyền hoặc bản sao lưu authority.** Khóa ký chỉ được tạo và lưu trên VPS của chủ phần mềm.

Kiểm thử phiên bản mã trên VPS thành công trước. Sau đó GitHub Actions → **Build Windows desktop → Run workflow**: chọn đúng phiên bản đã thử, đánh dấu `vps_tested`, dán JSON công khai vào trường `license_config` nếu chưa có trong kho mã rồi Run workflow. Có thể commit `desktop/license-config.json` để các lần dựng sau dùng lại, nhưng không tự đóng gói khi push; mỗi lần dựng phải xác nhận bước VPS. Nếu chưa có cấu hình, workflow chỉ kiểm thử gói với danh tính tạm; không xuất bản gói khách hàng. Không dùng khóa thử để cấp key thật.

Khi lượt dựng có dấu xanh và artifact, tải `ZaloFlow-Setup-Windows-x64`, lấy `ZaloFlow-Setup-x64.exe` trong ZIP rồi chạy để cài. Bộ cài tạo biểu tượng Desktop/Start; tệp hỗ trợ được cài vào thư mục chương trình và ẩn mặc định. Chỉ gửi bộ cài cho khách. Ẩn tệp không ngăn được sao chép; key vẫn kiểm soát một phiên tool được sử dụng tại một thời điểm. Gói khách hàng chỉ có khóa công khai; không đóng gói kho key hoặc công cụ quản trị server. Dựng thủ công trên Windows cũng yêu cầu cấu hình công khai hợp lệ trước. Cài đè/gỡ giữ dữ liệu và thông tin kích hoạt. Đóng tool trước khi cài đè/gỡ. Với key theo phiên, chỉ cần đóng tool cũ để dùng key ở tool khác; với key cũ theo máy vẫn cần hủy kích hoạt hoặc quản trị viên reset máy.

## Cấp, gia hạn và chuyển máy

1. Trang quản trị → nhập tên khách hàng và số ngày → **Tạo key — 1 tool**. Hạn tính từ lúc cấp key. Sao chép key và gửi riêng cho khách. Với key cấp từ bản có chức năng xem key, chủ phần mềm bấm **Xem key** trong danh sách để xem lại. Key gốc được lưu mã hóa; mã kiểm tra vẫn dùng để xác thực.
2. Khách cập nhật tool Windows hỗ trợ key theo phiên → **Bản quyền** → nhập key → kích hoạt. Sau đó tạo/đăng nhập tài khoản ZaloFlow và quét QR Zalo như trước. Key mới bị từ chối ở tool cũ; cần dùng bộ cài mới được dựng từ phiên bản này.
3. Gia hạn: chọn key trong trang quản trị → nhập số ngày → **Gia hạn / mở lại key**. Thêm ngày từ hạn hiện tại nếu còn hạn, hoặc từ hiện tại nếu đã hết hạn. Khách bấm **Kiểm tra lại / cập nhật gia hạn**, hoặc chờ lần kiểm tra định kỳ.
4. Chuyển tool/máy: đóng tool cũ hoàn toàn rồi nhập cùng key ở tool mới. Không cần quản trị viên hủy máy. Nếu mở đồng thời, tool mới báo đang có tool khác sử dụng. Sau khi đóng bình thường, có thể dùng ngay; sau mất mạng/tắt đột ngột, chờ tối đa 2 phút. Key cũ theo máy vẫn dùng **Bản quyền → Hủy kích hoạt máy này** trước khi chuyển.
5. Ngắt quyền tool hiện tại: **Thao tác khác → Ngắt phiên đang dùng** hoặc **Thu hồi key**. Tool đang chạy dừng lượt mới ở lần kiểm tra tiếp hoặc khi phiên 60 giây hết hạn. Giữ khoảng chờ lượt đang xử lý trước khi cấp phiên khác, tối đa 2 phút. Với key cũ theo máy, nút vẫn là **Hủy máy để chuyển máy**, phiên ngoại tuyến tối đa 1 giờ như trước.
6. Đổi sang key khác: hủy kích hoạt key hiện tại trước, để không giữ nhầm suất máy của key cũ. Không xóa thư mục dữ liệu hoặc database để đổi key.
7. Xóa key đã thu hồi: tại dòng **Đã thu hồi**, mở **Thao tác khác**, tích **Xác nhận xóa vĩnh viễn key** rồi bấm **Xóa key đã thu hồi**. Hệ thống chỉ cho xóa key đã thu hồi, kể cả khi gửi yêu cầu trực tiếp. Xóa sẽ gỡ key và các kích hoạt khỏi máy chủ, không thể gia hạn/mở lại; key cũ và token kích hoạt cũ không dùng lại được. ID key đã xóa không được cấp lại. Dữ liệu chiến dịch trong tool giữ nguyên; phiên đã ký không thể vô hiệu hóa ngay trên máy mất mạng: key theo phiên tối đa 60 giây, key cũ theo máy tối đa 1 giờ.

Để cập nhật chức năng quản trị key trên VPS hiện tại, chạy lại ba lệnh ở phần **Cài máy chủ trên VPS hiện tại**. Script sao lưu kho key trước khi cập nhật và giữ nguyên khóa ký, mật khẩu cùng các key khác. Riêng thay đổi bố cục/xóa key không cần dựng lại tool. Chế độ key theo phiên cần bộ cài Windows mới; cập nhật và kiểm tra máy chủ trên VPS trước khi đóng gói theo quy trình đã thống nhất.

## Vận hành và khôi phục

```bash
systemctl status zaloflow-license --no-pager
journalctl -u zaloflow-license -n 50 --no-pager
cd /opt/zaloflow
runuser -u zaloflow-license -- .venv/bin/python -m license_system.admin list
```

CLI cũng có `issue --customer TEN --days 30`, `extend ID --days 30`, `revoke ID`, `reset-devices ID`. CLI `issue` mặc định cấp key theo phiên; có thể dùng `--mode device` khi cần key tương thích tool cũ. API Python nội bộ giữ mặc định `device` cho tương thích; các điểm cấp key web/CLI đều chỉ định `floating`. Không gửi key riêng qua kho mã hoặc log công khai.

Sao lưu toàn bộ `/var/lib/zaloflow-licenses` trong lúc riêng dịch vụ key đã dừng; giữ bản sao ở nơi chỉ chủ phần mềm truy cập. Khi khôi phục phải giữ cả database, `signing-private.pem` và `session-secret.txt`. Không chạy `init` lại hoặc tạo khóa ký khác cho bản Windows đã phát. Mất khóa ký cần dựng lại bản khách với khóa công khai mới và cấp lại key.

Nếu cửa sổ key cần cấu hình máy chủ, kiểm tra gói được dựng với đúng `client-config.json`. Nếu xác thực thất bại do thời gian, bật đồng bộ ngày giờ Windows. Nếu key đủ số máy, hủy máy cũ hoặc nhờ chủ phần mềm reset; việc đăng ký tài khoản ZaloFlow mới không tăng số máy được phép.

Giới hạn: cơ chế áp dụng cho bản Windows mới có tích hợp kiểm tra key. Bản cũ chưa có kiểm tra vẫn hoạt động như trước; không thể thêm kiểm tra từ xa cho tệp EXE đã phát. Kho mã hiện công khai, nên đây là quản lý kích hoạt cho bản phân phối của chủ phần mềm, không phải cơ chế chống sửa mã tuyệt đối.

## Cấp tài khoản quản trị tool kèm key

Trên trang `/licenses/admin`, nhập **Khách hàng**; ô **Tên quản trị tool** tự gợi ý dạng **`quantri-tenkhachhang`**, ví dụ “Thảo Như” → `quantri-thaonhu`, “Đặng Đức An” → `quantri-dangducan`. Tên được chuyển sang chữ thường, bỏ dấu và khoảng trắng, tối đa 64 ký tự; tên khách hàng hiển thị vẫn giữ nguyên dấu. Bạn có thể sửa tên gợi ý trước khi bấm **Tạo key — 1 tool**; khi đã sửa riêng, đổi tên khách hàng không ghi đè lựa chọn đó. Để trống vẫn tạo tên theo cùng quy tắc ở máy chủ, kể cả khi trình duyệt không chạy JavaScript. Nếu tên tự tạo đã có trong kho key, hệ thống thêm `-2`, `-3`; tên nhập riêng bị trùng sẽ báo lỗi để chọn lại.

Nhập số ngày rồi tạo key. Hệ thống tạo đủ key, tên quản trị và mật khẩu khởi tạo; xem lại cả bộ tại **Xem key**. Gửi riêng cả ba thông tin cho khách. Có thể cấp nhiều bộ cho các khách hàng khác nhau; kho key lưu hash xác thực và bản mật khẩu khởi tạo mã hóa để chủ phần mềm xem lại. Đây không phải mật khẩu hiện tại nếu khách đã đổi/khôi phục trong tool; việc xem lại không đặt lại mật khẩu local. Quy tắc đặt tên chỉ áp dụng khi cấp quản trị mới, không đổi tên tài khoản/key đã cấp.

Khách cần bản Windows mới hỗ trợ cấp tài khoản từ key. Trong tool: **Bản quyền → nhập key → Kích hoạt**, sau đó đăng nhập bằng tên/mật khẩu đã được cấp. Tài khoản quản trị được tạo từ thông tin có chữ ký của máy chủ. Trang **Quản lý tài khoản → Tạo tài khoản trong tool** cho phép tạo nhiều tài khoản thường, mật khẩu 8–256 ký tự, có thể dùng ngay; email tùy chọn và chưa tự xác minh. Người dùng tự đăng ký với key hợp lệ vẫn dùng ngay như trước, không được tự cấp quyền quản trị.

Quản trị tool chỉ quản lý tài khoản trong hồ sơ tool đó, không được vào trang quản trị kho key trên VPS. Những tài khoản này dùng chung bản quyền của tool, không cần cấp key riêng cho từng tài khoản; giới hạn một phiên tool cho mỗi key vẫn áp dụng. Mỗi tài khoản giữ dữ liệu riêng theo cơ chế hiện có. Tài khoản/dữ liệu không tự đồng bộ sang máy khác. Đăng xuất tài khoản không đóng tool hoặc giải phóng phiên key.

Nếu tên quản trị được cấp đã trùng tài khoản có sẵn, tool không ghi đè mật khẩu hoặc tự nâng quyền. Trong **Bản quyền → Tạo quản trị bằng tên khác**, chọn tên mới chưa dùng (ví dụ `test-key-6`) và nhập mật khẩu khởi tạo đã được cấp cùng key. Tool xác minh mật khẩu với thông tin có chữ ký và tạo một quản trị riêng. Sau đó dùng **tên mới trong tool** và cùng mật khẩu đã cấp để đăng nhập; tên trên máy chủ cấp key vẫn giữ nguyên. Tài khoản cũ, mật khẩu, quyền và dữ liệu cũ được giữ; dữ liệu không chuyển sang quản trị mới. Mỗi key chỉ tạo một quản trị trong hồ sơ đó; không dùng thao tác này để tạo thêm quản trị hoặc đặt lại tài khoản đã được cấp thành công.

Sau khi tạo thành công, việc kiểm tra/gia hạn/mở lại key giữ tên local đã chọn, không đặt lại mật khẩu, không tự khôi phục quyền đã bị thay đổi. Giữ nguyên `instance`, gồm bảng ghi nhận cấp quản trị, khi nâng cấp/chuyển dữ liệu. Để khôi phục mật khẩu cục bộ dùng quy trình khôi phục tài khoản hiện có. Tên `admin` vẫn không được tự đăng ký qua biểu mẫu công khai.

CLI tương ứng: `issue --customer TEN --days 30 --admin-username quantri-tencongty`. Lệnh in bộ thông tin khởi tạo và lưu bản mật khẩu khởi tạo mã hóa; không đưa đầu ra vào log, Git hoặc ảnh chia sẻ công khai. Bộ cài chỉ mang khóa công khai, không đóng gói sẵn tài khoản/mật khẩu của khách. Cần cập nhật và kiểm tra VPS trước khi dựng Windows; lệnh `python -m license_system.smoke_sessions` kiểm tra thêm cấp quản trị và tạo tài khoản bằng dữ liệu tạm, kết quả có `"tool_admin_accounts": true`.

## Xem lại key trong trang quản trị

Tại từng dòng trong **Danh sách key**, bấm **Xem key**. Trang đưa tới khung key được chọn, có ô chỉ đọc để sao chép và **Đóng phần xem key** để ẩn. Chỉ phiên chủ phần mềm đăng nhập mới được xem; thao tác dùng POST và CSRF, không đặt key trong URL hoặc cookie/flash. Trang trả `Cache-Control: no-store`; GET danh sách thông thường không chứa key gốc trong HTML. Không có API xem key cho tool hoặc tài khoản khách hàng.

Key mới được lưu thêm bản mã hóa Fernet; khóa mã hóa được dẫn xuất HKDF-SHA256 với miền riêng từ khóa ký riêng hiện có, không dùng khóa công khai hoặc mật khẩu quản trị. Bản mã được kiểm tra khớp hash key khi đọc. Sao lưu/khôi phục **toàn bộ** `/var/lib/zaloflow-licenses`, gồm database và đúng `signing-private.pem`; không tạo lại khóa ký. Không đưa kho này vào Git hoặc bộ cài. Đổi mật khẩu quản trị không làm mất khả năng xem key.

Key đã cấp trước thay đổi chỉ có hash, không thể khôi phục chuỗi gốc bằng cách nâng cấp. Bấm **Xem key** sẽ hiện thông báo và biểu mẫu **Key gốc đã cấp**. Nếu còn bản đã sao chép, chủ phần mềm nhập lại rồi bấm **Lưu key gốc**; chỉ bản khớp hash của đúng dòng được lưu mã hóa. Không đổi key, hạn dùng, tài khoản quản trị hay kích hoạt. Không nhập key gốc trong chat, dòng lệnh hoặc ảnh công khai. Nếu không còn bản gốc, cần cấp key khác theo nhu cầu; nâng cấp không tự thu hồi hoặc thay key đang dùng.

Đây là thay đổi máy chủ quản trị, không cần cài lại tool Windows. Cập nhật bằng ba lệnh trong phần **Cài máy chủ trên VPS hiện tại**; script sao lưu authority trước khi khởi động schema mới.

## Tự tạo đủ bộ key và quản trị

Biểu mẫu cấp key mặc định gợi ý tên quản trị dạng `quantri-tenkhachhang` và sinh mật khẩu ngẫu nhiên. CLI bỏ trống `--admin-username` hoặc tạo bổ sung cho key chưa có quản trị cũng dùng cùng quy tắc đặt tên. Chủ phần mềm xem lại key, tên quản trị và **mật khẩu khởi tạo** trong **Xem key**. Bản mật khẩu khởi tạo được mã hóa bằng vault của authority, kiểm tra khớp hash khi đọc; không gửi chuỗi mật khẩu hoặc bản mã trong lease cho tool. Tool chỉ nhận username/hash có chữ ký như giao thức trước. Mật khẩu đã đổi/khôi phục trong tool giữ nguyên.

Thay đổi gợi ý tên chỉ cần cập nhật máy chủ bằng các lệnh ở phần **Cài máy chủ trên VPS hiện tại** rồi tải lại trang quản trị. Bản tool Windows đã hỗ trợ quản trị kèm key tiếp tục nhận tên mới theo cùng giao thức; không cần dựng lại bộ cài cho thay đổi này. Máy chủ chỉ kiểm tra trùng với các tên còn lưu trong kho key; tài khoản cũ trên từng máy vẫn được giữ nguyên và dùng cách xử lý trùng tên trong tool nếu cần.

Với key theo phiên đã cấp nhưng chưa có quản trị, bấm **Xem key → Tạo tài khoản và mật khẩu quản trị**. Thao tác chỉ bổ sung lần đầu cho key còn hiệu lực; không đổi key, hạn dùng, lượt kích hoạt hoặc tài khoản cũ. Bấm lại không tạo lại hoặc đặt lại mật khẩu. Key đã có quản trị nhưng chỉ còn hash mật khẩu từ bản cũ không thể tự khôi phục mật khẩu; dùng mật khẩu đã giao hoặc quy trình khôi phục local. Khách đóng/mở tool để nhận tài khoản được bổ sung; bản mới cũng đồng bộ khi bấm **Kiểm tra lại**.

Bản Windows dùng nhận diện hiển thị ZaloFlow: nhà phát hành, màn hình cài đặt và hướng dẫn khách hàng không hiển thị tên công ty, tên miền quản trị hoặc đường dẫn kho mã của chủ phần mềm. Cấu hình máy chủ kiểm tra key và khóa công khai vẫn được giữ để kiểm tra bản quyền; thay đổi nhận diện không vô hiệu hóa cấp phép.
