"""Versioned payloads for unclaimed actions on a partially processed recipient."""
import json
import re

from personalization import personalize
from rich_message import render_message,utf16

ACTIONS={'send':('state','send_message'),'friend':('friend_state','send_friend'),'alias':('alias_state','rename_enabled')}
FIELDS=('account_id','recipient_id','recipient_name','message','message_styles','media_id','friend_message','alias')


def initialize_pending(db):
    db().executescript('''CREATE TABLE IF NOT EXISTS campaign_action_payloads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,send_id INTEGER NOT NULL REFERENCES message_sends(id),action TEXT NOT NULL,
        payload TEXT NOT NULL,media_id INTEGER REFERENCES campaign_media(id),needs_lookup INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE UNIQUE INDEX IF NOT EXISTS action_payload_current ON campaign_action_payloads(send_id,action) WHERE active=1;
        CREATE TABLE IF NOT EXISTS campaign_pending_repairs (event_id INTEGER PRIMARY KEY REFERENCES campaign_events(id));''')
    for table,name,declaration in [('campaign_attempts','payload_id','INTEGER REFERENCES campaign_action_payloads(id)'),
            ('message_sends','continue_after_edit','INTEGER NOT NULL DEFAULT 0'),
            ('campaign_action_payloads','account_id','INTEGER REFERENCES zalo_accounts(id)')]:
        if name not in {r['name'] for r in db().execute(f'PRAGMA table_info({table})')}:
            db().execute(f'ALTER TABLE {table} ADD COLUMN {name} {declaration}')


