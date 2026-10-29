import json
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from werkzeug.security import check_password_hash

import email_recovery as recovery
from app import create_app
from test_workflow import app, post, register


def query(app, sql, args=()):
    with sqlite3.connect(app.config['DATABASE']) as connection:
        return connection.execute(sql, args).fetchall()


@pytest.fixture
def outbox(app, monkeypatch):
    app.config.update(SMTP_HOST='smtp.example.test', SMTP_FROM='sender@example.com', SMTP_SECURITY='starttls')
    messages = []
    monkeypatch.setattr(recovery, 'deliver', lambda app, email, code, purpose: messages.append((email, code, purpose)))
    return messages


def verify_email(client, outbox, email='an@example.com'):
    post(client, '/account/security/email', dict(email=email, current_password='secure-password'))
    assert outbox[-1][0] == email and outbox[-1][2] == 'verify'
    code = outbox[-1][1]
    assert 'Đã xác minh email.' in post(client, '/account/security/email', dict(action='verify', email=email, code=code)).text


def send_reset(client, email='an@example.com', username='an01'):
    return post(client, '/forgot-password/email', dict(action='request', username=username, email=email))


def reset(client, code, email='an@example.com', username='an01', **extra):
    return post(client, '/forgot-password/email', dict(action='reset', username=username, email=email, code=code,
        password='changed-password-123', confirm_password='changed-password-123', **extra))


def clear_cooldown(app):
    # Tests skip simulated waiting without clearing attempt budgets in scenarios
    # which test the durable limits themselves.
    with sqlite3.connect(app.config['DATABASE']) as connection:
        connection.execute('DELETE FROM account_email_limits')


def test_registration_requires_email_and_never_trusts_verification_form_fields(app):
    client = app.test_client()
    for email in ('', 'invalid', 'bad\r\nBcc: victim@example.com', '.bad@example.com', 'a@-bad.com'):
        result = post(client, '/register', dict(name='An', username='an01', password='secure-password', email=email))
        assert 'email hợp lệ' in result.text
    assert query(app, 'SELECT count(*) FROM users') == [(0,)]
    result = post(client, '/register', dict(name='An', username='an01', password='secure-password', email=' AN@EXAMPLE.COM ', email_verified='1'))
    assert 'Chờ duyệt' in result.text
    assert query(app, 'SELECT email,email_verified,approval_status FROM users') == [('an@example.com', 0, 'pending')]


def test_email_verification_requires_password_and_correct_owner_code(app, outbox):
    client = app.test_client(); register(client)
    post(client, '/account/security/email', dict(email='new@example.com', current_password='wrong'))
    assert not outbox and query(app, 'SELECT email_verified FROM users') == [(0,)]
    clear_cooldown(app)
    post(client, '/account/security/email', dict(email='new@example.com', current_password='secure-password'))
    code = outbox[-1][1]
    assert re.fullmatch(r'[0-9]{5}', code)
    stored = query(app, 'SELECT id,digest FROM account_email_codes')[0]
    assert stored[1] != code and stored[1] == recovery.code_digest(app, stored[0], code)
    assert code not in client.get('/account/security').text
    assert 'không hợp lệ' in post(client, '/account/security/email', dict(action='verify', email='other@example.com', code=code)).text
    assert query(app, 'SELECT email,email_verified FROM users') == [('an@example.com',0)]
    assert 'Đã xác minh email' in post(client, '/account/security/email', dict(action='verify', email='new@example.com', code=code)).text
    assert query(app, 'SELECT email,email_verified FROM users') == [('new@example.com',1)]
    assert not query(app, 'SELECT * FROM account_email_codes')


