import sqlite3
from datetime import timedelta

import pytest

from app import create_app
from test_campaign_schedule import setup,tick,campaign,moment
from test_message_composer import query
from test_lookup_skip import add_contact
from test_workflow import app,post


@pytest.mark.parametrize('missing',[{'state':'not_found'},{'state':'failed'},{'state':'lookup_failed','lookup_reason':'unavailable','lookup_code':'221'}])
def test_missing_phone_rests_exactly_configured_interval_then_looks_up_next_phone(app,missing):
    client,connector=setup(app);add_contact(client)
    post(client,'/campaigns/1/limits',{'interval_seconds':'120'})
    def action(user,account,kind,**data):
        return missing if data.get('phone')=='0901234567' else {'state':'resolved','uid':'222','name':'Next customer'}
    connector.message_action.side_effect=action
    clock=moment()
    tick(app,clock)
    assert query(app,'SELECT contact_id,state FROM message_sends')==[(1,'not_requested')]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(0,)]
    assert campaign(app)['next_message_variant']==0 and not campaign(app)['schedule_error']
    tick(app,clock+timedelta(seconds=119))
    assert connector.message_action.call_count==1
    # Restarting cannot bypass the configured rest or redo the first lookup.
    restored=create_app({'TESTING':True,'DATABASE':app.config['DATABASE'],'SECRET_KEY':'test-only','ZALO_QR_ENABLED':True})
    restored.extensions['zalo_connector'].status=connector.status
    restored.extensions['zalo_connector'].message_action=connector.message_action
    tick(restored,clock+timedelta(seconds=119))
    assert connector.message_action.call_count==1
    tick(restored,clock+timedelta(seconds=120))
    assert connector.message_action.call_count==2
    assert connector.message_action.call_args.kwargs['phone']=='0912345678'
    assert query(app,'SELECT contact_id,state FROM message_sends ORDER BY id')==[(1,'not_requested'),(2,'prepared')]
    kinds=[row[0] for row in query(app,'SELECT kind FROM campaign_events ORDER BY id')]
    assert kinds.index('lookup_skip')<kinds.index('schedule_complete')<kinds.index('schedule_rest')
    assert 'Nghỉ 120 giây' in client.get('/campaigns/1/history').text


@pytest.mark.parametrize('reason,seconds',[('network',60),('rate_limited',900),('invalid_response',60)])
def test_temporary_service_failure_waits_and_retries_without_losing_phone(app,reason,seconds):
    client,connector=setup(app)
    connector.message_action.side_effect=None
    connector.message_action.return_value={'state':'lookup_failed','lookup_reason':reason,'lookup_code':'429' if reason=='rate_limited' else 'ETIMEDOUT'}
    clock=moment();tick(app,clock)
    assert query(app,'SELECT count(*) FROM message_sends')==[(0,)]
    assert not campaign(app)['schedule_error']
    tick(app,clock+timedelta(seconds=seconds-1))
    assert connector.message_action.call_count==1
    connector.message_action.return_value={'state':'resolved','uid':'123','name':'Found'}
    tick(app,clock+timedelta(seconds=seconds))
    assert connector.message_action.call_count==2
    assert query(app,'SELECT state FROM message_sends')==[('prepared',)]


def test_session_failure_is_specific_and_not_misreported_as_a_missing_phone(app):
    client,connector=setup(app)
    connector.message_action.side_effect=None
    connector.message_action.return_value={'state':'lookup_failed','lookup_reason':'session','lookup_code':'401'}
    tick(app)
    assert 'đăng nhập QR lại' in campaign(app)['schedule_error'] and '401' in campaign(app)['schedule_error']
    assert query(app,'SELECT count(*) FROM message_sends')==[(0,)]


def test_current_generic_lookup_block_also_resumes_after_upgrade(app):
    client,connector=setup(app)
    error='Không thể tra cứu Zalo của 0943880779 lúc này. Kiểm tra kết nối, giới hạn tra cứu hoặc đăng nhập Zalo rồi lưu lại lịch.'
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('UPDATE campaigns SET schedule_error=? WHERE id=1',(error,))
    create_app({'TESTING':True,'DATABASE':app.config['DATABASE'],'SECRET_KEY':'test-only'})
    assert not campaign(app)['schedule_error']
