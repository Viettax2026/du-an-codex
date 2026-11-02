"""Publisher-issued tool administrator, local user creation and privilege boundaries."""
import json
import sqlite3

import pytest
from werkzeug.security import check_password_hash, generate_password_hash

import account_approval
from account_approval import create_pending_account, set_approval
from desktop.admin_accounts import sync_license_admin
from desktop.runtime import DesktopRuntime
from license_system.server import create_app as license_app
from test_license_sessions import authority, clock, client_for
from test_license_system import admin_csrf
from test_workflow import app, post, token


@pytest.fixture
def issued_desktop(tmp_path,authority,clock):
    issued=authority.issue('Customer',mode='floating',admin_username='customer-admin')
    license=client_for(tmp_path,authority,clock,'license')
    runtime=DesktopRuntime(tmp_path/'desktop',config={'TESTING':True},license=license)
    try:yield runtime,license,issued
    finally:runtime.stop(5)


def rows(runtime,sql,args=()):
    with sqlite3.connect(runtime.app.config['DATABASE']) as db:
        return db.execute(sql,args).fetchall()


def activate(runtime,issued):
    client=runtime.app.test_client()
    return client,post(client,'/desktop/license',dict(key=issued['key'],action='activate'))


def login_admin(runtime,issued):
    client,response=activate(runtime,issued)
    assert response.status_code==200
    post(client,'/login',dict(username=issued['admin_username'],password=issued['admin_password']))
    assert client.get('/admin/users').status_code==200
    return client


def test_owner_issues_key_and_admin_password_once_without_storing_plaintext(authority):
    client=license_app(authority.folder).test_client()
    password=(authority.folder/'admin-password.txt').read_text().strip()
    client.post('/admin/login',data=dict(csrf=admin_csrf(client),password=password))
    response=client.post('/admin',data=dict(csrf=admin_csrf(client,'/admin'),action='issue',customer='Company',days=30,admin_username='COMPANY-ADMIN'))
    assert response.status_code==200 and 'Mật khẩu khởi tạo quản trị tool' in response.text
    import re
    initial=re.search(r'aria-label="Mật khẩu khởi tạo quản trị tool"[^>]*value="([^"]+)"',response.text).group(1)
    with authority.connection() as db:
        row=db.execute('SELECT * FROM licenses').fetchone()
        assert row['admin_username']=='company-admin'
        assert check_password_hash(row['admin_password_hash'],initial)
    assert initial.encode() not in authority.database.read_bytes()
    assert initial not in client.get('/admin').text
    assert 'password_hash' not in json.dumps(authority.list_licenses())


def test_signed_key_provisions_approved_local_admin_and_ignores_form_privileges(issued_desktop):
    runtime,license,issued=issued_desktop
    client,response=activate(runtime,issued)
    assert response.status_code==200
    assert rows(runtime,'SELECT username,role,approval_status FROM users')==[('customer-admin','admin','approved')]
    assert check_password_hash(rows(runtime,'SELECT password FROM users')[0][0],issued['admin_password'])
    assert issued['admin_password'] not in response.text
    with client.session_transaction() as session:assert 'user_id' not in session
    post(client,'/login',dict(username='customer-admin',password=issued['admin_password']))
    assert 'Tạo tài khoản trong tool' in client.get('/admin/users').text


def test_saved_key_provisions_admin_on_startup_without_new_activation(issued_desktop):
    runtime,license,issued=issued_desktop
    license.activate(issued['key'])
    runtime.start()
    assert rows(runtime,'SELECT username,role FROM users')==[('customer-admin','admin')]


