"""Editing a running campaign resumes untouched recipients without real sends."""
import json
import sqlite3
from unittest.mock import Mock

import pytest

from test_workflow import app,post,register,token
from test_send import setup_send,prepare
from test_message_composer import query,rich,png
from test_campaign_schedule import setup,tick,moment,fields
from test_campaign_sequence import all_actions
from test_lookup_skip import add_contact
from test_group_campaign_options import setup_options


def test_edit_after_send_preserves_history_and_previews_use_new_account_content_and_ids(app):
    client,connector=setup_send(app);add_contact(client)
    post(client,'/accounts',dict(name='Second'))
    prepare(client);connector.message_action.return_value=dict(state='sent',message_id='old-ack')
    post(client,'/campaigns/1/send/1',dict(confirm_send='yes'))
    connector.message_action.return_value=dict(state='resolved',uid='654321',name='Second customer')
    post(client,'/campaigns/1/prepare-send',dict(contact_id='2',account_id='1'))
    old=query(app,'SELECT * FROM message_sends WHERE id=1');attempts=query(app,'SELECT * FROM campaign_attempts')
    response=post(client,'/campaigns/1/edit',rich('<span data-style="c_db342e">Mới {{name}}</span>',name='Edited',tag='VIP',account_id='2'))
    assert 'Đã lưu thay đổi' in response.text
    assert query(app,'SELECT * FROM message_sends WHERE id=1')==old
    assert query(app,'SELECT * FROM campaign_attempts')==attempts
    assert client.post('/campaigns/1/send/2',data=dict(csrf=token(client),confirm_send='yes')).status_code==404
    history=client.get('/campaigns/1/preview-history');assert 'Xin chào' in history.text and 'không thể xác nhận' in history.text
    post(client,'/campaigns/1/prepare-send',dict(contact_id='2',account_id='2'))
    assert query(app,'SELECT id,account_id,message FROM message_sends WHERE contact_id=2')==[(3,2,'Mới Next customer')]
    connector.message_action.reset_mock();connector.message_action.return_value=dict(state='sent',message_id='new-ack')
    post(client,'/campaigns/1/send/2',dict(confirm_send='yes'));assert not connector.message_action.called
    post(client,'/campaigns/1/send/3',dict(confirm_send='yes'))
    assert connector.message_action.call_args.args[1]==2
    assert connector.message_action.call_args.kwargs['styles'][0]['st']=='c_db342e'
    post(client,'/campaigns/1/send/1',dict(confirm_send='yes'));assert connector.message_action.call_count==1


def test_scheduler_replaces_unused_preview_and_resumes_only_remaining_data_after_edit(app):
    client,connector=setup(app);add_contact(client);add_contact(client,'0923456789')
    post(client,'/campaigns/1/limits',dict(interval_seconds='0',message_limit='100',message_hour_limit='100'))
    tick(app);tick(app);tick(app)  # First is sent, second has a lookup/preview only.
    assert query(app,'SELECT state FROM message_sends ORDER BY id')==[('sent',),('prepared',)]
    old=query(app,'SELECT * FROM message_sends WHERE id=1')
    before=query(app,'SELECT next_message_variant FROM campaigns')[0][0]
    response=post(client,'/campaigns/1/edit',dict(fields(),name='After edit',message='Thông báo mới {{name}}',tag='VIP'))
    assert 'Đã lưu thay đổi' in response.text
    assert query(app,'SELECT next_message_variant FROM campaigns')==[(before,)]
    for _ in range(8):tick(app)
    assert query(app,'SELECT * FROM message_sends WHERE id=1')==old
    assert query(app,'SELECT contact_id,message,state FROM message_sends ORDER BY id')==[(1,'Xin chào Lan','sent'),(2,'Thông báo mới Next customer','sent'),(3,'Thông báo mới Next customer','sent')]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(3,)]
    assert query(app,'SELECT count(*) FROM campaign_preview_archive')==[(1,)]
    assert query(app,'SELECT schedule_error FROM campaigns')==[('',)]


def test_edit_after_partially_processed_recipient_never_restarts_that_recipient(app):
    client,connector=setup(app);add_contact(client);all_actions(client,interval=0)
    tick(app);tick(app)  # A message sent; friend/alias have not started.
    assert query(app,'SELECT state,friend_state,alias_state FROM message_sends')==[('sent','prepared','prepared')]
    response=post(client,'/campaigns/1/edit',dict(name='Continue',message='Mới',tag='VIP',account_id='1',options_present='yes',send_message='yes'))
    assert response.status_code==200
    assert query(app,'SELECT state,friend_state,alias_state FROM message_sends')==[('sent','not_requested','not_requested')]
    for _ in range(6):tick(app)
    assert [call.args[2] for call in connector.message_action.call_args_list]==['resolve','send','resolve','send']
    assert query(app,'SELECT message FROM message_sends WHERE contact_id=2')==[('Mới',)]
    assert 'đã tắt trong cấu hình' in client.get('/campaigns/1/history').text


