"""Pending steps remain distinct from attempts made on the same recipient."""
import json
import sqlite3

import pytest

from app import create_app
from test_workflow import app,post,token
from test_campaign_schedule import setup,tick,moment,configure
from test_campaign_sequence import all_actions
from test_lookup_skip import add_contact
from test_message_composer import query


def edit(client,**extra):
    fields=dict(name='Edited',message='Mới {{name}}',tag='VIP',account_id='1',options_present='yes',send_message='yes',send_friend='yes',friend_message='Lời mời mới',rename_enabled='yes',rename_template='Mới #{FULL_NAME}')
    fields.update(extra);return post(client,'/campaigns/1/edit',fields)


def payload_id(app,action,send_id=1):
    return query(app,'SELECT id FROM campaign_action_payloads WHERE send_id=? AND action=? AND active=1',(send_id,action))[0][0]


def test_waiting_message_survives_edit_after_other_steps_have_run_and_limits_are_kept(app):
    client,connector=setup(app);add_contact(client);all_actions(client,interval=0);post(client,'/campaigns/1/limits',dict(message_limit='1'))
    for _ in range(8):tick(app)
    assert query(app,'SELECT state,friend_state,alias_state FROM message_sends ORDER BY id')==[('sent','friend_requested','renamed'),('prepared','friend_requested','renamed')]
    old_attempts=query(app,'SELECT * FROM campaign_attempts');old=query(app,'SELECT * FROM message_sends WHERE id=1')
    assert edit(client,rich_message='yes',message_html='<span data-style="c_db342e">Mới {{name}}</span>').status_code==200
    assert query(app,'SELECT state FROM message_sends WHERE id=2')==[('prepared',)]
    assert query(app,'SELECT * FROM campaign_attempts')==old_attempts
    for _ in range(3):tick(app)
    assert query(app,'SELECT state FROM message_sends WHERE id=2')==[('prepared',)]
    post(client,'/campaigns/1/limits',dict(message_limit='10'))
    tick(app)
    assert connector.message_action.call_args.args[2]=='send'
    assert connector.message_action.call_args.kwargs['message']=='Mới Next customer'
    assert connector.message_action.call_args.kwargs['styles'][0]['st']=='c_db342e'
    assert query(app,'SELECT * FROM message_sends WHERE id=1')==old
    assert query(app,"SELECT count(*) FROM campaign_attempts WHERE send_id=2 AND action='friend'")==[(1,)]
    assert 'Mới Next customer' in client.get('/campaigns/1/report').text
    tick(app);assert query(app,'SELECT count(*) FROM campaign_attempts')==[(6,)]


def test_sent_step_is_frozen_but_friend_and_alias_continue_with_new_content(app):
    client,connector=setup(app);all_actions(client,interval=0);tick(app);tick(app)
    old=query(app,"SELECT * FROM campaign_attempts WHERE action='send'")
    edit(client)
    assert query(app,'SELECT state,friend_state,alias_state FROM message_sends')==[('sent','prepared','prepared')]
    tick(app);tick(app)
    calls=connector.message_action.call_args_list
    assert [c.args[2] for c in calls]==['resolve','send','friend','alias']
    assert calls[-2].kwargs['message']=='Lời mời mới'
    assert calls[-1].kwargs['message']=='Mới Lan Zalo'
    assert query(app,"SELECT * FROM campaign_attempts WHERE action='send'")==old
    report=client.get('/campaigns/1/report').text
    assert 'Hello Lan' in report and 'Lời mời mới' in report and 'Mới Lan Zalo' in report


def test_old_manual_confirmation_cannot_send_a_new_pending_payload(app):
    client,connector=setup(app);all_actions(client,interval=0);tick(app);tick(app)
    # Manual confirmation must also obey the configured schedule; turn it off for this test.
    post(client,'/campaigns/1/schedule',dict(schedule_present='yes'))
    edit(client);first=payload_id(app,'friend')
    connector.message_action.reset_mock()
    assert post(client,'/campaigns/1/friend/1',dict(confirm_friend='yes')).status_code==409
    assert not connector.message_action.called
    response=post(client,'/campaigns/1/friend/1',dict(confirm_friend='yes',action_payload_id=str(first)))
    assert response.status_code==200 and connector.message_action.call_count==1
    edit(client,friend_message='Another invitation')
    post(client,'/campaigns/1/friend/1',dict(confirm_friend='yes',action_payload_id=str(first)))
    assert connector.message_action.call_count==1
    assert connector.message_action.call_args.kwargs['message']=='Lời mời mới'


