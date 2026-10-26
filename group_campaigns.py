"""Immutable group destinations, explicit sends and scheduled group messages."""
import json
from datetime import datetime, timedelta, timezone

from flask import abort, flash, g, redirect, render_template, request, url_for

from campaign_errors import error_description
from campaign_limits import enforce_limits, save_limits, usage
from campaign_schedule import active_window, local_now, manual_schedule_block, save_schedule
from rich_message import read_message, render_message, load_styles
from personalization import TOKEN
from group_data import initialize_group_data,register_group_data,owned_group_rows,collection_rows
from campaign_edits import edit_remaining,next_send_id


def initialize_group_campaigns(db):
    columns={row['name'] for row in db().execute('PRAGMA table_info(campaigns)')}
    if 'campaign_type' not in columns:
        db().execute("ALTER TABLE campaigns ADD COLUMN campaign_type TEXT NOT NULL DEFAULT 'phone'")
    for field,declaration in {'group_send_mode':"TEXT NOT NULL DEFAULT 'normal'",'group_tag_names':"TEXT NOT NULL DEFAULT '[]'",
            'group_data_mode':"TEXT NOT NULL DEFAULT 'direct'",'group_data_id':'INTEGER','group_is_draft':'INTEGER NOT NULL DEFAULT 0'}.items():
        if field not in columns:db().execute(f'ALTER TABLE campaigns ADD COLUMN {field} {declaration}')
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
    for table,fields in {'group_campaign_targets':{'active':'INTEGER NOT NULL DEFAULT 1'},
        'group_message_sends':{'send_mode':"TEXT NOT NULL DEFAULT 'normal'",'tag_names':"TEXT NOT NULL DEFAULT '[]'",'batch_id':'INTEGER'}}.items():
        present={row['name'] for row in db().execute(f'PRAGMA table_info({table})')}
        for name,declaration in fields.items():
            if name not in present:db().execute(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')
    db().execute('''CREATE TABLE IF NOT EXISTS group_message_batches (
        id INTEGER PRIMARY KEY,campaign_id INTEGER NOT NULL REFERENCES campaigns(id),account_id INTEGER NOT NULL REFERENCES zalo_accounts(id),
        message TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'sending',message_ids TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,finished_at TEXT)''')
    if 'preview_ids' not in {row['name'] for row in db().execute('PRAGMA table_info(group_message_batches)')}:
        db().execute("ALTER TABLE group_message_batches ADD COLUMN preview_ids TEXT NOT NULL DEFAULT '[]'")
    initialize_group_data(db)
    db().commit()


def group_counts(db,campaign_id):
    count=db().execute('''SELECT count(*) FROM group_campaign_targets t WHERE campaign_id=? AND
        (active=1 OR EXISTS (SELECT 1 FROM group_message_sends s WHERE s.target_id=t.id))''',(campaign_id,)).fetchone()[0]
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

    def sync_targets(self,campaign):
        if campaign['group_data_mode']!='group' or not campaign['group_data_id']:return
        rows=collection_rows(self.db,campaign['user_id'],campaign['group_data_id'],campaign['account_id'])
        self.db().execute('UPDATE group_campaign_targets SET active=0 WHERE campaign_id=?',(campaign['id'],))
        for row in rows:
            self.db().execute('''INSERT INTO group_campaign_targets(campaign_id,source_row_id,group_id,name,active) VALUES (?,?,?,?,1)
                ON CONFLICT(campaign_id,group_id) DO UPDATE SET active=1''',(campaign['id'],row['id'],row['uid'],row['name']))
        self.db().execute('''UPDATE group_message_sends SET state='skipped',detail='Group đã bị loại khỏi nhóm data; bỏ qua.',finished_at=CURRENT_TIMESTAMP
            WHERE campaign_id=? AND state='prepared' AND target_id IN (SELECT id FROM group_campaign_targets WHERE campaign_id=? AND active=0)''',(campaign['id'],campaign['id']))

    def apply_tags(self,record):
        for tag in json.loads(record['tag_names']):
            self.db().execute('INSERT OR IGNORE INTO zalo_group_tags(user_id,account_id,group_id,tag) VALUES (?,?,?,?)',
                (g.user['id'],record['account_id'],record['group_id'],tag))

    def prepare(self,campaign,target,shared=None):
        self.db().execute('BEGIN IMMEDIATE')
        try:
            current=self.own(campaign['id']);self.manager.require_active(current)
            if current['group_is_draft']:raise ValueError('Lưu chiến dịch trước khi tạo bản xem trước hoặc gửi.')
            self.sync_targets(current)
            target=self.db().execute('SELECT * FROM group_campaign_targets WHERE id=? AND campaign_id=?',(target['id'],current['id'])).fetchone()
            if not target:abort(404)
            if not target['active']:raise ValueError('Group không còn trong nguồn data của chiến dịch.')
            self.manager.require_account(current['account_id'])
            existing=self.db().execute('SELECT * FROM group_message_sends WHERE campaign_id=? AND target_id=?',(current['id'],target['id'])).fetchone()
            if existing:self.db().commit();return existing
            message,styles=shared if shared is not None else render_message(current['message'],current['message_html'],dict(name=target['name'],phone='',zalo_id=target['group_id']),
                dict(name=target['name'],uid=target['group_id']),variant_index=current['next_message_variant'])
            mode='share' if current['group_send_mode']=='share' and not styles and not current['media_id'] else 'normal'
            cur=self.db().execute('''INSERT INTO group_message_sends(id,campaign_id,target_id,account_id,group_id,group_name,message,message_styles,media_id,send_mode,tag_names)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)''',(next_send_id(self.db,'group_message_sends'),current['id'],target['id'],current['account_id'],target['group_id'],target['name'],message,json.dumps(styles),current['media_id'],mode,current['group_tag_names']))
            if shared is None:self.db().execute('UPDATE campaigns SET next_message_variant=next_message_variant+1 WHERE id=?',(current['id'],))
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
            if campaign['group_is_draft']:raise ValueError('Chiến dịch đang là bản nháp.')
            self.sync_targets(campaign)
            record=self.db().execute('SELECT * FROM group_message_sends WHERE id=? AND campaign_id=?',(send_id,campaign_id)).fetchone()
            if not record:self.db().commit();return False
            self.manager.require_account(record['account_id'])
            if record['account_id']!=campaign['account_id']:raise ValueError('Bản xem trước thuộc tài khoản cũ. Không gửi bằng tài khoản khác.')
            if scheduled and (self.app.extensions['campaign_scheduler'].stopping or campaign['schedule_revision']!=current['schedule_revision'] or not active_window(campaign,now())):
                raise ValueError('Lịch đã dừng hoặc ngoài giờ chạy.')
            blocked=manual_schedule_block(campaign,now())
            if blocked:raise ValueError(blocked)
            if record['state']!='prepared':self.db().commit();return False
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
            if record['send_mode']=='share':
                result=next(iter(self.connector.forward_group_messages(g.user['id'],record['account_id'],[record['group_id']],record['message'])),{})
            else:
                result=self.connector.message_action(g.user['id'],record['account_id'],'send',uid=record['group_id'],message=record['message'],thread_type=1,
                    **({'styles':styles} if styles else {}),**({'attachment':attachment} if attachment else {}))
        except Exception:result={'state':'unknown'}
        result=result if isinstance(result,dict) else {}
        state=result.get('state') if result.get('state') in ('sent','failed','unknown') else 'unknown'
        detail='Zalo đã tiếp nhận tin nhắn gửi group.' if state=='sent' else error_description(result) or ('Chưa xác định kết quả. Kiểm tra hội thoại group; không tự gửi lại.' if state=='unknown' else 'Gửi group không thành công. Bỏ qua lượt này và tiếp tục group khác.')
        self.db().execute('BEGIN IMMEDIATE')
        self.db().execute('UPDATE group_message_sends SET state=?,message_id=?,detail=?,finished_at=CURRENT_TIMESTAMP WHERE id=?',
            (state,str(result.get('message_id',''))[:100] if state=='sent' else '',detail,send_id))
        if state=='sent':self.apply_tags(record)
        latest=self.own(campaign_id,deleted=True)
        until=(now().astimezone(timezone.utc)+timedelta(seconds=latest['interval_seconds'])).replace(tzinfo=None,microsecond=0).isoformat(' ')
        self.db().execute('UPDATE campaigns SET schedule_wait_until=?,schedule_wait_message=? WHERE id=?',(until,'Nghỉ theo cài đặt trước khi xử lý group tiếp theo.',campaign_id))
        self.manager.event(campaign_id,'group_result',f'Group {record["group_name"]} ({record["group_id"]}): {detail}')
        if latest['interval_seconds']:self.manager.event(campaign_id,'group_rest',f'Nghỉ {latest["interval_seconds"]} giây trước group tiếp theo.')
        self.db().commit();return True

    def prepare_shared_preview(self,campaign):
        self.db().execute('BEGIN IMMEDIATE');self.sync_targets(campaign);self.db().commit()
        targets=self.db().execute('''SELECT t.* FROM group_campaign_targets t LEFT JOIN group_message_sends s ON s.target_id=t.id
            WHERE t.campaign_id=? AND t.active=1 AND (s.id IS NULL OR s.state='prepared') ORDER BY t.id LIMIT 50''',(campaign['id'],)).fetchall()
        if not targets:raise ValueError('Không còn group chưa xử lý để tạo lô chia sẻ.')
        first=self.prepare(campaign,targets[0])
        if first['send_mode']!='share':raise ValueError('Lô chia sẻ chỉ dùng tin chữ không có định dạng hoặc media. Nội dung hiện tại được gửi riêng từng group.')
        records=[first]
        for target in targets[1:]:
            item=self.prepare(campaign,target,shared=(first['message'],[]))
            if item['send_mode']=='share' and item['message']==first['message']:records.append(item)
        batch_id=self.db().execute("INSERT INTO group_message_batches(campaign_id,account_id,message,state,preview_ids) VALUES (?,?,?,'prepared',?)",
            (campaign['id'],campaign['account_id'],first['message'],json.dumps([item['id'] for item in records]))).lastrowid
        self.db().commit();return batch_id

    def dispatch_shared_batch(self,campaign,first,now,scheduled=True,preview_id=None):
        records=[first]
        if preview_id:
            preview=self.db().execute('SELECT * FROM group_message_batches WHERE id=? AND campaign_id=?',(preview_id,campaign['id'])).fetchone()
            if not preview:abort(404)
            ids=json.loads(preview['preview_ids'])
            records=self.db().execute('SELECT * FROM group_message_sends WHERE campaign_id=? AND id IN ('+','.join('?' for _ in ids)+') ORDER BY id',(campaign['id'],*ids)).fetchall() if ids else []
        else:
            targets=self.db().execute('''SELECT t.* FROM group_campaign_targets t LEFT JOIN group_message_sends s ON s.target_id=t.id
                WHERE t.campaign_id=? AND t.active=1 AND t.id!=? AND (s.id IS NULL OR s.state='prepared') ORDER BY t.id LIMIT 49''',
                (campaign['id'],first['target_id'])).fetchall()
            for target in targets:
                item=self.prepare(campaign,target,shared=(first['message'],[]))
                if item['send_mode']=='share' and item['message']==first['message']:records.append(item)
        self.sender(campaign['account_id'])
        self.db().execute('BEGIN IMMEDIATE')
        try:
            current=self.own(campaign['id']);self.manager.require_active(current)
            if current['group_is_draft']:raise ValueError('Chiến dịch đang là bản nháp.')
            if scheduled and (current['schedule_revision']!=campaign['schedule_revision'] or not active_window(current,now()) or self.app.extensions['campaign_scheduler'].stopping):
                raise ValueError('Lịch đã dừng hoặc ngoài giờ chạy.')
            blocked=manual_schedule_block(current,now())
            if blocked:raise ValueError(blocked)
            if preview_id:
                preview=self.db().execute('SELECT * FROM group_message_batches WHERE id=? AND campaign_id=?',(preview_id,current['id'])).fetchone()
                if preview['state']!='prepared':self.db().rollback();return False
                if preview['account_id']!=current['account_id'] or preview['message']!=first['message']:raise ValueError('Bản xem trước thuộc cấu hình cũ.')
            self.manager.require_account(current['account_id']);self.sync_targets(current)
            stamp=now().astimezone(timezone.utc).replace(tzinfo=None,microsecond=0).isoformat(' ')
            if current['schedule_wait_until'] and current['schedule_wait_until']>stamp:raise ValueError('Đang nghỉ theo cài đặt trước lượt chia sẻ tiếp theo.')
            budget=usage(self.db,current,now())['send'];capacity=50
            for kind in ('day','hour'):
                if budget[kind+'_limit']:capacity=min(capacity,max(0,budget[kind+'_limit']-budget[kind+'_used']))
            enforce_limits(self.db,current,'send',now=now())
            ready=[]
            for item in records:
                fresh=self.db().execute('''SELECT s.* FROM group_message_sends s JOIN group_campaign_targets t ON t.id=s.target_id
                    WHERE s.id=? AND s.campaign_id=? AND s.state='prepared' AND t.active=1''',(item['id'],current['id'])).fetchone()
                if fresh and fresh['account_id']==current['account_id'] and fresh['send_mode']=='share' and fresh['message']==first['message'] and not fresh['media_id'] and fresh['message_styles']=='[]':ready.append(fresh)
            ready=ready[:capacity]
            if not ready:
                if preview_id:self.db().execute("UPDATE group_message_batches SET state='confirmed',finished_at=CURRENT_TIMESTAMP WHERE id=?",(preview_id,))
                self.db().commit();return False
            batch_id=self.db().execute('INSERT INTO group_message_batches(campaign_id,account_id,message) VALUES (?,?,?)',
                (current['id'],current['account_id'],first['message'])).lastrowid
            if preview_id:self.db().execute("UPDATE group_message_batches SET state='confirmed',finished_at=CURRENT_TIMESTAMP WHERE id=?",(preview_id,))
            for index,item in enumerate(ready):
                enforce_limits(self.db,current,'send',now=now(),check_interval=index==0)
                self.db().execute("UPDATE group_message_sends SET state='sending',claimed_at=?,batch_id=? WHERE id=?",(stamp,batch_id,item['id']))
            self.db().execute('UPDATE campaigns SET schedule_first_day=coalesce(schedule_first_day,?),schedule_carry=1 WHERE id=?',(now().date().isoformat(),current['id']))
            self.manager.event(current['id'],'group_batch_send',f'Bắt đầu lô chia sẻ #{batch_id}: {len(ready)} group. Nguồn: '+('Theo lịch tự động.' if scheduled else 'Xác nhận thủ công.'))
            self.db().commit()
        except BaseException:self.db().rollback();raise
        try:result=self.connector.forward_group_messages(g.user['id'],current['account_id'],[item['group_id'] for item in ready],first['message'])
        except Exception:result=[]
        outcomes={item.get('uid'):item for item in result if isinstance(item,dict)} if isinstance(result,list) else {}
        self.db().execute('BEGIN IMMEDIATE');states=[];acks=set()
        for item in ready:
            outcome=outcomes.get(item['group_id'],{});state=outcome.get('state') if outcome.get('state') in ('sent','failed','unknown') else 'unknown'
            if state=='sent' and not outcome.get('message_id'):state='unknown'
            detail='Zalo đã tiếp nhận lô chia sẻ gồm group này.' if state=='sent' else 'Tài khoản không còn tham gia group; bỏ qua.' if outcome.get('reason')=='group_not_joined' else 'Lô chia sẻ bị từ chối; bỏ qua.' if state=='failed' else 'Lô chia sẻ chưa xác định đầy đủ kết quả. Kiểm tra hội thoại; không tự gửi lại.'
            self.db().execute('UPDATE group_message_sends SET state=?,message_id=?,detail=?,finished_at=CURRENT_TIMESTAMP WHERE id=?',
                (state,f'batch:{batch_id}' if state=='sent' else '',detail,item['id']))
            if state=='sent':self.apply_tags(item);acks.add(outcome['message_id'])
            states.append(state)
            self.manager.event(current['id'],'group_result',f'Group {item["group_name"]} ({item["group_id"]}), lô #{batch_id}: {detail}')
        state=states[0] if len(set(states))==1 else 'partial'
        self.db().execute('UPDATE group_message_batches SET state=?,message_ids=?,finished_at=CURRENT_TIMESTAMP WHERE id=?',(state,';'.join(sorted(acks)),batch_id))
        latest=self.own(current['id'],deleted=True)
        until=(now().astimezone(timezone.utc)+timedelta(seconds=latest['interval_seconds'])).replace(tzinfo=None,microsecond=0).isoformat(' ')
        self.db().execute('UPDATE campaigns SET schedule_wait_until=?,schedule_wait_message=? WHERE id=?',(until,'Nghỉ trước lô group tiếp theo.',current['id']))
        self.manager.event(current['id'],'group_rest',f'Lô #{batch_id} kết thúc; nghỉ {latest["interval_seconds"]} giây trước lượt tiếp theo.')
        self.db().commit();return True

    def tick(self,campaign_id,now):
        campaign=self.own(campaign_id)
        if campaign['group_is_draft'] or not active_window(campaign,now()):return
        self.db().execute('BEGIN IMMEDIATE');self.sync_targets(campaign);self.db().commit()
        stamp=now().astimezone(timezone.utc).replace(tzinfo=None,microsecond=0).isoformat(' ')
        if campaign['schedule_wait_until'] and campaign['schedule_wait_until']>stamp:return
        # A claim has a 90-second grace period, longer than the connector timeout.
        active=self.db().execute("SELECT * FROM group_message_sends WHERE campaign_id=? AND state='sending' ORDER BY id LIMIT 1",(campaign_id,)).fetchone()
        if active:
            elapsed=(now().astimezone(timezone.utc)-datetime.fromisoformat(active['claimed_at']).replace(tzinfo=timezone.utc)).total_seconds()
            if elapsed<90:return
            if active['batch_id']:
                self.db().execute("UPDATE group_message_sends SET state='unknown',detail='Lô chia sẻ bị gián đoạn. Không tự gửi lại.',finished_at=CURRENT_TIMESTAMP WHERE batch_id=? AND state='sending'",(active['batch_id'],))
                self.db().execute("UPDATE group_message_batches SET state='unknown',finished_at=CURRENT_TIMESTAMP WHERE id=?",(active['batch_id'],))
            else:self.db().execute("UPDATE group_message_sends SET state='unknown',detail='Lượt gửi bị gián đoạn. Không tự gửi lại.',finished_at=CURRENT_TIMESTAMP WHERE id=?",(active['id'],))
            self.manager.event(campaign_id,'group_recovery',f'Lượt group #{active["id"]} bị gián đoạn; bỏ qua, không tự gửi lại.')
            until=(now().astimezone(timezone.utc)+timedelta(seconds=campaign['interval_seconds'])).replace(tzinfo=None,microsecond=0).isoformat(' ')
            self.db().execute('UPDATE campaigns SET schedule_wait_until=?,schedule_wait_message=? WHERE id=?',(until,'Nghỉ trước group tiếp theo.',campaign_id));self.db().commit();return
        target=self.db().execute('''SELECT t.* FROM group_campaign_targets t LEFT JOIN group_message_sends s ON s.target_id=t.id
            WHERE t.campaign_id=? AND t.active=1 AND (s.id IS NULL OR s.state='prepared') ORDER BY t.id LIMIT 1''',(campaign_id,)).fetchone()
        if not target:
            self.db().execute("UPDATE campaigns SET schedule_status='Đã xử lý hết danh sách group',schedule_carry=0 WHERE id=?",(campaign_id,));self.db().commit();return
        self.sender(campaign['account_id'])
        record=self.prepare(campaign,target)
        if record['send_mode']=='share':self.dispatch_shared_batch(campaign,record,now)
        else:self.dispatch(campaign_id,record['id'],now=now,scheduled=True)
        self.db().execute("UPDATE campaigns SET schedule_first_day=coalesce(schedule_first_day,?),schedule_carry=1,schedule_status='Đang xử lý group' WHERE id=?",(now().date().isoformat(),campaign_id));self.db().commit()


def register_group_campaigns(app,db,login_required,manager,connector):
    with app.app_context():initialize_group_campaigns(db)
    runner=GroupCampaignRunner(app,db,manager,connector);app.extensions['group_campaign_runner']=runner
    register_group_data(app,db,login_required,manager)

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

    def save_form(campaign_id=None,template=None):
        old=runner.own(campaign_id) if campaign_id else template
        draft=request.form.get('save_draft')=='yes'
        name=request.form.get('name','').strip();message,html=read_message(request.form)
        if draft and not name:name='Chiến dịch group chưa đặt tên'
        if not name or len(name)>120 or not message and not draft:raise ValueError('Nhập tên chiến dịch và nội dung gửi group.')
        account_id=request.form.get('account_id') or None
        if (account_id or not draft) and not db().execute('SELECT 1 FROM zalo_accounts WHERE id=? AND user_id=? AND deleted_at IS NULL',(account_id,g.user['id'])).fetchone():raise ValueError('Chọn tài khoản Zalo hợp lệ.')
        mode=request.form.get('group_send_mode',old['group_send_mode'] if old else 'normal')
        if request.form.get('group_options_present')=='yes':mode='share' if request.form.get('group_share')=='yes' else 'normal'
        if mode not in ('normal','share'):raise ValueError('Cách gửi group không hợp lệ.')
        if mode=='share' and any(not match.group().startswith('#{TODAY(') for match in TOKEN.finditer(message)):
            raise ValueError('Gửi chia sẻ không áp dụng cá nhân hóa. Xóa biến cá nhân hóa hoặc bỏ chọn gửi chia sẻ.')
        tags=json.loads(old['group_tag_names']) if old else []
        if request.form.get('group_options_present')=='yes':
            tags=list(dict.fromkeys(value.strip() for value in request.form.get('group_tags','').split(',') if value.strip())) if request.form.get('group_tags_enabled')=='yes' else []
            if len(tags)>10 or any(len(value)>80 for value in tags):raise ValueError('Chọn tối đa 10 tag, mỗi tag tối đa 80 ký tự.')
            if request.form.get('group_tags_enabled')=='yes' and not tags:raise ValueError('Nhập tag nội bộ để gắn sau khi gửi thành công.')
        data_mode=request.form.get('group_data_mode',old['group_data_mode'] if old else 'direct')
        if data_mode not in ('direct','group'):raise ValueError('Chọn cách thêm data hợp lệ.')
        data_group_id=request.form.get('group_data_id',old['group_data_id'] if old else None) or None
        if data_mode=='group':
            if not data_group_id and not draft:raise ValueError('Chọn nhóm data chứa group Zalo để chạy.')
            targets=collection_rows(db,g.user['id'],data_group_id,account_id) if data_group_id else []
            targets=owned_group_rows(db,g.user['id'],account_id,json.dumps([row['id'] for row in targets]),allow_empty=draft)
        else:
            data_group_id=None
            targets=owned_group_rows(db,g.user['id'],account_id,request.form.get('group_scan_row_ids','[]'),allow_empty=draft)
        by_uid={row['uid']:row for row in targets}
        # Validate all personalized variants before retaining a new campaign.
        if message:
            for target in by_uid.values():render_message(message,html,dict(name=target['name'],phone='',zalo_id=target['uid']),dict(name=target['name'],uid=target['uid']),variant_index=0)
        if campaign_id:
            runner.own(campaign_id)
            db().execute('UPDATE group_campaign_targets SET active=0 WHERE campaign_id=?',(campaign_id,))
            db().execute('UPDATE campaigns SET name=?,message=?,message_html=?,account_id=? WHERE id=?',(name,message,html,account_id,campaign_id))
        else:
            campaign_id=db().execute("INSERT INTO campaigns(user_id,name,message,message_html,account_id,campaign_type,audience_mode,send_message,send_friend) VALUES (?,?,?,?,?,'zalo_group','list',1,0)",(g.user['id'],name,message,html,account_id)).lastrowid
        for target in by_uid.values():db().execute('''INSERT INTO group_campaign_targets(campaign_id,source_row_id,group_id,name) VALUES (?,?,?,?)
            ON CONFLICT(campaign_id,group_id) DO UPDATE SET active=1,source_row_id=excluded.source_row_id,name=excluded.name''',(campaign_id,target['id'],target['uid'],target['name']))
        db().execute('''UPDATE campaigns SET group_send_mode=?,group_tag_names=?,group_data_mode=?,group_data_id=?,group_is_draft=?,
            paused=CASE WHEN ?=1 THEN 1 WHEN group_is_draft=1 THEN 0 ELSE paused END WHERE id=?''',
            (mode,json.dumps(tags,ensure_ascii=False),data_mode,data_group_id,int(draft),int(draft),campaign_id))
        manager.set_media(campaign_id);save_limits(db,campaign_id,request.form)
        if draft:db().execute("UPDATE campaigns SET schedule_enabled=0,schedule_error='',schedule_status='Bản nháp' WHERE id=?",(campaign_id,))
        else:save_schedule(db,campaign_id,request.form,account_id)
        if old and old['id']==campaign_id:edit_remaining(db,manager,old)
        manager.event(campaign_id,'group_config',f'Lưu {"nháp" if draft else "chiến dịch"} gửi group: {len(by_uid)} group · {"Chia sẻ theo lô tối đa 50 group" if mode=="share" else "Gửi từng group"}.')
        return campaign_id

    def form_view(campaign_id=None,duplicate=False):
        campaign=runner.own(campaign_id) if campaign_id else None
        if request.method=='POST':
            try:
                db().execute('BEGIN IMMEDIATE');saved=save_form(campaign_id if not duplicate else None,campaign if duplicate else None);db().commit()
                flash('Đã lưu chiến dịch gửi group.','success');return redirect(url_for('group_campaign_detail',campaign_id=saved))
            except ValueError as error:db().rollback();flash(str(error),'error')
        accounts=db().execute('SELECT * FROM zalo_accounts WHERE user_id=? AND deleted_at IS NULL ORDER BY name',(g.user['id'],)).fetchall()
        targets=db().execute('SELECT source_row_id AS id,group_id AS uid,name FROM group_campaign_targets WHERE campaign_id=? AND active=1',(campaign_id,)).fetchall() if campaign else []
        if request.method=='POST':
            try:targets=owned_group_rows(db,g.user['id'],request.form.get('account_id'),request.form.get('group_scan_row_ids'),allow_empty=True)
            except ValueError:pass
        tags=', '.join(json.loads(campaign['group_tag_names'])) if campaign else ''
        return render_template('group_campaign_form.html',campaign=campaign,accounts=accounts,targets=[dict(row) for row in targets],group_tags=tags,duplicating=duplicate,page='campaigns')

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
            LEFT JOIN zalo_accounts a ON a.id=s.account_id WHERE t.campaign_id=? AND (t.active=1 OR s.id IS NOT NULL) ORDER BY t.id LIMIT 100 OFFSET ?''',(campaign_id,(number-1)*100)).fetchall()
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

    @app.post('/group-campaigns/<int:campaign_id>/refresh-source')
    @login_required
    def refresh_group_campaign_source(campaign_id):
        campaign=runner.own(campaign_id)
        db().execute('BEGIN IMMEDIATE');runner.sync_targets(campaign);db().commit()
        flash('Đã cập nhật danh sách từ nhóm data. Chưa gửi tin.','success')
        return redirect(url_for('group_campaign_detail',campaign_id=campaign_id))

    @app.post('/group-campaigns/<int:campaign_id>/prepare-share')
    @login_required
    def prepare_group_share(campaign_id):
        campaign=runner.own(campaign_id)
        try:
            batch_id=runner.prepare_shared_preview(campaign)
            return redirect(url_for('group_share_preview',campaign_id=campaign_id,batch_id=batch_id))
        except ValueError as error:flash(str(error),'error')
        return redirect(url_for('group_campaign_detail',campaign_id=campaign_id))

    @app.route('/group-campaigns/<int:campaign_id>/share-preview/<int:batch_id>',methods=['GET','POST'])
    @login_required
    def group_share_preview(campaign_id,batch_id):
        campaign=runner.own(campaign_id)
        preview=db().execute('SELECT * FROM group_message_batches WHERE id=? AND campaign_id=?',(batch_id,campaign_id)).fetchone()
        if not preview or not preview['preview_ids'] or preview['preview_ids']=='[]':abort(404)
        if preview['state']=='superseded':
            flash('Bản xem trước đã hết hiệu lực sau khi sửa chiến dịch. Tạo bản mới trước khi xác nhận.','error')
            return redirect(url_for('group_campaign_detail',campaign_id=campaign_id))
        ids=json.loads(preview['preview_ids'])
        records=db().execute('SELECT * FROM group_message_sends WHERE campaign_id=? AND id IN ('+','.join('?' for _ in ids)+') ORDER BY id',(campaign_id,*ids)).fetchall()
        if request.method=='POST':
            if request.form.get('confirm_send')!='yes':abort(400,'Cần xác nhận nội dung và danh sách group.')
            try:
                sent=runner.dispatch_shared_batch(campaign,records[0],local_now,scheduled=False,preview_id=batch_id)
                flash('Đã xử lý lô chia sẻ. Xem nhật ký từng group.' if sent else 'Lô đã xử lý hoặc không còn group chờ; không gửi trùng.','success')
            except ValueError as error:flash(str(error),'error')
            return redirect(url_for('group_campaign_detail',campaign_id=campaign_id))
        return render_template('group_share_preview.html',campaign=campaign,preview=preview,records=records,page='campaigns')

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
    if tab=='data':detail['rows']=db().execute('''SELECT t.*,r.member_count FROM group_campaign_targets t JOIN data_scan_rows r ON r.id=t.source_row_id
        WHERE t.campaign_id=? AND (t.active=1 OR EXISTS (SELECT 1 FROM group_message_sends s WHERE s.target_id=t.id)) ORDER BY t.id LIMIT 50 OFFSET ?''',(cid,offset)).fetchall()
    elif tab in ('results','preview'):
        where=' AND claimed_at IS NOT NULL' if tab=='results' else ''
        detail['rows']=db().execute('SELECT * FROM group_message_sends WHERE campaign_id=?'+where+' ORDER BY id DESC LIMIT 50 OFFSET ?',(cid,offset)).fetchall()
    elif tab=='history':detail['rows']=db().execute('SELECT * FROM campaign_events WHERE campaign_id=? ORDER BY id DESC LIMIT 50 OFFSET ?',(cid,offset)).fetchall()
    elif tab=='accounts':
        rows=db().execute('SELECT a.* FROM zalo_accounts a WHERE '+account_where+' ORDER BY a.id LIMIT 50 OFFSET ?',(*account_args,offset)).fetchall()
        detail['rows']=[dict(row,connection={'state':'deleted'} if row['deleted_at'] else connector.status(campaign['user_id'],row['id'])) for row in rows]
    return detail
