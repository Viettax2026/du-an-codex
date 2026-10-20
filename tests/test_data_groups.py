import io
import sqlite3

from openpyxl import Workbook
from test_workflow import app, post, register


def database(app):
    return sqlite3.connect(app.config['DATABASE'])


def test_group_import_metadata_duplicates_and_consent(app):
    client = app.test_client()
    register(client)
    assert 'Nhóm data' in post(client, '/data-groups', {'name': 'VIP'}).text
    result = post(client, '/data-groups/import', {'group': 'VIP', 'consent': 'yes',
        'file': (io.BytesIO('phone,name,email,info1\n+84901234567,Lan,lan@example.com,A\n'.encode()), 'contacts.csv')})
    assert 'Lan' in result.text
    post(client, '/data-groups', {'name': 'Other'})
    post(client, '/data-groups/import', {'group': 'Other', 'phones': '0901234567\n0912345678'})
    with database(app) as db:
        assert db.execute('SELECT name,tag,consent,email,info1 FROM contacts WHERE phone=?', ('0901234567',)).fetchone() == ('Lan', 'VIP', 1, 'lan@example.com', 'A')
        assert db.execute('SELECT consent FROM contacts WHERE phone=?', ('0912345678',)).fetchone() == (0,)
    # A group that has no consented members contributes no recipients.
    post(client, '/campaigns', {'name': 'Group', 'message': 'Hi', 'data_mode': 'group', 'tag': 'Other'})
    with database(app) as db:
        assert db.execute('SELECT audience_mode,tag FROM campaigns').fetchone() == ('group', 'Other')


def test_campaign_file_import_edit_and_snapshot_group(app):
    client = app.test_client()
    register(client)
    book = Workbook()
    book.active.append(['phone', 'name', 'info2'])
    book.active.append([901234567, 'Lan', 'Excel'])
    stream = io.BytesIO()
    book.save(stream)
    stream.seek(0)
    result = post(client, '/campaigns', {'name': 'Excel', 'message': 'Hi', 'data_mode': 'direct',
        'data_file': (stream, 'data.xlsx'), 'phones_consent': 'yes'})
    assert 'Excel' in result.text
    with database(app) as db:
        assert db.execute('SELECT name,phone,info2 FROM contacts').fetchone() == ('Lan', '0901234567', 'Excel')
        assert db.execute('SELECT audience_mode FROM campaigns').fetchone() == ('list',)
    assert 'Cách thêm data vào chiến dịch' in client.get('/campaigns/1/edit').text
    post(client, '/data-groups', {'name': 'VIP'})
    post(client, '/data-groups/import', {'group': 'VIP', 'phones': '0912345678', 'consent': 'yes'})
    post(client, '/campaigns/1/edit', {'name': 'Snapshot', 'message': 'Hi', 'data_mode': 'direct',
        'source_tags': 'VIP', 'phones_consent': 'yes'})
    post(client, '/data-groups/import', {'group': 'VIP', 'phones': '0923456789', 'consent': 'yes'})
    with database(app) as db:
        assert db.execute('SELECT p.phone FROM contacts p JOIN campaign_contacts cc ON cc.contact_id=p.id WHERE cc.campaign_id=1').fetchall() == [('0912345678',)]
    # Existing campaign add-data supports TXT and group snapshot together.
    post(client, '/campaigns/1/data', {'source_tag': 'VIP', 'consent': 'yes',
        'file': (io.BytesIO(b'0934567890'), 'data.txt')})
    with database(app) as db:
        assert db.execute('SELECT count(*) FROM campaign_contacts WHERE campaign_id=1').fetchone() == (3,)


