import sqlite3
import pytest

from test_workflow import app, post, register


def query(app, sql, args=()):
    with sqlite3.connect(app.config['DATABASE']) as connection:
        return connection.execute(sql, args).fetchall()


def delete(app, username='test12345'):
    return app.test_cli_runner().invoke(args=['delete-test-user','--username',username])


def test_delete_exact_empty_test_account_revokes_session_and_recovery(app):
    owner=app.test_client(); register(owner,'owner')
    target=app.test_client(); register(target,'test12345')
    similar=app.test_client(); register(similar,'test123456')
    app.test_cli_runner().invoke(args=['issue-recovery-code','--username','test12345'])
    result=delete(app,' TEST12345 ')
    assert result.exit_code == 0 and 'Đã xóa tài khoản thử test12345.' in result.output
    assert query(app,'SELECT username FROM users ORDER BY id') == [('owner',),('test123456',)]
    assert query(app,'SELECT * FROM account_recovery_codes WHERE user_id=2') == []
    assert query(app,'SELECT * FROM account_approval_events WHERE user_id=2') == []
    assert target.get('/account/security').status_code == 302
    assert owner.get('/contacts').status_code == 200
    assert similar.get('/contacts').status_code == 200
    assert 'Không tìm thấy' in delete(app).output


def test_cleanup_refuses_real_data_and_rolls_back(app):
    target=app.test_client(); register(target,'test12345')
    post(target,'/contacts',{'name':'Keep customer','phone':'0901234567'})
    before=query(app,'SELECT * FROM users'),query(app,'SELECT * FROM contacts'),query(app,'SELECT * FROM account_approval_events')
    result=delete(app)
    assert result.exit_code != 0 and 'contacts' in result.output
    assert (query(app,'SELECT * FROM users'),query(app,'SELECT * FROM contacts'),query(app,'SELECT * FROM account_approval_events')) == before
    assert target.get('/contacts').status_code == 200


def test_cleanup_refuses_admin_and_non_test_names(app):
    target=app.test_client(); register(target,'test12345')
    app.test_cli_runner().invoke(args=['grant-admin','--username','test12345'])
    assert delete(app).exit_code != 0
    for name in ('admin','owner','test%','test12345 OR 1=1'):
        assert delete(app,name).exit_code != 0
    assert query(app,'SELECT count(*) FROM users') == [(1,)]


def test_cleanup_does_not_delete_other_accounts_audit_or_unknown_relations(app):
    target=app.test_client(); register(target,'test12345')
    other=app.test_client(); register(other,'other')
    with sqlite3.connect(app.config['DATABASE']) as connection:
        connection.execute("INSERT INTO account_approval_events(user_id,actor_id,action) VALUES (2,1,'approved')")
    assert delete(app).exit_code != 0
    assert query(app,'SELECT count(*) FROM users') == [(2,)]
    with sqlite3.connect(app.config['DATABASE']) as connection:
        connection.execute('DELETE FROM account_approval_events WHERE actor_id=1')
        connection.execute('CREATE TABLE future_data(id INTEGER PRIMARY KEY,user_id INTEGER)')
        connection.execute('INSERT INTO future_data(user_id) VALUES(1)')
    result=delete(app)
    assert result.exit_code != 0 and 'future_data' in result.output
    assert query(app,'SELECT count(*) FROM users') == [(2,)]


def test_deleted_identity_is_never_reused_by_signup_or_admin_creation(app):
    stale=app.test_client(); register(stale,'test12345')
    assert delete(app).exit_code == 0
    assert query(app,'SELECT id FROM retired_user_ids') == [(1,)]
    admin_result=app.test_cli_runner().invoke(args=['reset-admin'],input='new-admin-password\nnew-admin-password\n')
    assert admin_result.exit_code == 0
    assert query(app,'SELECT id,username FROM users') == [(2,'admin')]
    replacement=app.test_client(); register(replacement,'test12345')
    assert query(app,'SELECT id FROM users WHERE username=?',('test12345',)) == [(3,)]
    assert stale.get('/account/security').status_code == 302
    with sqlite3.connect(app.config['DATABASE']) as connection:
        with pytest.raises(sqlite3.IntegrityError,match='cannot be reused'):
            connection.execute("INSERT INTO users(id,name,username,password) VALUES(1,'Old ID','other','unused')")
