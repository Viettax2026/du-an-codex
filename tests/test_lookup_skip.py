import csv
import io
import sqlite3

import pytest

from app import create_app
from test_campaign_schedule import setup, tick, campaign, moment
from test_message_composer import query, rich
from test_send import setup_send, prepare
from test_workflow import app, post


def add_contact(client,phone='0912345678'):
    post(client,'/contacts',{'name':'Next customer','phone':phone,'tag':'VIP','consent':'on'})


def test_scheduler_skips_missing_numbers_then_sends_all_actions_to_next_recipient(app):
    client,connector=setup(app)
    add_contact(client);add_contact(client,'0923456789')
    post(client,'/campaigns/1/edit',rich('<b>A #{FULL_NAME}</b> | B #{FULL_NAME}',name='Skip missing',tag='VIP',account_id='1',
        options_present='yes',send_message='yes',send_friend='yes',friend_message='Hi #{FULL_NAME}',rename_enabled='yes',rename_template='#{FULL_NAME}'))
    missing={'0901234567','0912345678'}
    def action(user,account,kind,**data):
        if kind=='resolve':
            return {'state':'not_found'} if data['phone'] in missing else {'state':'resolved','uid':'999','name':'Found customer'}
        return {'state':{'send':'sent','friend':'friend_requested','alias':'renamed'}[kind],'message_id':'99'}
    connector.message_action.side_effect=action
    tick(app);tick(app)
    assert campaign(app)['next_message_variant']==0
    skipped=query(app,'SELECT recipient_id,recipient_phone,state,friend_state,alias_state,message,media_id FROM message_sends ORDER BY id')
    assert skipped==[('',phone,'not_requested','not_requested','not_requested','',None) for phone in ['0901234567','0912345678']]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(0,)]
    for _ in range(6):tick(app)
    assert [call.args[2] for call in connector.message_action.call_args_list]==['resolve','resolve','resolve','send','friend','alias']
    assert query(app,'SELECT state,friend_state,alias_state,message FROM message_sends WHERE contact_id=3')==[('sent','friend_requested','renamed','A Found customer')]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(3,)]
    assert campaign(app)['next_message_variant']==1 and not campaign(app)['schedule_error']
    assert campaign(app)['schedule_carry']==0 and campaign(app)['schedule_status']=='Đã xử lý hết data hiện tại'
    assert query(app,"SELECT count(*) FROM campaign_events WHERE kind='lookup_skip'")==[(2,)]
    page=client.get('/campaigns?selected=1').text
    assert 'Bỏ qua 2' in page and 'value="100"' in page and '0901234567' in page
    assert 'không tìm thấy Zalo' in client.get('/campaigns/1/history').text
    assert 'không tìm thấy Zalo' in client.get('/campaigns/1/report').text
    csv_rows=list(csv.DictReader(io.StringIO(client.get('/campaigns/1/report?format=csv').data.decode('utf-8-sig'))))
    assert len([row for row in csv_rows if row['Lý do bỏ qua']])==2


def test_skipped_lookup_is_persistent_not_a_success_and_not_cancellable_as_a_preview(app):
    client,connector=setup(app)
    connector.message_action.return_value={'state':'not_found'};connector.message_action.side_effect=None
    for _ in range(3):tick(app)
    assert connector.message_action.call_count==1
    assert query(app,"SELECT count(*) FROM message_sends WHERE state='sent'")==[(0,)]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(0,)]
    assert campaign(app)['schedule_status']=='Đã xử lý hết data hiện tại'
    page=client.get('/campaigns?selected=1').text
    assert 'Bỏ qua 1' in page and 'value="100"' in page
    assert 'Hủy bản xem trước' not in client.get('/campaigns/1').text
    post(client,'/campaigns/1/cancel-send/1')
    assert query(app,'SELECT count(*) FROM message_sends')==[(1,)]
    assert campaign(app)['schedule_enabled']==1
    for action,confirmation in [('send','confirm_send'),('friend','confirm_friend'),('alias','confirm_alias')]:
        post(client,f'/campaigns/1/{action}/1',{confirmation:'yes'})
    assert connector.message_action.call_count==1
    restarted=create_app({'TESTING':True,'DATABASE':app.config['DATABASE'],'SECRET_KEY':'test-only','ZALO_QR_ENABLED':True})
    restored=restarted.extensions['zalo_connector'];restored.status=connector.status;restored.message_action=connector.message_action
    tick(restarted)
    assert restored.message_action.call_count==1
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(0,)]


