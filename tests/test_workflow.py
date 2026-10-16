import io
import re
import sqlite3

import pytest

from app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING': True, 'DATABASE': str(tmp_path / 'test.sqlite3'), 'SECRET_KEY': 'test-only'})


def token(client, page='/'):
    client.get(page)
    with client.session_transaction() as session:
        return session['csrf']


def post(client, path, data=None):
    return client.post(path, data={'csrf': token(client), **(data or {})}, follow_redirects=True)


def register(client, username='an01'):
    return post(client, '/register', {'name': 'An', 'username': username, 'password': 'secure-password'})


def test_full_workflow_and_persistence(app):
    client = app.test_client()
    assert client.get('/campaigns').status_code == 302
    assert register(client).status_code == 200
    for name, phone, consent in [('Lan', '0901', 'on'), ('Binh', '0902', '')]:
        post(client, '/contacts', {'name': name, 'phone': phone, 'tag': 'VIP', 'consent': consent})
    result = post(client, '/campaigns', {'name': 'Chăm sóc', 'message': 'Xin chào {{name}}', 'tag': 'VIP'})
    assert 'Chăm sóc' in result.text
    result = post(client, '/campaigns/1')
    assert 'Xin chào Lan' in result.text
    assert 'Đã mô phỏng 1 tin nhắn' in result.text
    post(client, '/campaigns/1')
    conn = sqlite3.connect(app.config['DATABASE'])
    assert conn.execute('SELECT count(*) FROM deliveries').fetchone()[0] == 1
    assert conn.execute('SELECT message FROM deliveries').fetchone()[0] == 'Xin chào Lan'
    assert conn.execute('SELECT password FROM users').fetchone()[0] != 'secure-password'
    conn.close()
    post(client, '/logout')
    result = post(client, '/login', {'username': 'an01', 'password': 'secure-password'})
    assert 'Chăm sóc' in result.text
    assert 'Lan' in client.get('/contacts').text


def test_tenant_isolation_and_csrf(app):
    alice, bob = app.test_client(), app.test_client()
    register(alice)
    post(alice, '/contacts', {'name': 'PRIVATE', 'phone': '0901', 'consent': 'on'})
    post(alice, '/campaigns', {'name': 'PRIVATE_CAMPAIGN', 'message': 'Hello'})
    register(bob, 'bob')
    assert 'PRIVATE' not in bob.get('/contacts').text
    assert 'PRIVATE_CAMPAIGN' not in bob.get('/campaigns').text
    assert bob.get('/campaigns/1').status_code == 404
    assert bob.post('/campaigns/1', data={'csrf': token(bob)}).status_code == 404
    post(bob, '/contacts/1/consent')
    assert 'Đã đồng ý' in alice.get('/contacts').text
    assert alice.post('/contacts', data={'name': 'Bad', 'phone': '999'}).status_code == 400


def test_csv_transaction_and_duplicate_handling(app):
    client = app.test_client()
    register(client)
    result = post(client, '/contacts/import', {'file': (io.BytesIO('name,phone,consent\nLan,0901,1\nLan,0901,1'.encode()), 'contacts.csv')})
    assert 'Đã nhập 1 khách hàng, bỏ qua 1 số trùng' in result.text
    result = post(client, '/contacts/import', {'file': (io.BytesIO(b'name,phone\nTemporary,0902\nInvalid,'), 'bad.csv')})
    assert 'Không thể nhập CSV' in result.text
    assert 'Temporary' not in client.get('/contacts').text


def test_empty_audience_and_xss(app):
    client = app.test_client()
    register(client)
    post(client, '/campaigns', {'name': '<script>alert(1)</script>', 'message': '<img src=x onerror=alert(1)>'})
    result = post(client, '/campaigns/1')
    assert 'Cần có người đồng ý' in result.text
    assert '<script>alert(1)</script>' not in result.text
    assert '&lt;script&gt;' in result.text
    with sqlite3.connect(app.config['DATABASE']) as conn:
        assert conn.execute('SELECT status FROM campaigns').fetchone()[0] == 'draft'


def test_pages_render(app):
    client = app.test_client()
    assert client.get('/login').status_code == 200
    assert client.get('/register').status_code == 200
    register(client)
    for page in ['/', '/contacts', '/campaigns', '/settings', '/static/style.css']:
        assert client.get(page).status_code == 200


def test_campaign_filters_and_selected_logs(app):
    owner, other = app.test_client(), app.test_client()
    register(owner)
    post(owner, '/contacts', {'name': 'Lan', 'phone': '0901', 'tag': 'VIP', 'consent': 'on'})
    post(owner, '/campaigns', {'name': 'VIP Offer', 'message': 'Hello {{name}}', 'tag': 'VIP'})
    post(owner, '/campaigns/1')
    post(owner, '/campaigns', {'name': 'Old campaign', 'message': 'Old', 'tag': 'Khách mới'})
    with sqlite3.connect(app.config['DATABASE']) as conn:
        conn.execute("UPDATE campaigns SET created_at='2020-01-01 12:00:00' WHERE id=2")
    result = owner.get('/campaigns?days=7&status=simulated&tag=VIP&q=Offer&selected=1')
    assert 'VIP Offer' in result.text
    assert 'Old campaign' not in result.text
    assert 'Hello Lan' in result.text
    assert 'data-copy="Hello Lan"' in result.text
    assert 'VIP Offer' not in owner.get('/campaigns?status=draft').text
    assert 'Không tìm thấy chiến dịch' in owner.get('/campaigns?q=missing').text
    register(other, 'other')
    result = other.get('/campaigns?selected=1')
    assert 'Hello Lan' not in result.text
    assert 'VIP Offer' not in result.text


def test_zalo_profiles_are_persistent_and_private(app):
    owner, other = app.test_client(), app.test_client()
    register(owner)
    result = post(owner, '/accounts', {'name': 'Kế Toán Viettax', 'account_group': 'Kế toán'})
    assert 'Đã lưu hồ sơ tài khoản' in result.text
    assert 'Kế Toán Viettax' in owner.get('/accounts?group=Kế%20toán').text
    assert 'Kế Toán Viettax' not in owner.get('/accounts?group=Other').text
    assert 'Tên tài khoản đã có' in post(owner, '/accounts', {'name': 'Kế Toán Viettax'}).text
    assert 'Vui lòng nhập tên tài khoản' in post(owner, '/accounts', {'name': ''}).text
    register(other, 'other')
    assert 'Kế Toán Viettax' not in other.get('/accounts').text
    assert 'Chưa có tài khoản' in other.get('/accounts').text
