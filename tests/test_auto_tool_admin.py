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
    assert revealed['admin_username']=='quantri-company' and len(revealed['admin_password'])>=8
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


@pytest.mark.parametrize(('customer','expected'),[
    ('Trần Thảo Như','quantri-tranthaonhu'),
    ('ĐẶNG ĐỨC AN','quantri-dangducan'),
    ('  Công ty A & B .  ','quantri-congtyab'),
    ('A'*150,'quantri-'+'a'*56),
    ('東京','quantri-khachhang'),
])
def test_generated_name_normalizes_customer_and_is_valid_for_tool(authority,customer,expected):
    issued=authority.issue(customer,mode='floating',admin_username='')
    assert issued['admin_username']==expected
    revealed=authority.key_for_owner(issued['id'])
    assert revealed['admin_username']==expected
    assert revealed['admin_password']==issued['admin_password']


def test_automatic_names_are_unique_even_when_created_concurrently(authority):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        issued=list(pool.map(lambda _:authority.issue('Thảo Như',mode='floating',admin_username=''),range(2)))
    assert {row['admin_username'] for row in issued}=={'quantri-thaonhu','quantri-thaonhu-2'}
    third=authority.issue('Thao Nhu',mode='floating',admin_username='')
    assert third['admin_username']=='quantri-thaonhu-3'


def test_duplicate_long_customer_names_stay_within_tool_username_limit(authority):
    first=authority.issue('A'*150,mode='floating',admin_username='')
    second=authority.issue('A'*150,mode='floating',admin_username='')
    assert len(first['admin_username'])==len(second['admin_username'])==64
    assert second['admin_username'].endswith('-2')
    assert second['admin_username']!=first['admin_username']


def test_manual_name_is_kept_and_duplicate_is_rejected_without_changing_old_key(authority):
    old=authority.issue('Old',mode='floating',admin_username='own-admin')
    before=authority.key_for_owner(old['id'])
    with pytest.raises(LicenseError,match='đã được cấp'):
        authority.issue('Other',mode='floating',admin_username='OWN-ADMIN')
    assert authority.key_for_owner(old['id'])==before
    assert len(authority.list_licenses())==1
    supplemental=authority.issue('Other',mode='floating')
    with pytest.raises(LicenseError,match='đã được cấp'):
        authority.create_tool_admin(supplemental['id'],'own-admin')
    assert not authority.key_for_owner(supplemental['id'])['admin_username']


def test_web_autofill_uses_customer_and_manual_edits_are_preserved(authority):
    client=owner(authority)
    def issue(customer,username,automatic):
        return client.post('/admin',data=dict(csrf=admin_csrf(client,'/admin'),action='issue',
            customer=customer,days=30,admin_username=username,admin_username_auto=automatic))
    # A stale browser suggestion is not trusted when the customer name changes.
    assert issue('Thảo Như','quantri-old-customer','1').status_code==200
    assert authority.list_licenses()[0]['admin_username']=='quantri-thaonhu'
    assert issue('Other customer','QUANTRI-RIENG','0').status_code==200
    assert authority.list_licenses()[0]['admin_username']=='quantri-rieng'
    assert issue('Thảo Như','quantri-thaonhu','1').status_code==200
    assert authority.list_licenses()[0]['admin_username']=='quantri-thaonhu-2'


def test_admin_script_works_below_license_proxy_prefix(authority):
    client=owner(authority)
    response=client.get('/admin',environ_overrides={'SCRIPT_NAME':'/licenses'})
    assert 'src="/licenses/static/admin-names.js"' in response.text
    assert "script-src 'self'" in response.headers['Content-Security-Policy']
    assert client.get('/static/admin-names.js').status_code==200


def test_supplement_existing_key_preserves_key_expiry_and_activations(authority):
    issued=authority.issue('Existing',mode='floating')
    authority.exchange('activate',DEVICE_A,issued['key'],session_id='ZFS1-'+'A'*64)
    with authority.connection() as db:
        before=dict(db.execute('SELECT * FROM licenses').fetchone())
        activations=[dict(row) for row in db.execute('SELECT * FROM activations')]
    authority.create_tool_admin(issued['id'])
    after=authority.key_for_owner(issued['id'])
    assert after['key']==issued['key'] and after['admin_username'] and after['admin_password']
    assert after['admin_username']=='quantri-existing'
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
