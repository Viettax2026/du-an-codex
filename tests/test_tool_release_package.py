import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('tool_release',ROOT/'release_tools/package_tool.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)


def fixture_installer(tmp_path):
    folder=tmp_path/'installer';folder.mkdir()
    exe=folder/'ZaloFlow-Setup-x64.exe';exe.write_bytes(b'MZ-synthetic-only-for-pytest')
    (folder/'ZaloFlow-Setup-x64.exe.sha256').write_text(hashlib.sha256(exe.read_bytes()).hexdigest()+'  '+exe.name+'\n')
    (folder/'SOURCE.txt').write_text('Application source: '+release.APP_COMMIT+'\nInstaller version: 1.0.99\n')
    (folder/'audit.json').write_text(json.dumps(dict(passed=True,findings=[],errors=[],files_scanned=1,modules_scanned=1,installer_sha256=hashlib.sha256(exe.read_bytes()).hexdigest())))
    return folder


def test_tool_zip_has_checked_installer_source_guide_and_honest_provenance(tmp_path):
    folder=fixture_installer(tmp_path)
    # Unrelated private files next to the installer must not enter the release.
    (folder/'admin-password.txt').write_text('synthetic-secret')
    output=tmp_path/'release'
    manifest=release.assemble(folder,output,ROOT/'desktop/HUONG-DAN.txt',folder/'audit.json')
    assert manifest['source_commit']==release.APP_COMMIT
    assert manifest['floating_license'] and manifest['tool_admin_accounts']
    assert manifest['vps_live_test_confirmed'] is False
    assert manifest['neutral_branding'] and manifest['automatic_admin_credentials']
    with zipfile.ZipFile(output/release.ZIP_NAME) as archive:
        assert archive.testzip() is None
        assert not any('admin-password' in name for name in archive.namelist())
        for name,digest in manifest['files'].items():
            assert hashlib.sha256(archive.read(release.ARCHIVE_ROOT+name)).hexdigest()==digest
        assert json.loads(archive.read(release.ARCHIVE_ROOT+'RELEASE-MANIFEST.json'))==manifest
    assert hashlib.sha256((output/release.ZIP_NAME).read_bytes()).hexdigest()==(output/(release.ZIP_NAME+'.sha256')).read_text().split()[0]


@pytest.mark.parametrize('failure',['checksum','source','format'])
def test_tool_release_rejects_corruption_wrong_source_or_non_executable(tmp_path,failure):
    folder=fixture_installer(tmp_path)
    if failure=='checksum':
        (folder/'ZaloFlow-Setup-x64.exe').write_bytes(b'MZ-changed')
    elif failure=='source':
        (folder/'SOURCE.txt').write_text('Application source: wrong-commit')
    else:
        exe=folder/'ZaloFlow-Setup-x64.exe';exe.write_bytes(b'not-an-executable')
        (folder/'ZaloFlow-Setup-x64.exe.sha256').write_text(hashlib.sha256(exe.read_bytes()).hexdigest())
    with pytest.raises(ValueError):release.assemble(folder,tmp_path/'release',ROOT/'desktop/HUONG-DAN.txt',folder/'audit.json')


def test_customer_release_cannot_bypass_failed_or_unrelated_artifact_audit(tmp_path):
    folder=fixture_installer(tmp_path)
    report=folder/'audit.json'
    original=json.loads(report.read_text())
    for changed in (dict(passed=False),dict(findings=[{'marker':'owner'}]),dict(modules_scanned=0),dict(installer_sha256='0'*64)):
        report.write_text(json.dumps(dict(original,**changed)))
        with pytest.raises(ValueError,match='inspection'):
            release.assemble(folder,tmp_path/'release',ROOT/'desktop/HUONG-DAN.txt',report)
