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
    assert 'Kết quả chạy (1)' in results and 'Tìm SĐT' in results
    assert 'Đã tìm thấy SĐT 0901234567: Lan Zalo.' in results
    assert 'data-result-action="send"' not in results
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


def test_results_split_actual_actions_use_completion_times_and_never_dispatch_on_read(app):
    client,connector=setup_send(app)
    post(client,'/campaigns/1/edit',{'name':'Actions','message':'Hi','tag':'VIP','options_present':'yes',
        'send_message':'yes','send_friend':'yes','friend_message':'Hello','rename_enabled':'yes','rename_template':'#{FULL_NAME}'})
    prepare(client)
    for action,state,confirm in [('send','sent','confirm_send'),('friend','friend_requested','confirm_friend'),('alias','renamed','confirm_alias')]:
        connector.message_action.return_value={'state':state}
        assert post(client,f'/campaigns/1/{action}/1',{confirm:'yes'}).status_code==200
    assert query(app,'SELECT count(*) FROM campaign_attempts WHERE completed_at IS NOT NULL')==[(3,)]
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE message_sends SET created_at='2026-10-23 02:00:00'")
        for action,minute in [('alias',3),('send',2),('friend',1)]:
            db.execute('UPDATE campaign_attempts SET completed_at=? WHERE action=?',(f'2026-10-23 02:0{minute}:00',action))
    connector.message_action.reset_mock()
    result=client.get('/campaigns?selected=1&detail_tab=results').text
    assert 'Kết quả chạy (4)' in result
    assert re.findall('data-result-action="([^"]+)"',result)==['alias','send','friend','lookup']
    assert '09:03:00 23/10/2026' in result and '09:00:00 23/10/2026' in result
    assert 'Zalo đã tiếp nhận lời mời kết bạn đến Lan Zalo.' in result
    assert 'Đã đổi tên Lan Zalo thành' in result
    assert not connector.message_action.called


def test_lookup_result_distinguishes_missing_from_unavailable_and_isolates_owner(app):
    from test_campaign_schedule import setup,tick
    client,connector=setup(app)
    connector.message_action.side_effect=None
    connector.message_action.return_value={'state':'not_found'}
    tick(app)
    response=client.get('/campaigns?selected=1&detail_tab=results').text
    assert 'Kết quả chạy (1)' in response and 'data-result-state="not_found"' in response
    assert 'Không tồn tại' in response and 'result-state-warning' in response
    assert 'data-result-action="send"' not in response
    # Legacy ambiguous failures must not be relabeled as confirmed missing accounts.
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE message_sends SET lookup_state='',message_skip_reason='<script>lookup blocked</script>'")
    response=client.get('/campaigns?selected=1&detail_tab=results').text
    assert 'Không tra cứu được' in response and 'Không tồn tại' not in response
    assert '&lt;script&gt;lookup blocked&lt;/script&gt;' in response
    assert '<script>lookup blocked</script>' not in response
    other=app.test_client();register(other,'other')
    response=other.get('/campaigns?selected=1&detail_tab=results').text
    assert 'lookup blocked' not in response and 'data-result-action' not in response


def test_action_results_paginate_and_handle_old_attempts_without_completion_time(app):
    client,_=setup_send(app);prepare(client)
    with sqlite3.connect(app.config['DATABASE']) as db:
        for i in range(2,54):
            db.execute("INSERT INTO contacts(id,user_id,name,phone,consent) VALUES(?,1,?,?,1)",(i,f'Contact {i:02d}',f'09000000{i:02d}'))
            db.execute("""INSERT INTO message_sends(campaign_id,contact_id,account_id,recipient_id,recipient_name,message,recipient_phone,state)
                VALUES(1,?,1,?,'','',?,'sent')""",(i,str(i),f'09000000{i:02d}'))
    page=client.get('/campaigns?selected=1&detail_tab=results').text
    assert 'Kết quả chạy (105)' in page
    assert len(re.findall('data-result-action=',page))==50
    assert 'Dữ liệu cũ: hiển thị thời điểm bắt đầu' in page
    last=client.get('/campaigns?selected=1&detail_tab=results&detail_page=3').text
    assert 'Trang 3/3' in last and len(re.findall('data-result-action=',last))==5


def test_upgrade_recovers_old_completion_time_from_matching_result_event(app):
    from app import create_app
    client,connector=setup_send(app);prepare(client)
    connector.message_action.return_value={'state':'sent'}
    post(client,'/campaigns/1/send/1',{'confirm_send':'yes'})
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute('ALTER TABLE campaign_attempts DROP COLUMN completed_at')
        db.execute('ALTER TABLE message_sends DROP COLUMN lookup_state')
        db.execute("UPDATE campaign_events SET created_at='2026-10-23 02:03:00' WHERE kind='send_result'")
    upgraded=create_app(dict(TESTING=True,DATABASE=app.config['DATABASE'],SECRET_KEY='test-only'))
    assert query(upgraded,'SELECT completed_at FROM campaign_attempts')==[('2026-10-23 02:03:00',)]
    assert query(upgraded,'SELECT state FROM message_sends')==[('sent',)]
