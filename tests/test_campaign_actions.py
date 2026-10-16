import csv
import io
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

import pytest
from PIL import Image

from app import create_app
from test_workflow import app, post, register, token
from test_send import setup_send, prepare


def query(app, sql, params=()):
    with sqlite3.connect(app.config['DATABASE']) as connection:
        return connection.execute(sql, params).fetchall()


def add_second_recipient(client):
    post(client, '/contacts', {'name': 'Binh', 'phone': '0912345678', 'consent': 'on', 'tag': 'VIP'})
    post(client, '/campaigns/1/prepare-send', {'contact_id': '2', 'account_id': '1'})


def limits(client, **overrides):
    return post(client, '/campaigns/1/limits', {
        'message_limit': '0', 'friend_limit': '0', 'alias_limit': '0', 'interval_seconds': '0', **overrides})


def image_file(color='red'):
    stream = io.BytesIO()
    Image.new('RGB', (8, 6), color).save(stream, format='PNG')
    stream.seek(0)
    return stream


def test_menu_and_every_management_page_are_available(app):
    client, _ = setup_send(app)
    page = client.get('/campaigns').text
    for text in ['Dừng chiến dịch', 'Sửa', 'Nhân bản', 'Lấy ID chiến dịch', 'Cập nhật giới hạn gửi',
                 'Cập nhật nội dung + media', 'Thêm data', 'Xem báo cáo chi tiết', 'Đăng nhập lại Zalo',
                 'Thông tin tài khoản', 'Lịch sử chạy', 'Xóa']:
        assert text in page
    for action in ['pause', 'duplicate', 'limits', 'content', 'data', 'report', 'history', 'account', 'delete']:
        assert client.get('/campaigns/1/' + action).status_code == 200
    assert client.get('/campaigns/1/reconnect').status_code == 302


def test_pause_blocks_all_actions_and_resume_does_not_repeat(app):
    client, connector = setup_send(app)
    post(client, '/campaigns/1/edit', {'name': 'All actions', 'message': 'Hello', 'tag': 'VIP',
        'options_present': 'yes', 'send_message': 'yes', 'send_friend': 'yes',
        'friend_message': 'Xin chào', 'rename_enabled': 'yes', 'rename_template': '#{FULL_NAME}'})
    prepare(client)
    post(client, '/campaigns/1/pause', {'paused': '1'})
    connector.message_action.reset_mock()
    for path, data in [('', {}), ('/prepare-send', {'contact_id': '1', 'account_id': '1'}),
                       ('/send/1', {'confirm_send': 'yes'}), ('/friend/1', {'confirm_friend': 'yes'}),
                       ('/alias/1', {'confirm_alias': 'yes'})]:
        response = client.post('/campaigns/1' + path, data={'csrf': token(client), **data})
        assert response.status_code == 409
    assert connector.message_action.call_count == 0
    assert 'All actions' in client.get('/campaigns?status=paused').text
    post(client, '/campaigns/1/pause', {'paused': '0'})
    connector.message_action.return_value = {'state': 'sent', 'message_id': '55'}
    post(client, '/campaigns/1/send/1', {'confirm_send': 'yes'})
    post(client, '/campaigns/1/pause', {'paused': '1'})
    post(client, '/campaigns/1/pause', {'paused': '0'})
    post(client, '/campaigns/1/send/1', {'confirm_send': 'yes'})
    assert connector.message_action.call_count == 1


