import fcntl
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from campaign_schedule import TZ, active_window
from test_workflow import app, post, register, token
from test_send import setup_send
from test_message_composer import query, png


def moment(value='2026-10-24T10:00:00'):
    return datetime.fromisoformat(value).replace(tzinfo=TZ)


def fields(**extra):
    return dict(schedule_present='yes',schedule_enabled='yes',schedule_kind='daily',schedule_date='2026-10-24',schedule_time='08:00',
                schedule_stop_enabled='yes',schedule_stop='17:00',schedule_continue='yes',schedule_monthday='24',account_id='1',**extra)


def configure(client,**extra):
    data=fields();data.update(extra)
    return post(client,'/campaigns/1/schedule',data)


def setup(app):
    client,connector=setup_send(app)
    connector.message_action.side_effect=lambda user,account,action,**data: {'state':'resolved','uid':'123456','name':'Lan Zalo'} if action=='resolve' else {'state':{'send':'sent','friend':'friend_requested','alias':'renamed'}[action],'message_id':'99'}
    configure(client)
    return client,connector


def tick(app,clock=None):
    with app.app_context():
        app.extensions['campaign_scheduler'].tick(lambda:clock or moment())


def campaign(app):
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.row_factory=sqlite3.Row
        return dict(db.execute('SELECT * FROM campaigns WHERE id=1').fetchone())


def test_schedule_validation_ownership_and_manual_defaults(app):
    client,connector=setup_send(app)
    assert campaign(app)['schedule_enabled']==0
    for extra in ({'account_id':''},{'schedule_time':'25:00'},{'schedule_date':'bad'},{'schedule_stop':'07:00'},{'schedule_kind':'weekly','schedule_weekdays':[]},{'schedule_kind':'monthly','schedule_monthday':'32'},{'schedule_stop_enabled':'no','schedule_time':'23:59'}):
        result=configure(client,**extra)
        assert result.status_code==200 and campaign(app)['schedule_enabled']==0
    assert client.post('/campaigns/1/schedule',data=fields()).status_code==400
    other=app.test_client();register(other,'other')
    assert post(other,'/campaigns/1/schedule',fields()).status_code==404
    post(other,'/accounts',{'name':'Other'})
    assert 'không hợp lệ' in configure(client,account_id='2').text
    assert configure(client).status_code==200
    assert campaign(app)['schedule_enabled']==1
    assert connector.message_action.call_count==0


def test_windows_timezone_weekly_monthly_and_carry(app):
    client,_=setup(app)
    c=campaign(app)
    assert active_window(c,moment('2026-10-24T08:00:00'))
    assert active_window(c,datetime.fromisoformat('2026-10-24T01:00:00+00:00'))
    assert not active_window(c,moment('2026-10-24T17:00:00'))
    assert not active_window(c,moment('2026-10-23T10:00:00'))
    c.update(schedule_kind='weekly',schedule_weekdays='0',schedule_date='2026-10-26')
    assert active_window(c,moment('2026-10-26T10:00:00'))
    assert not active_window(c,moment('2026-10-27T10:00:00'))
    c.update(schedule_first_day='2026-10-26',schedule_carry=1)
    assert active_window(c,moment('2026-10-27T10:00:00'))
    c.update(schedule_continue=0)
    assert not active_window(c,moment('2026-10-27T10:00:00'))
    assert active_window(c,moment('2026-11-02T10:00:00'))
    c.update(schedule_kind='monthly',schedule_monthday=31,schedule_date='2026-01-01',schedule_carry=0)
    assert active_window(c,moment('2026-02-28T10:00:00'))
    assert active_window(c,moment('2028-02-29T10:00:00'))
    assert not active_window(c,moment('2026-02-27T10:00:00'))
    c.update(schedule_stop_enabled=0)
    assert active_window(c,moment('2026-02-28T23:58:59'))
    assert not active_window(c,moment('2026-02-28T23:59:00'))


def test_worker_prepares_once_then_sends_with_frozen_variant_and_media_ownership(app):
    client,connector=setup(app)
    post(client,'/campaigns/1/content',{'message':'A {{name}} | B {{name}}'})
    tick(app,moment('2026-10-24T07:59:59'));assert not connector.message_action.called
    tick(app);assert query(app,'SELECT state,scheduled,message FROM message_sends')==[('prepared',1,'A Lan')]
    tick(app);assert query(app,'SELECT state,message_id FROM message_sends')==[('sent','99')]
    for _ in range(3):tick(app)
    assert [call.args[2] for call in connector.message_action.call_args_list]==['resolve','send']
    assert campaign(app)['schedule_carry']==0
    assert campaign(app)['next_message_variant']==1
    assert Path(app.config['DATABASE']).with_suffix('.scheduler.heartbeat').is_file()


