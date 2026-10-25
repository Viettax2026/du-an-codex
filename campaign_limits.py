"""Action budgets shared by manual dispatch and the campaign scheduler."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import jsonify, request, url_for
from werkzeug.exceptions import Conflict

TZ = ZoneInfo('Asia/Ho_Chi_Minh')
LIMIT_COLUMNS = ('message_limit','friend_limit','alias_limit','interval_seconds',
                 'message_hour_limit','friend_hour_limit','message_window_minutes','friend_window_minutes',
                 'limits_day_mode','limits_continue')
ACTIONS = {'send':('message_limit','message_hour_limit','message_window_minutes','send_message'),
           'friend':('friend_limit','friend_hour_limit','friend_window_minutes','send_friend'),
           'alias':('alias_limit',None,None,'rename_enabled')}
DEFAULTS = dict(message_limit=100,friend_limit=25,alias_limit=0,interval_seconds=120,
                message_hour_limit=5,friend_hour_limit=5,message_window_minutes=65,friend_window_minutes=65,
                limits_day_mode='calendar',limits_continue=1)


class ActionLimitReached(Conflict):
    def __init__(self, description, kind='quota'):
        super().__init__(description)
        self.kind=kind


def initialize_limits(db):
    columns={'message_hour_limit':'INTEGER NOT NULL DEFAULT 0','friend_hour_limit':'INTEGER NOT NULL DEFAULT 0',
             'message_window_minutes':'INTEGER NOT NULL DEFAULT 65','friend_window_minutes':'INTEGER NOT NULL DEFAULT 65',
             'limits_day_mode':"TEXT NOT NULL DEFAULT 'rolling'",'limits_continue':'INTEGER NOT NULL DEFAULT 1'}
    present={r['name'] for r in db().execute('PRAGMA table_info(campaigns)')}
    for name,definition in columns.items():
        if name not in present:
            db().execute(f'ALTER TABLE campaigns ADD COLUMN {name} {definition}')
    db().commit()


def save_limits(db,campaign_id,form,legacy=False):
    if form.get('limits_present')!='yes' and not legacy:
        return
    old=db().execute('SELECT * FROM campaigns WHERE id=?',(campaign_id,)).fetchone()
    values={}
    full=form.get('limits_present')=='yes'
    for name in LIMIT_COLUMNS:
        if name in ('limits_day_mode','limits_continue'):
            continue
        raw=form.get(name,old[name])
        try:
            # Reject decimals and booleans rather than silently rounding.
            value=int(raw)
            low,high=(1,1440) if name.endswith('_minutes') else (0,86400)
            if not low<=value<=high:
                raise ValueError()
        except (ValueError,TypeError):
            raise ValueError('Giới hạn và khoảng nghỉ cần số nguyên từ 0 đến 86400; khung giờ từ 1 đến 1440 phút.') from None
        values[name]=value
    mode=form.get('limits_day_mode',old['limits_day_mode'])
    if mode not in ('calendar','rolling'):
        raise ValueError('Chọn giới hạn theo ngày Việt Nam hoặc 24 giờ gần nhất.')
    values['limits_day_mode']=mode
    values['limits_continue']=int(form.get('limits_continue')=='yes') if full else old['limits_continue']
    db().execute('UPDATE campaigns SET '+','.join(name+'=?' for name in values)+' WHERE id=?',(*values.values(),campaign_id))


def usage(db,campaign,now=None):
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    day_start=(now.astimezone(TZ).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
               if campaign['limits_day_mode']=='calendar' else now-timedelta(hours=24))
    stamp=lambda value:value.strftime('%Y-%m-%d %H:%M:%S')
    result={}
    for action,(day_field,hour_field,window_field,_) in ACTIONS.items():
        minutes=campaign[window_field] if window_field else 60
        hour_start=now-timedelta(minutes=minutes)
        row=db().execute('''SELECT coalesce(sum(created_at>=?),0),coalesce(sum(created_at>=?),0)
            FROM campaign_attempts WHERE campaign_id=? AND action=? AND created_at>=? AND created_at<=?''',
            (stamp(day_start),stamp(hour_start),campaign['id'],action,stamp(min(day_start,hour_start)),stamp(now))).fetchone()
        day_cap=campaign[day_field];hour_cap=campaign[hour_field] if hour_field else 0
        result[action]=dict(day_used=int(row[0]),hour_used=int(row[1]),day_limit=day_cap,hour_limit=hour_cap,
            minutes=minutes,blocked=bool(day_cap and row[0]>=day_cap or hour_cap and row[1]>=hour_cap))
    recent=db().execute('SELECT max(created_at) FROM campaign_attempts WHERE campaign_id=? AND created_at<=?',(campaign['id'],stamp(now))).fetchone()[0]
    elapsed=(now-datetime.fromisoformat(recent).replace(tzinfo=timezone.utc)).total_seconds() if recent else 0
    result['interval_wait']=max(0,int(campaign['interval_seconds']-elapsed)) if recent else 0
    return result


def available_actions(campaign,budgets,check_interval=True):
    selected={action for action,(_,_,_,enabled) in ACTIONS.items() if campaign[enabled]}
    blocked={action for action in selected if budgets[action]['blocked']}
    if (check_interval and budgets['interval_wait']) or blocked and not campaign['limits_continue']:
        return set()
    return selected-blocked


def enforce_limits(db,campaign,action,now=None,check_interval=True):
    budgets=usage(db,campaign,now)
    selected={a for a,(_,_,_,enabled) in ACTIONS.items() if campaign[enabled]}
    if budgets[action]['blocked'] or not campaign['limits_continue'] and any(budgets[a]['blocked'] for a in selected):
        label='trong ngày (đến 24h, UTC+7)' if campaign['limits_day_mode']=='calendar' else 'trong 24 giờ gần nhất'
        raise ActionLimitReached(f'Đã đạt giới hạn hành động {label} hoặc khung giờ. Chờ hạn mức còn lại hoặc cập nhật giới hạn.')
    if check_interval and budgets['interval_wait']:
        raise ActionLimitReached('Chưa đủ khoảng cách giữa hai hành động. Vui lòng chờ rồi xác nhận lại.','spacing')


def register_campaign_limits(app,db,login_required,manager):
    with app.app_context():
        initialize_limits(db)

    def catalog(campaign=None,duplicating=False):
        settings=dict(campaign) if campaign is not None else dict(DEFAULTS)
        if campaign is not None and not duplicating:
            budgets=usage(db,campaign)
            endpoint=url_for('campaign_limits_usage',campaign_id=campaign['id'])
        else:
            budgets={a:dict(day_used=0,hour_used=0) for a in ACTIONS}
            endpoint=''
        return dict(settings=settings,usage=budgets,url=endpoint)
    app.jinja_env.globals['limits_catalog']=catalog

    @app.get('/campaigns/<int:campaign_id>/limits/usage')
    @login_required
    def campaign_limits_usage(campaign_id):
        current=dict(manager.owned(campaign_id))
        mode=request.args.get('mode',current['limits_day_mode'])
        if mode not in ('calendar','rolling'):
            return jsonify(error='Loại giới hạn ngày không hợp lệ.'),400
        current['limits_day_mode']=mode
        try:
            for name in ('message_window_minutes','friend_window_minutes'):
                value=int(request.args.get(name,current[name]))
                if not 1<=value<=1440:
                    raise ValueError()
                current[name]=value
        except (ValueError,TypeError):
            return jsonify(error='Khung giờ cần từ 1 đến 1440 phút.'),400
        return jsonify(usage=usage(db,current))
