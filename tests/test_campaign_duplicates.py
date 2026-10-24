import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest
from flask import g

from campaign_duplicates import DuplicateMessageBlocked, recent_message
from test_workflow import app, post, register, token
from test_send import setup_send, prepare
from test_message_composer import query
from test_campaign_schedule import tick, fields as schedule_fields


def configure(client,campaign_id=1,**extra):
    data=dict(duplicate_present='yes',duplicate_enabled='yes',duplicate_days='10');data.update(extra)
    return post(client,f'/campaigns/{campaign_id}/duplicate-check',data)


def second(client,account='1',**extra):
    data=dict(name='Chiến dịch thứ hai',message='Tin mới {{name}}',tag='VIP',account_id=account);data.update(extra)
    post(client,'/campaigns',data)
    return 2


def send_first(client,connector):
    prepare(client)
    connector.message_action.return_value={'state':'sent','message_id':'123'}
    with sqlite3.connect(client.application.config['DATABASE']) as db:
        send_id=db.execute('SELECT id FROM message_sends WHERE campaign_id=1 AND contact_id=1').fetchone()[0]
    post(client,f'/campaigns/1/send/{send_id}',{'confirm_send':'yes'})
    connector.message_action.return_value={'state':'resolved','uid':'123456','name':'Lan Zalo'}


def prepare_second(client,account='1'):
    return post(client,'/campaigns/2/prepare-send',{'contact_id':'1','account_id':account})


def test_same_account_manual_message_blocked_without_consuming_attempt(app):
    client,connector=setup_send(app);send_first(client,connector);second(client);configure(client,2)
    page=prepare_second(client)
    assert 'Không gửi lại' in page.text and 'Chiến dịch' in page.text
    connector.message_action.reset_mock()
    result=post(client,'/campaigns/2/send/2',{'confirm_send':'yes'})
    assert result.status_code==409 and '10 ngày' in result.text
    assert not connector.message_action.called
    assert query(app,'SELECT count(*) FROM campaign_attempts WHERE campaign_id=2')==[(0,)]
    assert query(app,'SELECT state FROM message_sends WHERE campaign_id=2')==[('prepared',)]
    configure(client,2,duplicate_enabled='')
    connector.message_action.return_value={'state':'sent','message_id':'456'}
    post(client,'/campaigns/2/send/2',{'confirm_send':'yes'})
    assert connector.message_action.call_count==1


def test_account_scope_and_owner_isolation(app):
    client,connector=setup_send(app);send_first(client,connector)
    post(client,'/accounts',{'name':'Tài khoản 2'});second(client,account='2');configure(client,2)
    prepare_second(client,account='2')
    manager=app.extensions['campaign_manager']
    with app.app_context():
        db=manager.db();c=db.execute('SELECT * FROM campaigns WHERE id=2').fetchone()
        assert recent_message(manager.db,c,2,'0901234567','123456') is None
    configure(client,2,duplicate_all_accounts='yes')
    assert post(client,'/campaigns/2/send/2',{'confirm_send':'yes'}).status_code==409
    other=app.test_client();register(other,'other');post(other,'/accounts',{'name':'Tài khoản khác'})
    post(other,'/contacts',{'name':'Khách khác','phone':'0901234567','consent':'on','tag':'VIP'})
    post(other,'/campaigns',{'name':'Riêng tư','message':'Xin chào','tag':'VIP','account_id':'3'})
    configure(other,3,duplicate_all_accounts='yes')
    post(other,'/campaigns/3/prepare-send',{'contact_id':'2','account_id':'3'})
    connector.message_action.return_value={'state':'sent','message_id':'other'}
    result=post(other,'/campaigns/3/send/3',{'confirm_send':'yes'})
    assert result.status_code==200 and query(app,'SELECT state FROM message_sends WHERE id=3')==[('sent',)]
    assert other.get('/campaigns/1/duplicate-check').status_code==404
    assert post(other,'/campaigns/1/duplicate-check',{'duplicate_present':'yes'}).status_code==404


def test_window_uses_dispatch_time_and_preserves_deleted_history(app):
    client,connector=setup_send(app);send_first(client,connector);second(client);configure(client,2)
    manager=app.extensions['campaign_manager'];now=datetime.fromisoformat('2026-10-24T12:00:00+00:00')
    with app.app_context():
        db=manager.db()
        db.execute("UPDATE message_sends SET created_at='2020-01-01 00:00:00'")
        db.execute("UPDATE campaign_attempts SET created_at='2026-10-23 12:00:00'")
        db.execute("UPDATE campaigns SET deleted_at=CURRENT_TIMESTAMP WHERE id=1");db.commit()
        c=db.execute('SELECT * FROM campaigns WHERE id=2').fetchone()
        assert recent_message(manager.db,c,1,'0901234567',now=now) is not None
        assert recent_message(manager.db,c,1,'0901234567',now=now+timedelta(days=10)) is None
        # Ten days exactly is still within the checked window.
        assert recent_message(manager.db,c,1,'0901234567',now=now+timedelta(days=9)) is not None


