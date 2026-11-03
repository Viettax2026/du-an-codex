"""The separately packaged local edition. No license client is constructed."""
import os
from pathlib import Path

from desktop.runtime import DesktopRuntime


def default_local_data_root():
    base = Path(os.environ.get('LOCALAPPDATA') or Path.home()/'.local'/'share')
    return base/'ZaloFlowLocal'


class LocalDesktopRuntime(DesktopRuntime):
    requires_license = False

    def __init__(self, data_root=None, config=None, tick=None):
        super().__init__(data_root or default_local_data_root(), config=config, tick=tick)
        self.app.extensions['desktop_local'] = True
        self.app.config['RECOVERY_TRUST_LOCAL_PROXY'] = False

        @self.app.context_processor
        def local_context():
            return dict(desktop_local_enabled=True)
