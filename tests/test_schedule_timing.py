import re
import sqlite3

import pytest

from campaign_schedule import active_window
from test_workflow import app, post
from test_send import setup_send, prepare
from test_campaign_schedule import configure, campaign, moment, setup, tick
from test_message_composer import query


def ready(client):
    post(client,'/campaigns/1/edit',{'name':'Noon campaign','message':'Chào {{name}}','tag':'VIP',
         'options_present':'yes','send_message':'yes','send_friend':'yes','friend_message':'Xin chào',
         'rename_enabled':'yes','rename_template':'{{name}}'})
    prepare(client)
    configure(client,schedule_date='2026-10-25',schedule_time='12:00')


def test_noon_midnight_and_utc_boundaries_are_distinct(app):
    client,_=setup_send(app)
    configure(client,schedule_date='2026-10-25',schedule_time='12:00')
    c=campaign(app)
    assert not active_window(c,moment('2026-10-25T00:00:00'))
    assert not active_window(c,moment('2026-10-25T11:59:59'))
    assert active_window(c,moment('2026-10-25T12:00:00'))
    assert not active_window(c,moment('2026-10-25T17:00:00'))
    from datetime import datetime
    assert not active_window(c,datetime.fromisoformat('2026-10-25T04:59:59+00:00'))
    assert active_window(c,datetime.fromisoformat('2026-10-25T05:00:00+00:00'))
    configure(client,schedule_date='2026-10-25',schedule_time='00:00')
    assert active_window(campaign(app),moment('2026-10-25T00:00:00'))
    assert active_window(campaign(app),moment('2026-10-25T11:51:00'))


@pytest.mark.parametrize('action,confirmation,column,result',[
    ('send','confirm_send','state',{'state':'sent','message_id':'time-test'}),
    ('friend','confirm_friend','friend_state',{'state':'friend_requested'}),
    ('alias','confirm_alias','alias_state',{'state':'renamed'}),
])
def test_manual_actions_cannot_bypass_noon_but_can_run_exactly_at_start(app,monkeypatch,action,confirmation,column,result):
    client,connector=setup_send(app);ready(client)
    clock=[moment('2026-10-25T11:51:00')]
    monkeypatch.setattr('campaign_schedule.local_now',lambda:clock[0])
    connector.message_action.reset_mock();connector.message_action.return_value=result
    response=post(client,f'/campaigns/1/{action}/1',{confirmation:'yes'})
    assert response.status_code==409 and 'Ngoài lịch chạy' in response.text
    assert not connector.message_action.called
    assert query(app,f'SELECT {column} FROM message_sends')==[('prepared',)]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(0,)]
    html=client.get('/campaigns/1').text
    for label in ('Gửi tin thật','Gửi lời mời kết bạn','Đổi tên gợi nhớ'):
        assert re.search(r'<button[^>]*disabled[^>]*>'+label+r'</button>',html)
    clock[0]=moment('2026-10-25T12:00:00')
    response=post(client,f'/campaigns/1/{action}/1',{confirmation:'yes'})
    assert response.status_code==200 and connector.message_action.call_count==1
    assert query(app,f'SELECT {column} FROM message_sends')==[(result['state'],)]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(1,)]
    assert 'Xác nhận thủ công' in query(app,'SELECT detail FROM campaign_events WHERE kind=?',(action,))[0][0]


def test_manual_dispatch_rechecks_new_schedule_after_preflight_and_honors_stop_and_disable(app,monkeypatch):
    client,connector=setup_send(app);ready(client)
    clock=[moment('2026-10-25T12:01:00')]
    monkeypatch.setattr('campaign_schedule.local_now',lambda:clock[0])
    def connected(*args):
        with sqlite3.connect(app.config['DATABASE']) as db:
            db.execute("UPDATE campaigns SET schedule_time='13:00',schedule_revision=schedule_revision+1 WHERE id=1")
        return {'state':'connected'}
    connector.status.side_effect=connected
    connector.message_action.reset_mock()
    response=post(client,'/campaigns/1/send/1',{'confirm_send':'yes'})
    assert response.status_code==409 and '13:00' in response.text
    assert not connector.message_action.called
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(0,)]
    connector.status.side_effect=None
    clock[0]=moment('2026-10-25T17:00:00')
    assert post(client,'/campaigns/1/send/1',{'confirm_send':'yes'}).status_code==409
    assert not connector.message_action.called
    configure(client,schedule_enabled='no')
    connector.message_action.return_value={'state':'sent','message_id':'manual'}
    assert post(client,'/campaigns/1/send/1',{'confirm_send':'yes'}).status_code==200
    assert connector.message_action.call_count==1


def test_schedule_update_stops_pending_automatic_action_until_new_start(app):
    client,connector=setup(app)
    # A saved preview from an earlier window must not dispatch under its old time.
    tick(app)
    assert query(app,'SELECT state,scheduled FROM message_sends')==[('prepared',1)]
    configure(client,schedule_date='2026-10-25',schedule_time='12:00')
    connector.message_action.reset_mock()
    tick(app,moment('2026-10-25T11:51:00'))
    tick(app,moment('2026-10-25T11:59:59'))
    assert not connector.message_action.called
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(0,)]
    tick(app,moment('2026-10-25T12:00:00'))
    assert connector.message_action.call_count==1
    assert query(app,'SELECT state FROM message_sends')==[('sent',)]
    assert 'Theo lịch tự động' in query(app,"SELECT detail FROM campaign_events WHERE kind='send'")[0][0]
    details=query(app,"SELECT detail FROM campaign_events WHERE kind='schedule' ORDER BY id DESC")[0][0]
    assert '12:00–17:00' in details and '2026-10-25' in details and 'Zalo của tôi' in details
    assert 'UTC+7' in details
