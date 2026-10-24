"""Vietnam-time campaign windows and a serialized, restart-safe scheduler."""
import calendar
import re
import time
import signal
from threading import Event
from datetime import date, datetime, time as wall_time
from pathlib import Path
from zoneinfo import ZoneInfo

import click
from flask import flash, g, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException

from campaign_exclusions import contact_is_excluded
from rich_message import load_styles

TZ = ZoneInfo('Asia/Ho_Chi_Minh')
CONFIG_COLUMNS = ('schedule_kind','schedule_date','schedule_time','schedule_weekdays',
                  'schedule_monthday','schedule_continue','schedule_stop_enabled','schedule_stop')


def local_now():
    return datetime.now(TZ)


def initialize_schedule(db):
    fields = {'schedule_enabled':'INTEGER NOT NULL DEFAULT 0', 'schedule_kind':"TEXT NOT NULL DEFAULT 'daily'",
              'schedule_date':"TEXT NOT NULL DEFAULT ''", 'schedule_time':"TEXT NOT NULL DEFAULT '08:00'",
              'schedule_weekdays':"TEXT NOT NULL DEFAULT ''", 'schedule_monthday':'INTEGER NOT NULL DEFAULT 1',
              'schedule_continue':'INTEGER NOT NULL DEFAULT 1', 'schedule_stop_enabled':'INTEGER NOT NULL DEFAULT 0',
              'schedule_stop':"TEXT NOT NULL DEFAULT '17:00'", 'schedule_first_day':'TEXT',
              'schedule_carry':'INTEGER NOT NULL DEFAULT 0', 'schedule_error':"TEXT NOT NULL DEFAULT ''",
              'schedule_status':"TEXT NOT NULL DEFAULT 'Chưa bật lịch'", 'schedule_revision':'INTEGER NOT NULL DEFAULT 0'}
    present={row['name'] for row in db().execute('PRAGMA table_info(campaigns)')}
    for name,definition in fields.items():
        if name not in present:
            db().execute(f'ALTER TABLE campaigns ADD COLUMN {name} {definition}')
    present={row['name'] for row in db().execute('PRAGMA table_info(message_sends)')}
    if 'scheduled' not in present:
        db().execute('ALTER TABLE message_sends ADD COLUMN scheduled INTEGER NOT NULL DEFAULT 0')
    db().commit()


def schedule_values(form, account_id):
    enabled = int(form.get('schedule_enabled')=='yes')
    if not enabled:
        return {'schedule_enabled':0}
    if not account_id:
        raise ValueError('Chọn tài khoản gửi trước khi bật lịch chạy.')
    kind=form.get('schedule_kind','daily')
    if kind not in ('daily','weekly','monthly'):
        raise ValueError('Chọn lịch hằng ngày, theo tuần hoặc theo tháng.')
    try:
        anchor=date.fromisoformat(form.get('schedule_date',''))
        if not 2020 <= anchor.year <= 2100:
            raise ValueError()
        start=form.get('schedule_time','')
        stop=form.get('schedule_stop','17:00')
        if not re.fullmatch(r'\d{2}:\d{2}',start) or not re.fullmatch(r'\d{2}:\d{2}',stop):
            raise ValueError()
        start_time=wall_time.fromisoformat(start);stop_time=wall_time.fromisoformat(stop)
        monthday=int(form.get('schedule_monthday',str(anchor.day)))
        weekdays=sorted(set(int(day) for day in form.getlist('schedule_weekdays'))) if kind=='weekly' else [anchor.weekday()]
        if not 1 <= monthday <= 31 or not weekdays or any(day not in range(7) for day in weekdays):
            raise ValueError()
    except (ValueError,TypeError):
        raise ValueError('Kiểm tra ngày chạy, giờ chạy và các ngày trong tuần/tháng.') from None
    stop_enabled=int(form.get('schedule_stop_enabled')=='yes')
    if not stop_enabled and start_time >= wall_time(23,59):
        raise ValueError('Giờ chạy cần trước 23:59 khi không bật giờ dừng.')
    if stop_enabled and stop_time <= start_time:
        raise ValueError('Giờ dừng phải sau giờ chạy trong cùng ngày (UTC+7).')
    return dict(schedule_enabled=enabled,schedule_kind=kind,schedule_date=anchor.isoformat(),schedule_time=start,
                schedule_weekdays=','.join(map(str,weekdays)),schedule_monthday=monthday,
                schedule_continue=int(form.get('schedule_continue')=='yes'),schedule_stop_enabled=stop_enabled,schedule_stop=stop)


