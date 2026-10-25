import json

import pytest

from rich_message import read_message, render_message, select_variant
from test_message_composer import rich, query
from test_send import setup_send, prepare
from test_workflow import app, post


def test_manual_choices_preserve_outer_rotation_and_are_chosen_independently(monkeypatch):
    selections = []
    def choose(options):
        selections.append(len(options))
        return options[-1]
    monkeypatch.setattr('rich_message.secrets.choice', choose)
    message,html = read_message({'message':'{Chào|Xin chào} {anh|chị} {{name}} | Hẹn {gặp|gặp lại} bạn'})
    assert selections == []  # Validation must not consume random choices.
    assert render_message(message,html,{'name':'Lan'},variant_index=0)[0] == 'Xin chào chị Lan'
    assert selections == [2,2]
    assert render_message(message,html,{},variant_index=1)[0] == 'Hẹn gặp lại bạn'
    assert render_message(message,html,{'name':'Lan'},variant_index=2)[0] == 'Xin chào chị Lan'


def test_nested_spins_escape_literals_and_personalization_values_are_not_parsed(monkeypatch):
    monkeypatch.setattr('rich_message.secrets.choice',lambda options:options[-1])
    raw = r'{Chào|{Xin chào|Kính chào}} {{name}} \| \{a\|b\} #{SEX{Anh|Chú-Chị-Bạn}}'
    message,html = read_message({'message':raw})
    assert render_message(message,html,{'name':'{Lan|Thu}'},{'gender':0})[0] == 'Kính chào {Lan|Thu} | {a|b} Anh|Chú'
    assert select_variant('A '+r'\{x\|y\} | B',[],0)[0] == 'A {x|y}'
    # Unknown personalization still fails rather than being spun into a token.
    message,html = read_message({'message':'#{NOT_A_TOKEN|PHONE}'})
    with pytest.raises(ValueError,match='Cú pháp cá nhân hóa'):
        render_message(message,html,{'phone':'0901234567'})


def test_spins_keep_branch_formatting_and_utf16_offsets_after_personalization(monkeypatch):
    monkeypatch.setattr('rich_message.secrets.choice',lambda options:options[-1])
    message,html = read_message(rich('<b>😊 {Chào|Xin chào}</b> <i>{bạn|chị {{name}}}</i>!'))
    text,styles = render_message(message,html,{'name':'Lan😊'})
    assert text == '😊 Xin chào chị Lan😊!'
    assert styles == [{'start':0,'len':11,'st':'b'},{'start':12,'len':9,'st':'i'}]
    message,html = read_message(rich('{<b>Chào</b>|<i>Xin chào</i>}'))
    assert render_message(message,html,{}) == ('Xin chào',[{'start':0,'len':8,'st':'i'}])


def test_longest_possible_choice_enforces_zalo_limit_and_empty_content_is_blocked(monkeypatch):
    message,html = read_message({'message':'{'+('a'*1999)+'|'+('😊'*999)+'}!'})
    assert len(select_variant(message,[],max_length=True)[0]) == 2000
    with pytest.raises(ValueError,match='vượt 2000'):
        read_message({'message':'{ok|'+('😊'*1000)+'}!'})
    with pytest.raises(ValueError,match='Thiếu dấu }'):
        read_message({'message':'Chào {anh|chị'})
    with pytest.raises(ValueError,match='không có nội dung'):
        read_message({'message':'{|}'})
    # An optional phrase is fine; an entirely empty final message cannot send.
    monkeypatch.setattr('rich_message.secrets.choice',lambda options:options[-1])
    assert render_message('Chào{ bạn|}', '', {})[0] == 'Chào'
    with pytest.raises(ValueError,match='đang trống'):
        render_message('{Chào|}', '', {})
    assert read_message({'message':''}) == ('','')  # Campaigns may only request a friend invitation.


@pytest.mark.parametrize('message', ['{'*11+'a|b'+'}'*11, '{'+'|'.join(['a']*21)+'}', '{a|b}'*101])
def test_spins_have_bounded_depth_groups_and_choices(message):
    with pytest.raises(ValueError):
        read_message({'message':message})


def test_composer_preview_and_stored_send_keep_the_chosen_text_after_random_changes(app,monkeypatch):
    client,connector = setup_send(app)
    monkeypatch.setattr('rich_message.secrets.choice',lambda options:options[-1])
    content = rich('<b>{Chào|Xin chào} {{name}}</b> | <i>{Hẹn gặp|Hẹn gặp lại}</i>')
    response = post(client,'/campaigns/1/content',content)
    assert response.status_code == 200
    preview = post(client,'/composer/preview',content).json
    assert [variant['html'] for variant in preview['variants']] == ['<strong>Xin chào Lan</strong>','<em>Hẹn gặp lại</em>']
    prepare(client)
    stored = query(app,'SELECT message,message_styles FROM message_sends')[0]
    assert stored[0] == 'Xin chào Lan'
    assert json.loads(stored[1]) == [{'start':0,'len':12,'st':'b'}]
    monkeypatch.setattr('rich_message.secrets.choice',lambda options:options[0])
    prepare(client)  # A duplicate preview must keep the saved choice and cursor.
    assert query(app,'SELECT message,message_styles FROM message_sends')[0] == stored
    assert query(app,'SELECT next_message_variant FROM campaigns') == [(1,)]
    connector.message_action.reset_mock()
    connector.message_action.return_value = {'state':'sent','message_id':'spin-test'}
    post(client,'/campaigns/1/send/1',{'confirm_send':'yes'})
    assert connector.message_action.call_args.kwargs['message'] == 'Xin chào Lan'
    assert query(app,'SELECT message,message_styles FROM message_sends')[0] == stored


def test_scheduled_send_preserves_random_choice_from_its_saved_preview(app,monkeypatch):
    from test_campaign_schedule import setup, tick
    client,connector = setup(app)
    monkeypatch.setattr('rich_message.secrets.choice',lambda options:options[-1])
    post(client,'/campaigns/1/content',rich('<b>{Chào|Xin chào} {{name}}</b>'))
    tick(app)
    assert query(app,'SELECT scheduled,state,message FROM message_sends') == [(1,'prepared','Xin chào Lan')]
    monkeypatch.setattr('rich_message.secrets.choice',lambda options:options[0])
    tick(app)
    sends = [call for call in connector.message_action.call_args_list if call.args[2]=='send']
    assert len(sends)==1 and sends[0].kwargs['message']=='Xin chào Lan'
    assert sends[0].kwargs['styles']==[{'start':0,'len':12,'st':'b'}]
    assert query(app,'SELECT next_message_variant FROM campaigns') == [(1,)]
    assert query(app,'SELECT state,message FROM message_sends') == [('sent','Xin chào Lan')]
