import sqlite3

from test_workflow import app, post, register, token


def test_phone_campaign_deduplicates_and_excludes_other_contacts(app):
    client = app.test_client()
    register(client)
    post(client, '/accounts', {'name': 'Viettax'})
    post(client, '/contacts', {'name': 'Lan', 'phone': '0901234567', 'consent': 'on', 'tag': 'VIP'})
    post(client, '/contacts', {'name': 'Ngoài danh sách', 'phone': '0999999999', 'consent': 'on'})
    result = post(client, '/campaigns', {'name': 'Gửi theo số', 'message': 'Xin chào {{name}}',
        'account_id': '1', 'phones': '0901234567\n+84 901 234 567\n0912345678', 'phones_consent': 'yes'})
    assert 'Gửi theo số' in result.text and 'Lan' in result.text
    assert 'Ngoài danh sách' not in result.text
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT count(*) FROM campaign_contacts').fetchone()[0] == 2
        assert db.execute('SELECT name,tag FROM contacts WHERE phone=?', ('0901234567',)).fetchone() == ('Lan', 'VIP')
        assert db.execute('SELECT account_id FROM campaigns').fetchone()[0] == 1
    # Preview/send policy also uses the explicit list, rather than all consented contacts.
    assert client.post('/campaigns/1/prepare-send', data={'csrf': token(client), 'contact_id': '2', 'account_id': '1'}).status_code == 400
    post(client, '/campaigns/1')
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT count(*) FROM deliveries').fetchone()[0] == 2


def test_editor_validation_and_ownership(app):
    owner, other = app.test_client(), app.test_client()
    register(owner)
    for values in ({'phones': '0901234567'}, {'phones': 'bad', 'phones_consent': 'yes'}, {'account_id': '999'}, {'action': 'friend'}):
        post(owner, '/campaigns', {'name': 'Invalid', 'message': 'Hello', **values})
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT count(*) FROM campaigns').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM contacts').fetchone()[0] == 0
    post(owner, '/campaigns', {'name': 'Draft', 'message': 'Hello'})
    assert 'Sửa chiến dịch' in owner.get('/campaigns/1/edit').text
    result = post(owner, '/campaigns/1/edit', {'name': 'Updated', 'message': 'Xin chào',
        'phones': '0901234567', 'phones_consent': 'yes'})
    assert 'Updated' in result.text
    register(other, 'other')
    assert other.get('/campaigns/1/edit').status_code == 404
    assert other.post('/campaigns/1/edit', data={'csrf': token(other), 'name': 'Bad', 'message': 'Bad'}).status_code == 404
    assert owner.post('/campaigns/1/edit', data={'name': 'Bad', 'message': 'Bad'}).status_code == 400
    post(owner, '/campaigns/1')
    post(owner, '/campaigns/1/edit', {'name': 'Bad', 'message': 'Bad'})
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT name FROM campaigns').fetchone()[0] == 'Updated'
