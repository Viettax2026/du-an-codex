"""No customer login can administer this database; administration is local CLI only."""
import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from werkzeug.security import generate_password_hash

from license_system.signatures import PRODUCT, LicenseError, new_signer, public_text, sign

LEASE_SECONDS = 3600


def secret_hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def validate_server_url(value):
    parts = urlsplit(value)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise LicenseError('Địa chỉ máy chủ bản quyền phải là HTTPS, không chứa tài khoản hoặc tham số.')
    return value.rstrip('/')


class Authority:
    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.key_path = self.folder / 'signing-private.pem'
        self.database = self.folder / 'licenses.sqlite3'

    def initialize(self, url):
        url = validate_server_url(url)
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        signer = new_signer()
        # Never replace an existing signing identity or reset its licenses.
        fd = os.open(self.key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as file:
            file.write(signer.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE licenses (
                    id INTEGER PRIMARY KEY, key_hash TEXT UNIQUE NOT NULL, customer TEXT NOT NULL,
                    expires_at INTEGER NOT NULL, seats INTEGER NOT NULL, revoked INTEGER NOT NULL DEFAULT 0,
                    created_at INTEGER NOT NULL);
                CREATE TABLE activations (
                    id INTEGER PRIMARY KEY, license_id INTEGER NOT NULL REFERENCES licenses(id),
                    device TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1, last_seen INTEGER NOT NULL,
                    UNIQUE(license_id, device));
                CREATE TABLE rate_windows (address TEXT PRIMARY KEY, started INTEGER NOT NULL, attempts INTEGER NOT NULL);
                CREATE TABLE settings (name TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            password = secrets.token_urlsafe(18)
            db.execute('INSERT INTO settings VALUES(?,?)', ('admin_password_hash', generate_password_hash(password)))
            db.execute('INSERT INTO settings VALUES(?,?)', ('admin_epoch', secrets.token_hex(16)))
        for name, value in [('admin-password.txt', password), ('session-secret.txt', secrets.token_hex(32))]:
            fd = os.open(self.folder / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w') as file:
                file.write(value + '\n')
        config = dict(version=1, server_url=url, public_key=public_text(signer))
        self.folder.joinpath('client-config.json').write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
        return config

    @contextmanager
    def connection(self):
        if not self.key_path.is_file():
            raise LicenseError('Chưa khởi tạo máy chủ bản quyền.')
        db = sqlite3.connect(self.database, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def signer(self):
        return serialization.load_pem_private_key(self.key_path.read_bytes(), password=None)

    def setting(self, name):
        with self.connection() as db:
            row = db.execute('SELECT value FROM settings WHERE name=?', (name,)).fetchone()
            return row['value'] if row else ''

    def set_admin_password(self, password):
        if not 12 <= len(password) <= 256:
            raise LicenseError('Mật khẩu quản trị phải từ 12 đến 256 ký tự.')
        with self.connection() as db:
            db.execute('UPDATE settings SET value=? WHERE name=?', (generate_password_hash(password), 'admin_password_hash'))
            db.execute('UPDATE settings SET value=? WHERE name=?', (secrets.token_hex(16), 'admin_epoch'))
        self.folder.joinpath('admin-password.txt').unlink(missing_ok=True)

    def issue(self, customer, days=30, seats=1, now=None):
        now = int(time.time() if now is None else now)
        if not customer.strip() or len(customer) > 150 or not 1 <= days <= 36500 or not 1 <= seats <= 100:
            raise LicenseError('Nhập tên khách hàng, hạn dùng 1–36500 ngày và số máy 1–100.')
        key = 'ZF-' + secrets.token_urlsafe(24)
        with self.connection() as db:
            cur = db.execute('INSERT INTO licenses(key_hash,customer,expires_at,seats,created_at) VALUES(?,?,?,?,?)',
                             (secret_hash(key), customer.strip(), now + days * 86400, seats, now))
        return dict(id=cur.lastrowid, key=key, expires_at=now + days * 86400, seats=seats)

    def manage(self, license_id, action, days=30, now=None):
        now = int(time.time() if now is None else now)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM licenses WHERE id=?', (license_id,)).fetchone()
            if row is None:
                raise LicenseError('Không tìm thấy bản quyền.')
            if action == 'revoke':
                db.execute('UPDATE licenses SET revoked=1 WHERE id=?', (license_id,))
            elif action == 'extend':
                if not 1 <= days <= 36500:
                    raise LicenseError('Số ngày không hợp lệ.')
                db.execute('UPDATE licenses SET revoked=0,expires_at=? WHERE id=?', (max(now, row['expires_at']) + days * 86400, license_id))
            elif action == 'reset-devices':
                db.execute('UPDATE activations SET active=0 WHERE license_id=?', (license_id,))
            else:
                raise LicenseError('Thao tác không hợp lệ.')

    def list_licenses(self):
        with self.connection() as db:
            return [dict(row, expired=row['expires_at'] <= time.time()) for row in db.execute('''SELECT l.id,l.customer,l.expires_at,l.seats,l.revoked,
                (SELECT count(*) FROM activations a WHERE a.license_id=l.id AND a.active=1) AS machines
                FROM licenses l ORDER BY l.id DESC''')]

    def throttle(self, address, now=None):
        now = int(time.time() if now is None else now)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM rate_windows WHERE started<?', (now - 900,))
            row = db.execute('SELECT attempts FROM rate_windows WHERE address=?', (address,)).fetchone()
            if row and row['attempts'] >= 100:
                return False
            db.execute('INSERT INTO rate_windows VALUES(?,?,1) ON CONFLICT(address) DO UPDATE SET attempts=attempts+1', (address, now))
        return True

    def lease(self, db, activation, license_row, now):
        token = sign(self.signer(), dict(product=PRODUCT, license_id=license_row['id'], customer=license_row['customer'],
                     activation_id=activation['id'], device=activation['device'], issued_at=now,
                     valid_until=min(now + LEASE_SECONDS, license_row['expires_at']), license_expires_at=license_row['expires_at']))
        db.execute('UPDATE activations SET last_seen=? WHERE id=?', (now, activation['id']))
        return dict(lease=token, server_time=now)

    def exchange(self, action, device, credential, now=None):
        now = int(time.time() if now is None else now)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if action == 'activate':
                license_row = db.execute('SELECT * FROM licenses WHERE key_hash=?', (secret_hash(credential),)).fetchone()
                if license_row is None or license_row['revoked'] or now >= license_row['expires_at']:
                    raise LicenseError('Key không hợp lệ, đã hết hạn hoặc đã bị thu hồi.')
                activation = db.execute('SELECT * FROM activations WHERE license_id=? AND device=?', (license_row['id'], device)).fetchone()
                used = db.execute('SELECT count(*) FROM activations WHERE license_id=? AND active=1', (license_row['id'],)).fetchone()[0]
                if (not activation or not activation['active']) and used >= license_row['seats']:
                    raise LicenseError('Key đã đủ số máy. Hủy kích hoạt máy cũ hoặc liên hệ người cấp key.')
                # Re-entering a key on the same device rotates its bearer token.
                secret = secrets.token_urlsafe(32)
                db.execute('''INSERT INTO activations(license_id,device,token_hash,active,last_seen) VALUES(?,?,?,1,?)
                    ON CONFLICT(license_id,device) DO UPDATE SET token_hash=excluded.token_hash,active=1,last_seen=excluded.last_seen''',
                           (license_row['id'], device, secret_hash(secret), now))
                activation = db.execute('SELECT * FROM activations WHERE license_id=? AND device=?', (license_row['id'], device)).fetchone()
                return dict(self.lease(db, activation, license_row, now), activation_token=secret)
            activation = db.execute('SELECT * FROM activations WHERE device=? AND token_hash=? AND active=1', (device, secret_hash(credential))).fetchone()
            if activation is None:
                raise LicenseError('Phiên kích hoạt không còn hiệu lực. Nhập lại key hoặc liên hệ người cấp key.')
            if action == 'deactivate':
                db.execute('UPDATE activations SET active=0 WHERE id=?', (activation['id'],))
                return dict(deactivated=True)
            license_row = db.execute('SELECT * FROM licenses WHERE id=?', (activation['license_id'],)).fetchone()
            if license_row['revoked'] or now >= license_row['expires_at']:
                raise LicenseError('Key đã hết hạn hoặc bị thu hồi. Liên hệ người cấp key để gia hạn.')
            return self.lease(db, activation, license_row, now)
