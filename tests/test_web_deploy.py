import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from web_deploy.configure import render, validate
from web_deploy.package import ROOT, build, install_code, verify


def test_domain_port_and_name_are_data_not_shell_or_nginx_directives():
    assert validate('CRM.Example.com', 'crm-web', 8099) == ('crm.example.com', 'crm-web', 8099)
    for domain in ('https://example.com', 'example.com/x', 'example.com; include /tmp/x;', '127.0.0.1', '*.example.com', 'a..com', '-x.com', 'x\n.example.com'):
        with pytest.raises(ValueError):
            validate(domain)
    for name in ('zaloflow', '../bad', 'test; id', 'root user', 'a', 'UPPER'):
        with pytest.raises(ValueError):
            validate('example.com', name)
    for port in (80, 443, 0, 65536, True, '8040'):
        with pytest.raises(ValueError):
            validate('example.com', port=port)


def test_custom_installations_render_independent_services_paths_and_auth_zones():
    first, second = render('crm.example.com'), render('other.example.com', 'other-web', 8088)
    assert '127.0.0.1:8040' in first['zaloflow-web.service']
    assert '/opt/other-web/instance' in second['other-web.service']
    assert '127.0.0.1:8088' in second['other-web.nginx.conf']
    assert 'other_web_auth' in second['other-web-limits.conf']
    assert 'cskh.viettaxco.com' not in '\n'.join(second.values())
    assert 'COOKIE_SECURE=1' in second['other-web.service']
    assert 'COOKIE_SECURE=0' in render('test.example.com', tls=False)['zaloflow-web.service']
    assert 'Requires=other-web.service' in second['other-web-scheduler.service']
    assert '127.0.0.1:8088' in second['other-web.service']
    assert 'listen 443 ssl' in second['other-web.nginx.conf']
    assert 'return 308 https://other.example.com$request_uri' in second['other-web.nginx.conf']


def test_web_archive_excludes_private_instances_windows_authority_and_dependencies(tmp_path):
    archive = build(tmp_path / 'web.zip')
    with zipfile.ZipFile(archive) as zip:
        names = set(zip.namelist())
        assert 'zaloflow-web/app.py' in names and 'zaloflow-web/web_deploy/install-web.sh' in names
        assert 'zaloflow-web/connector/package-lock.json' in names
        for name in names:
            assert not any(part in name.split('/') for part in ('instance', 'desktop', 'license_system', '.venv', 'node_modules', '.git', '__pycache__'))
            assert not name.endswith(('.pem', '.sqlite3', '.key', '.pyc', '.exe'))
        zip.extractall(tmp_path / 'extracted')
    source = tmp_path / 'extracted/zaloflow-web'
    release = verify(source)
    assert release['includes_customer_data'] is False and release['includes_windows_app'] is False
    assert build(tmp_path / 'rebuilt-without-git.zip', root=source).is_file()
    installed = tmp_path / 'installed'
    installed.joinpath('instance').mkdir(parents=True)
    installed.joinpath('instance/keep.txt').write_text('saved user data')
    source.joinpath('instance').mkdir(); source.joinpath('instance/do-not-copy.txt').write_text('not part of the code package')
    install_code(source, installed)
    assert installed.joinpath('instance/keep.txt').read_text() == 'saved user data'
    assert not installed.joinpath('instance/do-not-copy.txt').exists()
    installed.joinpath('app.py').write_text('changed')
    with pytest.raises(ValueError, match='thay đổi'):
        verify(installed)


def test_manifest_does_not_allow_paths_outside_the_installation(tmp_path):
    archive = build(tmp_path / 'web.zip')
    with zipfile.ZipFile(archive) as zip:
        zip.extractall(tmp_path)
    root = tmp_path / 'zaloflow-web'
    manifest = root / 'WEB-RELEASE.json'
    value = json.loads(manifest.read_text()); value['files']['../outside'] = 'irrelevant'
    manifest.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='Đường dẫn'):
        verify(root)


def test_web_scripts_parse_and_help_never_changes_the_machine():
    for script in ('install-web.sh', 'node-runtime.sh', 'backup-web.sh'):
        subprocess.run(['bash', '-n', str(ROOT / 'web_deploy' / script)], check=True)
    result = subprocess.run(['bash', str(ROOT / 'web_deploy/install-web.sh'), '--help'], capture_output=True, text=True, check=True)
    assert '--domain' in result.stdout and '--start-scheduler' in result.stdout
