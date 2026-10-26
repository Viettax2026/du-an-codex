"""Campaign edits preserve claimed outcomes and replace only unused previews."""
import json


def initialize_edits(db):
    db().executescript('''CREATE TABLE IF NOT EXISTS campaign_preview_archive (
        id INTEGER PRIMARY KEY,campaign_id INTEGER NOT NULL REFERENCES campaigns(id),source_table TEXT NOT NULL,
        send_id INTEGER NOT NULL,snapshot TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS campaign_send_sequences (source_table TEXT PRIMARY KEY,last_id INTEGER NOT NULL);''')
    if 'edit_revision' not in {row['name'] for row in db().execute('PRAGMA table_info(campaigns)')}:
        db().execute('ALTER TABLE campaigns ADD COLUMN edit_revision INTEGER NOT NULL DEFAULT 0')
    if 'media_id' not in {row['name'] for row in db().execute('PRAGMA table_info(campaign_preview_archive)')}:
        db().execute('ALTER TABLE campaign_preview_archive ADD COLUMN media_id INTEGER REFERENCES campaign_media(id)')


def reserve_send_ids(db,table):
    if table not in ('message_sends','group_message_sends'):raise ValueError('Invalid send table')
    maximum=db().execute(f'SELECT coalesce(max(id),0) FROM {table}').fetchone()[0]
    db().execute('INSERT INTO campaign_send_sequences(source_table,last_id) VALUES (?,?) ON CONFLICT(source_table) DO UPDATE SET last_id=max(last_id,excluded.last_id)',(table,maximum))


def next_send_id(db,table):
    # Callers hold BEGIN IMMEDIATE. Never recycle an old confirmation URL,
    # including the highest ID when every unused preview has been removed.
    reserve_send_ids(db,table)
    db().execute('UPDATE campaign_send_sequences SET last_id=last_id+1 WHERE source_table=?',(table,))
    return db().execute('SELECT last_id FROM campaign_send_sequences WHERE source_table=?',(table,)).fetchone()[0]


def edit_remaining(db,manager,campaign):
    cid=campaign['id'];group=campaign['campaign_type']=='zalo_group'
    table='group_message_sends' if group else 'message_sends'
    reserve_send_ids(db,table)
    if group:
        rows=db().execute("SELECT * FROM group_message_sends WHERE campaign_id=? AND state='prepared' AND claimed_at IS NULL",(cid,)).fetchall()
        db().execute("UPDATE group_message_batches SET state='superseded',finished_at=CURRENT_TIMESTAMP WHERE campaign_id=? AND state='prepared'",(cid,))
    else:
        rows=db().execute('''SELECT * FROM message_sends s WHERE campaign_id=? AND schedule_skip_reason=''
            AND state IN ('prepared','not_requested') AND friend_state IN ('prepared','not_requested') AND alias_state IN ('prepared','not_requested')
            AND (state='prepared' OR friend_state='prepared' OR alias_state='prepared')
            AND NOT EXISTS (SELECT 1 FROM campaign_attempts a WHERE a.send_id=s.id)''',(cid,)).fetchall()
        # Completed/claimed actions remain immutable. Only unclaimed actions
        # receive a versioned payload, including their new sender if changed.
        partial=db().execute('''SELECT s.* FROM message_sends s WHERE campaign_id=? AND schedule_skip_reason=''
            AND (state='prepared' OR friend_state='prepared' OR alias_state='prepared')
            AND (EXISTS (SELECT 1 FROM campaign_attempts a WHERE a.send_id=s.id)
                 OR state NOT IN ('prepared','not_requested') OR friend_state NOT IN ('prepared','not_requested') OR alias_state NOT IN ('prepared','not_requested'))''',(cid,)).fetchall()
        for row in partial:
            manager.pending.stage(db().execute('SELECT * FROM campaigns WHERE id=?',(cid,)).fetchone(),row)
    for row in rows:
        db().execute('INSERT INTO campaign_preview_archive(campaign_id,source_table,send_id,snapshot,media_id) VALUES (?,?,?,?,?)',
            (cid,table,row['id'],json.dumps(dict(row),ensure_ascii=False),row['media_id']))
        db().execute(f'DELETE FROM {table} WHERE id=?',(row['id'],))
    db().execute('''UPDATE campaigns SET edit_revision=edit_revision+1,schedule_revision=schedule_revision+1,
        schedule_error='',schedule_status=CASE WHEN schedule_enabled=1 THEN 'Tiếp tục phần data chưa xử lý theo cấu hình mới' ELSE schedule_status END WHERE id=?''',(cid,))
    manager.event(cid,'edit_remaining',f'Sửa chiến dịch: áp dụng cấu hình mới cho các bước chưa thực hiện. Vô hiệu hóa {len(rows)} bản xem trước chưa gửi; lưu bản cũ vào lịch sử. Giữ kết quả, lượt hạn mức và thời gian nghỉ; không thực hiện lại hành động đã có lượt chạy.')
