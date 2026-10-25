"""Failed/uncertain recipients cannot stall the campaign or be sent again."""
import csv
import io
import sqlite3
from datetime import datetime,timedelta,timezone

import pytest

from app import create_app
from test_workflow import app,post
from test_campaign_schedule import setup,tick,moment,campaign
from test_campaign_sequence import all_actions
from test_lookup_skip import add_contact
from test_message_composer import query
from test_campaign_list import campaign_status


@pytest.mark.parametrize('action',['send','friend','alias'])
@pytest.mark.parametrize('outcome',['unknown','failed'])
def test_error_is_preserved_but_skipped_then_next_recipient_runs_after_rest(app,action,outcome):
    client,connector=setup(app);add_contact(client);all_actions(client)
    def call(user,account,kind,**data):
        if kind=='resolve':return dict(state='resolved',uid=data['phone'],name='Found customer')
        if data['uid']=='0901234567' and kind==action:return dict(state=outcome)
        return dict(state={'send':'sent','friend':'friend_requested','alias':'renamed'}[kind])
    connector.message_action.side_effect=call
    clock=moment();end={'send':1,'friend':2,'alias':3}[action]
    for second in range(end+1):tick(app,clock+timedelta(seconds=second))
    column={'send':'state','friend':'friend_state','alias':'alias_state'}[action]
    assert query(app,f'SELECT {column},schedule_turn_finished FROM message_sends')==[(outcome,1)]
    assert query(app,'SELECT schedule_skip_reason FROM message_sends')[0][0]
    assert not campaign(app)['schedule_error']
    assert campaign_status(client)==['Đang xử lý']
    before=connector.message_action.call_count
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(end,)]
    restored=create_app(dict(TESTING=True,DATABASE=app.config['DATABASE'],SECRET_KEY='test-only',ZALO_QR_ENABLED=True))
    restored.extensions['zalo_connector'].status=connector.status
    restored.extensions['zalo_connector'].message_action=connector.message_action
    tick(restored,clock+timedelta(seconds=end+119));assert connector.message_action.call_count==before
    for second in range(end+120,end+124):tick(restored,clock+timedelta(seconds=second))
    assert connector.message_action.call_count==before+4
    assert query(app,'SELECT state,friend_state,alias_state FROM message_sends WHERE contact_id=2')==[('sent','friend_requested','renamed')]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(end+3,)]
    for second in range(end+244,end+247):tick(restored,clock+timedelta(seconds=second))
    assert connector.message_action.call_count==before+4
    assert campaign_status(client)==['Đã xử lý']
    page=client.get('/campaigns?selected=1&detail_tab=results').text
    assert f'data-result-state="{outcome}"' in page and 'Bỏ qua 0901234567' in page
    exported=list(csv.DictReader(io.StringIO(client.get('/campaigns/1/report?format=csv').data.decode('utf-8-sig'))))
    assert any('Bỏ qua 0901234567' in row['Lý do bỏ qua'] for row in exported)
    assert query(app,"SELECT count(*) FROM campaign_events WHERE kind='schedule_action_skip'")==[(1,)]
    # Marking the parent recipient skipped never lets a manual click dispatch a later action.
    post(client,'/campaigns/1/friend/1',{'confirm_friend':'yes'})
    assert connector.message_action.call_count==before+4


@pytest.mark.parametrize('result',[None,RuntimeError('PRIVATE_UPSTREAM_DETAILS')])
def test_malformed_response_or_exception_also_moves_on_without_leaking_errors(app,result):
    client,connector=setup(app);add_contact(client);all_actions(client,interval=0)
    def call(user,account,kind,**data):
        if kind=='resolve':return dict(state='resolved',uid=data['phone'],name='Found')
        if data['uid']=='0901234567':
            if isinstance(result,Exception):raise result
            return result
        return dict(state={'send':'sent','friend':'friend_requested','alias':'renamed'}[kind])
    connector.message_action.side_effect=call
    for _ in range(10):tick(app)
    assert query(app,'SELECT state FROM message_sends ORDER BY id')==[('unknown',),('sent',)]
    assert not campaign(app)['schedule_error']
    assert 'PRIVATE_' not in client.get('/campaigns/1/history').text


def test_stale_sending_claim_is_not_retried_and_wait_is_persisted(app):
    client,connector=setup(app);add_contact(client);all_actions(client)
    tick(app)
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE message_sends SET state='sending'")
        db.execute("INSERT INTO campaign_attempts(campaign_id,send_id,action,created_at) VALUES(1,1,'send',?)",(now.isoformat(' '),))
    tick(app);assert connector.message_action.call_count==1
    assert not query(app,'SELECT schedule_skip_reason FROM message_sends')[0][0]
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('UPDATE campaign_attempts SET created_at=?',((now-timedelta(seconds=91)).isoformat(' '),))
    tick(app)
    assert query(app,'SELECT state,friend_state,alias_state FROM message_sends')==[('unknown','not_requested','not_requested')]
    assert query(app,'SELECT schedule_skip_reason FROM message_sends')[0][0]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(1,)]
    assert not campaign(app)['schedule_error']
    tick(app,moment()+timedelta(seconds=119));assert connector.message_action.call_count==1
    tick(app,moment()+timedelta(seconds=120));assert connector.message_action.call_count==2


@pytest.mark.parametrize('paused',[0,1])
def test_upgrade_resumes_specific_old_unknown_block_but_keeps_pause_and_result(app,paused):
    client,connector=setup(app);add_contact(client);tick(app)
    message='Kết quả hành động chưa xác định. Kiểm tra hội thoại Zalo rồi lưu lại lịch để tiếp tục; không tự gửi lại lần đó.'
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE message_sends SET state='unknown'")
        db.execute('UPDATE campaigns SET schedule_error=?,paused=?',(message,paused))
    restored=create_app(dict(TESTING=True,DATABASE=app.config['DATABASE'],SECRET_KEY='test-only',ZALO_QR_ENABLED=True))
    restored.extensions['zalo_connector'].status=connector.status
    restored.extensions['zalo_connector'].message_action=connector.message_action
    assert query(app,'SELECT schedule_error,paused FROM campaigns')==[('',paused)]
    tick(restored)
    assert connector.message_action.call_count==1
    assert query(app,'SELECT state FROM message_sends')==[('unknown',)]
    assert bool(query(app,'SELECT schedule_skip_reason FROM message_sends')[0][0])==(not bool(paused))
