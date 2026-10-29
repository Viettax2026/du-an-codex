"""Verified recovery email and short-lived, one-use five-digit email codes."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import smtplib
import ssl
import time
from email.message import EmailMessage

import click
from flask import flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from account_recovery import client_address


def normalize_email(value):
    value = value.strip().lower()
    # A deliberately narrow mailbox format; reject header injection and Unicode
    # lookalikes rather than silently delivering a recovery secret elsewhere.
    if len(value) > 254 or not re.fullmatch(r"[a-z0-9!#$%&'*+/=?^_`{|}~.-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", value):
        raise ValueError('Nhập địa chỉ email hợp lệ để nhận mã khôi phục.')
    local, domain = value.rsplit('@', 1)
    if len(local) > 64 or '..' in value or local.startswith('.') or local.endswith('.') or any(part.startswith('-') or part.endswith('-') for part in domain.split('.')):
        raise ValueError('Nhập địa chỉ email hợp lệ để nhận mã khôi phục.')
    return value


def initialize_email(db):
    columns = {row['name'] for row in db().execute('PRAGMA table_info(users)')}
    for name, definition in {'email': "TEXT NOT NULL DEFAULT ''", 'email_verified': 'INTEGER NOT NULL DEFAULT 0'}.items():
        if name not in columns:
            db().execute(f'ALTER TABLE users ADD COLUMN {name} {definition}')
    db().executescript('''
        CREATE TABLE IF NOT EXISTS account_email_codes (
            id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            purpose TEXT NOT NULL CHECK(purpose IN ('verify','reset')),
            email TEXT NOT NULL, digest TEXT NOT NULL, created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            sent INTEGER NOT NULL DEFAULT 0, UNIQUE(user_id,purpose));
        CREATE TABLE IF NOT EXISTS account_email_limits (
            bucket TEXT PRIMARY KEY, attempts INTEGER NOT NULL, expires_at INTEGER NOT NULL);
    ''')
    db().commit()


def mail_settings(app):
    path = Path(app.instance_path) / 'smtp.json'
    saved = json.loads(path.read_text()) if path.exists() else {}
    return {key: app.config.get('SMTP_' + key.upper(), os.environ.get('SMTP_' + key.upper(), saved.get(key, '')))
            for key in ('host', 'port', 'security', 'username', 'password', 'from')}


def mail_ready(app):
    settings = mail_settings(app)
    return bool(settings['host'] and settings['from'] and settings['security'] in ('starttls', 'ssl'))


def deliver(app, recipient, code, purpose):
    settings = mail_settings(app)
    if not mail_ready(app):
        raise ValueError('SMTP chưa được cấu hình.')
    sender = normalize_email(settings['from'])
    recipient = normalize_email(recipient)
    message = EmailMessage()
    message['Subject'] = 'ZaloFlow — Mã ' + ('xác minh email' if purpose == 'verify' else 'đặt lại mật khẩu')
    message['From'] = sender
    message['To'] = recipient
    message.set_content(f'Mã của bạn là: {code}\n\nMã gồm 5 số, có hiệu lực 10 phút và chỉ dùng một lần. '
                        'Không cung cấp mã cho người khác. Nếu bạn không yêu cầu, hãy bỏ qua email này.\n')
    port = int(settings['port'] or (465 if settings['security'] == 'ssl' else 587))
    context = ssl.create_default_context()
    factory = smtplib.SMTP_SSL if settings['security'] == 'ssl' else smtplib.SMTP
    kwargs = dict(timeout=10)
    if settings['security'] == 'ssl':
        kwargs['context'] = context
    with factory(settings['host'], port, **kwargs) as smtp:
        if settings['security'] == 'starttls':
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
        if settings['username']:
            smtp.login(settings['username'], settings['password'])
        refused = smtp.send_message(message)
        if refused:
            raise ValueError('Máy chủ email chưa nhận thư.')


def code_digest(app, challenge_id, code):
    # Five decimal digits have little entropy: use a keyed digest, never plain
    # SHA256, so a database backup alone cannot reveal a valid reset code.
    return hmac.new(app.secret_key.encode(), ('ZaloFlow/email/v1:' + challenge_id + ':' + code).encode(), hashlib.sha256).hexdigest()


def limit(connection, key, maximum, seconds):
    """Must run inside the caller's write transaction; persists across workers."""
    now = int(time.time())
    connection.execute('DELETE FROM account_email_limits WHERE expires_at<=?', (now,))
    bucket = hashlib.sha256(key.encode()).hexdigest()
    row = connection.execute('SELECT attempts FROM account_email_limits WHERE bucket=?', (bucket,)).fetchone()
    if row and row['attempts'] >= maximum:
        return False
    connection.execute('''INSERT INTO account_email_limits VALUES (?,1,?)
        ON CONFLICT(bucket) DO UPDATE SET attempts=attempts+1''', (bucket, now + seconds))
    return True


