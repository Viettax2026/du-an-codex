import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from werkzeug.security import check_password_hash

import account_recovery
from app import create_app
from desktop.runtime import DesktopRuntime
from desktop import recovery as windows_recovery
from runtime_lock import RuntimeLock
from test_workflow import app, post, register, token
from types import SimpleNamespace


def query(app, sql, args=()):
    with sqlite3.connect(app.config['DATABASE']) as connection:
        return connection.execute(sql, args).fetchall()


def create_code(client):
    result = post(client, '/account/security', {'current_password': 'secure-password'})
    return re.search(r'<code id="issued-recovery-code">(ZFR-[A-F0-9-]+)</code>', result.text).group(1)


def reset(client, username, code, password='a-new-password-123'):
    return post(client, '/forgot-password', dict(username=username, recovery_code=code,
        password=password, confirm_password=password))


def test_login_link_setup_requires_current_password_and_never_saves_plaintext(app):
    client = app.test_client()
    assert 'href="/forgot-password"' in client.get('/login').text
    assert client.get('/account/security').status_code == 302
    register(client)
    assert 'Chưa có mã khôi phục' in client.get('/account/security').text
    assert 'chưa đúng' in post(client, '/account/security', {'current_password': 'wrong'}).text
    assert query(app, 'SELECT * FROM account_recovery_codes') == []
    code = create_code(client)
    stored = query(app, 'SELECT digest,kind,expires_at FROM account_recovery_codes')
    assert stored == [(account_recovery.code_digest(code), 'personal', None)]
    assert code not in client.get('/account/security').text
    with client.session_transaction() as session:
        assert code not in repr(dict(session))
    assert 'no-store' in client.get('/account/security').headers['Cache-Control']


def test_reset_is_single_use_revokes_sessions_and_preserves_campaign_data(app):
    alice = app.test_client(); register(alice)
    bob = app.test_client(); register(bob, 'bob01')
    other_browser = app.test_client()
    post(other_browser, '/login', {'username': 'an01', 'password': 'secure-password'})
    post(alice, '/contacts', {'name': 'Lan', 'phone': '0901234567', 'consent': 'on'})
    post(alice, '/campaigns', {'name': 'Thông báo', 'message': 'Xin chào {{name}}'})
    post(alice, '/campaigns/1')
    tables = [row[0] for row in query(app, "SELECT name FROM sqlite_master WHERE type='table'")
              if row[0] != 'users' and not row[0].startswith('account_recovery_')]
    before = {name: query(app, f'SELECT * FROM "{name}"') for name in tables}
    code = create_code(alice)
    post(alice, '/logout')
    result = reset(alice, ' AN01 ', code.lower().replace('-', ' '))
    assert 'Đã đặt mật khẩu mới.' in result.text
    assert 'Đăng nhập' in result.text
    assert query(app, 'SELECT * FROM account_recovery_codes') == []
    assert {name: query(app, f'SELECT * FROM "{name}"') for name in tables} == before
    assert other_browser.get('/contacts').status_code == 302
    assert bob.get('/contacts').status_code == 200
    assert 'không hợp lệ' in reset(alice, 'an01', code).text
    post(alice, '/login', {'username': 'an01', 'password': 'secure-password'})
    with alice.session_transaction() as session:
        assert 'user_id' not in session
    post(alice, '/login', {'username': 'an01', 'password': 'a-new-password-123'})
    assert 'Lan' in alice.get('/contacts').text


def test_replacing_code_invalidates_old_code_and_codes_are_tenant_scoped(app):
    alice = app.test_client(); register(alice)
    first = create_code(alice)
    second = create_code(alice)
    assert first != second
    stranger = app.test_client(); register(stranger, 'bob01')
    before = query(app, 'SELECT password FROM users ORDER BY id')
    for username, code in [('an01', first), ('bob01', second), ('absent', second), ('an01', 'not-a-code')]:
        result = reset(stranger, username, code)
        assert 'Tài khoản hoặc mã khôi phục không hợp lệ' in result.text
        assert code not in result.text
    assert query(app, 'SELECT password FROM users ORDER BY id') == before
    assert 'Đã đặt mật khẩu mới.' in reset(stranger, 'an01', second).text


