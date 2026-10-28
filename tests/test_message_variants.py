import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app import create_app
from rich_message import read_message, render_message
from test_workflow import app, post, token
from test_send import setup_send, prepare
from test_message_composer import rich, query


def test_outer_pipes_escaping_personalized_pipes_and_rich_offsets():
    message,html=read_message(rich(r'<b>😊 Chào {{name}}</b> | <i>Dịch vụ \| kế toán</i> | {a|b}'))
    contact={'name':'Lan | Thu'}
    assert render_message(message,html,contact,variant_index=0)==('😊 Chào Lan | Thu',[{'start':0,'len':17,'st':'b'}])
    assert render_message(message,html,contact,variant_index=1)==('Dịch vụ | kế toán',[{'start':0,'len':17,'st':'i'}])
    assert render_message(message,html,contact,variant_index=2) in [('a',[]),('b',[])]
    assert render_message(message,html,contact,variant_index=3)==render_message(message,html,contact)
    message,html=read_message(rich(r'<b>A \| B | C</b>'))
    assert render_message(message,html,{},variant_index=0)==('A | B',[{'start':0,'len':5,'st':'b'}])
    assert render_message(message,html,{},variant_index=1)==('C',[{'start':0,'len':1,'st':'b'}])


def test_each_variant_has_own_unicode_limit_and_empty_parts_are_rejected():
    raw='😊'*1000+' | '+'a'*2000
    message,html=read_message({'message':raw})
    assert render_message(message,html,{},variant_index=1)[0]=='a'*2000
    for raw in ('A |', '| B', 'A |  | B', '|'.join(['A']*21), 'A | '+'😊'*1001):
        with pytest.raises(ValueError):read_message({'message':raw})


def test_preview_all_variants_simulation_and_persistent_rotation(app):
    client,connector=setup_send(app)
    for i in (2,3):post(client,'/contacts',{'name':f'Khách {i}','phone':f'090123456{i}','tag':'VIP','consent':'on'})
    post(client,'/campaigns/1/content',rich('<b>Chào {{name}}</b> | <i>Dịch vụ {{name}}</i>'))
    preview=post(client,'/composer/preview',rich('<b>Chào {{name}}</b> | <i>Dịch vụ {{name}}</i>')).json
    assert [v['html'] for v in preview['variants']]==['<strong>Chào Lan</strong>','<em>Dịch vụ Lan</em>']
    assert query(app,'SELECT next_message_variant FROM campaigns')[0][0]==0
    post(client,'/campaigns/1')
    assert [r[0] for r in query(app,'SELECT message FROM deliveries ORDER BY id')]==['Chào Lan','Dịch vụ Khách 2','Chào Khách 3']
    assert query(app,'SELECT next_message_variant FROM campaigns')[0][0]==0
    prepare(client);prepare(client)  # Duplicate submission cannot consume a variant.
    post(client,'/campaigns/1/prepare-send',{'contact_id':'2','account_id':'1'})
    # Reload the application against the same database before preparing the next recipient.
    restarted=create_app({'TESTING':True,'DATABASE':app.config['DATABASE'],'SECRET_KEY':'test-only','ZALO_QR_ENABLED':True})
    restarted.extensions['zalo_connector'].message_action=connector.message_action
    new_client=restarted.test_client()
    post(new_client,'/login',{'username':'an01','password':'secure-password'})
    post(new_client,'/campaigns/1/prepare-send',{'contact_id':'3','account_id':'1'})
    rows=query(app,'SELECT message,message_styles FROM message_sends ORDER BY id')
    assert [r[0] for r in rows]==['Chào Lan','Dịch vụ Khách 2','Chào Khách 3']
    assert [json.loads(r[1])[0]['st'] for r in rows]==['b','i','b']
    assert query(app,'SELECT next_message_variant FROM campaigns')[0][0]==3
    post(client,'/campaigns/1/duplicate',{'name':'Bản sao'})
    assert query(app,'SELECT next_message_variant FROM campaigns WHERE id=2')[0][0]==0
    # Saving unchanged content must not restart the rotation.
    post(client,'/campaigns/1/content',rich('<b>Chào {{name}}</b> | <i>Dịch vụ {{name}}</i>'))
    assert query(app,'SELECT next_message_variant FROM campaigns WHERE id=1')[0][0]==3
    post(client,'/campaigns/1/content',rich('Mới A | Mới B'))
    assert query(app,'SELECT next_message_variant FROM campaigns WHERE id=1')[0][0]==0
    assert query(app,'SELECT message FROM message_sends WHERE id=1')[0][0]=='Chào Lan'
    connector.message_action.reset_mock();connector.message_action.return_value={'state':'sent','message_id':'123'}
    post(client,'/campaigns/1/send/1',{'confirm_send':'yes'})
    assert connector.message_action.call_args.kwargs['message']=='Chào Lan'
    assert query(app,'SELECT next_message_variant FROM campaigns WHERE id=1')[0][0]==0


def test_failed_personalization_and_cancellation_do_not_rewrite_other_previews(app):
    client,connector=setup_send(app)
    post(client,'/campaigns/1/content',rich('#{EMAIL} | B'))
    response=prepare(client)
    assert 'Thiếu thông tin EMAIL' in response.text
    assert query(app,'SELECT next_message_variant FROM campaigns')[0][0]==0
    assert query(app,'SELECT id FROM message_sends')==[]
    post(client,'/campaigns/1/content',rich('A | B'))
    prepare(client)
    assert query(app,'SELECT next_message_variant FROM campaigns')[0][0]==1
    post(client,'/campaigns/1/cancel-send/1')
    prepare(client)
    assert query(app,'SELECT message FROM message_sends')[0][0]=='B'
    assert query(app,'SELECT next_message_variant FROM campaigns')[0][0]==2


def test_concurrent_duplicate_preview_advances_only_once(app):
    owner,connector=setup_send(app)
    post(owner,'/campaigns/1/content',rich('A | B'))
    barrier=Barrier(2)
    def resolve(*args,**kwargs):
        barrier.wait(timeout=10)
        return {'state':'resolved','uid':'123456','name':'Lan Zalo'}
    connector.message_action.side_effect=resolve
    def worker(_):
        client=app.test_client()
        post(client,'/login',{'username':'an01','password':'secure-password'})
        return client.post('/campaigns/1/prepare-send',data={'csrf':token(client),'contact_id':'1','account_id':'1'}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(worker,range(2)))==[302,302]
    assert query(app,'SELECT message FROM message_sends')==[('A',)]
    assert query(app,'SELECT next_message_variant FROM campaigns')[0][0]==1