@pytest.mark.parametrize('state',['failed','unknown'])
def test_edit_never_retries_failed_or_uncertain_data(app,state):
    client,connector=setup_send(app);add_contact(client);prepare(client)
    connector.message_action.return_value=dict(state=state)
    post(client,'/campaigns/1/send/1',dict(confirm_send='yes'))
    post(client,'/campaigns/1/edit',dict(name='Updated',message='Mới',tag='VIP'))
    connector.message_action.reset_mock()
    post(client,'/campaigns/1/send/1',dict(confirm_send='yes'));prepare(client)
    assert not connector.message_action.called
    assert query(app,'SELECT state FROM message_sends')==[(state,)]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(1,)]


def test_edit_during_inflight_send_preserves_its_claim_and_next_recipient_uses_new_content(app):
    client,connector=setup_send(app);add_contact(client);prepare(client)
    def sending(owner,account,action,**data):
        assert action=='send' and data['message']=='Xin chào Lan'
        assert query(app,'SELECT state FROM message_sends')==[('sending',)]
        result=post(client,'/campaigns/1/edit',dict(name='In flight edit',message='Mới',tag='VIP'))
        assert result.status_code==200
        return dict(state='sent',message_id='accepted-old')
    connector.message_action.side_effect=sending
    post(client,'/campaigns/1/send/1',dict(confirm_send='yes'))
    assert query(app,'SELECT state,message,message_id FROM message_sends')==[('sent','Xin chào Lan','accepted-old')]
    connector.message_action.side_effect=None;connector.message_action.return_value=dict(state='resolved',uid='777',name='Next')
    post(client,'/campaigns/1/prepare-send',dict(contact_id='2',account_id='1'))
    assert query(app,'SELECT message FROM message_sends WHERE contact_id=2')==[('Mới',)]


def test_edit_during_lookup_discards_stale_lookup_without_creating_preview(app):
    client,connector=setup_send(app)
    def lookup(*args,**kwargs):
        post(client,'/campaigns/1/edit',dict(name='New',message='Mới',tag='VIP'))
        return dict(state='resolved',uid='123',name='Lan')
    connector.message_action.side_effect=lookup
    assert 'Chiến dịch vừa được sửa' in prepare(client).text
    assert query(app,'SELECT count(*) FROM message_sends')==[(0,)]


def test_invalid_edit_rolls_back_and_archived_media_stays_private_and_retained(app):
    client,connector=setup_send(app)
    post(client,'/campaigns/1/content',rich('<b>Original</b>',media_present='yes',media_mode='send',media=png()))
    prepare(client);old=query(app,'SELECT * FROM message_sends')
    response=post(client,'/campaigns/1/edit',dict(name='Bad',message='Bad',tag='VIP',limits_present='yes',message_limit='-1'))
    assert 'Đã lưu thay đổi' not in response.text
    assert query(app,'SELECT * FROM message_sends')==old and query(app,'SELECT count(*) FROM campaign_preview_archive')==[(0,)]
    post(client,'/campaigns/1/edit',dict(name='Updated',message='Next',tag='VIP',media_present='yes',media_mode='none'))
    media_id=query(app,'SELECT media_id FROM campaign_preview_archive')[0][0]
    assert post(client,f'/media/{media_id}/delete',dict(confirm_delete='yes')).status_code==200
    assert query(app,'SELECT count(*) FROM campaign_media WHERE id=?',(media_id,))==[(1,)]
    assert client.get(f'/media/{media_id}').status_code==200
    other=app.test_client();register(other,'other')
    assert other.get('/campaigns/1/preview-history').status_code==404
    assert other.post('/campaigns/1/edit',data=dict(csrf=token(other),name='Bad',message='Bad')).status_code==404
    assert client.post('/campaigns/1/edit',data=dict(name='Bad',message='Bad')).status_code==400


