"""Reusable owner-scoped exclusions, checked again at the dispatch boundary."""
import re
import sqlite3

from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for


def exclusion_predicate(person='p', campaign='c', resolved_uid="''"):
    # Alias/expression arguments are fixed application SQL, never user input.
    return f'''(EXISTS (SELECT 1 FROM campaign_exclusion_rules x JOIN exclusion_rule_groups r ON r.id=x.rule_group_id
        WHERE x.campaign_id={campaign}.id AND r.user_id={person}.user_id AND (
          (r.sent=1 AND EXISTS (SELECT 1 FROM message_sends es JOIN campaigns ec ON ec.id=es.campaign_id
            WHERE ec.user_id={person}.user_id AND es.contact_id={person}.id AND es.campaign_id!={campaign}.id AND es.state='sent')) OR
          (r.friend_requested=1 AND EXISTS (SELECT 1 FROM message_sends es JOIN campaigns ec ON ec.id=es.campaign_id
            WHERE ec.user_id={person}.user_id AND es.contact_id={person}.id AND es.campaign_id!={campaign}.id AND es.friend_state='friend_requested')) OR
          (r.renamed=1 AND EXISTS (SELECT 1 FROM message_sends es JOIN campaigns ec ON ec.id=es.campaign_id
            WHERE ec.user_id={person}.user_id AND es.contact_id={person}.id AND es.campaign_id!={campaign}.id AND es.alias_state='renamed')) OR
          EXISTS (SELECT 1 FROM exclusion_rule_contacts erc WHERE erc.rule_group_id=r.id AND erc.contact_id={person}.id) OR
          (r.data_group_id IS NOT NULL AND EXISTS (SELECT 1 FROM data_groups ed JOIN contact_group_memberships em
            ON em.user_id=ed.user_id AND em.group_name=ed.name WHERE ed.id=r.data_group_id AND ed.user_id={person}.user_id AND em.contact_id={person}.id))
        )) OR EXISTS (SELECT 1 FROM campaign_exclusion_lists x JOIN exclusion_lists l ON l.id=x.list_id
          WHERE x.campaign_id={campaign}.id AND l.user_id={person}.user_id AND (
            EXISTS (SELECT 1 FROM exclusion_list_entries e WHERE e.list_id=l.id AND e.kind='phone' AND e.value={person}.phone) OR
            EXISTS (SELECT 1 FROM exclusion_list_entries e WHERE e.list_id=l.id AND e.kind='uid' AND e.value IN (
              {person}.zalo_id,{resolved_uid},coalesce((SELECT es.recipient_id FROM message_sends es
                WHERE es.campaign_id={campaign}.id AND es.contact_id={person}.id),'')))
          )))'''


def contact_is_excluded(db, user_id, campaign_id, contact_id, resolved_uid=''):
    return bool(db().execute('''SELECT 1 FROM contacts p JOIN campaigns c ON c.user_id=p.user_id
        WHERE p.user_id=? AND p.id=? AND c.id=? AND '''+exclusion_predicate(resolved_uid='?'),
        (user_id,contact_id,campaign_id,str(resolved_uid))).fetchone())


def save_exclusion_settings(db, user_id, campaign_id):
    if request.form.get('exclusions_present')!='yes':
        return
    raw=request.form.get('exclusion_rule_group_id','')
    ids=list(dict.fromkeys(request.form.getlist('exclusion_list_ids')))
    if raw and (not raw.isdigit() or not db().execute('SELECT 1 FROM exclusion_rule_groups WHERE id=? AND user_id=?',(raw,user_id)).fetchone()):
        raise ValueError('Nhóm điều kiện loại trừ không thuộc tài khoản của bạn.')
    if len(ids)>20 or any(not value.isdigit() for value in ids):
        raise ValueError('Chọn tối đa 20 danh sách loại trừ hợp lệ.')
    if ids:
        marks=','.join('?' for _ in ids)
        count=db().execute('SELECT count(*) FROM exclusion_lists WHERE user_id=? AND id IN ('+marks+')',(user_id,*ids)).fetchone()[0]
        if count!=len(ids):
            raise ValueError('Danh sách loại trừ không thuộc tài khoản của bạn.')
    db().execute('DELETE FROM campaign_exclusion_rules WHERE campaign_id=?',(campaign_id,))
    db().execute('DELETE FROM campaign_exclusion_lists WHERE campaign_id=?',(campaign_id,))
    if raw:
        db().execute('INSERT INTO campaign_exclusion_rules(campaign_id,rule_group_id) VALUES (?,?)',(campaign_id,raw))
    db().executemany('INSERT INTO campaign_exclusion_lists(campaign_id,list_id) VALUES (?,?)',((campaign_id,value) for value in ids))


