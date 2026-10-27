import base64
import json
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

PRODUCT = 'zaloflow-windows'


class LicenseError(ValueError):
    pass


class ActivationInvalid(LicenseError):
    """The authority explicitly confirms that this bearer session is inactive."""


def encode(value):
    return base64.urlsafe_b64encode(value).decode('ascii').rstrip('=')


def decode(value):
    try:
        return base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    except (ValueError, TypeError) as error:
        raise LicenseError('Key hoặc chữ ký không hợp lệ.') from error


def new_signer():
    return Ed25519PrivateKey.generate()


def public_text(signer):
    return encode(signer.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def sign(signer, claims):
    payload = json.dumps(claims, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return 'ZF1.' + encode(payload) + '.' + encode(signer.sign(payload))


def verify(token, public_key, device, now=None):
    now = time.time() if now is None else now
    try:
        if not isinstance(token, str) or len(token) > 8192:
            raise ValueError()
        prefix, payload_text, signature_text = token.split('.')
        if prefix != 'ZF1':
            raise ValueError()
        payload = decode(payload_text)
        Ed25519PublicKey.from_public_bytes(decode(public_key)).verify(decode(signature_text), payload)
        claims = json.loads(payload)
        if claims['product'] != PRODUCT or claims['device'] != device:
            raise LicenseError('Bản quyền không dành cho máy này.')
        for key in ('issued_at', 'valid_until', 'license_expires_at'):
            if type(claims[key]) is not int:
                raise ValueError()
        if claims['valid_until'] > claims['license_expires_at'] or claims['issued_at'] > now + 300:
            raise LicenseError('Thời gian bản quyền không hợp lệ. Kiểm tra ngày giờ Windows.')
        if now >= min(claims['valid_until'], claims['license_expires_at']):
            raise LicenseError('Bản quyền cần được kiểm tra lại hoặc đã hết hạn.')
        return claims
    except LicenseError:
        raise
    except (ValueError, TypeError, KeyError, InvalidSignature, UnicodeError) as error:
        raise LicenseError('Key hoặc chữ ký không hợp lệ.') from error
