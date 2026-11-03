"""Publish a checked native installer for the owner's 3 November tool release."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

APP_COMMIT = '889383fa0f780fefe3884d904bb06a2bc044183b'
TAG = 'windows-tool-customer-admin-20261103'
ZIP_NAME = 'ZaloFlow-Tool-Windows-2026-11-03.zip'
ARCHIVE_ROOT = 'ZaloFlow-2026-11-03/'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def assemble(installer_dir, output, customer_guide, audit_report):
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
    audit = json.loads(Path(audit_report).read_text(encoding='utf-8-sig'))
    if (audit.get('passed') is not True or audit.get('findings') or audit.get('errors')
            or audit.get('modules_scanned',0)<1 or audit.get('files_scanned',0)<1
            or audit.get('installer_sha256')!=digest(exe)):
        raise ValueError('Missing or failed inspection of the actual installed customer files')
    output.mkdir(parents=True, exist_ok=True)
    for path in (exe, checksum, source):
        shutil.copyfile(path, output/path.name)
    guide = Path(customer_guide).read_text(encoding='utf-8')
    if re.search(r'Viettax|du-an-codex|cskh\.',guide,re.IGNORECASE):
        raise ValueError('Customer guide contains owner branding')
    (output/'HUONG-DAN.txt').write_text(guide, encoding='utf-8')
    (output/'PRIVACY-AUDIT.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    names = ['ZaloFlow-Setup-x64.exe','ZaloFlow-Setup-x64.exe.sha256','SOURCE.txt','HUONG-DAN.txt','PRIVACY-AUDIT.json']
    manifest = dict(source_commit=APP_COMMIT, release_tag=TAG, owner_requested_packaging=True,
                    vps_live_test_confirmed=False, floating_license=True, tool_admin_accounts=True,
                    neutral_branding=True, automatic_admin_credentials=True, admin_name_conflict_resolved=True,
                    installed_artifact_privacy_checked=True,
                    customer_admin_naming_requires_server_update=True,
                    approved_license_endpoint_retained=bool(audit.get('accepted_exceptions')),
                    includes_customer_credentials=False, includes_private_authority=False,
                    files={name:digest(output/name) for name in names})
    (output/'RELEASE-MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    archive_path = output/ZIP_NAME
    with zipfile.ZipFile(archive_path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
        for name in (*names,'RELEASE-MANIFEST.json'):
            archive.write(output/name,ARCHIVE_ROOT+name)
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError('Tool archive failed integrity check')
    (output/(ZIP_NAME+'.sha256')).write_text(digest(archive_path)+'  '+ZIP_NAME+'\n',encoding='ascii')
    notes = f'''Mã nguồn ứng dụng: `{APP_COMMIT}`.

- Tải `ZaloFlow-Setup-x64.exe` để cài trực tiếp hoặc `{ZIP_NAME}` kèm hướng dẫn.
- Đã kiểm tra cả tệp cài ra, ZIP nội bộ và mô-đun Python trong file chạy; kết quả đi kèm trong `PRIVACY-AUDIT.json`. Loại email quản trị web cũ khỏi bản desktop và bỏ cấu hình JSON rõ.
- Giữ địa chỉ máy chủ kiểm tra key hiện tại theo yêu cầu chủ phần mềm; chỉ URL đó ở phần bản quyền là ngoại lệ. Không tuyên bố giấu danh tính máy chủ hoặc tài khoản kênh phát hành GitHub.
- Sửa lỗi đăng nhập khi tên quản trị được cấp đã có trong tool: vào Bản quyền > Tạo quản trị bằng tên khác, chọn tên mới và xác nhận mật khẩu khởi tạo. Đăng nhập bằng tên mới và cùng mật khẩu được cấp. Giữ nguyên tài khoản, mật khẩu và dữ liệu cũ; không chuyển dữ liệu giữa tài khoản. Dùng lại key hiện tại, không cần cấp key mới.
- Máy chủ mới gợi ý tên quản trị theo khách hàng: “Thảo Như” → `quantri-thaonhu`, cho phép sửa trước khi cấp key. Tên tự tạo bị trùng thêm -2, -3; tên nhập riêng trùng báo lỗi. Cần cập nhật VPS để trang quản trị có thay đổi này; cài tool Windows không tự cập nhật VPS.
- Máy chủ bản quyền mới tự cấp đủ key, tài khoản và mật khẩu quản trị; hỗ trợ bổ sung quản trị cho key chưa có. Khách cần máy chủ đã cập nhật để dùng chức năng này.
- Key mới dùng một phiên tool tại một thời điểm, trên bất kỳ máy nào. Đóng tool cũ trước khi dùng ở tool khác; tắt đột ngột chờ tối đa 2 phút.
- Đóng tool cũ rồi cài đè trong cùng tài khoản Windows; giữ dữ liệu, tiến độ và kích hoạt. Mở lại/gia hạn không đặt lại mật khẩu đã khôi phục.
- Chưa có kết quả xác nhận kiểm tra VPS thật từ chủ phần mềm; đóng gói theo yêu cầu trực tiếp ngày 03/11/2026, có kiểm thử Windows và bộ cài.
- Không chứa dữ liệu hoặc mật khẩu khách hàng, phiên Zalo, mật khẩu SMTP hay khóa ký riêng. SHA256/SOURCE/manifest dùng để đối chiếu bản tải.
'''
    (output/'RELEASE-NOTES.md').write_text(notes,encoding='utf-8')
    return manifest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--installer-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--customer-guide',type=Path,required=True)
    parser.add_argument('--audit-report',type=Path,required=True)
    args=parser.parse_args()
    manifest=assemble(args.installer_dir,args.output,args.customer_guide,args.audit_report)
    print(json.dumps(dict(source_commit=manifest['source_commit'],release_tag=TAG,zip=ZIP_NAME)))


if __name__=='__main__':
    main()
