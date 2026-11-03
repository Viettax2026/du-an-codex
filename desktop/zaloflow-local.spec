# Separate owner-authorized edition; no authority client or identity is bundled.
import shutil
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files,collect_submodules

root=Path(SPECPATH).parent
node=shutil.which('node')
if not node:raise RuntimeError('Install Node.js before building')
datas=[(str(root/'templates'),'templates'),(str(root/'static'),'static'),
       (str(root/'connector'),'connector')]+collect_data_files('webview')+collect_data_files('tzdata')
a=Analysis([str(root/'desktop'/'local_main.py')],pathex=[str(root)],
    binaries=[(node,'runtime')],datas=datas,
    hiddenimports=['webview.platforms.winforms','webview.platforms.edgechromium','webview.platforms.mshtml']+collect_submodules('waitress'),
    excludes=['PyQt5','PyQt6','PySide2','PySide6','gi','cefpython3','license_system',
        'desktop.main','desktop.licensing','desktop.license_routes','desktop.license_identity',
        'desktop.admin_accounts','desktop.configure_build','desktop.privacy_audit','legacy_web_accounts'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='ZaloFlow',console=False,debug=False,disable_windowed_traceback=True,
        icon=str(root/'desktop'/'assets'/'zaloflow.ico'))
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='ZaloFlowLocal')
