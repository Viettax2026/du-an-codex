import sqlite3

import pytest
from flask import g
from werkzeug.security import generate_password_hash

from app import create_app
from desktop import recovery as windows_support
from runtime_lock import RuntimeLock
from test_workflow import app, post, register, token


def query(app, sql, args=()):
    with sqlite3.connect(app.config['DATABASE']) as connection:
        return connection.execute(sql, args).fetchall()


def admin_client(app):
    assert app.test_cli_runner().invoke(args=['reset-admin'], input='owner-password-123\nowner-password-123\n').exit_code == 0
    client = app.test_client()
    post(client, '/login', {'username':'admin','password':'owner-password-123'})
    return client


def submit(client, username='new-user', **extra):
    return post(client, '/register', dict(name='New user', username=username, password='secure-password', email='new@example.com', **extra))


def test_new_account_needs_explicit_approval_and_cannot_promote_itself(app):
    client = app.test_client()
    result = submit(client, role='admin', approval_status='approved', user_id='1')
    assert 'Chờ duyệt tài khoản' in result.text
    assert query(app, 'SELECT role,approval_status FROM users') == [('user','pending')]
    with client.session_transaction() as session:
        assert 'user_id' not in session
    assert client.get('/campaigns').status_code == 302
    assert 'chờ quản trị viên duyệt' in post(client,'/login',dict(username='new-user',password='secure-password')).text
    owner = admin_client(app)
    page = owner.get('/admin/users')
    assert page.status_code == 200 and 'new-user' in page.text
    result = post(owner, '/admin/users/1/status', {'status':'approved'})
    assert result.status_code == 200
    assert query(app,'SELECT approval_status,approved_by FROM users WHERE id=1') == [('approved',2)]
    post(client,'/login',dict(username='new-user',password='secure-password'))
    assert client.get('/campaigns').status_code == 200
    assert client.get('/admin/users').status_code == 403
    assert post(client,'/admin/users/2/status',{'status':'approved'}).status_code == 403


def test_cannot_register_reserved_admin_or_bypass_approval_with_a_forged_session(app):
    client = app.test_client()
    assert 'dành cho tài khoản quản trị' in submit(client,username='ADMIN').text
    assert query(app,'SELECT count(*) FROM users') == [(0,)]
    submit(client)
    with client.session_transaction() as session:
        session['user_id']=1
        session['auth_version']=0
        session['role']='admin'
    assert client.get('/admin/users').status_code == 302
    assert client.get('/contacts').status_code == 302


def test_only_admin_can_approve_and_csrf_is_required(app):
    owner=admin_client(app)
    guest=app.test_client(); submit(guest)
    assert guest.get('/admin/users').status_code == 302
    assert guest.post('/admin/users/2/status',data={'csrf':token(guest),'status':'approved'}).status_code == 302
    assert owner.post('/admin/users/2/status',data={'status':'approved'}).status_code == 400
    assert query(app,'SELECT approval_status FROM users WHERE id=2') == [('pending',)]
    assert post(owner,'/admin/users/1/status',{'status':'blocked'}).status_code == 400
    assert post(owner,'/admin/users/2/status',{'status':'pending'}).status_code == 400
    assert post(owner,'/admin/users/999/status',{'status':'approved'}).status_code == 404
    assert query(app,'SELECT role,approval_status FROM users WHERE id=1') == [('admin','approved')]


def test_rejected_and_blocked_accounts_cannot_login_but_can_be_approved_later(app):
    owner=admin_client(app); client=app.test_client(); submit(client)
    for state in ('rejected','blocked'):
        assert post(owner,'/admin/users/2/status',{'status':state}).status_code == 200
        assert 'chưa được phép đăng nhập' in post(client,'/login',dict(username='new-user',password='secure-password')).text
        with client.session_transaction() as session:
            assert 'user_id' not in session
    post(owner,'/admin/users/2/status',{'status':'approved'})
    post(client,'/login',dict(username='new-user',password='secure-password'))
    assert client.get('/contacts').status_code == 200
    assert query(app,"SELECT action FROM account_approval_events WHERE user_id=2 ORDER BY id") == [('rejected',),('blocked',),('approved',)]


def test_block_revokes_live_sessions_and_api_and_preserves_data(app):
    owner=admin_client(app)
    client=app.test_client(); register(client)
    post(client,'/contacts',dict(name='Lan',phone='0901234567'))
    result=post(client,'/integrations',dict(name='Test integration',scopes=['data:read'],days='30'))
    import re
    key=re.search(r'zf_[A-Za-z0-9_-]{43}',result.text).group(0)
    assert client.get('/api/v1/data-groups',headers={'Authorization':'Bearer '+key}).status_code == 200
    snapshot=query(app,'SELECT * FROM contacts')
    post(owner,'/admin/users/2/status',dict(status='blocked'))
    assert client.get('/contacts').status_code == 302
    assert client.get('/api/v1/data-groups',headers={'Authorization':'Bearer '+key}).status_code == 401
    assert query(app,'SELECT * FROM contacts') == snapshot
    post(owner,'/admin/users/2/status',dict(status='approved'))
    assert client.get('/contacts').status_code == 302
    post(client,'/login',dict(username='an01',password='secure-password'))
    assert 'Lan' in client.get('/contacts').text


