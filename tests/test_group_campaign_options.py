import json
import sqlite3
from datetime import datetime,timedelta
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from test_workflow import app,post,register,token
from test_data_scans import setup_scan,start,query,scan_page
from test_group_campaigns import configure_schedule,tick


def setup_options(app,count=2,**changes):
    client,connector=setup_scan(app)
    connector.scan_action.side_effect=None
    connector.scan_action.return_value=scan_page('groups',rows=[dict(uid=str(900+i),name='Group '+str(i+1),kind='group',member_count=10) for i in range(count)])
    start(client,'groups')
    fields=dict(name='Group options',message='Thông báo chung',account_id='1',group_scan_row_ids=json.dumps(list(range(1,count+1))),
        interval_seconds='0',limits_present='yes',message_limit='100',message_hour_limit='100',message_window_minutes='65',group_send_mode='share')
    fields.update(changes)
    result=post(client,'/group-campaigns/new',fields)
    assert result.status_code==200,result.text[:1000]
    assert query(app,'SELECT count(*) FROM campaigns')==[(1,)]
    connector.forward_group_messages=Mock(side_effect=lambda owner,account,ids,message:[dict(uid=uid,state='sent',message_id=','.join(str(1000+i) for i in range(len(ids)))) for uid in ids])
    connector.message_action=Mock(return_value=dict(state='sent',message_id='ack'))
    return client,connector


def test_draft_can_be_incomplete_and_publishing_preserves_targets_without_sending(app):
    client,connector=setup_scan(app)
    response=post(client,'/group-campaigns/new',dict(save_draft='yes'))
    assert response.status_code==200
    assert query(app,'SELECT group_is_draft,paused,schedule_enabled,account_id FROM campaigns')==[(1,1,0,None)]
    assert 'Bản nháp' in client.get('/campaigns').text
    start(client,'groups')
    post(client,'/group-campaigns/1/edit',dict(name='Ready',message='Hi',account_id='1',group_scan_row_ids='[1,2]'))
    assert query(app,'SELECT group_is_draft,paused FROM campaigns')==[(0,0)]
    assert not connector.message_action.called


def test_share_validation_rejects_personalization_and_tags_require_names(app):
    client,_=setup_scan(app);start(client,'groups')
    base=dict(name='Bad',message='Hi {{name}}',account_id='1',group_scan_row_ids='[1,2]',group_options_present='yes',group_share='yes')
    assert 'không áp dụng cá nhân hóa' in post(client,'/group-campaigns/new',base).text
    base.update(message='Thông báo',group_tags_enabled='yes',group_tags='')
    assert 'Nhập tag nội bộ' in post(client,'/group-campaigns/new',base).text
    assert query(app,'SELECT count(*) FROM campaigns')==[(0,)]


def test_share_batches_are_capped_at_50_rest_once_count_every_group_and_apply_tags(app):
    client,connector=setup_options(app,53,interval_seconds='120',group_options_present='yes',group_share='yes',group_tags_enabled='yes',group_tags='Đã gửi, Khách hàng')
    configure_schedule(app);now=datetime(2026,10,26,10,tzinfo=ZoneInfo('Asia/Ho_Chi_Minh'))
    tick(app,now)
    assert connector.forward_group_messages.call_count==1 and len(connector.forward_group_messages.call_args.args[2])==50
    assert query(app,"SELECT count(*) FROM group_message_sends WHERE state='sent'")==[(50,)]
    assert query(app,'SELECT count(*) FROM zalo_group_tags')==[(100,)]
    tick(app,now+timedelta(seconds=119));assert connector.forward_group_messages.call_count==1
    tick(app,now+timedelta(seconds=120));assert connector.forward_group_messages.call_count==2
    assert len(connector.forward_group_messages.call_args.args[2])==3
    tick(app,now+timedelta(seconds=240));assert connector.forward_group_messages.call_count==2
    assert not connector.message_action.called
    assert query(app,"SELECT count(*) FROM group_message_sends WHERE claimed_at IS NOT NULL")==[(53,)]
    assert query(app,'SELECT count(*) FROM zalo_group_tags')==[(106,)]