def test_group_edit_preserves_sent_uid_and_invalidates_old_batch_before_new_share(app):
    client,connector=setup_options(app,3)
    post(client,'/group-campaigns/1/prepare/1');post(client,'/group-campaigns/1/send/1',dict(confirm_send='yes'))
    old=query(app,'SELECT * FROM group_message_sends WHERE target_id=1')
    post(client,'/group-campaigns/1/prepare-share')
    assert query(app,'SELECT count(*) FROM group_message_sends')==[(3,)]
    response=post(client,'/group-campaigns/1/edit',dict(name='Group updated',message='Mới',account_id='1',group_scan_row_ids='[1,2,3]',group_options_present='yes',group_share='yes',group_tags_enabled='yes',group_tags='Updated',interval_seconds='0'))
    assert response.status_code==200
    assert query(app,'SELECT * FROM group_message_sends WHERE target_id=1')==old
    assert query(app,'SELECT state FROM group_message_batches WHERE id=1')==[('superseded',)]
    connector.forward_group_messages.reset_mock()
    post(client,'/group-campaigns/1/share-preview/1',dict(confirm_send='yes'));assert not connector.forward_group_messages.called
    post(client,'/group-campaigns/1/prepare-share')
    assert query(app,'SELECT id FROM group_message_sends WHERE target_id<>1')==[(4,),(5,)]
    post(client,'/group-campaigns/1/share-preview/2',dict(confirm_send='yes'))
    assert connector.forward_group_messages.call_args.args[2]==['901','902']
    assert connector.forward_group_messages.call_args.args[3]=='Mới'
    assert query(app,'SELECT group_id,tag FROM zalo_group_tags ORDER BY group_id')==[('901','Updated'),('902','Updated')]
    assert query(app,'SELECT * FROM group_message_sends WHERE target_id=1')==old


def test_edit_keeps_pause_rest_and_used_limits_while_clearing_corrected_error(app):
    client,connector=setup(app);add_contact(client)
    post(client,'/campaigns/1/limits',dict(interval_seconds='120',message_limit='10',message_hour_limit='10'))
    tick(app);tick(app)
    with sqlite3.connect(app.config['DATABASE']) as db:db.execute("UPDATE campaigns SET paused=1,schedule_error='Đăng nhập cũ đã hết hạn' WHERE id=1")
    old=query(app,'SELECT schedule_wait_until,schedule_carry,schedule_first_day FROM campaigns')
    attempts=query(app,'SELECT * FROM campaign_attempts')
    post(client,'/campaigns/1/edit',dict(name='Fixed',message='New',tag='VIP',account_id='1'))
    assert query(app,'SELECT schedule_wait_until,schedule_carry,schedule_first_day FROM campaigns')==old
    assert query(app,'SELECT * FROM campaign_attempts')==attempts
    assert query(app,'SELECT paused,schedule_enabled,schedule_error FROM campaigns')==[(1,1,'')]
    connector.message_action.reset_mock();tick(app);assert not connector.message_action.called


def test_stale_scheduler_tick_cannot_block_new_group_configuration(app):
    client,connector=setup_options(app,2,group_send_mode='normal')
    from test_group_campaigns import configure_schedule
    configure_schedule(app);clock=moment('2026-10-26T10:00:00')
    runner=app.extensions['group_campaign_runner'];original=runner.dispatch
    def edit_before_claim(campaign_id,send_id,**kwargs):
        response=post(client,'/group-campaigns/1/edit',dict(name='Edited during tick',message='New',account_id='1',group_scan_row_ids='[1,2]',interval_seconds='0'))
        assert response.status_code==200
        return original(campaign_id,send_id,**kwargs)
    runner.dispatch=edit_before_claim
    tick(app,clock);assert not connector.message_action.called
    assert query(app,'SELECT schedule_error FROM campaigns')==[('',)]
    runner.dispatch=original;tick(app,clock);tick(app,clock)
    assert connector.message_action.call_count==2
    assert all(call.kwargs['message']=='New' for call in connector.message_action.call_args_list)


@pytest.mark.parametrize('mutation',["paused=1","deleted_at=CURRENT_TIMESTAMP"])
def test_group_scheduler_does_not_block_or_raise_when_stopped_before_dispatch(app,mutation):
    client,connector=setup_options(app,2,group_send_mode='normal')
    from test_group_campaigns import configure_schedule
    configure_schedule(app);runner=app.extensions['group_campaign_runner'];original=runner.dispatch
    def stop_before_claim(campaign_id,send_id,**kwargs):
        with sqlite3.connect(app.config['DATABASE']) as db:db.execute(f'UPDATE campaigns SET {mutation},schedule_revision=schedule_revision+1 WHERE id=1')
        return original(campaign_id,send_id,**kwargs)
    runner.dispatch=stop_before_claim
    tick(app,moment('2026-10-26T10:00:00'))
    assert not connector.message_action.called
    assert query(app,'SELECT schedule_error FROM campaigns')==[('',)]
