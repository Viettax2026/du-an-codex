"""Provision only the administrator carried by a verified publisher lease."""
import re
import sqlite3

from werkzeug.security import check_password_hash

from account_approval import create_pending_account, set_approval
from license_system.signatures import LicenseError


def _profile(license):
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
    return license_id, username, password_hash, profile


def license_admin_status(app, license):
    """Read the local mapping; a publisher username never identifies an old user."""
    result = dict(created=False, conflict=False, renamed=False, username='', suggested_username='')
    try:
        supplied = _profile(license)
    except LicenseError:
        return result
    if supplied is None:
        return result
    license_id, username, _, _ = supplied
    with sqlite3.connect(app.config['DATABASE'], timeout=15) as connection:
        if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='desktop_admin_grants'").fetchone():
            grant = connection.execute('''SELECT g.username,u.username FROM desktop_admin_grants g
                JOIN users u ON u.id=g.user_id WHERE g.license_id=?''', (license_id,)).fetchone()
            if grant:
                if grant[0] == username:
                    result.update(created=True, username=grant[1], renamed=grant[1] != username)
                return result
        if connection.execute('SELECT 1 FROM users WHERE username=?', (username,)).fetchone():
            suffix = '-key-' + str(license_id)
            suggestion = username[:64-len(suffix)] + suffix
            result.update(conflict=True, suggested_username=suggestion)
    return result


def sync_license_admin(app, license, *, local_username=None, initial_password=None):
    supplied = _profile(license)
    if supplied is None:
        if local_username is not None:
            raise LicenseError('Key hiện tại chưa cấp tài khoản quản trị tool.')
        return None
    license_id, username, password_hash, profile = supplied
    chosen_username = username
    if local_username is not None:
        chosen_username = local_username.strip().lower()
        if not re.fullmatch(r'[a-z0-9_.-]{3,64}', chosen_username) or chosen_username in (username, 'admin'):
            raise LicenseError('Chọn tên mới khác tên được cấp, từ 3–64 ký tự: chữ không dấu, số, dấu chấm, gạch dưới hoặc gạch ngang.')
        if (not isinstance(initial_password, str) or not 8 <= len(initial_password) <= 256
                or not check_password_hash(password_hash, initial_password)):
            raise LicenseError('Mật khẩu khởi tạo do người cấp key cung cấp chưa đúng.')
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
            if local_username is not None:
                raise LicenseError('Quản trị của key đã được tạo. Đăng nhập bằng tên hiển thị bên dưới; không tạo thêm quản trị từ key này.')
            # Never reset a recovered password, restore removed permissions or
            # approve an explicitly blocked account on a subsequent heartbeat.
            connection.commit()
            app.extensions.pop('desktop_admin_error', None)
            return connection.execute('SELECT username FROM users WHERE id=?', (grant['user_id'],)).fetchone()[0]
        name_exists = connection.execute('SELECT 1 FROM users WHERE username=?', (username,)).fetchone()
        if local_username is None and name_exists:
            raise LicenseError('Tên quản trị được cấp đã tồn tại trong tool. Không ghi đè mật khẩu hoặc quyền. Chọn Tạo quản trị bằng tên khác bên dưới để dùng mật khẩu được cấp.')
        if local_username is not None:
            if not name_exists:
                raise LicenseError('Tên được cấp không bị trùng. Bấm Kiểm tra lại để tạo quản trị bằng tên đã cấp.')
            if connection.execute('SELECT 1 FROM users WHERE username=?', (chosen_username,)).fetchone():
                raise LicenseError('Tên mới đã tồn tại. Chọn một tên khác; tài khoản cũ được giữ nguyên.')
        created = create_pending_account(connection, 'Quản trị tool', chosen_username, password_hash)
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
        return chosen_username
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
