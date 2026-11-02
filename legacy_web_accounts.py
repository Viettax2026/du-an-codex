"""Compatibility migration for the existing web deployment; not a desktop asset."""


def migrate_legacy_web_account(connection):
    user=connection.execute('SELECT id FROM users WHERE username=?',('lienhe.viettaxco@gmail.com',)).fetchone()
    if user:
        if connection.execute('SELECT id FROM users WHERE lower(username)=?',('admin',)).fetchone():
            raise RuntimeError('Không thể đổi tài khoản cũ: tên admin đã được sử dụng.')
        connection.execute('UPDATE users SET username=? WHERE id=?',('admin',user['id']))
        connection.commit()
