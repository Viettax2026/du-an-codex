"""Data groups use the existing customer tag, shared with campaign audiences."""
import re
import csv
import io
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from data_sources import initialize_data_sources, create_source_batch, record_contact_source

from flask import Response, abort, flash, g, jsonify, redirect, render_template, request, url_for
from data_import import read_contacts, insert_contact, read_sheet_rows, read_mapped_contacts, default_contact_consent, canonical_header


def insert_data_group(db, user_id, name, data_type='all', color='#6860f6'):
    # A persistent high-water mark prevents a deleted group's ID being reused by
    # a new group, including when the last remaining group is deleted.
    existing = db().execute('SELECT id FROM data_groups WHERE user_id=? AND name=?', (user_id,name)).fetchone()
    if existing:
        return existing['id']
    db().execute('''UPDATE data_group_sequence SET last_id=max(last_id,
        (SELECT coalesce(max(id),0) FROM data_groups))+1 WHERE id=1''')
    group_id = db().execute('SELECT last_id FROM data_group_sequence WHERE id=1').fetchone()[0]
    db().execute('''INSERT OR IGNORE INTO data_groups(id,user_id,name,data_type,color,created_at)
        VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)''', (group_id,user_id,name,data_type,color))
    return db().execute('SELECT id FROM data_groups WHERE user_id=? AND name=?', (user_id,name)).fetchone()['id']


def materialize_legacy_groups(db, user_id):
    for row in db().execute('''SELECT DISTINCT tag FROM contacts p WHERE user_id=? AND tag!=''
        AND NOT EXISTS (SELECT 1 FROM data_groups d WHERE d.user_id=p.user_id AND d.name=p.tag)''', (user_id,)).fetchall():
        insert_data_group(db,user_id,row['tag'])


def remove_data_group(db, user_id, name):
    """Delete the group; preserve profiles, provenance and existing audiences."""
    group = db().execute('SELECT id FROM data_groups WHERE user_id=? AND name=?', (user_id,name)).fetchone()
    # Freeze dynamic campaigns before detaching the group's name. Snapshot all
    # current members; consent and exclusions are still evaluated before sending.
    db().execute('''DELETE FROM campaign_contacts WHERE campaign_id IN
        (SELECT id FROM campaigns WHERE user_id=? AND tag=? AND audience_mode='group')''', (user_id,name))
    db().execute('''INSERT OR IGNORE INTO campaign_contacts(campaign_id,contact_id)
        SELECT c.id,m.contact_id FROM campaigns c JOIN contact_group_memberships m
          ON m.user_id=c.user_id AND m.group_name=c.tag
        WHERE c.user_id=? AND c.tag=? AND c.audience_mode='group' ''', (user_id,name))
    db().execute("UPDATE campaigns SET audience_mode='list',tag='' WHERE user_id=? AND tag=? AND audience_mode='group'", (user_id,name))
    db().execute("UPDATE campaigns SET tag='' WHERE user_id=? AND tag=?", (user_id,name))
    if group:
        group_id = group['id']
        # Existing exclusions must continue protecting these recipients after
        # deletion, and must never follow a new group with the same name.
        db().execute('''INSERT OR IGNORE INTO exclusion_rule_contacts(rule_group_id,contact_id)
            SELECT r.id,m.contact_id FROM exclusion_rule_groups r JOIN contact_group_memberships m
              ON m.user_id=r.user_id AND m.group_name=?
            WHERE r.user_id=? AND r.data_group_id=?''', (name,user_id,group_id))
        db().execute('UPDATE exclusion_rule_groups SET data_group_id=NULL WHERE user_id=? AND data_group_id=?', (user_id,group_id))
        db().execute('UPDATE data_import_batches SET group_id=NULL WHERE user_id=? AND group_id=?', (user_id,group_id))
        db().execute('UPDATE contact_data_sources SET group_id=NULL WHERE user_id=? AND group_id=?', (user_id,group_id))
        db().execute('UPDATE data_group_sequence SET last_id=max(last_id,?) WHERE id=1', (group_id,))
        db().execute('DELETE FROM data_group_contacts WHERE group_id=?', (group_id,))
        db().execute('DELETE FROM data_groups WHERE id=? AND user_id=?', (group_id,user_id))
    db().execute("UPDATE contacts SET tag='' WHERE user_id=? AND tag=?", (user_id,name))


