"""Immutable group destinations, explicit sends and scheduled group messages."""
import json
from datetime import datetime, timedelta, timezone

from flask import abort, flash, g, redirect, render_template, request, url_for

from campaign_errors import error_description
from campaign_limits import enforce_limits, save_limits
from campaign_schedule import active_window, local_now, manual_schedule_block, save_schedule
from rich_message import read_message, render_message, load_styles


def initialize_group_campaigns(db):
    columns={row['name'] for row in db().execute('PRAGMA table_info(campaigns)')}
    if 'campaign_type' not in columns:
        db().execute("ALTER TABLE campaigns ADD COLUMN campaign_type TEXT NOT NULL DEFAULT 'phone'")
    db().executescript('''CREATE TABLE IF NOT EXISTS group_campaign_targets (
        id INTEGER PRIMARY KEY,campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
        source_row_id INTEGER NOT NULL REFERENCES data_scan_rows(id),group_id TEXT NOT NULL,name TEXT NOT NULL,
        UNIQUE(campaign_id,group_id));
        CREATE TABLE IF NOT EXISTS group_message_sends (
        id INTEGER PRIMARY KEY,campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
        target_id INTEGER NOT NULL REFERENCES group_campaign_targets(id),account_id INTEGER NOT NULL REFERENCES zalo_accounts(id),
        group_id TEXT NOT NULL,group_name TEXT NOT NULL,message TEXT NOT NULL,message_styles TEXT NOT NULL DEFAULT '[]',
        media_id INTEGER REFERENCES campaign_media(id),state TEXT NOT NULL DEFAULT 'prepared',message_id TEXT NOT NULL DEFAULT '',
        detail TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,claimed_at TEXT,finished_at TEXT,
        UNIQUE(campaign_id,target_id));
        CREATE INDEX IF NOT EXISTS group_message_attempts ON group_message_sends(campaign_id,claimed_at);''')
    db().commit()


def group_counts(db,campaign_id):
    count=db().execute('SELECT count(*) FROM group_campaign_targets WHERE campaign_id=?',(campaign_id,)).fetchone()[0]
    row=db().execute('''SELECT count(*) AS sent_total,coalesce(sum(state='sent'),0) AS confirmed,
        coalesce(sum(state IN ('failed','unknown','skipped')),0) AS skipped,coalesce(sum(state='sending'),0) AS sending,
        coalesce(sum(state='prepared'),0) AS waiting FROM group_message_sends WHERE campaign_id=?''',(campaign_id,)).fetchone()
    return dict(row,audience=count,uncertain=0,failed=0,total=0)


