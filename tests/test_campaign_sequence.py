"""Recipient-level campaign sequence and quota continuation, without real sends."""
import sqlite3
from datetime import timedelta

from app import create_app
from test_workflow import app,post
from test_campaign_schedule import setup,tick,moment,fields
from test_lookup_skip import add_contact
from test_message_composer import query


def all_actions(client,interval=120,**limits):
    post(client,'/campaigns/1/edit',dict(name='Full sequence',message='Hello {{name}}',tag='VIP',account_id='1',
        options_present='yes',send_message='yes',send_friend='yes',friend_message='Hi',
        rename_enabled='yes',rename_template='#{FULL_NAME} - #{PHONE}'))
    post(client,'/campaigns/1/limits',dict(interval_seconds=str(interval),message_limit='0',friend_limit='0',alias_limit='0',**limits))


def test_all_actions_run_in_order_then_rest_once_and_restart_does_not_repeat(app):
    client,connector=setup(app);add_contact(client);add_contact(client,'0923456789')
    all_actions(client)
    def action(user,account,kind,**data):
        if kind=='resolve':
            return {'state':'not_found'} if data['phone']=='0912345678' else {'state':'resolved','uid':data['phone'],'name':'Found customer'}
        return dict(state={'send':'sent','friend':'friend_requested','alias':'renamed'}[kind])
    connector.message_action.side_effect=action
    clock=moment()
    for second in range(4):tick(app,clock+timedelta(seconds=second))
    assert [call.args[2] for call in connector.message_action.call_args_list]==['resolve','send','friend','alias']
    assert query(app,'SELECT state,friend_state,alias_state,schedule_turn_finished FROM message_sends')==[('sent','friend_requested','renamed',1)]
    assert query(app,"SELECT count(*) FROM campaign_events WHERE kind='schedule_complete'")==[(1,)]
    assert query(app,"SELECT count(*) FROM campaign_events WHERE kind='schedule_rest'")==[(1,)]
    kinds=[row[0] for row in query(app,'SELECT kind FROM campaign_events ORDER BY id')]
    expected=['schedule_start','schedule_lookup','schedule_lookup_result','send_result','friend_result','alias_result','schedule_complete','schedule_rest']
    indices=[kinds.index(kind) for kind in expected]
    assert indices==sorted(indices)
    # Rest starts after alias completes at +3, not after sending at +1.
    tick(app,clock+timedelta(seconds=122));assert connector.message_action.call_count==4
    restarted=create_app(dict(TESTING=True,DATABASE=app.config['DATABASE'],SECRET_KEY='test-only',ZALO_QR_ENABLED=True))
    restarted.extensions['zalo_connector'].status=connector.status
    restarted.extensions['zalo_connector'].message_action=connector.message_action
    tick(restarted,clock+timedelta(seconds=122));assert connector.message_action.call_count==4
    tick(restarted,clock+timedelta(seconds=123));assert connector.message_action.call_count==5
    assert query(app,'SELECT state,friend_state,alias_state FROM message_sends WHERE contact_id=2')==[('not_requested','not_requested','not_requested')]
    tick(restarted,clock+timedelta(seconds=242));assert connector.message_action.call_count==5
    for second in range(243,247):tick(restarted,clock+timedelta(seconds=second))
    assert [call.args[2] for call in connector.message_action.call_args_list]==['resolve','send','friend','alias','resolve','resolve','send','friend','alias']
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(6,)]
    assert query(app,"SELECT count(*) FROM campaign_events WHERE kind='schedule_complete'")==[(3,)]
    assert query(app,"SELECT count(*) FROM campaign_events WHERE kind='schedule_rest'")==[(3,)]
    tick(restarted,clock+timedelta(seconds=366));tick(restarted,clock+timedelta(seconds=367))
    assert query(app,"SELECT count(*) FROM campaign_events WHERE kind='schedule_finished'")==[(1,)]
    assert connector.message_action.call_count==9


