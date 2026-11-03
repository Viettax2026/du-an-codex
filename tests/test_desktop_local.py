"""The owner's separate local edition: no activation, isolated data and local roles."""
import json
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from desktop.local_runtime import LocalDesktopRuntime,default_local_data_root
from desktop.runtime import DesktopRuntime,default_data_root
from test_workflow import app,post


@pytest.fixture
def local(tmp_path):
    runtime=LocalDesktopRuntime(tmp_path/'local',config={'TESTING':True,'ZALO_QR_ENABLED':False})
    try:yield runtime
    finally:runtime.stop(5)


def rows(local,sql,args=()):
    with sqlite3.connect(local.app.config['DATABASE']) as db:return db.execute(sql,args).fetchall()


def signup(client,name='local-owner'):
    return post(client,'/register',dict(name=name,username=name,password='local-password',role='admin',approval_status='blocked'))


def test_local_first_account_is_admin_and_other_users_can_login_without_activation(local):
    client=local.app.test_client()
    assert local.license is None and local.license_worker is None
    assert client.get('/desktop/license').status_code==404
    assert 'Bản quyền / Nhập key' not in client.get('/login').text
    assert 'Tài khoản đầu tiên' in client.get('/register').text
    assert 'Đã tạo tài khoản quản trị đầu tiên' in signup(client).text
    assert rows(local,'SELECT username,role,approval_status,email FROM users')==[('local-owner','admin','approved','')]
    post(client,'/login',dict(username='local-owner',password='local-password'))
    assert 'Tạo tài khoản trong tool' in client.get('/admin/users').text
    assert 'dùng chung key' not in client.get('/admin/users').text
    response=post(client,'/admin/users/create',dict(name='Staff',username='staff-one',password='staff888',confirm_password='staff888'))
    assert 'Đã tạo tài khoản thường' in response.text
    other=local.app.test_client();signup(other,'self-signup')
    assert rows(local,"SELECT role,approval_status FROM users WHERE username='self-signup'")==[('user','approved')]
    post(other,'/login',dict(username='self-signup',password='local-password'))
    assert other.get('/contacts').status_code==200
    assert other.get('/admin/users').status_code==403
    assert other.get('/registration-pending').location.endswith('/login')


def test_only_one_first_administrator_can_be_created_concurrently(local):
    barrier=threading.Barrier(2)
    def register(name):
        client=local.app.test_client();client.get('/register');barrier.wait(5)
        return signup(client,name).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(register,['owner-one','owner-two']))==[200,200]
    assert rows(local,"SELECT count(*) FROM users WHERE role='admin'")==[(1,)]
    assert rows(local,'SELECT count(*) FROM users')==[(2,)]


def test_retired_accounts_do_not_reopen_first_admin_bootstrap(local):
    with sqlite3.connect(local.app.config['DATABASE']) as db:db.execute('INSERT INTO retired_user_ids VALUES(7)')
    signup(local.app.test_client())
    assert rows(local,'SELECT id,role FROM users')==[(8,'user')]


def test_local_still_requires_csrf_and_preserves_explicit_account_blocks(local):
    client=local.app.test_client()
    assert client.post('/register',data=dict(name='Bad',username='bad',password='local-password')).status_code==400
    signup(client)
    other=local.app.test_client();signup(other,'blocked-user')
    with sqlite3.connect(local.app.config['DATABASE']) as db:
        db.execute("UPDATE users SET approval_status='blocked' WHERE username='blocked-user'")
    response=post(other,'/login',dict(username='blocked-user',password='local-password'))
    assert 'chưa được phép đăng nhập' in response.text
    assert rows(local,"SELECT approval_status FROM users WHERE username='blocked-user'")==[('blocked',)]


def test_web_cannot_enable_local_administration_by_submitting_flags(app):
    client=app.test_client()
    post(client,'/register',dict(name='Web',username='web-user',password='local-password',email='web@example.com',desktop_local='1',DESKTOP_LOCAL='1',role='admin'))
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT role,approval_status FROM users').fetchall()==[('user','pending')]


def test_normal_desktop_still_constructs_its_license_client(tmp_path,monkeypatch):
    from desktop import licensing
    fake=SimpleNamespace(allowed=lambda:False)
    constructor=Mock(return_value=fake);monkeypatch.setattr(licensing,'DesktopLicense',constructor)
    runtime=DesktopRuntime(tmp_path/'licensed',config={'DESKTOP_LOCAL':True})
    try:
        constructor.assert_called_once()
        assert runtime.license is fake and 'desktop_local' not in runtime.app.extensions
    finally:runtime.stop(5)


def test_data_is_separate_and_scheduler_runs_without_license_modules(tmp_path,monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    assert default_data_root()!=default_local_data_root()
    code='''import json,sys,threading
from desktop.local_runtime import LocalDesktopRuntime
tick=threading.Event()
runtime=LocalDesktopRuntime(sys.argv[1],tick=tick.set)
try:
 runtime.start();runtime.activate();assert tick.wait(5)
 assert runtime.license is None and runtime.license_worker is None
 assert not [m for m in sys.modules if m.startswith(('desktop.licensing','license_system'))]
 print(json.dumps({'no_key':True,'scheduler':True}))
finally:assert runtime.stop(5)
'''
    result=subprocess.run([sys.executable,'-c',code,str(tmp_path/'isolated')],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)==dict(no_key=True,scheduler=True)
