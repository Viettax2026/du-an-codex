import json
import subprocess
import uuid
from types import SimpleNamespace

import pytest

from zalo_connector import QRConnector


def connector(tmp_path,monkeypatch,output):
    result=QRConnector(tmp_path,tmp_path)
    result.available=lambda:True
    result.status=lambda *args:{'state':'connected'}
    base=result.account_path(1,1);base.mkdir(parents=True)
    (base/'current.json').write_text(json.dumps({'run_id':str(uuid.uuid4())}))
    if isinstance(output,Exception):
        def run(*args,**kwargs):raise output
    else:
        def run(*args,**kwargs):return SimpleNamespace(stdout=output)
    monkeypatch.setattr(subprocess,'run',run)
    return result


def test_lookup_diagnostics_cross_the_worker_boundary_without_upstream_secrets(tmp_path,monkeypatch):
    worker=connector(tmp_path,monkeypatch,json.dumps({'state':'lookup_failed','lookup_reason':'session','lookup_code':'401',
                      'message':'private cookie/path/token','cookie':'private'}))
    assert worker.message_action(1,1,'resolve',phone='0901234567')=={'state':'lookup_failed','lookup_reason':'session','lookup_code':'401'}


@pytest.mark.parametrize('output,reason',[(subprocess.TimeoutExpired('node',45),'network'),('not JSON private data','invalid_response')])
def test_lookup_timeout_and_invalid_output_are_typed_not_missing_profiles(tmp_path,monkeypatch,output,reason):
    worker=connector(tmp_path,monkeypatch,output)
    assert worker.message_action(1,1,'resolve',phone='0901234567')=={'state':'lookup_failed','lookup_reason':reason}