def save_schedule(db, campaign_id, form, account_id):
    if form.get('schedule_present')!='yes':
        return
    values=schedule_values(form,account_id)
    old=db().execute('SELECT * FROM campaigns WHERE id=?',(campaign_id,)).fetchone()
    unchanged=bool(old['schedule_enabled'] and values['schedule_enabled'] and all(old[name]==value for name,value in values.items()))
    db().execute('UPDATE campaigns SET '+','.join(name+'=?' for name in values)+''',
        schedule_first_day=?,schedule_carry=?,schedule_error='',schedule_revision=schedule_revision+1,schedule_status=? WHERE id=?''',
        (*values.values(),old['schedule_first_day'] if unchanged else None,old['schedule_carry'] if unchanged else 0,
         'Chờ đến giờ chạy' if values['schedule_enabled'] else 'Chưa bật lịch',campaign_id))


def active_window(campaign, now):
    now=now.astimezone(TZ)
    if not campaign['schedule_enabled'] or campaign['paused'] or campaign['deleted_at'] or campaign['schedule_error']:
        return False
    try:
        anchor=date.fromisoformat(campaign['schedule_date'])
        today=now.date()
        if today<anchor:
            return False
        regular=campaign['schedule_kind']=='daily'
        if campaign['schedule_kind']=='weekly':
            regular=today.weekday() in {int(day) for day in campaign['schedule_weekdays'].split(',')}
        if campaign['schedule_kind']=='monthly':
            regular=today.day==min(campaign['schedule_monthday'],calendar.monthrange(today.year,today.month)[1])
        carry=bool(campaign['schedule_continue'] and campaign['schedule_carry'] and campaign['schedule_first_day'] and today>=date.fromisoformat(campaign['schedule_first_day']))
        if not regular and not carry:
            return False
        start=wall_time.fromisoformat(campaign['schedule_time'])
        stop=wall_time.fromisoformat(campaign['schedule_stop']) if campaign['schedule_stop_enabled'] else wall_time(23,59)
        if now.time().replace(tzinfo=None)<start or now.time().replace(tzinfo=None)>=stop:
            return False
        return True
    except (ValueError,TypeError):
        return False


