"""Combine the checked Windows installer and matching public source backup."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

APP_COMMIT = '73f38a058680535486990dfcc1a4890ae4e2726e'
CODE_NAME = 'ZaloFlow-toan-bo-code-va-cai-VPS-2026-10-30.zip'
FULL_NAME = 'ZaloFlow-code-web-va-tool-Windows-2026-10-30.zip'
TAG = 'windows-owner-package-20261030-r2'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check_hash(path):
    expected = Path(str(path) + '.sha256').read_text().split()[0]
    if not re.fullmatch(r'[a-fA-F0-9]{64}', expected) or digest(path) != expected.lower():
        raise ValueError('Checksum mismatch: ' + path.name)


def assemble(code, installer_dir, output):
    code, installer_dir, output = Path(code), Path(installer_dir), Path(output)
    check_hash(code)
    installer = installer_dir / 'ZaloFlow-Setup-x64.exe'
    check_hash(installer)
    with installer.open('rb') as stream:
        if stream.read(2) != b'MZ':
            raise ValueError('Not a Windows executable')
    source = installer_dir / 'SOURCE.txt'
    source_text = source.read_text(encoding='utf-8-sig')
    if 'Application source: ' + APP_COMMIT not in source_text:
        raise ValueError('Installer source does not match the release')
    with zipfile.ZipFile(code) as archive:
        if archive.testzip() is not None:
            raise ValueError('Invalid code archive')
        backup = json.loads(archive.read('ZaloFlow-backup/BACKUP-MANIFEST.json'))
        if backup['source_commit'] != APP_COMMIT or backup['includes_live_customer_data'] or backup['includes_private_authority'] or backup['includes_smtp_credentials']:
            raise ValueError('Wrong source revision or private data in code archive')
        for name, checksum in backup['files'].items():
            if hashlib.sha256(archive.read('ZaloFlow-backup/' + name)).hexdigest() != checksum:
                raise ValueError('Code archive content checksum mismatch')
    output.mkdir(parents=True, exist_ok=True)
    for path in (code, Path(str(code)+'.sha256'), installer, Path(str(installer)+'.sha256'), source):
        shutil.copyfile(path, output/path.name)
    guide = '''ZALOFLOW — MÃ NGUỒN, BỘ CÀI VPS VÀ TOOL WINDOWS — 30/10/2026

1. TOOL WINDOWS
Đóng ZaloFlow hoàn toàn rồi chạy ZaloFlow-Setup-x64.exe để cài đè bằng cùng tài khoản Windows.
Bộ cài tạo biểu tượng Desktop. Dữ liệu và kích hoạt được giữ tại %LOCALAPPDATA%\\ZaloFlow.
Kích hoạt key hợp lệ rồi tự tạo tài khoản và đăng nhập ngay, không cần duyệt; mật khẩu tối thiểu 8 ký tự.
Tài khoản cũ còn chờ duyệt: đăng nhập bằng mật khẩu của tài khoản đó khi key hợp lệ.
Mở tool mới chạy chiến dịch; đóng tool thì dừng. Bản web vẫn yêu cầu duyệt đăng ký.

2. TOÀN BỘ MÃ NGUỒN VÀ CÀI VPS MỚI
Giải nén ZaloFlow-toan-bo-code-va-cai-VPS-2026-10-30.zip rồi đọc ZaloFlow-backup/HUONG-DAN.txt.
Trong đó có zaloflow-source.zip (web, tool, bộ kết nối, máy chủ key và tài liệu) và zaloflow-web.zip (cài Ubuntu 24.04/domain mới).
Không chạy script cài VPS mới để ghi đè website đang dùng. Bản Windows và web có dữ liệu/tài khoản riêng.

3. GỬI PDF
Bản này có sửa bước nhận xác nhận tải PDF/MP4 của Zalo. Đã có kiểm thử bằng SDK thật với HTTP/WebSocket giả lập.
Chưa có kết quả xác nhận nhận PDF trên Zalo thật do chủ ứng dụng cung cấp; gói được phát hành theo yêu cầu đóng gói ngày 30/10/2026.
Hãy thử một lượt mới tới tài khoản bạn kiểm soát, kiểm tra nhận và mở được PDF. Các lượt cũ không tự gửi lại.

4. DỮ LIỆU VÀ BẢN QUYỀN
Gói không chứa dữ liệu khách hàng, phiên Zalo, mật khẩu Gmail hay kho key/khóa ký riêng trên VPS.
Muốn chuyển cả công việc cũ, sao lưu riêng instance; máy chủ cấp key cần sao lưu riêng /var/lib/zaloflow-licenses.
Cấu hình Gmail trên VPS không tự áp dụng cho bản Windows. Hướng dẫn sao lưu/khôi phục nằm trong gói mã nguồn.
Các tệp .sha256 dùng để kiểm tra tải về. SOURCE.txt ghi đúng mã nguồn và phiên bản của bộ cài.
'''
    (output/'HUONG-DAN.txt').write_text(guide, encoding='utf-8')
    assets = [path for path in output.iterdir() if path.is_file() and path.name not in (FULL_NAME, FULL_NAME+'.sha256', 'RELEASE-MANIFEST.json', 'RELEASE-NOTES.md')]
    manifest = dict(source_commit=APP_COMMIT, release_tag=TAG, pdf_live_delivery_confirmed=False,
                    includes_live_customer_data=False, files={path.name:digest(path) for path in sorted(assets)})
    (output/'RELEASE-MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    combined = output/FULL_NAME
    with zipfile.ZipFile(combined, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
        for path in (*sorted(assets), output/'RELEASE-MANIFEST.json'):
            archive.write(path, 'ZaloFlow-2026-10-30/'+path.name)
    with zipfile.ZipFile(combined) as archive:
        if archive.testzip() is not None:
            raise ValueError('Combined archive failed integrity check')
    (output/(FULL_NAME+'.sha256')).write_text(digest(combined)+'  '+FULL_NAME+'\n', encoding='ascii')
    notes = f'''Mã nguồn ứng dụng: `{APP_COMMIT}`.

- Tải `{FULL_NAME}` để lấy bộ cài Windows, toàn bộ mã nguồn, bộ cài VPS và hướng dẫn trong một ZIP.
- Hoặc tải riêng `ZaloFlow-Setup-x64.exe` và `{CODE_NAME}`.
- Windows: kích hoạt key hợp lệ rồi tự đăng ký, không cần duyệt; mật khẩu tối thiểu 8 ký tự. Bản web vẫn yêu cầu duyệt.
- Có bản sửa gửi PDF/MP4. Đã kiểm thử SDK và bộ cài; chưa có xác nhận nhận PDF trên Zalo thật từ chủ ứng dụng.
- Không chứa dữ liệu khách hàng, phiên Zalo, mật khẩu SMTP hoặc khóa ký riêng. Sao lưu dữ liệu vận hành riêng theo hướng dẫn.

Đóng gói theo yêu cầu trực tiếp ngày 30/10/2026. Các tệp SHA256 và `SOURCE.txt` dùng để đối chiếu bản tải về.
'''
    (output/'RELEASE-NOTES.md').write_text(notes, encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workflow-ref', required=True)
    parser.add_argument('--installer-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-f0-9]{40}', args.workflow_ref):
        parser.error('workflow-ref must be a full commit hash')
    staging = args.output.parent/'zaloflow-public-source-staging'
    staging.mkdir(parents=True, exist_ok=True)
    for name in (CODE_NAME, CODE_NAME+'.sha256'):
        data = subprocess.check_output(['git','show',args.workflow_ref+':downloads/'+name])
        (staging/name).write_bytes(data)
    manifest = assemble(staging/CODE_NAME, args.installer_dir, args.output)
    print(json.dumps(dict(source_commit=manifest['source_commit'], release_tag=TAG, files=sorted(path.name for path in args.output.iterdir() if path.is_file()))))


if __name__ == '__main__':
    main()