class GroupCampaignRunner:
    def __init__(self,app,db,manager,connector):
        self.app,self.db,self.manager,self.connector=app,db,manager,connector

    def own(self,campaign_id,deleted=False):
        campaign=self.manager.owned(campaign_id,include_deleted=deleted)
        if campaign['campaign_type']!='zalo_group':abort(404)
        return campaign

    def sender(self,account_id):
        sender=self.db().execute('SELECT * FROM zalo_accounts WHERE id=? AND user_id=? AND deleted_at IS NULL',(account_id,g.user['id'])).fetchone()
        if not sender or not self.app.config['ZALO_QR_ENABLED'] or self.connector.status(g.user['id'],account_id).get('state')!='connected':
            raise ValueError('Tài khoản gửi chưa đăng nhập Zalo. Đăng nhập lại trước khi gửi group.')
        return sender

    def prepare(self,campaign,target):
        self.db().execute('BEGIN IMMEDIATE')
        try:
            current=self.own(campaign['id']);self.manager.require_active(current)
            target=self.db().execute('SELECT * FROM group_campaign_targets WHERE id=? AND campaign_id=?',(target['id'],current['id'])).fetchone()
            if not target:abort(404)
            self.manager.require_account(current['account_id'])
            existing=self.db().execute('SELECT * FROM group_message_sends WHERE campaign_id=? AND target_id=?',(current['id'],target['id'])).fetchone()
            if existing:self.db().commit();return existing
            message,styles=render_message(current['message'],current['message_html'],dict(name=target['name'],phone='',zalo_id=target['group_id']),
                dict(name=target['name'],uid=target['group_id']),variant_index=current['next_message_variant'])
            cur=self.db().execute('''INSERT INTO group_message_sends(campaign_id,target_id,account_id,group_id,group_name,message,message_styles,media_id)
                VALUES (?,?,?,?,?,?,?,?)''',(current['id'],target['id'],current['account_id'],target['group_id'],target['name'],message,json.dumps(styles),current['media_id']))
            self.db().execute('UPDATE campaigns SET next_message_variant=next_message_variant+1 WHERE id=?',(current['id'],))
            self.manager.event(current['id'],'group_preview',f'Tạo bản xem trước gửi group {target["name"]} ({target["group_id"]}). Chưa gửi tin.')
            self.db().commit()
            return self.db().execute('SELECT * FROM group_message_sends WHERE id=?',(cur.lastrowid,)).fetchone()
        except BaseException:self.db().rollback();raise

    def dispatch(self,campaign_id,send_id,now=local_now,scheduled=False):
        current=self.own(campaign_id);self.sender(current['account_id'])
        record=self.db().execute('SELECT * FROM group_message_sends WHERE id=? AND campaign_id=?',(send_id,campaign_id)).fetchone()
        if not record:abort(404)
        styles=load_styles(record['message_styles'],record['message'])
        attachment=self.manager.attachment(record['media_id']) if record['media_id'] else None
        self.db().execute('BEGIN IMMEDIATE')
        try:
            campaign=self.own(campaign_id);self.manager.require_active(campaign)
            record=self.db().execute('SELECT * FROM group_message_sends WHERE id=? AND campaign_id=?',(send_id,campaign_id)).fetchone()
            self.manager.require_account(record['account_id'])
            if record['account_id']!=campaign['account_id']:raise ValueError('Bản xem trước thuộc tài khoản cũ. Không gửi bằng tài khoản khác.')
            if scheduled and (self.app.extensions['campaign_scheduler'].stopping or campaign['schedule_revision']!=current['schedule_revision'] or not active_window(campaign,now())):
                raise ValueError('Lịch đã dừng hoặc ngoài giờ chạy.')
            blocked=manual_schedule_block(campaign,now())
            if blocked:raise ValueError(blocked)
            if record['state']!='prepared':self.db().rollback();return False
            # Same group is never dispatched twice in a campaign, even after restart.
            enforce_limits(self.db,campaign,'send',now=now())
            stamp=now().astimezone(timezone.utc).replace(tzinfo=None,microsecond=0).isoformat(' ')
            if campaign['schedule_wait_until'] and campaign['schedule_wait_until']>stamp:raise ValueError('Đang nghỉ theo cài đặt trước group tiếp theo.')
            self.db().execute("UPDATE group_message_sends SET state='sending',claimed_at=? WHERE id=?",(stamp,send_id))
            if scheduled:self.db().execute('UPDATE campaigns SET schedule_first_day=coalesce(schedule_first_day,?),schedule_carry=1 WHERE id=?',(now().date().isoformat(),campaign_id))
            self.manager.event(campaign_id,'group_send',f'Bắt đầu gửi group {record["group_name"]} ({record["group_id"]}). Nguồn: '+('Theo lịch tự động.' if scheduled else 'Xác nhận thủ công.'))
            self.db().commit()
        except BaseException:self.db().rollback();raise
        try:
            result=self.connector.message_action(g.user['id'],record['account_id'],'send',uid=record['group_id'],message=record['message'],thread_type=1,
                **({'styles':styles} if styles else {}),**({'attachment':attachment} if attachment else {}))
        except Exception:result={'state':'unknown'}
        result=result if isinstance(result,dict) else {}
        state=result.get('state') if result.get('state') in ('sent','failed','unknown') else 'unknown'
        detail='Zalo đã tiếp nhận tin nhắn gửi group.' if state=='sent' else error_description(result) or ('Chưa xác định kết quả. Kiểm tra hội thoại group; không tự gửi lại.' if state=='unknown' else 'Gửi group không thành công. Bỏ qua lượt này và tiếp tục group khác.')
        self.db().execute('BEGIN IMMEDIATE')
        self.db().execute('UPDATE group_message_sends SET state=?,message_id=?,detail=?,finished_at=CURRENT_TIMESTAMP WHERE id=?',
            (state,str(result.get('message_id',''))[:100] if state=='sent' else '',detail,send_id))
        latest=self.own(campaign_id,deleted=True)
        until=(now().astimezone(timezone.utc)+timedelta(seconds=latest['interval_seconds'])).replace(tzinfo=None,microsecond=0).isoformat(' ')
        self.db().execute('UPDATE campaigns SET schedule_wait_until=?,schedule_wait_message=? WHERE id=?',(until,'Nghỉ theo cài đặt trước khi xử lý group tiếp theo.',campaign_id))
        self.manager.event(campaign_id,'group_result',f'Group {record["group_name"]} ({record["group_id"]}): {detail}')
        if latest['interval_seconds']:self.manager.event(campaign_id,'group_rest',f'Nghỉ {latest["interval_seconds"]} giây trước group tiếp theo.')
        self.db().commit();return True

    def tick(self,campaign_id,now):
        campaign=self.own(campaign_id)
        if not active_window(campaign,now()):return
        stamp=now().astimezone(timezone.utc).replace(tzinfo=None,microsecond=0).isoformat(' ')
        if campaign['schedule_wait_until'] and campaign['schedule_wait_until']>stamp:return
        # A claim has a 90-second grace period, longer than the connector timeout.
        active=self.db().execute("SELECT * FROM group_message_sends WHERE campaign_id=? AND state='sending' ORDER BY id LIMIT 1",(campaign_id,)).fetchone()
        if active:
            elapsed=(now().astimezone(timezone.utc)-datetime.fromisoformat(active['claimed_at']).replace(tzinfo=timezone.utc)).total_seconds()
            if elapsed<90:return
            self.db().execute("UPDATE group_message_sends SET state='unknown',detail='Lượt gửi bị gián đoạn. Không tự gửi lại.',finished_at=CURRENT_TIMESTAMP WHERE id=?",(active['id'],))
            self.manager.event(campaign_id,'group_recovery',f'Lượt group #{active["id"]} bị gián đoạn; bỏ qua, không tự gửi lại.')
            until=(now().astimezone(timezone.utc)+timedelta(seconds=campaign['interval_seconds'])).replace(tzinfo=None,microsecond=0).isoformat(' ')
            self.db().execute('UPDATE campaigns SET schedule_wait_until=?,schedule_wait_message=? WHERE id=?',(until,'Nghỉ trước group tiếp theo.',campaign_id));self.db().commit();return
        target=self.db().execute('''SELECT t.* FROM group_campaign_targets t LEFT JOIN group_message_sends s ON s.target_id=t.id
            WHERE t.campaign_id=? AND (s.id IS NULL OR s.state='prepared') ORDER BY t.id LIMIT 1''',(campaign_id,)).fetchone()
        if not target:
            self.db().execute("UPDATE campaigns SET schedule_status='Đã xử lý hết danh sách group',schedule_carry=0 WHERE id=?",(campaign_id,));self.db().commit();return
        self.sender(campaign['account_id'])
        record=self.prepare(campaign,target)
        self.dispatch(campaign_id,record['id'],now=now,scheduled=True)
        self.db().execute("UPDATE campaigns SET schedule_first_day=coalesce(schedule_first_day,?),schedule_carry=1,schedule_status='Đang xử lý group' WHERE id=?",(now().date().isoformat(),campaign_id));self.db().commit()