def purge_archived_groups(app, db):
    """Apply permanent deletion to groups hidden by earlier versions as well."""
    with app.app_context():
        db().execute('BEGIN IMMEDIATE')
        for group in db().execute('SELECT user_id,name FROM data_groups WHERE deleted_at IS NOT NULL').fetchall():
            remove_data_group(db,group['user_id'],group['name'])
        db().commit()


def save_group_members(db, user_id, group, incoming, consent=1, filename='', source_type=None, confirm_existing=False):
    """Persist validated members and provenance in the caller's transaction."""
    added = created_profiles = confirmed = 0
    destination_id = insert_data_group(db,user_id,group)
    batch_id = create_source_batch(db, user_id, group, filename, source_type)
    recorded = 0
    for phone, row in incoming.items():
        contact = db().execute('SELECT id,deleted_at FROM contacts WHERE user_id=? AND phone=?', (user_id,phone)).fetchone()
        was_member = contact and db().execute('SELECT 1 FROM contact_group_memberships WHERE user_id=? AND group_name=? AND contact_id=?',
                                              (user_id,group,contact['id'])).fetchone()
        if not contact or contact['deleted_at']:
            created_profiles += int(contact is None)
            insert_contact(db(), user_id, phone, row, tag=group, consent=consent)
            contact = db().execute('SELECT id FROM contacts WHERE user_id=? AND phone=?', (user_id,phone)).fetchone()
        if not was_member:
            if not db().execute('SELECT 1 FROM contact_group_memberships WHERE user_id=? AND group_name=? AND contact_id=?', (user_id,group,contact['id'])).fetchone():
                db().execute('INSERT OR IGNORE INTO data_group_contacts(group_id,contact_id) VALUES (?,?)', (destination_id,contact['id']))
            added += 1
        if consent and confirm_existing:
            confirmed += db().execute('UPDATE contacts SET consent=1 WHERE user_id=? AND id=? AND consent=0', (user_id,contact['id'])).rowcount
        record_contact_source(db, user_id,contact['id'],batch_id)
        recorded += 1
    if recorded:
        db().execute('''UPDATE data_groups SET last_import_at=CURRENT_TIMESTAMP, imported_count=imported_count+?
            WHERE user_id=? AND name=?''', (added,user_id,group))
    else:
        db().execute('DELETE FROM data_import_batches WHERE id=? AND user_id=?', (batch_id,user_id))
    return {'added': added, 'created_profiles': created_profiles, 'recorded': recorded, 'confirmed': confirmed}


