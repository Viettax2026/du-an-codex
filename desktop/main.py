"""Native Windows window; no server or schedule service is installed."""
import argparse
import faulthandler
import json
import logging
import os
import sys
import tempfile
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.request import urlopen

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from desktop.runtime import DesktopRuntime,default_data_root
from desktop.windows_job import protect_process_tree


def show_error(message):
    if os.name=='nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,message,'ZaloFlow',0x10)
    else:print(message,file=sys.stderr)


def run_window(runtime,smoke=False):
    import webview
    webview.settings['ALLOW_DOWNLOADS']=True
    logger=logging.getLogger('desktop')
    logger.info('Creating native window')
    window=webview.create_window('ZaloFlow',runtime.url,width=1440,height=940,min_size=(900,640),confirm_close=False)
    closing=threading.Event();ready_to_close=threading.Event();loaded=threading.Event()
    def on_shown():
        logger.info('Native window shown')
        try:runtime.activate()
        except Exception:
            logging.getLogger('desktop').exception('Cannot start local scheduler')
            show_error('Không bật được bộ chạy chiến dịch. Có thể tool hoặc bộ lịch đang mở ở nơi khác. Đóng rồi mở lại tool.')
            on_closing()
    def drain():
        logger.info('Draining local runtime')
        runtime.stop();ready_to_close.set()
        logger.info('Destroying native window')
        window.destroy()
    def on_closing():
        if ready_to_close.is_set():return True
        runtime.begin_stop()
        if not closing.is_set():
            closing.set();window.set_title('ZaloFlow · Đang dừng, chờ lượt đang xử lý kết thúc…')
            threading.Thread(target=drain,name='ZaloFlow-close',daemon=True).start()
        return False
    def on_loaded():
        logger.info('Native window loaded')
        loaded.set()
        if smoke:on_closing()
    window.events.shown+=on_shown;window.events.closing+=on_closing;window.events.loaded+=on_loaded
    try:
        webview.start(gui='edgechromium' if os.name=='nt' else None,debug=False,private_mode=False,storage_path=str(runtime.data_root/'webview'))
    finally:runtime.stop()
    if smoke and not loaded.is_set():raise RuntimeError('The Windows webview did not load the local application')


def smoke_check(report,gui=False):
    from desktop.licensing import DesktopLicense
    from license_system.signatures import PRODUCT, new_signer, public_text, sign
    # Persistent WebView2 profiles can retain a cache file until process exit.
    # These are disposable test profiles; the process job closes any remaining
    # browser children on exit. Normal user profiles are never removed here.
    with tempfile.TemporaryDirectory(prefix='zaloflow-smoke-',ignore_cleanup_errors=True) as folder:
        signer=new_signer();device='ZFM1-'+'A'*64
        def transport(config,action,data):
            now=int(time.time())
            lease=sign(signer,dict(product=PRODUCT,license_id=1,customer='Smoke test only',activation_id=1,
                device=device,issued_at=now,valid_until=now+3600,license_expires_at=now+86400))
            return dict(lease=lease,activation_token='temporary-smoke-activation-token')
        license=DesktopLicense(Path(folder)/'license',config=dict(server_url='https://smoke.invalid',public_key=public_text(signer)),transport=transport,device=device)
        runtime=DesktopRuntime(folder,license=license)
        try:
            runtime.start()
            with urlopen(runtime.url+'/register',timeout=10) as response:assert response.url.endswith('/desktop/license')
            license.activate('ZF-'+'a'*32)
            assert license.allowed(),'Signed activation was not accepted'
            with urlopen(runtime.url+'/login',timeout=10) as response:assert response.status==200
            assert runtime.app.extensions['zalo_connector'].available(),'Missing bundled Node.js or Zalo SDK'
            if gui:run_window(runtime,smoke=True)
            else:
                runtime.activate();deadline=time.monotonic()+10
                heartbeat=Path(runtime.app.config['DATABASE']).with_suffix('.scheduler.heartbeat')
                while not heartbeat.exists() and time.monotonic()<deadline:time.sleep(.05)
                assert heartbeat.exists(),'Local scheduler did not start'
                assert runtime.stop(timeout=10),'Local runtime did not close'
            Path(report).write_text(json.dumps(dict(ok=True,gui=gui,stopped=runtime.closed.is_set(),node_available=True,licensed=True)),encoding='utf-8')
        finally:runtime.stop()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir');parser.add_argument('--smoke-test',action='store_true');parser.add_argument('--smoke-gui',action='store_true');parser.add_argument('--smoke-report')
    args=parser.parse_args();protect_process_tree()
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
        if not runtime.app.extensions['zalo_connector'].available():raise RuntimeError('Thiếu bộ kết nối. Giải nén đầy đủ gói Windows, giữ thư mục _internal cạnh ZaloFlow.exe.')
        runtime.start();run_window(runtime)
    except Exception as error:
        logging.getLogger('desktop').exception('Desktop startup failed')
        message=str(error) if isinstance(error,RuntimeError) and str(error).startswith(('Bộ chạy','Thiếu bộ kết nối')) else 'Không mở được ZaloFlow. Kiểm tra Microsoft Edge WebView2 Runtime và xem desktop.log trong thư mục dữ liệu.'
        show_error(message)
        raise SystemExit(1)
    finally:
        if runtime:runtime.stop()


if __name__=='__main__':main()