def test_import_errors_rollback_and_tenant_isolation(app):
    client = app.test_client()
    register(client)
    post(client, '/data-groups', {'name': 'Private'})
    post(client, '/data-groups/import', {'group': 'Private', 'phones': '0901234567',
        'file': (io.BytesIO(b'phone,name\ninvalid,Bad'), 'bad.csv')})
    with database(app) as db:
        assert db.execute('SELECT count(*) FROM contacts').fetchone() == (0,)
    other = app.test_client()
    register(other, 'other')
    assert other.get('/data-groups?group=Private').status_code == 404
    assert post(other, '/data-groups/import', {'group': 'Private', 'phones': '0901234567'}).status_code == 404
    post(client, '/campaigns', {'name': 'Missing', 'message': 'Hi', 'data_mode': 'direct', 'phones': '0901234567'})
    post(client, '/campaigns', {'name': 'Empty', 'message': 'Hi', 'data_mode': 'direct'})
    post(client, '/campaigns', {'name': 'Missing group', 'message': 'Hi', 'data_mode': 'group', 'tag': 'Secret'})
    with database(app) as db:
        assert db.execute('SELECT count(*) FROM campaigns').fetchone() == (0,)


def test_invalid_excel_and_large_import_are_atomic(app):
    client = app.test_client()
    register(client)
    post(client, '/data-groups', {'name': 'VIP'})
    for content, filename in [(b'broken', 'bad.xlsx'), (b'x' * (2 * 1024 * 1024 + 1), 'big.csv'),
                              (b'phone\n' + b'0901234567\n' * 501, 'many.csv')]:
        response = post(client, '/data-groups/import', {'group': 'VIP', 'consent': 'yes',
            'phones': '0912345678', 'file': (io.BytesIO(content), filename)})
        assert response.status_code == 200
        with database(app) as db:
            assert db.execute('SELECT count(*) FROM contacts').fetchone() == (0,)


def test_create_group_dialog_and_saved_preferences(app):
    client = app.test_client()
    register(client)
    page = client.get('/data-groups').text
    assert 'id="create-group-dialog"' in page
    assert 'Tạo nhóm data' in page
    response = post(client, '/data-groups', {'name': 'Tháng 10', 'data_type': 'phone', 'color': '#EF1234'})
    assert response.status_code == 200
    assert 'Số điện thoại' in response.text
    assert 'data-group-color="#ef1234"' in response.text
    with database(app) as db:
        assert db.execute('SELECT name,data_type,color FROM data_groups').fetchone() == ('Tháng 10', 'phone', '#ef1234')
    # The same group name must not silently reset its saved preferences.
    response = post(client, '/data-groups', {'name': 'Tháng 10', 'data_type': 'uid', 'color': '#000000'})
    assert 'Tên nhóm đã tồn tại' in response.text
    assert 'data-reopen="yes"' in response.text
    with database(app) as db:
        assert db.execute('SELECT data_type,color FROM data_groups').fetchall() == [('phone', '#ef1234')]


def test_invalid_group_preferences_and_csrf_are_rejected(app):
    client = app.test_client()
    register(client)
    for fields in [{'name': '  '}, {'name': 'Invalid', 'data_type': 'unknown'},
                   {'name': 'Invalid', 'color': 'red;display:none'}]:
        assert post(client, '/data-groups', fields).status_code == 200
    assert client.post('/data-groups', data={'name': 'Missing CSRF'}).status_code == 400
    with database(app) as db:
        assert db.execute('SELECT count(*) FROM data_groups').fetchone() == (0,)


def test_legacy_groups_receive_metadata_without_losing_contacts(app):
    from app import create_app
    client = app.test_client()
    register(client)
    post(client, '/contacts', {'name': 'Lan', 'phone': '0901234567', 'tag': 'Legacy'})
    with database(app) as db:
        db.execute('DROP TABLE data_groups')
        db.execute('CREATE TABLE data_groups (id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,name TEXT NOT NULL,UNIQUE(user_id,name))')
        db.execute("INSERT INTO data_groups(user_id,name) VALUES (1,'Legacy')")
    create_app({'TESTING': True, 'DATABASE': app.config['DATABASE'], 'SECRET_KEY': 'test-only'})
    with database(app) as db:
        assert db.execute('SELECT name,data_type,color FROM data_groups').fetchone() == ('Legacy', 'all', '#6860f6')
        assert db.execute('SELECT name,tag FROM contacts').fetchone() == ('Lan', 'Legacy')


