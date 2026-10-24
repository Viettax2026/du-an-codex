import sqlite3

import pytest

from test_workflow import app, post, register, token
from test_send import setup_send, prepare


def query(app,sql,args=()):
    with sqlite3.connect(app.config['DATABASE']) as connection:
        return connection.execute(sql,args).fetchall()


def exclusion_list(client,**values):
    response=client.post('/campaign-exclusions/lists',data={'csrf':token(client),'name':'Do not contact','phones':'0901234567',**values})
    assert response.status_code==200,response.text
    return response.json['id']


def rule(client,**values):
    response=client.post('/campaign-exclusions/rules',data={'csrf':token(client),'name':'Prior contact','sent':'yes',**values})
    assert response.status_code==201,response.text
    return response.json['id']


def select(client,campaign=1,rule_id='',lists=()):
    return post(client,f'/campaigns/{campaign}/exclusions',{'exclusions_present':'yes','exclusion_rule_group_id':str(rule_id),
                                                        'exclusion_list_ids':[str(value) for value in lists]})


def test_phone_exclusion_is_applied_to_simulation_preview_and_list_counts(app):
    client,connector=setup_send(app)
    item=exclusion_list(client,phones='+84 901 234 567\n0901234567')
    assert query(app,'SELECT kind,value FROM exclusion_list_entries')==[('phone','0901234567')]
    select(client,lists=[item])
    assert 'Gửi thử cho 0 khách hàng' in client.get('/campaigns/1').text
    assert '0/0' in client.get('/campaigns').text
    connector.message_action.reset_mock()
    assert client.post('/campaigns/1/prepare-send',data={'csrf':token(client),'contact_id':'1','account_id':'1'}).status_code==400
    post(client,'/campaigns/1')
    assert query(app,'SELECT count(*) FROM deliveries')==[(0,)]
    assert query(app,'SELECT count(*) FROM message_sends')==[(0,)]
    assert connector.message_action.call_count==0
    select(client)  # Explicitly clearing selections restores eligible consented members.
    assert 'Gửi thử cho 1 khách hàng' in client.get('/campaigns/1').text


def test_uid_is_checked_after_resolution_even_when_contact_has_no_saved_uid(app):
    client,connector=setup_send(app)
    item=exclusion_list(client,phones='',uids='123456')
    select(client,lists=[item])
    assert query(app,'SELECT zalo_id FROM contacts')==[('',)]
    response=client.post('/campaigns/1/prepare-send',data={'csrf':token(client),'contact_id':'1','account_id':'1'})
    assert response.status_code==400 and 'loại trừ' in response.text
    assert query(app,'SELECT count(*) FROM message_sends')==[(0,)]
    assert connector.message_action.call_args.args[-1]=='resolve'


@pytest.mark.parametrize('action,confirmation',[('send','confirm_send'),('friend','confirm_friend'),('alias','confirm_alias')])
def test_exclusions_added_after_preview_block_all_pending_actions(app,action,confirmation):
    client,connector=setup_send(app)
    post(client,'/campaigns/1/edit',{'name':'All actions','message':'Hello','tag':'VIP','options_present':'yes',
         'send_message':'yes','send_friend':'yes','friend_message':'Hi','rename_enabled':'yes','rename_template':'#{FULL_NAME}'})
    prepare(client)
    item=exclusion_list(client,phones='',uids='123456')
    select(client,lists=[item])
    connector.message_action.reset_mock()
    response=client.post(f'/campaigns/1/{action}/1',data={'csrf':token(client),confirmation:'yes'})
    assert response.status_code==400
    assert connector.message_action.call_count==0
    assert query(app,'SELECT state,friend_state,alias_state FROM message_sends')==[('prepared','prepared','prepared')]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(0,)]
    assert 'Các hành động chưa gửi đã bị chặn' in client.get('/campaigns/1').text


def test_list_changes_between_preflight_and_claim_are_rechecked_atomically(app):
    client,connector=setup_send(app);prepare(client)
    item=exclusion_list(client,phones='0912345678')
    select(client,lists=[item])
    def connected(*args):
        with sqlite3.connect(app.config['DATABASE']) as db:
            db.execute("INSERT OR IGNORE INTO exclusion_list_entries VALUES (?,'uid','123456')",(item,))
        return {'state':'connected'}
    connector.status.side_effect=connected
    connector.message_action.reset_mock()
    response=client.post('/campaigns/1/send/1',data={'csrf':token(client),'confirm_send':'yes'})
    assert response.status_code==400
    assert query(app,'SELECT state FROM message_sends')==[('prepared',)]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(0,)]
    assert connector.message_action.call_count==0


@pytest.mark.parametrize('flag,column,confirmed',[('sent','state','sent'),('friend_requested','friend_state','friend_requested'),('renamed','alias_state','renamed')])
def test_history_rules_count_confirmed_other_campaigns_only(app,flag,column,confirmed):
    client,connector=setup_send(app);prepare(client)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute(f'UPDATE message_sends SET {column}=? WHERE id=1',(confirmed,))
    post(client,'/campaigns',{'name':'Second campaign','message':'Hello','tag':'VIP'})
    group=rule(client,name='Confirmed '+flag,sent='',**{flag:'yes'}) if flag!='sent' else rule(client)
    select(client,campaign=2,rule_id=group)
    assert 'Gửi thử cho 0 khách hàng' in client.get('/campaigns/2').text
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute(f"UPDATE message_sends SET {column}='unknown' WHERE id=1")
    assert 'Gửi thử cho 1 khách hàng' in client.get('/campaigns/2').text