def test_new_sender_requires_new_identity_and_completed_step_keeps_original_sender(app):
    client,connector=setup(app);all_actions(client,interval=0)
    tick(app)  # Lookup only; send a friend request manually before the message.
    post(client,'/campaigns/1/schedule',dict(schedule_present='yes'))
    post(client,'/campaigns/1/friend/1',dict(confirm_friend='yes'))
    post(client,'/accounts',dict(name='New sender'))
    edit(client,account_id='2',rename_enabled='no')
    initial=payload_id(app,'send')
    assert post(client,'/campaigns/1/send/1',dict(confirm_send='yes',action_payload_id=str(initial))).status_code==409
    def action(owner,account,kind,**data):
        if kind=='resolve':assert account==2;return dict(state='resolved',uid='998877',name='New profile')
        assert kind=='send' and account==2 and data['uid']=='998877'
        return dict(state='sent',message_id='new-account-ack')
    connector.message_action.side_effect=action;connector.message_action.reset_mock()
    post(client,'/campaigns/1/pending/1/send/resolve')
    ready=payload_id(app,'send');assert ready!=initial
    assert post(client,'/campaigns/1/send/1',dict(confirm_send='yes',action_payload_id=str(initial))).status_code==409
    post(client,'/campaigns/1/send/1',dict(confirm_send='yes',action_payload_id=str(ready)))
    assert [c.args[2] for c in connector.message_action.call_args_list]==['resolve','send']
    assert query(app,'SELECT account_id,friend_state,state FROM message_sends')==[(1,'friend_requested','sent')]
    assert 'New sender' in client.get('/campaigns/1/report').text
    assert 'New sender' in client.get('/campaigns/1/report?format=csv').data.decode('utf-8-sig')
    results=client.get('/campaigns?selected=1&detail_tab=results').text
    assert 'New sender' in results and 'Zalo của tôi' in results


def legacy_cancel(app,send_id=1):
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE message_sends SET state='not_requested',continue_after_edit=0,schedule_turn_finished=1,schedule_completed_at=CURRENT_TIMESTAMP WHERE id=?",(send_id,))
        db.execute('INSERT INTO campaign_events(campaign_id,kind,detail) VALUES (1,?,?)',('edit_started_recipient',f'Giữ kết quả bản gửi #{send_id} đã bắt đầu; bỏ các bước chưa thực hiện sau khi sửa chiến dịch. Không chạy lại data này.'))


def restart(app,connector):
    updated=create_app(dict(TESTING=True,DATABASE=app.config['DATABASE'],SECRET_KEY='test-only',ZALO_QR_ENABLED=True))
    updated.extensions['zalo_connector'].status=connector.status
    updated.extensions['zalo_connector'].message_action=connector.message_action
    return updated


def test_upgrade_restores_only_steps_canceled_by_previous_bug_once_without_sending_during_update(app):
    client,connector=setup(app);all_actions(client,interval=0)
    tick(app);post(client,'/campaigns/1/schedule',dict(schedule_present='yes'));post(client,'/campaigns/1/friend/1',dict(confirm_friend='yes'));configure(client)
    assert query(app,'SELECT friend_state FROM message_sends')==[('friend_requested',)]
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE campaigns SET message='Thông báo đã sửa',message_html='',rename_enabled=0 WHERE id=1")
    legacy_cancel(app)
    before=query(app,'SELECT * FROM campaign_attempts');calls=connector.message_action.call_count
    updated=restart(app,connector)
    assert connector.message_action.call_count==calls
    assert query(app,'SELECT state,friend_state FROM message_sends')==[('prepared','friend_requested')]
    assert query(app,'SELECT * FROM campaign_attempts')==before
    versions=query(app,'SELECT count(*) FROM campaign_action_payloads')
    updated=restart(updated,connector);assert query(app,'SELECT count(*) FROM campaign_action_payloads')==versions
    tick(updated)
    assert connector.message_action.call_args.kwargs['message']=='Thông báo đã sửa'
    assert query(app,"SELECT count(*) FROM campaign_attempts WHERE action='friend'")==[(1,)]
    assert query(app,"SELECT count(*) FROM campaign_events WHERE kind='pending_repair'")==[(1,)]


