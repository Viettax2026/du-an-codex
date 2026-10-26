import json
import sqlite3
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from flask import g
from test_workflow import app,post,register,token
from test_data_scans import setup_scan,start,query


def setup_groups(app,**fields):
    client,connector=setup_scan(app);start(client,'groups')
    result=post(client,'/group-campaigns/new',{'name':'Groups','message':'Chào {{name}}','account_id':'1','group_scan_row_ids':'[1,2]',
        'limits_present':'yes','limits_day_mode':'calendar','interval_seconds':'0','message_limit':'10','message_hour_limit':'10',**fields})
    assert result.status_code==200,result.text[:1000]
    assert query(app,"SELECT campaign_type FROM campaigns")==[('zalo_group',)]
    connector.message_action=Mock(return_value={'state':'sent','message_id':'group-ack'})
    return client,connector


def test_group_campaign_creation_is_read_only_and_manual_send_is_confirmed_immutable_and_idempotent(app):
    client,connector=setup_groups(app)
    assert not connector.message_action.called
    assert query(app,'SELECT count(*) FROM contacts')==[(0,)]
    assert query(app,'SELECT count(*) FROM group_message_sends')==[(0,)]
    response=post(client,'/group-campaigns/1/prepare/1')
    assert 'Chào Group A' in response.text
    assert not connector.message_action.called
    assert client.post('/group-campaigns/1/send/1',data={'csrf':token(client)}).status_code==400
    post(client,'/group-campaigns/1/send/1',{'confirm_send':'yes'})
    assert connector.message_action.call_count==1
    assert connector.message_action.call_args.kwargs==dict(uid='900',message='Chào Group A',thread_type=1)
    post(client,'/group-campaigns/1/send/1',{'confirm_send':'yes'})
    assert connector.message_action.call_count==1
    response=post(client,'/group-campaigns/1/edit',{'name':'Changed','message':'Changed','account_id':'1','group_scan_row_ids':'[1,2]'})
    assert 'Chiến dịch đã có lượt gửi' in response.text
    assert query(app,'SELECT message,state,message_id FROM group_message_sends')==[('Chào Group A','sent','group-ack')]


def test_group_campaign_account_scope_csrf_and_phone_data_cannot_be_group_targets(app):
    client,connector=setup_groups(app)
    other=app.test_client();register(other,'other')
    for path in ('/group-campaigns/1','/group-campaigns/1/edit','/group-campaigns/1/duplicate'):
        assert other.get(path).status_code==404
    assert post(other,'/group-campaigns/1/prepare/1').status_code==404
    assert client.post('/group-campaigns/1/prepare/1').status_code==400
    start(client,'friends')
    response=post(client,'/group-campaigns/new',{'name':'Bad','message':'Hi','account_id':'1','group_scan_row_ids':'[3]'})
    assert 'Group không thuộc tài khoản gửi' in response.text
    assert query(app,'SELECT count(*) FROM campaigns')==[(1,)]
    assert not connector.message_action.called
    post(client,'/accounts',{'name':'Second account'})
    response=post(client,'/group-campaigns/new',{'name':'Wrong account','message':'Hi','account_id':'2','group_scan_row_ids':'[1]'})
    assert 'Group không thuộc tài khoản gửi' in response.text
    assert query(app,'SELECT count(*) FROM campaigns')==[(1,)]


def test_group_campaign_status_tabs_and_legacy_phone_actions_remain_separate(app):
    client,connector=setup_groups(app)
    for tab in ('info','accounts','data','preview','results','history'):
        response=client.get('/campaigns?selected=1&detail_tab='+tab)
        assert response.status_code==200 and 'Groups' in response.text
        assert 'Zalo · Gửi tin nhắn đến group' in response.text
    assert '0/2' in client.get('/campaigns').text
    assert client.get('/campaigns/1').status_code==302
    assert client.get('/campaigns/1/edit').location.endswith('/group-campaigns/1/edit')
    assert post(client,'/campaigns/1/prepare-send',{'account_id':'1','contact_id':'1'}).status_code==400
    post(client,'/group-campaigns/1/prepare/1')
    post(client,'/group-campaigns/1/send/1',{'confirm_send':'yes'})
    post(client,'/group-campaigns/1/prepare/2')
    post(client,'/group-campaigns/1/send/2',{'confirm_send':'yes'})
    assert '2/2' in client.get('/campaigns').text and 'Đã xử lý' in client.get('/campaigns').text
    assert client.get('/campaigns?selected=1&detail_tab=results').text.count('Gửi tin đến group')==2


def configure_schedule(app,**values):
    settings=dict(schedule_enabled=1,schedule_kind='daily',schedule_date='2026-10-26',schedule_time='08:00',
        schedule_stop_enabled=1,schedule_stop='17:00',schedule_continue=1)
    settings.update(values)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('UPDATE campaigns SET '+','.join(key+'=?' for key in settings)+' WHERE id=1',list(settings.values()))


def tick(app,now):
    with app.app_context():app.extensions['campaign_scheduler'].tick(now=lambda:now)


