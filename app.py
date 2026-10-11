import csv
import io
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from functools import wraps
from pathlib import Path

from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from zalo_connector import QRConnector
from personalization import personalize


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    key_path = Path(app.instance_path) / 'session.key'
    if not key_path.exists():
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as stream:
                stream.write(secrets.token_hex(32))
        except FileExistsError:
            pass
    app.config.update(SECRET_KEY=os.environ.get('APP_SECRET_KEY') or key_path.read_text(),
                      DATABASE=str(Path(app.instance_path) / 'zalo.sqlite3'),
                      MAX_CONTENT_LENGTH=2 * 1024 * 1024,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                      SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE') == '1',
                      ZALO_QR_ENABLED=os.environ.get('ZALO_QR_ENABLED') == '1',
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
    if test_config:
        app.config.update(test_config)
    connector = QRConnector(app.instance_path, app.root_path)
    app.extensions['zalo_connector'] = connector

    @app.template_filter('localtime')
    def localtime(value):
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).astimezone(
            ZoneInfo('Asia/Bangkok')).strftime('%H:%M %d/%m/%Y')

    def db():
        if 'db' not in g:
            g.db = sqlite3.connect(app.config['DATABASE'])
            g.db.row_factory = sqlite3.Row
            g.db.execute('PRAGMA foreign_keys=ON')
        return g.db

    @app.teardown_appcontext
    def close_db(_):
        if 'db' in g:
            g.pop('db').close()

    with app.app_context():
        db().executescript('''
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
          password TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS contacts (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
          name TEXT NOT NULL, phone TEXT NOT NULL, zalo_id TEXT NOT NULL DEFAULT '',
          tag TEXT NOT NULL DEFAULT 'Khách hàng', consent INTEGER NOT NULL DEFAULT 0,
          UNIQUE(user_id, phone));
        CREATE TABLE IF NOT EXISTS campaigns (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
          name TEXT NOT NULL, message TEXT NOT NULL, tag TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'draft', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS zalo_accounts (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
          name TEXT NOT NULL, account_group TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(user_id, name));
        CREATE TABLE IF NOT EXISTS deliveries (
          id INTEGER PRIMARY KEY, campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
          contact_id INTEGER NOT NULL REFERENCES contacts(id), message TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'simulated', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS message_sends (
          id INTEGER PRIMARY KEY, campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
          contact_id INTEGER NOT NULL REFERENCES contacts(id), account_id INTEGER NOT NULL REFERENCES zalo_accounts(id),
          recipient_id TEXT NOT NULL, recipient_name TEXT NOT NULL, message TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'prepared', message_id TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(campaign_id, contact_id));
        CREATE TABLE IF NOT EXISTS campaign_contacts (
          campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
          contact_id INTEGER NOT NULL REFERENCES contacts(id), PRIMARY KEY(campaign_id,contact_id));
        ''')
        if 'account_id' not in {row['name'] for row in db().execute('PRAGMA table_info(campaigns)')}:
            db().execute('ALTER TABLE campaigns ADD COLUMN account_id INTEGER REFERENCES zalo_accounts(id)')
            db().commit()

        for table, columns in {
            'contacts': {column: "TEXT NOT NULL DEFAULT ''" for column in ('email','info1','info2','info3','info4','info5')},
            'campaigns': {'rename_enabled': 'INTEGER NOT NULL DEFAULT 0', 'rename_template': "TEXT NOT NULL DEFAULT ''", 'send_message': 'INTEGER NOT NULL DEFAULT 1', 'send_friend': 'INTEGER NOT NULL DEFAULT 0', 'friend_message': "TEXT NOT NULL DEFAULT ''"},
            'message_sends': {'alias': "TEXT NOT NULL DEFAULT ''", 'alias_state': "TEXT NOT NULL DEFAULT 'not_requested'", 'friend_message': "TEXT NOT NULL DEFAULT ''", 'friend_state': "TEXT NOT NULL DEFAULT 'not_requested'"},
        }.items():
            present = {row['name'] for row in db().execute(f'PRAGMA table_info({table})')}
            for column, declaration in columns.items():
                if column not in present:
                    db().execute(f'ALTER TABLE {table} ADD COLUMN {column} {declaration}')
        db().commit()

    def action_settings():
        if request.form.get('options_present') == 'yes':
            message_enabled = int(request.form.get('send_message') == 'yes')
            friend_enabled = int(request.form.get('send_friend') == 'yes')
        else:
            message_enabled, friend_enabled = 1, 0
        invitation = field('friend_message', 150)
        if not message_enabled and not friend_enabled:
            raise ValueError('Chọn ít nhất một hành động: nhắn tin hoặc kết bạn.')
        if friend_enabled and not invitation:
            raise ValueError('Nhập nội dung lời mời kết bạn (tối đa 150 ký tự).')
        return message_enabled, friend_enabled, invitation

    def save_action_settings(campaign_id):
        message_enabled, friend_enabled, invitation = action_settings()
        rename_enabled = int(request.form.get('rename_enabled') == 'yes')
        rename_template = field('rename_template', 100)
        if rename_enabled:
            if not rename_template:
                raise ValueError('Nhập mẫu tên gợi nhớ.')
            personalize(rename_template, {}, strict=False)
        db().execute('UPDATE campaigns SET rename_enabled=?,rename_template=? WHERE id=?',
                     (rename_enabled, rename_template, campaign_id))
        db().execute('UPDATE campaigns SET send_message=?,send_friend=?,friend_message=? WHERE id=?',
                     (message_enabled, friend_enabled, invitation, campaign_id))

    def audience(campaign):
        return db().execute('''SELECT p.* FROM contacts p WHERE p.user_id=? AND p.consent=1 AND
            (p.id IN (SELECT contact_id FROM campaign_contacts WHERE campaign_id=?) OR
             (NOT EXISTS (SELECT 1 FROM campaign_contacts WHERE campaign_id=?) AND (?='' OR p.tag=?)))
             ORDER BY p.id''', (g.user['id'], campaign['id'], campaign['id'], campaign['tag'], campaign['tag'])).fetchall()

    def campaign_fields():
        if request.form.get('action', 'phone_message') not in ('phone_message', 'phone_actions'):
            raise ValueError('Chỉ hỗ trợ tìm theo số điện thoại và nhắn tin.')
        name, message, tag = field('name', 120), field('message', 2000), field('tag', 80)
        message_enabled, _, _ = action_settings()
        personalize(message, {}, strict=False)
        if request.form.get('send_friend') == 'yes':
            personalize(request.form.get('friend_message', ''), {}, strict=False)
        if not name or (message_enabled and not message):
            raise ValueError('Vui lòng nhập tên chiến dịch và nội dung.')
        account_id = request.form.get('account_id') or None
        if account_id and not db().execute('SELECT 1 FROM zalo_accounts WHERE id=? AND user_id=?', (account_id, g.user['id'])).fetchone():
            raise ValueError('Tài khoản Zalo không hợp lệ.')
        phones = []
        raw = request.form.get('phones', '').strip()
        if len(raw) > 15000:
            raise ValueError('Danh sách số điện thoại quá dài.')
        for value in re.split(r'[\n,;]+', raw):
            phone = re.sub(r'[\s()+-]', '', value)
            if not phone:
                continue
            if phone.startswith('84'):
                phone = '0' + phone[2:]
            if not re.fullmatch(r'0[0-9]{9}', phone):
                raise ValueError('Số điện thoại Việt Nam cần 10 chữ số, bắt đầu bằng 0 (hoặc dùng +84).')
            if phone not in phones:
                phones.append(phone)
        if len(phones) > 500:
            raise ValueError('Mỗi chiến dịch tối đa 500 số điện thoại.')
        if phones and request.form.get('phones_consent') != 'yes':
            raise ValueError('Cần xác nhận các số điện thoại đã đồng ý nhận nội dung này.')
        return name, message, tag, account_id, phones

    def save_campaign_phones(campaign_id, phones):
        save_action_settings(campaign_id)
        db().execute('DELETE FROM campaign_contacts WHERE campaign_id=?', (campaign_id,))
        for phone in phones:
            db().execute('''INSERT INTO contacts(user_id,name,phone,consent) VALUES (?,?,?,1)
                ON CONFLICT(user_id,phone) DO UPDATE SET consent=1''', (g.user['id'], 'Khách hàng ' + phone, phone))
            contact = db().execute('SELECT id FROM contacts WHERE user_id=? AND phone=?', (g.user['id'], phone)).fetchone()
            db().execute('INSERT INTO campaign_contacts(campaign_id,contact_id) VALUES (?,?)', (campaign_id, contact['id']))

    @app.before_request
    def security():
        session.setdefault('csrf', secrets.token_hex(24))
        if request.method == 'POST' and not secrets.compare_digest(
                session['csrf'], request.form.get('csrf', '')):
            return 'Phiên làm việc không hợp lệ. Vui lòng tải lại trang.', 400
        g.user = None
        if session.get('user_id'):
            g.user = db().execute('SELECT id, name, email FROM users WHERE id=?',
                                  (session['user_id'],)).fetchone()

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        response.headers['Cache-Control'] = 'no-store'
        return response

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for('login'))
            return view(*args, **kwargs)
        return wrapped

    def field(name, limit):
        value = request.form.get(name, '').strip()
        if len(value) > limit:
            raise ValueError('Nội dung vượt quá độ dài cho phép.')
        return value

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'POST':
            name, email, password = request.form.get('name', '').strip(), request.form.get('email', '').strip().lower(), request.form.get('password', '')
            if not name or len(name) > 100 or '@' not in email or len(email) > 254 or not 10 <= len(password) <= 256:
                flash('Nhập tên, email hợp lệ và mật khẩu từ 10 đến 256 ký tự.', 'error')
            else:
                try:
                    cur = db().execute('INSERT INTO users(name,email,password) VALUES (?,?,?)',
                                       (name, email, generate_password_hash(password)))
                    db().commit()
                    session.clear()
                    session['user_id'] = cur.lastrowid
                    session.permanent = True
                    return redirect(url_for('dashboard'))
                except sqlite3.IntegrityError:
                    flash('Email này đã được đăng ký.', 'error')
        return render_template('auth.html', register=True)

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            user = db().execute('SELECT * FROM users WHERE email=?', (request.form.get('email', '').strip().lower(),)).fetchone()
            password = request.form.get('password', '')
            if user and len(password) <= 256 and check_password_hash(user['password'], password):
                session.clear()
                session['user_id'] = user['id']
                session.permanent = True
                return redirect(url_for('dashboard'))
            flash('Email hoặc mật khẩu chưa đúng.', 'error')
        return render_template('auth.html', register=False)

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect(url_for('login'))

    @app.get('/')
    @login_required
    def dashboard():
        uid = g.user['id']
        stats = {
            'contacts': db().execute('SELECT count(*) FROM contacts WHERE user_id=?', (uid,)).fetchone()[0],
            'consent': db().execute('SELECT count(*) FROM contacts WHERE user_id=? AND consent=1', (uid,)).fetchone()[0],
            'campaigns': db().execute('SELECT count(*) FROM campaigns WHERE user_id=?', (uid,)).fetchone()[0],
            'deliveries': db().execute('SELECT count(*) FROM deliveries d JOIN campaigns c ON c.id=d.campaign_id WHERE c.user_id=?', (uid,)).fetchone()[0],
        }
        campaigns = db().execute('SELECT c.*, (SELECT count(*) FROM deliveries d WHERE d.campaign_id=c.id) AS total FROM campaigns c WHERE user_id=? ORDER BY id DESC LIMIT 5', (uid,)).fetchall()
        return render_template('dashboard.html', stats=stats, campaigns=campaigns, page='dashboard')

    @app.route('/contacts', methods=['GET', 'POST'])
    @login_required
    def contacts():
        if request.method == 'POST':
            try:
                name, phone = field('name', 100), field('phone', 30)
                if not name or not phone:
                    raise ValueError('Vui lòng nhập tên và số điện thoại.')
                db().execute('INSERT INTO contacts(user_id,name,phone,zalo_id,tag,consent,email,info1,info2,info3,info4,info5) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                             (g.user['id'], name, phone, field('zalo_id', 100), field('tag', 80) or 'Khách hàng', int(request.form.get('consent') == 'on'),
                              field('email',254), *(field(f'info{i}',500) for i in range(1,6))))
                db().commit()
                flash('Đã thêm khách hàng.', 'success')
            except ValueError as error:
                flash(str(error), 'error')
            except sqlite3.IntegrityError:
                flash('Số điện thoại đã có trong danh sách.', 'error')
            return redirect(url_for('contacts'))
        query = request.args.get('q', '').strip()
        rows = db().execute('SELECT * FROM contacts WHERE user_id=? AND (name LIKE ? OR phone LIKE ? OR tag LIKE ?) ORDER BY id DESC',
                            (g.user['id'], *(['%' + query + '%'] * 3))).fetchall()
        return render_template('contacts.html', contacts=rows, query=query, page='contacts')

    @app.post('/contacts/import')
    @login_required
    def import_contacts():
        upload = request.files.get('file')
        if not upload:
            flash('Chọn tệp CSV trước khi nhập.', 'error')
            return redirect(url_for('contacts'))
        try:
            reader = csv.DictReader(io.StringIO(upload.read().decode('utf-8-sig')))
            if not reader.fieldnames or not {'name', 'phone'}.issubset(reader.fieldnames):
                raise ValueError('CSV cần có hai cột name, phone.')
            count = skipped = 0
            for index, row in enumerate(reader):
                if index >= 5000:
                    raise ValueError('Mỗi lần nhập tối đa 5.000 khách hàng.')
                name, phone, tag, zalo_id = [(row.get(key) or '').strip() for key in ('name', 'phone', 'tag', 'zalo_id')]
                if not name or not phone or len(name) > 100 or len(phone) > 30 or len(tag) > 80 or len(zalo_id) > 100:
                    raise ValueError(f'Dữ liệu không hợp lệ tại dòng {index + 2}.')
                extra = [(row.get(key) or '').strip() for key in ('email','info1','info2','info3','info4','info5')]
                if len(extra[0]) > 254 or any(len(value) > 500 for value in extra[1:]):
                    raise ValueError(f'Thông tin bổ sung quá dài tại dòng {index + 2}.')
                cur = db().execute('INSERT OR IGNORE INTO contacts(user_id,name,phone,tag,zalo_id,consent,email,info1,info2,info3,info4,info5) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                                   (g.user['id'], name, phone, tag or 'Khách hàng', zalo_id, int((row.get('consent') or '').lower() in ('1', 'true', 'yes')), *extra))
                count += cur.rowcount
                skipped += 1 - cur.rowcount
            db().commit()
            flash(f'Đã nhập {count} khách hàng, bỏ qua {skipped} số trùng.', 'success')
        except (UnicodeDecodeError, ValueError, csv.Error) as error:
            db().rollback()
            flash(f'Không thể nhập CSV: {error}', 'error')
        return redirect(url_for('contacts'))

    @app.route('/contacts/<int:contact_id>/edit', methods=['GET','POST'])
    @login_required
    def edit_contact(contact_id):
        person = db().execute('SELECT * FROM contacts WHERE id=? AND user_id=?', (contact_id,g.user['id'])).fetchone()
        if person is None:
            return 'Không tìm thấy khách hàng.', 404
        if request.method == 'POST':
            try:
                name = field('name',100)
                if not name:
                    raise ValueError('Nhập tên khách hàng.')
                db().execute('UPDATE contacts SET name=?,email=?,info1=?,info2=?,info3=?,info4=?,info5=? WHERE id=? AND user_id=?',
                    (name,field('email',254),*(field(f'info{i}',500) for i in range(1,6)),contact_id,g.user['id']))
                db().commit()
                flash('Đã lưu thông tin khách hàng. Các bản xem trước cũ giữ nguyên nội dung.', 'success')
                return redirect(url_for('contacts'))
            except ValueError as error:
                flash(str(error),'error')
        return render_template('contact_edit.html',person=person,page='contacts')

    @app.post('/contacts/<int:contact_id>/consent')
    @login_required
    def consent(contact_id):
        db().execute('UPDATE contacts SET consent=1-consent WHERE id=? AND user_id=?', (contact_id, g.user['id']))
        db().commit()
        flash('Đã cập nhật trạng thái đồng ý nhận tin.', 'success')
        return redirect(url_for('contacts'))

    @app.route('/campaigns', methods=['GET', 'POST'])
    @login_required
    def campaigns():
        if request.method == 'POST':
            try:
                name, message, tag, account_id, phones = campaign_fields()
                cur = db().execute('INSERT INTO campaigns(user_id,name,message,tag,account_id) VALUES (?,?,?,?,?)', (g.user['id'], name, message, tag, account_id))
                save_campaign_phones(cur.lastrowid, phones)
                db().commit()
                flash('Đã tạo chiến dịch. Kiểm tra nội dung trước khi gửi thử.', 'success')
                return redirect(url_for('campaign_detail', campaign_id=cur.lastrowid))
            except ValueError as error:
                db().rollback()
                flash(str(error), 'error')
                return redirect(url_for('campaigns'))
        query = request.args.get('q', '').strip()[:120]
        status = request.args.get('status', '')
        status = status if status in ('draft', 'simulated') else ''
        days = request.args.get('days', '')
        days = days if days in ('7', '30', '90') else ''
        tag = request.args.get('tag', '').strip()[:80]
        rows = db().execute('''SELECT c.*,
            (SELECT count(*) FROM deliveries d WHERE d.campaign_id=c.id) AS total,
            (SELECT count(*) FROM contacts p WHERE p.user_id=c.user_id AND p.consent=1
              AND (p.id IN (SELECT contact_id FROM campaign_contacts WHERE campaign_id=c.id) OR
                   (NOT EXISTS (SELECT 1 FROM campaign_contacts WHERE campaign_id=c.id) AND (c.tag='' OR p.tag=c.tag)))) AS audience
            FROM campaigns c WHERE user_id=? AND name LIKE ?
              AND (?='' OR status=?) AND (?='' OR tag=?)
              AND (?='' OR created_at >= datetime('now', ?)) ORDER BY id DESC''',
            (g.user['id'], '%' + query + '%', status, status, tag, tag,
             days, '-' + (days or '0') + ' days')).fetchall()
        tags = db().execute('SELECT DISTINCT tag FROM contacts WHERE user_id=? ORDER BY tag', (g.user['id'],)).fetchall()
        selected_id = request.args.get('selected', type=int)
        selected = next((row for row in rows if row['id'] == selected_id), None)
        logs = []
        if selected:
            logs = db().execute('''SELECT d.*, p.name FROM deliveries d
                JOIN contacts p ON p.id=d.contact_id WHERE d.campaign_id=?
                ORDER BY d.id DESC LIMIT 100''', (selected['id'],)).fetchall()
        return render_template('campaigns.html', campaigns=rows, tags=tags,
                               query=query, status=status, days=days, tag=tag,
                               selected=selected, logs=logs, page='campaigns',
                               accounts=db().execute('SELECT * FROM zalo_accounts WHERE user_id=? ORDER BY name', (g.user['id'],)).fetchall())

    @app.route('/campaigns/<int:campaign_id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_campaign(campaign_id):
        if request.method == 'POST':
            db().execute('BEGIN IMMEDIATE')
        campaign = db().execute('SELECT * FROM campaigns WHERE id=? AND user_id=?', (campaign_id, g.user['id'])).fetchone()
        if campaign is None:
            return 'Không tìm thấy chiến dịch.', 404
        if campaign['status'] != 'draft' or db().execute('SELECT 1 FROM message_sends WHERE campaign_id=?', (campaign_id,)).fetchone():
            flash('Chiến dịch đã mô phỏng hoặc có lần gửi/xem trước. Không sửa để giữ nguyên nội dung nhật ký.', 'error')
            return redirect(url_for('campaign_detail', campaign_id=campaign_id))
        if request.method == 'POST':
            try:
                name, message, tag, account_id, phones = campaign_fields()
                db().execute('UPDATE campaigns SET name=?,message=?,tag=?,account_id=? WHERE id=?', (name, message, tag, account_id, campaign_id))
                save_campaign_phones(campaign_id, phones)
                db().commit()
                flash('Đã lưu chiến dịch. Chưa gửi tin.', 'success')
                return redirect(url_for('campaign_detail', campaign_id=campaign_id))
            except ValueError as error:
                db().rollback()
                flash(str(error), 'error')
        phones = db().execute('SELECT p.phone FROM contacts p JOIN campaign_contacts cc ON cc.contact_id=p.id WHERE cc.campaign_id=? ORDER BY p.id', (campaign_id,)).fetchall()
        return render_template('campaign_edit.html', campaign=campaign, phones='\n'.join(p['phone'] for p in phones),
            accounts=db().execute('SELECT * FROM zalo_accounts WHERE user_id=? ORDER BY name', (g.user['id'],)).fetchall(),
            tags=db().execute('SELECT DISTINCT tag FROM contacts WHERE user_id=? ORDER BY tag', (g.user['id'],)).fetchall(), page='campaigns')

    @app.route('/campaigns/<int:campaign_id>', methods=['GET', 'POST'])
    @login_required
    def campaign_detail(campaign_id):
        campaign = db().execute('SELECT * FROM campaigns WHERE id=? AND user_id=?', (campaign_id, g.user['id'])).fetchone()
        if campaign is None:
            return 'Không tìm thấy chiến dịch.', 404
        recipients = audience(campaign)
        if request.method == 'POST':
            # The conditional update atomically claims a draft to prevent double submissions.
            if not campaign['send_message']:
                flash('Chiến dịch này chỉ chọn kết bạn, không có nội dung nhắn tin để mô phỏng.', 'error')
                return redirect(url_for('campaign_detail', campaign_id=campaign_id))
            cur = db().execute("UPDATE campaigns SET status='simulated' WHERE id=? AND user_id=? AND status='draft'", (campaign_id, g.user['id']))
            if not recipients or not cur.rowcount:
                db().rollback()
                flash('Cần có người đồng ý nhận tin và chiến dịch chưa gửi thử.', 'error')
            else:
                try:
                    for person in recipients:
                        message = personalize(campaign['message'], person, strict=False)
                        db().execute('INSERT INTO deliveries(campaign_id,contact_id,message) VALUES (?,?,?)', (campaign_id, person['id'], message))
                    db().commit()
                    flash(f'Đã mô phỏng {len(recipients)} tin nhắn. Chưa gửi tin đến Zalo.', 'success')
                except ValueError as error:
                    db().rollback()
                    flash(str(error), 'error')
            return redirect(url_for('campaign_detail', campaign_id=campaign_id))
        logs = db().execute('SELECT d.*, c.name FROM deliveries d JOIN contacts c ON c.id=d.contact_id WHERE campaign_id=? ORDER BY d.id DESC', (campaign_id,)).fetchall()
        try:
            preview = personalize(campaign['message'], recipients[0] if recipients else {'name':'Nguyễn An'}, strict=False)
        except ValueError as error:
            preview = str(error)
        accounts = db().execute('SELECT * FROM zalo_accounts WHERE user_id=? ORDER BY name', (g.user['id'],)).fetchall()
        connected = [account for account in accounts if connector.status(g.user['id'], account['id']).get('state') == 'connected']
        sends = db().execute('''SELECT s.*, p.name AS contact_name, a.name AS account_name FROM message_sends s
            JOIN contacts p ON p.id=s.contact_id JOIN zalo_accounts a ON a.id=s.account_id
            WHERE s.campaign_id=? ORDER BY s.id DESC''', (campaign_id,)).fetchall()
        return render_template('detail.html', campaign=campaign, recipients=recipients, logs=logs, preview=preview,
                               connected_accounts=connected, sends=sends, page='campaigns')

    @app.post('/campaigns/<int:campaign_id>/prepare-send')
    @login_required
    def prepare_send(campaign_id):
        campaign = db().execute('SELECT * FROM campaigns WHERE id=? AND user_id=?', (campaign_id, g.user['id'])).fetchone()
        if campaign is None:
            return 'Không tìm thấy chiến dịch.', 404
        person = next((p for p in audience(campaign) if str(p['id']) == request.form.get('contact_id')), None)
        account = db().execute('SELECT * FROM zalo_accounts WHERE id=? AND user_id=?',
                               (request.form.get('account_id'), g.user['id'])).fetchone()
        if not person or not account:
            return 'Tài khoản hoặc khách hàng không hợp lệ.', 400
        if not app.config['ZALO_QR_ENABLED']:
            return 'Chưa bật kết nối Zalo.', 503
        existing = db().execute('SELECT id FROM message_sends WHERE campaign_id=? AND contact_id=?', (campaign_id, person['id'])).fetchone()
        if existing:
            flash('Khách hàng đã có bản xem trước hoặc lần gửi trong chiến dịch này. Xem nhật ký bên dưới.', 'error')
            return redirect(url_for('campaign_detail', campaign_id=campaign_id))
        try:
            result = connector.message_action(g.user['id'], account['id'], 'resolve', phone=person['phone'])
        except Exception:
            result = {'state': 'failed'}
        if result.get('state') != 'resolved' or not str(result.get('uid', '')).isdigit():
            flash('Không tìm được người nhận Zalo. Kiểm tra số điện thoại, quyền tìm kiếm của người nhận hoặc đăng nhập QR lại.', 'error')
            return redirect(url_for('campaign_detail', campaign_id=campaign_id))
        # Recheck consent after the network request, before retaining a send preview.
        allowed = db().execute('SELECT consent FROM contacts WHERE id=? AND user_id=?', (person['id'], g.user['id'])).fetchone()
        if not allowed or not allowed['consent']:
            return 'Khách hàng đã thu hồi đồng ý nhận tin.', 400
        try:
            try:
                alias = personalize(campaign['rename_template'], person, result).strip() if campaign['rename_enabled'] else ''
                if campaign['rename_enabled'] and (not alias or len(alias) > 100):
                    raise ValueError('Tên gợi nhớ sau cá nhân hóa phải có từ 1 đến 100 ký tự.')
                invitation = personalize(campaign['friend_message'], person, result) if campaign['send_friend'] else ''
                rendered_message = personalize(campaign['message'], person, result) if campaign['send_message'] else ''
            except ValueError as error:
                flash(str(error), 'error')
                return redirect(url_for('campaign_detail', campaign_id=campaign_id))
            if len(rendered_message) > 2000:
                flash('Tin nhắn sau cá nhân hóa vượt 2000 ký tự.', 'error')
                return redirect(url_for('campaign_detail', campaign_id=campaign_id))
            if campaign['send_friend'] and len(invitation) > 150:
                flash('Lời mời sau khi chèn tên vượt 150 ký tự. Rút ngắn lời mời trước khi tạo bản xem trước.', 'error')
                return redirect(url_for('campaign_detail', campaign_id=campaign_id))
            db().execute('''INSERT INTO message_sends(campaign_id,contact_id,account_id,recipient_id,recipient_name,message,state,friend_message,friend_state,alias,alias_state)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)''', (campaign_id, person['id'], account['id'], result['uid'],
                str(result.get('name', ''))[:100], rendered_message,
                'prepared' if campaign['send_message'] else 'not_requested', invitation,
                'prepared' if campaign['send_friend'] else 'not_requested', alias,
                'prepared' if campaign['rename_enabled'] else 'not_requested'))
            db().commit()
            flash('Đã tìm thấy người nhận. Kiểm tra tên Zalo và nội dung trước khi xác nhận gửi thật bên dưới.', 'success')
        except sqlite3.IntegrityError:
            db().rollback()
            flash('Bản xem trước đã được tạo. Không tạo trùng.', 'error')
        return redirect(url_for('campaign_detail', campaign_id=campaign_id))

    @app.post('/campaigns/<int:campaign_id>/send/<int:send_id>')
    @login_required
    def send_message(campaign_id, send_id):
        record = db().execute('''SELECT s.*, p.consent, p.tag, c.tag AS campaign_tag FROM message_sends s
            JOIN campaigns c ON c.id=s.campaign_id JOIN contacts p ON p.id=s.contact_id
            JOIN zalo_accounts a ON a.id=s.account_id WHERE s.id=? AND c.id=? AND c.user_id=?
            AND p.user_id=c.user_id AND a.user_id=c.user_id''', (send_id, campaign_id, g.user['id'])).fetchone()
        if record is None:
            return 'Không tìm thấy lần gửi.', 404
        if request.form.get('confirm_send') != 'yes' or not record['consent']:
            return 'Cần xác nhận gửi và sự đồng ý của khách hàng.', 400
        campaign = db().execute('SELECT * FROM campaigns WHERE id=?', (campaign_id,)).fetchone()
        if record['contact_id'] not in {p['id'] for p in audience(campaign)}:
            return 'Khách hàng không còn thuộc nhóm chiến dịch.', 400
        if not app.config['ZALO_QR_ENABLED'] or connector.status(g.user['id'], record['account_id']).get('state') != 'connected':
            return 'Cần đăng nhập QR lại trước khi gửi.', 400
        # Persist the claim before dispatch. Double clicks and restarts cannot resend it.
        claimed = db().execute("UPDATE message_sends SET state='sending' WHERE id=? AND state='prepared'", (send_id,))
        db().commit()
        if not claimed.rowcount:
            flash('Lần gửi này đã được xử lý. Không gửi lại để tránh trùng tin.', 'error')
            return redirect(url_for('campaign_detail', campaign_id=campaign_id))
        try:
            result = connector.message_action(g.user['id'], record['account_id'], 'send',
                                              uid=record['recipient_id'], message=record['message'])
        except Exception:
            result = {'state': 'unknown'}
        state = result.get('state') if result.get('state') in ('sent', 'failed', 'unknown') else 'unknown'
        db().execute('UPDATE message_sends SET state=?, message_id=? WHERE id=?',
                     (state, str(result.get('message_id', ''))[:100] if state == 'sent' else '', send_id))
        db().commit()
        flash({'sent': 'Zalo đã tiếp nhận tin nhắn. Chưa xác nhận người nhận đã đọc.',
               'failed': 'Không gửi được tin. Kiểm tra phiên đăng nhập và kết nối VPS.',
               'unknown': 'Chưa xác định tin đã gửi hay chưa. Kiểm tra hội thoại trên Zalo; ứng dụng không tự gửi lại.'}[state],
              'success' if state == 'sent' else 'error')
        return redirect(url_for('campaign_detail', campaign_id=campaign_id))

    @app.post('/campaigns/<int:campaign_id>/friend/<int:send_id>')
    @login_required
    def send_friend_request(campaign_id, send_id):
        record = db().execute('''SELECT s.*, p.consent FROM message_sends s
            JOIN campaigns c ON c.id=s.campaign_id JOIN contacts p ON p.id=s.contact_id
            JOIN zalo_accounts a ON a.id=s.account_id WHERE s.id=? AND c.id=? AND c.user_id=?
            AND p.user_id=c.user_id AND a.user_id=c.user_id''', (send_id, campaign_id, g.user['id'])).fetchone()
        if record is None:
            return 'Không tìm thấy người nhận.', 404
        campaign = db().execute('SELECT * FROM campaigns WHERE id=?', (campaign_id,)).fetchone()
        if request.form.get('confirm_friend') != 'yes' or not record['consent'] or record['contact_id'] not in {p['id'] for p in audience(campaign)}:
            return 'Cần xác nhận lời mời và người nhận hợp lệ.', 400
        if not app.config['ZALO_QR_ENABLED'] or connector.status(g.user['id'], record['account_id']).get('state') != 'connected':
            return 'Cần đăng nhập QR lại.', 400
        claimed = db().execute("UPDATE message_sends SET friend_state='sending' WHERE id=? AND friend_state='prepared'", (send_id,))
        db().commit()
        if not claimed.rowcount:
            flash('Lời mời này đã được xử lý hoặc chưa được chọn. Không gửi lại.', 'error')
            return redirect(url_for('campaign_detail', campaign_id=campaign_id))
        try:
            result = connector.message_action(g.user['id'], record['account_id'], 'friend',
                uid=record['recipient_id'], message=record['friend_message'])
        except Exception:
            result = {'state': 'unknown'}
        state = result.get('state') if result.get('state') in ('friend_requested', 'failed', 'unknown') else 'unknown'
        db().execute('UPDATE message_sends SET friend_state=? WHERE id=?', (state, send_id))
        db().commit()
        flash({'friend_requested': 'Zalo đã tiếp nhận lời mời. Chưa xác nhận người nhận chấp nhận kết bạn.',
               'failed': 'Không gửi được lời mời. Kiểm tra phiên đăng nhập.',
               'unknown': 'Chưa xác định lời mời đã gửi hay chưa. Kiểm tra Zalo; không tự gửi lại.'}[state],
              'success' if state == 'friend_requested' else 'error')
        return redirect(url_for('campaign_detail', campaign_id=campaign_id))

    @app.post('/campaigns/<int:campaign_id>/alias/<int:send_id>')
    @login_required
    def change_alias(campaign_id, send_id):
        record = db().execute("""SELECT s.*,p.consent FROM message_sends s
            JOIN campaigns c ON c.id=s.campaign_id JOIN contacts p ON p.id=s.contact_id
            JOIN zalo_accounts a ON a.id=s.account_id WHERE s.id=? AND c.id=? AND c.user_id=?
            AND p.user_id=c.user_id AND a.user_id=c.user_id""", (send_id,campaign_id,g.user['id'])).fetchone()
        if record is None:
            return 'Không tìm thấy người nhận.',404
        campaign = db().execute('SELECT * FROM campaigns WHERE id=?',(campaign_id,)).fetchone()
        if request.form.get('confirm_alias') != 'yes' or not record['consent'] or record['contact_id'] not in {p['id'] for p in audience(campaign)}:
            return 'Cần xác nhận đổi tên và người nhận hợp lệ.',400
        if not app.config['ZALO_QR_ENABLED'] or connector.status(g.user['id'],record['account_id']).get('state') != 'connected':
            return 'Cần đăng nhập QR lại.',400
        claimed = db().execute("UPDATE message_sends SET alias_state='sending' WHERE id=? AND alias_state='prepared'",(send_id,))
        db().commit()
        if claimed.rowcount:
            try:
                result = connector.message_action(g.user['id'],record['account_id'],'alias',uid=record['recipient_id'],message=record['alias'])
            except Exception:
                result = {'state':'unknown'}
            state = result.get('state') if result.get('state') in ('renamed','failed','unknown') else 'unknown'
            db().execute('UPDATE message_sends SET alias_state=? WHERE id=?',(state,send_id))
            db().commit()
        return redirect(url_for('campaign_detail',campaign_id=campaign_id))

    @app.post('/campaigns/<int:campaign_id>/cancel-send/<int:send_id>')
    @login_required
    def cancel_send(campaign_id, send_id):
        db().execute('''DELETE FROM message_sends WHERE id=? AND campaign_id=? AND state IN ('prepared','not_requested')
            AND friend_state IN ('prepared','not_requested') AND alias_state IN ('prepared','not_requested')
            AND campaign_id IN (SELECT id FROM campaigns WHERE user_id=?)''', (send_id, campaign_id, g.user['id']))
        db().commit()
        return redirect(url_for('campaign_detail', campaign_id=campaign_id))

    @app.get('/settings')
    @login_required
    def settings():
        return render_template('settings.html', page='settings')

    @app.route('/accounts', methods=['GET', 'POST'])
    @login_required
    def accounts():
        if request.method == 'POST':
            try:
                name, group = field('name', 100), field('account_group', 80)
                if not name:
                    raise ValueError('Vui lòng nhập tên tài khoản.')
                cur = db().execute('INSERT INTO zalo_accounts(user_id,name,account_group) VALUES (?,?,?)',
                             (g.user['id'], name, group))
                db().commit()
                flash('Đã lưu hồ sơ tài khoản. Quét QR và xác nhận trên điện thoại để đăng nhập Zalo.', 'success')
                return redirect(url_for('accounts', connect=cur.lastrowid))
            except ValueError as error:
                flash(str(error), 'error')
            except sqlite3.IntegrityError:
                flash('Tên tài khoản đã có trong danh sách.', 'error')
            return redirect(url_for('accounts'))
        query = request.args.get('q', '').strip()[:100]
        group = request.args.get('group', '').strip()[:80]
        rows = db().execute('''SELECT * FROM zalo_accounts WHERE user_id=?
            AND name LIKE ? AND (?='' OR account_group=?) ORDER BY id DESC''',
            (g.user['id'], '%' + query + '%', group, group)).fetchall()
        groups = db().execute("SELECT DISTINCT account_group FROM zalo_accounts WHERE user_id=? AND account_group!='' ORDER BY account_group", (g.user['id'],)).fetchall()
        return render_template('accounts.html', accounts=rows, groups=groups,
                               query=query, group=group, page='accounts',
                               qr_enabled=app.config['ZALO_QR_ENABLED'],
                               auto_connect=request.args.get('connect', type=int),
                               connection_states={row['id']: connector.status(g.user['id'], row['id']) for row in rows})

    def own_account(account_id):
        return db().execute('SELECT * FROM zalo_accounts WHERE id=? AND user_id=?',
                            (account_id, g.user['id'])).fetchone()

    @app.route('/accounts/<int:account_id>/qr', methods=['GET', 'POST'])
    @login_required
    def account_qr(account_id):
        if own_account(account_id) is None:
            return jsonify(error='Không tìm thấy tài khoản.'), 404
        if request.method == 'GET':
            return jsonify(connector.status(g.user['id'], account_id))
        if not app.config['ZALO_QR_ENABLED']:
            return jsonify(error='Đăng nhập QR chưa được bật trên máy chủ.'), 503
        if request.form.get('accept_unofficial') != 'yes':
            return jsonify(error='Cần xác nhận sử dụng kết nối Zalo cá nhân không chính thức.'), 400
        try:
            return jsonify(connector.start(g.user['id'], account_id)), 202
        except (RuntimeError, OSError):
            return jsonify(error='Không thể khởi tạo QR. Kiểm tra Node.js, npm ci và quyền thư mục instance trên VPS.'), 503

    @app.post('/accounts/<int:account_id>/disconnect')
    @login_required
    def account_disconnect(account_id):
        if own_account(account_id) is None:
            return jsonify(error='Không tìm thấy tài khoản.'), 404
        connector.disconnect(g.user['id'], account_id)
        return jsonify(state='disconnected')

    return app


if __name__ == '__main__':
    create_app().run(host='0.0.0.0', port=int(os.environ.get('PORT', '8000')))
