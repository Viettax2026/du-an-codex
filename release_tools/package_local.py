"""Assemble only the strictly audited owner-authorized local Windows edition."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

TAG='windows-local-20261103-r2'
ZIP_NAME='ZaloFlow-Local-Windows-2026-11-03.zip'
ARCHIVE_ROOT='ZaloFlow-Local/'


def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def assemble(installer_dir,output,customer_guide,audit_report,source_commit):
    if not re.fullmatch(r'[a-f0-9]{40}',source_commit):raise ValueError('Expected an exact source commit')
    folder,output=Path(installer_dir),Path(output)
    exe=folder/'ZaloFlow-Local-Setup-x64.exe'
    checksum=Path(str(exe)+'.sha256');source=folder/'SOURCE.txt'
    expected=checksum.read_text().split()[0]
    if not re.fullmatch(r'[a-fA-F0-9]{64}',expected) or digest(exe)!=expected.lower():
        raise ValueError('Installer checksum mismatch')
    with exe.open('rb') as stream:
        if stream.read(2)!=b'MZ':raise ValueError('Not a Windows installer')
    provenance=source.read_text(encoding='utf-8-sig')
    if 'Application source: '+source_commit not in provenance or 'Edition: local' not in provenance:
        raise ValueError('Installer source or edition mismatch')
    audit=json.loads(Path(audit_report).read_text(encoding='utf-8-sig'))
    if (audit.get('passed') is not True or audit.get('strict') is not True or audit.get('accepted_exceptions')
            or audit.get('licensing_modules')!=[] or audit.get('errors') or audit.get('findings')
            or audit.get('files_scanned',0)<1 or audit.get('modules_scanned',0)<1
            or audit.get('installer_sha256')!=digest(exe)):
        raise ValueError('Missing or failed strict inspection of actual installed files')
    guide=Path(customer_guide).read_text(encoding='utf-8')
    if (re.search(r'Viettax|du-an-codex|cskh\.',guide,re.IGNORECASE)
            or 'ZALOFLOW LOCAL' not in guide or 'không yêu cầu key' not in guide):
        raise ValueError('Incorrect local customer guide')
    output.mkdir(parents=True,exist_ok=True)
    for path in (exe,checksum,source):shutil.copyfile(path,output/path.name)
    (output/'HUONG-DAN.txt').write_text(guide,encoding='utf-8')
    (output/'PRIVACY-AUDIT.json').write_text(json.dumps(audit,indent=2)+'\n',encoding='utf-8')
    names=[exe.name,checksum.name,source.name,'HUONG-DAN.txt','PRIVACY-AUDIT.json']
    manifest=dict(source_commit=source_commit,release_tag=TAG,owner_requested_packaging=True,
        edition='local',requires_key=False,license_endpoint_included=False,strict_privacy_checked=True,
        data_directory='ZaloFlowLocal',first_account_admin=True,includes_customer_credentials=False,
        includes_private_authority=False,vps_live_test_confirmed=False,
        files={name:digest(output/name) for name in names})
    (output/'RELEASE-MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    archive_path=output/ZIP_NAME
    with zipfile.ZipFile(archive_path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
        for name in (*names,'RELEASE-MANIFEST.json'):archive.write(output/name,ARCHIVE_ROOT+name)
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:raise ValueError('Local archive failed integrity check')
    (output/(ZIP_NAME+'.sha256')).write_text(digest(archive_path)+'  '+ZIP_NAME+'\n',encoding='ascii')
    notes=f'''Mã nguồn ứng dụng: `{source_commit}`.

- Bản ZaloFlow Local độc lập theo yêu cầu chủ phần mềm ngày 03/11/2026. Không yêu cầu key; không chứa mô-đun hoặc địa chỉ kiểm tra bản quyền.
- Tải `ZaloFlow-Local-Setup-x64.exe` hoặc `{ZIP_NAME}` kèm hướng dẫn và báo cáo kiểm tra.
- Tự đăng ký khi mở lần đầu; tài khoản đầu tiên là quản trị. Có thể tạo thêm người dùng trong cùng tool. Dữ liệu riêng cho từng tài khoản.
- Cài riêng tại `%LOCALAPPDATA%\\Programs\\ZaloFlowLocal`; dữ liệu `%LOCALAPPDATA%\\ZaloFlowLocal`. Không tự nhập hoặc thay dữ liệu của bản khác.
- Không chứa tài khoản, mật khẩu SMTP, phiên Zalo hay dữ liệu khách hàng. Quét tệp và mã nén không cho phép ngoại lệ địa chỉ máy chủ.
- Đã kiểm tra Windows, WebView2, tài khoản/khôi phục, bộ lịch, cài đè và gỡ giữ dữ liệu. Không đánh dấu là đã thử gửi Zalo thật hoặc kiểm tra VPS thật.
- Gửi và đăng nhập Zalo vẫn cần Internet; đóng cửa sổ hoặc tắt máy thì không chạy lịch.
'''
    (output/'RELEASE-NOTES.md').write_text(notes,encoding='utf-8')
    return manifest


def main():
    parser=argparse.ArgumentParser()
    for flag in ('installer-dir','output','customer-guide','audit-report'):
        parser.add_argument('--'+flag,type=Path,required=True)
    parser.add_argument('--source-commit',required=True)
    args=parser.parse_args()
    manifest=assemble(args.installer_dir,args.output,args.customer_guide,args.audit_report,args.source_commit)
    print(json.dumps(dict(source_commit=manifest['source_commit'],release_tag=TAG,zip=ZIP_NAME)))


if __name__=='__main__':main()