def test_password_recovery_never_approves_pending_account(app):
    client=app.test_client(); submit(client)
    output=app.test_cli_runner().invoke(args=['issue-recovery-code','--username','new-user']).output
    import re
    code=re.search(r'ZFR-(?:[A-F0-9]{4}-){7}[A-F0-9]{4}',output).group(0)
    post(client,'/forgot-password',dict(username='new-user',recovery_code=code,password='new-password-123',confirm_password='new-password-123'))
    assert query(app,'SELECT approval_status FROM users') == [('pending',)]
    assert 'chờ quản trị viên duyệt' in post(client,'/login',dict(username='new-user',password='new-password-123')).text


def test_migration_preserves_existing_access_but_new_users_still_wait(tmp_path):
    database=tmp_path/'legacy.sqlite3'
    old_hash=generate_password_hash('legacy-password')
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,name TEXT,username TEXT UNIQUE,password TEXT)')
        connection.execute('INSERT INTO users VALUES(7,?,?,?)',('Owner','admin',old_hash))
    config={'TESTING':True,'DATABASE':str(database),'SECRET_KEY':'test-only'}
    app=create_app(config); client=app.test_client()
    post(client,'/login',dict(username='admin',password='legacy-password'))
    assert client.get('/contacts').status_code == 200
    assert client.get('/admin/users').status_code == 403
    submit(app.test_client())
    create_app(config)
    assert query(app,'SELECT username,approval_status,role FROM users ORDER BY id') == [('admin','approved','user'),('new-user','pending','user')]
    assert app.test_cli_runner().invoke(args=['grant-admin','--username','admin']).exit_code == 0
    assert query(app,'SELECT password FROM users WHERE id=7') == [(old_hash,)]
    assert client.get('/admin/users').status_code == 302
    post(client,'/login',dict(username='admin',password='legacy-password'))
    assert client.get('/admin/users').status_code == 200
    assert query(app,'SELECT username,approval_status FROM users WHERE id=8') == [('new-user','pending')]


def test_cli_unknown_account_does_not_create_user_and_grant_does_not_change_password(app):
    runner=app.test_cli_runner()
    assert runner.invoke(args=['grant-admin','--username','missing']).exit_code != 0
    assert runner.invoke(args=['approve-user','--username','missing']).exit_code != 0
    assert query(app,'SELECT count(*) FROM users') == [(0,)]
    client=app.test_client(); submit(client)
    before=query(app,'SELECT password FROM users')
    assert runner.invoke(args=['grant-admin','--username',' NEW-USER ']).exit_code == 0
    assert query(app,'SELECT password FROM users') == before
    assert query(app,'SELECT role,approval_status FROM users') == [('admin','approved')]


def test_locked_account_scheduler_and_new_claims_are_stopped(app,monkeypatch):
    owner=admin_client(app); client=app.test_client(); register(client)
    post(client,'/campaigns',dict(name='Unsent',message='Hello'))
    with app.app_context():
        db=app.extensions['campaign_manager'].db()
        db.execute("UPDATE campaigns SET schedule_enabled=1,paused=0,schedule_error='' WHERE id=1")
        db.commit()
    post(owner,'/admin/users/2/status',dict(status='blocked'))
    scheduler=app.extensions['campaign_scheduler']
    called=[]
    monkeypatch.setattr(scheduler,'tick_campaign',lambda *args:called.append(args))
    with app.app_context():
        scheduler.tick()
        assert called == []
        manager=app.extensions['campaign_manager']; campaign=manager.db().execute('SELECT * FROM campaigns WHERE id=1').fetchone()
        with pytest.raises(Exception) as error:
            manager.require_active(campaign)
        assert getattr(error.value,'code',None) == 403
    assert query(app,'SELECT count(*) FROM campaign_attempts') == [(0,)]


def test_logout_button_in_shared_header_and_logout_clears_auth(app):
    client=app.test_client(); register(client)
    for path in ('/account/security','/campaigns','/accounts','/contacts','/data-groups','/media','/integrations','/settings'):
        page=client.get(path)
        assert page.status_code == 200
        assert 'aria-label="Đăng xuất tài khoản"' in page.text
        assert 'session-controls.css' in page.text
    assert client.post('/logout').status_code == 400
    post(client,'/logout')
    assert client.get('/account/security').status_code == 302


def test_windows_first_admin_requires_os_admin_closed_tool_and_existing_account(tmp_path,monkeypatch):
    root=tmp_path/'Windows data'
    app=create_app({'TESTING':True},instance_path=root/'instance')
    client=app.test_client(); submit(client)
    monkeypatch.setattr(windows_support,'windows_admin',lambda:False)
    with pytest.raises(RuntimeError):windows_support.grant_local_admin(root,'new-user')
    assert query(app,'SELECT role FROM users') == [('user',)]
    monkeypatch.setattr(windows_support,'windows_admin',lambda:True)
    with RuntimeLock(root/'desktop.lock'):
        with pytest.raises(RuntimeError):windows_support.grant_local_admin(root,'new-user')
    windows_support.grant_local_admin(root,'new-user')
    assert query(app,'SELECT role,approval_status FROM users') == [('admin','approved')]