def register_data_groups(app, db, login_required, parse_phones):
    with app.app_context():
        db().execute('''CREATE TABLE IF NOT EXISTS data_groups (
            id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
            name TEXT NOT NULL, UNIQUE(user_id,name))''')
        columns = {row['name'] for row in db().execute('PRAGMA table_info(data_groups)')}
        for column, definition in {'data_type': "TEXT NOT NULL DEFAULT 'all'", 'color': "TEXT NOT NULL DEFAULT '#6860f6'", 'created_at': 'TEXT', 'last_import_at': 'TEXT', 'imported_count': 'INTEGER NOT NULL DEFAULT 0', 'deleted_at': 'TEXT'}.items():
            if column not in columns:
                db().execute(f'ALTER TABLE data_groups ADD COLUMN {column} {definition}')
        contact_columns = {row['name'] for row in db().execute('PRAGMA table_info(contacts)')}
        if 'data_source' not in contact_columns:
            db().execute("ALTER TABLE contacts ADD COLUMN data_source TEXT NOT NULL DEFAULT ''")
        db().executescript('''CREATE TABLE IF NOT EXISTS data_group_sequence (
            id INTEGER PRIMARY KEY CHECK(id=1),last_id INTEGER NOT NULL);
            INSERT OR IGNORE INTO data_group_sequence(id,last_id) SELECT 1,coalesce(max(id),0) FROM data_groups;
            UPDATE data_group_sequence SET last_id=max(last_id,(SELECT coalesce(max(id),0) FROM data_groups)) WHERE id=1;
            CREATE TABLE IF NOT EXISTS data_group_contacts (
            group_id INTEGER NOT NULL REFERENCES data_groups(id) ON DELETE CASCADE,
            contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            PRIMARY KEY(group_id,contact_id));
            CREATE INDEX IF NOT EXISTS data_group_contacts_contact ON data_group_contacts(contact_id);
            DROP VIEW IF EXISTS contact_group_memberships;
            CREATE VIEW contact_group_memberships AS
            SELECT user_id,tag AS group_name,id AS contact_id FROM contacts WHERE deleted_at IS NULL AND tag!=''
            UNION SELECT d.user_id,d.name,m.contact_id FROM data_group_contacts m
                JOIN data_groups d ON d.id=m.group_id JOIN contacts p ON p.id=m.contact_id AND p.user_id=d.user_id AND p.deleted_at IS NULL;''')
        initialize_data_sources(db)
        db().commit()

    @app.route('/data-groups', methods=['GET', 'POST'])
    @login_required
    def data_groups():
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            data_type = request.form.get('data_type', 'all')
            color = request.form.get('color', '#6860f6')
            error = None
            if not name or len(name) > 80:
                error = 'Tên nhóm cần từ 1 đến 80 ký tự.'
            elif data_type not in ('all', 'phone', 'uid'):
                error = 'Loại data không hợp lệ.'
            elif not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
                error = 'Màu nhóm không hợp lệ.'
            if not error:
                db().execute('BEGIN IMMEDIATE')
            if not error and db().execute('SELECT 1 FROM data_groups WHERE user_id=? AND name=? UNION SELECT 1 FROM contacts WHERE user_id=? AND tag=?',
                              (g.user['id'], name, g.user['id'], name)).fetchone():
                error = 'Tên nhóm đã tồn tại. Vui lòng chọn tên khác.'
            if error:
                db().rollback()
                flash(error, 'error')
            else:
                insert_data_group(db,g.user['id'],name,data_type,color.lower())
                db().commit()
                return redirect(url_for('data_groups', group=name))
        materialize_legacy_groups(db,g.user['id'])
        db().commit()
        groups = db().execute('''SELECT names.name, d.id, count(p.id) AS total,
            COALESCE(d.data_type,'all') AS data_type, COALESCE(d.color,'#6860f6') AS color FROM
            (SELECT name FROM data_groups WHERE user_id=? UNION SELECT tag FROM contacts WHERE user_id=? AND tag!='') names
            LEFT JOIN contacts p ON p.id IN (SELECT contact_id FROM contact_group_memberships WHERE user_id=p.user_id AND group_name=names.name) AND p.user_id=?
            LEFT JOIN data_groups d ON d.name=names.name AND d.user_id=?
            WHERE d.deleted_at IS NULL GROUP BY names.name ORDER BY names.name''',
            (g.user['id'], g.user['id'], g.user['id'], g.user['id'])).fetchall()
        selected = request.args.get('group', groups[0]['name'] if groups else '')
        if selected and selected not in [row['name'] for row in groups]:
            abort(404)
        query = request.args.get('q', '').strip()[:120]
        kind = request.args.get('kind', '')
        consent = request.args.get('consent', '')
        if kind not in ('', 'phone', 'uid') or consent not in ('', 'yes', 'no'):
            abort(400)
        accounts = db().execute('SELECT id,name FROM zalo_accounts WHERE user_id=? AND deleted_at IS NULL ORDER BY name,id', (g.user['id'],)).fetchall()
        account_id = request.args.get('account_id', '')
        if account_id and (not account_id.isdigit() or int(account_id) not in {account['id'] for account in accounts}):
            abort(404)
        where = "user_id=? AND id IN (SELECT contact_id FROM contact_group_memberships WHERE user_id=contacts.user_id AND group_name=?) AND (name LIKE ? OR phone LIKE ? OR zalo_id LIKE ?)"
        params = [g.user['id'], selected, *(['%' + query + '%'] * 3)]
        if kind == 'uid':
            where += " AND zalo_id!=''"
        elif kind == 'phone':
            where += " AND phone!=''"
        if consent:
            where += ' AND consent=?'
            params.append(int(consent == 'yes'))
        if account_id:
            where += ''' AND (EXISTS (SELECT 1 FROM message_sends s WHERE s.contact_id=contacts.id AND s.account_id=?)
                OR EXISTS (SELECT 1 FROM campaigns c WHERE c.user_id=contacts.user_id AND c.account_id=? AND c.deleted_at IS NULL
                    AND ((c.audience_mode='group' AND (c.tag='' OR contacts.id IN (SELECT contact_id FROM contact_group_memberships WHERE user_id=contacts.user_id AND group_name=c.tag))) OR
                         (c.audience_mode='list' AND EXISTS (SELECT 1 FROM campaign_contacts cc WHERE cc.campaign_id=c.id AND cc.contact_id=contacts.id)))))'''
            params.extend([int(account_id), int(account_id)])
        filtered = db().execute('SELECT count(*) FROM contacts WHERE ' + where, params).fetchone()[0]
        pages = max(1, math.ceil(filtered / 50))
        number = max(1, min(request.args.get('p', 1, type=int), pages))
        rows = db().execute('''SELECT contacts.*,
            (SELECT s.recipient_name FROM message_sends s JOIN zalo_accounts a ON a.id=s.account_id
             WHERE s.contact_id=contacts.id AND a.user_id=contacts.user_id AND s.recipient_name!='' ORDER BY s.id DESC LIMIT 1) AS display_name,
            (SELECT group_concat(DISTINCT a.name) FROM message_sends s JOIN zalo_accounts a ON a.id=s.account_id
             WHERE s.contact_id=contacts.id AND a.user_id=contacts.user_id) AS account_names,
            EXISTS (SELECT 1 FROM message_sends s WHERE s.contact_id=contacts.id AND
                (s.state!='prepared' OR s.friend_state NOT IN ('prepared','not_requested') OR s.alias_state NOT IN ('prepared','not_requested'))) AS has_processed
            FROM contacts WHERE ''' + where + ' ORDER BY id DESC LIMIT 50 OFFSET ?',
                            (*params, (number - 1) * 50)).fetchall()
        total = next((row['total'] for row in groups if row['name'] == selected), 0)
        metadata = db().execute('SELECT * FROM data_groups WHERE user_id=? AND name=?', (g.user['id'], selected)).fetchone()
        source_summary = db().execute('''SELECT label FROM contact_data_sources WHERE user_id=? AND contact_id IN
            (SELECT contact_id FROM contact_group_memberships WHERE user_id=? AND group_name=?) ORDER BY id DESC LIMIT 1''',
            (g.user['id'],g.user['id'],selected)).fetchone()
        usage = db().execute('''SELECT count(*) FROM campaigns c WHERE c.user_id=? AND c.deleted_at IS NULL AND
            ((c.audience_mode='group' AND (c.tag=? OR c.tag='')) OR
             (c.audience_mode='list' AND EXISTS (SELECT 1 FROM campaign_contacts cc JOIN contacts p ON p.id=cc.contact_id
                WHERE cc.campaign_id=c.id AND p.user_id=? AND p.id IN (SELECT contact_id FROM contact_group_memberships WHERE user_id=p.user_id AND group_name=?))))''',
            (g.user['id'], selected, g.user['id'], selected)).fetchone()[0] if selected else 0
        runs = db().execute('''SELECT count(*) FROM message_sends s JOIN contacts p ON p.id=s.contact_id
            WHERE p.user_id=? AND p.id IN (SELECT contact_id FROM contact_group_memberships WHERE user_id=p.user_id AND group_name=?) AND (s.state!='prepared' OR s.friend_state NOT IN ('prepared','not_requested')
            OR s.alias_state NOT IN ('prepared','not_requested'))''', (g.user['id'], selected)).fetchone()[0]
        distribution = db().execute("SELECT count(*) AS phones, sum(zalo_id!='') AS uids, sum(consent=1) AS consented FROM contacts WHERE user_id=? AND id IN (SELECT contact_id FROM contact_group_memberships WHERE user_id=contacts.user_id AND group_name=?)",
                                     (g.user['id'], selected)).fetchone()
        return render_template('data_groups.html', groups=groups, selected=selected, rows=rows,
                               total=total, query=query, page='data_groups', metadata=metadata, usage=usage, source_summary=source_summary,
                               runs=runs, distribution=distribution, filtered=filtered, number=number, pages=pages,
                               kind=kind, consent=consent, accounts=accounts, account_id=account_id,
                               data_type_labels={'all': 'Mọi loại dữ liệu', 'phone': 'Số điện thoại', 'uid': 'UID'})

    @app.post('/data-groups/export')
    @login_required
    def export_group_data():
        selected = request.form.get('group', '')
        require_group(selected)
        ids = request.form.getlist('contact_ids')
        if len(ids) > 50 or not ids or not all(value.isdigit() for value in ids):
            abort(400)
        rows = db().execute('SELECT name,phone,zalo_id,email,info1,info2,info3,info4,info5 FROM contacts WHERE user_id=? AND id IN (SELECT contact_id FROM contact_group_memberships WHERE user_id=contacts.user_id AND group_name=?) AND id IN (' +
                            ','.join('?' for _ in ids) + ') ORDER BY id', (g.user['id'], selected, *ids)).fetchall()
        if len(rows) != len(set(ids)):
            abort(404)
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(['name','phone','zalo_id','email','info1','info2','info3','info4','info5'])
        for row in rows:
            writer.writerow(["'" + value if str(value).lstrip().startswith(('=', '+', '-', '@')) else value for value in row])
        return Response('\ufeff' + stream.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename="group-data.csv"'})

    def require_group(name):
        if not name:
            abort(404)
        metadata = db().execute('SELECT * FROM data_groups WHERE user_id=? AND name=?', (g.user['id'], name)).fetchone()
        if metadata and metadata['deleted_at']:
            abort(404)
        if not metadata and not db().execute('SELECT 1 FROM contacts WHERE user_id=? AND tag=?', (g.user['id'], name)).fetchone():
            abort(404)
        return metadata

    @app.post('/data-groups/edit')
    @login_required
    def edit_data_group():
        original = request.form.get('original_group', '')
        require_group(original)
        name = request.form.get('name', '').strip()
        data_type = request.form.get('data_type', 'all')
        color = request.form.get('color', '#6860f6')
        try:
            if not name or len(name) > 80 or data_type not in ('all','phone','uid') or not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
                raise ValueError('Kiểm tra tên nhóm, loại data và màu nhóm.')
            db().execute('BEGIN IMMEDIATE')
            if name != original and db().execute('SELECT 1 FROM data_groups WHERE user_id=? AND name=? UNION SELECT 1 FROM contacts WHERE user_id=? AND tag=?',
                                                  (g.user['id'], name, g.user['id'], name)).fetchone():
                raise ValueError('Tên nhóm đã tồn tại. Vui lòng chọn tên khác.')
            insert_data_group(db,g.user['id'],original)
            db().execute('UPDATE data_groups SET name=?,data_type=?,color=? WHERE user_id=? AND name=?', (name, data_type, color.lower(), g.user['id'], original))
            db().execute('UPDATE contacts SET tag=? WHERE user_id=? AND tag=?', (name, g.user['id'], original))
            db().execute('UPDATE campaigns SET tag=? WHERE user_id=? AND tag=?', (name, g.user['id'], original))
            db().commit()
            flash('Đã sửa nhóm data.', 'success')
            return redirect(url_for('data_groups', group=name))
        except ValueError as error:
            db().rollback()
            flash(str(error), 'error')
            return redirect(url_for('data_groups', group=original))

    @app.route('/data-groups/duplicate', methods=['GET','POST'])
    @login_required
    def duplicate_data_group():
        original = request.form.get('group', '') if request.method == 'POST' else request.args.get('group', '')
        metadata = require_group(original)
        count = db().execute('SELECT count(*) FROM contact_group_memberships WHERE user_id=? AND group_name=?', (g.user['id'], original)).fetchone()[0]
        if request.method == 'POST':
            name = request.form.get('name', '').strip()
            try:
                if not name or len(name) > 80:
                    raise ValueError('Tên nhóm cần từ 1 đến 80 ký tự.')
                db().execute('BEGIN IMMEDIATE')
                metadata = require_group(original)
                if db().execute('SELECT 1 FROM data_groups WHERE user_id=? AND name=? UNION SELECT 1 FROM contacts WHERE user_id=? AND tag=?',
                                 (g.user['id'], name, g.user['id'], name)).fetchone():
                    raise ValueError('Tên nhóm đã tồn tại. Vui lòng chọn tên khác.')
                group_id = insert_data_group(db,g.user['id'],name,metadata['data_type'] if metadata else 'all',metadata['color'] if metadata else '#6860f6')
                db().execute('''INSERT INTO data_group_contacts(group_id,contact_id)
                    SELECT ?,contact_id FROM contact_group_memberships WHERE user_id=? AND group_name=?''', (group_id, g.user['id'], original))
                db().commit()
                flash('Đã nhân bản nhóm cùng danh sách data. Không tạo trùng hồ sơ khách hàng hoặc sao chép chiến dịch.', 'success')
                return redirect(url_for('data_groups', group=name))
            except ValueError as error:
                db().rollback()
                flash(str(error), 'error')
        return render_template('group_duplicate.html', original=original, count=count, page='data_groups')

    @app.route('/data-groups/delete', methods=['GET','POST'])
    @login_required
    def delete_data_group():
        name = request.form.get('group', '') if request.method == 'POST' else request.args.get('group', '')
        metadata = require_group(name)
        if request.method == 'POST':
            if request.form.get('confirm_delete') != 'yes':
                abort(400)
            db().execute('BEGIN IMMEDIATE')
            current = require_group(name)
            if request.form.get('group_id') and (not current or str(current['id']) != request.form['group_id']):
                abort(409, 'Nhóm đã thay đổi. Tải lại trước khi xóa.')
            remove_data_group(db,g.user['id'],name)
            db().commit()
            flash('Đã xóa nhóm. Khách hàng và lịch sử nguồn được giữ nguyên; chiến dịch cũ giữ danh sách hiện tại.', 'success')
            return redirect(url_for('data_groups'))
        return render_template('group_delete.html', name=name, metadata=metadata, page='data_groups')

    def group_import_input(preview=False):
        group = request.form.get('group', '')
        require_group(group)
        if request.form.get('data_type', 'phone') != 'phone':
            raise ValueError('Hiện hỗ trợ Zalo – User theo SĐT.')
        incoming = {phone: {'phone': phone} for phone in parse_phones(request.form.get('phones', ''))}
        invalid = []
        if request.form.get('import_mode') == 'mapped':
            if incoming:
                raise ValueError('Chỉ nhập một nguồn dữ liệu mỗi lần.')
            mapping = {key: request.form.get('column_' + key, '') for key in ('name','phone','info1','info2','info3','info4','info5')}
            mapped, invalid = read_mapped_contacts(request.files.get('file'), parse_phones, mapping,
                                                   request.form.get('skip_header') == 'yes', report=True,
                                                   sheet_name=request.form.get('sheet') or None)
            incoming.update(mapped)
            if invalid and not preview and request.form.get('skip_invalid') != 'yes':
                first = invalid[0]
                raise ValueError(f"Có {len(invalid)} dòng lỗi; dòng {first['row']}, SĐT {first['phone']!r}: {first['reason']} Kiểm tra bảng lỗi hoặc xác nhận bỏ qua dòng lỗi.")
        else:
            incoming.update(read_contacts(request.files.get('file'), parse_phones))
        if (not incoming and not (preview and invalid)) or len(incoming) > 500:
            raise ValueError('Mỗi lần nhập từ 1 đến 500 số điện thoại.')
        return group, incoming, invalid

    @app.get('/data-groups/source-history/<int:contact_id>')
    @login_required
    def group_source_history(contact_id):
        group = request.args.get('group', '')
        require_group(group)
        contact = db().execute('''SELECT id,phone,data_source,current_source_id FROM contacts WHERE id=? AND user_id=?
            AND id IN (SELECT contact_id FROM contact_group_memberships WHERE user_id=? AND group_name=?)''',
            (contact_id,g.user['id'],g.user['id'],group)).fetchone()
        if not contact:
            abort(404)
        sources = []
        for source in db().execute('SELECT * FROM contact_data_sources WHERE contact_id=? AND user_id=? ORDER BY id DESC',
                                    (contact_id,g.user['id'])):
            time = datetime.fromisoformat(source['created_at']).replace(tzinfo=timezone.utc).astimezone(ZoneInfo('Asia/Bangkok')).strftime('%H:%M:%S %d/%m/%Y') if source['created_at'] else None
            sources.append(dict(id=source['id'], label=source['label'], filename=source['filename'],
                                source_type=source['source_type'], group_id=source['group_id'], batch_id=source['batch_id'],
                                created_at=time, current=source['id']==contact['current_source_id']))
        return jsonify(phone=contact['phone'], sources=sources)

    @app.post('/data-groups/import/columns')
    @login_required
    def inspect_group_import():
        group = request.form.get('group', '')
        require_group(group)
        try:
            source = read_sheet_rows(request.files.get('file'), sheet_name=request.form.get('sheet') or None, details=True)
            rows = source['rows']
            width = max(len(row) for row in rows)
            aliases = {'mobile':'phone', 'full name':'name', 'fullname':'name'}
            headers = [aliases.get(canonical_header(cell), canonical_header(cell)) for cell in rows[0]]
            fields = ('name','phone','info1','info2','info3','info4','info5')
            mapping = {key: str(headers.index(key)) if key in headers else '' for key in fields}
            if not mapping['phone']:
                # Headerless customer sheets start with phone numbers in A.
                # Do not assign that column to a second field as well.
                mapping = {key: value if value != '0' else '' for key, value in mapping.items()}
                mapping['phone'] = '0'
            return jsonify(columns=[{'index': index, 'sample': rows[0][index][:100] if index < len(rows[0]) else ''}
                                    for index in range(width)], row_count=len(rows),
                           preview_rows=[[cell[:1000] for cell in row] for row in rows[:6]],
                           mapping=mapping, skip_header='phone' in headers,
                           sheets=source['sheets'], sheet=source['sheet'])
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.post('/data-groups/import/preview')
    @login_required
    def preview_group_import():
        try:
            group, incoming, invalid = group_import_input(preview=True)
            rows = []
            existing_count = 0
            for phone, row in incoming.items():
                existing = db().execute('SELECT * FROM contacts WHERE user_id=? AND phone=?', (g.user['id'], phone)).fetchone()
                if existing and db().execute('SELECT 1 FROM contact_group_memberships WHERE user_id=? AND group_name=? AND contact_id=?',
                                             (g.user['id'],group,existing['id'])).fetchone():
                    existing_count += 1
                source = dict(existing) if existing else row
                rows.append({key: source.get(key, '') for key in ('name','phone','email','zalo_id','info1','info2','info3','info4','info5')})
            return jsonify(rows=rows, total=len(rows), existing=existing_count, added=len(rows)-existing_count, invalid=len(invalid), invalid_rows=invalid)
        except ValueError as error:
            return jsonify(error=str(error)), 400

    @app.post('/data-groups/import')
    @login_required
    def import_group_data():
        group = request.form.get('group', '')
        try:
            group, incoming, invalid = group_import_input()
            consent = default_contact_consent(request.form, 'yes')
            db().execute('BEGIN IMMEDIATE')
            require_group(group)
            upload = request.files.get('file')
            result = save_group_members(db, g.user['id'], group, incoming, consent,
                                        upload.filename if upload else '', confirm_existing=request.form.get('consent')=='yes')
            added, created_profiles, recorded = (result[key] for key in ('added','created_profiles','recorded'))
            db().commit()
            flash(f"Đã thêm {added} số vào nhóm ({created_profiles} hồ sơ mới, {added-created_profiles} hồ sơ đã có). {len(incoming)-added} số đã thuộc nhóm. Đã ghi nhận đồng ý cho {result['confirmed']} hồ sơ đã có. Ghi nguồn cho {recorded} khách hàng, bỏ qua {len(invalid)} dòng lỗi đã xác nhận. Giữ nguyên thông tin và nhóm gốc.", 'success')
        except ValueError as error:
            db().rollback()
            flash(str(error), 'error')
        return redirect(url_for('data_groups', group=group))
