"""Publish a checked native installer for the owner's 1 November tool release."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

APP_COMMIT = 'ac4e5fb3c177dc46df5ea4d33a21131a43fdb98b'
TAG = 'windows-tool-admin-20261101'
ZIP_NAME = 'ZaloFlow-Tool-Windows-2026-11-01.zip'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def assemble(installer_dir, output):
    installer_dir, output = Path(installer_dir), Path(output)
    exe = installer_dir/'ZaloFlow-Setup-x64.exe'
    checksum = Path(str(exe)+'.sha256')
    expected = checksum.read_text().split()[0]
    if not re.fullmatch(r'[a-fA-F0-9]{64}', expected) or digest(exe) != expected.lower():
        raise ValueError('Installer checksum mismatch')
    with exe.open('rb') as stream:
        if stream.read(2) != b'MZ':
            raise ValueError('Not a Windows installer')
    source = installer_dir/'SOURCE.txt'
    if 'Application source: '+APP_COMMIT not in source.read_text(encoding='utf-8-sig'):
        raise ValueError('Installer source does not match the approved application')
    output.mkdir(parents=True, exist_ok=True)
    for path in (exe, checksum, source):
        shutil.copyfile(path, output/path.name)
    guide = '''ZALOFLOW WINDOWS — KEY MỘT PHIÊN TOOL VÀ TÀI KHOẢN QUẢN TRỊ — 01/11/2026

1. CÀI ĐẶT
Đóng tool cũ hoàn toàn. Chạy ZaloFlow-Setup-x64.exe và cài đè trong cùng tài khoản Windows.
Dữ liệu và thông tin kích hoạt được giữ ở %LOCALAPPDATA%\\ZaloFlow. Không xóa thư mục này.
Bộ cài tạo icon Desktop và Start. Mở tool mới chạy chiến dịch; đóng thì dừng nhận lượt mới,
chờ lượt đang xử lý hoàn tất. Thu nhỏ cửa sổ vẫn chạy. Windows 10/11 x64, cần WebView2.

2. KEY MỘT PHIÊN TOOL
Key cấp mới dùng trong một tool tại một thời điểm, trên bất kỳ máy nào.
Khi tool A đang dùng key, tool B bị chặn, kể cả hai tool trên cùng máy. Đóng A rồi dùng ở B.
Nếu tắt đột ngột hoặc mất kết nối lúc đóng, chờ tối đa 2 phút rồi thử lại.
Cần mạng khi mở và kiểm tra mỗi 20 giây. Nếu mất kết nối quá 1 phút, dừng nhận lượt mới;
giữ nguyên dữ liệu và tiến độ. Key cũ theo máy vẫn giữ chế độ cũ.
Chuyển key không tự chuyển tài khoản/khách hàng/chiến dịch sang máy khác.

3. TÀI KHOẢN QUẢN TRỊ KÈM KEY
Chủ phần mềm vào https://cskh.viettaxco.com/licenses/admin, nhập thêm tên quản trị tool
khi tạo key. Lưu và gửi riêng tên đăng nhập, mật khẩu khởi tạo (chỉ hiện một lần) và key.
Khách vào Bản quyền để kích hoạt key trước, rồi đăng nhập bằng tài khoản đã được cấp.
Quản lý tài khoản > Tạo tài khoản trong tool: tạo nhiều tài khoản thường, dùng ngay,
mật khẩu ít nhất 8 ký tự, không cần key riêng cho từng tài khoản.
Mỗi tài khoản có dữ liệu riêng trong cùng tool. Người dùng thường không có quyền quản trị.
Quản trị tool không có quyền quản trị kho key trên VPS. Nếu tên đã trùng tài khoản cũ,
tool không ghi đè mật khẩu hoặc tự nâng quyền; liên hệ người cấp key.
Gia hạn/mở lại tool không đặt lại mật khẩu đã khôi phục hoặc quyền đã bị thay đổi.

4. CẬP NHẬT MÁY CHỦ KEY
Cơ chế mới cần máy chủ key và bộ cài Windows cùng hỗ trợ. Trên SSH root của VPS hiện tại:
cd /opt/zaloflow
git pull --ff-only origin main
bash deployment/install-license-server.sh
runuser -u zaloflow-license -- .venv/bin/python -m license_system.smoke_sessions
Kết quả cần có "ok": true và "tool_admin_accounts": true. Lệnh chỉ dùng dữ liệu tạm;
không sửa kho key thật hoặc gửi tin Zalo. Script cài đặt sao lưu kho key trước khi nâng cấp.
Tại thời điểm đóng gói chưa nhận kết quả kiểm tra VPS thật từ chủ phần mềm. Bản này được
đóng gói theo yêu cầu trực tiếp ngày 01/11/2026; đã có kiểm thử tự động và bộ cài Windows.

5. DỮ LIỆU RIÊNG
Bộ cài không chứa tài khoản/mật khẩu khách hàng, Gmail, phiên Zalo hoặc khóa ký riêng.
Windows và web có tài khoản/dữ liệu riêng; Gmail cấu hình trên VPS không tự áp dụng cho Windows.
Sao lưu instance riêng nếu cần chuyển dữ liệu. Không chạy cùng chiến dịch ở cả VPS và tool.
Tệp SOURCE.txt ghi đúng mã nguồn, phiên bản; .sha256 và RELEASE-MANIFEST.json để đối chiếu bản tải.
'''
    (output/'HUONG-DAN.txt').write_text(guide, encoding='utf-8')
    names = ['ZaloFlow-Setup-x64.exe','ZaloFlow-Setup-x64.exe.sha256','SOURCE.txt','HUONG-DAN.txt']
    manifest = dict(source_commit=APP_COMMIT, release_tag=TAG, owner_requested_packaging=True,
                    vps_live_test_confirmed=False, floating_license=True, tool_admin_accounts=True,
                    includes_customer_credentials=False, includes_private_authority=False,
                    files={name:digest(output/name) for name in names})
    (output/'RELEASE-MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    archive_path = output/ZIP_NAME
    with zipfile.ZipFile(archive_path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
        for name in (*names,'RELEASE-MANIFEST.json'):
            archive.write(output/name,'ZaloFlow-2026-11-01/'+name)
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError('Tool archive failed integrity check')
    (output/(ZIP_NAME+'.sha256')).write_text(digest(archive_path)+'  '+ZIP_NAME+'\n',encoding='ascii')
    notes = f'''Mã nguồn ứng dụng: `{APP_COMMIT}`.

- Tải `ZaloFlow-Setup-x64.exe` để cài trực tiếp hoặc `{ZIP_NAME}` kèm hướng dẫn.
- Key mới: một phiên tool tại một thời điểm, không khóa máy. Tool B bị chặn khi A còn mở; đóng A để chuyển. Tắt đột ngột chờ tối đa 2 phút.
- Cấp key kèm quản trị tool, sau đó quản trị tạo nhiều tài khoản thường trong cùng tool. Mật khẩu khởi tạo chỉ hiện một lần ở trang cấp key.
- Đóng tool cũ rồi cài đè trong cùng tài khoản Windows; giữ dữ liệu, tiến độ và kích hoạt. Key cũ giữ chế độ cũ; web và Windows độc lập.
- Cần cập nhật máy chủ key theo `HUONG-DAN.txt`. Chưa có kết quả xác nhận kiểm tra VPS thật từ chủ phần mềm; đóng gói theo yêu cầu trực tiếp ngày 01/11/2026.
- Không đóng gói dữ liệu khách hàng, mật khẩu SMTP, phiên Zalo hoặc khóa ký riêng. SHA256/SOURCE/manifest để kiểm tra đúng bản.
'''
    (output/'RELEASE-NOTES.md').write_text(notes,encoding='utf-8')
    return manifest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--installer-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    manifest=assemble(args.installer_dir,args.output)
    print(json.dumps(dict(source_commit=manifest['source_commit'],release_tag=TAG,zip=ZIP_NAME)))


if __name__=='__main__':
    main()