@pytest.mark.parametrize('result',[{'state':'failed'}, {'state':'resolved','uid':'bad'}, None, RuntimeError('private failure')])
def test_operational_lookup_failures_do_not_skip_customers_or_leak_errors(app,result):
    client,connector=setup(app);add_contact(client)
    connector.message_action.side_effect=result if isinstance(result,Exception) else None
    connector.message_action.return_value=result
    tick(app)
    assert campaign(app)['schedule_error'].startswith('Không thể tra cứu Zalo')
    assert 'private failure' not in campaign(app)['schedule_error']
    assert query(app,'SELECT count(*) FROM message_sends')==[(0,)]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(0,)]
    assert connector.message_action.call_count==1


def test_skip_rechecks_pause_and_consent_after_lookup(app):
    client,connector=setup(app)
    def lookup(*args,**kwargs):
        with sqlite3.connect(app.config['DATABASE']) as db:
            db.execute('UPDATE campaigns SET paused=1 WHERE id=1')
        return {'state':'not_found'}
    connector.message_action.side_effect=lookup
    tick(app)
    assert query(app,'SELECT count(*) FROM message_sends')==[(0,)]
    assert not campaign(app)['schedule_error']
    post(client,'/campaigns/1/pause',{'paused':'0'})
    def withdrawn(*args,**kwargs):
        with sqlite3.connect(app.config['DATABASE']) as db:
            db.execute('UPDATE contacts SET consent=0 WHERE id=1')
        return {'state':'not_found'}
    connector.message_action.side_effect=withdrawn
    tick(app)
    assert query(app,'SELECT count(*) FROM message_sends')==[(0,)]


def test_manual_missing_lookup_records_skip_and_selects_next_customer(app):
    client,connector=setup_send(app);add_contact(client)
    connector.message_action.return_value={'state':'not_found'}
    response=prepare(client)
    assert response.status_code==200 and 'Đã bỏ qua số không tìm thấy Zalo' in response.text
    assert '<option value="2">Next customer' in response.text
    assert '<option value="1">Lan ·' not in response.text
    assert query(app,'SELECT scheduled,recipient_id,state FROM message_sends')==[(0,'','not_requested')]
    assert campaign(app)['next_message_variant']==0
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(0,)]
    prepare(client)
    assert connector.message_action.call_count==1
    connector.message_action.return_value={'state':'resolved','uid':'123','name':'Found'}
    post(client,'/campaigns/1/prepare-send',{'contact_id':'2','account_id':'1'})
    assert query(app,'SELECT contact_id,state FROM message_sends ORDER BY id')==[(1,'not_requested'),(2,'prepared')]


def test_upgrade_resumes_only_legacy_lookup_blocks_without_replaying_sent_actions(app):
    client,connector=setup(app);tick(app);tick(app)
    add_contact(client)
    old_error='Không tìm được Zalo của 0912345678. Kiểm tra data rồi lưu lại lịch.'
    for label in ['Paused','Other error','Disabled']:
        post(client,'/campaigns',{'name':label,'message':'Hi','tag':'VIP'})
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE campaigns SET schedule_error=?,schedule_status='Cần kiểm tra' WHERE id=1",(old_error,))
        db.execute('UPDATE campaigns SET schedule_enabled=1,paused=1,schedule_error=? WHERE id=2',(old_error,))
        db.execute("UPDATE campaigns SET schedule_enabled=1,schedule_error='Kết quả chưa xác định' WHERE id=3")
        db.execute('UPDATE campaigns SET schedule_enabled=0,schedule_error=? WHERE id=4',(old_error,))
    config={'TESTING':True,'DATABASE':app.config['DATABASE'],'SECRET_KEY':'test-only','ZALO_QR_ENABLED':True}
    restarted=create_app(config);create_app(config)
    assert query(app,'SELECT schedule_enabled,paused,schedule_error FROM campaigns ORDER BY id')==[(1,0,''),(1,1,''),(1,0,'Kết quả chưa xác định'),(0,0,old_error)]
    assert query(app,"SELECT count(*) FROM campaign_events WHERE kind='schedule_resume'")==[(2,)]
    connector.message_action.reset_mock();connector.message_action.side_effect=None;connector.message_action.return_value={'state':'not_found'}
    restored=restarted.extensions['zalo_connector'];restored.status=connector.status;restored.message_action=connector.message_action
    tick(restarted)
    assert restored.message_action.call_count==1 and restored.message_action.call_args.kwargs['phone']=='0912345678'
    assert query(app,'SELECT contact_id,state FROM message_sends ORDER BY id')==[(1,'sent'),(2,'not_requested')]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(1,)]
