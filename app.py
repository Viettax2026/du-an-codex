import csv
import click
import io
import json
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from zalo_connector import QRConnector
from personalization import personalize
from rich_message import read_message, render_message, load_styles, display_message
from data_import import read_contacts, insert_contact, default_contact_consent
from campaign_actions import initialize_campaign_actions, register_campaign_actions, parse_phones
from campaign_exclusions import exclusion_predicate, contact_is_excluded, save_exclusion_settings
from campaign_group_picker import read_snapshot_contacts, CAMPAIGN_CONTACT_LIMIT
from campaign_schedule import save_schedule
from campaign_limits import save_limits
from campaign_duplicates import save_duplicate_check
from campaign_details import inline_detail, TABS as DETAIL_TABS


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
                      MAX_CONTENT_LENGTH=12 * 1024 * 1024,
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

    @app.template_filter('localtime_seconds')
    def localtime_seconds(value):
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).astimezone(
            ZoneInfo('Asia/Bangkok')).strftime('%H:%M:%S %d/%m/%Y')

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
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, username TEXT UNIQUE NOT NULL,
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
        user_columns = {row['name'] for row in db().execute('PRAGMA table_info(users)')}
        if 'username' not in user_columns:
            db().execute('ALTER TABLE users RENAME COLUMN email TO username')
            db().commit()
        legacy_admin = db().execute(
            'SELECT id FROM users WHERE username=?', ('lienhe.viettaxco@gmail.com',)).fetchone()
        if legacy_admin:
            if db().execute('SELECT id FROM users WHERE lower(username)=?', ('admin',)).fetchone():
                raise RuntimeError('Không thể đổi tài khoản cũ: tên admin đã được sử dụng.')
            db().execute('UPDATE users SET username=? WHERE id=?', ('admin', legacy_admin['id']))
            db().commit()
        if 'account_id' not in {row['name'] for row in db().execute('PRAGMA table_info(campaigns)')}:
            db().execute('ALTER TABLE campaigns ADD COLUMN account_id INTEGER REFERENCES zalo_accounts(id)')
            db().commit()

        for table, columns in {
            'contacts': {**{column: "TEXT NOT NULL DEFAULT ''" for column in ('email','info1','info2','info3','info4','info5')}, 'deleted_at':'TEXT'},
            'campaigns': {'rename_enabled': 'INTEGER NOT NULL DEFAULT 0', 'rename_template': "TEXT NOT NULL DEFAULT ''", 'send_message': 'INTEGER NOT NULL DEFAULT 1', 'send_friend': 'INTEGER NOT NULL DEFAULT 0', 'friend_message': "TEXT NOT NULL DEFAULT ''"},
            'message_sends': {'alias': "TEXT NOT NULL DEFAULT ''", 'alias_state': "TEXT NOT NULL DEFAULT 'not_requested'", 'friend_message': "TEXT NOT NULL DEFAULT ''", 'friend_state': "TEXT NOT NULL DEFAULT 'not_requested'"},
        }.items():
            present = {row['name'] for row in db().execute(f'PRAGMA table_info({table})')}
            for column, declaration in columns.items():
                if column not in present:
                    db().execute(f'ALTER TABLE {table} ADD COLUMN {column} {declaration}')
        db().execute('CREATE INDEX IF NOT EXISTS contacts_active_user ON contacts(user_id,deleted_at)')
        db().commit()
        initialize_campaign_actions(db)

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
        db().execute('UPDATE campaigns SET message_html=? WHERE id=?', (g.get('campaign_message_html',''), campaign_id))

    def audience(campaign, apply_exclusions=True):
        return db().execute('''SELECT p.* FROM contacts p JOIN campaigns c ON c.user_id=p.user_id AND c.id=?
            WHERE p.user_id=? AND p.deleted_at IS NULL AND p.consent=1 AND
            ((c.audience_mode='list' AND p.id IN (SELECT contact_id FROM campaign_contacts WHERE campaign_id=c.id)) OR
             (c.audience_mode='group' AND (c.tag='' OR p.id IN (SELECT contact_id FROM contact_group_memberships WHERE user_id=p.user_id AND group_name=c.tag))))
             AND NOT '''+(exclusion_predicate() if apply_exclusions else '0')+' ORDER BY p.id', (campaign['id'],g.user['id'])).fetchall()

    def campaign_fields():
        if request.form.get('action', 'phone_message') not in ('phone_message', 'phone_actions'):
            raise ValueError('Chỉ hỗ trợ tìm theo số điện thoại và nhắn tin.')
        name, tag = field('name', 120), field('tag', 80)
        message, g.campaign_message_html = read_message(request.form)
        message_enabled, _, _ = action_settings()
        personalize(message, {}, strict=False)
        if request.form.get('send_friend') == 'yes':
            personalize(request.form.get('friend_message', ''), {}, strict=False)
        if not name or (message_enabled and not message):
            raise ValueError('Vui lòng nhập tên chiến dịch và nội dung.')
        account_id = request.form.get('account_id') or None
        if account_id and not db().execute('SELECT 1 FROM zalo_accounts WHERE id=? AND user_id=?', (account_id, g.user['id'])).fetchone():
            raise ValueError('Tài khoản Zalo không hợp lệ.')
        mode = request.form.get('data_mode')
        if mode not in (None, 'direct', 'group'):
            raise ValueError('Nguồn data không hợp lệ.')
        if mode == 'group':
            if not tag or not db().execute('SELECT 1 FROM contact_group_memberships WHERE user_id=? AND group_name=?', (g.user['id'], tag)).fetchone():
                raise ValueError('Chọn nhóm data hiện có.')
            return name, message, tag, account_id, []
        incoming = {phone: {'phone': phone} for phone in parse_phones(request.form.get('phones', ''))}
        incoming.update(read_contacts(request.files.get('data_file'), parse_phones))
        needs_confirmation = bool(incoming)
        for person in read_snapshot_contacts(db, g.user['id'], request.form.get('source_contact_ids','')):
            incoming.setdefault(person['phone'], dict(person))
        for source in request.form.getlist('source_tags'):
            metadata=db().execute('SELECT deleted_at FROM data_groups WHERE user_id=? AND name=?',(g.user['id'],source)).fetchone()
            if metadata and metadata['deleted_at']:
                raise ValueError('Nhóm data đã được lưu trữ. Chọn lại nhóm.')
            members=db().execute('SELECT * FROM contacts WHERE user_id=? AND consent=1 AND id IN (SELECT contact_id FROM contact_group_memberships WHERE user_id=contacts.user_id AND group_name=?)', (g.user['id'], source)).fetchall()
            if not members:
                raise ValueError('Nhóm data không có khách hàng đã đồng ý nhận tin.')
            for person in members:
                incoming.setdefault(person['phone'], dict(person))
        if len(incoming) > CAMPAIGN_CONTACT_LIMIT:
            raise ValueError('Danh sách chiến dịch tối đa 10.000 khách hàng.')
        if mode == 'direct' and not incoming:
            raise ValueError('Thêm ít nhất một số điện thoại hoặc chọn nhóm có khách hàng đồng ý nhận tin.')
        g.imported_contacts = incoming
        phones = list(incoming)
        if needs_confirmation and request.form.get('phones_consent') != 'yes':
            raise ValueError('Cần xác nhận các số điện thoại đã đồng ý nhận nội dung này.')
        return name, message, tag, account_id, phones

    def save_campaign_phones(campaign_id, phones):
        save_action_settings(campaign_id)
        save_exclusion_settings(db, g.user['id'], campaign_id)
        db().execute('UPDATE campaigns SET audience_mode=? WHERE id=?', ('list' if phones else 'group', campaign_id))
        db().execute('DELETE FROM campaign_contacts WHERE campaign_id=?', (campaign_id,))
        for phone in phones:
            insert_contact(db(), g.user['id'], phone, getattr(g, 'imported_contacts', {}).get(phone, {}))
            contact = db().execute('SELECT id FROM contacts WHERE user_id=? AND phone=?', (g.user['id'], phone)).fetchone()
            db().execute('INSERT INTO campaign_contacts(campaign_id,contact_id) VALUES (?,?)', (campaign_id, contact['id']))
        save_limits(db,campaign_id,request.form)
        save_duplicate_check(db,campaign_id,request.form)
        manager.set_media(campaign_id)
        save_schedule(db, campaign_id, request.form, request.form.get('account_id') or None)

    @app.before_request
    def security():
        g.user = None
        if request.blueprint == 'public_api':
            return  # The API blueprint requires bearer authentication for every route.
        session.setdefault('csrf', secrets.token_hex(24))
        if request.method == 'POST' and not secrets.compare_digest(
                session['csrf'], request.form.get('csrf', '')):
            return 'Phiên làm việc không hợp lệ. Vui lòng tải lại trang.', 400
        if session.get('user_id'):
            g.user = db().execute('SELECT id, name, username FROM users WHERE id=?',
                                  (session['user_id'],)).fetchone()

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        if request.endpoint in ('campaigns', 'edit_campaign', 'campaign_content'):
            response.headers['Content-Security-Policy'] += "; media-src 'self' blob:; img-src-elem 'self' data: blob:"
        if request.endpoint == 'preview_library_media' and response.mimetype == 'application/pdf':
            response.headers['X-Frame-Options'] = 'SAMEORIGIN'
            response.headers['Content-Security-Policy'] = response.headers['Content-Security-Policy'].replace("frame-ancestors 'none'", "frame-ancestors 'self'")
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

    manager = register_campaign_actions(app, db, login_required, audience, connector, personalize)
    manager.form_fields = campaign_fields
    manager.save_form_data = save_campaign_phones

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'POST':
            name, username, password = request.form.get('name', '').strip(), request.form.get('username', '').strip().lower(), request.form.get('password', '')
            if not name or len(name) > 100 or not re.fullmatch(r'[a-z0-9_.-]{3,64}', username) or not 10 <= len(password) <= 256:
                flash('Nhập họ tên, tài khoản từ 3 đến 64 ký tự (chữ không dấu, số, dấu chấm, gạch dưới hoặc gạch ngang) và mật khẩu từ 10 đến 256 ký tự.', 'error')
            else:
                try:
                    cur = db().execute('INSERT INTO users(name,username,password) VALUES (?,?,?)',
                                       (name, username, generate_password_hash(password)))
                    db().commit()
                    session.clear()
                    session['user_id'] = cur.lastrowid
                    session.permanent = True
                    return redirect(url_for('dashboard'))
                except sqlite3.IntegrityError:
                    flash('Tài khoản này đã được đăng ký.', 'error')
        return render_template('auth.html', register=True)

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            user = db().execute('SELECT * FROM users WHERE username=?', (request.form.get('username', '').strip().lower(),)).fetchone()
            password = request.form.get('password', '')
            if user and len(password) <= 256 and check_password_hash(user['password'], password):
                session.clear()
                session['user_id'] = user['id']
                session.permanent = True
                return redirect(url_for('dashboard'))
            flash('Tài khoản hoặc mật khẩu chưa đúng.', 'error')
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
            'contacts': db().execute('SELECT count(*) FROM contacts WHERE user_id=? AND deleted_at IS NULL', (uid,)).fetchone()[0],
            'consent': db().execute('SELECT count(*) FROM contacts WHERE user_id=? AND deleted_at IS NULL AND consent=1', (uid,)).fetchone()[0],
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
                inserted = db().execute('INSERT INTO contacts(user_id,name,phone,zalo_id,tag,consent,email,info1,info2,info3,info4,info5) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,phone) DO UPDATE SET deleted_at=NULL,consent=excluded.consent WHERE contacts.deleted_at IS NOT NULL',
                             (g.user['id'], name, phone, field('zalo_id', 100), field('tag', 80) or 'Khách hàng', default_contact_consent(request.form, 'on'),
                              field('email',254), *(field(f'info{i}',500) for i in range(1,6))))
                db().commit()
                flash('Đã thêm khách hàng.' if inserted.rowcount else 'Số điện thoại đã có trong danh sách.', 'success' if inserted.rowcount else 'error')
            except ValueError as error:
                flash(str(error), 'error')
            except sqlite3.IntegrityError:
                flash('Số điện thoại đã có trong danh sách.', 'error')
            return redirect(url_for('contacts'))
        query = request.args.get('q', '').strip()
        rows = db().execute('SELECT * FROM contacts WHERE user_id=? AND deleted_at IS NULL AND (name LIKE ? OR phone LIKE ? OR tag LIKE ?) ORDER BY id DESC',
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
            data = upload.read(2 * 1024 * 1024 + 1)
            if len(data) > 2 * 1024 * 1024:
                raise ValueError('CSV không vượt quá 2 MB.')
            reader = csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
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
                cur = db().execute('INSERT INTO contacts(user_id,name,phone,tag,zalo_id,consent,email,info1,info2,info3,info4,info5) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,phone) DO UPDATE SET deleted_at=NULL,consent=excluded.consent WHERE contacts.deleted_at IS NOT NULL',
                                   (g.user['id'], name, phone, tag or 'Khách hàng', zalo_id, int(not (row.get('consent') or '').strip() or (row.get('consent') or '').strip().lower() in ('1', 'true', 'yes')), *extra))
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
        person = db().execute('SELECT * FROM contacts WHERE id=? AND user_id=? AND deleted_at IS NULL', (contact_id,g.user['id'])).fetchone()
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
        db().execute('UPDATE contacts SET consent=1-consent WHERE id=? AND user_id=? AND deleted_at IS NULL', (contact_id, g.user['id']))
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
                manager.event(cur.lastrowid, 'create', 'Tạo chiến dịch mới. Chưa gửi tin.')
                db().commit()
                flash('Đã tạo chiến dịch. Kiểm tra nội dung trước khi gửi thử.', 'success')
                return redirect(url_for('campaign_detail', campaign_id=cur.lastrowid))
            except ValueError as error:
                db().rollback()
                flash(str(error), 'error')
                return redirect(url_for('campaigns'))
        query = request.args.get('q', '').strip()[:120]
        status = request.args.get('status', '')
        status = status if status in ('draft', 'simulated', 'paused', 'deleted', 'running', 'complete', 'pending', 'review', 'error') else ''
        days = request.args.get('days', '')
        days = days if days in ('7', '30', '90') else ''
        tag = request.args.get('tag', '').strip()[:80]
        accounts = db().execute('SELECT * FROM zalo_accounts WHERE user_id=? ORDER BY name', (g.user['id'],)).fetchall()
        account_id = request.args.get('account_id', '')
        log_account_id = request.args.get('log_account_id', '')
        valid_accounts = {str(row['id']) for row in accounts}
        if any(value and value not in valid_accounts for value in (account_id, log_account_id)):
            abort(404)
        kind = request.args.get('kind', '')
        if kind not in ('', 'message', 'friend', 'both'):
            abort(400)
        rows = db().execute(f'''SELECT c.*,a.name AS account_name,
            (SELECT group_concat(DISTINCT za.name) FROM message_sends ms JOIN zalo_accounts za ON za.id=ms.account_id AND za.user_id=c.user_id WHERE ms.campaign_id=c.id) AS used_accounts,
            coalesce(r.sent_total,0) AS sent_total,coalesce(r.confirmed,0) AS confirmed,coalesce(r.skipped,0) AS skipped,
            coalesce(r.waiting,0) AS waiting,coalesce(r.sending,0) AS sending,
            coalesce(r.uncertain,0) AS uncertain,coalesce(r.failed,0) AS failed,
            (SELECT count(*) FROM deliveries d WHERE d.campaign_id=c.id) AS total,
            (SELECT count(*) FROM contacts p WHERE p.user_id=c.user_id AND p.deleted_at IS NULL AND p.consent=1
              AND ((c.audience_mode='list' AND p.id IN (SELECT contact_id FROM campaign_contacts WHERE campaign_id=c.id)) OR
                   (c.audience_mode='group' AND (c.tag='' OR p.id IN (SELECT contact_id FROM contact_group_memberships WHERE user_id=p.user_id AND group_name=c.tag)))) AND NOT {exclusion_predicate()}) AS audience
            FROM campaigns c LEFT JOIN zalo_accounts a ON a.id=c.account_id AND a.user_id=c.user_id
            LEFT JOIN (SELECT campaign_id,count(*) AS sent_total,
                sum((state='sent' OR friend_state='friend_requested' OR alias_state='renamed') AND state IN ('sent','not_requested') AND friend_state IN ('friend_requested','not_requested') AND alias_state IN ('renamed','not_requested')) AS confirmed,
                sum(state='not_requested' AND friend_state='not_requested' AND alias_state='not_requested') AS skipped,
                sum(state='prepared' OR friend_state='prepared' OR alias_state='prepared') AS waiting,
                sum(state='sending' OR friend_state='sending' OR alias_state='sending') AS sending,
                sum(state='unknown' OR friend_state='unknown' OR alias_state='unknown') AS uncertain,
                sum(state='failed' OR friend_state='failed' OR alias_state='failed') AS failed
                FROM message_sends GROUP BY campaign_id) r ON r.campaign_id=c.id
            WHERE c.user_id=? AND c.name LIKE ?
              AND ((?='deleted' AND c.deleted_at IS NOT NULL) OR (?!='deleted' AND c.deleted_at IS NULL))
              AND (?='' OR c.tag=?)
              AND (?='' OR c.created_at >= datetime('now', ?)) AND (?='' OR c.account_id=?)
              AND (?='' OR (?='message' AND c.send_message=1 AND c.send_friend=0)
                  OR (?='friend' AND c.send_message=0 AND c.send_friend=1) OR (?='both' AND c.send_message=1 AND c.send_friend=1))
              ORDER BY c.id DESC''',
            (g.user['id'], '%' + query + '%', status, status, tag, tag,
             days, '-' + (days or '0') + ' days', account_id, account_id, kind, kind, kind, kind)).fetchall()
        rows = [dict(row) for row in rows]
        for row in rows:
            if row['deleted_at']:
                state, label, tone = 'deleted', 'Đã xóa', 'muted'
            elif row['paused']:
                state, label, tone = 'paused', 'Tạm ngưng', 'paused'
            elif row['sending']:
                state, label, tone = 'running', 'Đang xử lý', 'draft'
            elif row['uncertain']:
                state, label, tone = 'review', 'Cần kiểm tra', 'warning'
            elif row['failed'] or row['schedule_error']:
                state, label, tone = 'error', 'Có lỗi', 'warning'
            elif row['sent_total'] and row['confirmed']+row['skipped']>=max(row['audience'],row['sent_total']):
                state, label, tone = 'complete', 'Đã xử lý', 'complete'
            elif row['schedule_enabled']:
                state, label, tone = 'running', 'Đang xử lý', 'draft'
            elif row['waiting']:
                state, label, tone = 'pending', 'Chờ xác nhận', 'draft'
            elif row['sent_total']:
                state, label, tone = 'running', 'Đang xử lý', 'draft'
            elif row['status']=='simulated':
                state, label, tone = 'simulated', 'Đã mô phỏng', 'complete'
            else:
                state, label, tone = 'draft', 'Bản nháp', 'draft'
            row.update(display_state=state, display_status=label, status_tone=tone,
                       progress_done=row['confirmed']+row['skipped'] if row['sent_total'] else row['total'],
                       progress_total=max(row['audience'],row['sent_total'] or row['total']),
                       progress_basis='Đã xử lý (gửi / bỏ qua)' if row['skipped'] else 'Gửi qua Zalo' if row['sent_total'] else 'Mô phỏng')
            row['progress_percent'] = min(100,round(100*row['progress_done']/row['progress_total'])) if row['progress_total'] else 0
        if status:
            rows=[row for row in rows if row['display_state']==status]
        tags = db().execute('SELECT DISTINCT group_name AS tag FROM contact_group_memberships WHERE user_id=? ORDER BY tag', (g.user['id'],)).fetchall()
        selected_id = request.args.get('selected', type=int)
        selected = next((row for row in rows if row['id'] == selected_id), None)
        detail_tab=request.args.get('detail_tab','info')
        if detail_tab not in DETAIL_TABS:
            abort(400)
        detail=inline_detail(db,selected,detail_tab,request.args.get('detail_page',1,type=int),connector) if selected else None
        logs = []
        if selected:
            if not log_account_id:
                logs.extend(dict(row, log_type='simulation') for row in db().execute('''SELECT d.*, p.name FROM deliveries d
                    JOIN contacts p ON p.id=d.contact_id AND p.user_id=? WHERE d.campaign_id=?
                    ORDER BY d.id DESC LIMIT 100''', (g.user['id'],selected['id'])))
            logs.extend(dict(row, log_type='zalo') for row in db().execute('''SELECT s.*,a.name AS account_name FROM message_sends s
                JOIN zalo_accounts a ON a.id=s.account_id AND a.user_id=? WHERE s.campaign_id=? AND (?='' OR s.account_id=?)
                ORDER BY s.id DESC LIMIT 100''', (g.user['id'],selected['id'],log_account_id,log_account_id)))
            logs = sorted(logs,key=lambda item:(item['created_at'],item['id']),reverse=True)[:100]
        def campaign_link(**changes):
            values=dict(q=query,days=days,status=status,tag=tag,account_id=account_id,kind=kind,log_account_id=log_account_id,detail_tab=detail_tab)
            if selected:
                values['selected']=selected['id']
            values.update(changes)
            return url_for('campaigns',**values)
        return render_template('campaigns.html', campaigns=rows, tags=tags,
                               query=query, status=status, days=days, tag=tag,kind=kind,
                               account_id=account_id,log_account_id=log_account_id,campaign_link=campaign_link,
                               selected=selected, logs=logs, detail=detail, page='campaigns', accounts=accounts)

    @app.route('/campaigns/<int:campaign_id>/edit', methods=['GET', 'POST'])
    @login_required
    def edit_campaign(campaign_id):
        if request.method == 'POST':
            db().execute('BEGIN IMMEDIATE')
        campaign = manager.owned(campaign_id)
        if campaign['status'] != 'draft' or db().execute('SELECT 1 FROM message_sends WHERE campaign_id=?', (campaign_id,)).fetchone():
            flash('Chiến dịch đã mô phỏng hoặc có lần gửi/xem trước. Không sửa để giữ nguyên nội dung nhật ký.', 'error')
            return redirect(url_for('campaign_detail', campaign_id=campaign_id))
        if request.method == 'POST':
            try:
                name, message, tag, account_id, phones = campaign_fields()
                db().execute('UPDATE campaigns SET name=?,message=?,tag=?,account_id=? WHERE id=?', (name, message, tag, account_id, campaign_id))
                save_campaign_phones(campaign_id, phones)
                manager.event(campaign_id, 'edit', 'Sửa cài đặt chiến dịch.')
                db().commit()
                flash('Đã lưu chiến dịch. Chưa gửi tin.', 'success')
                return redirect(url_for('campaign_detail', campaign_id=campaign_id))
            except ValueError as error:
                db().rollback()
                flash(str(error), 'error')
        members = db().execute('SELECT p.id,p.name,p.phone FROM contacts p JOIN campaign_contacts cc ON cc.contact_id=p.id WHERE cc.campaign_id=? AND p.user_id=? AND p.deleted_at IS NULL ORDER BY p.id', (campaign_id,g.user['id'])).fetchall()
        snapshot = [dict(row) for row in members] if len(members)>500 else []
        return render_template('campaign_edit.html', campaign=campaign, phones='' if snapshot else '\n'.join(p['phone'] for p in members), snapshot_contacts=snapshot,
            accounts=db().execute('SELECT * FROM zalo_accounts WHERE user_id=? ORDER BY name', (g.user['id'],)).fetchall(),
            tags=db().execute('SELECT DISTINCT group_name AS tag FROM contact_group_memberships WHERE user_id=? ORDER BY tag', (g.user['id'],)).fetchall(), page='campaigns')

    @app.route('/campaigns/<int:campaign_id>', methods=['GET', 'POST'])
    @login_required
    def campaign_detail(campaign_id):
        campaign = manager.owned(campaign_id)
        recipients = audience(campaign)
        if request.method == 'POST':
            db().execute('BEGIN IMMEDIATE')
            campaign = manager.owned(campaign_id)
            manager.require_active(campaign)
            recipients = audience(campaign)
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
                    for variant_index, person in enumerate(recipients):
                        message, styles = render_message(campaign['message'], campaign['message_html'], person, strict=False, variant_index=variant_index)
                        db().execute('INSERT INTO deliveries(campaign_id,contact_id,message,message_styles) VALUES (?,?,?,?)', (campaign_id, person['id'], message, json.dumps(styles)))
                    manager.event(campaign_id, 'simulate', f'Mô phỏng {len(recipients)} tin nhắn; chưa gửi Zalo.')
                    db().commit()
                    flash(f'Đã mô phỏng {len(recipients)} tin nhắn. Chưa gửi tin đến Zalo.', 'success')
                except ValueError as error:
                    db().rollback()
                    flash(str(error), 'error')
            return redirect(url_for('campaign_detail', campaign_id=campaign_id))
        logs = db().execute('SELECT d.*, c.name FROM deliveries d JOIN contacts c ON c.id=d.contact_id WHERE campaign_id=? ORDER BY d.id DESC', (campaign_id,)).fetchall()
        try:
            preview_text, preview_styles = render_message(campaign['message'], campaign['message_html'], recipients[0] if recipients else {'name':'Nguyễn An'}, strict=False, variant_index=campaign['next_message_variant'])
            preview = display_message(preview_text, json.dumps(preview_styles))
        except ValueError as error:
            preview = str(error)
        accounts = db().execute('SELECT * FROM zalo_accounts WHERE user_id=? ORDER BY name', (g.user['id'],)).fetchall()
        connected = [account for account in accounts if connector.status(g.user['id'], account['id']).get('state') == 'connected']
        sends = db().execute('''SELECT s.*, p.name AS contact_name, a.name AS account_name FROM message_sends s
            JOIN contacts p ON p.id=s.contact_id JOIN zalo_accounts a ON a.id=s.account_id
            WHERE s.campaign_id=? ORDER BY s.id DESC''', (campaign_id,)).fetchall()
        return render_template('detail.html', campaign=campaign, recipients=recipients, logs=logs, preview=preview,
                               connected_accounts=connected, sends=sends, eligible_ids={p['id'] for p in recipients}, page='campaigns')

    @app.post('/campaigns/<int:campaign_id>/prepare-send')
    @login_required
    def prepare_send(campaign_id):
        campaign = manager.owned(campaign_id)
        manager.require_active(campaign)
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
        if not isinstance(result,dict) or result.get('state') not in ('resolved','not_found') or (result['state']=='resolved' and not str(result.get('uid','')).isdigit()):
            flash('Không tìm được người nhận Zalo. Kiểm tra số điện thoại, quyền tìm kiếm của người nhận hoặc đăng nhập QR lại.', 'error')
            return redirect(url_for('campaign_detail', campaign_id=campaign_id))
        db().execute('BEGIN IMMEDIATE')
        campaign = manager.owned(campaign_id)
        manager.require_active(campaign)
        person = next((p for p in audience(campaign) if p['id'] == person['id']), None)
        if person is None:
            return 'Khách hàng không còn thuộc chiến dịch.', 400
        if result['state']=='resolved' and contact_is_excluded(db, g.user['id'], campaign_id, person['id'], result['uid']):
            return 'Người nhận Zalo thuộc danh sách loại trừ của chiến dịch.', 400
        # Recheck consent after the network request, before retaining a send preview.
        allowed = db().execute('SELECT consent FROM contacts WHERE id=? AND user_id=?', (person['id'], g.user['id'])).fetchone()
        if not allowed or not allowed['consent']:
            return 'Khách hàng đã thu hồi đồng ý nhận tin.', 400
        try:
            try:
                if result['state']=='not_found':
                    manager.store_lookup_skip(campaign,person,account)
                else:
                    manager.store_preview(campaign,person,account,result)
            except ValueError as error:
                flash(str(error),'error')
                return redirect(url_for('campaign_detail',campaign_id=campaign_id))
            db().commit()
            flash('Đã bỏ qua số không tìm thấy Zalo. Chọn số tiếp theo trong danh sách.' if result['state']=='not_found' else 'Đã tìm thấy người nhận. Kiểm tra tên Zalo và nội dung trước khi xác nhận gửi thật bên dưới.', 'success')
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
        attachment = None
        if record['media_id']:
            try:
                attachment = manager.attachment(record['media_id'])
            except ValueError as error:
                return str(error), 400
        try:
            styles = load_styles(record['message_styles'], record['message'])
        except ValueError as error:
            return str(error), 400
        claimed = manager.claim(campaign_id, send_id, 'send', record)
        if not claimed:
            flash('Lần gửi này đã được xử lý. Không gửi lại để tránh trùng tin.', 'error')
            return redirect(url_for('campaign_detail', campaign_id=campaign_id))
        try:
            result = connector.message_action(g.user['id'], record['account_id'], 'send',
                                              uid=record['recipient_id'], message=record['message'],
                                              **({'attachment': attachment} if attachment else {}),
                                              **({'styles': styles} if styles else {}))
        except Exception:
            result = {'state': 'unknown'}
        state = result.get('state') if result.get('state') in ('sent', 'failed', 'unknown') else 'unknown'
        db().execute('UPDATE message_sends SET state=?, message_id=? WHERE id=?',
                     (state, str(result.get('message_id', ''))[:100] if state == 'sent' else '', send_id))
        manager.result(campaign_id, 'send', send_id, state)
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
        claimed = manager.claim(campaign_id, send_id, 'friend', record)
        if not claimed:
            flash('Lời mời này đã được xử lý hoặc chưa được chọn. Không gửi lại.', 'error')
            return redirect(url_for('campaign_detail', campaign_id=campaign_id))
        try:
            result = connector.message_action(g.user['id'], record['account_id'], 'friend',
                uid=record['recipient_id'], message=record['friend_message'])
        except Exception:
            result = {'state': 'unknown'}
        state = result.get('state') if result.get('state') in ('friend_requested', 'failed', 'unknown') else 'unknown'
        db().execute('UPDATE message_sends SET friend_state=? WHERE id=?', (state, send_id))
        manager.result(campaign_id, 'friend', send_id, state)
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
        claimed = manager.claim(campaign_id, send_id, 'alias', record)
        if claimed:
            try:
                result = connector.message_action(g.user['id'],record['account_id'],'alias',uid=record['recipient_id'],message=record['alias'])
            except Exception:
                result = {'state':'unknown'}
            state = result.get('state') if result.get('state') in ('renamed','failed','unknown') else 'unknown'
            db().execute('UPDATE message_sends SET alias_state=? WHERE id=?',(state,send_id))
            manager.result(campaign_id, 'alias', send_id, state)
            db().commit()
        return redirect(url_for('campaign_detail',campaign_id=campaign_id))

    @app.post('/campaigns/<int:campaign_id>/cancel-send/<int:send_id>')
    @login_required
    def cancel_send(campaign_id, send_id):
        manager.owned(campaign_id)
        scheduled = db().execute('SELECT scheduled FROM message_sends WHERE id=? AND campaign_id=?',(send_id,campaign_id)).fetchone()
        removed = db().execute('''DELETE FROM message_sends WHERE id=? AND campaign_id=? AND state IN ('prepared','not_requested')
            AND friend_state IN ('prepared','not_requested') AND alias_state IN ('prepared','not_requested')
            AND (state='prepared' OR friend_state='prepared' OR alias_state='prepared')
            AND campaign_id IN (SELECT id FROM campaigns WHERE user_id=?)''', (send_id, campaign_id, g.user['id']))
        if removed.rowcount:
            if scheduled and scheduled['scheduled']:
                db().execute("UPDATE campaigns SET schedule_enabled=0,schedule_revision=schedule_revision+1,schedule_status='Chưa bật lịch' WHERE id=?",(campaign_id,))
            manager.event(campaign_id, 'cancel_preview', f'Hủy bản xem trước #{send_id}, chưa thực hiện hành động nào.')
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

    @app.cli.command('reset-admin')
    @click.password_option(prompt='Mật khẩu mới cho admin', confirmation_prompt='Nhập lại mật khẩu mới')
    def reset_admin(password):
        """Create admin or reset its password while preserving existing data."""
        if not 10 <= len(password) <= 256:
            raise click.ClickException('Mật khẩu phải từ 10 đến 256 ký tự.')
        user = db().execute('SELECT id FROM users WHERE username=?', ('admin',)).fetchone()
        password_hash = generate_password_hash(password)
        if user:
            db().execute('UPDATE users SET password=? WHERE id=?', (password_hash, user['id']))
        else:
            db().execute('INSERT INTO users(name,username,password) VALUES (?,?,?)',
                         ('Admin', 'admin', password_hash))
        db().commit()
        click.echo('Đã đặt mật khẩu mới cho tài khoản admin. Dữ liệu hiện có được giữ nguyên.')

    from data_groups import register_data_groups
    register_data_groups(app, db, login_required, parse_phones)
    from media_library import register_media_library
    register_media_library(app, db, login_required, manager)
    from campaign_exclusions import register_campaign_exclusions
    register_campaign_exclusions(app, db, login_required, manager, parse_phones)
    from campaign_group_picker import register_campaign_group_picker
    register_campaign_group_picker(app, db, login_required)
    from contact_management import register_contact_management
    register_contact_management(app, db, login_required)
    from campaign_duplicates import register_campaign_duplicates
    register_campaign_duplicates(app, db, login_required, manager)
    from campaign_limits import register_campaign_limits
    register_campaign_limits(app, db, login_required, manager)
    from campaign_schedule import register_campaign_schedule
    register_campaign_schedule(app, db, login_required, manager, connector, audience)
    from message_composer import register_message_composer
    register_message_composer(app, db, login_required, manager)
    from public_api import register_public_api
    register_public_api(app, db, login_required, manager, parse_phones)
    from data_groups import purge_archived_groups
    purge_archived_groups(app, db)
    return app


if __name__ == '__main__':
    create_app().run(host='0.0.0.0', port=int(os.environ.get('PORT', '8000')))
