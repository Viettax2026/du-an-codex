"""Owner-scoped recent-message checks, including in-flight dispatch claims."""
from datetime import datetime, timedelta, timezone

from flask import flash, redirect, render_template, request, url_for
from werkzeug.exceptions import Conflict

DUPLICATE_COLUMNS=('duplicate_enabled','duplicate_days','duplicate_all_accounts')


class DuplicateMessageBlocked(Conflict):
    def __init__(self, recent, days):
        self.recent=recent
        super().__init__(f'Không gửi lại: người nhận đã có tin gửi trong {days} ngày gần đây, ở chiến dịch “{recent["campaign_name"]}”.')


def initialize_duplicates(db):
    for table,columns in {
        'campaigns':{'duplicate_enabled':'INTEGER NOT NULL DEFAULT 0','duplicate_days':'INTEGER NOT NULL DEFAULT 10',
                     'duplicate_all_accounts':'INTEGER NOT NULL DEFAULT 0'},
        'message_sends':{'recipient_phone':"TEXT NOT NULL DEFAULT ''",'message_skip_reason':"TEXT NOT NULL DEFAULT ''"},
    }.items():
        present={row['name'] for row in db().execute(f'PRAGMA table_info({table})')}
        for name,definition in columns.items():
            if name not in present:
                db().execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
                if name=='recipient_phone':
                    db().execute("UPDATE message_sends SET recipient_phone=coalesce((SELECT phone FROM contacts WHERE contacts.id=message_sends.contact_id),'')")
    db().execute('CREATE INDEX IF NOT EXISTS sends_phone_history ON message_sends(recipient_phone,account_id,state)')
    db().execute('CREATE INDEX IF NOT EXISTS sends_uid_history ON message_sends(recipient_id,account_id,state)')
    db().commit()


def save_duplicate_check(db,campaign_id,form):
    if form.get('duplicate_present')!='yes':
        return
    old=db().execute('SELECT duplicate_days,duplicate_all_accounts FROM campaigns WHERE id=?',(campaign_id,)).fetchone()
    try:
        days=int(form.get('duplicate_days',old['duplicate_days']))
        if not 1<=days<=3650:
            raise ValueError()
    except (TypeError,ValueError):
        raise ValueError('Số ngày kiểm tra trùng lặp cần là số nguyên từ 1 đến 3650.') from None
    enabled=int(form.get('duplicate_enabled')=='yes')
    scope=int(form.get('duplicate_all_accounts')=='yes') if enabled else old['duplicate_all_accounts']
    db().execute('UPDATE campaigns SET duplicate_enabled=?,duplicate_days=?,duplicate_all_accounts=? WHERE id=?',
        (enabled,days,scope,campaign_id))


def recent_message(db,campaign,account_id,phone='',uid='',exclude_id=0,now=None):
    if not campaign['duplicate_enabled'] or not (phone or uid):
        return None
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    since=(now-timedelta(days=campaign['duplicate_days'])).strftime('%Y-%m-%d %H:%M:%S')
    stamp=now.strftime('%Y-%m-%d %H:%M:%S')
    scope='' if campaign['duplicate_all_accounts'] else ' AND s.account_id=?'
    params=[campaign['user_id'],campaign['user_id'],campaign['user_id'],exclude_id,phone,phone,phone,uid,uid,since,stamp]
    if scope:
        params.append(account_id)
    # The attempt timestamp is the actual dispatch claim, rather than preview creation time.
    return db().execute('''SELECT s.id,s.campaign_id,c.name AS campaign_name,a.name AS account_name,
        s.recipient_id,s.recipient_name,s.state,coalesce(t.created_at,s.created_at) AS sent_at
        FROM message_sends s JOIN campaigns c ON c.id=s.campaign_id
        JOIN zalo_accounts a ON a.id=s.account_id JOIN contacts p ON p.id=s.contact_id
        LEFT JOIN campaign_attempts t ON t.send_id=s.id AND t.action='send'
        WHERE c.user_id=? AND a.user_id=? AND p.user_id=? AND s.id<>?
        AND s.state IN ('sent','sending','unknown')
        AND ((?<>'' AND (s.recipient_phone=? OR (s.recipient_phone='' AND p.phone=?))) OR (?<>'' AND s.recipient_id=?))
        AND coalesce(t.created_at,s.created_at)>=? AND coalesce(t.created_at,s.created_at)<=?'''+scope+'''
        ORDER BY coalesce(t.created_at,s.created_at) DESC,s.id DESC LIMIT 1''',tuple(params)).fetchone()


def recent_for_record(db,campaign,record,now=None):
    phone=record['recipient_phone']
    if not phone:
        person=db().execute('SELECT phone FROM contacts WHERE id=? AND user_id=?',(record['contact_id'],campaign['user_id'])).fetchone()
        phone=person['phone'] if person else ''
    return recent_message(db,campaign,record['account_id'],phone,record['recipient_id'],record['id'],now)


def register_campaign_duplicates(app,db,login_required,manager):
    with app.app_context():
        initialize_duplicates(db)
    app.jinja_env.globals['recent_message_for']=lambda campaign,record:recent_for_record(db,campaign,record)

    @app.route('/campaigns/<int:campaign_id>/duplicate-check',methods=['GET','POST'])
    @login_required
    def campaign_duplicate_check(campaign_id):
        campaign=manager.owned(campaign_id)
        if request.method=='POST':
            try:
                if request.form.get('duplicate_present')!='yes':
                    raise ValueError('Biểu mẫu chưa đầy đủ. Tải lại trang để thử lại.')
                db().execute('BEGIN IMMEDIATE');manager.owned(campaign_id)
                save_duplicate_check(db,campaign_id,request.form)
                manager.event(campaign_id,'duplicate_check','Cập nhật kiểm tra lịch sử nhắn tin. Giữ nguyên các lượt đã gửi.')
                db().commit();flash('Đã lưu kiểm tra trùng lặp.','success')
                return redirect(url_for('campaign_detail',campaign_id=campaign_id))
            except ValueError as error:
                db().rollback();flash(str(error),'error')
        return render_template('campaign_duplicate_check.html',campaign=campaign,page='campaigns')
