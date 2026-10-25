"""Campaign operations, immutable attachments and serialized dispatch limits."""
import csv
import json
import io
import os
import re
import uuid
import warnings
from pathlib import Path

from flask import abort, flash, g, redirect, render_template, request, send_file, url_for
from PIL import Image
from data_import import read_contacts, insert_contact
from campaign_exclusions import contact_is_excluded
from campaign_group_picker import CAMPAIGN_CONTACT_LIMIT
from werkzeug.utils import secure_filename
from rich_message import read_message, display_message, parse_html, markup, render_message, utf16
from personalization import personalize
from campaign_limits import enforce_limits, save_limits, LIMIT_COLUMNS
from campaign_duplicates import DuplicateMessageBlocked, recent_for_record, DUPLICATE_COLUMNS
from campaign_errors import diagnostics,error_description


ACTION_COLUMNS = {'send': ('state', 'message_limit'), 'friend': ('friend_state', 'friend_limit'),
                  'alias': ('alias_state', 'alias_limit')}
STATE_LABELS = {'prepared': 'Chờ xác nhận', 'sending': 'Đang xử lý / cần kiểm tra',
                'sent': 'Zalo đã tiếp nhận', 'friend_requested': 'Đã tiếp nhận lời mời',
                'renamed': 'Đã đổi tên gợi nhớ', 'failed': 'Thất bại',
                'unknown': 'Chưa xác định', 'not_requested': 'Không chọn'}