def test_rule_does_not_interrupt_other_actions_within_same_campaign(app):
    client,connector=setup_send(app)
    post(client,'/campaigns/1/edit',{'name':'All actions','message':'Hello','tag':'VIP','options_present':'yes',
         'send_message':'yes','send_friend':'yes','friend_message':'Hi','rename_enabled':'yes','rename_template':'#{FULL_NAME}'})
    group=rule(client,friend_requested='yes',renamed='yes');select(client,rule_id=group);prepare(client)
    for action,confirmation,state in [('send','confirm_send','sent'),('friend','confirm_friend','friend_requested'),('alias','confirm_alias','renamed')]:
        connector.message_action.return_value={'state':state,'message_id':'confirmed'}
        assert post(client,f'/campaigns/1/{action}/1',{confirmation:'yes'}).status_code==200
    assert query(app,'SELECT state,friend_state,alias_state FROM message_sends')==[('sent','friend_requested','renamed')]


def test_group_membership_is_dynamic_and_duplicate_preserves_exclusions(app):
    client,connector=setup_send(app)
    client.get('/data-groups')
    group_id=query(app,"SELECT id FROM data_groups WHERE name='VIP'")[0][0]
    group=rule(client,sent='',data_group_id=str(group_id))
    item=exclusion_list(client,phones='0912345678')
    select(client,rule_id=group,lists=[item])
    assert 'Gửi thử cho 0 khách hàng' in client.get('/campaigns/1').text
    post(client,'/campaigns/1/duplicate',{'name':'Copy'})
    assert query(app,'SELECT rule_group_id FROM campaign_exclusion_rules WHERE campaign_id=2')==[(group,)]
    assert query(app,'SELECT list_id FROM campaign_exclusion_lists WHERE campaign_id=2')==[(item,)]
    assert 'Gửi thử cho 0 khách hàng' in client.get('/campaigns/2').text
    assert query(app,'SELECT count(*) FROM message_sends')==[(0,)]


def test_cross_owner_ids_and_invalid_edits_do_not_change_settings(app):
    first,connector=setup_send(app)
    item=exclusion_list(first);group=rule(first)
    other=app.test_client();register(other,'other')
    post(other,'/campaigns',{'name':'Other campaign','message':'Hello'})
    assert other.get('/campaigns/1/exclusions').status_code==404
    response=select(other,campaign=2,rule_id=group,lists=[item])
    assert 'không thuộc tài khoản' in response.text
    assert query(app,'SELECT count(*) FROM campaign_exclusion_lists WHERE campaign_id=2')==[(0,)]
    assert other.post('/campaign-exclusions/lists',data={'csrf':token(other),'list_id':str(item),'name':'Hijack','phones':'0912345678'}).status_code==404
    assert first.post('/campaign-exclusions/rules',data={'name':'No CSRF','sent':'yes'}).status_code==400
    response=first.post('/campaign-exclusions/lists',data={'csrf':token(first),'list_id':str(item),'name':'Changed','phones':'invalid'})
    assert response.status_code==400
    assert query(app,'SELECT name FROM exclusion_lists WHERE id=?',(item,))==[('Do not contact',)]
    assert query(app,'SELECT value FROM exclusion_list_entries WHERE list_id=?',(item,))==[('0901234567',)]
    # Invalid selections roll back a newly created campaign too.
    post(other,'/campaigns',{'name':'Must not persist','message':'Hello','exclusions_present':'yes','exclusion_list_ids':[str(item)]})
    assert query(app,"SELECT count(*) FROM campaigns WHERE name='Must not persist'")==[(0,)]


def test_importing_or_appending_does_not_reenable_previously_revoked_consent(app):
    client=app.test_client();register(client)
    post(client,'/contacts',{'name':'Opted out','phone':'0901234567','tag':'VIP'})
    post(client,'/campaigns',{'name':'Direct list','message':'Hello','phones':'0901234567\n0912345678','phones_consent':'yes'})
    assert query(app,'SELECT phone,consent FROM contacts ORDER BY id')==[('0901234567',0),('0912345678',1)]
    post(client,'/campaigns/1/data',{'phones':'0901234567','consent':'yes'})
    assert query(app,"SELECT consent FROM contacts WHERE phone='0901234567'")==[(0,)]
    post(client,'/campaigns/1')
    assert query(app,'SELECT contact_id FROM deliveries')==[(2,)]


def test_appending_data_keeps_excluded_group_members_in_the_underlying_list(app):
    client,connector=setup_send(app)
    item=exclusion_list(client);select(client,lists=[item])
    post(client,'/campaigns/1/data',{'phones':'0912345678','consent':'yes'})
    assert query(app,'SELECT contact_id FROM campaign_contacts WHERE campaign_id=1 ORDER BY contact_id')==[(1,),(2,)]
    assert 'Gửi thử cho 1 khách hàng' in client.get('/campaigns/1').text
    select(client)
    assert 'Gửi thử cho 2 khách hàng' in client.get('/campaigns/1').text
