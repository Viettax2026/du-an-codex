"""Provision only the administrator carried by a verified publisher lease."""
import re
import sqlite3

from account_approval import create_pending_account, set_approval
from license_system.signatures import LicenseError


def sync_license_admin(app, license):
    claims = license.claims()
    profile = claims.get('tool_admin') if claims and claims.get('license_mode') == 'floating' else None
    if not profile:
        return None
    username = profile.get('username') if isinstance(profile, dict) else None
    password_hash = profile.get('password_hash') if isinstance(profile, dict) else None
    license_id = claims.get('license_id')
    if (type(license_id) is not int or license_id < 1 or not isinstance(username, str)
            or not re.fullmatch(r'[a-z0-9_.-]{3,64}', username) or not isinstance(password_hash, str)
            or not re.fullmatch(r'scrypt:32768:8:1\$[A-Za-z0-9]{16}\$[a-f0-9]{128}', password_hash)):
        raise LicenseError('Thông tin cấp tài khoản quản trị tool không hợp lệ. Liên hệ người cấp key.')
    connection = sqlite3.connect(app.config['DATABASE'], timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute('PRAGMA foreign_keys=ON')
    try:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('''CREATE TABLE IF NOT EXISTS desktop_admin_grants (
            license_id INTEGER PRIMARY KEY, username TEXT NOT NULL,
            user_id INTEGER UNIQUE NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        grant = connection.execute('SELECT * FROM desktop_admin_grants WHERE license_id=?', (license_id,)).fetchone()
        if grant:
            if grant['username'] != username:
                raise LicenseError('Tài khoản quản trị của key đã thay đổi. Giữ nguyên tài khoản và dữ liệu hiện có; liên hệ người cấp key.')
            # Never reset a recovered password, restore removed permissions or
            # approve an explicitly blocked account on a subsequent heartbeat.
            connection.commit()
            app.extensions.pop('desktop_admin_error', None)
            return username
        if connection.execute('SELECT 1 FROM users WHERE username=?', (username,)).fetchone():
            raise LicenseError('Tên quản trị được cấp đã tồn tại trong tool. Không ghi đè mật khẩu hoặc quyền; liên hệ người cấp key để xử lý.')
        created = create_pending_account(connection, 'Quản trị tool', username, password_hash)
        user_id = created.lastrowid
        set_approval(connection, user_id, 'approved')
        connection.execute("UPDATE users SET role='admin',auth_version=auth_version+1 WHERE id=?", (user_id,))
        connection.execute("INSERT INTO account_approval_events(user_id,action) VALUES (?,'license_admin')", (user_id,))
        connection.execute('INSERT INTO desktop_admin_grants(license_id,username,user_id) VALUES (?,?,?)', (license_id,username,user_id))
        latest = license.claims()
        if not latest or latest.get('license_id') != license_id or latest.get('tool_admin') != profile:
            raise LicenseError('Key không còn hiệu lực để tạo quản trị tool. Kích hoạt lại rồi thử tiếp.')
        connection.commit()
        app.extensions.pop('desktop_admin_error', None)
        return username
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