class CampaignScheduler:
    def __init__(self,app,db,manager,connector,audience):
        self.app,self.db,self.manager,self.connector,self.audience=app,db,manager,connector,audience
        self.stopping=False

    def status(self,campaign_id,text):
        self.db().execute('UPDATE campaigns SET schedule_status=? WHERE id=?',(text,campaign_id))
        self.db().commit()

    def guard(self,campaign_id,revision,now):
        def check(campaign,record=None):
            if self.stopping or campaign['schedule_revision']!=revision or not active_window(campaign,now()):
                raise ValueError('Lịch đã dừng hoặc ngoài giờ chạy.')
            if record is not None and (not record['scheduled'] or record['account_id']!=campaign['account_id']):
                raise ValueError('Bản chờ không thuộc tài khoản gửi của lịch hiện tại.')
        return check

    def pending(self,campaign):
        return self.db().execute('''SELECT * FROM message_sends WHERE campaign_id=? AND scheduled=1
            AND (state='prepared' OR friend_state='prepared' OR alias_state='prepared') ORDER BY id LIMIT 1''',(campaign['id'],)).fetchone()

    def dispatch(self,campaign,record,action,guard):
        column={'send':'state','friend':'friend_state','alias':'alias_state'}[action]
        if record[column]!='prepared':
            return
        # Check private ownership and payload before committing the dispatch claim.
        account=self.db().execute('SELECT id FROM zalo_accounts WHERE id=? AND user_id=?',(record['account_id'],g.user['id'])).fetchone()
        if not account or self.connector.status(g.user['id'],record['account_id']).get('state')!='connected':
            raise ValueError('Tài khoản chưa đăng nhập Zalo. Đăng nhập lại rồi lưu lại lịch.')
        data={'uid':record['recipient_id'],'message':record['message'] if action=='send' else record['friend_message'] if action=='friend' else record['alias']}
        if action=='send':
            styles=load_styles(record['message_styles'],record['message'])
            if styles:
                data['styles']=styles
            if record['media_id']:
                data['attachment']=self.manager.attachment(record['media_id'])
        if not self.manager.claim(campaign['id'],record['id'],action,record,guard=guard):
            return
        try:
            result=self.connector.message_action(g.user['id'],record['account_id'],action,**data)
        except Exception:
            result={'state':'unknown'}
        success={'send':'sent','friend':'friend_requested','alias':'renamed'}[action]
        state=result.get('state') if result.get('state') in (success,'failed','unknown') else 'unknown'
        if action=='send':
            self.db().execute('UPDATE message_sends SET state=?,message_id=? WHERE id=?',(state,str(result.get('message_id',''))[:100] if state=='sent' else '',record['id']))
        else:
            self.db().execute(f'UPDATE message_sends SET {column}=? WHERE id=?',(state,record['id']))
        self.manager.result(campaign['id'],action,record['id'],state)
        self.db().commit()
        if state=='unknown':
            raise ValueError('Kết quả hành động chưa xác định. Kiểm tra hội thoại Zalo rồi lưu lại lịch để tiếp tục; không tự gửi lại lần đó.')

    def tick_campaign(self,campaign_id,now):
        campaign=self.manager.owned(campaign_id)
        if not active_window(campaign,now()):
            return
        revision=campaign['schedule_revision'];guard=self.guard(campaign_id,revision,now)
        if not self.app.config['ZALO_QR_ENABLED']:
            raise ValueError('Máy chủ chưa bật kết nối Zalo.')
        account=self.db().execute('SELECT * FROM zalo_accounts WHERE id=? AND user_id=?',(campaign['account_id'],g.user['id'])).fetchone()
        if not account or self.connector.status(g.user['id'],account['id']).get('state')!='connected':
            raise ValueError('Tài khoản chưa đăng nhập Zalo. Đăng nhập lại rồi lưu lại lịch.')
        unfinished=self.db().execute("SELECT 1 FROM message_sends WHERE campaign_id=? AND scheduled=1 AND (state='sending' OR friend_state='sending' OR alias_state='sending') LIMIT 1",(campaign_id,)).fetchone()
        if unfinished:
            raise ValueError('Có lần gửi bị gián đoạn. Kiểm tra hội thoại Zalo và lịch sử trước khi tiếp tục.')
        record=self.pending(campaign)
        if record is not None:
            # Remove pending actions for recipients who opted out/left the group, without dispatching.
            allowed={person['id'] for person in self.audience(campaign)}
            if record['contact_id'] not in allowed or contact_is_excluded(self.db,g.user['id'],campaign_id,record['contact_id'],record['recipient_id']):
                self.db().execute("UPDATE message_sends SET state=CASE WHEN state='prepared' THEN 'not_requested' ELSE state END,friend_state=CASE WHEN friend_state='prepared' THEN 'not_requested' ELSE friend_state END,alias_state=CASE WHEN alias_state='prepared' THEN 'not_requested' ELSE alias_state END WHERE id=?",(record['id'],))
                self.manager.event(campaign_id,'schedule_skip',f'Bỏ qua bản gửi #{record["id"]}: khách hàng không còn thuộc danh sách được gửi.')
                self.db().commit();return
            for action,column in (('send','state'),('friend','friend_state'),('alias','alias_state')):
                if record[column]=='prepared':
                    self.dispatch(campaign,record,action,guard)
                    self.status(campaign_id,'Đang chạy theo lịch')
                    return  # At most one external action per campaign per tick.
        existing={r['contact_id'] for r in self.db().execute('SELECT contact_id FROM message_sends WHERE campaign_id=?',(campaign_id,))}
        person=next((person for person in self.audience(campaign) if person['id'] not in existing),None)
        if person is None:
            self.db().execute("UPDATE campaigns SET schedule_carry=0,schedule_status='Đã xử lý hết data hiện tại' WHERE id=?",(campaign_id,));self.db().commit();return
        # The lookup is read-only. Revalidate window/settings/consent afterwards in a write transaction.
        try:
            resolved=self.connector.message_action(g.user['id'],account['id'],'resolve',phone=person['phone'])
        except Exception:
            resolved={}
        if resolved.get('state')!='resolved' or not re.fullmatch(r'\d{1,30}',str(resolved.get('uid',''))):
            raise ValueError(f'Không tìm được Zalo của {person["phone"]}. Kiểm tra data rồi lưu lại lịch.')
        self.db().execute('BEGIN IMMEDIATE')
        try:
            campaign=self.manager.owned(campaign_id);guard(campaign)
            person=next((p for p in self.audience(campaign) if p['id']==person['id']),None)
            if person is None:
                self.db().rollback();return
            if self.db().execute('SELECT 1 FROM message_sends WHERE campaign_id=? AND contact_id=?',(campaign_id,person['id'])).fetchone():
                self.db().rollback();return
            if contact_is_excluded(self.db,g.user['id'],campaign_id,person['id'],resolved['uid']):
                self.db().execute('''INSERT INTO message_sends(campaign_id,contact_id,account_id,recipient_id,recipient_name,message,state,friend_state,alias_state,scheduled)
                    VALUES (?,?,?,?,?,'','not_requested','not_requested','not_requested',1)''',(campaign_id,person['id'],account['id'],resolved['uid'],str(resolved.get('name',''))[:100]))
                self.db().execute('UPDATE campaigns SET schedule_first_day=coalesce(schedule_first_day,?),schedule_carry=1 WHERE id=?',(now().astimezone(TZ).date().isoformat(),campaign_id))
                self.manager.event(campaign_id,'schedule_skip',f'Bỏ qua khách hàng #{person["id"]}: Zalo thuộc danh sách loại trừ.')
                self.db().commit();return
            self.manager.store_preview(campaign,person,account,resolved,scheduled=True)
            self.db().execute("UPDATE campaigns SET schedule_first_day=coalesce(schedule_first_day,?),schedule_carry=1,schedule_status='Đang chạy theo lịch' WHERE id=?",(now().astimezone(TZ).date().isoformat(),campaign_id))
            self.db().commit()
        except BaseException:
            self.db().rollback();raise

    def heartbeat(self):
        Path(self.app.config['DATABASE']).with_suffix('.scheduler.heartbeat').write_text(local_now().isoformat())

    def tick(self,now=local_now):
        self.heartbeat()
        rows=self.db().execute("SELECT id,user_id,schedule_revision FROM campaigns WHERE schedule_enabled=1 AND paused=0 AND deleted_at IS NULL AND schedule_error='' ORDER BY id").fetchall()
        for row in rows:
            if self.stopping:
                break
            self.heartbeat()
            g.user=self.db().execute('SELECT id,name,username FROM users WHERE id=?',(row['user_id'],)).fetchone()
            try:
                self.tick_campaign(row['id'],now)
            except HTTPException as error:
                self.db().rollback()
                # Quotas/spacing are temporary waits; no new attempts have been claimed.
                if error.code==409:
                    self.status(row['id'],'Đang chờ giới hạn gửi / khoảng nghỉ')
                else:
                    self.block(row['id'],error.description)
            except ValueError as error:
                self.db().rollback()
                current=self.manager.owned(row['id'])
                if str(error)!='Lịch đã dừng hoặc ngoài giờ chạy.' and current['schedule_enabled'] and not current['paused'] and not current['deleted_at'] and current['schedule_revision']==row['schedule_revision']:
                    self.block(row['id'],str(error))
            finally:
                self.db().rollback()

    def block(self,campaign_id,message):
        self.db().execute("UPDATE campaigns SET schedule_error=?,schedule_status='Cần kiểm tra' WHERE id=?",(message,campaign_id))
        self.manager.event(campaign_id,'schedule_error',message)
        self.db().commit()