def test_exhausted_friend_quota_keeps_sending_and_renaming_then_finishes_missing_friends(app):
    client,connector=setup(app);add_contact(client)
    all_actions(client,interval=0)
    post(client,'/campaigns/1/limits',{'friend_limit':'1'})
    for _ in range(20):tick(app)
    actions=[call.args[2] for call in connector.message_action.call_args_list]
    assert actions==['resolve','send','friend','alias','resolve','send','alias']
    assert query(app,'SELECT state,friend_state,alias_state FROM message_sends ORDER BY id')==[
        ('sent','friend_requested','renamed'),('sent','prepared','renamed')]
    assert query(app,'SELECT schedule_completed_at FROM message_sends WHERE contact_id=2')==[(None,)]
    assert query(app,"SELECT count(*) FROM campaign_events WHERE kind='schedule_limit'")==[(1,)]
    assert query(app,"SELECT count(*) FROM campaign_events WHERE kind='schedule_complete'")==[(1,)]
    assert 'Kết bạn: đạt giới hạn' in client.get('/campaigns/1/history').text
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE campaign_attempts SET created_at='2000-01-01 00:00:00' WHERE action='friend'")
    tick(app);tick(app)
    assert [call.args[2] for call in connector.message_action.call_args_list]==actions+['friend']
    assert query(app,'SELECT state,friend_state,alias_state FROM message_sends ORDER BY id')==[
        ('sent','friend_requested','renamed'),('sent','friend_requested','renamed')]
    assert query(app,"SELECT count(*) FROM campaign_events WHERE kind='schedule_complete'")==[(2,)]
    assert 'value="100"' in client.get('/campaigns').text


def test_one_campaign_waiting_for_quota_does_not_stop_other_campaigns(app):
    client,connector=setup(app);add_contact(client)
    post(client,'/campaigns/1/limits',{'message_limit':'1','interval_seconds':'0'})
    data=fields();data.update(name='Second campaign',message='Hi',tag='VIP')
    post(client,'/campaigns',data)
    for _ in range(10):tick(app)
    assert query(app,"SELECT campaign_id,count(*) FROM message_sends WHERE state='sent' GROUP BY campaign_id ORDER BY campaign_id")==[(1,1),(2,2)]
    assert 'chờ giới hạn' in query(app,'SELECT schedule_status FROM campaigns WHERE id=1')[0][0]
    assert query(app,'SELECT schedule_error FROM campaigns WHERE id=2')==[('',)]


def test_rest_is_rechecked_after_lookup_before_creating_or_sending(app):
    client,connector=setup(app)
    def lookup(*args,**kwargs):
        with sqlite3.connect(app.config['DATABASE']) as db:
            db.execute("UPDATE campaigns SET schedule_wait_until='2099-01-01 00:00:00'")
        return dict(state='resolved',uid='123',name='Found')
    connector.message_action.side_effect=lookup
    tick(app)
    assert query(app,'SELECT count(*) FROM message_sends')==[(0,)]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(0,)]
    assert query(app,'SELECT schedule_error FROM campaigns')==[('',)]


def test_recovery_finishes_committed_skip_and_rests_before_next_phone(app):
    client,connector=setup(app);add_contact(client)
    post(client,'/campaigns/1/limits',{'interval_seconds':'120'})
    connector.message_action.side_effect=None
    connector.message_action.return_value={'state':'not_found'}
    clock=moment();tick(app,clock)
    # Simulate a restart between committing a read-only skip and its rest.
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('UPDATE message_sends SET schedule_turn_finished=0,schedule_completed_at=NULL')
        db.execute("UPDATE campaigns SET schedule_wait_until='',schedule_wait_message=''")
        db.execute("DELETE FROM campaign_events WHERE kind IN ('schedule_complete','schedule_rest')")
    tick(app,clock+timedelta(seconds=1))
    assert connector.message_action.call_count==1
    assert query(app,"SELECT count(*) FROM campaign_events WHERE kind='schedule_complete'")==[(1,)]
    assert query(app,"SELECT count(*) FROM campaign_events WHERE kind='schedule_rest'")==[(1,)]
    tick(app,clock+timedelta(seconds=120));assert connector.message_action.call_count==1
    tick(app,clock+timedelta(seconds=121));assert connector.message_action.call_count==2
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(0,)]
