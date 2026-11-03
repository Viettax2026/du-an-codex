"""Build-time owner-identity audit, including compressed Python modules.

Never imported by the customer runtime. Findings contain locations and marker
names only, never arbitrary surrounding content or customer credentials.
"""
import argparse
import base64
import hashlib
import json
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

MARKERS = ('viettax', 'du-an-codex', '103.77.172.174')
# Explicit owner instruction, 02/11/2026: keep the existing licensing address.
APPROVED_LICENSE_URL = 'https://cskh.viettaxco.com/licenses'
OVERLAP = 128


def matches(data):
    data = data.lower()
    return {marker for marker in MARKERS if any(marker.encode(encoding) in data
            for encoding in ('utf-8','utf-16le','utf-16be'))}


def file_matches(path):
    found=set();previous=b''
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024):
            data=previous+chunk;found.update(matches(data));previous=data[-OVERLAP:]
    return found


def audit_config(path, *, strict=False):
    result=dict(passed=False,findings=[],errors=[],accepted_exceptions=[])
    try:
        data=json.loads(Path(path).read_text(encoding='utf-8'))
        if set(data)!={'version','server_url','public_key'} or data['version']!=1:
            raise ValueError()
        url=urlsplit(data['server_url'])
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError()
        if len(base64.urlsafe_b64decode(data['public_key']+'='*(-len(data['public_key'])%4)))!=32:
            raise ValueError()
        inspected=dict(data)
        if not strict and data['server_url'].rstrip('/')==APPROVED_LICENSE_URL:
            inspected['server_url']='approved-license-endpoint'
            result['accepted_exceptions'].append(dict(location='server configuration',exception='owner-approved license endpoint'))
        for marker in matches(json.dumps(inspected).encode()):
            result['findings'].append(dict(scope='public-license-config',location='server configuration',marker=marker))
    except (OSError,ValueError,TypeError,KeyError):
        result['errors'].append('Invalid public license configuration')
    result['passed']=not result['findings'] and not result['errors']
    return result


def audit_tree(root, *, strict=False):
    root=Path(root)
    result=dict(passed=False,strict=strict,files_scanned=0,modules_scanned=0,zip_members_scanned=0,findings=[],errors=[],accepted_exceptions=[],licensing_modules=[])
    seen=set()
    def record(scope,location,markers):
        for marker in markers:
            item=(scope,location,marker)
            if item not in seen:
                seen.add(item)
                result['findings'].append(dict(scope=scope,location=location,marker=marker))
    if not root.is_dir():
        result['errors'].append('Application directory is missing')
        return result
    for path in sorted(root.rglob('*')):
        location=path.relative_to(root).as_posix()
        record('path',location,matches(location.encode()))
        if path.is_file():
            try:
                if strict and path.name in ('license-config.json','signing-private.pem','admin-password.txt','session-secret.txt','licenses.sqlite3'):
                    result['errors'].append('File not allowed in local edition: '+location)
                if not strict and location=='_internal/desktop/license-config.json':
                    checked=audit_config(path)
                    record('file',location,{item['marker'] for item in checked['findings']})
                    result['errors'].extend(checked['errors'])
                    if checked['accepted_exceptions']:
                        result['accepted_exceptions'].append(dict(location=location,exception='owner-approved license endpoint'))
                else:
                    record('file',location,file_matches(path))
                result['files_scanned']+=1
                if path.suffix.lower() in ('.zip','.whl','.jar','.nupkg'):
                    try:
                        with zipfile.ZipFile(path) as zipped:
                            if sum(item.file_size for item in zipped.infolist())>256*1024*1024:
                                raise ValueError('Archive exceeds inspection limit')
                            for item in zipped.infolist():
                                nested=location+'!'+item.filename
                                record('zip-path',nested,matches(item.filename.encode()))
                                if not item.is_dir():
                                    record('zip-member',nested,matches(zipped.read(item)))
                                    result['zip_members_scanned']+=1
                    except (OSError,ValueError,zipfile.BadZipFile,RuntimeError):
                        result['errors'].append('Cannot inspect ZIP: '+location)
            except OSError:
                result['errors'].append('Cannot inspect file: '+location)
    exe=root/'ZaloFlow.exe'
    if not exe.is_file():
        result['errors'].append('Main executable is missing')
    else:
        with exe.open('rb') as stream:result['executable_sha256']=hashlib.file_digest(stream,'sha256').hexdigest()
        try:
            from PyInstaller.archive.readers import CArchiveReader
            archive=CArchiveReader(str(exe))
            for name in archive.options:
                record('executable-option','ZaloFlow.exe',matches(name.encode()))
            for name,entry in archive.toc.items():
                record('archive-path','ZaloFlow.exe!'+name,matches(name.encode()))
                if entry[-1]=='z':
                    pyz=archive.open_embedded_archive(name)
                    for module in pyz.toc:
                        blob=pyz.extract(module,raw=True)
                        result['modules_scanned']+=1
                        if (module=='license_system' or module.startswith('license_system.') or module in
                                ('desktop.licensing','desktop.license_routes','desktop.license_identity','desktop.admin_accounts','desktop.main','legacy_web_accounts')):
                            result['licensing_modules'].append(module)
                            if strict:result['errors'].append('Module not allowed in local edition: '+module)
                        if blob:
                            if not strict and module=='desktop.license_identity':
                                cleaned=blob.lower()
                                for encoding in ('utf-8','utf-16le','utf-16be'):
                                    cleaned=cleaned.replace(APPROVED_LICENSE_URL.encode(encoding),b'')
                                if cleaned!=blob.lower():
                                    result['accepted_exceptions'].append(dict(location='ZaloFlow.exe!'+module,exception='owner-approved license endpoint'))
                                blob=cleaned
                            record('python-module','ZaloFlow.exe!'+module,matches(blob))
                else:
                    blob=archive.extract(name)
                    if blob:record('executable-entry','ZaloFlow.exe!'+name,matches(blob))
            if not result['modules_scanned']:
                result['errors'].append('No embedded Python modules were inspected')
        except Exception as error:
            result['errors'].append('Cannot inspect executable archive: '+type(error).__name__)
    result['findings'].sort(key=lambda item:(item['scope'],item['location'],item['marker']))
    result['passed']=not result['findings'] and not result['errors']
    return result


def main():
    parser=argparse.ArgumentParser(description='Audit owner identity in a customer Windows build')
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--config',type=Path)
    source.add_argument('--app-dir',type=Path)
    parser.add_argument('--report',type=Path)
    parser.add_argument('--strict',action='store_true',help='Local edition: no owner endpoint exceptions or licensing modules')
    args=parser.parse_args()
    result=audit_config(args.config,strict=args.strict) if args.config else audit_tree(args.app_dir,strict=args.strict)
    text=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(text,encoding='utf-8')
    print(text,end='')
    raise SystemExit(0 if result['passed'] else 1)


if __name__=='__main__':main()
