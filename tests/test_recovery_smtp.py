"""Exercise real smtplib against a disposable local TLS SMTP server."""
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
import ipaddress
import socketserver
import ssl
import threading

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import pytest

import email_recovery
from test_workflow import app


@pytest.mark.parametrize('security', ['starttls','ssl'])
def test_real_smtp_encrypts_authenticates_and_delivers_five_digits(app,tmp_path,monkeypatch,security):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
    now=datetime.now(timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
          .not_valid_after(now+timedelta(hours=1)).add_extension(x509.SubjectAlternativeName([
              x509.DNSName('localhost'),x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
          .sign(key,hashes.SHA256()))
    cert_path=tmp_path/'smtp.pem'; key_path=tmp_path/'smtp-key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    server_tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server_tls.load_cert_chain(cert_path,key_path)
    client_tls=ssl.create_default_context(cafile=str(cert_path))
    monkeypatch.setattr(email_recovery.ssl,'create_default_context',lambda:client_tls)
    messages=[];events=[]

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            connection=self.connection
            if security=='ssl':
                connection=server_tls.wrap_socket(connection,server_side=True)
            reader=connection.makefile('rb');encrypted=security=='ssl'
            def reply(value):
                connection.sendall(value.encode()+b'\r\n')
            reply('220 localhost ready')
            while True:
                line=reader.readline()
                if not line:
                    break
                command=line.decode().strip().split(' ',1)[0].upper()
                if command=='EHLO':
                    reply('250-localhost')
                    reply('250 AUTH PLAIN' if encrypted else '250 STARTTLS')
                elif command=='STARTTLS':
                    reply('220 Begin TLS')
                    reader.close();connection=server_tls.wrap_socket(connection,server_side=True)
                    reader=connection.makefile('rb');encrypted=True;events.append('tls')
                elif command=='AUTH':
                    assert encrypted
                    events.append('auth');reply('235 Authenticated')
                elif command in ('MAIL','RCPT'):
                    assert encrypted
                    reply('250 OK')
                elif command=='DATA':
                    reply('354 End with dot')
                    lines=[]
                    while (part:=reader.readline())!=b'.\r\n':
                        assert part
                        lines.append(part)
                    messages.append(BytesParser(policy=policy.default).parsebytes(b''.join(lines)))
                    reply('250 Accepted')
                elif command=='QUIT':
                    reply('221 Bye');break
                else:
                    reply('500 Unexpected command')
            reader.close();connection.close()

    with socketserver.TCPServer(('127.0.0.1',0),Handler) as server:
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        app.config.update(SMTP_HOST='127.0.0.1',SMTP_PORT=server.server_address[1],SMTP_SECURITY=security,
                          SMTP_USERNAME='sender@gmail.com',SMTP_PASSWORD='synthetic-app-password',SMTP_FROM='sender@gmail.com')
        try:
            email_recovery.deliver(app,'recipient@example.com','00007','reset')
            assert events.count('auth')==1
            assert len(messages)==1 and messages[0]['To']=='recipient@example.com'
            content=messages[0].get_content()
            assert '00007' in content and '10 phút' in content
            assert 'synthetic-app-password' not in messages[0].as_string()
        finally:
            server.shutdown();worker.join(timeout=3)