def test_group_scheduler_obeys_window_rest_sunday_and_skips_failed_without_stopping(app):
    client,connector=setup_groups(app,interval_seconds='120')
    configure_schedule(app,schedule_skip_sunday=1)
    tz=ZoneInfo('Asia/Ho_Chi_Minh');now=datetime(2026,10,26,8,0,tzinfo=tz)
    connector.message_action.side_effect=[{'state':'failed','error_reason':'recipient_blocked'}, {'state':'sent','message_id':'ack'}]
    tick(app,now-timedelta(minutes=1));assert not connector.message_action.called
    tick(app,now);assert connector.message_action.call_count==1
    assert query(app,'SELECT state FROM group_message_sends')==[('failed',)]
    tick(app,now+timedelta(seconds=119));assert connector.message_action.call_count==1
    tick(app,now+timedelta(seconds=120));assert connector.message_action.call_count==2
    assert query(app,'SELECT state FROM group_message_sends ORDER BY id')==[('failed',),('sent',)]
    tick(app,now+timedelta(minutes=5));assert connector.message_action.call_count==2
    assert query(app,'SELECT schedule_error FROM campaigns')==[('',)]
    assert 'Đã xử lý' in client.get('/campaigns').text


def test_group_scheduler_limits_pause_deletion_and_unknown_are_durable(app):
    client,connector=setup_groups(app,message_limit='1');configure_schedule(app)
    now=datetime(2026,10,26,10,tzinfo=ZoneInfo('Asia/Ho_Chi_Minh'))
    connector.message_action.return_value={'state':'unknown','token':'PRIVATE'}
    tick(app,now);tick(app,now+timedelta(minutes=1))
    assert connector.message_action.call_count==1
    assert query(app,'SELECT state FROM group_message_sends ORDER BY id')==[('unknown',),('prepared',)]
    assert query(app,'SELECT schedule_error FROM campaigns')==[('',)]
    assert 'PRIVATE' not in client.get('/group-campaigns/1').text
    post(client,'/campaigns/1/pause',{'paused':'1'})
    tick(app,now+timedelta(days=1));assert connector.message_action.call_count==1
    post(client,'/campaigns/1/pause',{'paused':'0'})
    connector.message_action.return_value={'state':'sent','message_id':'next-day'}
    tick(app,now+timedelta(days=1));assert connector.message_action.call_count==2
    post(client,'/accounts/1/delete',{'confirm_delete':'yes'})
    assert query(app,'SELECT paused,schedule_enabled,account_id FROM campaigns')==[(1,0,None)]
    assert client.get('/group-campaigns/1').status_code==200


def test_interrupted_group_claim_is_not_resent_and_recovers_after_grace(app):
    client,connector=setup_groups(app);configure_schedule(app)
    post(client,'/group-campaigns/1/prepare/1')
    now=datetime(2026,10,26,10,tzinfo=ZoneInfo('Asia/Ho_Chi_Minh'))
    stamp=now.astimezone(timezone.utc).replace(tzinfo=None).isoformat(' ')
    with sqlite3.connect(app.config['DATABASE']) as db:db.execute("UPDATE group_message_sends SET state='sending',claimed_at=? WHERE id=1",(stamp,))
    tick(app,now+timedelta(seconds=89));assert not connector.message_action.called
    tick(app,now+timedelta(seconds=90));assert not connector.message_action.called
    tick(app,now+timedelta(seconds=91));assert connector.message_action.call_count==1
    assert connector.message_action.call_args.kwargs['uid']=='901'
    assert query(app,'SELECT state FROM group_message_sends ORDER BY id')==[('unknown',),('sent',)]


def test_group_styles_and_media_snapshot_remain_frozen_after_campaign_changes(app,tmp_path):
    from PIL import Image
    import io
    client,connector=setup_groups(app)
    app.extensions['campaign_manager'].media_root=tmp_path/'media'
    image=io.BytesIO();Image.new('RGB',(2,2)).save(image,format='PNG');image.seek(0)
    post(client,'/group-campaigns/1/edit',{'name':'Styled','message':'Hello','rich_message':'yes','message_html':'<p><b>Hello</b></p>',
        'account_id':'1','group_scan_row_ids':'[1,2]','media':(image,'a.png'),'media_present':'yes','media_mode':'send'})
    post(client,'/group-campaigns/1/prepare/1')
    before=query(app,'SELECT message,message_styles,media_id FROM group_message_sends')
    assert before[0][2] is not None and '"b"' in before[0][1]
    post(client,'/group-campaigns/1/send/1',{'confirm_send':'yes'})
    kwargs=connector.message_action.call_args.kwargs
    assert kwargs['thread_type']==1 and kwargs['styles'][0]['st']=='b' and kwargs['attachment']['filename']=='a.png'
    assert query(app,'SELECT message,message_styles,media_id FROM group_message_sends')==before


def test_prepared_group_preview_cannot_be_replaced_under_an_old_confirmation_tab(app):
    client,connector=setup_groups(app)
    post(client,'/group-campaigns/1/prepare/1')
    original=query(app,'SELECT id,group_id,message,account_id FROM group_message_sends')
    response=post(client,'/group-campaigns/1/edit',{'name':'Replacement','message':'Changed without review',
        'account_id':'1','group_scan_row_ids':'[2]'})
    assert 'Chiến dịch đã có bản xem trước' in response.text
    assert query(app,'SELECT id,group_id,message,account_id FROM group_message_sends')==original
    post(client,'/group-campaigns/1/send/1',{'confirm_send':'yes'})
    assert connector.message_action.call_args.kwargs['message']=='Chào Group A'
    assert connector.message_action.call_args.kwargs['uid']=='900'