def test_group_detail_empty_state_filters_pagination_and_import_dates(app):
    client = app.test_client()
    register(client)
    response = post(client, '/data-groups', {'name': 'Details'})
    assert 'Không có data nào khớp bộ lọc.' in response.text
    assert 'Chưa có data để phân bố.' in response.text
    assert 'Đang dùng ở 0 chiến dịch' in response.text
    assert 'Trang 1/1' in response.text
    phones = '\n'.join(f'09{index:08}' for index in range(51))
    post(client, '/data-groups/import', {'group': 'Details', 'phones': phones, 'consent': 'yes'})
    response = client.get('/data-groups?group=Details')
    assert response.text.count('name="contact_ids"') == 50
    assert 'Trang 1/2' in response.text
    response = client.get('/data-groups?group=Details&p=2')
    assert response.text.count('name="contact_ids"') == 1
    assert 'Trang 2/2' in response.text
    assert 'Không có data nào khớp bộ lọc.' in client.get('/data-groups?group=Details&kind=uid').text
    assert 'Không có data nào khớp bộ lọc.' in client.get('/data-groups?group=Details&consent=no').text
    assert client.get('/data-groups?group=Details&kind=invalid').status_code == 400
    post(client, '/campaigns', {'name': 'Group use', 'message': 'Hi', 'data_mode': 'group', 'tag': 'Details'})
    assert 'Đang dùng ở 1 chiến dịch' in client.get('/data-groups?group=Details').text
    with database(app) as db:
        created, latest, count = db.execute('SELECT created_at,last_import_at,imported_count FROM data_groups').fetchone()
        assert created and latest and count == 51


def test_export_group_selection_is_scoped_and_csv_safe(app):
    client = app.test_client()
    register(client)
    post(client, '/data-groups', {'name': 'Export'})
    post(client, '/data-groups/import', {'group': 'Export', 'consent': 'yes',
        'file': (io.BytesIO(b'phone,name\n0901234567,=1+1\n'), 'data.csv')})
    response = post(client, '/data-groups/export', {'group': 'Export', 'contact_ids': '1'})
    assert response.mimetype == 'text/csv'
    assert "'=1+1" in response.data.decode('utf-8-sig')
    assert '0901234567' in response.data.decode('utf-8-sig')
    assert post(client, '/data-groups/export', {'group': 'Wrong', 'contact_ids': '1'}).status_code == 404
    assert post(client, '/data-groups/export', {'group': 'Export'}).status_code == 400
    other = app.test_client()
    register(other, 'other')
    assert post(other, '/data-groups/export', {'group': 'Export', 'contact_ids': '1'}).status_code == 404


def test_account_dropdown_uses_owned_accounts_and_filters_campaign_data(app):
    client = app.test_client()
    register(client)
    post(client, '/data-groups', {'name': 'Accounts'})
    post(client, '/data-groups/import', {'group': 'Accounts', 'phones': '0901234567', 'consent': 'yes'})
    with database(app) as db:
        db.execute("INSERT INTO zalo_accounts(user_id,name) VALUES (1,'Kế Toán Viettax')")
        db.execute("INSERT INTO zalo_accounts(user_id,name) VALUES (1,'Admin kế toán')")
    response = client.get('/data-groups?group=Accounts')
    assert 'Kế Toán Viettax' in response.text and 'Admin kế toán' in response.text
    post(client, '/campaigns', {'name': 'Account campaign', 'message': 'Hi', 'data_mode': 'group', 'tag': 'Accounts', 'account_id': '1'})
    response = client.get('/data-groups?group=Accounts&account_id=1')
    assert '<option value="1" selected>' in response.text
    assert 'name="contact_ids"' in response.text
    assert 'name="contact_ids"' not in client.get('/data-groups?group=Accounts&account_id=2').text
    assert 'name="contact_ids"' in client.get('/data-groups?group=Accounts').text
    other = app.test_client()
    register(other, 'other')
    assert 'Kế Toán Viettax' not in other.get('/data-groups').text
    assert other.get('/data-groups?account_id=1').status_code == 404
    assert client.get('/data-groups?account_id=invalid').status_code == 404
