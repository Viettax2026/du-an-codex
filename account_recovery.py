"""One-use recovery secrets; passwords and recovery codes are never reversible."""
import hashlib
import ipaddress
import re
import secrets
import time

import click
from flask import flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


def initialize_recovery(db):
    if 'auth_version' not in {row['name'] for row in db().execute('PRAGMA table_info(users)')}:
        db().execute('ALTER TABLE users ADD COLUMN auth_version INTEGER NOT NULL DEFAULT 0')
    db().executescript('''
        CREATE TABLE IF NOT EXISTS account_recovery_codes (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            digest TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
            created_at INTEGER NOT NULL, expires_at INTEGER);
        CREATE INDEX IF NOT EXISTS account_recovery_user ON account_recovery_codes(user_id);
        CREATE TABLE IF NOT EXISTS account_recovery_limits (
            bucket TEXT PRIMARY KEY, attempts INTEGER NOT NULL, expires_at INTEGER NOT NULL);
    ''')
    db().commit()


def code_digest(value):
    compact = re.sub(r'[\s-]', '', value).upper()
    if not re.fullmatch(r'ZFR[0-9A-F]{32}', compact):
        return None
    return hashlib.sha256(('ZaloFlow/account-recovery/v1:' + compact).encode()).hexdigest()


def issue_code(connection, user_id, *, support=False):
    """Caller must authorize the account owner or a local server/Windows admin."""
    raw = secrets.token_hex(16).upper()
    code = 'ZFR-' + '-'.join(raw[i:i+4] for i in range(0, len(raw), 4))
    kind = 'support' if support else 'personal'
    connection.execute('DELETE FROM account_recovery_codes WHERE user_id=? AND kind=?', (user_id, kind))
    now = int(time.time())
    connection.execute('INSERT INTO account_recovery_codes(user_id,digest,kind,created_at,expires_at) VALUES (?,?,?,?,?)',
                       (user_id, code_digest(code), kind, now, now + 900 if support else None))
    return code


def revoke_recovery(connection, user_id):
    connection.execute('DELETE FROM account_recovery_codes WHERE user_id=?', (user_id,))
    connection.execute('DELETE FROM account_email_codes WHERE user_id=?', (user_id,))


def allow_attempt(connection, username, address):
    # Durable limits also work across restarts and web workers.
    now = int(time.time())
    buckets = [('address:' + address, 30), ('account-address:' + username + ':' + address, 8)]
    connection.execute('BEGIN IMMEDIATE')
    try:
        connection.execute('DELETE FROM account_recovery_limits WHERE expires_at<=?', (now,))
        allowed = True
        for value, limit in buckets:
            bucket = hashlib.sha256(value.encode()).hexdigest()
            connection.execute('''INSERT INTO account_recovery_limits(bucket,attempts,expires_at) VALUES (?,1,?)
                ON CONFLICT(bucket) DO UPDATE SET attempts=attempts+1''', (bucket, now + 900))
            attempts = connection.execute('SELECT attempts FROM account_recovery_limits WHERE bucket=?', (bucket,)).fetchone()[0]
            allowed = allowed and attempts <= limit
        connection.commit()
        return allowed
    except BaseException:
        connection.rollback()
        raise


def client_address(app):
    address = request.remote_addr or 'unknown'
    # Bundled web deployments bind Gunicorn to loopback. Their local Nginx
    # overwrites X-Real-IP with $remote_addr. Do not accept X-Forwarded-For,
    # headers from remote peers, or proxy headers in the Windows local app.
    if address in ('127.0.0.1', '::1') and 'desktop_license' not in app.extensions and app.config.get('RECOVERY_TRUST_LOCAL_PROXY', True):
        try:
            return str(ipaddress.ip_address(request.headers.get('X-Real-IP', '')))
        except ValueError:
            pass
    return address