def test_explicitly_disabled_or_attempted_steps_are_not_restored(app):
    client,connector=setup(app);all_actions(client,interval=0);tick(app);tick(app)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE campaigns SET send_friend=0,rename_enabled=0 WHERE id=1")
        db.execute("UPDATE message_sends SET friend_state='not_requested',alias_state='not_requested' WHERE id=1")
        db.execute('INSERT INTO campaign_events(campaign_id,kind,detail) VALUES (1,?,?)',('edit_started_recipient','Giữ kết quả bản gửi #1 đã bắt đầu; bỏ các bước chưa thực hiện sau khi sửa chiến dịch. Không chạy lại data này.'))
    before=query(app,'SELECT * FROM campaign_attempts')
    updated=restart(app,connector);tick(updated)
    assert query(app,'SELECT state,friend_state,alias_state FROM message_sends')==[('sent','not_requested','not_requested')]
    assert query(app,'SELECT * FROM campaign_attempts')==before


@pytest.mark.parametrize('state',['failed','unknown'])
def test_repaired_other_step_continues_without_retrying_failed_or_uncertain_send(app,state):
    client,connector=setup(app);all_actions(client,interval=0);tick(app)
    post(client,'/campaigns/1/schedule',dict(schedule_present='yes'))
    connector.message_action.side_effect=None;connector.message_action.return_value=dict(state=state)
    post(client,'/campaigns/1/send/1',dict(confirm_send='yes'))
    configure(client)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE campaigns SET friend_message='Chờ kết bạn mới',rename_enabled=0 WHERE id=1")
        db.execute("UPDATE message_sends SET friend_state='not_requested',alias_state='not_requested' WHERE id=1")
        db.execute('INSERT INTO campaign_events(campaign_id,kind,detail) VALUES (1,?,?)',('edit_started_recipient','Giữ kết quả bản gửi #1 đã bắt đầu; bỏ các bước chưa thực hiện sau khi sửa chiến dịch. Không chạy lại data này.'))
    before=query(app,"SELECT * FROM campaign_attempts WHERE action='send'")
    updated=restart(app,connector)
    connector.message_action.reset_mock();connector.message_action.return_value=dict(state='friend_requested')
    tick(updated);tick(updated)
    assert [c.args[2] for c in connector.message_action.call_args_list]==['friend']
    assert connector.message_action.call_args.kwargs['message']=='Chờ kết bạn mới'
    assert query(app,"SELECT * FROM campaign_attempts WHERE action='send'")==before
    assert query(app,'SELECT state,friend_state FROM message_sends')==[(state,'friend_requested')]


def test_resumed_step_after_uncertain_action_still_rests_before_next_recipient(app):
    from datetime import timedelta
    client,connector=setup(app);all_actions(client,interval=120);tick(app)
    post(client,'/campaigns/1/schedule',dict(schedule_present='yes'))
    connector.message_action.side_effect=None;connector.message_action.return_value=dict(state='unknown')
    post(client,'/campaigns/1/send/1',dict(confirm_send='yes'))
    # The uncertain send remains unknown; edit only prepares the unattempted friend step.
    edit(client,rename_enabled='no');add_contact(client);configure(client)
    connector.message_action.reset_mock();connector.message_action.return_value=dict(state='friend_requested')
    clock=moment();tick(app,clock)
    assert [c.args[2] for c in connector.message_action.call_args_list]==['friend']
    assert query(app,'SELECT schedule_wait_until FROM campaigns')[0][0]
    tick(app,clock+timedelta(seconds=119));assert connector.message_action.call_count==1
    assert query(app,'SELECT state FROM message_sends WHERE id=1')==[('unknown',)]
