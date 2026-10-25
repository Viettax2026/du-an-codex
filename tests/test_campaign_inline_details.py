import re
import sqlite3

from test_workflow import app,post,register
from test_send import setup_send,prepare
from test_message_composer import rich,query,png


def test_inline_details_have_real_data_accounts_variants_results_and_history_without_dispatch(app):
    client,connector=setup_send(app)
    post(client,'/contacts',{'name':'Unconsented data','phone':'0912345678','tag':'VIP','consent':''})
    post(client,'/campaigns/1/content',rich('<b>A {{name}}</b> | <i>B {{name}}</i>'))
    prepare(client)
    connector.message_action.reset_mock()
    before=query(app,'SELECT count(*) FROM campaign_events')
    for key,label in [('info','Thông tin'),('accounts','Tài khoản'),('data','Data ban đầu'),('results','Kết quả chạy'),('preview','Xem trước nội dung'),('history','Lịch sử chạy')]:
        response=client.get('/campaigns',query_string={'selected':1,'detail_tab':key})
        assert response.status_code==200
        assert f'data-detail-current="{key}"' in response.text
        assert label in response.text
    assert not connector.message_action.called
    assert query(app,'SELECT count(*) FROM campaign_events')==before
    data=client.get('/campaigns?selected=1&detail_tab=data').text
    assert 'Data ban đầu (2)' in data and 'Unconsented data' in data and 'Chưa đồng ý' in data
    assert 'không phải bản chụp tại ngày tạo' in data
    assert 'Info 5' in data
    accounts=client.get('/campaigns?selected=1&detail_tab=accounts').text
    assert 'Đã đăng nhập' in accounts and 'Zalo của tôi' in accounts
    results=client.get('/campaigns?selected=1&detail_tab=results').text
    assert 'Chờ xác nhận' in results and '<strong>A Lan</strong>' in results
    preview=client.get('/campaigns?selected=1&detail_tab=preview').text
    assert 'Xem trước nội dung (2)' in preview
    assert '<strong>A {{name}}</strong>' in preview and '<em>B {{name}}</em>' in preview


def test_inline_history_is_paginated_and_other_owners_cannot_read_it(app):
    client,connector=setup_send(app)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.executemany("INSERT INTO campaign_events(campaign_id,kind,detail) VALUES(1,'test',?)",[(f'Private step {i:03d}',) for i in range(205)])
    first=client.get('/campaigns?selected=1&detail_tab=history').text
    assert len(re.findall(r'Private step \d{3}',first))==100
    assert 'Private step 204' in first and 'Private step 000' not in first
    third=client.get('/campaigns?selected=1&detail_tab=history&detail_page=3').text
    assert 'Private step 000' in third and 'Private step 204' not in third
    assert 'Trang 3/3' in third
    assert client.get('/campaigns?selected=1&detail_tab=invalid').status_code==400
    other=app.test_client();register(other,'other')
    page=other.get('/campaigns?selected=1&detail_tab=history').text
    assert 'Private step' not in page and 'Zalo của tôi' not in page and 'Chọn một chiến dịch để xem chi tiết' in page


def test_inline_saved_list_keeps_deleted_members_visible_as_history_and_escapes_text(app):
    client,_=setup_send(app)
    post(client,'/campaigns',{'name':'Saved list','message':'Hi','data_mode':'direct','phones':'0901234567','phones_consent':'yes'})
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE contacts SET deleted_at=CURRENT_TIMESTAMP,info1='<script>bad()</script>' WHERE id=1")
    response=client.get('/campaigns?selected=2&detail_tab=data')
    assert response.status_code==200
    assert 'Data ban đầu (1)' in response.text and 'Đã xóa' in response.text
    assert '&lt;script&gt;bad()&lt;/script&gt;' in response.text
    assert '<script>bad()</script>' not in response.text


def test_phone_previews_repeat_private_image_per_variant_and_preserve_format_without_sending(app):
    client,connector=setup_send(app)
    post(client,'/campaigns/1/edit',{'name':'Preview','message':'Hi','tag':'VIP','account_id':'1'})
    post(client,'/campaigns/1/content',rich('<b>Chào {{name}}</b> | Nội dung thường',media_present='yes',media_mode='send',media=png()))
    media_id=query(app,'SELECT media_id FROM campaigns WHERE id=1')[0][0]
    connector.message_action.reset_mock()
    response=client.get('/campaigns?selected=1&detail_tab=preview')
    assert response.status_code==200
    assert response.text.count('class="inline-variant zalo-preview-card"')==2
    assert response.text.count(f'src="/media/{media_id}"')==2
    assert '<strong>Chào {{name}}</strong>' in response.text
    assert 'zalo-preview-image' in response.text and 'zalo-preview-caption' in response.text
    assert 'Đang hoạt động' not in response.text
    assert not connector.message_action.called
    assert query(app,'SELECT count(*) FROM message_sends')==[(0,)]
