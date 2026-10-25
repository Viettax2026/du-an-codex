import io
import json
import sqlite3

import pytest
from PIL import Image

from rich_message import parse_html, read_message, render_message, display_message, load_styles
from test_workflow import app, post, register, token
from test_send import setup_send, prepare


def query(app, sql, params=()):
    with sqlite3.connect(app.config['DATABASE']) as db:
        return db.execute(sql, params).fetchall()


def rich(html, **extra):
    return dict(message='ignored plain mirror',rich_message='yes',message_html=html,**extra)


def png():
    data=io.BytesIO();Image.new('RGB',(3,3),'red').save(data,format='PNG');data.seek(0)
    return data,'bao-gia.png'


def test_rich_sanitization_and_canonical_roundtrip():
    html='<script>alert(1)</script><div onclick="bad()"><b>Xin chào</b> <i>bạn</i></div><ul><li><b>Kế toán</b> thuế</li><li>BHXH</li></ul><img src=x onerror=bad()><p>Kết thúc</p>'
    message,canonical=read_message(rich(html))
    assert message=='Xin chào bạn\nKế toán thuế\nBHXH\nKết thúc'
    assert all(x not in canonical for x in ('script','onclick','img','onerror'))
    assert read_message(rich(canonical))==(message,canonical)
    assert '<strong>Xin chào</strong>' in canonical
    assert canonical.count('data-style="lst_1"')==2
    assert parse_html('<div>A</div><div><br></div><div>B</div>')[0]=='A\n\nB'


def test_personalization_unicode_and_safe_preview():
    message,html=read_message(rich('😊 <b>Xin chào {{na</b><i>me}}</i> <u>Viettax</u>'))
    text,styles=render_message(message,html,{'name':'Lan <img src=x>'})
    assert text=='😊 Xin chào Lan <img src=x> Viettax'
    bold=next(s for s in styles if s['st']=='b')
    assert bold=={'start':3,'len':24,'st':'b'}
    assert next(s for s in styles if s['st']=='i')['len']==15
    preview=display_message(text,json.dumps(styles))
    assert '<img' not in preview and '&lt;img src=x&gt;' in preview
    assert load_styles(json.dumps(styles),text)==styles
    with pytest.raises(ValueError):load_styles('[{"start":1,"len":1,"st":"b"}]',text)
    with pytest.raises(ValueError):read_message({'message':'😊'*1001})
    with pytest.raises(ValueError):render_message(message,html,{'name':'a'*2000})


def test_templates_private_csrf_update_delete_and_literal_content(app):
    owner=app.test_client();register(owner)
    data=rich('<b>Chào {{name}}</b> | {a|b}',name='Kế toán',group_name='Viettax')
    assert owner.post('/message-templates',data=data).status_code==400
    result=post(owner,'/message-templates',data);assert result.status_code==200
    template_id=result.json['id']
    assert owner.get('/message-templates').json['items'][0]['message']=='Chào {{name}} | {a|b}'
    other=app.test_client();register(other,'other')
    assert other.get('/message-templates').json['items']==[]
    assert post(other,'/message-templates',dict(data,template_id=template_id)).status_code==404
    assert post(other,f'/message-templates/{template_id}/delete').status_code==404
    post(owner,'/message-templates',rich('<u>Nội dung sửa</u>',name='Sửa mẫu',group_name='Thuế',template_id=template_id))
    items=owner.get('/message-templates').json['items'];assert len(items)==1 and items[0]['message_html']=='<u>Nội dung sửa</u>'
    result=post(owner,'/composer/preview',rich('<b>Chào {{name}}</b> | {a|b}'))
    assert result.json['html']=='<strong>Chào Lan</strong>'
    assert result.json['variants'][1]['html'] in ('a','b')
    assert post(owner,f'/message-templates/{template_id}/delete').json=={'deleted':True}
    assert owner.get('/message-templates').json['items']==[]