def test_batch_quota_clamps_the_size_without_permanently_blocking_schedule(app):
    _,connector=setup_options(app,8,message_hour_limit='3');configure_schedule(app)
    now=datetime(2026,10,26,10,tzinfo=ZoneInfo('Asia/Ho_Chi_Minh'))
    tick(app,now);assert len(connector.forward_group_messages.call_args.args[2])==3
    tick(app,now+timedelta(seconds=1));assert connector.forward_group_messages.call_count==1
    assert query(app,'SELECT schedule_error FROM campaigns')==[('',)]
    tick(app,now+timedelta(minutes=66));assert connector.forward_group_messages.call_count==2
    assert len(connector.forward_group_messages.call_args.args[2])==3


def test_manual_batch_needs_a_frozen_preview_and_confirmation_and_never_repeats(app):
    client,connector=setup_options(app)
    response=post(client,'/group-campaigns/1/prepare-share')
    assert 'Xem trước lô chia sẻ' in response.text and 'Thông báo chung' in response.text
    assert not connector.forward_group_messages.called
    assert client.post('/group-campaigns/1/share-preview/1',data=dict(csrf=token(client))).status_code==400
    post(client,'/group-campaigns/1/share-preview/1',dict(confirm_send='yes'))
    assert connector.forward_group_messages.call_count==1
    post(client,'/group-campaigns/1/share-preview/1',dict(confirm_send='yes'))
    assert connector.forward_group_messages.call_count==1
    assert query(app,'SELECT state FROM group_message_sends')==[('sent',),('sent',)]


def test_unknown_batch_is_skipped_and_tagging_never_marks_uncertain_groups(app):
    _,connector=setup_options(app,group_options_present='yes',group_share='yes',group_tags_enabled='yes',group_tags='Sent')
    connector.forward_group_messages.side_effect=lambda owner,account,ids,message:[dict(uid=uid,state='unknown') for uid in ids]
    configure_schedule(app);now=datetime(2026,10,26,10,tzinfo=ZoneInfo('Asia/Ho_Chi_Minh'))
    tick(app,now);tick(app,now+timedelta(minutes=1))
    assert connector.forward_group_messages.call_count==1
    assert query(app,'SELECT state FROM group_message_sends')==[('unknown',),('unknown',)]
    assert query(app,'SELECT count(*) FROM zalo_group_tags')==[(0,)]


def test_dynamic_group_source_adds_new_groups_and_collection_deletion_freezes_existing_targets(app):
    client,connector=setup_scan(app);start(client,'groups')
    result=post(client,'/group-data/new',dict(name='Groups',account_id='1',group_scan_row_ids='[1]'));collection=result.json['id']
    result=post(client,'/group-campaigns/new',dict(name='Dynamic',message='Hi',account_id='1',group_data_mode='group',group_data_id=str(collection),limits_present='yes',interval_seconds='0',message_limit='10',message_hour_limit='10'))
    assert result.status_code==200
    connector.message_action=Mock(return_value=dict(state='sent',message_id='ack'))
    configure_schedule(app);now=datetime(2026,10,26,10,tzinfo=ZoneInfo('Asia/Ho_Chi_Minh'))
    tick(app,now);assert connector.message_action.call_count==1
    post(client,f'/group-data/{collection}/add',dict(account_id='1',group_scan_row_ids='[2]'))
    tick(app,now+timedelta(seconds=1));assert connector.message_action.call_count==2
    assert query(app,'SELECT count(*) FROM group_campaign_targets')==[(2,)]
    post(client,f'/group-data/{collection}/delete')
    assert query(app,'SELECT group_data_mode,group_data_id FROM campaigns')==[('direct',None)]
    tick(app,now+timedelta(seconds=2));assert connector.message_action.call_count==2


def test_group_collections_enforce_owner_account_and_csrf_and_reject_phone_rows(app):
    client,_=setup_scan(app);start(client,'groups');start(client,'friends')
    assert post(client,'/group-data/new',dict(name='Bad',account_id='1',group_scan_row_ids='[3]')).status_code==400
    assert query(app,'SELECT count(*) FROM zalo_group_data')==[(0,)]
    post(client,'/group-data/new',dict(name='Good',account_id='1',group_scan_row_ids='[1]'))
    other=app.test_client();register(other,'other')
    assert other.get('/group-data/1/members?account_id=1').status_code==404
    assert post(other,'/group-data/1/delete').status_code==404
    assert post(other,'/group-campaigns/new',dict(name='Bad',message='Hi',account_id='1',group_data_mode='group',group_data_id='1')).status_code==200
    assert client.post('/group-data/1/delete').status_code==400
    assert client.get('/group-data/catalog?account_id=1').json['groups'][0]['total']==1
    assert query(app,'SELECT count(*) FROM campaigns')==[(0,)]


