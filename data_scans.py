"""Private, persisted, read-only Zalo scans with explicit phone-only imports."""
import io
import json
import re
from urllib.parse import urlsplit

from flask import abort, g, jsonify, request, send_file
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

from data_groups import save_group_members

KINDS={'friends':'Danh sách bạn bè','groups':'Danh sách group đã tham gia',
       'members':'Thành viên group','history':'Khách đã gửi tin trong ZaloFlow'}
ERRORS={'session':'Tài khoản chưa đăng nhập hoặc phiên đã hết hạn. Đăng nhập QR lại.',
        'network':'Kết nối Zalo bị gián đoạn. Kết quả đã tải vẫn được giữ; bạn có thể tải tiếp.',
        'rate_limited':'Zalo đang giới hạn tra cứu. Chờ rồi thử lại.',
        'connector_unavailable':'VPS chưa sẵn sàng kết nối Zalo.'}
ID=re.compile(r'\d{1,30}\Z')


def public_avatar(value):
    if not isinstance(value,str) or len(value)>1500:return ''
    try:
        url=urlsplit(value);host=url.hostname or ''
        if url.scheme=='https' and not url.username and not url.password and url.port in (None,443) and any(host==base or host.endswith('.'+base) for base in ('zadn.vn','zaloapp.com','zalo.me')):
            return value
    except ValueError:pass
    return ''


def normalized_phone(raw,parse_phones):
    if not isinstance(raw,str) or not raw.strip():return ''
    raw=raw.strip()
    if raw.isdigit() and len(raw)==9:raw='0'+raw
    try:
        phones=parse_phones(raw)
        return phones[0] if len(phones)==1 else ''
    except ValueError:return ''


