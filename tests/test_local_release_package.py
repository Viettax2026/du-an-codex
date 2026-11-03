import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from release_tools import package_local as release

ROOT=Path(__file__).resolve().parent.parent
SOURCE='1'*40


def fixture_installer(tmp_path):
    folder=tmp_path/'installer';folder.mkdir()
    exe=folder/'ZaloFlow-Local-Setup-x64.exe';exe.write_bytes(b'MZ-synthetic-installer')
    (folder/(exe.name+'.sha256')).write_text(hashlib.sha256(exe.read_bytes()).hexdigest())
    (folder/'SOURCE.txt').write_text('Application source: '+SOURCE+'\nEdition: local\nInstaller version: 1.0.1\n')
    (folder/'audit.json').write_text(json.dumps(dict(passed=True,strict=True,accepted_exceptions=[],
        licensing_modules=[],errors=[],findings=[],files_scanned=1,modules_scanned=1,
        installer_sha256=hashlib.sha256(exe.read_bytes()).hexdigest())))
    return folder


def test_local_package_contains_only_checked_installer_and_neutral_local_guide(tmp_path):
    folder=fixture_installer(tmp_path);output=tmp_path/'release'
    (folder/'admin-password.txt').write_text('synthetic-not-for-release')
    manifest=release.assemble(folder,output,ROOT/'desktop/HUONG-DAN-LOCAL.txt',folder/'audit.json',SOURCE)
    assert manifest['requires_key'] is False and manifest['license_endpoint_included'] is False
    assert manifest['data_directory']=='ZaloFlowLocal'
    with zipfile.ZipFile(output/release.ZIP_NAME) as archive:
        assert archive.testzip() is None
        assert not any('admin-password' in name for name in archive.namelist())
        for name,digest in manifest['files'].items():
            assert hashlib.sha256(archive.read(release.ARCHIVE_ROOT+name)).hexdigest()==digest
    assert release.digest(output/release.ZIP_NAME)==(output/(release.ZIP_NAME+'.sha256')).read_text().split()[0]


@pytest.mark.parametrize('change',[
    dict(strict=False),dict(accepted_exceptions=[{'exception':'endpoint'}]),
    dict(licensing_modules=['desktop.licensing']),dict(installer_sha256='0'*64),dict(modules_scanned=0),
])
def test_local_package_rejects_licensed_or_unverified_audit(tmp_path,change):
    folder=fixture_installer(tmp_path);report=folder/'audit.json'
    report.write_text(json.dumps(json.loads(report.read_text())|change))
    with pytest.raises(ValueError,match='strict inspection'):
        release.assemble(folder,tmp_path/'release',ROOT/'desktop/HUONG-DAN-LOCAL.txt',report,SOURCE)