def request_code(app, connection, username, email, purpose, address, *, user_id=None, current_password=None, auth_version=None):
    """Reserve a code before SMTP; never keep a DB lock during network I/O."""
    connection.execute('BEGIN IMMEDIATE')
    challenge_id = None
    try:
        user = connection.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        allowed = limit(connection, 'send-ip:' + address, 20, 3600)
        allowed = limit(connection, 'send-account:' + username, 5, 3600) and allowed
        allowed = limit(connection, 'send-cooldown:' + username, 1, 60) and allowed
        if purpose == 'verify':
            valid = (user and user['id'] == user_id and user['auth_version'] == auth_version
                     and user['approval_status'] == 'approved' and len(current_password or '') <= 256
                     and check_password_hash(user['password'], current_password or ''))
        else:
            valid = user and user['email_verified'] and user['email'] == email
        if valid and allowed:
            code = f'{secrets.randbelow(100000):05d}'
            challenge_id = secrets.token_hex(24)
            now = int(time.time())
            connection.execute('DELETE FROM account_email_codes WHERE user_id=? AND purpose=?', (user['id'], purpose))
            connection.execute('''INSERT INTO account_email_codes(id,user_id,purpose,email,digest,created_at,expires_at)
                VALUES (?,?,?,?,?,?,?)''', (challenge_id, user['id'], purpose, email, code_digest(app, challenge_id, code), now, now + 600))
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    if challenge_id:
        try:
            deliver(app, email, code, purpose)
        except (OSError, smtplib.SMTPException, ValueError):
            # Never log SMTP credentials, addresses, codes or provider responses.
            app.logger.warning('Không gửi được email khôi phục; kiểm tra cấu hình SMTP trên máy chủ.')
            connection.execute('DELETE FROM account_email_codes WHERE id=?', (challenge_id,))
            connection.commit()
            return False
        connection.execute('UPDATE account_email_codes SET sent=1 WHERE id=?', (challenge_id,))
        connection.commit()
    return True


def consume_code(app, connection, username, email, code, purpose, address, *, password=None, user_id=None, auth_version=None):
    connection.execute('BEGIN IMMEDIATE')
    try:
        # Global account limit prevents distributing guesses across IPs/resends.
        allowed = limit(connection, 'guess-account:' + username, 10, 3600)
        allowed = limit(connection, 'guess-ip:' + address, 30, 3600) and allowed
        row = connection.execute('''SELECT c.*,u.auth_version,u.approval_status,u.email AS current_email,
            u.email_verified FROM account_email_codes c JOIN users u ON u.id=c.user_id
            WHERE u.username=? AND c.purpose=?''', (username, purpose)).fetchone()
        eligible = (allowed and row and row['sent'] and row['expires_at'] > int(time.time()) and row['attempts'] < 5)
        if eligible:
            connection.execute('UPDATE account_email_codes SET attempts=attempts+1 WHERE id=?', (row['id'],))
        valid = (eligible and row['email'] == email and re.fullmatch(r'[0-9]{5}', code)
                 and hmac.compare_digest(row['digest'], code_digest(app, row['id'], code)))
        if purpose == 'verify':
            valid = valid and row['user_id'] == user_id and row['auth_version'] == auth_version and row['approval_status'] == 'approved'
        else:
            valid = valid and row['email_verified'] and row['current_email'] == email
        if valid:
            if purpose == 'verify':
                connection.execute('UPDATE users SET email=?,email_verified=1 WHERE id=?', (email, row['user_id']))
            else:
                connection.execute('UPDATE users SET password=?,auth_version=auth_version+1 WHERE id=?',
                                   (generate_password_hash(password), row['user_id']))
                connection.execute('DELETE FROM account_recovery_codes WHERE user_id=?', (row['user_id'],))
            # Changing verified email invalidates any reset addressed to the old one.
            connection.execute('DELETE FROM account_email_codes WHERE user_id=?', (row['user_id'],))
        connection.commit()
        return bool(valid)
    except BaseException:
        connection.rollback()
        raise