def register_campaign_schedule(app,db,login_required,manager,connector,audience):
    with app.app_context():
        initialize_schedule(db)
    scheduler=CampaignScheduler(app,db,manager,connector,audience)
    app.extensions['campaign_scheduler']=scheduler
    app.jinja_env.globals['schedule_today']=lambda: local_now().date().isoformat()
    def scheduler_online():
        try:
            return time.time()-Path(app.config['DATABASE']).with_suffix('.scheduler.heartbeat').stat().st_mtime<180
        except OSError:
            return False
    app.jinja_env.globals['scheduler_online']=scheduler_online

    @app.route('/campaigns/<int:campaign_id>/schedule',methods=['GET','POST'])
    @login_required
    def campaign_schedule(campaign_id):
        campaign=manager.owned(campaign_id)
        if request.method=='POST':
            try:
                db().execute('BEGIN IMMEDIATE');campaign=manager.owned(campaign_id)
                if request.form.get('schedule_present')!='yes':
                    raise ValueError('Biểu mẫu lịch chưa đầy đủ. Tải lại trang để thử lại.')
                account_id=request.form.get('account_id') or None
                if account_id and not db().execute('SELECT id FROM zalo_accounts WHERE id=? AND user_id=?',(account_id,g.user['id'])).fetchone():
                    raise ValueError('Tài khoản gửi không hợp lệ.')
                save_schedule(db,campaign_id,request.form,account_id)
                db().execute('UPDATE campaigns SET account_id=? WHERE id=?',(account_id,campaign_id))
                manager.event(campaign_id,'schedule','Cập nhật lịch tự động (UTC+7).')
                db().commit();flash('Đã lưu lịch chạy. Chỉ xử lý những khách hàng chưa gửi trong chiến dịch.','success')
                return redirect(url_for('campaign_detail',campaign_id=campaign_id))
            except ValueError as error:
                db().rollback();flash(str(error),'error')
        return render_template('campaign_schedule.html',campaign=campaign,page='campaigns',accounts=db().execute('SELECT id,name FROM zalo_accounts WHERE user_id=? ORDER BY name',(g.user['id'],)).fetchall())

    @app.cli.command('run-scheduler')
    @click.option('--once',is_flag=True,help='Check one cycle and exit.')
    def run_scheduler(once):
        """Run the automatic schedule worker; one process per database."""
        try:
            import fcntl
        except ImportError:
            raise click.ClickException('Chạy bộ lịch trên VPS Linux.') from None
        path=Path(app.config['DATABASE']).with_suffix('.scheduler.lock')
        with path.open('a') as lock:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                raise click.ClickException('Bộ chạy lịch đang hoạt động ở tiến trình khác.') from None
            stopping=Event()
            def stop(signum,frame):
                scheduler.stopping=True
                stopping.set()
            previous=signal.signal(signal.SIGTERM,stop) if not once else None
            try:
                while not stopping.is_set():
                    try:
                        scheduler.tick()
                    except Exception:
                        db().rollback();app.logger.exception('Schedule worker cycle failed')
                        if once:
                            raise
                    if once:
                        return
                    stopping.wait(1)
            finally:
                if previous is not None:
                    signal.signal(signal.SIGTERM,previous)
                Path(app.config['DATABASE']).with_suffix('.scheduler.heartbeat').unlink(missing_ok=True)