class PendingActions:
    def __init__(self,manager):self.manager=manager;self.db=manager.db

    def payload(self,send_id,action):
        return self.db().execute('''SELECT p.* FROM campaign_action_payloads p WHERE p.send_id=? AND p.action=?
            AND (EXISTS (SELECT 1 FROM campaign_attempts a WHERE a.send_id=p.send_id AND a.action=p.action AND a.payload_id=p.id)
                OR (p.active=1 AND NOT EXISTS (SELECT 1 FROM campaign_attempts a WHERE a.send_id=p.send_id AND a.action=p.action)))
            ORDER BY p.id DESC LIMIT 1''',(send_id,action)).fetchone()

    def record(self,row,action):
        result=dict(row);result.update(action_payload_id=0,needs_lookup=0)
        payload=self.payload(row['id'],action)
        if payload:
            result.update(json.loads(payload['payload']));result.update(action_payload_id=payload['id'],needs_lookup=payload['needs_lookup'])
            account=self.db().execute('SELECT name FROM zalo_accounts WHERE id=?',(result['account_id'],)).fetchone()
            result['account_name']=account['name'] if account else 'Tài khoản đã xóa'
        return result

    def decorate(self,row):
        result=dict(row);details={}
        for action in ACTIONS:
            part=self.record(row,action);details[action]=part
            if part['action_payload_id']:
                fields=('message','message_styles','media_id') if action=='send' else ('friend_message',) if action=='friend' else ('alias',)
                for field in fields:result[field]=part[field]
                if action=='send':
                    for field in ('account_name','recipient_id','recipient_name'):result[field]=part[field]
        result['action_details']=details
        return result

    def build(self,campaign,row,action,identity=None):
        person=self.db().execute('SELECT * FROM contacts WHERE id=? AND user_id=?',(row['contact_id'],campaign['user_id'])).fetchone()
        if not person:raise ValueError('Không tìm thấy khách hàng để cập nhật bước chờ.')
        identity=identity or dict(uid=row['recipient_id'],name=row['recipient_name'],original_name=row['recipient_name'])
        payload={key:row[key] for key in FIELDS};payload.update(account_id=campaign['account_id'] or row['account_id'],recipient_id=identity['uid'],recipient_name=identity.get('name',''))
        if action=='send':
            text,styles=render_message(campaign['message'],campaign['message_html'],person,identity,variant_index=campaign['next_message_variant'])
            payload.update(message=text,message_styles=json.dumps(styles),media_id=campaign['media_id'],variant_index=campaign['next_message_variant'])
        elif action=='friend':
            text=personalize(campaign['friend_message'],person,identity)
            if utf16(text)>150:raise ValueError('Lời mời sau cá nhân hóa vượt 150 ký tự.')
            payload['friend_message']=text;payload['media_id']=None
        else:
            text=personalize(campaign['rename_template'],person,identity).strip()
            if not text or utf16(text)>100:raise ValueError('Tên gợi nhớ sau cá nhân hóa cần từ 1 đến 100 ký tự.')
            payload['alias']=text;payload['media_id']=None
        return payload

    def stage(self,campaign,row):
        changes=[]
        for action,(column,enabled) in ACTIONS.items():
            if row[column]!='prepared' or self.db().execute('SELECT 1 FROM campaign_attempts WHERE send_id=? AND action=?',(row['id'],action)).fetchone():continue
            self.db().execute('UPDATE campaign_action_payloads SET active=0 WHERE send_id=? AND action=? AND active=1',(row['id'],action))
            if not campaign[enabled]:
                self.db().execute(f"UPDATE message_sends SET {column}='not_requested' WHERE id=?",(row['id'],))
                changes.append(action+' (đã tắt trong cấu hình)');continue
            payload=self.build(campaign,row,action)
            if not self.db().execute('SELECT 1 FROM zalo_accounts WHERE id=? AND user_id=? AND deleted_at IS NULL',(payload['account_id'],campaign['user_id'])).fetchone():raise ValueError('Chọn tài khoản hợp lệ cho bước chưa thực hiện.')
            needs_lookup=int(payload['account_id']!=row['account_id'])
            self.db().execute('INSERT INTO campaign_action_payloads(send_id,action,payload,media_id,needs_lookup,account_id) VALUES (?,?,?,?,?,?)',
                (row['id'],action,json.dumps(payload,ensure_ascii=False),payload['media_id'],needs_lookup,payload['account_id']))
            if action=='send':self.db().execute('UPDATE campaigns SET next_message_variant=next_message_variant+1 WHERE id=?',(campaign['id'],))
            changes.append(action)
        if changes:
            self.db().execute('UPDATE message_sends SET continue_after_edit=1,schedule_completed_at=NULL,schedule_turn_finished=0 WHERE id=?',(row['id'],))
            self.manager.event(campaign['id'],'edit_pending_actions',f'Bản gửi #{row["id"]}: giữ các bước đã có lượt thực hiện; cập nhật các bước chưa thực hiện: '+', '.join(changes)+'. Không gửi lại bước đã chạy.')
        return changes

    def resolve(self,campaign,row,action,connector,guard=None):
        current=self.record(row,action)
        if not current['needs_lookup']:return current
        if connector.status(campaign['user_id'],current['account_id']).get('state')!='connected':raise ValueError('Tài khoản của bước chờ chưa đăng nhập Zalo. Đăng nhập lại rồi tiếp tục.')
        try:identity=connector.message_action(campaign['user_id'],current['account_id'],'resolve',phone=row['recipient_phone'])
        except Exception:identity={}
        if not isinstance(identity,dict) or identity.get('state')!='resolved' or not re.fullmatch(r'\d{1,30}',str(identity.get('uid',''))):raise ValueError('Chưa tìm được người nhận bằng tài khoản mới. Kiểm tra phiên Zalo và số điện thoại rồi thử lại; chưa gửi hành động.')
        self.db().execute('BEGIN IMMEDIATE')
        try:
            latest=self.manager.owned(campaign['id']);fresh=self.db().execute('SELECT * FROM message_sends WHERE id=?',(row['id'],)).fetchone()
            self.manager.require_active(latest)
            if latest['edit_revision']!=campaign['edit_revision'] or not fresh or self.record(fresh,action)['action_payload_id']!=current['action_payload_id']:
                raise ValueError('Lịch đã dừng hoặc ngoài giờ chạy.')
            if guard:guard(latest)
            if fresh[ACTIONS[action][0]]!='prepared' or self.db().execute('SELECT 1 FROM campaign_attempts WHERE send_id=? AND action=?',(row['id'],action)).fetchone():raise ValueError('Bước này đã bắt đầu; không tìm hoặc gửi lại.')
            template=dict(latest)
            if action=='send':template['next_message_variant']=current.get('variant_index',latest['next_message_variant'])
            payload=self.build(template,fresh,action,identity)
            self.db().execute('UPDATE campaign_action_payloads SET active=0 WHERE id=?',(current['action_payload_id'],))
            self.db().execute('INSERT INTO campaign_action_payloads(send_id,action,payload,media_id,needs_lookup,account_id) VALUES (?,?,?,?,0,?)',
                (row['id'],action,json.dumps(payload,ensure_ascii=False),payload['media_id'],payload['account_id']))
            self.manager.event(campaign['id'],'pending_identity',f'Đã xác nhận người nhận của bước {action}, bản gửi #{row["id"]}, bằng tài khoản mới. Chưa gửi hành động.')
            self.db().commit();return self.record(fresh,action)
        except BaseException:self.db().rollback();raise


