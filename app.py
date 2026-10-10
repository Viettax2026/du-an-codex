import csv
import io
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from functools import wraps
from pathlib import Path

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


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
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8))
    if test_config:
        app.config.update(test_config)

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
        ''')

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
                db().execute('INSERT INTO contacts(user_id,name,phone,zalo_id,tag,consent) VALUES (?,?,?,?,?,?)',
                             (g.user['id'], name, phone, field('zalo_id', 100), field('tag', 80) or 'Khách hàng', int(request.form.get('consent') == 'on')))
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
                cur = db().execute('INSERT OR IGNORE INTO contacts(user_id,name,phone,tag,zalo_id,consent) VALUES (?,?,?,?,?,?)',
                                   (g.user['id'], name, phone, tag or 'Khách hàng', zalo_id, int((row.get('consent') or '').lower() in ('1', 'true', 'yes'))))
                count += cur.rowcount
                skipped += 1 - cur.rowcount
            db().commit()
            flash(f'Đã nhập {count} khách hàng, bỏ qua {skipped} số trùng.', 'success')
        except (UnicodeDecodeError, ValueError, csv.Error) as error:
            db().rollback()
            flash(f'Không thể nhập CSV: {error}', 'error')
        return redirect(url_for('contacts'))

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
                name, message, tag = field('name', 120), field('message', 2000), field('tag', 80)
                if not name or not message:
                    raise ValueError('Vui lòng nhập tên chiến dịch và nội dung.')
                cur = db().execute('INSERT INTO campaigns(user_id,name,message,tag) VALUES (?,?,?,?)', (g.user['id'], name, message, tag))
                db().commit()
                flash('Đã tạo chiến dịch. Kiểm tra nội dung trước khi gửi thử.', 'success')
                return redirect(url_for('campaign_detail', campaign_id=cur.lastrowid))
            except ValueError as error:
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
              AND (c.tag='' OR p.tag=c.tag)) AS audience
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
                               selected=selected, logs=logs, page='campaigns')

    @app.route('/campaigns/<int:campaign_id>', methods=['GET', 'POST'])
    @login_required
    def campaign_detail(campaign_id):
        campaign = db().execute('SELECT * FROM campaigns WHERE id=? AND user_id=?', (campaign_id, g.user['id'])).fetchone()
        if campaign is None:
            return 'Không tìm thấy chiến dịch.', 404
        recipients = db().execute("SELECT * FROM contacts WHERE user_id=? AND consent=1 AND (?='' OR tag=?) ORDER BY id", (g.user['id'], campaign['tag'], campaign['tag'])).fetchall()
        if request.method == 'POST':
            # The conditional update atomically claims a draft to prevent double submissions.
            cur = db().execute("UPDATE campaigns SET status='simulated' WHERE id=? AND user_id=? AND status='draft'", (campaign_id, g.user['id']))
            if not recipients or not cur.rowcount:
                db().rollback()
                flash('Cần có người đồng ý nhận tin và chiến dịch chưa gửi thử.', 'error')
            else:
                for person in recipients:
                    message = campaign['message'].replace('{{name}}', person['name'])
                    db().execute('INSERT INTO deliveries(campaign_id,contact_id,message) VALUES (?,?,?)', (campaign_id, person['id'], message))
                db().commit()
                flash(f'Đã mô phỏng {len(recipients)} tin nhắn. Chưa gửi tin đến Zalo.', 'success')
            return redirect(url_for('campaign_detail', campaign_id=campaign_id))
        logs = db().execute('SELECT d.*, c.name FROM deliveries d JOIN contacts c ON c.id=d.contact_id WHERE campaign_id=? ORDER BY d.id DESC', (campaign_id,)).fetchall()
        preview = campaign['message'].replace('{{name}}', recipients[0]['name'] if recipients else 'Nguyễn An')
        return render_template('detail.html', campaign=campaign, recipients=recipients, logs=logs, preview=preview, page='campaigns')

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
                db().execute('INSERT INTO zalo_accounts(user_id,name,account_group) VALUES (?,?,?)',
                             (g.user['id'], name, group))
                db().commit()
                flash('Đã lưu hồ sơ tài khoản. Hồ sơ chưa được kết nối với Zalo.', 'success')
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
                               query=query, group=group, page='accounts')

    return app


if __name__ == '__main__':
    create_app().run(host='0.0.0.0', port=int(os.environ.get('PORT', '8000')))