def test_cutoff_pending_continues_next_day_and_same_config_keeps_carry(app):
    client,connector=setup(app)
    configure(client,schedule_kind='weekly',schedule_weekdays=['5'])
    tick(app);assert query(app,'SELECT state FROM message_sends')==[('prepared',)]
    tick(app,moment('2026-10-24T17:00:00'))
    assert [call.args[2] for call in connector.message_action.call_args_list]==['resolve']
    configure(client,schedule_kind='weekly',schedule_weekdays=['5'])
    assert campaign(app)['schedule_carry']==1
    tick(app,moment('2026-10-25T10:00:00'))
    assert query(app,'SELECT state FROM message_sends')==[('sent',)]


def test_pause_disable_and_lookup_race_do_not_send(app):
    client,connector=setup(app)
    def resolve(*args,**kwargs):
        with sqlite3.connect(app.config['DATABASE']) as db:
            db.execute('UPDATE campaigns SET schedule_enabled=0,schedule_revision=schedule_revision+1 WHERE id=1')
        return {'state':'resolved','uid':'123456','name':'Lan'}
    connector.message_action.side_effect=resolve
    tick(app)
    assert query(app,'SELECT id FROM message_sends')==[]
    assert not campaign(app)['schedule_error']
    configure(client);connector.message_action.side_effect=None;connector.message_action.return_value={'state':'resolved','uid':'123456','name':'Lan'}
    tick(app)
    post(client,'/campaigns/1/pause',{'paused':'1'})
    tick(app);assert query(app,'SELECT state FROM message_sends')==[('prepared',)]
    assert len(connector.message_action.call_args_list)==2


def test_stop_time_rechecked_inside_dispatch_claim(app):
    client,connector=setup(app);tick(app)
    clock=[moment()];calls=[0]
    def status(*args):
        calls[0]+=1
        if calls[0]==2:clock[0]=moment('2026-10-24T17:00:00')
        return {'state':'connected'}
    connector.status.side_effect=status
    with app.app_context():app.extensions['campaign_scheduler'].tick(lambda:clock[0])
    assert query(app,'SELECT state FROM message_sends')==[('prepared',)]
    assert query(app,'SELECT id FROM campaign_attempts')==[]
    assert len(connector.message_action.call_args_list)==1


def test_consent_exclusions_and_manual_previews_are_never_auto_sent(app):
    client,connector=setup(app)
    # A manually prepared preview remains manual even when a schedule is enabled.
    post(client,'/campaigns/1/prepare-send',{'contact_id':'1','account_id':'1'})
    tick(app);assert query(app,'SELECT state,scheduled FROM message_sends')==[('prepared',0)]
    assert len(connector.message_action.call_args_list)==1
    post(client,'/campaigns/1/cancel-send/1');tick(app)
    post(client,'/contacts/1/consent');tick(app)
    assert query(app,'SELECT state FROM message_sends')==[('not_requested',)]
    assert [call.args[2] for call in connector.message_action.call_args_list]==['resolve','resolve']


def test_worker_limits_wait_without_consuming_attempts_and_unknown_never_retries(app):
    client,connector=setup(app)
    post(client,'/contacts',{'name':'Bình','phone':'0912345678','tag':'VIP','consent':'on'})
    post(client,'/campaigns/1/limits',{'message_limit':'1','friend_limit':'0','alias_limit':'0','interval_seconds':'0'})
    tick(app);tick(app);tick(app);tick(app)
    assert query(app,'SELECT state FROM message_sends ORDER BY id')==[('sent',)]
    assert [call.args[2] for call in connector.message_action.call_args_list]==['resolve','send']
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(1,)]
    assert campaign(app)['schedule_error']=='' and 'giới hạn' in campaign(app)['schedule_status']
    post(client,'/campaigns/1/limits',{'message_limit':'0','friend_limit':'0','alias_limit':'0','interval_seconds':'0'})
    connector.message_action.side_effect=lambda user,account,action,**kwargs: {'state':'resolved','uid':'123456','name':'Bình'} if action=='resolve' else {'state':'unknown'}
    tick(app);tick(app);assert query(app,'SELECT state FROM message_sends ORDER BY id')==[('sent',),('unknown',)]
    assert campaign(app)['schedule_error']
    count=connector.message_action.call_count
    tick(app);tick(app);assert connector.message_action.call_count==count


