import sqlite3
from unittest.mock import Mock

from app import create_app
from test_qr import prepare as prepare_connector
from test_send import setup_send, prepare
from test_workflow import app, post, register, token


def test_delete_requires_owner_csrf_and_confirmation(app, tmp_path):
    owner, other = app.test_client(), app.test_client()
    register(owner)
    post(owner, '/accounts', {'name': 'Test'})
    register(other, 'other')
    connector = prepare_connector(app, tmp_path)
    connector.disconnect = Mock()
    assert owner.get('/accounts/1/delete').status_code == 405
    assert owner.post('/accounts/1/delete', data={'confirm_delete': 'yes'}).status_code == 400
    assert owner.post('/accounts/1/delete', data={'csrf': token(owner)}).status_code == 400
    assert other.post('/accounts/1/delete', data={'csrf': token(other), 'confirm_delete': 'yes'}).status_code == 404
    assert not connector.disconnect.called
    assert 'data-delete-account-id="1"' in owner.get('/accounts').text


def test_delete_clears_login_pauses_only_affected_campaign_and_preserves_history(app, tmp_path):
    client, connector = setup_send(app)
    connector = prepare_connector(app, tmp_path)
    prepare(client)
    connector.message_action.return_value = {'state': 'sent', 'message_id': 'saved-id'}
    post(client, '/campaigns/1/send/1', {'confirm_send': 'yes'})
    post(client, '/accounts', {'name': 'Other', 'account_group': 'Keep'})
    post(client, '/campaigns', {'name': 'Unrelated', 'message': 'Hello', 'account_id': '2'})
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('UPDATE zalo_accounts SET account_group=? WHERE id=1', ('Only deleted',))
        db.execute('UPDATE campaigns SET account_id=1,schedule_enabled=1,schedule_revision=5 WHERE id=1')
        before = db.execute('SELECT * FROM message_sends').fetchall()
        attempts = db.execute('SELECT * FROM campaign_attempts').fetchall()
        other = db.execute('SELECT * FROM campaigns WHERE id=2').fetchone()
    login = connector.account_path(1, 1)
    login.mkdir(parents=True)
    (login / 'credentials.enc').write_text('test-only')
    keep = connector.account_path(1, 2)
    keep.mkdir(parents=True)
    response = post(client, '/accounts/1/delete', {'confirm_delete': 'yes'})
    assert response.status_code == 200 and 'Đã xóa tài khoản và phiên đăng nhập' in response.text
    assert 'data-delete-account-id="1"' not in response.text
    assert 'data-delete-account-id="2"' in response.text
    assert 'Only deleted' not in response.text
    assert not login.exists() and keep.exists()
    assert client.get('/accounts/status').json == {'accounts': [{'id': 2, 'state': 'connected'}]}
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        assert db.execute('SELECT * FROM message_sends').fetchall() == before
        assert db.execute('SELECT * FROM campaign_attempts').fetchall() == attempts
        assert db.execute('SELECT account_id,paused,schedule_enabled,schedule_revision FROM campaigns WHERE id=1').fetchone() == (None, 1, 0, 6)
        assert db.execute('SELECT * FROM campaigns WHERE id=2').fetchone() == other
        assert db.execute("SELECT count(*) FROM campaign_events WHERE campaign_id=1 AND kind='account_deleted'").fetchone()[0] == 1
    assert 'saved-id' in client.get('/campaigns/1').text
    detail = client.get('/campaigns?selected=1&detail_tab=accounts').text
    assert 'Zalo của tôi (đã xóa #1)' in detail
    assert 'connect=1' not in client.get('/campaigns/1/account').text
    assert client.post('/accounts/1/delete', data={'csrf': token(client), 'confirm_delete': 'yes'}).status_code == 404
    # Migration is repeatable; a restart must not reactivate the deleted profile.
    restarted = create_app({'TESTING': True, 'DATABASE': app.config['DATABASE'], 'SECRET_KEY': 'test-only'})
    with sqlite3.connect(restarted.config['DATABASE']) as db:
        assert db.execute('SELECT deleted_at FROM zalo_accounts WHERE id=1').fetchone()[0]


def test_deleted_profile_cannot_be_used_from_old_tabs_or_reused_for_new_login(app, tmp_path):
    client, connector = setup_send(app)
    prepare_connector(app, tmp_path)
    prepare(client)
    post(client, '/accounts/1/delete', {'confirm_delete': 'yes'})
    connector.start = Mock(return_value={'state': 'loading'})
    connector.message_action.reset_mock()
    assert client.get('/accounts/1/qr').status_code == 404
    assert client.post('/accounts/1/qr', data={'csrf': token(client), 'accept_unofficial': 'yes'}).status_code == 404
    assert client.post('/accounts/1/disconnect', data={'csrf': token(client)}).status_code == 404
    assert client.post('/campaigns/1/prepare-send', data={'csrf': token(client), 'contact_id': '1', 'account_id': '1'}).status_code == 400
    # This campaign used a manual sender; its default account is NULL, so the
    # claim must independently reject an old immutable preview after deletion.
    assert client.post('/campaigns/1/send/1', data={'csrf': token(client), 'confirm_send': 'yes'}).status_code == 409
    assert not connector.start.called and not connector.message_action.called
    response = post(client, '/accounts', {'name': 'Zalo của tôi'})
    assert 'data-auto-connect="2"' in response.text
    assert client.post('/campaigns/1/send/1', data={'csrf': token(client), 'confirm_send': 'yes'}).status_code == 409
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT account_id,state FROM message_sends').fetchone() == (1, 'prepared')
        assert db.execute('SELECT count(*) FROM campaign_attempts').fetchone()[0] == 0
    for url in ('/campaigns', '/campaigns/1/edit', '/campaigns/1/schedule'):
        assert '<option value="1"' not in client.get(url).text
    result = post(client, '/campaigns', {'name': 'Invalid sender', 'message': 'Hi', 'account_id': '1'})
    assert 'Tài khoản Zalo không hợp lệ' in result.text


def test_delete_cleanup_failure_rolls_back_and_does_not_leak_details(app, tmp_path):
    client, connector = setup_send(app)
    prepare_connector(app, tmp_path)
    connector.disconnect = Mock(side_effect=OSError('private/session/path'))
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('UPDATE campaigns SET account_id=1,schedule_enabled=1 WHERE id=1')
        before = db.execute('SELECT * FROM campaigns').fetchall()
    response = post(client, '/accounts/1/delete', {'confirm_delete': 'yes'})
    assert 'Chưa xóa được phiên đăng nhập' in response.text
    assert 'private/session/path' not in response.text
    assert 'data-delete-account-id="1"' in response.text
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT deleted_at,name FROM zalo_accounts').fetchone() == (None, 'Zalo của tôi')
        assert db.execute('SELECT * FROM campaigns').fetchall() == before
        assert db.execute("SELECT count(*) FROM campaign_events WHERE kind='account_deleted'").fetchone()[0] == 0


def test_deleted_archive_name_collision_does_not_block_deletion(app, tmp_path):
    client = app.test_client()
    register(client)
    prepare_connector(app, tmp_path)
    post(client, '/accounts', {'name': 'Test'})
    post(client, '/accounts', {'name': 'Test (đã xóa #1)'})
    response = post(client, '/accounts/1/delete', {'confirm_delete': 'yes'})
    assert 'Đã xóa tài khoản và phiên đăng nhập' in response.text
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT name FROM zalo_accounts WHERE id=1').fetchone()[0] == 'Test (đã xóa #1) -2'
        assert db.execute('SELECT deleted_at FROM zalo_accounts WHERE id=2').fetchone()[0] is None
