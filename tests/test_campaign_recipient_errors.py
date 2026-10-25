import json

from test_workflow import app
from test_campaign_schedule import setup,tick,moment,campaign
from test_campaign_sequence import all_actions
from test_lookup_skip import add_contact
from test_message_composer import query
from test_campaign_list import campaign_status
from test_lookup_diagnostics import connector as worker_connector
from datetime import timedelta


def test_stranger_message_refusal_still_invites_renames_and_continues_next_recipient(app):
    client,connector=setup(app);add_contact(client);all_actions(client)
    def call(user,account,action,**data):
        if action=='resolve':return dict(state='resolved',uid=data['phone'],name='Found')
        if action=='send' and data['uid']=='0901234567':
            return dict(state='failed',error_reason='stranger_messages_blocked',error_code='221',message='PRIVATE_RAW')
        return dict(state={'send':'sent','friend':'friend_requested','alias':'renamed'}[action])
    connector.message_action.side_effect=call
    clock=moment()
    tick(app,clock);tick(app,clock+timedelta(seconds=1))
    assert campaign_status(client)==['Đang xử lý']
    for second in [2,3,122,123,124,125,126]:tick(app,clock+timedelta(seconds=second))
    assert [c.args[2] for c in connector.message_action.call_args_list]==['resolve','send','friend','alias','resolve','send','friend','alias']
    assert query(app,'SELECT state,friend_state,alias_state FROM message_sends ORDER BY id')==[('failed','friend_requested','renamed'),('sent','friend_requested','renamed')]
    assert query(app,"SELECT error_reason,error_code FROM campaign_attempts WHERE send_id=1 AND action='send'")==[('stranger_messages_blocked','221')]
    page=client.get('/campaigns?selected=1&detail_tab=results').text
    assert 'Người nhận chặn tin nhắn từ người lạ (mã 221)' in page
    history=client.get('/campaigns/1/history').text
    assert 'Người nhận chặn tin nhắn từ người lạ' in history and 'PRIVATE_RAW' not in history
    assert not campaign(app)['schedule_error']


def test_blocked_lookup_code_210_is_logged_then_next_phone_runs_after_rest(app):
    client,connector=setup(app);add_contact(client);all_actions(client)
    def call(user,account,action,**data):
        if action=='resolve':
            if data['phone']=='0901234567':return dict(state='lookup_failed',lookup_reason='recipient_blocked',lookup_code='210')
            return dict(state='resolved',uid=data['phone'],name='Found')
        return dict(state={'send':'sent','friend':'friend_requested','alias':'renamed'}[action])
    connector.message_action.side_effect=call
    clock=moment();tick(app,clock);tick(app,clock+timedelta(seconds=119))
    assert connector.message_action.call_count==1
    assert query(app,'SELECT lookup_state,state,friend_state,alias_state FROM message_sends')==[('blocked','not_requested','not_requested','not_requested')]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(0,)]
    for second in range(120,124):tick(app,clock+timedelta(seconds=second))
    assert connector.message_action.call_count==5
    assert 'Người nhận bị Zalo chặn (mã 210)' in client.get('/campaigns/1/history').text
    page=client.get('/campaigns?selected=1&detail_tab=results').text
    assert 'Bị Zalo chặn' in page and 'Người nhận bị Zalo chặn (mã 210)' in page
    assert not campaign(app)['schedule_error']


def test_public_action_diagnostics_cross_bridge_but_raw_secrets_do_not(tmp_path,monkeypatch):
    worker=worker_connector(tmp_path,monkeypatch,json.dumps(dict(state='failed',error_reason='stranger_messages_blocked',error_code='221',message='PRIVATE',token='PRIVATE')))
    assert worker.message_action(1,1,'send',uid='123',message='Hi')==dict(state='failed',error_reason='stranger_messages_blocked',error_code='221')
    worker=worker_connector(tmp_path/'other',monkeypatch,json.dumps(dict(state='failed',error_reason='PRIVATE',error_code='PRIVATE/path')))
    assert worker.message_action(1,1,'send',uid='123',message='Hi')==dict(state='failed')
    worker=worker_connector(tmp_path/'blocked',monkeypatch,json.dumps(dict(state='lookup_failed',lookup_reason='recipient_blocked',lookup_code='210',message='PRIVATE')))
    assert worker.message_action(1,1,'resolve',phone='0901234567')==dict(state='lookup_failed',lookup_reason='recipient_blocked',lookup_code='210')


def test_partial_send_with_refusal_stays_uncertain_and_is_not_retried(app):
    client,connector=setup(app);add_contact(client);all_actions(client,interval=0)
    def call(user,account,action,**data):
        if action=='resolve':return dict(state='resolved',uid=data['phone'],name='Found')
        if data['uid']=='0901234567':return dict(state='unknown',error_reason='stranger_messages_blocked')
        return dict(state={'send':'sent','friend':'friend_requested','alias':'renamed'}[action])
    connector.message_action.side_effect=call
    for _ in range(10):tick(app)
    assert query(app,'SELECT state,friend_state,alias_state FROM message_sends ORDER BY id')==[('unknown','not_requested','not_requested'),('sent','friend_requested','renamed')]
    assert connector.message_action.call_count==6
    assert query(app,"SELECT count(*) FROM campaign_attempts WHERE send_id=1")==[(1,)]
    assert not campaign(app)['schedule_error']
