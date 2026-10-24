import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest
from flask import g

from campaign_limits import usage, ActionLimitReached
from test_workflow import app, post, register, token
from test_send import setup_send, prepare
from test_message_composer import query
from test_campaign_schedule import setup as setup_schedule, tick, fields as schedule_fields


def fields(**extra):
    values=dict(limits_present='yes',message_limit='100',friend_limit='25',alias_limit='0',interval_seconds='0',
        message_hour_limit='5',friend_hour_limit='5',message_window_minutes='65',friend_window_minutes='65',limits_day_mode='calendar',limits_continue='yes')
    values.update(extra)
    return values


def configure(client,**extra):
    return post(client,'/campaigns/1/limits',fields(**extra))


def add_second(client):
    post(client,'/contacts',{'name':'Bình','phone':'0912345678','tag':'VIP','consent':'on'})
    post(client,'/campaigns/1/prepare-send',{'contact_id':'2','account_id':'1'})


def test_hour_quota_blocks_manual_send_and_retains_existing_attempts(app):
    client,connector=setup_send(app);configure(client,message_limit='0',message_hour_limit='1')
    prepare(client);add_second(client)
    connector.message_action.reset_mock();connector.message_action.return_value={'state':'sent','message_id':'101'}
    post(client,'/campaigns/1/send/1',{'confirm_send':'yes'})
    response=post(client,'/campaigns/1/send/2',{'confirm_send':'yes'})
    assert response.status_code==409 and 'giới hạn' in response.text
    assert connector.message_action.call_count==1
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(1,)]
    assert query(app,'SELECT state FROM message_sends WHERE id=2')==[('prepared',)]
    configure(client,message_limit='0',message_hour_limit='1',message_window_minutes='60')
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(1,)]
    with sqlite3.connect(app.config['DATABASE']) as db:db.execute("UPDATE campaign_attempts SET created_at=datetime('now','-61 minutes')")
    post(client,'/campaigns/1/send/2',{'confirm_send':'yes'})
    assert connector.message_action.call_count==2


def test_vietnam_midnight_and_rolling_hour_boundaries(app):
    client,_=setup_send(app);prepare(client)
    manager=app.extensions['campaign_manager']
    with app.app_context():
        db=manager.db();db.execute("INSERT INTO campaign_attempts(campaign_id,send_id,action,created_at) VALUES (1,1,'send','2026-10-24 16:59:59')");db.commit()
        c=dict(db.execute('SELECT * FROM campaigns WHERE id=1').fetchone());c.update(limits_day_mode='calendar',message_window_minutes=65)
        after=datetime.fromisoformat('2026-10-24T17:00:00+00:00')  # Midnight in Vietnam.
        budget=usage(manager.db,c,after)['send'];assert budget['day_used']==0 and budget['hour_used']==1
        c['limits_day_mode']='rolling';assert usage(manager.db,c,after)['send']['day_used']==1
        assert usage(manager.db,c,datetime.fromisoformat('2026-10-24T18:05:00+00:00'))['send']['hour_used']==0


def test_config_validation_private_usage_and_legacy_settings(app):
    client,_=setup_send(app)
    configure(client,message_hour_limit='2',friend_window_minutes='80')
    before=query(app,'SELECT message_hour_limit,friend_window_minutes FROM campaigns')[0]
    for extra in ({'message_limit':'-1'},{'interval_seconds':'2.3'},{'friend_window_minutes':'0'},{'message_window_minutes':'1441'},{'limits_day_mode':'bad'}):
        assert configure(client,**extra).status_code==200
        assert query(app,'SELECT message_hour_limit,friend_window_minutes FROM campaigns')[0]==before
    assert client.post('/campaigns/1/limits',data=fields()).status_code==400
    response=client.get('/campaigns/1/limits/usage?mode=calendar&message_window_minutes=30')
    assert response.status_code==200 and response.json['usage']['send']['minutes']==30
    assert client.get('/campaigns/1/limits/usage?message_window_minutes=0').status_code==400
    other=app.test_client();register(other,'other')
    assert other.get('/campaigns/1/limits/usage').status_code==404
    # Old clients changing daily limits do not clear an existing hourly cap.
    post(client,'/campaigns/1/limits',{'message_limit':'90','friend_limit':'20','alias_limit':'0','interval_seconds':'5'})
    assert query(app,'SELECT message_hour_limit,friend_window_minutes FROM campaigns')[0]==before


@pytest.mark.parametrize('continues',[True,False])
def test_scheduler_continues_only_actions_with_remaining_quota(app,continues):
    client,connector=setup_schedule(app)
    post(client,'/contacts',{'name':'Bình','phone':'0912345678','tag':'VIP','consent':'on'})
    data=schedule_fields();data.update(fields(message_limit='1',message_hour_limit='0',friend_limit='10',friend_hour_limit='0',limits_continue='yes' if continues else ''))
    data.update(name='Hai hành động',message='Chào {{name}}',tag='VIP',options_present='yes',send_message='yes',send_friend='yes',friend_message='Xin chào',data_mode='group')
    post(client,'/campaigns/1/edit',data)
    for _ in range(9):tick(app)
    actions=[call.args[2] for call in connector.message_action.call_args_list]
    assert actions.count('send')==1
    assert actions.count('friend')==(2 if continues else 0)
    assert actions.count('resolve')==(2 if continues else 1)
    assert query(app,'SELECT count(*) FROM campaign_attempts WHERE action="send"')==[(1,)]
    assert not query(app,'SELECT schedule_error FROM campaigns')[0][0]
    assert 'chờ giới hạn' in query(app,'SELECT schedule_status FROM campaigns')[0][0]


def test_new_create_edit_and_clone_preserve_limits_but_clear_counters(app):
    client,_=setup_send(app)
    data=fields();data.update(name='New limits',message='Chào',tag='VIP',interval_seconds='120')
    post(client,'/campaigns',data)
    assert query(app,'SELECT message_limit,friend_limit,message_hour_limit,interval_seconds,limits_day_mode FROM campaigns WHERE id=2')==[(100,25,5,120,'calendar')]
    configure(client,message_limit='123',friend_limit='27',message_window_minutes='70')
    prepare(client)
    with sqlite3.connect(app.config['DATABASE']) as db:db.execute("INSERT INTO campaign_attempts(campaign_id,send_id,action) VALUES (1,1,'send')")
    post(client,'/campaigns/1/duplicate',{'name':'Copy'})
    assert query(app,'SELECT message_limit,friend_limit,message_hour_limit,message_window_minutes,limits_day_mode FROM campaigns WHERE id=3')==[(123,27,5,70,'calendar')]
    assert query(app,'SELECT count(*) FROM campaign_attempts WHERE campaign_id=3')==[(0,)]
    assert 'wizard-limits' in client.get('/campaigns/1/duplicate').text


def test_two_simultaneous_claims_cannot_exceed_hourly_quota(app):
    client,_=setup_send(app);configure(client,message_limit='0',message_hour_limit='1')
    prepare(client);add_second(client)
    barrier=Barrier(2);manager=app.extensions['campaign_manager']
    def claim(send_id):
        with app.app_context():
            db=manager.db();g.user=db.execute('SELECT id,name,username FROM users WHERE id=1').fetchone()
            expected=db.execute('SELECT * FROM message_sends WHERE id=?',(send_id,)).fetchone()
            barrier.wait(timeout=10)
            try:return manager.claim(1,send_id,'send',expected)
            except ActionLimitReached:return False
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(claim,[1,2]))==[False,True]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(1,)]