def initialize_campaign_actions(db):
    columns = {
        'campaigns': {'next_message_variant': 'INTEGER NOT NULL DEFAULT 0', 'message_html': "TEXT NOT NULL DEFAULT ''", 'paused': 'INTEGER NOT NULL DEFAULT 0', 'deleted_at': 'TEXT',
                      'audience_mode': "TEXT NOT NULL DEFAULT 'group'", 'media_id': 'INTEGER',
                      'message_limit': 'INTEGER NOT NULL DEFAULT 0', 'friend_limit': 'INTEGER NOT NULL DEFAULT 0',
                      'alias_limit': 'INTEGER NOT NULL DEFAULT 0', 'interval_seconds': 'INTEGER NOT NULL DEFAULT 0'},
        'message_sends': {'media_id': 'INTEGER', 'message_styles': "TEXT NOT NULL DEFAULT '[]'", 'lookup_state': "TEXT NOT NULL DEFAULT ''"},
        'deliveries': {'message_styles': "TEXT NOT NULL DEFAULT '[]'"},
    }
    for table, fields in columns.items():
        present = {row['name'] for row in db().execute(f'PRAGMA table_info({table})')}
        for column, declaration in fields.items():
            if column not in present:
                db().execute(f'ALTER TABLE {table} ADD COLUMN {column} {declaration}')
                if column == 'audience_mode':
                    db().execute("UPDATE campaigns SET audience_mode='list' WHERE id IN (SELECT campaign_id FROM campaign_contacts)")
    db().executescript('''
        CREATE TABLE IF NOT EXISTS campaign_events (
            id INTEGER PRIMARY KEY, campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
            kind TEXT NOT NULL, detail TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS campaign_events_campaign ON campaign_events(campaign_id,id);
        CREATE TABLE IF NOT EXISTS campaign_attempts (
            id INTEGER PRIMARY KEY, campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
            send_id INTEGER NOT NULL REFERENCES message_sends(id), action TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(send_id,action));
        CREATE INDEX IF NOT EXISTS campaign_attempts_window ON campaign_attempts(campaign_id,created_at);
        CREATE TABLE IF NOT EXISTS campaign_media (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            storage_name TEXT UNIQUE NOT NULL, filename TEXT NOT NULL, mime TEXT NOT NULL,
            size INTEGER NOT NULL, width INTEGER, height INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    ''')
    attempt_columns={row['name'] for row in db().execute('PRAGMA table_info(campaign_attempts)')}
    for column in ('error_reason','error_code'):
        if column not in attempt_columns:
            db().execute(f"ALTER TABLE campaign_attempts ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    # Preserve prior dispatches in the limit counters; never grant extra sends on upgrade.
    for action, (column, _) in ACTION_COLUMNS.items():
        db().execute(f'''INSERT OR IGNORE INTO campaign_attempts(campaign_id,send_id,action,created_at)
            SELECT campaign_id,id,?,created_at FROM message_sends
            WHERE {column} NOT IN ('prepared','not_requested')''', (action,))
    if 'completed_at' not in {row['name'] for row in db().execute('PRAGMA table_info(campaign_attempts)')}:
        db().execute('ALTER TABLE campaign_attempts ADD COLUMN completed_at TEXT')
        # Recover completion times from existing result events where available.
        for action in ('send','friend','alias'):
            db().execute('''UPDATE campaign_attempts SET completed_at=(
                SELECT e.created_at FROM campaign_events e WHERE e.campaign_id=campaign_attempts.campaign_id
                AND e.kind=? AND e.detail LIKE '% · Bản gửi #' || campaign_attempts.send_id || ': %'
                ORDER BY e.id DESC LIMIT 1) WHERE action=?''',(action+'_result',action))
    db().commit()


def parse_phones(raw):
    if len(raw) > 15000:
        raise ValueError('Danh sách số điện thoại quá dài.')
    phones = []
    for value in re.split(r'[\n,;]+', raw.strip()):
        phone = re.sub(r'[\s().+-]', '', value)
        if not phone:
            continue
        if phone.startswith('84'):
            phone = '0' + phone[2:]
        if not re.fullmatch(r'0[0-9]{9}', phone):
            raise ValueError('Số điện thoại Việt Nam cần 10 chữ số, bắt đầu bằng 0 (hoặc dùng +84).')
        if phone not in phones:
            phones.append(phone)
    if len(phones) > 500:
        raise ValueError('Mỗi lần nhập tối đa 500 số điện thoại.')
    return phones


class CampaignManager:
    def __init__(self, app, db, audience):
        self.db, self.audience = db, audience
        self.media_root = Path(app.config.get('MEDIA_ROOT') or Path(app.config['DATABASE']).parent / 'media')

    def owned(self, campaign_id, include_deleted=False):
        row = self.db().execute('SELECT * FROM campaigns WHERE id=? AND user_id=?',
                                (campaign_id, g.user['id'])).fetchone()
        if row is None or (row['deleted_at'] and not include_deleted):
            abort(404, 'Không tìm thấy chiến dịch.')
        return row

    def event(self, campaign_id, kind, detail):
        self.db().execute('INSERT INTO campaign_events(campaign_id,kind,detail) VALUES (?,?,?)',
                          (campaign_id, kind, detail))

    def require_active(self, campaign):
        if campaign['paused'] or campaign['deleted_at']:
            abort(409, 'Chiến dịch đã dừng hoặc đã xóa. Không thực hiện thêm hành động.')

    def claim(self, campaign_id, send_id, action, expected, guard=None):
        """One writer checks stop, consent, quota and idempotency before dispatch."""
        column, quota = ACTION_COLUMNS[action]
        connection = self.db()
        connection.execute('BEGIN IMMEDIATE')
        try:
            campaign = self.owned(campaign_id)
            self.require_active(campaign)
            row = connection.execute(f'SELECT * FROM message_sends WHERE id=? AND campaign_id=?',
                                      (send_id, campaign_id)).fetchone()
            if row is None or row[column] != 'prepared' or row['schedule_skip_reason']:
                connection.rollback()
                return False
            if guard is not None:
                guard(campaign,row)
            elif campaign['schedule_enabled']:
                from campaign_schedule import manual_schedule_block
                schedule_error=manual_schedule_block(campaign)
                if schedule_error:
                    abort(409,schedule_error)
            snapshot_fields = ('contact_id', 'account_id', 'recipient_id', 'message', 'friend_message', 'alias', 'media_id', 'message_styles', 'recipient_phone')
            if any(row[key] != expected[key] for key in snapshot_fields):
                abort(409, 'Bản xem trước đã thay đổi trong tab khác. Tải lại để kiểm tra và xác nhận đúng nội dung.')
            if row['contact_id'] not in {p['id'] for p in self.audience(campaign)}:
                abort(400, 'Khách hàng không còn đồng ý hoặc không thuộc chiến dịch.')
            if contact_is_excluded(self.db, g.user['id'], campaign_id, row['contact_id'], row['recipient_id']):
                abort(400, 'Người nhận thuộc danh sách loại trừ của chiến dịch.')
            if action=='send':
                recent=recent_for_record(self.db,campaign,row)
                if recent is not None:
                    raise DuplicateMessageBlocked(recent,campaign['duplicate_days'])
            # Automatic spacing is persisted between recipients, while manual
            # confirmations retain the shared interval between actions.
            enforce_limits(self.db,campaign,action,check_interval=guard is None)
            connection.execute(f"UPDATE message_sends SET {column}='sending' WHERE id=?", (send_id,))
            if guard is not None:
                connection.execute('UPDATE message_sends SET schedule_turn_finished=0 WHERE id=?',(send_id,))
                if row['schedule_turn_finished']:
                    self.event(campaign_id,'schedule_recipient_resume',f'Tiếp tục xử lý {row["recipient_phone"]}: thực hiện hành động còn thiếu, dùng Zalo đã tìm thấy trước đó.')
            connection.execute('INSERT INTO campaign_attempts(campaign_id,send_id,action) VALUES (?,?,?)',
                               (campaign_id, send_id, action))
            label = {'send': 'tin nhắn', 'friend': 'lời mời kết bạn', 'alias': 'đổi tên gợi nhớ'}[action]
            origin='Theo lịch tự động' if guard is not None else 'Xác nhận thủ công'
            self.event(campaign_id, action, f'Bắt đầu xử lý {label}, bản gửi #{send_id}. Nguồn: {origin}.')
            connection.commit()
            return True
        except BaseException:
            connection.rollback()
            raise

    def store_preview(self, campaign, person, account, resolved, scheduled=False, skip_message=False, skip_reason='',lookup_state='resolved'):
        """Store one immutable personalized payload inside the caller's write transaction."""
        alias=personalize(campaign['rename_template'],person,resolved).strip() if campaign['rename_enabled'] else ''
        if campaign['rename_enabled'] and (not alias or utf16(alias)>100):
            raise ValueError('Tên gợi nhớ sau cá nhân hóa phải có từ 1 đến 100 ký tự.')
        invitation=personalize(campaign['friend_message'],person,resolved) if campaign['send_friend'] else ''
        if utf16(invitation)>150:
            raise ValueError('Lời mời sau khi chèn tên vượt 150 ký tự. Rút ngắn lời mời trước khi tạo bản xem trước.')
        send_message=campaign['send_message'] and not skip_message
        message,styles=render_message(campaign['message'],campaign['message_html'],person,resolved,variant_index=campaign['next_message_variant']) if send_message else ('',[])
        row=self.db().execute('''INSERT INTO message_sends(campaign_id,contact_id,account_id,recipient_id,recipient_name,message,state,friend_message,friend_state,alias,alias_state,media_id,message_styles,scheduled,recipient_phone,message_skip_reason)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(campaign['id'],person['id'],account['id'],resolved['uid'],str(resolved.get('name',''))[:100],message,
            'prepared' if send_message else 'not_requested',invitation,'prepared' if campaign['send_friend'] else 'not_requested',
            alias,'prepared' if campaign['rename_enabled'] else 'not_requested',campaign['media_id'] if send_message else None,json.dumps(styles),int(scheduled),person['phone'],skip_reason))
        self.db().execute('UPDATE message_sends SET lookup_state=? WHERE id=?',(lookup_state,row.lastrowid))
        if send_message:
            self.db().execute('UPDATE campaigns SET next_message_variant=next_message_variant+1 WHERE id=?',(campaign['id'],))
        origin='Theo lịch tự động' if scheduled else 'Thao tác thủ công'
        self.event(campaign['id'],'schedule_preview' if scheduled else 'preview',f'Tạo bản xem trước cho khách hàng #{person["id"]}. Nguồn: {origin}.')
        return row.lastrowid

    def store_lookup_skip(self,campaign,person,account,scheduled=False,reason='',lookup_state='not_found'):
        """Record a skipped lookup and its classification without fabricating a Zalo identity."""
        reason=reason or f'Bỏ qua {person["phone"]}: không tìm thấy Zalo từ số điện thoại này.'
        row=self.db().execute('''INSERT INTO message_sends(campaign_id,contact_id,account_id,
            recipient_id,recipient_name,message,state,friend_state,alias_state,scheduled,recipient_phone,message_skip_reason)
            VALUES (?,?,?,'','','','not_requested','not_requested','not_requested',?,?,?)''',
            (campaign['id'],person['id'],account['id'],int(scheduled),person['phone'],reason))
        self.db().execute('UPDATE message_sends SET lookup_state=? WHERE id=?',(lookup_state,row.lastrowid))
        origin='Theo lịch tự động' if scheduled else 'Thao tác thủ công'
        self.event(campaign['id'],'lookup_skip',reason+f' Nguồn: {origin}. Tiếp tục số điện thoại kế tiếp.')
        return row.lastrowid

    def skip_duplicate_message(self,campaign_id,send_id):
        self.db().execute('BEGIN IMMEDIATE')
        try:
            campaign=self.owned(campaign_id)
            row=self.db().execute('SELECT * FROM message_sends WHERE id=? AND campaign_id=?',(send_id,campaign_id)).fetchone()
            if not row or row['state']!='prepared':
                self.db().rollback();return False
            recent=recent_for_record(self.db,campaign,row)
            if recent is None:
                self.db().rollback();return False
            reason=DuplicateMessageBlocked(recent,campaign['duplicate_days']).description
            self.db().execute("UPDATE message_sends SET state='not_requested',message_skip_reason=? WHERE id=?",(reason,send_id))
            self.event(campaign_id,'duplicate_skip',f'Bỏ qua tin nhắn #{send_id}: {reason}')
            self.db().commit();return True
        except BaseException:
            self.db().rollback();raise

    def result(self, campaign_id, action, send_id, state,details=None):
        public=diagnostics(details) if state in ('failed','unknown') else {}
        self.db().execute('''UPDATE campaign_attempts SET completed_at=CURRENT_TIMESTAMP,error_reason=?,error_code=?
            WHERE campaign_id=? AND send_id=? AND action=?''',(public.get('error_reason',''),public.get('error_code',''),campaign_id,send_id,action))
        row=self.db().execute('''SELECT s.*,a.name AS account_name,c.name AS campaign_name FROM message_sends s
            JOIN campaigns c ON c.id=s.campaign_id JOIN zalo_accounts a ON a.id=s.account_id AND a.user_id=c.user_id
            WHERE s.id=? AND s.campaign_id=?''',(send_id,campaign_id)).fetchone()
        name=row['recipient_name'] or row['recipient_phone'] or row['recipient_id']
        label = {'send': 'Nhắn tin người lạ', 'friend': 'Kết bạn', 'alias': 'Đổi tên Zalo'}[action]
        description={'sent':f'Zalo đã tiếp nhận tin nhắn đến {name}',
            'friend_requested':f'Zalo đã tiếp nhận lời mời kết bạn đến {name}',
            'renamed':f'Đã đổi tên {name} thành "{row["alias"]}"'}.get(state,STATE_LABELS[state])
        if error_description(public):description=error_description(public)
        self.event(campaign_id, action + '_result', f'{row["account_name"]} – {row["campaign_name"]} – {label}: {description}. · Bản gửi #{send_id}: {STATE_LABELS[state]}.')

    def media(self, media_id):
        return self.db().execute('SELECT * FROM campaign_media WHERE id=? AND user_id=?',
                                (media_id, g.user['id'])).fetchone() if media_id else None

    def attachment(self, media_id):
        media = self.media(media_id)
        if not media or not (self.media_root / media['storage_name']).is_file():
            raise ValueError('Không tìm thấy media. Không gửi tin để tránh thiếu nội dung.')
        return {'path': str((self.media_root / media['storage_name']).resolve()),
                'filename': media['filename'], 'size': media['size'],
                'width': media['width'], 'height': media['height']}

    def upload(self, uploaded):
        if not uploaded or not uploaded.filename:
            return None
        if self.db().execute('SELECT count(*) FROM campaign_media WHERE user_id=?', (g.user['id'],)).fetchone()[0] >= 1000:
            raise ValueError('Thư viện đã đạt giới hạn 1.000 tệp.')
        data = uploaded.read(10 * 1024 * 1024 + 1)
        if not data or len(data) > 10 * 1024 * 1024:
            raise ValueError('Media cần có dữ liệu và không vượt quá 10 MB.')
        filename = secure_filename(uploaded.filename)[:120]
        extension = Path(filename).suffix.lower()
        width = height = None
        mimes = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                 '.webp': 'image/webp', '.pdf': 'application/pdf', '.mp4': 'video/mp4'}
        if extension not in mimes:
            raise ValueError('Media hỗ trợ JPG, PNG, WEBP, PDF và MP4.')
        if extension in ('.jpg', '.jpeg', '.png', '.webp'):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(data)) as image:
                        width, height = image.size
                        expected = {'.jpg': 'JPEG', '.jpeg': 'JPEG', '.png': 'PNG', '.webp': 'WEBP'}[extension]
                        if image.format != expected or width * height > 25_000_000:
                            raise ValueError('Ảnh sai định dạng hoặc vượt 25 triệu điểm ảnh.')
                        image.verify()
            except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
                raise ValueError('Tệp ảnh không hợp lệ.') from error
        elif extension == '.pdf' and not data.startswith(b'%PDF-'):
            raise ValueError('Tệp PDF không hợp lệ.')
        elif extension == '.mp4' and (len(data) < 12 or data[4:8] != b'ftyp'):
            raise ValueError('Tệp MP4 không hợp lệ.')
        self.media_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        storage_name = uuid.uuid4().hex + extension
        path = self.media_root / storage_name
        try:
            with open(path, 'xb', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
                stream.write(data)
            cur = self.db().execute('''INSERT INTO campaign_media(user_id,storage_name,filename,mime,size,width,height)
                VALUES (?,?,?,?,?,?,?)''', (g.user['id'], storage_name, filename, mimes[extension], len(data), width, height))
            g.setdefault('pending_media_files', []).append((cur.lastrowid, storage_name, path))
            return cur.lastrowid
        except BaseException:
            path.unlink(missing_ok=True)
            raise


    def set_media(self, campaign_id):
        campaign = self.owned(campaign_id)
        upload = request.files.get('media')
        library_id = request.form.get('library_media_id', '')
        if request.form.get('media_present') == 'yes' and request.form.get('media_mode') not in ('none','send'):
            raise ValueError('Chọn cách gửi tệp đính kèm hợp lệ.')
        if request.form.get('media_present') == 'yes' and request.form.get('media_mode') == 'none':
            self.db().execute('UPDATE campaigns SET media_id=NULL WHERE id=?', (campaign_id,))
            return
        if (upload and upload.filename or library_id) and not campaign['send_message']:
            raise ValueError('Media chỉ dùng cho chiến dịch có nhắn tin.')
        chosen = None
        if library_id:
            chosen = self.media(int(library_id)) if library_id.isdigit() else None
            if not chosen or chosen['library_deleted_at']:
                raise ValueError('Không tìm thấy media trong thư viện của bạn.')
            self.attachment(chosen['id'])
            if upload and upload.filename:
                raise ValueError('Chọn tệp tải mới hoặc media thư viện, mỗi lần một nguồn.')
        new_id = self.upload(upload)
        media_id = new_id or (chosen['id'] if chosen else None) or (None if request.form.get('remove_media') == 'yes' else campaign['media_id'])
        if request.form.get('media_present') == 'yes' and request.form.get('media_mode') == 'send' and not media_id:
            raise ValueError('Chọn một tệp để gửi hoặc chọn Không gửi file.')
        if not campaign['send_message']:
            media_id = None
        self.db().execute('UPDATE campaigns SET media_id=? WHERE id=?', (media_id, campaign_id))


def register_campaign_actions(app, db, login_required, audience, connector, personalize):
    manager = CampaignManager(app, db, audience)
    app.extensions['campaign_manager'] = manager
    app.jinja_env.globals['campaign_media'] = manager.media
    app.jinja_env.globals['send_state_labels'] = STATE_LABELS
    app.jinja_env.globals['display_message'] = display_message
    def campaign_markup(campaign):
        from markupsafe import Markup
        if campaign['message_html']:
            text, ranges = parse_html(campaign['message_html'])
            if text == campaign['message']:
                return Markup(markup(text, ranges))
        return campaign['message']
    app.jinja_env.globals['campaign_message'] = campaign_markup

    @app.teardown_request
    def cleanup_uncommitted_media(error):
        pending = g.get('pending_media_files', [])
        if not pending:
            return
        connection = db()
        if connection.in_transaction:
            connection.rollback()
        for media_id, storage_name, path in pending:
            if not connection.execute('SELECT 1 FROM campaign_media WHERE id=? AND storage_name=?', (media_id, storage_name)).fetchone():
                path.unlink(missing_ok=True)

    @app.errorhandler(409)
    def campaign_conflict(error):
        return render_template('campaign_error.html', message=error.description, page='campaigns'), 409

    @app.errorhandler(413)
    def upload_too_large(_):
        return render_template('campaign_error.html', message='Tệp tải lên quá lớn. Media tối đa 10 MB, CSV tối đa 2 MB.', page='campaigns'), 413

    @app.route('/campaigns/<int:campaign_id>/pause', methods=['GET', 'POST'])
    @login_required
    def pause_campaign(campaign_id):
        if request.method == 'POST':
            db().execute('BEGIN IMMEDIATE')
        campaign = manager.owned(campaign_id)
        if request.method == 'POST':
            if request.form.get('paused') not in ('0', '1'):
                abort(400)
            paused = int(request.form['paused'])
            db().execute('UPDATE campaigns SET paused=? WHERE id=?', (paused, campaign_id))
            manager.event(campaign_id, 'pause' if paused else 'resume', 'Tạm ngưng chiến dịch.' if paused else 'Tiếp tục chiến dịch.')
            db().commit()
            flash('Đã tạm ngưng các hành động tiếp theo.' if paused else 'Đã mở lại chiến dịch. Các lần đã xử lý không tự chạy lại.', 'success')
            return redirect(url_for('campaign_detail', campaign_id=campaign_id))
        return render_template('campaign_action.html', campaign=campaign, action='pause', page='campaigns')

    @app.route('/campaigns/<int:campaign_id>/duplicate', methods=['GET', 'POST'])
    @login_required
    def duplicate_campaign(campaign_id):
        if request.method == 'POST':
            db().execute('BEGIN IMMEDIATE')
        campaign = manager.owned(campaign_id)
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            if not name or len(name) > 120:
                flash('Tên chiến dịch cần từ 1 đến 120 ký tự.', 'error')
                db().rollback()
            else:
                try:
                    from campaign_schedule import CONFIG_COLUMNS
                    columns = ['message', 'message_html', 'tag', 'account_id', 'send_message', 'send_friend', 'friend_message',
                               'rename_enabled', 'rename_template', 'audience_mode', 'media_id',
                               *LIMIT_COLUMNS, *CONFIG_COLUMNS, *DUPLICATE_COLUMNS]
                    cur = db().execute(f"INSERT INTO campaigns(user_id,name,{','.join(columns)}) VALUES ({','.join('?' for _ in range(len(columns)+2))})",
                                       (g.user['id'], name, *(campaign[column] for column in columns)))
                    copied_id = cur.lastrowid
                    db().execute('INSERT INTO campaign_contacts(campaign_id,contact_id) SELECT ?,contact_id FROM campaign_contacts WHERE campaign_id=?',
                                 (copied_id, campaign_id))
                    db().execute('INSERT INTO campaign_exclusion_rules(campaign_id,rule_group_id) SELECT ?,rule_group_id FROM campaign_exclusion_rules WHERE campaign_id=?', (copied_id,campaign_id))
                    db().execute('INSERT INTO campaign_exclusion_lists(campaign_id,list_id) SELECT ?,list_id FROM campaign_exclusion_lists WHERE campaign_id=?', (copied_id,campaign_id))
                    if request.form.get('options_present')=='yes':
                        name,message,tag,account_id,phones=manager.form_fields()
                        db().execute('UPDATE campaigns SET name=?,message=?,tag=?,account_id=? WHERE id=?',(name,message,tag,account_id,copied_id))
                        manager.save_form_data(copied_id,phones)
                    manager.event(campaign_id, 'duplicate', f'Nhân bản thành chiến dịch #{copied_id}.')
                    manager.event(copied_id, 'create', f'Bản nháp nhân bản từ chiến dịch #{campaign_id}.')
                    db().commit()
                    flash('Đã nhân bản cấu hình và danh sách. Kiểm tra trạng thái lịch trong chi tiết chiến dịch.', 'success')
                    return redirect(url_for('campaign_detail', campaign_id=copied_id))
                except ValueError as error:
                    db().rollback();flash(str(error),'error')
        members=db().execute('SELECT p.id,p.name,p.phone FROM contacts p JOIN campaign_contacts cc ON cc.contact_id=p.id WHERE cc.campaign_id=? AND p.user_id=? AND p.deleted_at IS NULL ORDER BY p.id',(campaign_id,g.user['id'])).fetchall()
        snapshot=[dict(row) for row in members] if len(members)>500 else []
        return render_template('campaign_edit.html',campaign=campaign,duplicating=True,
            phones='' if snapshot else '\n'.join(row['phone'] for row in members),snapshot_contacts=snapshot,
            accounts=db().execute('SELECT * FROM zalo_accounts WHERE user_id=? ORDER BY name',(g.user['id'],)).fetchall(),
            tags=db().execute('SELECT DISTINCT group_name AS tag FROM contact_group_memberships WHERE user_id=? ORDER BY tag',(g.user['id'],)).fetchall(),page='campaigns')

    @app.route('/campaigns/<int:campaign_id>/limits', methods=['GET', 'POST'])
    @login_required
    def campaign_limits(campaign_id):
        campaign = manager.owned(campaign_id)
        if request.method == 'POST':
            try:
                db().execute('BEGIN IMMEDIATE')
                manager.owned(campaign_id)
                save_limits(db,campaign_id,request.form,legacy=True)
                manager.event(campaign_id,'limits','Cập nhật giới hạn hành động theo ngày, khung giờ và khoảng nghỉ. Giữ nguyên các lượt đã xử lý.')
                db().commit()
                flash('Đã cập nhật giới hạn. Các lần đã xử lý vẫn được tính trong hạn mức.','success')
                return redirect(url_for('campaign_detail',campaign_id=campaign_id))
            except ValueError as error:
                db().rollback();flash(str(error),'error')
        return render_template('campaign_action.html',campaign=campaign,action='limits',page='campaigns')

    @app.route('/campaigns/<int:campaign_id>/content', methods=['GET', 'POST'])
    @login_required
    def campaign_content(campaign_id):
        campaign = manager.owned(campaign_id)
        if request.method == 'POST':
            try:
                message, message_html = read_message(request.form)
                invitation = request.form.get('friend_message', '').strip()
                if (campaign['send_message'] and not message) or len(invitation) > 150 or (campaign['send_friend'] and not invitation):
                    raise ValueError('Nhập tin nhắn tối đa 2000 ký tự và lời mời tối đa 150 ký tự cho hành động đã chọn.')
                personalize(invitation, {}, strict=False)
                db().execute('BEGIN IMMEDIATE')
                campaign = manager.owned(campaign_id)
                manager.set_media(campaign_id)
                db().execute('''UPDATE campaigns SET next_message_variant=CASE WHEN message<>? OR message_html<>? THEN 0 ELSE next_message_variant END,
                    message=?,message_html=?,friend_message=? WHERE id=?''',
                             (message, message_html, message, message_html, invitation, campaign_id))
                manager.event(campaign_id, 'content', 'Cập nhật nội dung và media cho các bản xem trước tạo sau thời điểm này.')
                db().commit()
                flash('Đã cập nhật nội dung và media. Bản xem trước và nhật ký cũ giữ nguyên.', 'success')
                return redirect(url_for('campaign_detail', campaign_id=campaign_id))
            except ValueError as error:
                db().rollback()
                flash(str(error), 'error')
        return render_template('campaign_action.html', campaign=campaign, action='content', page='campaigns', library_media=db().execute('SELECT id,filename FROM campaign_media WHERE user_id=? AND library_deleted_at IS NULL ORDER BY id DESC', (g.user['id'],)).fetchall())

    @app.route('/campaigns/<int:campaign_id>/data', methods=['GET', 'POST'])
    @login_required
    def campaign_data(campaign_id):
        campaign = manager.owned(campaign_id)
        if request.method == 'POST':
            try:
                if request.form.get('consent') != 'yes':
                    raise ValueError('Cần xác nhận khách hàng đã đồng ý nhận nội dung này.')
                incoming = {phone: {'phone': phone} for phone in parse_phones(request.form.get('phones', ''))}
                incoming.update(read_contacts(request.files.get('file'), parse_phones))
                source = request.form.get('source_tag', '')
                if source:
                    for person in db().execute('SELECT * FROM contacts WHERE user_id=? AND consent=1 AND id IN (SELECT contact_id FROM contact_group_memberships WHERE user_id=contacts.user_id AND group_name=?)', (g.user['id'], source)):
                        incoming.setdefault(person['phone'], dict(person))
                if not incoming:
                    raise ValueError('Nhập số điện thoại, chọn tệp hoặc chọn nhóm để bổ sung.')
                db().execute('BEGIN IMMEDIATE')
                campaign = manager.owned(campaign_id)
                existing = list(audience(campaign, apply_exclusions=False)) if campaign['audience_mode'] == 'group' else db().execute(
                    'SELECT p.* FROM contacts p JOIN campaign_contacts cc ON cc.contact_id=p.id WHERE cc.campaign_id=?', (campaign_id,)).fetchall()
                if len({p['phone'] for p in existing} | set(incoming)) > CAMPAIGN_CONTACT_LIMIT:
                    raise ValueError('Tổng danh sách chiến dịch tối đa 10.000 khách hàng.')
                for person in existing:
                    db().execute('INSERT OR IGNORE INTO campaign_contacts VALUES (?,?)', (campaign_id, person['id']))
                added = 0
                for phone, row in incoming.items():
                    insert_contact(db(), g.user['id'], phone, row)
                    person = db().execute('SELECT id FROM contacts WHERE user_id=? AND phone=?', (g.user['id'], phone)).fetchone()
                    added += db().execute('INSERT OR IGNORE INTO campaign_contacts VALUES (?,?)', (campaign_id, person['id'])).rowcount
                db().execute("UPDATE campaigns SET audience_mode='list' WHERE id=?", (campaign_id,))
                manager.event(campaign_id, 'data', f'Bổ sung {added} khách hàng mới vào danh sách chiến dịch.')
                db().commit()
                flash(f'Đã bổ sung {added} khách hàng. Giữ nguyên các lần gửi trước.', 'success')
                return redirect(url_for('campaign_detail', campaign_id=campaign_id))
            except (ValueError, UnicodeError, csv.Error) as error:
                db().rollback()
                flash(str(error) if isinstance(error, ValueError) and not isinstance(error, UnicodeError) else 'CSV cần đúng định dạng UTF-8.', 'error')
        return render_template('campaign_action.html', campaign=campaign, action='data', page='campaigns', data_tags=db().execute('SELECT DISTINCT group_name AS tag FROM contact_group_memberships WHERE user_id=? ORDER BY tag', (g.user['id'],)).fetchall())

    @app.route('/campaigns/<int:campaign_id>/delete', methods=['GET', 'POST'])
    @login_required
    def delete_campaign(campaign_id):
        if request.method == 'POST':
            db().execute('BEGIN IMMEDIATE')
        campaign = manager.owned(campaign_id)
        if request.method == 'POST':
            if request.form.get('confirm_delete') != 'yes':
                abort(400, 'Cần xác nhận xóa chiến dịch.')
            db().execute("UPDATE campaigns SET paused=1,deleted_at=CURRENT_TIMESTAMP WHERE id=?", (campaign_id,))
            manager.event(campaign_id, 'delete', 'Xóa khỏi danh sách hoạt động; giữ nguyên báo cáo và lịch sử.')
            db().commit()
            flash('Đã xóa chiến dịch khỏi danh sách hoạt động. Báo cáo vẫn có trong mục Đã xóa.', 'success')
            return redirect(url_for('campaigns'))
        return render_template('campaign_action.html', campaign=campaign, action='delete', page='campaigns')

    @app.get('/campaigns/<int:campaign_id>/history')
    @login_required
    def campaign_history(campaign_id):
        campaign = manager.owned(campaign_id, include_deleted=True)
        page_number = max(1, min(request.args.get('p', 1, type=int), 100000))
        events = db().execute('SELECT * FROM campaign_events WHERE campaign_id=? ORDER BY id DESC LIMIT 51 OFFSET ?',
                              (campaign_id, (page_number-1)*50)).fetchall()
        return render_template('campaign_history.html', campaign=campaign, events=events[:50],
                               has_next=len(events)>50, page_number=page_number, page='campaigns')

    @app.get('/campaigns/<int:campaign_id>/report')
    @login_required
    def campaign_report(campaign_id):
        campaign = manager.owned(campaign_id, include_deleted=True)
        sends = db().execute('''SELECT s.*,p.name,p.phone,a.name AS account_name FROM message_sends s
            JOIN contacts p ON p.id=s.contact_id JOIN zalo_accounts a ON a.id=s.account_id
            WHERE s.campaign_id=? ORDER BY s.id DESC''', (campaign_id,)).fetchall()
        simulation_logs = db().execute('''SELECT d.*,p.name,p.phone FROM deliveries d
            JOIN contacts p ON p.id=d.contact_id WHERE d.campaign_id=? ORDER BY d.id DESC''', (campaign_id,)).fetchall()
        simulated = len(simulation_logs)
        counts = {action: {state: sum(row[column] == state for row in sends) for state in STATE_LABELS}
                  for action, (column, _) in ACTION_COLUMNS.items()}
        if request.args.get('format') == 'csv':
            stream = io.StringIO()
            writer = csv.writer(stream)
            writer.writerow(['ID', 'Khách hàng', 'SĐT', 'Tài khoản', 'Nội dung', 'Tin nhắn', 'Kết bạn', 'Đổi tên', 'Mã tin', 'Thời gian UTC',
                             'Zalo ID', 'Tên Zalo', 'Lời mời', 'Tên gợi nhớ', 'Media', 'Lý do bỏ qua'])
            def safe(value):
                value = str(value or '')
                return "'" + value if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else value
            for row in sends:
                media = manager.media(row['media_id'])
                writer.writerow([safe(value) for value in (row['id'], row['name'], row['phone'], row['account_name'], row['message'],
                    STATE_LABELS[row['state']], STATE_LABELS[row['friend_state']], STATE_LABELS[row['alias_state']], row['message_id'], row['created_at'],
                    row['recipient_id'], row['recipient_name'], row['friend_message'], row['alias'], media['filename'] if media else '',' '.join(filter(None,(row['message_skip_reason'],row['schedule_skip_reason']))))])
            return send_file(io.BytesIO(('\ufeff'+stream.getvalue()).encode()), mimetype='text/csv', as_attachment=True,
                             download_name=f'chien-dich-{campaign_id}.csv')
        return render_template('campaign_report.html', campaign=campaign, sends=sends, counts=counts,
                               simulated=simulated, simulation_logs=simulation_logs,
                               audience_count=len(audience(campaign)), page='campaigns')

    @app.get('/campaigns/<int:campaign_id>/account')
    @login_required
    def campaign_account(campaign_id):
        campaign = manager.owned(campaign_id)
        account = db().execute('SELECT * FROM zalo_accounts WHERE id=? AND user_id=?',
                               (campaign['account_id'], g.user['id'])).fetchone()
        used_accounts = db().execute('''SELECT DISTINCT a.* FROM zalo_accounts a JOIN message_sends s ON s.account_id=a.id
            WHERE s.campaign_id=? AND a.user_id=?''', (campaign_id, g.user['id'])).fetchall()
        connection = connector.status(g.user['id'], account['id']) if account else None
        return render_template('campaign_account.html', campaign=campaign, account=account, used_accounts=used_accounts,
                               connection=connection, page='campaigns')

    @app.get('/campaigns/<int:campaign_id>/reconnect')
    @login_required
    def campaign_reconnect(campaign_id):
        campaign = manager.owned(campaign_id)
        if not campaign['account_id']:
            flash('Chiến dịch chưa chọn tài khoản gửi. Chọn Đăng nhập QR bên cạnh tài khoản cần dùng.', 'info')
        return redirect(url_for('accounts', connect=campaign['account_id']))

    @app.get('/media/<int:media_id>')
    @login_required
    def media_file(media_id):
        media = manager.media(media_id)
        if media is None:
            abort(404)
        path = manager.media_root / media['storage_name']
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype=media['mime'], as_attachment=not media['mime'].startswith('image/'),
                         download_name=media['filename'], conditional=True)

    return manager
