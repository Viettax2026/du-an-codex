"""Bounded, read-only data for the campaign list's inline detail tabs."""
import math

from flask import abort, g
from markupsafe import Markup

from rich_message import parse_html, markup, variant_spans
from campaign_results import result_count,result_rows

TABS=('info','accounts','data','results','preview','history')


def inline_detail(db,campaign,tab='info',number=1,connector=None):
    if campaign['user_id']!=g.user['id']:
        abort(404)
    if tab not in TABS:
        abort(400)
    user_id,campaign_id=campaign['user_id'],campaign['id']
    if campaign['audience_mode']=='list':
        data_where='p.user_id=? AND p.id IN (SELECT contact_id FROM campaign_contacts WHERE campaign_id=?)'
        data_args=(user_id,campaign_id)
    else:
        data_where="p.user_id=? AND p.deleted_at IS NULL AND (?='' OR p.id IN (SELECT contact_id FROM contact_group_memberships WHERE user_id=? AND group_name=?))"
        data_args=(user_id,campaign['tag'],user_id,campaign['tag'])
    account_where='a.user_id=? AND (a.id=? OR EXISTS (SELECT 1 FROM message_sends s WHERE s.account_id=a.id AND s.campaign_id=?))'
    account_args=(user_id,campaign['account_id'],campaign_id)
    totals=dict(data=db().execute('SELECT count(*) FROM contacts p WHERE '+data_where,data_args).fetchone()[0],
                accounts=db().execute('SELECT count(*) FROM zalo_accounts a WHERE '+account_where,account_args).fetchone()[0],
                results=result_count(db,user_id,campaign_id),
                history=db().execute('SELECT count(*) FROM campaign_events WHERE campaign_id=?',(campaign_id,)).fetchone()[0])
    message=campaign['message'];ranges=[]
    try:
        if campaign['message_html']:
            source,parsed=parse_html(campaign['message_html'])
            if source==message:
                ranges=parsed
        spans=variant_spans(message) if message else []
    except ValueError:
        spans=[(0,len(message))] if message else []
    variants,formatted=[],[]
    for a,b in spans:
        clipped=[(max(a,start)-a,min(b,end)-a,style) for start,end,style in ranges if min(b,end)>max(a,start)]
        variants.append(Markup(markup(message[a:b],clipped)))
        formatted.append(bool(clipped))
    totals['preview']=len(variants)
    per_page=100 if tab=='history' else 50
    total=totals.get(tab,0)
    pages=max(1,math.ceil(total/per_page));number=max(1,min(number,pages))
    offset=(number-1)*per_page
    detail=dict(tab=tab,counts=totals,number=number,pages=pages,total=total,per_page=per_page,offset=offset,
                rows=[],variants=variants,formatted=formatted,exclusions=[])
    if tab=='data':
        detail['rows']=db().execute('SELECT p.* FROM contacts p WHERE '+data_where+' ORDER BY p.id LIMIT ? OFFSET ?',(*data_args,per_page,offset)).fetchall()
    elif tab=='results':
        detail['rows']=result_rows(db,user_id,campaign_id,per_page,offset)
    elif tab=='history':
        detail['rows']=db().execute('SELECT * FROM campaign_events WHERE campaign_id=? ORDER BY id DESC LIMIT ? OFFSET ?',
                                  (campaign_id,per_page,offset)).fetchall()
    elif tab=='accounts':
        rows=db().execute('SELECT a.* FROM zalo_accounts a WHERE '+account_where+' ORDER BY a.id LIMIT ? OFFSET ?',(*account_args,per_page,offset)).fetchall()
        detail['rows']=[dict(row,connection={'state':'deleted'} if row['deleted_at'] else connector.status(user_id,row['id']) if connector else {'state':'disconnected'}) for row in rows]
    elif tab=='info':
        detail['exclusions']=db().execute('''SELECT r.name FROM exclusion_rule_groups r JOIN campaign_exclusion_rules x ON x.rule_group_id=r.id
            WHERE x.campaign_id=? AND r.user_id=? UNION SELECT l.name FROM exclusion_lists l JOIN campaign_exclusion_lists x ON x.list_id=l.id
            WHERE x.campaign_id=? AND l.user_id=?''',(campaign_id,user_id,campaign_id,user_id)).fetchall()
    return detail