def test_interrupted_batch_recovers_all_claims_together_without_resending(app):
    client,connector=setup_options(app);post(client,'/group-campaigns/1/prepare-share');configure_schedule(app)
    now=datetime(2026,10,26,10,tzinfo=ZoneInfo('Asia/Ho_Chi_Minh'))
    from datetime import timezone
    stamp=now.astimezone(timezone.utc).replace(tzinfo=None).isoformat(' ')
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("INSERT INTO group_message_batches(id,campaign_id,account_id,message) VALUES (2,1,1,'Thông báo chung')")
        db.execute("UPDATE group_message_sends SET state='sending',claimed_at=?,batch_id=2",(stamp,))
        db.execute("UPDATE group_message_batches SET state='confirmed' WHERE id=1")
    tick(app,now+timedelta(seconds=89));assert query(app,"SELECT count(*) FROM group_message_sends WHERE state='sending'")==[(2,)]
    tick(app,now+timedelta(seconds=90));tick(app,now+timedelta(seconds=91))
    assert query(app,'SELECT state FROM group_message_sends')==[('unknown',),('unknown',)]
    assert query(app,'SELECT state FROM group_message_batches WHERE id=2')==[('unknown',)]
    assert not connector.forward_group_messages.called


def test_share_with_formatting_falls_back_to_individual_group_messages(app):
    _,connector=setup_options(app,message='Hello',rich_message='yes',message_html='<p><b>Hello</b></p>')
    configure_schedule(app);now=datetime(2026,10,26,10,tzinfo=ZoneInfo('Asia/Ho_Chi_Minh'))
    tick(app,now)
    assert not connector.forward_group_messages.called and connector.message_action.call_count==1
    assert connector.message_action.call_args.kwargs['styles'][0]['st']=='b'
    assert query(app,'SELECT send_mode FROM group_message_sends')==[('normal',)]


def test_removing_dynamic_group_after_preview_prevents_its_dispatch(app):
    client,connector=setup_scan(app);start(client,'groups')
    group=post(client,'/group-data/new',dict(name='Source',account_id='1',group_scan_row_ids='[1,2]')).json['id']
    post(client,'/group-campaigns/new',dict(name='Dynamic',message='Hi',account_id='1',group_data_mode='group',group_data_id=str(group),interval_seconds='0',limits_present='yes'))
    post(client,'/group-campaigns/1/prepare/1')
    member=client.get(f'/group-data/{group}/members?account_id=1').json['rows'][0]['membership_id']
    post(client,f'/group-data/{group}/remove/{member}')
    connector.message_action=Mock(return_value=dict(state='sent',message_id='ack'))
    post(client,'/group-campaigns/1/send/1',dict(confirm_send='yes'))
    assert not connector.message_action.called
    assert query(app,'SELECT state,claimed_at FROM group_message_sends')==[('skipped',None)]


def test_batch_preview_owner_csrf_and_frozen_tag_configuration(app):
    client,connector=setup_options(app,group_options_present='yes',group_share='yes',group_tags_enabled='yes',group_tags='Original')
    post(client,'/group-campaigns/1/prepare-share')
    other=app.test_client();register(other,'other')
    assert other.get('/group-campaigns/1/share-preview/1').status_code==404
    assert post(other,'/group-campaigns/1/share-preview/1',dict(confirm_send='yes')).status_code==404
    assert client.post('/group-campaigns/1/share-preview/1',data=dict(confirm_send='yes')).status_code==400
    with sqlite3.connect(app.config['DATABASE']) as db:db.execute("UPDATE campaigns SET group_tag_names='[\"Changed\"]' WHERE id=1")
    def accepted(owner,account,ids,message):
        assert query(app,"SELECT count(*) FROM group_message_sends WHERE state='sending'")==[(2,)]
        assert query(app,"SELECT state FROM group_message_batches WHERE id=1")==[('confirmed',)]
        return [dict(uid=uid,state='sent',message_id='100,101') for uid in ids]
    connector.forward_group_messages.side_effect=accepted
    post(client,'/group-campaigns/1/share-preview/1',dict(confirm_send='yes'))
    assert query(app,'SELECT DISTINCT tag FROM zalo_group_tags')==[('Original',)]