def register_email(app, db, login_required):
    @app.route('/forgot-password/email', methods=['GET', 'POST'])
    def forgot_password_email():
        username = request.form.get('username', '').strip().lower()[:254]
        email = request.form.get('email', '').strip().lower()[:254]
        stage = 'request'
        if request.method == 'POST':
            action = request.form.get('action', 'request')
            stage = 'reset' if action in ('request', 'reset') else 'request'
            if not mail_ready(app):
                flash('Chức năng gửi email chưa được quản trị viên cấu hình. Bạn có thể dùng mã khôi phục dự phòng hoặc liên hệ hỗ trợ.', 'error')
                return render_template('forgot_password_email.html', username=username, email=email, stage='request'), 503
            try:
                email = normalize_email(email)
                if action == 'request':
                    # Same response for absent accounts, wrong/unverified email,
                    # cooldown, provider failure and success; no email enumeration.
                    request_code(app, db(), username, email, 'reset', client_address(app))
                    flash('Nếu tài khoản và email đã xác minh khớp nhau, mã 5 số sẽ được gửi tới email của bạn. Mã có hiệu lực 10 phút; chờ ít nhất 60 giây trước khi gửi lại. Kiểm tra cả thư rác.', 'success')
                elif action == 'reset':
                    password = request.form.get('password', '')
                    if not 10 <= len(password) <= 256:
                        raise ValueError('Mật khẩu mới phải từ 10 đến 256 ký tự.')
                    if password != request.form.get('confirm_password', ''):
                        raise ValueError('Hai mật khẩu chưa trùng nhau. Vui lòng nhập lại.')
                    if consume_code(app, db(), username, email, request.form.get('code', '')[:100], 'reset', client_address(app), password=password):
                        session.clear()
                        flash('Đã đặt mật khẩu mới. Vui lòng đăng nhập lại.', 'success')
                        return redirect(url_for('login'))
                    raise ValueError('Tài khoản, email hoặc mã không hợp lệ; mã đã dùng, hết hạn hoặc vượt số lần thử. Vui lòng yêu cầu mã mới khi hết thời gian chờ.')
            except ValueError as error:
                flash(str(error), 'error')
        return render_template('forgot_password_email.html', username=username, email=email, stage=stage)

    @app.post('/account/security/email')
    @login_required
    def account_email():
        try:
            if not mail_ready(app):
                raise ValueError('Chưa cấu hình dịch vụ gửi email. Liên hệ quản trị viên để bật chức năng này.')
            email = normalize_email(request.form.get('email', ''))
            if request.form.get('action') == 'verify':
                if consume_code(app, db(), g.user['username'], email, request.form.get('code', '')[:100], 'verify', client_address(app), user_id=g.user['id'], auth_version=g.user['auth_version']):
                    flash('Đã xác minh email. Bạn có thể nhận mã 5 số qua email này khi quên mật khẩu.', 'success')
                else:
                    raise ValueError('Mã xác minh không hợp lệ, hết hạn hoặc vượt số lần thử.')
            else:
                if request_code(app, db(), g.user['username'], email, 'verify', client_address(app), user_id=g.user['id'], current_password=request.form.get('current_password', ''), auth_version=g.user['auth_version']):
                    flash('Nếu mật khẩu hiện tại đúng và chưa vượt giới hạn gửi, mã xác minh 5 số sẽ được gửi tới email vừa nhập. Mã có hiệu lực 10 phút; chờ 60 giây trước khi gửi lại.', 'success')
                else:
                    raise ValueError('Chưa gửi được email. Liên hệ quản trị viên kiểm tra cấu hình SMTP.')
        except ValueError as error:
            flash(str(error), 'error')
        return redirect(url_for('account_security'))

    @app.cli.command('configure-smtp')
    def configure_smtp():
        """Local VPS owner: store SMTP credentials outside the source/package."""
        if 'desktop_license' in app.extensions:
            raise click.ClickException('Cấu hình SMTP trên VPS bản web; không phân phối mật khẩu SMTP trong bộ cài Windows.')
        host = click.prompt('Máy chủ SMTP', default='smtp.gmail.com').strip()
        security = click.prompt('Bảo mật', default='starttls', type=click.Choice(['starttls', 'ssl']))
        port = click.prompt('Cổng', default=587 if security == 'starttls' else 465, type=click.IntRange(1, 65535))
        username = click.prompt('Tài khoản SMTP').strip()
        password = click.prompt('Mật khẩu ứng dụng SMTP', hide_input=True, confirmation_prompt=True)
        try:
            sender = normalize_email(click.prompt('Email gửi', default=username))
        except ValueError as error:
            raise click.ClickException(str(error)) from error
        path = Path(app.instance_path) / 'smtp.json'
        temporary = path.with_name('smtp-' + secrets.token_hex(8) + '.tmp')
        try:
            with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
                json.dump(dict(host=host, port=port, security=security, username=username, password=password, **{'from': sender}), stream)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        click.echo('Đã lưu cấu hình SMTP riêng trong instance/smtp.json (quyền 600). Chạy test-email để kiểm tra gửi thư.')

    @app.cli.command('test-email')
    @click.option('--to', 'recipient', required=True, help='Hộp thư của bạn để kiểm tra gửi thư.')
    def test_email(recipient):
        try:
            deliver(app, recipient, '00000', 'verify')
        except (OSError, smtplib.SMTPException, ValueError):
            raise click.ClickException('Chưa gửi được thư. Kiểm tra SMTP, mật khẩu ứng dụng, email gửi và cổng mạng của VPS.') from None
        click.echo('Máy chủ SMTP đã nhận thư thử (mã 00000 không có hiệu lực đăng nhập). Kiểm tra hộp thư và thư rác.')
