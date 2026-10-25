import re
import sqlite3
from datetime import datetime

import pytest

from app import create_app
from campaign_schedule import active_window
from test_campaign_schedule import configure, campaign, fields, moment, setup, tick
from test_message_composer import query
from test_schedule_timing import ready
from test_send import setup_send
from test_workflow import app, post


@pytest.mark.parametrize('kind', ['daily','weekly','monthly'])
def test_sunday_override_applies_to_all_kinds_and_carry_in_vietnam_timezone(app,kind):
    client,_=setup_send(app)
    configure(client,schedule_skip_sunday='yes',schedule_kind=kind,schedule_weekdays=['5','6'],schedule_monthday='25',
              schedule_time='00:00',schedule_stop='23:59')
    c=campaign(app)
    for carry in (0,1):
        c.update(schedule_carry=carry,schedule_first_day='2026-10-24')
        assert not active_window(c,moment('2026-10-25T10:00:00'))
        assert not active_window(c,datetime.fromisoformat('2026-10-24T17:00:00+00:00'))  # Sunday 00:00 in Vietnam.
    assert active_window(c,datetime.fromisoformat('2026-10-25T17:00:00+00:00'))  # Monday 00:00, carry enabled.
    c['schedule_skip_sunday']=0
    assert active_window(c,moment('2026-10-25T10:00:00'))


def test_unfinished_weekly_data_waits_on_sunday_and_continues_monday(app):
    client,connector=setup(app)
    configure(client,schedule_kind='weekly',schedule_weekdays=['5'])
    tick(app)  # Saturday lookup and saved preview.
    assert query(app,'SELECT state,scheduled FROM message_sends')==[('prepared',1)]
    assert campaign(app)['schedule_carry']==1
    configure(client,schedule_skip_sunday='yes',schedule_kind='weekly',schedule_weekdays=['5'])
    assert campaign(app)['schedule_carry']==1 and campaign(app)['schedule_first_day']=='2026-10-24'
    connector.message_action.reset_mock()
    tick(app,moment('2026-10-25T10:00:00'))
    assert not connector.message_action.called
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(0,)]
    assert not campaign(app)['schedule_error']
    tick(app,moment('2026-10-26T10:00:00'))
    assert [call.args[2] for call in connector.message_action.call_args_list]==['send']
    assert query(app,'SELECT state FROM message_sends')==[('sent',)]


@pytest.mark.parametrize('action,confirmation', [('send','confirm_send'),('friend','confirm_friend'),('alias','confirm_alias')])
def test_sunday_blocks_manual_actions_without_consuming_attempts(app,monkeypatch,action,confirmation):
    client,connector=setup_send(app);ready(client)
    configure(client,schedule_date='2026-10-25',schedule_time='08:00',schedule_skip_sunday='yes')
    monkeypatch.setattr('campaign_schedule.local_now',lambda:moment('2026-10-25T10:00:00'))
    connector.message_action.reset_mock()
    response=post(client,f'/campaigns/1/{action}/1',{confirmation:'yes'})
    assert response.status_code==409 and 'Không chạy ngày Chủ nhật' in response.text
    assert not connector.message_action.called
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(0,)]
    assert query(app,'SELECT state,friend_state,alias_state FROM message_sends')==[('prepared','prepared','prepared')]


def test_sunday_setting_saves_copies_and_survives_legacy_forms(app):
    client,_=setup_send(app)
    assert campaign(app)['schedule_skip_sunday']==0
    configure(client,schedule_skip_sunday='yes')
    assert campaign(app)['schedule_skip_sunday']==1
    assert 'Không chạy ngày Chủ nhật' in query(app,"SELECT detail FROM campaign_events WHERE kind='schedule' ORDER BY id DESC")[0][0]
    assert re.search(r'name="schedule_skip_sunday"[^>]*checked',client.get('/campaigns/1/schedule').text)
    assert 'Không chạy ngày Chủ nhật' in client.get('/campaigns/1').text
    post(client,'/campaigns/1/duplicate',{'name':'Copy'})
    assert query(app,'SELECT schedule_skip_sunday,schedule_enabled FROM campaigns WHERE id=2')==[(1,0)]
    configure(client)  # A tab using the old form cannot silently clear the new choice.
    assert campaign(app)['schedule_skip_sunday']==1
    invalid=configure(client,schedule_time='25:00')
    assert re.search(r'name="schedule_skip_sunday"[^>]*checked',invalid.text)
    configure(client,schedule_skip_sunday_present='yes')
    assert campaign(app)['schedule_skip_sunday']==0
    data=fields();data.update(name='New schedule',message='Hi',data_mode='group',tag='VIP',
                            schedule_skip_sunday_present='yes',schedule_skip_sunday='yes')
    post(client,'/campaigns',data)
    assert query(app,'SELECT schedule_skip_sunday,schedule_enabled FROM campaigns WHERE id=3')==[(1,1)]


def test_weekly_sunday_only_cannot_conflict_with_skip_setting(app):
    client,_=setup_send(app)
    response=configure(client,schedule_kind='weekly',schedule_weekdays=['6'],schedule_skip_sunday='yes')
    assert 'Chọn ít nhất một ngày từ Thứ 2 đến Thứ 7' in response.text
    assert campaign(app)['schedule_enabled']==0
    configure(client,schedule_kind='weekly',schedule_weekdays=['6'],schedule_skip_sunday_present='yes')
    assert campaign(app)['schedule_enabled']==1 and campaign(app)['schedule_skip_sunday']==0


def test_sunday_rule_is_rechecked_after_worker_preflight(app):
    client,connector=setup(app)
    tick(app,moment('2026-10-25T10:00:00'))
    def connected(*args):
        with sqlite3.connect(app.config['DATABASE']) as db:
            db.execute('UPDATE campaigns SET schedule_skip_sunday=1 WHERE id=1')
        return {'state':'connected'}
    connector.status.side_effect=connected
    connector.message_action.reset_mock()
    tick(app,moment('2026-10-25T10:00:00'))
    assert not connector.message_action.called
    assert query(app,'SELECT state FROM message_sends')==[('prepared',)]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(0,)]
    assert not campaign(app)['schedule_error']


def test_existing_schedule_migration_defaults_to_previous_sunday_behavior(app):
    client,_=setup_send(app);configure(client)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('ALTER TABLE campaigns DROP COLUMN schedule_skip_sunday')
    create_app({'TESTING':True,'DATABASE':app.config['DATABASE'],'SECRET_KEY':'test-only'})
    assert query(app,'SELECT schedule_skip_sunday,schedule_enabled,schedule_time FROM campaigns')==[(0,1,'08:00')]
