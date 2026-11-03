"""Entry point built only into the separate local edition."""
import argparse
import faulthandler
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from desktop.local_runtime import LocalDesktopRuntime,default_local_data_root
from desktop.window import run_window,show_error
from desktop.windows_job import protect_process_tree


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir');parser.add_argument('--smoke-test',action='store_true')
    parser.add_argument('--smoke-gui',action='store_true');parser.add_argument('--smoke-report')
    support=parser.add_mutually_exclusive_group()
    support.add_argument('--support-recovery',metavar='USERNAME')
    support.add_argument('--grant-account-admin',metavar='USERNAME')
    args=parser.parse_args();protect_process_tree()
    if args.support_recovery or args.grant_account_admin:
        from desktop.recovery import account_admin_dialog,recovery_dialog
        action=account_admin_dialog if args.grant_account_admin else recovery_dialog
        try:action(args.data_dir or default_local_data_root(),args.grant_account_admin or args.support_recovery)
        except Exception as error:
            show_error(str(error) if isinstance(error,RuntimeError) else 'Không thực hiện được hỗ trợ tài khoản. Đóng ZaloFlow Local rồi thử lại.')
            raise SystemExit(1)
        return
    if args.smoke_test:
        if not args.smoke_report:parser.error('--smoke-report is required')
        with open(args.smoke_report+'.log','w',encoding='utf-8') as diagnostic:
            logging.basicConfig(stream=diagnostic,level=logging.INFO,force=True)
            faulthandler.enable(diagnostic);faulthandler.dump_traceback_later(45,repeat=True,file=diagnostic)
            try:
                from desktop.local_smoke import smoke_check
                smoke_check(args.smoke_report,args.smoke_gui)
            except BaseException:
                logging.getLogger('desktop').exception('Local packaged smoke test failed')
                raise SystemExit(1)
            finally:faulthandler.cancel_dump_traceback_later()
        return
    root=Path(args.data_dir or default_local_data_root());root.mkdir(parents=True,exist_ok=True)
    log=RotatingFileHandler(root/'desktop.log',maxBytes=2_000_000,backupCount=2,encoding='utf-8')
    logging.basicConfig(handlers=[log],level=logging.WARNING,format='%(asctime)s %(levelname)s %(message)s')
    runtime=None
    try:
        runtime=LocalDesktopRuntime(root)
        if not runtime.app.extensions['zalo_connector'].available():raise RuntimeError('Thiếu bộ kết nối. Chạy lại bộ cài ZaloFlow Local để khôi phục tệp chương trình.')
        runtime.start();run_window(runtime,title='ZaloFlow Local')
    except Exception as error:
        logging.getLogger('desktop').exception('Local desktop startup failed')
        show_error(str(error) if isinstance(error,RuntimeError) and str(error).startswith('Thiếu bộ kết nối') else
            'Không mở được ZaloFlow Local. Kiểm tra Microsoft Edge WebView2 Runtime và xem desktop.log trong thư mục dữ liệu.')
        raise SystemExit(1)
    finally:
        if runtime:runtime.stop()


if __name__=='__main__':main()
