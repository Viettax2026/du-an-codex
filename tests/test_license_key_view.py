"""Owner-only key reveal, encrypted storage and hash-only legacy migration."""
import json

import pytest

from license_system.authority import Authority, secret_hash
from license_system.server import create_app
from license_system.signatures import LicenseError
from test_license_system import DEVICE_A, authority, admin_csrf


def owner_client(authority):
    app=create_app(authority.folder)
    client=app.test_client()
    password=(authority.folder/'admin-password.txt').read_text().strip()
    client.post('/admin/login',data=dict(csrf=admin_csrf(client),password=password))
    return app,client


def test_new_keys_are_encrypted_and_reveal_survives_restart_and_admin_password_change(authority):
    issued=authority.issue('Customer')
    with authority.connection() as db:
        row=db.execute('SELECT * FROM licenses').fetchone()
        assert row['key_hash']==secret_hash(issued['key'])
        assert issued['key'] not in row['key_ciphertext']
        assert row['key_ciphertext']
    assert issued['key'].encode() not in authority.database.read_bytes()
    assert issued['key'] not in json.dumps(authority.list_licenses())
    assert 'key_ciphertext' not in json.dumps(authority.list_licenses())
    assert authority.list_licenses()[0]['has_saved_key']
    reopened=Authority(authority.folder)
    reopened.set_admin_password('changed-owner-password')
    assert reopened.key_for_owner(issued['id'])['key']==issued['key']


def test_reveal_requires_admin_csrf_and_explicit_post_without_cookie_or_url_leak(authority):
    issued=authority.issue('Customer')
    app,owner=owner_client(authority)
    guest=app.test_client()
    values=dict(action='show-key',license_id=issued['id'])
    assert guest.post('/admin',data=dict(values,csrf=admin_csrf(guest))).status_code==302
    assert owner.post('/admin',data=values).status_code==400
    assert issued['key'] not in owner.get('/admin',query_string=values).text
    csrf=admin_csrf(owner,'/admin')
    result=owner.post('/admin',data=dict(values,csrf=csrf))
    assert result.status_code==200 and 'value="'+issued['key']+'"' in result.text
    assert result.headers['Cache-Control']=='no-store'
    assert issued['key'] not in result.headers.get('Location','')
    with owner.session_transaction() as session:
        assert issued['key'] not in json.dumps(dict(session))
    assert issued['key'] not in owner.get('/admin').text
    assert owner.get('/admin').text.count('value="show-key"')==1
    assert guest.post('/v1/show-key',json=dict(device=DEVICE_A,key=issued['key'])).status_code==404
    with guest.session_transaction() as session:session['admin_epoch']='forged-role'
    assert guest.post('/admin',data=dict(values,csrf=admin_csrf(guest))).status_code==302


def test_hash_only_migration_does_not_fabricate_or_rotate_old_keys(authority):
    issued=authority.issue('Legacy')
    active=authority.exchange('activate',DEVICE_A,issued['key'])
    private=authority.key_path.read_bytes()
    with authority.connection() as db:
        db.execute('ALTER TABLE licenses DROP COLUMN key_ciphertext')
        before=dict(db.execute('SELECT * FROM licenses').fetchone())
        activations=[dict(row) for row in db.execute('SELECT * FROM activations')]
    upgraded=Authority(authority.folder)
    upgraded.migrate()
    assert upgraded.key_for_owner(issued['id'])['key']==''
    assert not upgraded.list_licenses()[0]['has_saved_key']
    with upgraded.connection() as db:
        after=dict(db.execute('SELECT * FROM licenses').fetchone())
        assert all(after[name]==value for name,value in before.items())
        assert [dict(row) for row in db.execute('SELECT * FROM activations')]==activations
    assert upgraded.key_path.read_bytes()==private
    assert upgraded.exchange('refresh',DEVICE_A,active['activation_token'])['lease']
    _,owner=owner_client(upgraded)
    result=owner.post('/admin',data=dict(action='show-key',license_id=issued['id'],csrf=admin_csrf(owner,'/admin')))
    assert 'không thể khôi phục chuỗi key đã cấp' in result.text
    assert 'name="original_key"' in result.text
    assert issued['key'] not in result.text


def test_import_original_only_accepts_matching_key_and_preserves_activation_and_limits(authority):
    issued=authority.issue('Legacy')
    other=authority.issue('Other')
    active=authority.exchange('activate',DEVICE_A,issued['key'])
    with authority.connection() as db:
        db.execute("UPDATE licenses SET key_ciphertext='' WHERE id=?",(issued['id'],))
        before=dict(db.execute('SELECT * FROM licenses WHERE id=?',(issued['id'],)).fetchone())
        token=db.execute('SELECT token_hash FROM activations').fetchone()[0]
    with pytest.raises(LicenseError,match='không khớp'):
        authority.save_original_key(issued['id'],other['key'])
    assert authority.key_for_owner(issued['id'])['key']==''
    _,owner=owner_client(authority)
    csrf=admin_csrf(owner,'/admin')
    assert owner.post('/admin',data=dict(action='save-key-copy',license_id=issued['id'],original_key=issued['key'])).status_code==400
    result=owner.post('/admin',data=dict(action='save-key-copy',license_id=issued['id'],original_key=issued['key'],csrf=csrf))
    assert result.status_code==200 and 'value="'+issued['key']+'"' in result.text
    with authority.connection() as db:
        after=dict(db.execute('SELECT * FROM licenses WHERE id=?',(issued['id'],)).fetchone())
        assert all(after[name]==value for name,value in before.items() if name!='key_ciphertext')
        assert db.execute('SELECT token_hash FROM activations').fetchone()[0]==token
    assert authority.exchange('refresh',DEVICE_A,active['activation_token'])['lease']
    assert issued['key'] not in owner.get('/admin').text


def test_corrupt_or_swapped_ciphertext_never_reveals_the_wrong_key(authority):
    first=authority.issue('First')
    second=authority.issue('Second')
    with authority.connection() as db:
        encrypted=db.execute('SELECT key_ciphertext FROM licenses WHERE id=?',(second['id'],)).fetchone()[0]
        db.execute('UPDATE licenses SET key_ciphertext=? WHERE id=?',(encrypted,first['id']))
    with pytest.raises(LicenseError,match='Không đọc được'):
        authority.key_for_owner(first['id'])
    _,owner=owner_client(authority)
    result=owner.post('/admin',data=dict(action='show-key',license_id=first['id'],csrf=admin_csrf(owner,'/admin')))
    assert second['key'] not in result.text and first['key'] not in result.text
    with authority.connection() as db:
        db.execute('UPDATE licenses SET key_ciphertext=? WHERE id=?',('corrupt',first['id']))
    with pytest.raises(LicenseError):authority.key_for_owner(first['id'])


def test_revoke_and_delete_still_work_after_encrypted_key_storage(authority):
    issued=authority.issue('Customer')
    authority.manage(issued['id'],'revoke')
    assert authority.key_for_owner(issued['id'])['key']==issued['key']
    with pytest.raises(LicenseError):authority.exchange('activate',DEVICE_A,issued['key'])
    authority.manage(issued['id'],'delete')
    with pytest.raises(LicenseError,match='Không tìm thấy'):authority.key_for_owner(issued['id'])
