import io
import sqlite3
from datetime import datetime, timezone

import pytest
from personalization import personalize
from test_workflow import app, post, register, token
from test_send import setup_send, prepare


def test_tokens_timezone_unknown_gender_and_data_not_reparsed():
    contact={'name':'Nam #{PHONE}','phone':'0901234567','email':'nam@example.com','info1':'VIP'}
    zalo={'name':'Nam Zalo','original_name':'Nam','gender':0}
    rendered=personalize('{{name}} #{FULL_NAME} #{ORIGINAL_NAME} #{EMAIL} #{INFO1} #{SEX{anh-chị-anh/chị}} #{TODAY(DD/MM/YYYY)}',contact,zalo,
                         now=datetime(2026,10,10,18,tzinfo=timezone.utc))
    assert rendered=='Nam #{PHONE} Nam Zalo Nam nam@example.com VIP anh 11/10/2026'
    assert personalize('#{SEX{anh-chị-anh/chị}}',contact,{})=='anh/chị'
    for template in ('#{INFO5}','#{UNKNOWN}','#{TODAY(bad)}','#{SEX{bad}}','#{BROKEN'):
        with pytest.raises(ValueError):
            personalize(template,contact,zalo)


def test_csv_extra_fields_and_owner_edit(app):
    client=app.test_client()
    register(client)
    result=post(client,'/contacts/import',{'file':(io.BytesIO(b'name,phone,email,info1,consent\nLan,0901234567,lan@example.com,VIP,1'),'extra.csv')})
    assert 'Đã nhập 1' in result.text
    post(client,'/contacts/1/edit',{'name':'Lan','email':'new@example.com','info1':'Gold'})
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT email,info1,consent FROM contacts').fetchone()==('new@example.com','Gold',1)
    other=app.test_client()
    register(other,'other')
    assert other.get('/contacts/1/edit').status_code==404
    assert other.post('/contacts/1/edit',data={'csrf':token(other),'name':'Bad'}).status_code==404


def test_actual_preview_blocks_missing_data_and_freezes_rendered_content(app):
    client,connector=setup_send(app)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE campaigns SET message='Chào #{FULL_NAME}, #{EMAIL}'")
    result=prepare(client)
    assert 'Thiếu thông tin EMAIL' in result.text
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT count(*) FROM message_sends').fetchone()[0]==0
    post(client,'/contacts/1/edit',{'name':'Lan','email':'lan@example.com'})
    result=prepare(client)
    assert 'Chào Lan Zalo, lan@example.com' in result.text
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT message FROM message_sends').fetchone()[0]=='Chào Lan Zalo, lan@example.com'


def test_legacy_invalid_macro_does_not_break_or_commit_simulation(app):
    client, _ = setup_send(app)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE campaigns SET message='#{TODAY(bad)}'")
    response = post(client, '/campaigns/1')
    assert response.status_code == 200
    assert 'Định dạng ngày cá nhân hóa không được hỗ trợ' in response.text
    with sqlite3.connect(app.config['DATABASE']) as db:
        assert db.execute('SELECT status FROM campaigns').fetchone()[0] == 'draft'
        assert db.execute('SELECT count(*) FROM deliveries').fetchone()[0] == 0