def test_interrupted_send_and_disconnected_account_block_without_retries(app):
    client,connector=setup(app);tick(app)
    with sqlite3.connect(app.config['DATABASE']) as db:db.execute("UPDATE message_sends SET state='sending'")
    tick(app);assert 'gián đoạn' in campaign(app)['schedule_error']
    assert len(connector.message_action.call_args_list)==1
    configure(client);connector.status.return_value={'state':'disconnected'}
    tick(app);assert 'đăng nhập' in campaign(app)['schedule_error']


def test_cancel_scheduled_preview_disables_schedule_and_clone_starts_disabled(app):
    client,connector=setup(app);tick(app)
    post(client,'/campaigns/1/cancel-send/1')
    assert campaign(app)['schedule_enabled']==0
    configure(client)
    post(client,'/campaigns/1/duplicate',{'name':'Copy'})
    assert query(app,'SELECT schedule_enabled,schedule_time,schedule_carry,next_message_variant FROM campaigns WHERE id=2')==[(0,'08:00',0,0)]
    assert 'wizard-schedule' in client.get('/campaigns/1/duplicate').text
    data=fields();data.update(options_present='yes',send_message='yes',name='Copy schedule',message='Nội dung',data_mode='group',tag='VIP')
    post(client,'/campaigns/1/duplicate',data)
    assert query(app,'SELECT schedule_enabled,schedule_time FROM campaigns WHERE id=3')==[(1,'08:00')]
    assert query(app,'SELECT count(*) FROM message_sends WHERE campaign_id=3')==[(0,)]


def test_cli_single_worker_lock(app):
    path=Path(app.config['DATABASE']).with_suffix('.scheduler.lock')
    with path.open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        result=app.test_cli_runner().invoke(args=['run-scheduler','--once'])
        assert result.exit_code==1 and 'tiến trình khác' in result.output
    result=app.test_cli_runner().invoke(args=['run-scheduler','--once'])
    assert result.exit_code==0


def test_scheduled_message_friend_alias_and_media_share_frozen_payload(app):
    client,connector=setup(app)
    data=fields();data.update(options_present='yes',send_message='yes',send_friend='yes',friend_message='Chào {{name}}',
        rename_enabled='yes',rename_template='#{FULL_NAME} - #{PHONE}',name='Đủ hành động',message='Chào {{name}}',
        rich_message='yes',message_html='<b>Chào {{name}}</b>',data_mode='group',tag='VIP',media_present='yes',media_mode='send',media=png())
    post(client,'/campaigns/1/edit',data)
    for _ in range(6):tick(app)
    assert query(app,'SELECT state,friend_state,alias_state FROM message_sends')==[('sent','friend_requested','renamed')]
    actions=[call.args[2] for call in connector.message_action.call_args_list]
    assert actions==['resolve','send','friend','alias']
    sent=connector.message_action.call_args_list[1].kwargs
    assert sent['message']=='Chào Lan' and sent['styles']==[{'start':0,'len':8,'st':'b'}]
    assert sent['attachment']['filename']=='bao-gia.png'
    assert connector.message_action.call_args_list[3].kwargs['message']=='Lan Zalo - 0901234567'


def test_create_campaign_with_schedule_and_disabled_legacy_form(app):
    client,_=setup_send(app)
    data=fields();data.update(name='Lịch mới',message='Chào {{name}}',tag='VIP')
    post(client,'/campaigns',data)
    assert query(app,'SELECT schedule_enabled,schedule_time,schedule_first_day FROM campaigns WHERE id=2')==[(1,'08:00',None)]
    post(client,'/campaigns',{'name':'Thủ công','message':'Chào','tag':'VIP'})
    assert query(app,'SELECT schedule_enabled FROM campaigns WHERE id=3')==[(0,)]


def test_resolved_uid_exclusion_is_skipped_without_variant_or_success_count(app):
    client,connector=setup(app)
    result=post(client,'/campaign-exclusions/lists',{'name':'Không gửi UID','uids':'123456'})
    list_id=result.json['id']
    post(client,'/campaigns/1/exclusions',{'exclusions_present':'yes','exclusion_list_ids':str(list_id)})
    tick(app);tick(app)
    assert query(app,'SELECT state,friend_state,alias_state,scheduled FROM message_sends')==[('not_requested','not_requested','not_requested',1)]
    assert campaign(app)['next_message_variant']==0
    assert [call.args[2] for call in connector.message_action.call_args_list]==['resolve']
    page=client.get('/campaigns?selected=1')
    assert page.status_code==200
