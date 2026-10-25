"""Read saved per-action outcomes without dispatching or resolving recipients."""

RESULTS_SQL='''WITH source AS (
    SELECT s.id,s.recipient_name,s.recipient_phone,s.recipient_id,s.created_at,s.lookup_state,
        s.state,s.friend_state,s.alias_state,s.alias,s.message_skip_reason,a.name AS account_name,p.phone FROM message_sends s
    JOIN campaigns c ON c.id=s.campaign_id AND c.user_id=:owner
    JOIN contacts p ON p.id=s.contact_id AND p.user_id=c.user_id
    JOIN zalo_accounts a ON a.id=s.account_id AND a.user_id=c.user_id
    WHERE s.campaign_id=:campaign
), outcomes AS (
    SELECT id,'lookup' AS action,0 AS rank,
        CASE WHEN lookup_state<>'' THEN lookup_state WHEN recipient_id<>'' THEN 'resolved'
             WHEN message_skip_reason='Bỏ qua ' || recipient_phone || ': không tìm thấy Zalo từ số điện thoại này.'
             THEN 'not_found' ELSE 'unavailable' END AS outcome,
        created_at AS occurred_at,0 AS approximate FROM source
    UNION ALL
    SELECT id,'send',1,'skipped',created_at,0 FROM source
        WHERE state='not_requested' AND recipient_id<>'' AND message_skip_reason<>''
'''+''.join(f'''
    UNION ALL SELECT s.id,'{action}',{rank},s.{column},
        coalesce(a.completed_at,a.created_at,s.created_at),a.completed_at IS NULL
        FROM source s LEFT JOIN campaign_attempts a ON a.send_id=s.id AND a.action='{action}'
        WHERE s.{column} NOT IN ('prepared','not_requested')
''' for action,column,rank in [('send','state',1),('friend','friend_state',2),('alias','alias_state',3)])+''')
'''

LABELS={'lookup':'Tìm SĐT','send':'Nhắn tin người lạ','friend':'Kết bạn','alias':'Đổi tên Zalo'}


def result_count(db,owner,campaign):
    return db().execute(RESULTS_SQL+'SELECT count(*) FROM outcomes',dict(owner=owner,campaign=campaign)).fetchone()[0]


def result_rows(db,owner,campaign,limit,offset):
    rows=db().execute(RESULTS_SQL+'''SELECT o.*,s.recipient_name,s.recipient_phone,s.phone,s.account_name,
        s.message_skip_reason,s.alias FROM outcomes o JOIN source s ON s.id=o.id
        ORDER BY o.occurred_at DESC,o.id DESC,o.rank DESC LIMIT :limit OFFSET :offset''',
        dict(owner=owner,campaign=campaign,limit=limit,offset=offset)).fetchall()
    results=[]
    for row in rows:
        item=dict(row);state=row['outcome'];action=row['action']
        name=row['recipient_name'] or row['recipient_phone'] or row['phone']
        phone=row['recipient_phone'] or row['phone']
        status,tone='Chưa xác định','warning'
        if state in ('resolved','sent','friend_requested','renamed'):
            status,tone='Thành công','success'
            description={'lookup':f'Đã tìm thấy SĐT {phone}: {name}.',
                         'send':f'Zalo đã tiếp nhận tin nhắn đến {name}.',
                         'friend':f'Zalo đã tiếp nhận lời mời kết bạn đến {name}.',
                         'alias':f'Đã đổi tên {name} thành "{row["alias"]}".'}[action]
        elif state=='not_found':
            status,description='Không tồn tại','Không tìm thấy Zalo từ số điện thoại này.'
        elif state=='cached':
            status,tone,description='Đã lưu','neutral','Dùng Zalo đã lưu từ lần tra cứu trước; không tra cứu lại.'
        elif state=='unavailable':
            status,description='Không tra cứu được',row['message_skip_reason'] or 'Chưa xác định được người nhận Zalo.'
        elif state=='skipped':
            status,tone,description='Đã bỏ qua','neutral',row['message_skip_reason']
        elif state=='failed':
            status,tone,description='Thất bại','error','Hành động không thành công. Kiểm tra phiên Zalo và lịch sử chạy.'
        elif state=='sending':
            status,description='Đang xử lý / cần kiểm tra','Chưa có kết quả xác nhận. Không tự thực hiện lại hành động.'
        else:
            description='Chưa xác định kết quả. Kiểm tra hội thoại Zalo trước khi tiếp tục.'
        item.update(name=name,phone=phone,label=LABELS[action],status=status,tone=tone,description=description)
        results.append(item)
    return results
