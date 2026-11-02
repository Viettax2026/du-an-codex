import base64
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from desktop.privacy_audit import audit_config,audit_tree,file_matches,matches

ROOT=Path(__file__).resolve().parent.parent


def config(path,url):
    path.write_text(json.dumps(dict(version=1,server_url=url,
                    public_key=base64.urlsafe_b64encode(b'A'*32).decode().rstrip('='))))
    return path


def test_customer_build_allows_only_explicitly_approved_license_host(tmp_path):
    p=config(tmp_path/'config.json','https://cskh.viettaxco.com/licenses')
    result=audit_config(p)
    assert result['passed'] and result['accepted_exceptions']
    assert not audit_config(config(p,'https://marketing.viettaxco.com'))['passed']
    assert 'public_key' not in json.dumps(result)
    assert audit_config(config(p,'https://license.example.net/licenses'))['passed']
    assert not audit_config(config(p,'http://license.example.net'))['passed']
    assert not audit_config(config(p,'https://user:secret@license.example.net'))['passed']


def test_scan_detects_utf16_and_markers_crossing_file_chunks(tmp_path):
    assert matches('VIETTAX'.encode('utf-16le'))=={'viettax'}
    assert matches('VIETTAX'.encode('utf-16be'))=={'viettax'}
    path=tmp_path/'file.dat'
    path.write_bytes(b'A'*(1024*1024-3)+b'ViEtTaX'+b'B'*128)
    assert file_matches(path)=={'viettax'}


def program(tmp_path,source,module_name='identity'):
    pytest.importorskip('PyInstaller')
    from PyInstaller.archive.writers import CArchiveWriter,ZlibArchiveWriter
    root=tmp_path/'app';root.mkdir()
    module=tmp_path/'identity.py';module.write_text(source)
    pyz=tmp_path/'modules.pyz'
    ZlibArchiveWriter(str(pyz),[(module_name,str(module),'PYMODULE')],
                     code_dict={module_name:compile(source,'identity.py','exec')})
    CArchiveWriter(str(root/'ZaloFlow.exe'),[('PYZ.pyz',str(pyz),False,'z')],'python312.dll')
    return root


def test_scan_reads_compressed_code_that_plain_file_search_cannot_find(tmp_path):
    root=program(tmp_path,"HOST = 'https://cskh.viettaxco.com/licenses'\n")
    assert file_matches(root/'ZaloFlow.exe')==set()
    result=audit_tree(root)
    assert result['modules_scanned']==1 and not result['passed']
    assert result['findings']==[dict(scope='python-module',location='ZaloFlow.exe!identity',marker='viettax')]
    assert result['executable_sha256']


def test_clean_archive_passes_and_plain_configuration_fails(tmp_path):
    root=program(tmp_path,"HOST = 'https://license.example.net/licenses'\n")
    assert audit_tree(root)['passed']
    folder=root/'_internal'/'desktop';folder.mkdir(parents=True)
    config(folder/'license-config.json','https://marketing.viettaxco.com')
    result=audit_tree(root)
    assert not result['passed']
    assert any(item['location']=='_internal/desktop/license-config.json' for item in result['findings'])


def test_unreadable_or_missing_executable_is_not_reported_as_private(tmp_path):
    root=tmp_path/'broken';root.mkdir()
    assert not audit_tree(root)['passed']
    (root/'ZaloFlow.exe').write_bytes(b'MZnot-a-readable-python-archive')
    result=audit_tree(root)
    assert not result['passed'] and result['errors']


def test_desktop_legacy_account_keeps_original_identity_and_password(tmp_path):
    database=tmp_path/'desktop.sqlite3'
    digest=generate_password_hash('original-password')
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,name TEXT,username TEXT UNIQUE,password TEXT)')
        db.execute('INSERT INTO users VALUES(7,?,?,?)',('Existing','lienhe.viettaxco@gmail.com',digest))
    create_app(dict(TESTING=True,DATABASE=str(database),DESKTOP_RUNTIME=True),instance_path=tmp_path/'instance')
    with sqlite3.connect(database) as db:
        assert db.execute('SELECT id,username,password FROM users').fetchone()==(7,'lienhe.viettaxco@gmail.com',digest)


def test_customer_spec_excludes_plain_config_and_web_only_identity():
    spec=(ROOT/'desktop/zaloflow.spec').read_text()
    assert 'license-config.json' not in spec
    assert "'legacy_web_accounts'" in spec
    source=(ROOT/'app.py').read_text()
    assert 'lienhe.viettaxco' not in source
    assert 'privacy_audit --config' in (ROOT/'desktop/build-windows.ps1').read_text()
    assert 'privacy_audit --app-dir' in (ROOT/'desktop/build-windows.ps1').read_text()


def test_nested_zip_content_is_inspected_without_executing_it(tmp_path):
    root=program(tmp_path,"HOST = 'https://license.example.net/licenses'\n")
    with zipfile.ZipFile(root/'library.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('configuration.txt','https://cskh.viettaxco.com/licenses')
    assert not file_matches(root/'library.zip')
    result=audit_tree(root)
    assert not result['passed'] and result['zip_members_scanned']==1
    assert any(item['scope']=='zip-member' for item in result['findings'])


def test_compiled_license_url_exception_does_not_allow_other_owner_information(tmp_path):
    root=program(tmp_path,"HOST = 'https://cskh.viettaxco.com/licenses'\n",module_name='desktop.license_identity')
    result=audit_tree(root)
    assert result['passed'] and len(result['accepted_exceptions'])==1
    other=tmp_path/'second';other.mkdir()
    root=program(other,"HOST = 'https://cskh.viettaxco.com/licenses'\nEMAIL='owner@viettaxco.com'\n",module_name='desktop.license_identity')
    result=audit_tree(root)
    assert not result['passed'] and result['findings'][0]['marker']=='viettax'