def test_admin_creates_multiple_regular_accounts_that_can_login_immediately(issued_desktop):
    runtime,license,issued=issued_desktop
    owner=login_admin(runtime,issued)
    for name in ('staff-one','staff-two'):
        response=post(owner,'/admin/users/create',dict(name=name,username=name,password='staff888',confirm_password='staff888',
                                                      email=name+'@example.com',role='admin',approval_status='blocked',email_verified='1'))
        assert 'Đã tạo tài khoản thường' in response.text
    assert rows(runtime,'SELECT username,role,approval_status,email_verified FROM users ORDER BY id')==[
        ('customer-admin','admin','approved',0),('staff-one','user','approved',0),('staff-two','user','approved',0)]
    child=runtime.app.test_client()
    post(child,'/login',dict(username='staff-one',password='staff888'))
    assert child.get('/contacts').status_code==200
    assert child.get('/admin/users').status_code==403
    assert post(child,'/admin/users/create',dict(name='No',username='no-user',password='staff888',confirm_password='staff888')).status_code==403
    assert rows(runtime,'SELECT count(*) FROM users')==[(3,)]
    assert rows(runtime,"SELECT actor_id FROM account_approval_events WHERE action='admin_create'")==[(1,),(1,)]


def test_create_requires_csrf_current_admin_and_valid_license(issued_desktop,clock):
    runtime,license,issued=issued_desktop
    owner=login_admin(runtime,issued)
    values=dict(name='Staff',username='staff-one',password='staff888',confirm_password='staff888')
    assert owner.post('/admin/users/create',data=values).status_code==400
    guest=runtime.app.test_client()
    assert post(guest,'/admin/users/create',values).status_code==200  # Follows redirect to login.
    assert rows(runtime,'SELECT count(*) FROM users')==[(1,)]
    clock.wall+=70;clock.mono+=70
    post(owner,'/admin/users/create',values)
    assert rows(runtime,'SELECT count(*) FROM users')==[(1,)]


def test_expiry_during_password_hashing_rolls_back_creation(issued_desktop,clock,monkeypatch):
    runtime,license,issued=issued_desktop
    owner=login_admin(runtime,issued)
    original=account_approval.generate_password_hash
    def expire(value):
        result=original(value);clock.wall+=70;clock.mono+=70;return result
    monkeypatch.setattr(account_approval,'generate_password_hash',expire)
    post(owner,'/admin/users/create',dict(name='Staff',username='staff-one',password='staff888',confirm_password='staff888'))
    assert rows(runtime,'SELECT count(*) FROM users')==[(1,)]


@pytest.mark.parametrize('extra',[
    dict(username='bad space'),dict(password='seven77',confirm_password='seven77'),
    dict(confirm_password='mismatch'),dict(email='bad-email'),dict(username='admin')])
def test_invalid_child_account_is_not_created(issued_desktop,extra):
    runtime,license,issued=issued_desktop
    owner=login_admin(runtime,issued)
    values=dict(name='Staff',username='staff-one',password='staff888',confirm_password='staff888')
    values.update(extra)
    post(owner,'/admin/users/create',values)
    assert rows(runtime,'SELECT count(*) FROM users')==[(1,)]


def test_duplicate_username_does_not_overwrite_password(issued_desktop):
    runtime,license,issued=issued_desktop
    owner=login_admin(runtime,issued)
    values=dict(name='Staff',username='staff-one',password='staff888',confirm_password='staff888')
    post(owner,'/admin/users/create',values)
    before=rows(runtime,'SELECT password FROM users WHERE username=?',('staff-one',))
    post(owner,'/admin/users/create',dict(values,password='changed8',confirm_password='changed8'))
    assert rows(runtime,'SELECT password FROM users WHERE username=?',('staff-one',))==before


def test_renewal_never_resets_recovered_password_or_restores_removed_admin_role(issued_desktop):
    runtime,license,issued=issued_desktop
    activate(runtime,issued)
    changed=generate_password_hash('changed-password')
    with sqlite3.connect(runtime.app.config['DATABASE']) as db:
        db.execute("UPDATE users SET password=?,role='user',approval_status='blocked'",(changed,))
    assert license.refresh(force=True)
    sync_license_admin(runtime.app,license)
    assert rows(runtime,'SELECT password,role,approval_status FROM users')==[(changed,'user','blocked')]
    assert rows(runtime,"SELECT count(*) FROM account_approval_events WHERE action='license_admin'")==[(1,)]


