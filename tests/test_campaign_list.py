import sqlite3
import re

from test_workflow import app, post, register
from test_send import setup_send, prepare


def test_compact_list_filters_by_real_account_and_selected_actions(app):
    owner=app.test_client();register(owner)
    post(owner,'/accounts',{'name':'Kế Toán Viettax'})
    post(owner,'/accounts',{'name':'Admin kế toán'})
    post(owner,'/campaigns',{'name':'Message only','message':'Hello','account_id':'1'})
    post(owner,'/campaigns',{'name':'Friend only','options_present':'yes','send_friend':'yes','friend_message':'Hi','account_id':'2'})
    post(owner,'/campaigns',{'name':'Both actions','message':'Hello','options_present':'yes','send_message':'yes','send_friend':'yes','friend_message':'Hi','account_id':'1'})
    page=owner.get('/campaigns?account_id=1').text
    assert 'Message only' in page and 'Both actions' in page and 'Friend only' not in page
    assert 'Friend only' in owner.get('/campaigns?kind=friend').text
    assert 'Message only' not in owner.get('/campaigns?kind=friend').text
    assert 'Both actions' not in owner.get('/campaigns?kind=message').text
    assert 'Both actions' in owner.get('/campaigns?kind=both').text
    assert owner.get('/campaigns?kind=unsupported').status_code==400
    other=app.test_client();register(other,'other')
    assert other.get('/campaigns?account_id=1').status_code==404
    assert other.get('/campaigns?log_account_id=2').status_code==404


def test_progress_uses_confirmed_actions_and_keeps_simulation_separate(app):
    client,connector=setup_send(app)
    prepare(client)
    connector.message_action.reset_mock()
    pending=client.get('/campaigns?selected=1').text
    assert 'Chờ xác nhận' in pending and 'Lan Zalo' in pending
    assert 'Gửi qua Zalo' in pending and 'Zalo của tôi' in pending
    assert connector.message_action.call_count==0

    # A confirmed message with an unconfirmed friend action is still incomplete.
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE message_sends SET state='sent',friend_state='prepared'")
    page=client.get('/campaigns?selected=1').text
    assert 'Chờ xác nhận' in page
    assert '<progress class="campaign-progress" max="100" value="0"' in page
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE message_sends SET friend_state='friend_requested'")
    complete=client.get('/campaigns?selected=1').text
    assert 'Đã xử lý' in complete
    assert '<progress class="campaign-progress" max="100" value="100"' in complete
    assert 'Tiến độ hiển thị là mô phỏng' not in complete
    post(client,'/contacts',{'name':'Binh','phone':'0912345678','tag':'VIP','consent':'on'})
    partial=client.get('/campaigns').text
    assert 'Đang xử lý' in partial
    assert '<progress class="campaign-progress" max="100" value="50"' in partial
    post(client,'/accounts',{'name':'Other account'})
    filtered=client.get('/campaigns?selected=1&log_account_id=2').text
    assert 'Lan Zalo' not in filtered and 'Chưa có log nào' in filtered
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE message_sends SET state='unknown'")
    assert 'Cần kiểm tra' in client.get('/campaigns').text
    assert '<progress class="campaign-progress" max="100" value="0"' in client.get('/campaigns').text
    assert connector.message_action.call_count==0


def campaign_status(client,query=''):
    page=client.get('/campaigns'+query).text
    return re.findall(r'<span class="status-pill [^"]+">([^<]+)</span>',page)


def test_scheduled_campaign_is_running_until_complete_and_pause_is_explicit(app):
    from test_campaign_schedule import setup,tick
    client,connector=setup(app)
    assert campaign_status(client)==['Đang xử lý']
    tick(app)  # Resolve a recipient and prepare the next automatic action, without sending.
    assert campaign_status(client)==['Đang xử lý']
    assert campaign_status(client,'?status=running')==['Đang xử lý']
    assert campaign_status(client,'?status=complete')==[]
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE campaigns SET schedule_wait_until='2099-01-01 00:00:00',schedule_wait_message='Nghỉ 120 giây'")
    assert campaign_status(client)==['Đang xử lý']
    post(client,'/campaigns/1/pause',{'paused':'1'})
    assert campaign_status(client)==['Tạm ngưng']
    assert campaign_status(client,'?status=paused')==['Tạm ngưng']
    assert campaign_status(client,'?status=running')==[]
    post(client,'/campaigns/1/pause',{'paused':'0'})
    assert campaign_status(client)==['Đang xử lý']
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE message_sends SET state='not_requested',friend_state='not_requested',alias_state='not_requested'")
    assert campaign_status(client)==['Đã xử lý']
    assert campaign_status(client,'?status=complete')==['Đã xử lý']
    assert campaign_status(client,'?status=running')==[]
    # Showing a status/filter must never cause an external action.
    assert connector.message_action.call_count==1


def test_scheduled_errors_do_not_appear_running_or_manually_paused(app):
    from test_campaign_schedule import setup
    client,_=setup(app)
    with sqlite3.connect(app.config['DATABASE']) as db:
        db.execute("UPDATE campaigns SET schedule_error='Cần đăng nhập lại'")
    assert campaign_status(client)==['Có lỗi']
    assert campaign_status(client,'?status=error')==['Có lỗi']
    assert campaign_status(client,'?status=running')==[]
    assert campaign_status(client,'?status=paused')==[]