def test_duplicate_copies_configuration_and_list_without_sends(app):
    client, connector = setup_send(app)
    post(client, '/campaigns/1/edit', {'name': 'Original', 'message': 'Hello', 'account_id': '1',
        'phones': '0901234567', 'phones_consent': 'yes', 'options_present': 'yes',
        'send_message': 'yes', 'send_friend': 'yes', 'friend_message': 'Hi',
        'rename_enabled': 'yes', 'rename_template': '#{PHONE}'})
    limits(client, message_limit='12', interval_seconds='60')
    post(client, '/campaigns/1/content', {'message': 'Hello', 'friend_message': 'Hi', 'media': (image_file(), 'test.png')})
    prepare(client)
    post(client, '/campaigns/1/pause', {'paused': '1'})
    connector.message_action.reset_mock()
    assert 'Bản sao' in post(client, '/campaigns/1/duplicate', {'name': 'Bản sao'}).text
    copied = query(app, 'SELECT status,paused,account_id,send_friend,rename_enabled,audience_mode,message_limit,interval_seconds,media_id FROM campaigns WHERE id=2')[0]
    assert copied[:8] == ('draft', 0, 1, 1, 1, 'list', 12, 60)
    assert copied[8] == query(app, 'SELECT media_id FROM campaigns WHERE id=1')[0][0]
    assert query(app, 'SELECT contact_id FROM campaign_contacts WHERE campaign_id=2') == [(1,)]
    assert query(app, 'SELECT count(*) FROM message_sends WHERE campaign_id=2') == [(0,)]
    assert connector.message_action.call_count == 0


def test_limits_count_uncertain_attempts_and_survive_restart(app):
    client, connector = setup_send(app)
    prepare(client)
    add_second_recipient(client)
    limits(client, message_limit='1')
    connector.message_action.return_value = {'state': 'unknown'}
    post(client, '/campaigns/1/send/1', {'confirm_send': 'yes'})
    response = client.post('/campaigns/1/send/2', data={'csrf': token(client), 'confirm_send': 'yes'})
    assert response.status_code == 409
    assert query(app, 'SELECT state FROM message_sends WHERE id=2') == [('prepared',)]
    restarted = create_app({'TESTING': True, 'DATABASE': app.config['DATABASE'], 'SECRET_KEY': 'test-only', 'ZALO_QR_ENABLED': True})
    resumed = restarted.test_client()
    post(resumed, '/login', {'username': 'an01', 'password': 'secure-password'})
    restarted.extensions['zalo_connector'].status = Mock(return_value={'state': 'connected'})
    assert resumed.post('/campaigns/1/send/2', data={'csrf': token(resumed), 'confirm_send': 'yes'}).status_code == 409
    limits(client, message_limit='2')
    connector.message_action.return_value = {'state': 'sent', 'message_id': '77'}
    post(client, '/campaigns/1/send/2', {'confirm_send': 'yes'})
    assert query(app, 'SELECT count(*) FROM campaign_attempts') == [(2,)]


def test_interval_and_rolling_window(app):
    client, connector = setup_send(app)
    prepare(client)
    add_second_recipient(client)
    limits(client, message_limit='1', interval_seconds='60')
    connector.message_action.return_value = {'state': 'sent', 'message_id': '77'}
    post(client, '/campaigns/1/send/1', {'confirm_send': 'yes'})
    limits(client, message_limit='2', interval_seconds='60')
    response = client.post('/campaigns/1/send/2', data={'csrf': token(client), 'confirm_send': 'yes'})
    assert response.status_code == 409 and 'khoảng cách' in response.text
    with sqlite3.connect(app.config['DATABASE']) as connection:
        connection.execute("UPDATE campaign_attempts SET created_at=datetime('now','-25 hours')")
    limits(client, message_limit='1', interval_seconds='60')
    post(client, '/campaigns/1/send/2', {'confirm_send': 'yes'})
    assert query(app, 'SELECT state FROM message_sends WHERE id=2') == [('sent',)]


