import sqlite3
from unittest.mock import Mock
from test_workflow import app, post, register, token


def setup_friend(app, message_enabled=True):
    app.config['ZALO_QR_ENABLED'] = True
    client = app.test_client()
    register(client)
    post(client, '/accounts', {'name': 'My Zalo'})
    post(client, '/contacts', {'name': 'Lan', 'phone': '0901234567', 'consent': 'on'})
    data = {'name': 'Connect', 'options_present': 'yes', 'send_friend': 'yes',
            'friend_message': 'Xin chào {{name}}, kết nối nhé', 'message': 'Chào {{name}}'}
    if message_enabled:
        data['send_message'] = 'yes'
    post(client, '/campaigns', data)
    connector = app.extensions['zalo_connector']
    connector.status = Mock(return_value={'state': 'connected'})
    connector.message_action = Mock(return_value={'state': 'resolved', 'uid': '123456', 'name': 'Lan Zalo'})
    post(client, '/campaigns/1/prepare-send', {'contact_id': '1', 'account_id': '1'})
    connector.message_action.reset_mock()
    return client, connector


def test_friend_is_confirmed_separately_and_never_sent_twice(app):
    client, connector = setup_friend(app)
    assert client.post('/campaigns/1/friend/1', data={'csrf': token(client)}).status_code == 400
    connector.message_action.return_value = {'state': 'friend_requested'}
    response = post(client, '/campaigns/1/friend/1', {'confirm_friend': 'yes'})
    assert 'Chưa xác nhận người nhận chấp nhận kết bạn' in response.text
    assert 'Gửi tin thật' in response.text
    post(client, '/campaigns/1/friend/1', {'confirm_friend': 'yes'})
    post(client, '/campaigns/1/cancel-send/1')
    assert connector.message_action.call_count == 1
    assert connector.message_action.call_args.args[-1] == 'friend'
    assert connector.message_action.call_args.kwargs['message'] == 'Xin chào Lan, kết nối nhé'
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT friend_state,state FROM message_sends').fetchone() == ('friend_requested', 'prepared')


def test_friend_only_unknown_result_and_permissions(app):
    client, connector = setup_friend(app, False)
    assert 'Gửi tin thật' not in client.get('/campaigns/1').text
    assert client.post('/campaigns/1/friend/1', data={'confirm_friend': 'yes'}).status_code == 400
    other = app.test_client()
    register(other, 'other')
    assert other.post('/campaigns/1/friend/1', data={'csrf': token(other), 'confirm_friend': 'yes'}).status_code == 404
    connector.message_action.side_effect = RuntimeError('private error')
    response = post(client, '/campaigns/1/friend/1', {'confirm_friend': 'yes'})
    assert 'Chưa xác định lời mời' in response.text and 'private error' not in response.text
    post(client, '/campaigns/1/friend/1', {'confirm_friend': 'yes'})
    post(client, '/campaigns/1/send/1', {'confirm_send': 'yes'})
    assert connector.message_action.call_count == 1


def test_actions_and_invitation_length_are_validated(app):
    client = app.test_client()
    register(client)
    for data in ({}, {'send_friend': 'yes'}, {'send_friend': 'yes', 'friend_message': 'x' * 151}):
        post(client, '/campaigns', {'name': 'Invalid', 'message': 'Hello', 'options_present': 'yes', **data})
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT count(*) FROM campaigns').fetchone()[0] == 0
