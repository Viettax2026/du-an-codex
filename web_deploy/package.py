"""Build and verify a code-only archive using an explicit file allowlist."""
import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = 'WEB-RELEASE.json'


def source_files(root):
    files = list(root.glob('*.py')) + [root / 'requirements.txt', root / 'requirements-prod.txt']
    for folder in ('templates', 'static', 'web_deploy'):
        files.extend(path for path in (root / folder).rglob('*')
                     if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc')
    files.extend(path for path in (root / 'connector').iterdir()
                 if path.is_file() and (path.suffix == '.mjs' or path.name in ('package.json', 'package-lock.json', 'THIRD_PARTY_NOTICES.md')))
    for name in ('LICENSE', 'LICENSE.md', 'LICENSE.txt'):
        if (root / name).is_file():
            files.append(root / name)
    return sorted(set(files))


def build(output, root=ROOT):
    root, output = Path(root).resolve(), Path(output).resolve()
    files = source_files(root)
    entries = {}
    for path in files:
        if path.is_symlink():
            raise ValueError('Không đóng gói symlink: ' + str(path))
        name = path.relative_to(root).as_posix()
        entries[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = 'export-sha256:' + hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()
    release = dict(package='ZaloFlow-Web', format=1, source_commit=commit,
                   operating_system='Ubuntu 24.04 LTS', includes_customer_data=False,
                   includes_windows_app=False, includes_license_authority=False, files=entries)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, 'zaloflow-web/' + path.relative_to(root).as_posix())
        archive.writestr('zaloflow-web/' + MANIFEST, json.dumps(release, indent=2) + '\n')
    output.with_suffix(output.suffix + '.sha256').write_text(hashlib.sha256(output.read_bytes()).hexdigest() + '  ' + output.name + '\n')
    return output


def verify(root):
    root = Path(root).resolve()
    release = json.loads((root / MANIFEST).read_text())
    if release.get('package') != 'ZaloFlow-Web' or release.get('format') != 1:
        raise ValueError('Không phải gói mã web ZaloFlow được hỗ trợ.')
    files = release['files']
    required = {'app.py', 'requirements-prod.txt', 'web_deploy/install-web.sh', 'connector/package-lock.json'}
    if not isinstance(files, dict) or not required.issubset(files):
        raise ValueError('Gói web thiếu tệp cần thiết.')
    for name, digest in files.items():
        relative = PurePosixPath(name)
        allowed = (len(relative.parts) == 1 and (relative.suffix == '.py' or name in ('requirements.txt', 'requirements-prod.txt', 'LICENSE', 'LICENSE.md', 'LICENSE.txt'))
                   or relative.parts[0] in ('templates', 'static', 'web_deploy')
                   or len(relative.parts) == 2 and relative.parts[0] == 'connector')
        if not allowed or relative.is_absolute() or '..' in relative.parts or '\\' in name:
            raise ValueError('Đường dẫn không được phép trong gói web: ' + name)
        path = root.joinpath(*relative.parts)
        if any(parent.is_symlink() for parent in (path, *path.parents) if parent != root.parent):
            raise ValueError('Không cho phép symlink trong gói cài.')
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Tệp bị thiếu hoặc đã thay đổi: ' + name)
    return release


def install_code(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    release = verify(source)
    destination.mkdir(parents=True, exist_ok=True)
    for name in (*release['files'], MANIFEST):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink() or any(parent.is_symlink() for parent in target.parents):
            raise ValueError('Đích cài chứa symlink: ' + str(target))
        shutil.copyfile(source / name, target)
        target.chmod(0o644)
    for path in destination.rglob('*'):
        if path.is_dir() and 'instance' not in path.relative_to(destination).parts:
            path.chmod(0o755)


def main():
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest='command', required=True)
    archive = sub.add_parser('build'); archive.add_argument('--output', type=Path, default=ROOT / 'dist' / 'zaloflow-web.zip')
    check = sub.add_parser('verify'); check.add_argument('root', type=Path)
    copy = sub.add_parser('install-code'); copy.add_argument('source', type=Path); copy.add_argument('destination', type=Path)
    args = parser.parse_args()
    if args.command == 'build':
        print(build(args.output))
    elif args.command == 'verify':
        release = verify(args.root); print('Mã web hợp lệ: ' + release['source_commit'])
    else:
        install_code(args.source, args.destination)


if __name__ == '__main__':
    main()