def register_group_campaigns(app,db,login_required,manager,connector):
    with app.app_context():initialize_group_campaigns(db)
    runner=GroupCampaignRunner(app,db,manager,connector);app.extensions['group_campaign_runner']=runner

    @app.before_request
    def route_group_campaign_views():
        legacy={'campaign_detail','edit_campaign','duplicate_campaign','campaign_report','campaign_content','campaign_data','campaign_exclusions','campaign_duplicate_check','prepare_send'}
        if not g.get('user') or request.endpoint not in legacy or not request.view_args:return
        campaign_id=request.view_args.get('campaign_id')
        campaign=db().execute('SELECT * FROM campaigns WHERE id=? AND user_id=?',(campaign_id,g.user['id'])).fetchone()
        if campaign and campaign['campaign_type']=='zalo_group':
            if request.method!='GET':abort(400,'Dùng màn hình chiến dịch group để thực hiện thao tác này.')
            endpoint='edit_group_campaign' if request.endpoint in ('edit_campaign','campaign_content') else 'duplicate_group_campaign' if request.endpoint=='duplicate_campaign' else 'group_campaign_detail'
            return redirect(url_for(endpoint,campaign_id=campaign_id))

    def save_form(campaign_id=None):
        name=request.form.get('name','').strip();message,html=read_message(request.form)
        if not name or len(name)>120 or not message:raise ValueError('Nhập tên chiến dịch và nội dung gửi group.')
        account_id=request.form.get('account_id')
        if not db().execute('SELECT 1 FROM zalo_accounts WHERE id=? AND user_id=? AND deleted_at IS NULL',(account_id,g.user['id'])).fetchone():raise ValueError('Chọn tài khoản Zalo hợp lệ.')
        try:ids=json.loads(request.form.get('group_scan_row_ids','[]'))
        except ValueError:raise ValueError('Chọn lại danh sách group.') from None
        if not isinstance(ids,list) or not ids or len(ids)>10000 or any(type(value) is not int for value in ids):raise ValueError('Chọn từ 1 đến 10.000 group Zalo.')
        ids=set(ids)
        targets=db().execute('''SELECT r.* FROM data_scan_rows r JOIN data_scans s ON s.id=r.scan_id
            WHERE s.user_id=? AND s.account_id=? AND s.kind='groups' AND r.kind='group' AND r.id IN ('''+','.join('?' for _ in ids)+')',(g.user['id'],account_id,*ids)).fetchall()
        if len(targets)!=len(ids):raise ValueError('Group không thuộc tài khoản gửi. Tải và chọn lại group của đúng tài khoản.')
        by_uid={row['uid']:row for row in targets}
        # Validate all personalized variants before retaining a new campaign.
        for target in by_uid.values():render_message(message,html,dict(name=target['name'],phone='',zalo_id=target['uid']),dict(name=target['name'],uid=target['uid']),variant_index=0)
        if campaign_id:
            runner.own(campaign_id)
            if db().execute('SELECT 1 FROM group_message_sends WHERE campaign_id=? AND claimed_at IS NOT NULL',(campaign_id,)).fetchone():raise ValueError('Chiến dịch đã có lượt gửi. Nhân bản để thay nội dung hoặc danh sách; lịch và giới hạn vẫn có thể chỉnh riêng.')
            if db().execute('SELECT 1 FROM group_message_sends WHERE campaign_id=?',(campaign_id,)).fetchone():raise ValueError('Chiến dịch đã có bản xem trước. Nhân bản để thay nội dung hoặc danh sách; giữ nguyên nội dung đã chốt cho tab đang mở.')
            db().execute('DELETE FROM group_message_sends WHERE campaign_id=?',(campaign_id,));db().execute('DELETE FROM group_campaign_targets WHERE campaign_id=?',(campaign_id,))
            db().execute('UPDATE campaigns SET name=?,message=?,message_html=?,account_id=? WHERE id=?',(name,message,html,account_id,campaign_id))
        else:
            campaign_id=db().execute("INSERT INTO campaigns(user_id,name,message,message_html,account_id,campaign_type,audience_mode,send_message,send_friend) VALUES (?,?,?,?,?,'zalo_group','list',1,0)",(g.user['id'],name,message,html,account_id)).lastrowid
        for target in by_uid.values():db().execute('INSERT INTO group_campaign_targets(campaign_id,source_row_id,group_id,name) VALUES (?,?,?,?)',(campaign_id,target['id'],target['uid'],target['name']))
        manager.set_media(campaign_id);save_limits(db,campaign_id,request.form);save_schedule(db,campaign_id,request.form,account_id)
        manager.event(campaign_id,'group_config',f'Lưu chiến dịch gửi group: {len(by_uid)} group. Chỉ gửi tự động khi đã bật lịch.')
        return campaign_id

    def form_view(campaign_id=None,duplicate=False):
        campaign=runner.own(campaign_id) if campaign_id else None
        if request.method=='POST':
            try:
                db().execute('BEGIN IMMEDIATE');saved=save_form(campaign_id if not duplicate else None);db().commit()
                flash('Đã lưu chiến dịch gửi group.','success');return redirect(url_for('group_campaign_detail',campaign_id=saved))
            except ValueError as error:db().rollback();flash(str(error),'error')
        accounts=db().execute('SELECT * FROM zalo_accounts WHERE user_id=? AND deleted_at IS NULL ORDER BY name',(g.user['id'],)).fetchall()
        targets=db().execute('SELECT source_row_id AS id,group_id AS uid,name FROM group_campaign_targets WHERE campaign_id=?',(campaign_id,)).fetchall() if campaign else []
        return render_template('group_campaign_form.html',campaign=campaign,accounts=accounts,targets=[dict(row) for row in targets],duplicating=duplicate,page='campaigns')

    @app.route('/group-campaigns/new',methods=['GET','POST'])
    @login_required
    def new_group_campaign():return form_view()

    @app.route('/group-campaigns/<int:campaign_id>/edit',methods=['GET','POST'])
    @login_required
    def edit_group_campaign(campaign_id):return form_view(campaign_id)

    @app.route('/group-campaigns/<int:campaign_id>/duplicate',methods=['GET','POST'])
    @login_required
    def duplicate_group_campaign(campaign_id):return form_view(campaign_id,duplicate=True)

    @app.get('/group-campaigns/<int:campaign_id>')
    @login_required
    def group_campaign_detail(campaign_id):
        campaign=runner.own(campaign_id,deleted=True)
        count=group_counts(db,campaign_id);pages=max(1,(count['audience']+99)//100);number=max(1,min(request.args.get('p',1,type=int),pages))
        records=db().execute('''SELECT t.*,s.id AS send_id,s.state,s.message,s.message_styles,s.message_id,s.detail,s.claimed_at,s.finished_at,
            s.media_id,a.name AS sender_name FROM group_campaign_targets t LEFT JOIN group_message_sends s ON s.target_id=t.id
            LEFT JOIN zalo_accounts a ON a.id=s.account_id WHERE t.campaign_id=? ORDER BY t.id LIMIT 100 OFFSET ?''',(campaign_id,(number-1)*100)).fetchall()
        events=db().execute('SELECT * FROM campaign_events WHERE campaign_id=? ORDER BY id DESC LIMIT 100',(campaign_id,)).fetchall()
        count=group_counts(db,campaign_id)
        return render_template('group_campaign_detail.html',campaign=campaign,records=records,events=events,counts=count,number=number,pages=pages,page='campaigns')

    @app.post('/group-campaigns/<int:campaign_id>/prepare/<int:target_id>')
    @login_required
    def prepare_group_send(campaign_id,target_id):
        campaign=runner.own(campaign_id)
        target=db().execute('SELECT * FROM group_campaign_targets WHERE id=? AND campaign_id=?',(target_id,campaign_id)).fetchone()
        if not target:abort(404)
        try:runner.prepare(campaign,target)
        except ValueError as error:flash(str(error),'error')
        return redirect(url_for('group_campaign_detail',campaign_id=campaign_id))

    @app.post('/group-campaigns/<int:campaign_id>/send/<int:send_id>')
    @login_required
    def send_group_message(campaign_id,send_id):
        if request.form.get('confirm_send')!='yes':abort(400,'Cần xác nhận gửi group.')
        try:
            sent=runner.dispatch(campaign_id,send_id)
            flash('Đã xử lý lượt gửi. Xem kết quả bên dưới.' if sent else 'Lượt này đã xử lý; không gửi trùng.','success')
        except ValueError as error:flash(str(error),'error')
        return redirect(url_for('group_campaign_detail',campaign_id=campaign_id))


def group_inline_detail(db,campaign,tab,number,connector):
    counts=group_counts(db,campaign['id'])
    cid=campaign['id'];args=(cid,)
    account_where='a.user_id=? AND (a.id=? OR EXISTS (SELECT 1 FROM group_message_sends s WHERE s.campaign_id=? AND s.account_id=a.id))'
    account_args=(campaign['user_id'],campaign['account_id'],cid)
    totals=dict(data=counts['audience'],results=db().execute('SELECT count(*) FROM group_message_sends WHERE campaign_id=? AND claimed_at IS NOT NULL',args).fetchone()[0],
        history=db().execute('SELECT count(*) FROM campaign_events WHERE campaign_id=?',args).fetchone()[0],preview=max(1,db().execute('SELECT count(*) FROM group_message_sends WHERE campaign_id=?',args).fetchone()[0]),
        accounts=db().execute('SELECT count(*) FROM zalo_accounts a WHERE '+account_where,account_args).fetchone()[0])
    total=totals.get(tab,0);pages=max(1,(total+49)//50);number=max(1,min(number,pages));offset=(number-1)*50
    detail=dict(tab=tab,counts=totals,total=total,pages=pages,number=number,offset=offset,per_page=50,rows=[],variants=[])
    if tab=='data':detail['rows']=db().execute('SELECT t.*,r.member_count FROM group_campaign_targets t JOIN data_scan_rows r ON r.id=t.source_row_id WHERE t.campaign_id=? ORDER BY t.id LIMIT 50 OFFSET ?',(cid,offset)).fetchall()
    elif tab in ('results','preview'):
        where=' AND claimed_at IS NOT NULL' if tab=='results' else ''
        detail['rows']=db().execute('SELECT * FROM group_message_sends WHERE campaign_id=?'+where+' ORDER BY id DESC LIMIT 50 OFFSET ?',(cid,offset)).fetchall()
    elif tab=='history':detail['rows']=db().execute('SELECT * FROM campaign_events WHERE campaign_id=? ORDER BY id DESC LIMIT 50 OFFSET ?',(cid,offset)).fetchall()
    elif tab=='accounts':
        rows=db().execute('SELECT a.* FROM zalo_accounts a WHERE '+account_where+' ORDER BY a.id LIMIT 50 OFFSET ?',(*account_args,offset)).fetchall()
        detail['rows']=[dict(row,connection={'state':'deleted'} if row['deleted_at'] else connector.status(campaign['user_id'],row['id'])) for row in rows]
    return detail