def test_concurrent_sends_cannot_exceed_limit(app):
    client, connector = setup_send(app)
    prepare(client)
    add_second_recipient(client)
    limits(client, message_limit='1')
    clients = [app.test_client(), app.test_client()]
    tokens = []
    for item in clients:
        post(item, '/login', {'username': 'an01', 'password': 'secure-password'})
        tokens.append(token(item))
    connector.message_action.return_value = {'state': 'sent', 'message_id': '77'}
    connector.message_action.reset_mock()
    barrier = Barrier(2)
    def send(index):
        barrier.wait(timeout=5)
        return clients[index].post(f'/campaigns/1/send/{index+1}', data={'csrf': tokens[index], 'confirm_send': 'yes'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(send, [0, 1]))
    assert sorted(statuses) == [302, 409]
    assert connector.message_action.call_count == 1
    assert query(app, 'SELECT count(*) FROM campaign_attempts') == [(1,)]


def test_append_data_preserves_audience_details_and_send_history(app):
    client, connector = setup_send(app)
    prepare(client)
    post(client, '/contacts', {'name': 'Other group', 'phone': '0987654321', 'consent': 'on', 'tag': 'Other'})
    response = post(client, '/campaigns/1/data', {'phones': '+84 912 345 678\n0901234567\n0912345678', 'consent': 'yes'})
    assert 'Đã bổ sung 1 khách hàng' in response.text
    assert query(app, 'SELECT audience_mode FROM campaigns') == [('list',)]
    assert query(app, 'SELECT contact_id FROM campaign_contacts ORDER BY contact_id') == [(1,), (3,)]
    assert query(app, 'SELECT name,tag FROM contacts WHERE id=1') == [('Lan', 'VIP')]
    assert query(app, 'SELECT count(*) FROM message_sends') == [(1,)]
    post(client, '/campaigns/1/data', {'file': (io.BytesIO(b'phone,name,email,info1\n0923456789,New,new@example.com,Gold'), 'new.csv'), 'consent': 'yes'})
    assert query(app, 'SELECT name,email,info1 FROM contacts WHERE phone=?', ('0923456789',)) == [('New', 'new@example.com', 'Gold')]
    assert client.post('/campaigns/1/prepare-send', data={'csrf': token(client), 'contact_id': '2', 'account_id': '1'}).status_code == 400


def test_invalid_data_rolls_back_and_requires_consent(app):
    client, _ = setup_send(app)
    post(client, '/campaigns/1/data', {'phones': '0912345678'})
    post(client, '/campaigns/1/data', {'consent': 'yes', 'file': (io.BytesIO(b'phone,name\n0912345678,New\nbad,Bad'), 'bad.csv')})
    assert query(app, 'SELECT count(*) FROM contacts') == [(1,)]
    assert query(app, 'SELECT audience_mode FROM campaigns') == [('group',)]


def test_content_media_snapshot_and_access_control(app):
    client, connector = setup_send(app)
    post(client, '/campaigns/1/content', {'message': 'Old {{name}}', 'media': (image_file(), 'old.png')})
    media_id = query(app, 'SELECT media_id FROM campaigns')[0][0]
    prepare(client)
    post(client, '/campaigns/1/content', {'message': 'New {{name}}', 'media': (image_file('blue'), 'new.png')})
    assert query(app, 'SELECT message,media_id FROM message_sends') == [('Old Lan', media_id)]
    add_second_recipient(client)
    assert query(app, 'SELECT message,media_id FROM message_sends WHERE id=2') == [('New Binh', media_id+1)]
    assert client.get(f'/media/{media_id}').status_code == 200
    other = app.test_client()
    register(other, 'other')
    assert other.get(f'/media/{media_id}').status_code == 404
    connector.message_action.return_value = {'state': 'sent', 'message_id': '99'}
    post(client, '/campaigns/1/send/1', {'confirm_send': 'yes'})
    payload = connector.message_action.call_args.kwargs
    assert payload['message'] == 'Old Lan'
    assert payload['attachment']['filename'] == 'old.png'
    assert payload['attachment']['width'] == 8
    assert payload['attachment']['height'] == 6
    post(client, '/campaigns/1/content', {'message': 'No media', 'remove_media': 'yes'})
    assert query(app, 'SELECT media_id FROM campaigns') == [(None,)]
    assert client.get(f'/media/{media_id}').status_code == 200


@pytest.mark.parametrize('name,data', [('fake.png', b'not-an-image'), ('bad.exe', b'%PDF-1.4'), ('fake.pdf', b'not-pdf'), ('big.pdf', b'%PDF-'+b'x'*(10*1024*1024))])
def test_invalid_media_never_changes_content(app, name, data):
    client, _ = setup_send(app)
    post(client, '/campaigns/1/content', {'message': 'Changed', 'media': (io.BytesIO(data), name)})
    assert query(app, 'SELECT message,media_id FROM campaigns') == [('Xin chào {{name}}', None)]
    assert query(app, 'SELECT count(*) FROM campaign_media') == [(0,)]


def test_missing_media_blocks_dispatch_without_claim(app):
    client, connector = setup_send(app)
    post(client, '/campaigns/1/content', {'message': 'Hello', 'media': (image_file(), 'old.png')})
    prepare(client)
    media_path = next(app.extensions['campaign_manager'].media_root.iterdir())
    media_path.unlink()
    connector.message_action.reset_mock()
    assert client.post('/campaigns/1/send/1', data={'csrf': token(client), 'confirm_send': 'yes'}).status_code == 400
    assert connector.message_action.call_count == 0
    assert query(app, 'SELECT state FROM message_sends') == [('prepared',)]


def test_delete_hides_campaign_blocks_dispatch_and_keeps_report(app):
    client, connector = setup_send(app)
    prepare(client)
    assert client.post('/campaigns/1/delete', data={'csrf': token(client)}).status_code == 400
    post(client, '/campaigns/1/delete', {'confirm_delete': 'yes'})
    connector.message_action.reset_mock()
    assert 'popovertarget="actions-1"' not in client.get('/campaigns').text
    assert 'Chăm sóc' in client.get('/campaigns?status=deleted').text
    assert client.get('/campaigns/1').status_code == 404
    assert client.post('/campaigns/1/send/1', data={'csrf': token(client), 'confirm_send': 'yes'}).status_code == 404
    assert connector.message_action.call_count == 0
    assert client.get('/campaigns/1/report').status_code == 200
    assert 'Xóa khỏi danh sách' in client.get('/campaigns/1/history').text
    assert query(app, 'SELECT count(*) FROM message_sends') == [(1,)]
    assert query(app, 'SELECT count(*) FROM contacts') == [(1,)]


def test_reports_csv_and_history_match_real_outcomes(app):
    client, connector = setup_send(app)
    with sqlite3.connect(app.config['DATABASE']) as connection:
        connection.execute("UPDATE contacts SET name='=UNTRUSTED()'")
    prepare(client)
    connector.message_action.return_value = {'state': 'sent', 'message_id': '99'}
    post(client, '/campaigns/1/send/1', {'confirm_send': 'yes'})
    report = client.get('/campaigns/1/report')
    assert '99' in report.text and 'Zalo đã tiếp nhận' in report.text
    exported = client.get('/campaigns/1/report?format=csv')
    rows = list(csv.reader(io.StringIO(exported.data.decode('utf-8-sig'))))
    assert rows[1][1] == "'=UNTRUSTED()"
    assert rows[1][5] == 'Zalo đã tiếp nhận'
    assert rows[1][8] == '99'
    assert 'Bản gửi #1' in client.get('/campaigns/1/history').text


def test_all_new_routes_enforce_ownership_and_csrf(app):
    owner, _ = setup_send(app)
    other = app.test_client()
    register(other, 'other')
    for action in ['pause', 'duplicate', 'limits', 'content', 'data', 'delete', 'history', 'report', 'account', 'reconnect']:
        assert other.get('/campaigns/1/' + action).status_code == 404
    for action in ['pause', 'duplicate', 'limits', 'content', 'data', 'delete']:
        assert owner.post('/campaigns/1/' + action).status_code == 400
        assert other.post('/campaigns/1/' + action, data={'csrf': token(other)}).status_code == 404


def test_reconnect_uses_selected_account_and_no_foreign_profiles(app):
    client, _ = setup_send(app)
    post(client, '/campaigns/1/edit', {'name': 'Selected', 'message': 'Hi', 'account_id': '1'})
    response = client.get('/campaigns/1/reconnect')
    assert response.location.endswith('/accounts?connect=1')
    assert 'Zalo của tôi' in client.get('/campaigns/1/account').text


def test_friend_and_alias_limits_use_separate_counters(app):
    client, connector = setup_send(app)
    post(client, '/campaigns/1/edit', {'name': 'Actions', 'message': 'Hello', 'tag': 'VIP',
        'options_present': 'yes', 'send_message': 'yes', 'send_friend': 'yes',
        'friend_message': 'Xin chào', 'rename_enabled': 'yes', 'rename_template': '#{FULL_NAME}'})
    prepare(client)
    add_second_recipient(client)
    limits(client, message_limit='1', friend_limit='1', alias_limit='1')
    for path, confirm, state in [('friend', 'confirm_friend', 'friend_requested'), ('alias', 'confirm_alias', 'renamed'), ('send', 'confirm_send', 'sent')]:
        connector.message_action.return_value = {'state': state, 'message_id': '77'}
        assert post(client, f'/campaigns/1/{path}/1', {confirm: 'yes'}).status_code == 200
        assert client.post(f'/campaigns/1/{path}/2', data={'csrf': token(client), confirm: 'yes'}).status_code == 409
    assert query(app, 'SELECT action,count(*) FROM campaign_attempts GROUP BY action ORDER BY action') == [('alias', 1), ('friend', 1), ('send', 1)]


def test_pause_during_recipient_lookup_prevents_preview(app):
    client, connector = setup_send(app)
    def resolve(*args, **kwargs):
        with sqlite3.connect(app.config['DATABASE']) as connection:
            connection.execute('UPDATE campaigns SET paused=1 WHERE id=1')
        return {'state': 'resolved', 'uid': '123456', 'name': 'Lan'}
    connector.message_action.side_effect = resolve
    response = client.post('/campaigns/1/prepare-send', data={'csrf': token(client), 'contact_id': '1', 'account_id': '1'})
    assert response.status_code == 409
    assert query(app, 'SELECT count(*) FROM message_sends') == [(0,)]


def test_changed_preview_between_read_and_claim_cannot_dispatch_stale_content(app):
    client, connector = setup_send(app)
    prepare(client)
    def status(*args):
        with sqlite3.connect(app.config['DATABASE']) as connection:
            connection.execute("UPDATE message_sends SET message='Replacement preview' WHERE id=1")
        return {'state': 'connected'}
    connector.status.side_effect = status
    connector.message_action.reset_mock()
    response = client.post('/campaigns/1/send/1', data={'csrf': token(client), 'confirm_send': 'yes'})
    assert response.status_code == 409
    assert connector.message_action.call_count == 0
    assert query(app, 'SELECT state FROM message_sends') == [('prepared',)]
    assert query(app, 'SELECT count(*) FROM campaign_attempts') == [(0,)]


def test_upgrade_existing_campaigns_preserves_lists_and_attempts(app):
    client, _ = setup_send(app)
    post(client, '/campaigns/1/edit', {'name': 'Legacy', 'message': 'Hello',
        'phones': '0901234567', 'phones_consent': 'yes'})
    prepare(client)
    with sqlite3.connect(app.config['DATABASE']) as connection:
        connection.execute("UPDATE message_sends SET state='sent',message_id='legacy-id'")
        for table in ['campaign_attempts', 'campaign_events', 'campaign_media']:
            connection.execute(f'DROP TABLE {table}')
        for column in ['paused', 'deleted_at', 'audience_mode', 'media_id', 'message_limit', 'friend_limit', 'alias_limit', 'interval_seconds']:
            connection.execute(f'ALTER TABLE campaigns DROP COLUMN {column}')
        connection.execute('ALTER TABLE message_sends DROP COLUMN media_id')
    config = {'TESTING': True, 'DATABASE': app.config['DATABASE'], 'SECRET_KEY': 'test-only'}
    create_app(config)
    create_app(config)
    assert query(app, 'SELECT audience_mode,paused FROM campaigns') == [('list', 0)]
    assert query(app, 'SELECT contact_id FROM campaign_contacts') == [(1,)]
    assert query(app, 'SELECT state,message_id FROM message_sends') == [('sent', 'legacy-id')]
    assert query(app, 'SELECT action,count(*) FROM campaign_attempts GROUP BY action') == [('send', 1)]


def test_invalid_limits_and_data_overflow_do_not_modify_campaign(app):
    client, _ = setup_send(app)
    for value in ['-1', '1.5', '86401', 'invalid']:
        limits(client, message_limit=value)
        assert query(app, 'SELECT message_limit FROM campaigns') == [(0,)]
    phones = '\n'.join('09' + str(index).zfill(8) for index in range(501))
    post(client, '/campaigns/1/data', {'phones': phones, 'consent': 'yes'})
    assert query(app, 'SELECT count(*) FROM contacts') == [(1,)]
