import sqlite3

from werkzeug.security import generate_password_hash

from app import create_app
from test_workflow import app, post


def test_username_registration_and_login(app):
    client = app.test_client()
    page = client.get('/login').text
    assert 'name="username"' in page
    assert 'type="email"' not in page
    post(client, '/register', {'name': 'An', 'username': 'VietTax_01', 'password': 'secure-password'})
    with client.session_transaction() as session:
        assert session['user_id'] == 1
    post(client, '/logout')
    assert 'Tài khoản này đã được đăng ký.' in post(client, '/register', {
        'name': 'Other', 'username': 'viettax_01', 'password': 'secure-password'}).text
    assert 'Tài khoản hoặc mật khẩu chưa đúng.' in post(client, '/login', {
        'username': 'viettax_01', 'password': 'wrong-password'}).text
    post(client, '/login', {'username': ' VIETTAX_01 ', 'password': 'secure-password'})
    with client.session_transaction() as session:
        assert session['user_id'] == 1


def test_invalid_username(app):
    client = app.test_client()
    for username in ['ab', 'a b', 'new@example.com', 'a' * 65]:
        post(client, '/register', {'name': 'An', 'username': username, 'password': 'secure-password'})
        with client.session_transaction() as session:
            assert 'user_id' not in session


def test_legacy_email_account_migration(tmp_path):
    database = str(tmp_path / 'legacy.sqlite3')
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL)')
        conn.execute('INSERT INTO users VALUES (7, ?, ?, ?)', ('An', 'an@example.com', generate_password_hash('secure-password')))
    config = {'TESTING': True, 'DATABASE': database, 'SECRET_KEY': 'test-only'}
    app = create_app(config)
    client = app.test_client()
    post(client, '/login', {'username': 'an@example.com', 'password': 'secure-password'})
    with client.session_transaction() as session:
        assert session['user_id'] == 7
    create_app(config)
    with sqlite3.connect(database) as conn:
        assert conn.execute('SELECT id,username FROM users').fetchone() == (7, 'an@example.com')


def test_existing_owner_becomes_admin_without_changing_data(tmp_path):
    database = str(tmp_path / 'owner.sqlite3')
    password_hash = generate_password_hash('owner-password')
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL)')
        conn.execute('INSERT INTO users VALUES (7, ?, ?, ?)', ('Owner', 'lienhe.viettaxco@gmail.com', password_hash))
    config = {'TESTING': True, 'DATABASE': database, 'SECRET_KEY': 'test-only'}
    app = create_app(config)
    client = app.test_client()
    post(client, '/login', {'username': 'admin', 'password': 'owner-password'})
    with client.session_transaction() as session:
        assert session['user_id'] == 7
    post(client, '/contacts', {'name': 'Lan', 'phone': '0901234567'})
    create_app(config)
    with sqlite3.connect(database) as conn:
        assert conn.execute('SELECT id,username,password FROM users').fetchone() == (7, 'admin', password_hash)
        assert conn.execute('SELECT user_id,name FROM contacts').fetchone() == (7, 'Lan')
    post(client, '/logout')
    post(client, '/login', {'username': 'lienhe.viettaxco@gmail.com', 'password': 'owner-password'})
    with client.session_transaction() as session:
        assert 'user_id' not in session


def test_admin_migration_does_not_overwrite_an_existing_account(tmp_path):
    import pytest

    database = str(tmp_path / 'conflict.sqlite3')
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL)')
        conn.executemany('INSERT INTO users VALUES (?, ?, ?, ?)', [
            (1, 'Owner', 'lienhe.viettaxco@gmail.com', 'unchanged'),
            (2, 'Existing', 'admin', 'also-unchanged')])
    with pytest.raises(RuntimeError, match='admin đã được sử dụng'):
        create_app({'TESTING': True, 'DATABASE': database})
    with sqlite3.connect(database) as conn:
        assert conn.execute('SELECT username FROM users ORDER BY id').fetchall() == [
            ('lienhe.viettaxco@gmail.com',), ('admin',)]
