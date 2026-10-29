import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest


ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('zaloflow_release_package',ROOT/'release_tools/package_windows.py')
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)


def installer(tmp_path):
    folder=tmp_path/'installer';folder.mkdir()
    exe=folder/'ZaloFlow-Setup-x64.exe';exe.write_bytes(b'MZsynthetic-installer-for-package-test')
    Path(str(exe)+'.sha256').write_text(hashlib.sha256(exe.read_bytes()).hexdigest()+'  '+exe.name+'\n')
    (folder/'SOURCE.txt').write_text('Application source: '+release.APP_COMMIT+'\nInstaller version: 1.0.99\n')
    return folder


def test_release_combines_matching_installer_source_and_instructions_with_checksums(tmp_path):
    source=ROOT/'downloads'/release.CODE_NAME
    output=tmp_path/'public-release'
    manifest=release.assemble(source,installer(tmp_path),output)
    assert manifest['source_commit']==release.APP_COMMIT and manifest['pdf_live_delivery_confirmed'] is False
    with zipfile.ZipFile(output/release.FULL_NAME) as archive:
        assert archive.testzip() is None
        assert 'ZaloFlow-2026-10-30/ZaloFlow-Setup-x64.exe' in archive.namelist()
        for name,digest in manifest['files'].items():
            assert hashlib.sha256(archive.read('ZaloFlow-2026-10-30/'+name)).hexdigest()==digest
        assert json.loads(archive.read('ZaloFlow-2026-10-30/RELEASE-MANIFEST.json'))==manifest
    release.check_hash(output/release.FULL_NAME)


def test_release_refuses_installer_corruption_or_a_different_source_revision(tmp_path):
    folder=installer(tmp_path)
    code=ROOT/'downloads'/release.CODE_NAME
    (folder/'SOURCE.txt').write_text('Application source: wrong-commit')
    with pytest.raises(ValueError,match='source'):
        release.assemble(code,folder,tmp_path/'output')
    (folder/'ZaloFlow-Setup-x64.exe').write_bytes(b'MZchanged')
    with pytest.raises(ValueError,match='Checksum'):
        release.assemble(code,folder,tmp_path/'output')