def register_recovery(app, db, login_required):
    @app.route('/forgot-password', methods=['GET', 'POST'])
    def forgot_password():
        if request.method == 'GET' and request.args.get('method') != 'code':
            return render_template('forgot_password_email.html', username='', email='', stage='request')
        username = request.form.get('username', '').strip().lower()[:254]
        if request.method == 'POST':
            if not allow_attempt(db(), username, client_address(app)):
                flash('Bạn đã thử nhiều lần. Vui lòng chờ 15 phút rồi thử lại.', 'error')
                return render_template('forgot_password.html', username=username), 429
            password = request.form.get('password', '')
            if not 10 <= len(password) <= 256:
                flash('Mật khẩu mới phải từ 10 đến 256 ký tự.', 'error')
            elif password != request.form.get('confirm_password', ''):
                flash('Hai mật khẩu chưa trùng nhau. Vui lòng nhập lại.', 'error')
            else:
                digest = code_digest(request.form.get('recovery_code', '')[:150])
                # Serialize validation/consumption/password change. A code must
                # not succeed in two concurrent requests, even with old cookies.
                connection = db()
                connection.execute('BEGIN IMMEDIATE')
                try:
                    user = connection.execute('''SELECT u.id FROM users u JOIN account_recovery_codes r ON r.user_id=u.id
                        WHERE u.username=? AND r.digest=? AND (r.expires_at IS NULL OR r.expires_at>?)''',
                        (username, digest, int(time.time()))).fetchone()
                    if user:
                        connection.execute('UPDATE users SET password=?,auth_version=auth_version+1 WHERE id=?',
                                           (generate_password_hash(password), user['id']))
                        revoke_recovery(connection, user['id'])
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise
                if user:
                    session.clear()
                    flash('Đã đặt mật khẩu mới. Đăng nhập lại và tạo mã khôi phục mới trong Bảo mật tài khoản.', 'success')
                    return redirect(url_for('login'))
                flash('Tài khoản hoặc mã khôi phục không hợp lệ, mã đã dùng hoặc đã hết hạn.', 'error')
        return render_template('forgot_password.html', username=username)

    @app.route('/account/security', methods=['GET', 'POST'])
    @login_required
    def account_security():
        code = None
        if request.method == 'POST':
            password = request.form.get('current_password', '')
            # Current password is required even if another browser has a valid
            # session; re-check the auth version in the write transaction.
            connection = db()
            connection.execute('BEGIN IMMEDIATE')
            try:
                user = connection.execute('SELECT * FROM users WHERE id=?', (g.user['id'],)).fetchone()
                valid = user and user['auth_version'] == g.user['auth_version'] and len(password) <= 256 and check_password_hash(user['password'], password)
                if valid:
                    code = issue_code(connection, user['id'])
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            if not valid:
                flash('Mật khẩu hiện tại chưa đúng. Chưa tạo mã khôi phục mới.', 'error')
        has_code = db().execute("SELECT 1 FROM account_recovery_codes WHERE user_id=? AND kind='personal'", (g.user['id'],)).fetchone() is not None
        from email_recovery import mail_ready
        email_user = db().execute('SELECT email,email_verified FROM users WHERE id=?', (g.user['id'],)).fetchone()
        pending_email = db().execute("SELECT email FROM account_email_codes WHERE user_id=? AND purpose='verify' AND sent=1 AND expires_at>?", (g.user['id'], int(time.time()))).fetchone()
        return render_template('account_security.html', page='security', recovery_code=code, has_code=has_code,
                               email_user=email_user, pending_email=pending_email, mail_ready=mail_ready(app))

    @app.cli.command('issue-recovery-code')
    @click.option('--username', required=True, help='Existing account; does not create users.')
    def issue_recovery_code(username):
        """Local VPS owner: issue a one-use support code valid for 15 minutes."""
        connection = db()
        user = connection.execute('SELECT id FROM users WHERE username=?', (username.strip().lower(),)).fetchone()
        if not user:
            raise click.ClickException('Không tìm thấy tài khoản. Không tạo tài khoản mới.')
        code = issue_code(connection, user['id'], support=True)
        connection.commit()
        click.echo('Mã hỗ trợ dùng một lần, có hiệu lực 15 phút. Chỉ gửi riêng sau khi xác minh chủ tài khoản:')
        click.echo(code)