def register_campaign_exclusions(app, db, login_required, manager, parse_phones):
    with app.app_context():
        db().executescript('''CREATE TABLE IF NOT EXISTS exclusion_rule_groups (
            id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),name TEXT NOT NULL,
            sent INTEGER NOT NULL DEFAULT 0,friend_requested INTEGER NOT NULL DEFAULT 0,renamed INTEGER NOT NULL DEFAULT 0,
            data_group_id INTEGER REFERENCES data_groups(id),UNIQUE(user_id,name));
            CREATE TABLE IF NOT EXISTS exclusion_rule_contacts (
            rule_group_id INTEGER NOT NULL REFERENCES exclusion_rule_groups(id) ON DELETE CASCADE,
            contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            PRIMARY KEY(rule_group_id,contact_id));
            CREATE TABLE IF NOT EXISTS exclusion_lists (
            id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),name TEXT NOT NULL,UNIQUE(user_id,name));
            CREATE TABLE IF NOT EXISTS exclusion_list_entries (
            list_id INTEGER NOT NULL REFERENCES exclusion_lists(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK(kind IN ('phone','uid')),value TEXT NOT NULL,PRIMARY KEY(list_id,kind,value));
            CREATE TABLE IF NOT EXISTS campaign_exclusion_rules (
            campaign_id INTEGER NOT NULL REFERENCES campaigns(id),rule_group_id INTEGER NOT NULL REFERENCES exclusion_rule_groups(id),
            PRIMARY KEY(campaign_id,rule_group_id));
            CREATE TABLE IF NOT EXISTS campaign_exclusion_lists (
            campaign_id INTEGER NOT NULL REFERENCES campaigns(id),list_id INTEGER NOT NULL REFERENCES exclusion_lists(id),
            PRIMARY KEY(campaign_id,list_id));
            CREATE INDEX IF NOT EXISTS message_sends_contact_campaign ON message_sends(contact_id,campaign_id);''')

    @app.context_processor
    def helpers():
        def catalog(campaign_id=None):
            rule=db().execute('SELECT rule_group_id FROM campaign_exclusion_rules WHERE campaign_id=?',(campaign_id,)).fetchone() if campaign_id else None
            selected={row['list_id'] for row in db().execute('SELECT list_id FROM campaign_exclusion_lists WHERE campaign_id=?',(campaign_id,))} if campaign_id else set()
            if request.method=='POST' and request.form.get('exclusions_present')=='yes':
                rule_id=request.form.get('exclusion_rule_group_id','')
                selected=set(request.form.getlist('exclusion_list_ids'))
            else:
                rule_id=str(rule['rule_group_id']) if rule else ''
                selected={str(value) for value in selected}
            lists=[]
            for row in db().execute('SELECT id,name FROM exclusion_lists WHERE user_id=? ORDER BY name,id',(g.user['id'],)):
                entries=db().execute('SELECT kind,value FROM exclusion_list_entries WHERE list_id=? ORDER BY kind,value',(row['id'],)).fetchall()
                lists.append(dict(row,total=len(entries),phones='\n'.join(e['value'] for e in entries if e['kind']=='phone'),
                                  uids='\n'.join(e['value'] for e in entries if e['kind']=='uid')))
            return dict(rules=db().execute('SELECT id,name FROM exclusion_rule_groups WHERE user_id=? ORDER BY name,id',(g.user['id'],)).fetchall(),
                        lists=lists,selected_rule=rule_id,selected_lists=selected,
                        groups=db().execute('SELECT id,name FROM data_groups WHERE user_id=? AND deleted_at IS NULL ORDER BY name',(g.user['id'],)).fetchall())
        return dict(exclusion_catalog=catalog)

    @app.post('/campaign-exclusions/rules')
    @login_required
    def create_exclusion_rule():
        name=request.form.get('name','').strip()
        flags=[int(request.form.get(key)=='yes') for key in ('sent','friend_requested','renamed')]
        group=request.form.get('data_group_id','') or None
        try:
            if not name or len(name)>80 or not (any(flags) or group):
                raise ValueError('Nhập tên (tối đa 80 ký tự) và chọn ít nhất một điều kiện.')
            db().execute('BEGIN IMMEDIATE')
            if group and (not group.isdigit() or not db().execute('SELECT 1 FROM data_groups WHERE id=? AND user_id=? AND deleted_at IS NULL',(group,g.user['id'])).fetchone()):
                raise ValueError('Nhóm data không thuộc tài khoản của bạn.')
            row=db().execute('INSERT INTO exclusion_rule_groups(user_id,name,sent,friend_requested,renamed,data_group_id) VALUES (?,?,?,?,?,?)',
                             (g.user['id'],name,*flags,group))
            db().commit()
            return jsonify(id=row.lastrowid,name=name),201
        except (ValueError,sqlite3.IntegrityError) as error:
            db().rollback()
            return jsonify(error=str(error) if isinstance(error,ValueError) else 'Tên nhóm điều kiện đã tồn tại.'),400

    @app.post('/campaign-exclusions/lists')
    @login_required
    def save_exclusion_list():
        name=request.form.get('name','').strip();list_id=request.form.get('list_id','')
        try:
            if not name or len(name)>80:
                raise ValueError('Tên danh sách cần từ 1 đến 80 ký tự.')
            phones=parse_phones(request.form.get('phones',''))
            raw=request.form.get('uids','').strip()
            if len(raw)>30000:
                raise ValueError('Danh sách Zalo ID quá dài.')
            uids=list(dict.fromkeys(value.strip() for value in re.split(r'[\n,;]+',raw) if value.strip()))
            if len(uids)>500 or any(not re.fullmatch(r'[0-9]{1,30}',value) for value in uids):
                raise ValueError('Tối đa 500 Zalo ID; mỗi ID từ 1 đến 30 chữ số.')
            if not phones and not uids:
                raise ValueError('Nhập ít nhất một số điện thoại hoặc Zalo ID.')
            db().execute('BEGIN IMMEDIATE')
            if list_id:
                if not list_id.isdigit() or not db().execute('SELECT 1 FROM exclusion_lists WHERE id=? AND user_id=?',(list_id,g.user['id'])).fetchone():
                    abort(404)
                db().execute('UPDATE exclusion_lists SET name=? WHERE id=? AND user_id=?',(name,list_id,g.user['id']))
                db().execute('DELETE FROM exclusion_list_entries WHERE list_id=?',(list_id,))
            else:
                list_id=db().execute('INSERT INTO exclusion_lists(user_id,name) VALUES (?,?)',(g.user['id'],name)).lastrowid
            entries=[('phone',value) for value in phones]+[('uid',value) for value in uids]
            db().executemany('INSERT INTO exclusion_list_entries(list_id,kind,value) VALUES (?,?,?)',((list_id,*item) for item in entries))
            db().commit()
            return jsonify(id=int(list_id),name=name,total=len(entries),phones='\n'.join(phones),uids='\n'.join(uids)),200
        except (ValueError,sqlite3.IntegrityError) as error:
            db().rollback()
            return jsonify(error=str(error) if isinstance(error,ValueError) else 'Tên danh sách đã tồn tại.'),400

    @app.route('/campaigns/<int:campaign_id>/exclusions',methods=['GET','POST'])
    @login_required
    def campaign_exclusions(campaign_id):
        if request.method=='POST':
            db().execute('BEGIN IMMEDIATE')
        campaign=manager.owned(campaign_id)
        if request.method=='POST':
            try:
                save_exclusion_settings(db,g.user['id'],campaign_id)
                manager.event(campaign_id,'exclusions','Cập nhật nhóm điều kiện và danh sách loại trừ. Giữ nguyên nhật ký đã có.')
                db().commit()
                flash('Đã lưu loại trừ; áp dụng cho các hành động xác nhận tiếp theo.','success')
                return redirect(url_for('campaign_detail',campaign_id=campaign_id))
            except ValueError as error:
                db().rollback();flash(str(error),'error')
        return render_template('campaign_exclusions.html',campaign=campaign,page='campaigns')
