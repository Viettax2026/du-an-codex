import json
import sqlite3

from test_workflow import app, post, register, token


def query(app,sql,args=()):
    with sqlite3.connect(app.config['DATABASE']) as connection:
        return connection.execute(sql,args).fetchall()


def snapshot(client,group_id):
    return client.post('/campaigns/group-snapshot',data={'csrf':token(client),'group_id':str(group_id)})


def seed_group(app,count=2805,consent=1):
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.executemany('INSERT INTO contacts(user_id,name,phone,tag,consent) VALUES (1,?,?,?,?)',
                       ((f'Customer {index}',f'090{index:07d}','Large group',consent) for index in range(1,count+1)))


def test_large_group_is_copied_once_and_can_be_reopened_and_edited(app):
    client=app.test_client();register(client);seed_group(app)
    catalog=client.get('/campaigns/group-options').json['groups']
    group=catalog[0]
    assert group['total']==2805 and group['eligible']==2805
    selected=snapshot(client,group['id'])
    assert selected.status_code==200 and selected.json['total']==2805
    ids=[row['id'] for row in selected.json['rows']]
    # Added after choosing the group: this person must never join the snapshot.
    post(client,'/contacts',{'name':'Later member','phone':'0987654321','tag':'Large group','consent':'on'})
    response=post(client,'/campaigns',{'name':'Large snapshot','message':'Hello','data_mode':'direct',
                                     'source_contact_ids':json.dumps(ids)})
    assert 'Large snapshot' in response.text
    assert query(app,'SELECT audience_mode FROM campaigns')==[('list',)]
    assert query(app,'SELECT count(*) FROM campaign_contacts')==[(2805,)]
    assert query(app,'SELECT count(*) FROM campaign_contacts WHERE contact_id=2806')==[(0,)]
    editing=client.get('/campaigns/1/edit')
    assert editing.status_code==200 and 'data-initial-group-snapshot' in editing.text
    assert 'Customer 2805' in editing.text
    post(client,'/campaigns/1/edit',{'name':'Edited snapshot','message':'Updated','data_mode':'direct','source_contact_ids':json.dumps(ids)})
    assert query(app,'SELECT name FROM campaigns')==[('Edited snapshot',)]
    assert query(app,'SELECT count(*) FROM campaign_contacts')==[(2805,)]


def test_empty_archived_and_foreign_groups_cannot_be_copied(app):
    owner=app.test_client();register(owner)
    post(owner,'/contacts',{'name':'No consent','phone':'0901234567','tag':'Not eligible'})
    group=owner.get('/campaigns/group-options').json['groups'][0]
    assert group['total']==1 and group['eligible']==0
    assert snapshot(owner,group['id']).status_code==400
    post(owner,'/campaigns',{'name':'Empty must not select all','message':'Hello','data_mode':'direct','source_contact_ids':'[]'})
    assert query(app,'SELECT count(*) FROM campaigns')==[(0,)]
    other=app.test_client();register(other,'other')
    assert other.get('/campaigns/group-options').json['groups']==[]
    assert snapshot(other,group['id']).status_code==404
    post(owner,'/data-groups/delete',{'group':'Not eligible','confirm_delete':'yes'})
    assert owner.get('/campaigns/group-options').json['groups']==[]
    assert snapshot(owner,group['id']).status_code==404
    assert owner.post('/campaigns/group-snapshot',data={'group_id':str(group['id'])}).status_code==400