def repair_canceled_steps(app,db,manager):
    """Repair only the exact cancellation events emitted by the previous version."""
    with app.app_context():
        db().execute('BEGIN IMMEDIATE')
        events=db().execute("SELECT e.* FROM campaign_events e LEFT JOIN campaign_pending_repairs r ON r.event_id=e.id WHERE e.kind='edit_started_recipient' AND r.event_id IS NULL ORDER BY e.id").fetchall()
        for event in events:
            match=re.fullmatch(r'Giữ kết quả bản gửi #(\d+) đã bắt đầu; bỏ các bước chưa thực hiện sau khi sửa chiến dịch\. Không chạy lại data này\.',event['detail'])
            if not match:continue
            campaign=db().execute('SELECT * FROM campaigns WHERE id=?',(event['campaign_id'],)).fetchone()
            row=db().execute('SELECT * FROM message_sends WHERE id=? AND campaign_id=?',(int(match[1]),event['campaign_id'])).fetchone()
            db().execute('SAVEPOINT pending_repair')
            try:
                restored=[]
                if campaign and row and not campaign['deleted_at'] and not row['schedule_skip_reason']:
                    for action,(column,enabled) in ACTIONS.items():
                        if action=='send' and row['message_skip_reason']:continue
                        field={'send':'message','friend':'friend_message','alias':'alias'}[action]
                        if row[column]=='not_requested' and row[field] and campaign[enabled] and not db().execute('SELECT 1 FROM campaign_attempts WHERE send_id=? AND action=?',(row['id'],action)).fetchone():
                            db().execute(f"UPDATE message_sends SET {column}='prepared' WHERE id=?",(row['id'],));restored.append(action)
                    if restored:
                        fresh=db().execute('SELECT * FROM message_sends WHERE id=?',(row['id'],)).fetchone()
                        manager.pending.stage(campaign,fresh)
                        db().execute("UPDATE campaigns SET schedule_revision=schedule_revision+1,schedule_carry=CASE WHEN schedule_enabled=1 THEN 1 ELSE schedule_carry END,schedule_status='Đã khôi phục bước chờ bị bỏ nhầm; tiếp tục theo lịch và hạn mức' WHERE id=?",(campaign['id'],))
                        manager.event(campaign['id'],'pending_repair',f'Khôi phục bước chưa có lượt thực hiện của bản gửi #{row["id"]}: '+', '.join(restored)+'. Giữ kết quả và hạn mức của các bước đã chạy. Chưa gửi hành động trong lúc cập nhật.')
                db().execute('INSERT INTO campaign_pending_repairs(event_id) VALUES (?)',(event['id'],))
                db().execute('RELEASE pending_repair')
            except ValueError:
                db().execute('ROLLBACK TO pending_repair');db().execute('RELEASE pending_repair')
                # Leave unmarked for a later restart after the owner fixes missing data/account.
                manager.event(event['campaign_id'],'pending_repair_review',f'Bản gửi #{match[1]} có bước chờ bị bỏ ở phiên bản trước; cần sửa thông tin/tài khoản rồi khởi động lại để khôi phục an toàn. Chưa gửi lại.')
        db().commit()