def test_existing_username_is_never_silently_promoted_or_password_reset(issued_desktop):
    runtime,license,issued=issued_desktop
    with runtime.app.app_context():
        db=runtime.app.extensions['campaign_manager'].db()
        user=create_pending_account(db,'Existing','customer-admin',generate_password_hash('existing-password'))
        set_approval(db,user.lastrowid,'approved');db.commit()
    before=rows(runtime,'SELECT password,role FROM users')
    client,response=activate(runtime,issued)
    assert 'Không ghi đè mật khẩu' in response.text
    assert rows(runtime,'SELECT password,role FROM users')==before


def conflicting_admin(runtime):
    with runtime.app.app_context():
        db=runtime.app.extensions['campaign_manager'].db()
        user=create_pending_account(db,'Existing','customer-admin',generate_password_hash('existing-password'))
        set_approval(db,user.lastrowid,'approved')
        db.execute("INSERT INTO contacts(user_id,name,phone) VALUES (?,'Keep old data','0901')",(user.lastrowid,))
        db.commit()


def grants(runtime):
    if not rows(runtime,"SELECT 1 FROM sqlite_master WHERE type='table' AND name='desktop_admin_grants'"):
        return []
    return rows(runtime,'SELECT * FROM desktop_admin_grants')


def test_conflicting_name_can_create_separate_admin_without_touching_old_account(issued_desktop):
    runtime,license,issued=issued_desktop
    conflicting_admin(runtime)
    before=rows(runtime,'SELECT * FROM users')
    contacts=rows(runtime,'SELECT * FROM contacts')
    client,response=activate(runtime,issued)
    assert 'Tạo quản trị bằng tên khác' in response.text
    assert 'đang trùng tài khoản cũ' in client.get('/login').text
    response=post(client,'/desktop/license',dict(action='resolve-admin-name',local_username='NEW-OWNER',
        initial_password=issued['admin_password'],role='user',approval_status='blocked'))
    assert 'Đã tạo quản trị new-owner' in response.text
    assert 'Tài khoản quản trị trong tool này: <strong>new-owner</strong>' in response.text
    assert issued['admin_password'] not in response.text
    assert rows(runtime,'SELECT * FROM users WHERE username=?',('customer-admin',))==before
    assert rows(runtime,'SELECT * FROM contacts')==contacts
    assert rows(runtime,'SELECT username,role,approval_status FROM users WHERE username=?',('new-owner',))==[('new-owner','admin','approved')]
    post(client,'/login',dict(username='new-owner',password=issued['admin_password']))
    assert client.get('/admin/users').status_code==200
    assert 'Keep old data' not in client.get('/contacts').text
    assert license.refresh(force=True)
    assert sync_license_admin(runtime.app,license)=='new-owner'
    runtime.start()  # A restart uses the persisted mapping, not the signed name.
    other=runtime.app.test_client()
    assert 'Tài khoản quản trị trong tool này: <strong>new-owner</strong>' in other.get('/login').text
    post(other,'/login',dict(username='customer-admin',password='existing-password'))
    assert 'Keep old data' in other.get('/contacts').text
    assert other.get('/admin/users').status_code==403


@pytest.mark.parametrize('values',[
    dict(initial_password='wrong-password'),dict(local_username='customer-admin'),
    dict(local_username='bad name'),dict(local_username='x'),dict(local_username='x'*65),dict(local_username='admin'),
])
def test_conflict_resolution_requires_valid_unused_name_and_initial_password(issued_desktop,values):
    runtime,license,issued=issued_desktop
    conflicting_admin(runtime)
    client,_=activate(runtime,issued)
    before=rows(runtime,'SELECT * FROM users')
    post(client,'/desktop/license',dict(action='resolve-admin-name',local_username='new-owner',initial_password=issued['admin_password']) | values)
    assert rows(runtime,'SELECT * FROM users')==before
    assert grants(runtime)==[]


