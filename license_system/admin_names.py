"""Human-readable defaults for newly issued tool administrator accounts."""
import re
import unicodedata

from license_system.signatures import LicenseError


def customer_admin_name(customer):
    plain = unicodedata.normalize('NFD', customer.lower().replace('đ', 'd'))
    suffix = re.sub(r'[^a-z0-9]', '', plain) or 'khachhang'
    return 'quantri-' + suffix[:56]


def choose_admin_name(connection, customer, requested=''):
    """Caller holds the authority write lock; never rename an existing grant."""
    if requested:
        if connection.execute('SELECT 1 FROM licenses WHERE admin_username=?', (requested,)).fetchone():
            raise LicenseError('Tên quản trị này đã được cấp cho key khác. Chọn một tên khác để tránh trùng tài khoản.')
        return requested
    base = customer_admin_name(customer)
    name, number = base, 2
    while connection.execute('SELECT 1 FROM licenses WHERE admin_username=?', (name,)).fetchone():
        suffix = '-' + str(number)
        name = base[:64-len(suffix)] + suffix
        number += 1
    return name