def test_draft_is_not_dispatchable_even_if_unpaused_and_schedule_is_enabled(app):
    client,connector=setup_options(app,save_draft='yes')
    with sqlite3.connect(app.config['DATABASE']) as db:db.execute('UPDATE campaigns SET paused=0 WHERE id=1')
    configure_schedule(app);tick(app,datetime(2026,10,26,10,tzinfo=ZoneInfo('Asia/Ho_Chi_Minh')))
    response=post(client,'/group-campaigns/1/prepare/1')
    assert 'Lưu chiến dịch trước' in response.text
    assert query(app,'SELECT count(*) FROM group_message_sends')==[(0,)]
    assert not connector.forward_group_messages.called and not connector.message_action.called


def test_duplicate_keeps_options_and_source_but_starts_with_no_attempts(app):
    client,connector=setup_options(app,group_options_present='yes',group_share='yes',group_tags_enabled='yes',group_tags='Khách hàng')
    source=post(client,'/group-data/new',dict(name='Source',account_id='1',group_scan_row_ids='[1,2]')).json['id']
    post(client,'/group-campaigns/1/edit',dict(name='Dynamic',message='Hi',account_id='1',group_data_mode='group',group_data_id=str(source)))
    post(client,'/group-campaigns/1/duplicate',dict(name='Copy',message='Hi',account_id='1',group_scan_row_ids='[1,2]'))
    assert query(app,'SELECT group_send_mode,group_tag_names,group_data_mode,group_data_id FROM campaigns WHERE id=2')==[('share','["Khách hàng"]','group',source)]
    assert query(app,'SELECT count(*) FROM group_message_sends WHERE campaign_id=2')==[(0,)]
    assert not connector.forward_group_messages.called


def test_deleting_collection_freezes_latest_members_not_removed_snapshot(app):
    client,connector=setup_options(app)
    source=post(client,'/group-data/new',dict(name='Source',account_id='1',group_scan_row_ids='[1,2]')).json['id']
    post(client,'/group-campaigns/1/edit',dict(name='Dynamic',message='Hi',account_id='1',group_data_mode='group',group_data_id=str(source)))
    member=client.get(f'/group-data/{source}/members?account_id=1').json['rows'][0]['membership_id']
    post(client,f'/group-data/{source}/remove/{member}');post(client,f'/group-data/{source}/delete')
    assert query(app,'SELECT group_id,active FROM group_campaign_targets ORDER BY id')==[('900',0),('901',1)]
    assert query(app,'SELECT group_data_mode,group_data_id FROM campaigns')==[('direct',None)]
    assert not connector.forward_group_messages.called


def test_refresh_and_batch_confirmation_exclude_removed_group_without_sending_it(app):
    client,connector=setup_options(app)
    source=post(client,'/group-data/new',dict(name='Source',account_id='1',group_scan_row_ids='[1,2]')).json['id']
    post(client,'/group-campaigns/1/edit',dict(name='Dynamic',message='Hi',account_id='1',group_data_mode='group',group_data_id=str(source)))
    post(client,'/group-campaigns/1/prepare-share')
    members=client.get(f'/group-data/{source}/members?account_id=1').json['rows']
    for row in members:post(client,f'/group-data/{source}/remove/{row["membership_id"]}')
    post(client,'/group-campaigns/1/refresh-source')
    post(client,'/group-campaigns/1/share-preview/1',dict(confirm_send='yes'))
    assert query(app,'SELECT state,claimed_at FROM group_message_sends')==[('skipped',None),('skipped',None)]
    assert query(app,'SELECT state FROM group_message_batches WHERE id=1')==[('confirmed',)]
    assert not connector.forward_group_messages.called