def test_snapshot_ids_are_private_validated_and_preserve_withdrawn_consent(app):
    owner=app.test_client();register(owner)
    post(owner,'/contacts',{'name':'Original','phone':'0901234567','tag':'VIP','consent':'on'})
    group=owner.get('/campaigns/group-options').json['groups'][0]
    ids=[row['id'] for row in snapshot(owner,group['id']).json['rows']]
    post(owner,'/contacts/1/consent')
    post(owner,'/campaigns',{'name':'Consent revoked','message':'Hello','data_mode':'direct','source_contact_ids':json.dumps(ids)})
    assert query(app,'SELECT consent FROM contacts WHERE id=1')==[(0,)]
    assert 'Gửi thử cho 0 khách hàng' in owner.get('/campaigns/1').text
    other=app.test_client();register(other,'other')
    for raw in [json.dumps(ids),'not json','[true]','[1.2]','{"id":1}','[999999999999999999999999]']:
        post(other,'/campaigns',{'name':'Must not create','message':'Hello','data_mode':'direct','source_contact_ids':raw})
    assert query(app,'SELECT count(*) FROM campaigns WHERE user_id=2')==[(0,)]
    assert query(app,'SELECT count(*) FROM contacts WHERE user_id=2')==[(0,)]


def test_multiple_groups_and_manual_numbers_are_deduplicated(app):
    client=app.test_client();register(client)
    for name,phone in [('A','0901234567'),('B','0912345678')]:
        post(client,'/contacts',{'name':name,'phone':phone,'tag':'VIP','consent':'on'})
    group=client.get('/campaigns/group-options').json['groups'][0]
    ids=[row['id'] for row in snapshot(client,group['id']).json['rows']]
    post(client,'/campaigns',{'name':'Mixed','message':'Hello','data_mode':'direct','source_contact_ids':json.dumps(ids+ids),
                            'phones':'0901234567\n0923456789','phones_consent':'yes'})
    assert query(app,'SELECT count(*) FROM campaign_contacts')==[(3,)]
    assert query(app,'SELECT count(*) FROM contacts')==[(3,)]
    assert query(app,"SELECT name FROM contacts WHERE phone='0901234567'")==[('A',)]


def test_copying_a_cloned_group_uses_shared_membership_and_live_group_mode_stays_dynamic(app):
    client=app.test_client();register(client)
    post(client,'/contacts',{'name':'A','phone':'0901234567','tag':'Original','consent':'on'})
    client.get('/campaigns/group-options')
    post(client,'/data-groups/duplicate',{'group':'Original','name':'Clone'})
    groups=client.get('/campaigns/group-options').json['groups']
    clone=next(group for group in groups if group['name']=='Clone')
    assert clone['eligible']==1
    assert snapshot(client,clone['id']).json['rows'][0]['id']==1
    post(client,'/campaigns',{'name':'Dynamic','message':'Hello','data_mode':'group','tag':'Original'})
    post(client,'/contacts',{'name':'B','phone':'0912345678','tag':'Original','consent':'on'})
    assert query(app,'SELECT audience_mode FROM campaigns')==[('group',)]
    assert 'Gửi thử cho 2 khách hàng' in client.get('/campaigns/1').text


def test_group_limits_return_an_error_without_silently_truncating(app):
    client=app.test_client();register(client);seed_group(app,10001)
    group=client.get('/campaigns/group-options').json['groups'][0]
    response=snapshot(client,group['id'])
    assert response.status_code==400 and '10.000' in response.json['error']
    assert query(app,'SELECT count(*) FROM campaign_contacts')==[(0,)]


def test_large_groups_also_work_through_legacy_form_and_append_menu(app):
    client=app.test_client();register(client);seed_group(app)
    post(client,'/campaigns',{'name':'Legacy group copy','message':'Hello','data_mode':'direct','source_tags':['Large group']})
    assert query(app,'SELECT count(*) FROM campaign_contacts WHERE campaign_id=1')==[(2805,)]
    post(client,'/campaigns',{'name':'Append group','message':'Hello','tag':'Other'})
    post(client,'/campaigns/2/data',{'source_tag':'Large group','consent':'yes'})
    assert query(app,'SELECT count(*) FROM campaign_contacts WHERE campaign_id=2')==[(2805,)]
    assert query(app,'SELECT audience_mode FROM campaigns WHERE id=2')==[('list',)]
