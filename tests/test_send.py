import sqlite3
from unittest.mock import Mock

from test_workflow import app, post, register, token


def setup_send(app):
    app.config['ZALO_QR_ENABLED'] = True
    client = app.test_client()
    register(client)
    post(client, '/accounts', {'name': 'Zalo của tôi'})
    post(client, '/contacts', {'name': 'Lan', 'phone': '0901234567', 'consent': 'on', 'tag': 'VIP'})
    post(client, '/campaigns', {'name': 'Chăm sóc', 'message': 'Xin chào {{name}}', 'tag': 'VIP'})
    connector = app.extensions['zalo_connector']
    connector.status = Mock(return_value={'state': 'connected'})
    connector.message_action = Mock(return_value={'state': 'resolved', 'uid': '123456', 'name': 'Lan Zalo'})
    return client, connector


def prepare(client):
    return post(client, '/campaigns/1/prepare-send', {'contact_id': '1', 'account_id': '1'})


def test_preview_confirmation_and_duplicate_delivery(app):
    client, connector = setup_send(app)
    response = prepare(client)
    assert 'Lan Zalo' in response.text and 'Xin chào Lan' in response.text
    assert 'Gửi tin thật' in response.text
    blocked = post(client, '/campaigns/1/edit', {'name': 'Changed', 'message': 'Changed'})
    assert 'Không sửa để giữ nguyên nội dung nhật ký' in blocked.text
    assert connector.message_action.call_args.args[-1] == 'resolve'
    assert client.post('/campaigns/1/send/1', data={'csrf': token(client)}).status_code == 400
    connector.message_action.reset_mock()
    connector.message_action.return_value = {'state': 'sent', 'message_id': '999'}
    response = post(client, '/campaigns/1/send/1', {'confirm_send': 'yes'})
    assert 'Zalo đã tiếp nhận' in response.text and '999' in response.text
    post(client, '/campaigns/1/send/1', {'confirm_send': 'yes'})
    prepare(client)
    assert connector.message_action.call_count == 1
    assert connector.message_action.call_args.kwargs == {'uid': '123456', 'message': 'Xin chào Lan'}
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT count(*) FROM deliveries').fetchone()[0] == 0
        assert db.execute('SELECT state FROM message_sends').fetchone()[0] == 'sent'


def test_send_ownership_csrf_and_withdrawn_consent(app):
    owner, connector = setup_send(app)
    prepare(owner)
    assert owner.post('/campaigns/1/send/1', data={'confirm_send': 'yes'}).status_code == 400
    other = app.test_client()
    register(other, 'other')
    assert other.post('/campaigns/1/send/1', data={'csrf': token(other), 'confirm_send': 'yes'}).status_code == 404
    assert other.post('/campaigns/1/prepare-send', data={'csrf': token(other), 'account_id': 1, 'contact_id': 1}).status_code == 404
    post(owner, '/contacts/1/consent')
    assert owner.post('/campaigns/1/send/1', data={'csrf': token(owner), 'confirm_send': 'yes'}).status_code == 400
    assert connector.message_action.call_count == 1


def test_uncertain_send_never_retried_and_preview_cancellable(app):
    client, connector = setup_send(app)
    prepare(client)
    post(client, '/campaigns/1/cancel-send/1')
    prepare(client)
    connector.message_action.reset_mock()
    connector.message_action.side_effect = RuntimeError('private upstream details')
    response = post(client, '/campaigns/1/send/1', {'confirm_send': 'yes'})
    assert 'Chưa xác định' in response.text
    assert 'private upstream' not in response.text
    post(client, '/campaigns/1/send/1', {'confirm_send': 'yes'})
    post(client, '/campaigns/1/cancel-send/1')
    assert connector.message_action.call_count == 1
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT state FROM message_sends').fetchone()[0] == 'unknown'


def test_lookup_failure_and_disconnected_account_never_send(app):
    client, connector = setup_send(app)
    connector.message_action.return_value = {'state': 'failed'}
    assert 'Không tìm được người nhận' in prepare(client).text
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT count(*) FROM message_sends').fetchone()[0] == 0
    connector.message_action.return_value = {'state': 'resolved', 'uid': '123456', 'name': 'Lan'}
    prepare(client)
    connector.status.return_value = {'state': 'disconnected'}
    assert client.post('/campaigns/1/send/1', data={'csrf': token(client), 'confirm_send': 'yes'}).status_code == 400


def test_interrupted_dispatch_stays_claimed_after_app_restart(app):
    from app import create_app
    client, connector = setup_send(app)
    prepare(client)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE message_sends SET state='sending'")
    restarted = create_app({'TESTING': True, 'DATABASE': app.config['DATABASE'],
                            'SECRET_KEY': 'test-only', 'ZALO_QR_ENABLED': True})
    restarted_connector = restarted.extensions['zalo_connector']
    restarted_connector.status = Mock(return_value={'state': 'connected'})
    restarted_connector.message_action = Mock()
    new_client = restarted.test_client()
    post(new_client, '/login', {'username': 'an01', 'password': 'secure-password'})
    response = post(new_client, '/campaigns/1/send/1', {'confirm_send': 'yes'})
    assert 'Không gửi lại để tránh trùng tin' in response.text
    assert not restarted_connector.message_action.called