def test_conflict_resolution_requires_csrf_and_cannot_create_multiple_admins(issued_desktop):
    runtime,license,issued=issued_desktop
    conflicting_admin(runtime)
    client,_=activate(runtime,issued)
    values=dict(action='resolve-admin-name',local_username='new-owner',initial_password=issued['admin_password'])
    assert client.post('/desktop/license',data=values).status_code==400
    post(client,'/desktop/license',values)
    post(client,'/desktop/license',dict(values,local_username='another-admin'))
    assert rows(runtime,'SELECT count(*) FROM users')==[(2,)]
    changed=generate_password_hash('changed-password')
    with sqlite3.connect(runtime.app.config['DATABASE']) as db:
        db.execute("UPDATE users SET password=?,role='user',approval_status='blocked' WHERE username='new-owner'",(changed,))
    assert sync_license_admin(runtime.app,license)=='new-owner'
    assert rows(runtime,"SELECT password,role,approval_status FROM users WHERE username='new-owner'")==[(changed,'user','blocked')]


def test_conflict_resolution_rechecks_expiry_after_password_verification(issued_desktop,clock,monkeypatch):
    import desktop.admin_accounts as admins
    runtime,license,issued=issued_desktop
    conflicting_admin(runtime)
    client,_=activate(runtime,issued)
    original=admins.check_password_hash
    def expire(*args):
        result=original(*args);clock.wall+=70;clock.mono+=70;return result
    monkeypatch.setattr(admins,'check_password_hash',expire)
    post(client,'/desktop/license',dict(action='resolve-admin-name',local_username='new-owner',initial_password=issued['admin_password']))
    assert rows(runtime,'SELECT count(*) FROM users')==[(1,)]
    assert grants(runtime)==[]


def test_conflict_resolution_does_not_overwrite_another_taken_name(issued_desktop):
    runtime,license,issued=issued_desktop
    conflicting_admin(runtime)
    with runtime.app.app_context():
        db=runtime.app.extensions['campaign_manager'].db()
        create_pending_account(db,'Other','new-owner',generate_password_hash('other-password'));db.commit()
    client,_=activate(runtime,issued)
    before=rows(runtime,'SELECT * FROM users')
    response=post(client,'/desktop/license',dict(action='resolve-admin-name',local_username='new-owner',initial_password=issued['admin_password']))
    assert 'Tên mới đã tồn tại' in response.text
    assert rows(runtime,'SELECT * FROM users')==before


def test_alias_requires_a_signed_admin_grant_and_an_actual_name_conflict(issued_desktop):
    runtime,license,issued=issued_desktop
    client=runtime.app.test_client()
    values=dict(action='resolve-admin-name',local_username='new-owner',initial_password=issued['admin_password'])
    post(client,'/desktop/license',values)
    assert rows(runtime,'SELECT count(*) FROM users')==[(0,)]
    license.activate(issued['key'])
    response=post(client,'/desktop/license',values)
    assert 'Tên được cấp không bị trùng' in response.text
    assert rows(runtime,'SELECT count(*) FROM users')==[(0,)]
    conflicting_admin(runtime)
    prefix,payload,signature=license.state['lease'].split('.')
    license.state['lease']='.'.join((prefix,payload,('A' if signature[0]!='A' else 'B')+signature[1:]))
    post(client,'/desktop/license',values)
    assert rows(runtime,'SELECT count(*) FROM users')==[(1,)]
    assert grants(runtime)==[]


def test_modified_unsigned_lease_cannot_create_admin(issued_desktop):
    from license_system.signatures import decode,encode
    runtime,license,issued=issued_desktop
    license.activate(issued['key'])
    prefix,payload,signature=license.state['lease'].split('.')
    claims=json.loads(decode(payload));claims['tool_admin']['username']='forged-admin'
    license.state['lease']='.'.join((prefix,encode(json.dumps(claims).encode()),signature))
    assert sync_license_admin(runtime.app,license) is None
    assert rows(runtime,'SELECT count(*) FROM users')==[(0,)]


def test_web_admin_cannot_enable_desktop_user_creation_by_posting_flags(app):
    runner=app.test_cli_runner()
    assert runner.invoke(args=['reset-admin'],input='web-password\nweb-password\n').exit_code==0
    client=app.test_client();post(client,'/login',dict(username='admin',password='web-password'))
    assert 'Tạo tài khoản trong tool' not in client.get('/admin/users').text
    assert post(client,'/admin/users/create',dict(name='No',username='no-user',password='staff888',confirm_password='staff888',desktop_license_enabled='1')).status_code==404