def register_data_scans(app,db,login_required,connector,parse_phones):
    with app.app_context():
        db().executescript('''CREATE TABLE IF NOT EXISTS data_scans (
            id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),
            account_id INTEGER NOT NULL REFERENCES zalo_accounts(id),kind TEXT NOT NULL,
            remote_group TEXT NOT NULL DEFAULT '',source_name TEXT NOT NULL DEFAULT '',
            next_offset INTEGER NOT NULL DEFAULT 0,has_more INTEGER NOT NULL DEFAULT 1,
            total INTEGER,limited INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL DEFAULT 'ready',
            error TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE INDEX IF NOT EXISTS data_scans_owner ON data_scans(user_id,id);
            CREATE TABLE IF NOT EXISTS data_scan_rows (
            id INTEGER PRIMARY KEY,scan_id INTEGER NOT NULL REFERENCES data_scans(id) ON DELETE CASCADE,
            uid TEXT NOT NULL,name TEXT NOT NULL,phone TEXT NOT NULL DEFAULT '',avatar TEXT NOT NULL DEFAULT '',
            role TEXT NOT NULL DEFAULT 'member',kind TEXT NOT NULL DEFAULT 'user',member_count INTEGER NOT NULL DEFAULT 0,
            phone_state TEXT NOT NULL DEFAULT 'unchecked',UNIQUE(scan_id,uid));''')
        if 'loading_at' not in {row['name'] for row in db().execute('PRAGMA table_info(data_scans)')}:
            db().execute("ALTER TABLE data_scans ADD COLUMN loading_at TEXT NOT NULL DEFAULT ''")
        db().commit()

    def own_scan(scan_id):
        row=db().execute('SELECT * FROM data_scans WHERE id=? AND user_id=?',(scan_id,g.user['id'])).fetchone()
        if not row:abort(404)
        return row

    def account(account_id,remote=True):
        row=db().execute('SELECT * FROM zalo_accounts WHERE id=? AND user_id=? AND deleted_at IS NULL',(account_id,g.user['id'])).fetchone()
        if not row:abort(404)
        if remote and (not app.config['ZALO_QR_ENABLED'] or connector.status(g.user['id'],row['id']).get('state')!='connected'):
            raise ValueError(ERRORS['session'])
        return row

    def clean_result(result):
        if not isinstance(result,dict) or result.get('state')!='ok':
            reason=result.get('reason') if isinstance(result,dict) else ''
            raise ValueError(ERRORS.get(reason,'Không tải được dữ liệu Zalo. Kiểm tra quyền xem nhóm hoặc thử lại sau.'))
        rows=result.get('rows')
        if not isinstance(rows,list) or len(rows)>100:raise ValueError('Dữ liệu Zalo trả về không hợp lệ.')
        output=[]
        for row in rows:
            if not isinstance(row,dict) or not ID.fullmatch(str(row.get('uid',''))):raise ValueError('Dữ liệu Zalo trả về không hợp lệ.')
            kind='group' if row.get('kind')=='group' else 'user'
            role=row.get('role') if row.get('role') in ('friend','member','admin','owner','group','customer') else 'member'
            count=row.get('member_count',0)
            output.append(dict(uid=str(row['uid']),name=str(row.get('name') or row['uid'])[:100],
                phone=normalized_phone(row.get('phone',''),parse_phones) if kind=='user' else '',
                avatar=public_avatar(row.get('avatar')),role=role,kind=kind,
                member_count=max(0,min(count,1000000)) if isinstance(count,int) else 0))
        return output

    def history_page(scan):
        base='''FROM message_sends s JOIN campaigns c ON c.id=s.campaign_id
            WHERE c.user_id=? AND s.account_id=? AND s.state='sent' AND s.recipient_id!='' '''
        args=(g.user['id'],scan['account_id'])
        total=db().execute('SELECT count(DISTINCT s.recipient_id) '+base,args).fetchone()[0]
        rows=db().execute('''SELECT s.recipient_id AS uid,s.recipient_name AS name,s.recipient_phone AS phone,
            '' AS avatar,'customer' AS role,'user' AS kind,0 AS member_count '''+base+'''
            AND s.id IN (SELECT max(s2.id) FROM message_sends s2 JOIN campaigns c2 ON c2.id=s2.campaign_id
                WHERE c2.user_id=? AND s2.account_id=? AND s2.state='sent' GROUP BY s2.recipient_id)
            ORDER BY s.id DESC LIMIT 100 OFFSET ?''',(*args,*args,scan['next_offset'])).fetchall()
        return dict(state='ok',rows=[dict(row) for row in rows],total=total,
            has_more=scan['next_offset']+100<min(total,10000),next_offset=scan['next_offset']+100,
            limited=total>10000,source_name=KINDS['history'])

    def load_page(scan_id):
        scan=own_scan(scan_id)
        account(scan['account_id'],remote=scan['kind']!='history')
        if not scan['has_more']:return
        updated=db().execute("UPDATE data_scans SET status='loading',error='',loading_at=CURRENT_TIMESTAMP WHERE id=? AND (status!='loading' OR loading_at<datetime('now','-2 minutes'))",(scan_id,)).rowcount
        db().commit()
        if not updated:abort(409,'Lượt quét này đang tải dữ liệu. Chờ hoàn tất trước khi tải tiếp.')
        try:
            try:
                result=history_page(scan) if scan['kind']=='history' else connector.scan_action(g.user['id'],scan['account_id'],scan['kind'],offset=scan['next_offset'],group_id=scan['remote_group'])
            except Exception:
                result={'state':'error','reason':'network'}
            rows=clean_result(result)
            offset=result.get('next_offset')
            if offset!=scan['next_offset']+100:raise ValueError('Phân trang Zalo không hợp lệ.')
            db().execute('BEGIN IMMEDIATE')
            account(scan['account_id'],remote=False)
            inserted=0
            for row in rows:
                inserted+=db().execute('''INSERT OR IGNORE INTO data_scan_rows(scan_id,uid,name,phone,avatar,role,kind,member_count)
                    VALUES (?,?,?,?,?,?,?,?)''',(scan_id,*[row[key] for key in ('uid','name','phone','avatar','role','kind','member_count')])).rowcount
            has_more=bool(result.get('has_more')) and offset<10000
            stalled=has_more and not inserted
            total=result.get('total')
            total=total if isinstance(total,int) and 0<=total<=1000000 else None
            db().execute('''UPDATE data_scans SET status='ready',loading_at='',next_offset=?,has_more=?,total=?,limited=?,source_name=? WHERE id=?''',
                (offset,int(has_more and not stalled),total,int(bool(result.get('limited')) or stalled),str(result.get('source_name') or KINDS[scan['kind']])[:100],scan_id))
            db().commit()
        except Exception as error:
            db().rollback()
            message=str(error) if isinstance(error,ValueError) else 'Không tải được dữ liệu Zalo. Kết quả trước đó được giữ lại.'
            db().execute("UPDATE data_scans SET status='error',loading_at='',error=? WHERE id=?",(message,scan_id));db().commit()
            raise ValueError(message) from None

    def filtered_rows(scan_id,form):
        own_scan(scan_id)
        where='r.scan_id=?';args=[scan_id]
        query=form.get('q','').strip()[:120]
        if query:where+=' AND (r.name LIKE ? OR r.uid LIKE ? OR r.phone LIKE ?)';args.extend(['%'+query+'%']*3)
        role=form.get('role','')
        if role:
            if role not in ('friend','member','admin','owner','group','customer'):abort(400)
            where+=' AND r.role=?';args.append(role)
        phone=form.get('phone','')
        if phone=='yes':where+=" AND r.phone!=''"
        elif phone=='no':where+=" AND r.phone=''"
        elif phone:abort(400)
        return where,args

    def selected_rows(scan_id):
        where,args=filtered_rows(scan_id,request.form)
        raw=request.form.get('ids','')
        if raw:
            try:ids=json.loads(raw)
            except ValueError:abort(400)
            if not isinstance(ids,list) or not ids or len(ids)>10000 or any(type(value) is not int or value<1 for value in ids):abort(400)
            ids=set(ids)
            where+=' AND r.id IN ('+','.join('?' for _ in ids)+')';args.extend(ids)
        else:ids=None
        rows=db().execute('SELECT r.* FROM data_scan_rows r WHERE '+where+' ORDER BY r.id',args).fetchall()
        if ids is not None and len(rows)!=len(ids):abort(404)
        if not rows:raise ValueError('Chọn ít nhất một dòng dữ liệu.')
        if request.form.get('deduplicate','yes')=='yes':
            seen=set();unique=[]
            for row in rows:
                key=(row['kind'],row['phone'] or row['uid'])
                if key not in seen:seen.add(key);unique.append(row)
            rows=unique
        return rows

    @app.get('/data-scans/catalog')
    @login_required
    def scan_catalog():
        accounts=db().execute('SELECT id,name FROM zalo_accounts WHERE user_id=? AND deleted_at IS NULL ORDER BY name',(g.user['id'],)).fetchall()
        scans=db().execute('''SELECT s.id,s.kind,s.source_name,s.created_at,a.name AS account_name,
            (SELECT count(*) FROM data_scan_rows r WHERE r.scan_id=s.id) AS total FROM data_scans s
            JOIN zalo_accounts a ON a.id=s.account_id WHERE s.user_id=? ORDER BY s.id DESC LIMIT 30''',(g.user['id'],)).fetchall()
        groups=db().execute('SELECT id,name FROM data_groups WHERE user_id=? AND deleted_at IS NULL ORDER BY name',(g.user['id'],)).fetchall()
        return jsonify(accounts=[dict(row,connected=connector.status(g.user['id'],row['id']).get('state')=='connected') for row in accounts],
                       scans=[dict(row) for row in scans],groups=[dict(row) for row in groups])

    @app.post('/data-scans/groups')
    @login_required
    def scan_group_options():
        try:
            sender=account(request.form.get('account_id'))
            offset=int(request.form.get('offset',0))
            if offset<0 or offset>9900 or offset%100:abort(400)
            try:result=connector.scan_action(g.user['id'],sender['id'],'groups',offset=offset)
            except Exception:result={'state':'error','reason':'network'}
            rows=clean_result(result)
            return jsonify(rows=rows,has_more=bool(result.get('has_more')),next_offset=offset+100)
        except (ValueError,TypeError) as error:return jsonify(error=str(error)),400

    @app.post('/data-scans/start')
    @login_required
    def start_data_scan():
        scan_id=None
        try:
            kind=request.form.get('kind','')
            if kind not in KINDS:raise ValueError('Chọn nguồn quét dữ liệu.')
            sender=account(request.form.get('account_id'),remote=kind!='history')
            remote_group=request.form.get('remote_group','') if kind=='members' else ''
            if kind=='members' and not ID.fullmatch(remote_group):raise ValueError('Tải và chọn group Zalo đã tham gia.')
            cur=db().execute('INSERT INTO data_scans(user_id,account_id,kind,remote_group,source_name) VALUES (?,?,?,?,?)',
                (g.user['id'],sender['id'],kind,remote_group,KINDS[kind]))
            scan_id=cur.lastrowid;db().commit();load_page(scan_id)
            return jsonify(scan_id=scan_id)
        except ValueError as error:return jsonify(error=str(error),scan_id=scan_id),400

    @app.post('/data-scans/<int:scan_id>/more')
    @login_required
    def more_data_scan(scan_id):
        try:load_page(scan_id);return jsonify(scan_id=scan_id)
        except ValueError as error:return jsonify(error=str(error)),400

    @app.get('/data-scans/<int:scan_id>/rows')
    @login_required
    def data_scan_rows(scan_id):
        scan=own_scan(scan_id);where,args=filtered_rows(scan_id,request.args)
        total=db().execute('SELECT count(*) FROM data_scan_rows r WHERE '+where,args).fetchone()[0]
        number=request.args.get('p',1,type=int)
        number=max(1,min(number,max(1,(total+99)//100)))
        rows=db().execute('SELECT r.* FROM data_scan_rows r WHERE '+where+' ORDER BY r.id LIMIT 100 OFFSET ?',(*args,(number-1)*100)).fetchall()
        count=db().execute('SELECT count(*) FROM data_scan_rows WHERE scan_id=?',(scan_id,)).fetchone()[0]
        return jsonify(scan=dict(scan),rows=[dict(row) for row in rows],total=total,loaded=count,page=number,pages=max(1,(total+99)//100))

    @app.get('/data-scans/<int:scan_id>/ids')
    @app.get('/data-scans/<int:scan_id>/phone-ids')
    @login_required
    def scan_row_ids(scan_id):
        where,args=filtered_rows(scan_id,request.args)
        if request.path.endswith('/phone-ids'):where+=" AND r.phone!='' AND r.kind='user'"
        return jsonify(ids=[row['id'] for row in db().execute('SELECT r.id FROM data_scan_rows r WHERE '+where+' ORDER BY r.id LIMIT 10000',args)])

    @app.post('/data-scans/<int:scan_id>/export')
    @login_required
    def export_data_scan(scan_id):
        try:
            rows=selected_rows(scan_id)
            book=Workbook();sheet=book.active;sheet.title='Data quét'
            sheet.append(['STT','Tên','Số điện thoại','UID','Loại','Vai trò','Thành viên','Kiểm tra SĐT'])
            for index,row in enumerate(rows,1):
                sheet.append([ILLEGAL_CHARACTERS_RE.sub('',str(value)) for value in (index,row['name'],row['phone'],row['uid'],row['kind'],row['role'],row['member_count'],row['phone_state'])])
                for cell in sheet[sheet.max_row]:cell.data_type='s'
            output=io.BytesIO();book.save(output);output.seek(0)
            return send_file(output,mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',as_attachment=True,download_name=f'data-quet-{scan_id}.xlsx')
        except ValueError as error:return jsonify(error=str(error)),400

    @app.post('/data-scans/<int:scan_id>/import')
    @login_required
    def import_data_scan(scan_id):
        try:
            scan=own_scan(scan_id);rows=selected_rows(scan_id)
            if scan['kind']=='groups':raise ValueError('Danh sách group dùng cho chiến dịch gửi group, không phải SĐT khách hàng.')
            incoming={row['phone']:dict(name=row['name'],phone=row['phone'],zalo_id=row['uid']) for row in rows
                      if row['phone'] and row['phone_state'] not in ('not_found','mismatch')}
            if not incoming:raise ValueError('Không có SĐT hợp lệ để thêm. Bạn vẫn có thể lưu và xuất Excel các UID.')
            consent=int(request.form.get('consent')=='yes')
            db().execute('BEGIN IMMEDIATE')
            group=db().execute('SELECT * FROM data_groups WHERE id=? AND user_id=? AND deleted_at IS NULL',(request.form.get('group_id'),g.user['id'])).fetchone()
            if not group:abort(404)
            result=save_group_members(db,g.user['id'],group['name'],incoming,consent,scan['source_name'],source_type='scan',confirm_existing=False)
            db().commit()
            return jsonify(**result,eligible=len(incoming),skipped=len(rows)-len(incoming),group=group['name'])
        except ValueError as error:
            db().rollback();return jsonify(error=str(error)),400

    @app.post('/data-scans/<int:scan_id>/check-phone')
    @login_required
    def check_scan_phone(scan_id):
        scan=own_scan(scan_id)
        row=db().execute('SELECT * FROM data_scan_rows WHERE id=? AND scan_id=?',(request.form.get('row_id'),scan_id)).fetchone()
        if not row:abort(404)
        if not row['phone'] or row['kind']!='user':return jsonify(error='Dòng này không có SĐT công khai hợp lệ.'),400
        try:account(scan['account_id'])
        except ValueError as error:return jsonify(error=str(error)),400
        try:result=connector.message_action(g.user['id'],scan['account_id'],'resolve',phone=row['phone'])
        except Exception:result={}
        result=result if isinstance(result,dict) else {}
        state='matched' if result.get('state')=='resolved' and str(result.get('uid'))==row['uid'] else 'mismatch' if result.get('state')=='resolved' else 'not_found' if result.get('state')=='not_found' else 'unavailable'
        db().execute('UPDATE data_scan_rows SET phone_state=? WHERE id=?',(state,row['id']));db().commit()
        return jsonify(state=state,rate_limited=result.get('lookup_reason')=='rate_limited')
