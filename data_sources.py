"""Provenance records store metadata only, never uploaded file contents."""
import re


def initialize_data_sources(db):
    columns = {row['name'] for row in db().execute('PRAGMA table_info(contacts)')}
    if 'current_source_id' not in columns:
        db().execute('ALTER TABLE contacts ADD COLUMN current_source_id INTEGER')
    db().executescript('''CREATE TABLE IF NOT EXISTS data_import_batches (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
        group_id INTEGER REFERENCES data_groups(id), group_name TEXT NOT NULL,
        filename TEXT NOT NULL DEFAULT '', source_type TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS contact_data_sources (
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
        contact_id INTEGER NOT NULL REFERENCES contacts(id), batch_id INTEGER REFERENCES data_import_batches(id),
        group_id INTEGER REFERENCES data_groups(id), source_type TEXT NOT NULL,
        filename TEXT NOT NULL DEFAULT '', label TEXT NOT NULL, created_at TEXT,
        UNIQUE(contact_id,batch_id));
        CREATE INDEX IF NOT EXISTS contact_data_sources_contact ON contact_data_sources(user_id,contact_id,id);''')
    prefix = 'Tải file lên · '
    # A pre-existing label is evidence of a source, but supplies no timestamp or batch ID.
    db().execute('''INSERT INTO contact_data_sources(user_id,contact_id,source_type,filename,label)
        SELECT user_id,id,CASE WHEN substr(data_source,1,?)=? THEN 'file' ELSE 'legacy' END,
        CASE WHEN substr(data_source,1,?)=? THEN substr(data_source,?) ELSE '' END,data_source FROM contacts p
        WHERE data_source!='' AND current_source_id IS NULL AND NOT EXISTS
        (SELECT 1 FROM contact_data_sources s WHERE s.contact_id=p.id AND s.user_id=p.user_id)''',
        (len(prefix),prefix,len(prefix),prefix,len(prefix)+1))
    db().execute('''UPDATE contacts SET current_source_id=(SELECT id FROM contact_data_sources s
        WHERE s.contact_id=contacts.id AND s.user_id=contacts.user_id AND s.label=contacts.data_source ORDER BY id LIMIT 1)
        WHERE current_source_id IS NULL AND data_source!='' ''')


def create_source_batch(db, user_id, group_name, filename='', source_type=None):
    filename = filename or ''
    if source_type != 'api':
        filename = filename.replace('\\','/').split('/')[-1]
    filename = re.sub(r'[\x00-\x1f\x7f]', '', filename)[:150]
    kind = source_type or ('file' if filename else 'direct')
    group = db().execute('SELECT id FROM data_groups WHERE user_id=? AND name=?', (user_id,group_name)).fetchone()
    return db().execute('''INSERT INTO data_import_batches(user_id,group_id,group_name,filename,source_type)
        VALUES (?,?,?,?,?)''', (user_id,group['id'] if group else None,group_name,filename,kind)).lastrowid


def record_contact_source(db, user_id, contact_id, batch_id):
    contact = db().execute('SELECT data_source,current_source_id FROM contacts WHERE id=? AND user_id=?', (contact_id,user_id)).fetchone()
    batch = db().execute('SELECT * FROM data_import_batches WHERE id=? AND user_id=?', (batch_id,user_id)).fetchone()
    if not contact or not batch:
        raise ValueError('Nguồn data không thuộc tài khoản hiện tại.')
    label = ('Quét Zalo · ' + batch['filename']) if batch['source_type']=='scan' else ('API · ' + batch['filename'] if batch['filename'] else 'Nhập qua API') if batch['source_type']=='api' else ('Tải file lên · ' + batch['filename'] if batch['filename'] else 'Nhập trực tiếp')
    db().execute('''INSERT OR IGNORE INTO contact_data_sources(user_id,contact_id,batch_id,group_id,source_type,filename,label,created_at)
        VALUES (?,?,?,?,?,?,?,?)''', (user_id,contact_id,batch_id,batch['group_id'],batch['source_type'],batch['filename'],label,batch['created_at']))
    if not contact['data_source']:
        event = db().execute('SELECT id FROM contact_data_sources WHERE contact_id=? AND batch_id=? AND user_id=?', (contact_id,batch_id,user_id)).fetchone()
        db().execute('UPDATE contacts SET data_source=?,current_source_id=? WHERE id=? AND user_id=?', (label,event['id'],contact_id,user_id))