def test_bad_password_confirmation_and_csrf_never_consume_code(app):
    client = app.test_client(); register(client); code = create_code(client)
    post(client, '/logout')
    assert client.post('/forgot-password', data={'username': 'an01', 'recovery_code': code}).status_code == 400
    assert '10 đến 256' in reset(client, 'an01', code, password='short').text
    result = post(client, '/forgot-password', dict(username='an01', recovery_code=code,
        password='a-new-password-123', confirm_password='different-password'))
    assert 'chưa trùng nhau' in result.text
    assert len(query(app, 'SELECT * FROM account_recovery_codes')) == 1
    assert 'Đã đặt mật khẩu mới.' in reset(client, 'an01', code).text


def test_owner_support_code_expires_and_is_separate_from_personal_code(app, monkeypatch):
    client = app.test_client(); register(client); personal = create_code(client)
    runner = app.test_cli_runner()
    unknown = runner.invoke(args=['issue-recovery-code', '--username', 'missing'])
    assert unknown.exit_code != 0
    monkeypatch.setattr(account_recovery.time, 'time', lambda: 1000000000)
    result = runner.invoke(args=['issue-recovery-code', '--username', ' AN01 '])
    assert result.exit_code == 0
    support = re.search(r'ZFR-(?:[A-F0-9]{4}-){7}[A-F0-9]{4}', result.output).group(0)
    assert query(app, "SELECT expires_at FROM account_recovery_codes WHERE kind='support'") == [(1000000900,)]
    monkeypatch.setattr(account_recovery.time, 'time', lambda: 1000000900)
    assert 'không hợp lệ' in reset(client, 'an01', support).text
    assert 'Đã đặt mật khẩu mới.' in reset(client, 'an01', personal).text


def test_support_code_rotation_and_reset_admin_revoke_all_recovery_codes(app):
    client = app.test_client(); register(client, 'admin')
    personal = create_code(client)
    runner = app.test_cli_runner()
    issued = [runner.invoke(args=['issue-recovery-code', '--username', 'admin']).output for _ in range(2)]
    codes = [re.search(r'ZFR-(?:[A-F0-9]{4}-){7}[A-F0-9]{4}', text).group(0) for text in issued]
    assert 'không hợp lệ' in reset(client, 'admin', codes[0]).text
    assert runner.invoke(args=['reset-admin'], input='new-admin-password\nnew-admin-password\n').exit_code == 0
    assert client.get('/contacts').status_code == 302
    assert query(app, 'SELECT * FROM account_recovery_codes') == []
    assert 'không hợp lệ' in reset(client, 'admin', personal).text
    assert 'không hợp lệ' in reset(client, 'admin', codes[1]).text


def test_attempt_limits_are_durable_and_do_not_consume_code(app):
    client = app.test_client(); register(client); code = create_code(client)
    for _ in range(8):
        assert reset(client, 'an01', 'invalid').status_code == 200
    assert reset(client, 'an01', code).status_code == 429
    restarted = create_app(dict(app.config)).test_client()
    assert reset(restarted, 'an01', code).status_code == 429
    assert len(query(app, 'SELECT * FROM account_recovery_codes')) == 1


