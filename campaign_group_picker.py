"""Owner-scoped group picker and bounded snapshots of existing contacts."""
import json

from flask import g, jsonify, request

CAMPAIGN_CONTACT_LIMIT = 10000


def read_snapshot_contacts(db, user_id, raw):
    if not raw:
        return []
    if len(raw)>250000:
        raise ValueError('Danh sách từ nhóm quá lớn.')
    try:
        ids=json.loads(raw)
    except (ValueError,TypeError) as error:
        raise ValueError('Danh sách data từ nhóm không hợp lệ. Chọn lại nhóm.') from error
    if not isinstance(ids,list) or len(ids)>CAMPAIGN_CONTACT_LIMIT or any(type(value) is not int or not 1<=value<=9223372036854775807 for value in ids):
        raise ValueError('Danh sách từ nhóm tối đa 10.000 khách hàng hợp lệ.')
    ids=list(dict.fromkeys(ids))
    if not ids:
        return []
    rows=db().execute('SELECT * FROM contacts WHERE user_id=? AND deleted_at IS NULL AND id IN ('+','.join('?' for _ in ids)+') ORDER BY id', (user_id,*ids)).fetchall()
    if len(rows)!=len(ids):
        raise ValueError('Một số data không thuộc tài khoản hoặc đã bị xóa. Chọn lại nhóm.')
    return rows


def register_campaign_group_picker(app, db, login_required):
    @app.get('/campaigns/group-options')
    @login_required
    def campaign_group_options():
        from data_groups import materialize_legacy_groups
        materialize_legacy_groups(db,g.user['id'])
        db().commit()
        rows=db().execute('''SELECT d.id,d.name,d.data_type,count(p.id) AS total,coalesce(sum(p.consent=1),0) AS eligible
            FROM data_groups d LEFT JOIN contact_group_memberships m ON m.user_id=d.user_id AND m.group_name=d.name
            LEFT JOIN contacts p ON p.id=m.contact_id AND p.user_id=d.user_id
            WHERE d.user_id=? AND d.deleted_at IS NULL GROUP BY d.id ORDER BY d.name,d.id''',(g.user['id'],)).fetchall()
        return jsonify(groups=[dict(row) for row in rows],limit=CAMPAIGN_CONTACT_LIMIT)

    @app.post('/campaigns/group-consent')
    @login_required
    def confirm_campaign_group_consent():
        raw=request.form.get('group_id','')
        if not raw.isdigit() or request.form.get('confirm_consent')!='yes':
            return jsonify(error='Chọn nhóm và xác nhận khách hàng đã đồng ý nhận tin.'),400
        db().execute('BEGIN IMMEDIATE')
        group=db().execute('SELECT id,name FROM data_groups WHERE id=? AND user_id=? AND deleted_at IS NULL',(raw,g.user['id'])).fetchone()
        if not group:
            db().rollback()
            return jsonify(error='Không tìm thấy nhóm data.'),404
        count=db().execute('''UPDATE contacts SET consent=1 WHERE user_id=? AND deleted_at IS NULL AND consent=0 AND id IN
            (SELECT contact_id FROM contact_group_memberships WHERE user_id=? AND group_name=?)''',
            (g.user['id'],g.user['id'],group['name'])).rowcount
        db().commit()
        return jsonify(group_id=group['id'],confirmed=count,message=f'Đã xác nhận đồng ý nhận tin cho {count} khách hàng trong nhóm.')

    @app.post('/campaigns/group-snapshot')
    @login_required
    def campaign_group_snapshot():
        raw=request.form.get('group_id','')
        if not raw.isdigit():
            return jsonify(error='Chọn một nhóm data hợp lệ.'),400
        db().execute('BEGIN')
        group=db().execute('SELECT id,name FROM data_groups WHERE id=? AND user_id=? AND deleted_at IS NULL',(raw,g.user['id'])).fetchone()
        if not group:
            db().rollback()
            return jsonify(error='Không tìm thấy nhóm data hoặc bạn không có quyền truy cập.'),404
        rows=db().execute('''SELECT p.id,p.name,p.phone,p.email,p.zalo_id,p.info1,p.info2,p.info3,p.info4,p.info5 FROM contacts p WHERE p.user_id=? AND p.deleted_at IS NULL AND p.consent=1
            AND p.id IN (SELECT contact_id FROM contact_group_memberships WHERE user_id=? AND group_name=?)
            ORDER BY p.id LIMIT ?''',(g.user['id'],g.user['id'],group['name'],CAMPAIGN_CONTACT_LIMIT+1)).fetchall()
        db().rollback()
        if len(rows)>CAMPAIGN_CONTACT_LIMIT:
            return jsonify(error='Nhóm có hơn 10.000 khách hàng đồng ý nhận tin. Chia thành nhóm nhỏ hơn trước khi thêm.'),400
        if not rows:
            return jsonify(error='Chưa ghi nhận trạng thái đồng ý của khách hàng trong nhóm. Bạn có thể xác nhận ngay tại hộp chọn nhóm.'),400
        return jsonify(group_id=group['id'],name=group['name'],rows=[dict(row) for row in rows],total=len(rows))
