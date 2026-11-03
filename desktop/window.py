"""Native window shared by the separate desktop editions."""
import logging
import os
import sys
import threading


def show_error(message):
    if os.name=='nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,message,'ZaloFlow',0x10)
    else:print(message,file=sys.stderr)


def run_window(runtime,smoke=False,title='ZaloFlow'):
    import webview
    webview.settings['ALLOW_DOWNLOADS']=True
    logger=logging.getLogger('desktop')
    logger.info('Creating native window')
    window=webview.create_window(title,runtime.url,width=1440,height=940,min_size=(900,640),confirm_close=False)
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
            closing.set();window.set_title(title+' · Đang dừng, chờ lượt đang xử lý kết thúc…')
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