def test_wizard_media_rich_edit_duplicate_and_simulation(app):
    client=app.test_client();register(client)
    post(client,'/contacts',dict(name='Lan',phone='0901234567',tag='VIP',consent='on'))
    result=post(client,'/campaigns',rich('<b>Xin chào {{name}}</b> 😊',name='Chiến dịch',tag='VIP',media_present='yes',media_mode='send',media=png()))
    assert 'Đã tạo chiến dịch' in result.text
    message,html,media_id=query(app,'SELECT message,message_html,media_id FROM campaigns')[0]
    assert message=='Xin chào {{name}} 😊' and html=='<strong>Xin chào {{name}}</strong> 😊' and media_id
    manager=app.extensions['campaign_manager'];assert len(list(manager.media_root.iterdir()))==1
    result=client.get('/composer/media').json
    assert len(result['items'])==1 and result['items'][0]['id']==media_id
    assert client.get(result['items'][0]['preview_url']).status_code==200
    # Foreign library media cannot be attached, and a failed edit retains existing content/file.
    other=app.test_client();register(other,'other');post(other,'/media/upload',{'file':png()})
    other_id=query(app,'SELECT id FROM campaign_media WHERE user_id=2')[0][0]
    result=post(client,'/campaigns/1/edit',rich('<i>Không lưu</i>',name='Chiến dịch',tag='VIP',library_media_id=str(other_id),media_present='yes',media_mode='send'))
    assert 'Không tìm thấy media' in result.text
    assert query(app,'SELECT message_html,media_id FROM campaigns WHERE id=1')[0]==(html,media_id)
    post(client,'/campaigns/1/duplicate',{'name':'Bản sao'})
    assert query(app,'SELECT message_html,media_id FROM campaigns WHERE id=2')[0]==(html,media_id)
    post(client,'/campaigns/1')
    message,styles=query(app,'SELECT message,message_styles FROM deliveries')[0]
    assert message=='Xin chào Lan 😊' and json.loads(styles)==[{'start':0,'len':12,'st':'b'}]
    post(client,'/campaigns/1/content',rich('<i>Nội dung mới</i>',media_present='yes',media_mode='none'))
    assert query(app,'SELECT message_html,media_id FROM campaigns WHERE id=1')[0]==('<em>Nội dung mới</em>',None)
    assert query(app,'SELECT message_styles FROM deliveries')[0][0]==styles
    assert len(list(manager.media_root.iterdir()))==2  # Detaching never deletes the library file.


@pytest.mark.parametrize('with_image',[False,True])
def test_rich_send_uses_frozen_styles_even_after_content_edit(app,with_image):
    client,connector=setup_send(app)
    attachment_fields=dict(media_present='yes',media_mode='send',media=png()) if with_image else {}
    post(client,'/campaigns/1/content',rich('😊 <b>Chào {{name}}</b>',**attachment_fields))
    prepare(client)
    text,styles=query(app,'SELECT message,message_styles FROM message_sends')[0]
    assert text=='😊 Chào Lan' and json.loads(styles)==[{'start':3,'len':8,'st':'b'}]
    post(client,'/campaigns/1/content',rich('<i>Khác</i>'))
    connector.message_action.reset_mock();connector.message_action.return_value={'state':'sent','message_id':'123'}
    post(client,'/campaigns/1/send/1',{'confirm_send':'yes'})
    args=connector.message_action.call_args.kwargs
    assert {key:value for key,value in args.items() if key!='attachment'}=={'uid':'123456','message':'😊 Chào Lan','styles':[{'start':3,'len':8,'st':'b'}]}
    assert ('attachment' in args)==with_image
    if with_image:
        assert args['attachment']['filename']=='bao-gia.png' and args['attachment']['width']==3
    post(client,'/campaigns/1/send/1',{'confirm_send':'yes'})
    assert connector.message_action.call_count==1


def test_new_upload_rolled_back_on_late_error(app,monkeypatch):
    client=app.test_client();register(client)
    manager=app.extensions['campaign_manager']
    def failure(*args,**kwargs):
        raise ValueError('Không lưu được sự kiện')
    monkeypatch.setattr(manager,'event',failure)
    result=post(client,'/campaigns',rich('<b>Tin nhắn</b>',name='Không lưu',media_present='yes',media_mode='send',media=png()))
    assert 'Không lưu được sự kiện' in result.text
    assert query(app,'SELECT id FROM campaigns')==[] and query(app,'SELECT id FROM campaign_media')==[]
    assert list(manager.media_root.iterdir())==[]


def test_invalid_snapshot_styles_block_before_claim(app):
    client,connector=setup_send(app)
    prepare(client)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('UPDATE message_sends SET message_styles=?', ('[{"start":0,"len":10000,"st":"b"}]',))
    connector.message_action.reset_mock()
    response=post(client,'/campaigns/1/send/1',{'confirm_send':'yes'})
    assert response.status_code==400 and 'Định dạng bản xem trước không hợp lệ' in response.text
    assert not connector.message_action.called
    assert query(app,'SELECT state FROM message_sends')[0][0]=='prepared'
    assert query(app,'SELECT id FROM campaign_attempts')==[]
