import sqlite3

import pytest

import app as app_module
from desktop.runtime import DesktopRuntime
from test_workflow import post, token


class License:
    def __init__(self, valid=True):
        self.valid = valid

    def allowed(self):
        return self.valid

    def status(self):
        return dict(claims=None, error='', activated=self.valid, allowed=self.valid, device='synthetic-device', can_deactivate=False)


@pytest.fixture
def desktop(tmp_path):
    license = License()
    runtime = DesktopRuntime(tmp_path/'desktop', config={'TESTING':True}, license=license)
    try:
        yield runtime.app, license
    finally:
        runtime.stop()


def query(app, sql, args=()):
    with sqlite3.connect(app.config['DATABASE']) as connection:
        return connection.execute(sql, args).fetchall()


def signup(client):
    return post(client, '/register', dict(name='Windows user',username='desktop-user',email='owner@example.com',password='pass8888',
                                         role='admin',approval_status='approved',email_verified='1'))


def test_licensed_tool_registers_and_logs_in_without_approval(desktop):
    app, license = desktop
    client = app.test_client()
    assert 'href="/register"' in client.get('/desktop/license').text
    assert 'chờ quản trị viên duyệt' not in client.get('/register').text.lower()
    result = signup(client)
    assert 'Đăng ký thành công.' in result.text and result.request.path=='/login'
    assert query(app,'SELECT role,approval_status,email_verified FROM users')==[('user','approved',0)]
    with client.session_transaction() as session:
        assert 'user_id' not in session
    post(client,'/login',dict(username='desktop-user',password='pass8888'))
    assert client.get('/contacts').status_code==200
    assert client.get('/admin/users').status_code==403
    assert client.get('/registration-pending').location.endswith('/login')


def test_unlicensed_or_expired_tool_cannot_create_accounts(desktop):
    app, license = desktop
    client = app.test_client()
    csrf = token(client,'/login')
    license.valid=False
    assert client.get('/register').location.endswith('/desktop/license')
    response=client.post('/register',data=dict(csrf=csrf,name='No license',username='desktop-user',email='owner@example.com',password='pass8888'))
    assert response.location.endswith('/desktop/license')
    assert query(app,'SELECT count(*) FROM users')==[(0,)]


def test_license_expiring_during_registration_creates_no_account(desktop,monkeypatch):
    app, license = desktop
    client=app.test_client(); csrf=token(client,'/login')
    original=app_module.generate_password_hash
    def expire(password):
        result=original(password);license.valid=False;return result
    monkeypatch.setattr(app_module,'generate_password_hash',expire)
    response=client.post('/register',data=dict(csrf=csrf,name='Expired',username='desktop-user',email='owner@example.com',password='pass8888'))
    assert 'Kích hoạt key' in response.text
    assert query(app,'SELECT count(*) FROM users')==[(0,)]


def test_old_pending_desktop_user_can_login_with_own_password_and_valid_key(desktop):
    app, license = desktop
    client=app.test_client();signup(client)
    with sqlite3.connect(app.config['DATABASE']) as connection:
        connection.execute("UPDATE users SET approval_status='pending'")
    before=query(app,'SELECT password,id FROM users')
    post(client,'/login',dict(username='desktop-user',password='incorrect'))
    assert query(app,'SELECT approval_status FROM users')==[('pending',)]
    license.valid=False
    post(client,'/login',dict(username='desktop-user',password='pass8888'))
    assert query(app,'SELECT approval_status FROM users')==[('pending',)]
    license.valid=True
    post(client,'/login',dict(username='desktop-user',password='pass8888'))
    assert client.get('/contacts').status_code==200
    assert query(app,'SELECT approval_status,role FROM users')==[('approved','user')]
    assert query(app,'SELECT password,id FROM users')==before


@pytest.mark.parametrize('state',['blocked','rejected'])
def test_self_registration_does_not_reopen_explicitly_blocked_accounts(desktop,state):
    app, license=desktop
    client=app.test_client();signup(client)
    with sqlite3.connect(app.config['DATABASE']) as connection:
        connection.execute('UPDATE users SET approval_status=?',(state,))
    post(client,'/login',dict(username='desktop-user',password='pass8888'))
    assert query(app,'SELECT approval_status FROM users')==[(state,)]
    with client.session_transaction() as session:
        assert 'user_id' not in session


def test_concurrent_password_change_does_not_approve_or_authenticate_stale_password(desktop,monkeypatch):
    app, license=desktop
    client=app.test_client();signup(client)
    with sqlite3.connect(app.config['DATABASE']) as connection:
        connection.execute("UPDATE users SET approval_status='pending'")
    original=app_module.check_password_hash
    def reset_while_checking(digest,password):
        valid=original(digest,password)
        with sqlite3.connect(app.config['DATABASE']) as connection:
            connection.execute('UPDATE users SET password=?,auth_version=auth_version+1',
                               (app_module.generate_password_hash('changed-password'),))
        return valid
    monkeypatch.setattr(app_module,'check_password_hash',reset_while_checking)
    post(client,'/login',dict(username='desktop-user',password='pass8888'))
    assert query(app,'SELECT approval_status FROM users')==[('pending',)]
    with client.session_transaction() as session:
        assert 'user_id' not in session
