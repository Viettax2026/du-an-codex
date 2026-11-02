import json
from pathlib import Path

import pytest
from werkzeug.security import check_password_hash

from desktop.runtime import DesktopRuntime
from license_system.server import create_app
from license_system.signatures import LicenseError
from test_license_system import authority,clock,DEVICE_A,admin_csrf
from test_license_sessions import client_for
from test_workflow import post


def owner(authority):
    app=create_app(authority.folder);client=app.test_client()
    password=(authority.folder/'admin-password.txt').read_text().strip()
    client.post('/admin/login',data=dict(csrf=admin_csrf(client),password=password))
    return client


def test_web_creates_admin_automatically_and_owner_can_reveal_initial_credentials(authority):
    client=owner(authority)
    response=client.post('/admin',data=dict(csrf=admin_csrf(client,'/admin'),action='issue',customer='Company',days=30))
    assert response.status_code==200
    row=authority.list_licenses()[0]
    revealed=authority.key_for_owner(row['id'])
    assert revealed['admin_username'].startswith('qt-') and len(revealed['admin_password'])>=8
    assert revealed['key'] and not revealed['can_create_admin']
    with authority.connection() as db:
        saved=db.execute('SELECT * FROM licenses').fetchone()
        assert check_password_hash(saved['admin_password_hash'],revealed['admin_password'])
        assert revealed['admin_password'] not in saved['admin_password_ciphertext']
    assert revealed['admin_password'].encode() not in authority.database.read_bytes()
    assert revealed['admin_password'] not in client.get('/admin').text
    response=client.post('/admin',data=dict(action='show-key',license_id=row['id'],csrf=admin_csrf(client,'/admin')))
    assert revealed['admin_password'] in response.text and response.headers['Cache-Control']=='no-store'
    with client.session_transaction() as session:assert revealed['admin_password'] not in json.dumps(dict(session))


def test_supplement_existing_key_preserves_key_expiry_and_activations(authority):
    issued=authority.issue('Existing',mode='floating')
    authority.exchange('activate',DEVICE_A,issued['key'],session_id='ZFS1-'+'A'*64)
    with authority.connection() as db:
        before=dict(db.execute('SELECT * FROM licenses').fetchone())
        activations=[dict(row) for row in db.execute('SELECT * FROM activations')]
    authority.create_tool_admin(issued['id'])
    after=authority.key_for_owner(issued['id'])
    assert after['key']==issued['key'] and after['admin_username'] and after['admin_password']
    with authority.connection() as db:
        row=dict(db.execute('SELECT * FROM licenses').fetchone())
        for name in ('key_hash','key_ciphertext','expires_at','mode','revoked','seats'):
            assert row[name]==before[name]
        assert [dict(row) for row in db.execute('SELECT * FROM activations')]==activations
    with pytest.raises(LicenseError,match='đã có quản trị'):
        authority.create_tool_admin(issued['id'])
    assert authority.key_for_owner(issued['id'])['admin_password']==after['admin_password']


def test_supplement_requires_owner_and_csrf(authority):
    issued=authority.issue('Existing',mode='floating')
    guest=create_app(authority.folder).test_client()
    assert guest.post('/admin',data=dict(csrf=admin_csrf(guest),action='create-tool-admin',license_id=issued['id'])).status_code==302
    client=owner(authority)
    assert client.post('/admin',data=dict(action='create-tool-admin',license_id=issued['id'])).status_code==400
    assert not authority.key_for_owner(issued['id'])['admin_username']
    response=client.post('/admin',data=dict(csrf=admin_csrf(client,'/admin'),action='create-tool-admin',license_id=issued['id']))
    assert response.status_code==200 and authority.key_for_owner(issued['id'])['admin_password'] in response.text


def test_old_admin_password_is_not_reset_when_only_its_hash_exists(authority):
    issued=authority.issue('Old',mode='floating',admin_username='old-admin')
    with authority.connection() as db:
        db.execute("UPDATE licenses SET admin_password_ciphertext='' WHERE id=?",(issued['id'],))
        digest=db.execute('SELECT admin_password_hash FROM licenses').fetchone()[0]
    result=authority.key_for_owner(issued['id'])
    assert result['admin_username']=='old-admin' and not result['admin_password'] and not result['can_create_admin']
    with pytest.raises(LicenseError):authority.create_tool_admin(issued['id'])
    with authority.connection() as db:assert db.execute('SELECT admin_password_hash FROM licenses').fetchone()[0]==digest


def test_activated_tool_receives_supplemented_admin_after_manual_refresh(authority,clock,tmp_path):
    issued=authority.issue('Existing',mode='floating')
    license=client_for(tmp_path,authority,clock,'license')
    runtime=DesktopRuntime(tmp_path/'tool',config={'TESTING':True},license=license)
    try:
        client=runtime.app.test_client()
        post(client,'/desktop/license',dict(action='activate',key=issued['key']))
        authority.create_tool_admin(issued['id'])
        credentials=authority.key_for_owner(issued['id'])
        post(client,'/desktop/license',dict(action='refresh'))
        post(client,'/login',dict(username=credentials['admin_username'],password=credentials['admin_password']))
        assert client.get('/admin/users').status_code==200
    finally:runtime.stop(5)


def test_customer_installer_guide_metadata_and_templates_have_neutral_branding():
    root=Path(__file__).resolve().parent.parent
    assert 'AppPublisher=ZaloFlow' in (root/'desktop/installer.iss').read_text()
    for relative in ('desktop/HUONG-DAN.txt','desktop/installer.iss','templates/_message_composer_dialogs.html'):
        text=(root/relative).read_text().lower()
        assert 'viettax' not in text and 'du-an-codex' not in text and 'cskh.' not in text
    # The signed publisher identity stays configured; removing visible branding
    # must not disable licensing or silently change the trusted server.
    config=json.loads((root/'desktop/license-config.json').read_text())
    assert config['version']==1 and config['server_url'].startswith('https://') and config['public_key']
