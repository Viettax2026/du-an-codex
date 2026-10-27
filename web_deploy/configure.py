"""Render per-installation services and virtual hosts without touching the host."""
import argparse
import json
import re
from pathlib import Path


def validate(domain, name='zaloflow-web', port=8040):
    domain = domain.lower()
    labels = domain.split('.')
    if len(domain) > 253 or len(labels) < 2 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label) for label in labels) or labels[-1].isdigit():
        raise ValueError('Domain không hợp lệ; chỉ nhập tên miền, không nhập https:// hoặc đường dẫn.')
    if not re.fullmatch(r'[a-z][a-z0-9-]{2,30}', name) or name == 'zaloflow':
        raise ValueError('Tên bản cài cần 3–31 ký tự chữ thường, số, dấu gạch ngang; không dùng tên zaloflow của bản cũ.')
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('Cổng nội bộ phải từ 1024 đến 65535.')
    return domain, name, port


def render(domain, name='zaloflow-web', port=8040, tls=True):
    domain, name, port = validate(domain, name, port)
    root = f'/opt/{name}'
    challenge = f'/var/lib/{name}/letsencrypt'
    zone = name.replace('-', '_') + '_auth'
    common = f'''User={name}
Group={name}
WorkingDirectory={root}
Environment=ZALO_QR_ENABLED=1
Environment="PATH={root}/runtime/node/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths={root}/instance
'''
    web = f'''[Unit]
Description=ZaloFlow Web ({domain})
After=network.target

[Service]
{common}Environment=COOKIE_SECURE={1 if tls else 0}
ExecStart={root}/.venv/bin/gunicorn --bind 127.0.0.1:{port} --workers 1 --threads 4 --access-logfile - --error-logfile - app:create_app()
KillMode=mixed
TimeoutStopSec=50

[Install]
WantedBy=multi-user.target
'''
    scheduler = f'''[Unit]
Description=ZaloFlow campaign scheduler ({domain})
Requires={name}.service
After=network.target {name}.service
PartOf={name}.service

[Service]
{common}ExecStart={root}/.venv/bin/python -m flask --app app run-scheduler
KillMode=mixed
TimeoutStopSec=50

[Install]
WantedBy=multi-user.target
'''
    routes = f'''
    client_max_body_size 12m;
    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
    location ~ ^/(login|register)$ {{
        limit_req zone={zone} burst=10 nodelay;
        limit_req_status 429;
        proxy_pass http://127.0.0.1:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
'''
    acme = f'    location ^~ /.well-known/acme-challenge/ {{ root {challenge}; }}\n'
    if tls:
        site = f'''server {{
    listen 80;
    listen [::]:80;
    server_name {domain};
{acme}    location / {{ return 308 https://{domain}$request_uri; }}
}}
server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name {domain};
    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
{routes}}}
'''
    else:
        site = f'''server {{
    listen 80;
    listen [::]:80;
    server_name {domain};
{acme}{routes}}}
'''
    return {f'{name}.service': web, f'{name}-scheduler.service': scheduler,
            f'{name}.nginx.conf': site,
            f'{name}-limits.conf': f'limit_req_zone $binary_remote_addr zone={zone}:10m rate=6r/m;\n',
            'installation.json': json.dumps(dict(domain=domain, name=name, port=port, root=root, tls=tls), indent=2) + '\n'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--domain', required=True); parser.add_argument('--name', default='zaloflow-web')
    parser.add_argument('--port', type=int, default=8040); parser.add_argument('--output', type=Path)
    parser.add_argument('--http-only', action='store_true')
    args = parser.parse_args()
    try:
        files = render(args.domain, args.name, args.port, not args.http_only)
    except ValueError as error:
        parser.error(str(error))
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (args.output / name).write_text(text, encoding='utf-8')
    else:
        print(files['installation.json'])


if __name__ == '__main__':
    main()