def test_rate_limits_accept_only_the_web_local_proxy_ip(app):
    with app.test_request_context(headers={'X-Real-IP':'203.0.113.7'}, environ_base={'REMOTE_ADDR':'127.0.0.1'}):
        assert account_recovery.client_address(app) == '203.0.113.7'
    with app.test_request_context(headers={'X-Real-IP':'203.0.113.7'}, environ_base={'REMOTE_ADDR':'198.51.100.2'}):
        assert account_recovery.client_address(app) == '198.51.100.2'
    with app.test_request_context(headers={'X-Forwarded-For':'203.0.113.7','X-Real-IP':'invalid'}, environ_base={'REMOTE_ADDR':'127.0.0.1'}):
        assert account_recovery.client_address(app) == '127.0.0.1'
    app.extensions['desktop_license'] = object()
    with app.test_request_context(headers={'X-Real-IP':'203.0.113.7'}, environ_base={'REMOTE_ADDR':'127.0.0.1'}):
        assert account_recovery.client_address(app) == '127.0.0.1'


def test_recovery_remains_available_when_desktop_license_expires(tmp_path):
    license = SimpleNamespace(allowed=lambda: False)
    runtime = DesktopRuntime(tmp_path/'desktop', config={'TESTING':True}, license=license)
    try:
        with runtime.app.app_context():
            connection = runtime.app.extensions['campaign_manager'].db()
            connection.execute("INSERT INTO users(name,username,password) VALUES ('An','an01',?)",
                               (account_recovery.generate_password_hash('secure-password'),))
            connection.commit()
        client = runtime.app.test_client()
        assert client.get('/forgot-password').status_code == 200
        csrf = token(client, '/login')
        assert client.post('/login', data=dict(csrf=csrf,username='an01',password='secure-password')).status_code == 302
        assert client.get('/account/security').status_code == 200
        assert client.get('/campaigns').location.endswith('/desktop/license')
        assert runtime.worker is None
    finally:
        runtime.stop()


def test_two_simultaneous_resets_cannot_reuse_one_code(app):
    owner = app.test_client(); register(owner); code = create_code(owner)
    clients = [app.test_client(), app.test_client()]
    tokens = [token(client) for client in clients]
    def submit(index):
        password = f'new-password-{index}'
        return clients[index].post('/forgot-password', data=dict(csrf=tokens[index], username='an01',
            recovery_code=code, password=password, confirm_password=password)).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(submit, [0, 1])) == [200, 302]
    assert query(app, 'SELECT * FROM account_recovery_codes') == []
    assert query(app, 'SELECT auth_version FROM users') == [(1,)]


def test_web_and_windows_data_do_not_share_codes(app, tmp_path):
    owner = app.test_client(); register(owner); code = create_code(owner)
    independent = create_app({'TESTING': True}, instance_path=tmp_path / 'other-instance')
    client = independent.test_client(); register(client)
    assert 'không hợp lệ' in reset(client, 'an01', code).text
    assert 'Đã đặt mật khẩu mới.' in reset(owner, 'an01', code).text


def test_windows_support_requires_admin_existing_data_and_closed_app(tmp_path, monkeypatch):
    root = tmp_path / 'Dữ liệu Windows'
    monkeypatch.setattr(windows_recovery, 'windows_admin', lambda: False)
    with pytest.raises(RuntimeError, match='quản trị viên Windows'):
        windows_recovery.issue_local_support_code(root, 'an01')
    assert not root.exists()
    monkeypatch.setattr(windows_recovery, 'windows_admin', lambda: True)
    with pytest.raises(RuntimeError, match='Không tìm thấy dữ liệu'):
        windows_recovery.issue_local_support_code(root, 'an01')
    app = create_app({'TESTING': True}, instance_path=root / 'instance')
    client = app.test_client(); register(client)
    with RuntimeLock(root / 'desktop.lock'):
        with pytest.raises(RuntimeError):
            windows_recovery.issue_local_support_code(root, 'an01')
    with pytest.raises(RuntimeError, match='Không tìm thấy tài khoản'):
        windows_recovery.issue_local_support_code(root, 'wrong')
    code = windows_recovery.issue_local_support_code(root, 'an01')
    assert len(query(app, 'SELECT * FROM users')) == 1
    assert 'Đã đặt mật khẩu mới.' in reset(client, 'an01', code).text
