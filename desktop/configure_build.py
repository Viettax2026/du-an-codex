"""Accept only PUBLIC authority configuration, never private signing material."""
import json
import os
from pathlib import Path

from desktop.licensing import CONFIG_PATH, load_config


def main():
    raw = os.environ.get('ZALOFLOW_CLIENT_CONFIG', '').strip()
    if raw:
        data = json.loads(raw)
        if set(data) != {'version', 'server_url', 'public_key'}:
            raise ValueError('Only the public client-config.json may be passed to the build.')
        CONFIG_PATH.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    configured = CONFIG_PATH.is_file()
    config = None
    if configured:
        config = load_config()
    else:
        print('::notice::Windows license tests can run, but no customer package will be published until client-config.json is supplied.')
    Path(__file__).with_name('license_identity.py').write_text(
        '# Generated public publisher identity; no private signing material.\nCLIENT_CONFIG = ' + repr(config) + '\n', encoding='utf-8')
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as file:
            file.write('configured=' + str(configured).lower() + '\n')


if __name__ == '__main__':
    main()
