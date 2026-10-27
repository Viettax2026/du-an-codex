# Windows build only. Customer databases, media and QR credentials are excluded.
import shutil
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files,collect_submodules

root=Path(SPECPATH).parent
node=shutil.which('node')
if not node:raise RuntimeError('Install Node.js before building')
datas=[(str(root/'templates'),'templates'),(str(root/'static'),'static'),
       (str(root/'connector'),'connector')]+collect_data_files('webview')+collect_data_files('tzdata')
license_config=root/'desktop'/'license-config.json'
if license_config.is_file():datas.append((str(license_config),'desktop'))
a=Analysis([str(root/'desktop'/'main.py')],pathex=[str(root)],
    binaries=[(node,'runtime')],datas=datas,
    hiddenimports=['webview.platforms.winforms','webview.platforms.edgechromium','webview.platforms.mshtml']+collect_submodules('waitress'),
    excludes=['PyQt5','PyQt6','PySide2','PySide6','gi','cefpython3','license_system.admin','license_system.authority','license_system.server','license_system.web_admin'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='ZaloFlow',console=False,debug=False,disable_windowed_traceback=True)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='ZaloFlow')
