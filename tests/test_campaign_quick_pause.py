from test_workflow import app,post,token,register
from test_campaign_schedule import setup
from test_message_composer import query


def test_quick_pause_resume_is_persistent_idempotent_and_does_not_dispatch(app):
    client,connector=setup(app)
    def change(value):
        return client.post('/campaigns/1/pause',data=dict(csrf=token(client),inline='yes',paused=value,
            return_to='/campaigns?selected=1&detail_tab=history'),headers={'Accept':'application/json'})
    assert change('1').json=={'paused':True}
    assert change('1').json=={'paused':True}
    assert query(app,'SELECT paused,schedule_enabled FROM campaigns')==[(1,1)]
    assert query(app,"SELECT count(*) FROM campaign_events WHERE kind='pause'")==[(1,)]
    assert change('0').json=={'paused':False}
    assert change('0').json=={'paused':False}
    assert query(app,'SELECT paused,schedule_enabled FROM campaigns')==[(0,1)]
    assert query(app,"SELECT count(*) FROM campaign_events WHERE kind='resume'")==[(1,)]
    assert query(app,'SELECT count(*) FROM campaign_attempts')==[(0,)]
    assert not connector.message_action.called


def test_quick_pause_preserves_list_url_and_requires_csrf_ownership_and_valid_target(app):
    client,_=setup(app)
    target='/campaigns?selected=1&detail_tab=history&status=paused'
    response=client.post('/campaigns/1/pause',data=dict(csrf=token(client),inline='yes',paused='1',return_to=target))
    assert response.status_code==302 and response.location==target
    other=app.test_client();register(other,'other')
    assert other.post('/campaigns/1/pause',data=dict(csrf=token(other),inline='yes',paused='0'),headers={'Accept':'application/json'}).status_code==404
    assert client.post('/campaigns/1/pause',data=dict(inline='yes',paused='0')).status_code==400
    for url in ['https://example.org/campaigns','//example.org/campaigns','https://[invalid','/contacts','/campaigns\n']:
        assert client.post('/campaigns/1/pause',data=dict(csrf=token(client),inline='yes',paused='0',return_to=url)).status_code==400
    assert query(app,'SELECT paused FROM campaigns')==[(1,)]
    client.get('/campaigns/1/pause')
    assert query(app,'SELECT paused FROM campaigns')==[(1,)]
