"""Local authority administration; never bundle this package in the customer EXE."""
import argparse
import json
import os
import getpass

from license_system.authority import Authority
from license_system.signatures import LicenseError


def main():
    parser = argparse.ArgumentParser(description='Quản lý key ZaloFlow (chỉ chạy trên máy chủ của chủ phần mềm)')
    parser.add_argument('--data-dir', default=os.environ.get('ZALOFLOW_LICENSE_DATA', '/var/lib/zaloflow-licenses'))
    sub = parser.add_subparsers(dest='action', required=True)
    init = sub.add_parser('init'); init.add_argument('--url', required=True)
    issue = sub.add_parser('issue'); issue.add_argument('--customer', required=True); issue.add_argument('--days', type=int, default=30)
    sub.add_parser('list')
    sub.add_parser('set-admin-password')
    for name in ('revoke', 'extend', 'reset-devices'):
        command = sub.add_parser(name); command.add_argument('id', type=int)
        if name == 'extend':
            command.add_argument('--days', type=int, default=30)
    args = parser.parse_args(); authority = Authority(args.data_dir)
    try:
        if args.action == 'init':
            result = authority.initialize(args.url)
        elif args.action == 'issue':
            result = authority.issue(args.customer, args.days, seats=1)
        elif args.action == 'list':
            result = authority.list_licenses()
        elif args.action == 'set-admin-password':
            password = getpass.getpass('Mật khẩu quản trị mới: ')
            if password != getpass.getpass('Nhập lại: '):
                raise LicenseError('Mật khẩu nhập lại không khớp.')
            authority.set_admin_password(password); result = dict(ok=True)
        else:
            authority.manage(args.id, args.action, getattr(args, 'days', 30)); result = dict(ok=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (LicenseError, FileExistsError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