def test_reset_single_use_invalidates_all_sessions_codes_and_keeps_data(app, outbox):
    client=app.test_client(); register(client)
    verify_email(client, outbox)
    other=app.test_client(); post(other, '/login', dict(username='an01', password='secure-password'))
    post(client, '/contacts', dict(name='Keep customer',phone='0901234567'))
    post(client, '/campaigns', dict(name='Keep campaign',message='Hello'))
    contacts=query(app,'SELECT * FROM contacts'); campaigns=query(app,'SELECT * FROM campaigns')
    app.test_cli_runner().invoke(args=['issue-recovery-code','--username','an01'])
    clear_cooldown(app)
    assert 'mã 5 số' in send_reset(client).text
    code=outbox[-1][1]
    epoch=query(app,'SELECT auth_version FROM users')[0][0]
    result=reset(client,code)
    assert 'Đã đặt mật khẩu mới.' in result.text
    assert query(app,'SELECT * FROM contacts') == contacts and query(app,'SELECT * FROM campaigns') == campaigns
    assert query(app,'SELECT auth_version,email_verified,approval_status FROM users') == [(epoch+1,1,'approved')]
    assert not query(app,'SELECT * FROM account_email_codes') and not query(app,'SELECT * FROM account_recovery_codes')
    assert other.get('/account/security').status_code == 302
    assert client.get('/contacts').status_code == 302
    assert 'không hợp lệ' in reset(client,code).text
    post(client,'/login',dict(username='an01',password='changed-password-123'))
    assert 'Keep customer' in client.get('/contacts').text


def test_send_response_does_not_disclose_accounts_or_unverified_emails(app, outbox):
    client=app.test_client(); register(client)
    results=[]
    for username,email in [('an01','an@example.com'),('missing','missing@example.com'),('an01','wrong@example.com')]:
        result=send_reset(client,email,username)
        assert result.status_code == 200
        results.append(re.findall(r'<div role="status"[^>]*>(.*?)</div>',result.text))
    assert results[0] == results[1] == results[2]
    assert outbox == []


def test_codes_expire_are_purpose_scoped_and_preserve_leading_zero(app, outbox, monkeypatch):
    clock=[1_800_000_000]
    monkeypatch.setattr(recovery.time,'time',lambda: clock[0])
    monkeypatch.setattr(recovery.secrets,'randbelow',lambda n: 7)
    client=app.test_client(); register(client)
    post(client,'/account/security/email',dict(email='an@example.com',current_password='secure-password'))
    assert outbox[-1][1] == '00007'
    assert 'không hợp lệ' in reset(client,'00007').text
    clock[0]+=600
    assert 'không hợp lệ' in post(client,'/account/security/email',dict(action='verify',email='an@example.com',code='00007')).text
    verify_email(client,outbox)
    clock[0]+=61
    send_reset(client)
    clock[0]+=600
    assert 'không hợp lệ' in reset(client,'00007').text


def test_five_wrong_guesses_lock_code_even_when_ip_changes(app,outbox):
    client=app.test_client(); register(client); verify_email(client,outbox)
    clear_cooldown(app); send_reset(client)
    correct=outbox[-1][1]; wrong='99999' if correct!='99999' else '11111'
    for n in range(5):
        assert 'không hợp lệ' in reset(client,wrong).text
    assert query(app,'SELECT attempts FROM account_email_codes') == [(5,)]
    assert 'không hợp lệ' in reset(client,correct).text
    restarted=create_app(dict(app.config)).test_client()
    assert 'không hợp lệ' in reset(restarted,correct).text
    assert check_password_hash(query(app,'SELECT password FROM users')[0][0],'secure-password')


def test_resend_cooldown_replaces_old_code_and_has_durable_hourly_limit(app,outbox,monkeypatch):
    clock=[1_800_000_000]; monkeypatch.setattr(recovery.time,'time',lambda: clock[0])
    client=app.test_client(); register(client); verify_email(client,outbox)
    clear_cooldown(app)
    send_reset(client); first=outbox[-1][1]
    send_reset(client); assert len(outbox)==2  # verify + one reset
    clock[0]+=61
    send_reset(client); second=outbox[-1][1]
    assert 'không hợp lệ' in reset(client,first).text
    for _ in range(2):
        clock[0]+=61; send_reset(client)
    sent=len(outbox)
    restarted=create_app(dict(app.config)).test_client()
    clock[0]+=61; send_reset(restarted)
    assert len(outbox)==sent  # five requests/hour includes suppressed cooldown request
    assert 'Đã đặt mật khẩu mới.' in reset(client,outbox[-1][1]).text


