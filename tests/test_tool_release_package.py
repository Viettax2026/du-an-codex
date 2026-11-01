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
    return folder


def test_tool_zip_has_checked_installer_source_guide_and_honest_provenance(tmp_path):
    folder=fixture_installer(tmp_path)
    # Unrelated private files next to the installer must not enter the release.
    (folder/'admin-password.txt').write_text('synthetic-secret')
    output=tmp_path/'release'
    manifest=release.assemble(folder,output)
    assert manifest['source_commit']==release.APP_COMMIT
    assert manifest['floating_license'] and manifest['tool_admin_accounts']
    assert manifest['vps_live_test_confirmed'] is False
    with zipfile.ZipFile(output/release.ZIP_NAME) as archive:
        assert archive.testzip() is None
        assert not any('admin-password' in name for name in archive.namelist())
        for name,digest in manifest['files'].items():
            assert hashlib.sha256(archive.read('ZaloFlow-2026-11-01/'+name)).hexdigest()==digest
        assert json.loads(archive.read('ZaloFlow-2026-11-01/RELEASE-MANIFEST.json'))==manifest
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
    with pytest.raises(ValueError):release.assemble(folder,tmp_path/'release')
