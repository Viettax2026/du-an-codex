"""Native Windows window; no server or schedule service is installed."""
import argparse
import faulthandler
import hashlib
import json
import logging
import sys
import tempfile
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.request import urlopen

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from desktop.runtime import DesktopRuntime,default_data_root
from desktop.windows_job import protect_process_tree
from desktop.window import run_window, show_error


def smoke_check(report,gui=False):
    from desktop.licensing import CONFIG_PATH, DesktopLicense, load_config
    from license_system.signatures import PRODUCT, LicenseError, new_signer, public_text, sign
    from werkzeug.security import generate_password_hash
    publisher_identity_sha256=''
    try:
        publisher=load_config()
    except LicenseError:
        pass  # Unconfigured disposable builds still exercise synthetic flows.
    else:
        publisher_identity_sha256=hashlib.sha256(json.dumps(publisher,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    # Persistent WebView2 profiles can retain a cache file until process exit.
    # These are disposable test profiles; the process job closes any remaining
    # browser children on exit. Normal user profiles are never removed here.
    with tempfile.TemporaryDirectory(prefix='zaloflow-smoke-',ignore_cleanup_errors=True) as folder:
        signer=new_signer();device='ZFM1-'+'A'*64
        admin_password='synthetic-admin-password'
        admin_hash=generate_password_hash(admin_password)
        def transport(config,action,data):
            if action=='release':return dict(released=True)
            now=int(time.time())
            lease=sign(signer,dict(product=PRODUCT,license_id=1,customer='Smoke test only',activation_id=1,
                device=device,issued_at=now,valid_until=now+60,license_expires_at=now+86400,
                license_mode='floating',session_id=data['session_id'],
                tool_admin=dict(username='native-owner',password_hash=admin_hash)))
            return dict(lease=lease,activation_token='temporary-smoke-activation-token')
        license=DesktopLicense(Path(folder)/'license',config=dict(server_url='https://smoke.invalid',public_key=public_text(signer)),transport=transport,device=device)
        runtime=DesktopRuntime(folder,license=license)
        try:
            runtime.start()
            with urlopen(runtime.url+'/register',timeout=10) as response:assert response.url.endswith('/desktop/license')
            from account_approval import create_pending_account, set_approval
            with runtime.app.app_context():
                db=runtime.app.extensions['campaign_manager'].db()
                old=create_pending_account(db,'Synthetic old user','native-owner',generate_password_hash('synthetic-old-password'))
                set_approval(db,old.lastrowid,'approved');db.commit()
            license.activate('ZF-'+'a'*32)
            assert license.allowed(),'Signed activation was not accepted'
            assert license.claims()['license_mode']=='floating','Session license was not accepted'
            from desktop.admin_accounts import sync_license_admin
            try:sync_license_admin(runtime.app,license)
            except LicenseError:pass
            else:raise AssertionError('A signed key overwrote an existing local account')
            from desktop.smoke_recovery import verify_admin_name_conflict
            assert verify_admin_name_conflict(runtime.url,admin_password),'Packaged admin name conflict recovery failed'
            with urlopen(runtime.url+'/login',timeout=10) as response:assert response.status==200
            assert runtime.app.extensions['zalo_connector'].available(),'Missing bundled Node.js or Zalo SDK'
            from desktop.smoke_recovery import verify_recovery_flow
            assert verify_recovery_flow(runtime.url),'Packaged self-registration and password recovery did not complete'
            from desktop.smoke_recovery import verify_admin_flow
            assert verify_admin_flow(runtime.url,'native-owner-key-1',admin_password),'Packaged admin account creation failed'
            if gui:run_window(runtime,smoke=True)
            else:
                runtime.activate();deadline=time.monotonic()+10
                heartbeat=Path(runtime.app.config['DATABASE']).with_suffix('.scheduler.heartbeat')
                while not heartbeat.exists() and time.monotonic()<deadline:time.sleep(.05)
                assert heartbeat.exists(),'Local scheduler did not start'
                assert runtime.stop(timeout=10),'Local runtime did not close'
            Path(report).write_text(json.dumps(dict(ok=True,gui=gui,stopped=runtime.closed.is_set(),node_available=True,licensed=True,password_recovery=True,self_registration=True,floating_license=True,tool_admin_accounts=True,admin_name_conflict=True,publisher_identity_sha256=publisher_identity_sha256)),encoding='utf-8')
        finally:runtime.stop()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir');parser.add_argument('--smoke-test',action='store_true');parser.add_argument('--smoke-gui',action='store_true');parser.add_argument('--smoke-report')
    support=parser.add_mutually_exclusive_group()
    support.add_argument('--support-recovery',metavar='USERNAME',help='Local Windows administrator: issue a one-use recovery code for an existing account.')
    support.add_argument('--grant-account-admin',metavar='USERNAME',help='Local Windows administrator: approve an existing account and grant local ZaloFlow administration.')
    args=parser.parse_args();protect_process_tree()
    if args.grant_account_admin:
        from desktop.recovery import account_admin_dialog
        try:account_admin_dialog(args.data_dir or default_data_root(),args.grant_account_admin)
        except Exception as error:
            show_error(str(error) if isinstance(error,RuntimeError) else 'Không cấp được quyền quản trị. Kiểm tra thư mục dữ liệu và đóng ZaloFlow trước.')
            raise SystemExit(1)
        return
    if args.support_recovery:
        from desktop.recovery import recovery_dialog
        try:recovery_dialog(args.data_dir or default_data_root(),args.support_recovery)
        except Exception as error:
            show_error(str(error) if isinstance(error,RuntimeError) else 'Không tạo được mã hỗ trợ. Kiểm tra thư mục dữ liệu và đóng ZaloFlow trước.')
            raise SystemExit(1)
        return
    if args.smoke_test:
        if not args.smoke_report:parser.error('--smoke-report is required')
        # Windowed executables have no stderr. Preserve exceptions and blocked
        # thread stacks so a failed Windows smoke test is diagnosable.
        with open(args.smoke_report+'.log','w',encoding='utf-8') as diagnostic:
            logging.basicConfig(stream=diagnostic,level=logging.INFO,force=True)
            faulthandler.enable(diagnostic)
            faulthandler.dump_traceback_later(45,repeat=True,file=diagnostic)
            try:smoke_check(args.smoke_report,args.smoke_gui)
            except BaseException:
                logging.getLogger('desktop').exception('Packaged smoke test failed')
                raise SystemExit(1)
            finally:faulthandler.cancel_dump_traceback_later()
        return
    root=Path(args.data_dir or default_data_root());root.mkdir(parents=True,exist_ok=True)
    log=RotatingFileHandler(root/'desktop.log',maxBytes=2_000_000,backupCount=2,encoding='utf-8')
    logging.basicConfig(handlers=[log],level=logging.WARNING,format='%(asctime)s %(levelname)s %(message)s')
    runtime=None
    try:
        runtime=DesktopRuntime(root)
        if not runtime.app.extensions['zalo_connector'].available():raise RuntimeError('Thiếu bộ kết nối. Đóng ZaloFlow rồi chạy lại bộ cài để khôi phục tệp chương trình.')
        runtime.start();run_window(runtime)
    except Exception as error:
        logging.getLogger('desktop').exception('Desktop startup failed')
        message=str(error) if isinstance(error,RuntimeError) and str(error).startswith(('Bộ chạy','Thiếu bộ kết nối')) else 'Không mở được ZaloFlow. Kiểm tra Microsoft Edge WebView2 Runtime và xem desktop.log trong thư mục dữ liệu.'
        show_error(message)
        raise SystemExit(1)
    finally:
        if runtime:runtime.stop()


if __name__=='__main__':main()