def test_concurrent_consumption_has_one_winner(app,outbox):
    client=app.test_client(); register(client); verify_email(client,outbox)
    clear_cooldown(app); send_reset(client); code=outbox[-1][1]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:reset(app.test_client(),code).text,range(2)))
    assert sum('Đã đặt mật khẩu mới.' in text for text in results)==1


def test_changing_email_requires_new_mailbox_proof_and_revokes_old_reset(app,outbox):
    client=app.test_client(); register(client); verify_email(client,outbox)
    clear_cooldown(app); send_reset(client); old_reset=outbox[-1][1]
    clear_cooldown(app)
    post(client,'/account/security/email',dict(email='new@example.com',current_password='secure-password'))
    verify=outbox[-1][1]
    assert query(app,'SELECT email,email_verified FROM users') == [('an@example.com',1)]
    post(client,'/account/security/email',dict(action='verify',email='new@example.com',code=verify))
    assert query(app,'SELECT email,email_verified FROM users') == [('new@example.com',1)]
    assert 'không hợp lệ' in reset(client,old_reset).text


def test_reset_does_not_approve_blocked_or_pending_account(app,outbox):
    client=app.test_client(); register(client); verify_email(client,outbox)
    clear_cooldown(app); send_reset(client); code=outbox[-1][1]
    with sqlite3.connect(app.config['DATABASE']) as connection:
        connection.execute("UPDATE users SET approval_status='pending' WHERE id=1")
    assert 'Đã đặt mật khẩu mới.' in reset(client,code).text
    assert 'chờ quản trị viên duyệt' in post(client,'/login',dict(username='an01',password='changed-password-123')).text


def test_csrf_wrong_password_and_bad_password_never_change_email_or_consume_code(app,outbox):
    client=app.test_client(); register(client); verify_email(client,outbox)
    clear_cooldown(app); send_reset(client); code=outbox[-1][1]
    assert client.post('/forgot-password/email',data=dict(action='reset',code=code)).status_code==400
    assert client.post('/account/security/email',data=dict(email='other@example.com')).status_code==400
    response=post(client,'/forgot-password/email',dict(action='reset',username='an01',email='an@example.com',code=code,password='short',confirm_password='short'))
    assert '10 đến 256' in response.text
    assert query(app,'SELECT attempts FROM account_email_codes')==[(0,)]
    assert 'Đã đặt mật khẩu mới.' in reset(client,code).text


def test_delivery_failure_removes_unsent_code_and_logs_no_secrets(app,outbox,monkeypatch,caplog):
    client=app.test_client(); register(client); verify_email(client,outbox)
    clear_cooldown(app)
    def failed(*args):
        raise OSError('private-provider-response-secret')
    monkeypatch.setattr(recovery,'deliver',failed)
    response=send_reset(client)
    assert 'Nếu tài khoản và email' in response.text
    assert not query(app,'SELECT * FROM account_email_codes')
    assert 'private-provider-response-secret' not in response.text+caplog.text


def test_missing_smtp_explains_setup_and_keeps_backup_recovery(app):
    client=app.test_client(); register(client)
    assert 'Gửi mã qua email' in client.get('/forgot-password').text
    assert 'chưa được quản trị viên cấu hình' in send_reset(client).text
    assert send_reset(client).status_code==503
    assert 'name="recovery_code"' in client.get('/forgot-password?method=code').text


def test_smtp_cli_hides_credentials_and_keeps_private_config_outside_package(tmp_path):
    app=create_app({'TESTING':True},instance_path=tmp_path/'private-instance')
    result=app.test_cli_runner().invoke(args=['configure-smtp'],input='smtp.gmail.com\nstarttls\n587\nsender@gmail.com\nprivate-app-password\nprivate-app-password\nsender@gmail.com\n')
    assert result.exit_code==0, result.output
    path=recovery.Path(app.instance_path)/'smtp.json'
    try:
        assert path.stat().st_mode & 0o777 == 0o600
        assert json.loads(path.read_text())['password']=='private-app-password'
        assert 'private-app-password' not in result.output
        assert recovery.mail_settings(app)['host']=='smtp.gmail.com'
        from web_deploy.package import source_files
        assert path not in source_files(recovery.Path(app.root_path))
    finally:
        path.unlink()