@pytest.mark.parametrize('state,blocked',[('sent',True),('sending',True),('unknown',True),('failed',False),('prepared',False),('not_requested',False)])
def test_only_sent_and_uncertain_messages_block(app,state,blocked):
    client,connector=setup_send(app);send_first(client,connector);second(client);configure(client,2)
    manager=app.extensions['campaign_manager']
    with app.app_context():
        db=manager.db();db.execute('UPDATE message_sends SET state=? WHERE id=1',(state,));db.commit()
        c=db.execute('SELECT * FROM campaigns WHERE id=2').fetchone()
        assert bool(recent_message(manager.db,c,1,'0901234567'))==blocked


def test_phone_or_uid_match_and_phone_snapshot_survives_profile_edit(app):
    client,connector=setup_send(app);send_first(client,connector);second(client);configure(client,2)
    manager=app.extensions['campaign_manager']
    with app.app_context():
        db=manager.db();db.execute("UPDATE contacts SET phone='0912345678' WHERE id=1");db.commit()
        c=db.execute('SELECT * FROM campaigns WHERE id=2').fetchone()
        assert recent_message(manager.db,c,1,'0901234567','different-uid') is not None
        assert recent_message(manager.db,c,1,'different-phone','123456') is not None
        assert recent_message(manager.db,c,1,'different-phone','different-uid') is None


def test_concurrent_campaigns_only_claim_one_message(app):
    client,_=setup_send(app);second(client);configure(client,1);configure(client,2)
    prepare(client);prepare_second(client)
    manager=app.extensions['campaign_manager'];barrier=Barrier(2)
    def claim(campaign_id):
        with app.app_context():
            db=manager.db();g.user=db.execute('SELECT id,name,username FROM users WHERE id=1').fetchone()
            record=db.execute('SELECT * FROM message_sends WHERE campaign_id=?',(campaign_id,)).fetchone()
            barrier.wait(timeout=10)
            try:return manager.claim(campaign_id,record['id'],'send',record)
            except DuplicateMessageBlocked:return False
    with ThreadPoolExecutor(max_workers=2) as pool:assert sorted(pool.map(claim,[1,2]))==[False,True]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(1,)]


def test_scheduler_skips_duplicate_without_lookup_but_keeps_friend_action(app):
    client,connector=setup_send(app);send_first(client,connector);second(client);configure(client,2)
    post(client,'/campaigns/2/schedule',schedule_fields())
    connector.message_action.reset_mock()
    tick(app);tick(app)
    assert not connector.message_action.called
    row=query(app,'SELECT state,message_skip_reason FROM message_sends WHERE campaign_id=2')[0]
    assert row[0]=='not_requested' and 'Không gửi lại' in row[1]
    assert query(app,'SELECT next_message_variant FROM campaigns WHERE id=2')==[(0,)]
    # A second scheduled campaign can still perform its selected friend action.
    post(client,'/campaigns',{'name':'Vừa kết bạn','message':'Tin','tag':'VIP','options_present':'yes','send_message':'yes','send_friend':'yes','friend_message':'Chào'})
    configure(client,3);post(client,'/campaigns/3/schedule',schedule_fields())
    connector.message_action.side_effect=lambda user,account,action,**data: {'state':'resolved','uid':'123456','name':'Lan'} if action=='resolve' else {'state':'friend_requested'}
    tick(app);tick(app)
    assert [call.args[2] for call in connector.message_action.call_args_list]==['resolve','friend']
    assert query(app,'SELECT state,friend_state FROM message_sends WHERE campaign_id=3')==[('not_requested','friend_requested')]


def test_scheduler_rechecks_prepared_message_after_other_campaign_sent(app):
    client,connector=setup_send(app);second(client);configure(client,2);post(client,'/campaigns/2/schedule',schedule_fields())
    tick(app)  # Scheduled preview exists, but no message has been sent.
    send_first(client,connector);connector.message_action.reset_mock()
    tick(app)
    assert not connector.message_action.called
    assert query(app,'SELECT state FROM message_sends WHERE campaign_id=2')==[('not_requested',)]
    assert query(app,'SELECT count(*) FROM campaign_attempts WHERE campaign_id=2')==[(0,)]
    assert not query(app,'SELECT schedule_error FROM campaigns WHERE id=2')[0][0]


def test_configuration_validation_csrf_and_clone_settings(app):
    client,_=setup_send(app)
    assert client.post('/campaigns/1/duplicate-check',data={'duplicate_present':'yes'}).status_code==400
    for days in ('0','-1','3651','1.5',''):
        configure(client,duplicate_days=days)
        assert query(app,'SELECT duplicate_enabled FROM campaigns')==[(0,)]
    configure(client,duplicate_days='14',duplicate_all_accounts='yes')
    post(client,'/campaigns/1/duplicate',{'name':'Copy'})
    assert query(app,'SELECT duplicate_enabled,duplicate_days,duplicate_all_accounts FROM campaigns WHERE id=2')==[(1,14,1)]
    assert 'wizard-duplicates' in client.get('/campaigns/1/duplicate').text
    assert query(app,'SELECT count(*) FROM message_sends')==[(0,)]
