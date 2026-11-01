"""VPS self-test using a disposable authority; never reads the real key store."""
import json
import tempfile
from pathlib import Path

from desktop.licensing import DesktopLicense
from license_system.authority import Authority
from license_system.server import create_app
from license_system.signatures import ActivationInvalid, LicenseError


def main():
    with tempfile.TemporaryDirectory(prefix='zaloflow-session-check-') as folder:
        root = Path(folder)
        authority = Authority(root/'synthetic-authority')
        config = authority.initialize('https://synthetic.invalid/licenses')
        http = create_app(authority.folder).test_client()
        key = authority.issue('Synthetic self-test only', mode='floating')['key']
        device_a = 'ZFM1-'+'A'*64
        device_b = 'ZFM1-'+'B'*64

        def transport(config, action, data):
            response = http.post('/v1/'+action, json=data)
            if response.status_code != 200:
                error = response.json.get('error', 'Self-test request failed')
                if response.json.get('error_code') == 'activation_invalid':
                    raise ActivationInvalid(error)
                raise LicenseError(error)
            return response.json

        def check(condition, message):
            if not condition:
                raise RuntimeError(message)

        def blocked(client):
            try:
                client.activate(key)
            except LicenseError as error:
                check('tool khác' in str(error), 'Unexpected activation denial')
                return
            raise RuntimeError('More than one tool was allowed')

        first = DesktopLicense(root/'tool-a', config, transport, device_a)
        second = DesktopLicense(root/'tool-b', config, transport, device_b)
        same_machine = DesktopLicense(root/'tool-c', config, transport, device_b)
        first.activate(key)
        check(first.allowed(), 'First tool was not activated')
        blocked(second)
        first.release_session()
        check(not first.allowed(), 'Closing tool did not disable local access')
        second.activate(key)
        check(second.allowed(), 'Key did not move to another machine')
        blocked(same_machine)
        second.release_session()
        check(first.refresh(force=True), 'Saved key did not resume after reopening')
        first.release_session()
        legacy = http.post('/v1/activate', json=dict(device=device_a, key=key))
        check(legacy.status_code == 403, 'Old client was given a floating lease')
        print(json.dumps(dict(ok=True, one_tool=True, same_machine_blocked=True,
            move_to_another_machine=True, saved_key_reopened=True,
            old_tool_rejected=True, real_license_store_untouched=True), indent=2))


if __name__ == '__main__':
    main()
