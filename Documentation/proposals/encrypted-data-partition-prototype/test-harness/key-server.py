#!/usr/bin/env python3
"""Minimal HTTPS key server for the encrypted data partition prototype.

Test fixture only (not a production key server). It serves one raw key to
clients presenting the right bearer token, over TLS with a self-signed
certificate that the client pins (ca.pem on the overlay).

  key-server.py --init <dir> --ip 10.0.2.2   create net.key, token, cert, url
  key-server.py --serve <dir> [--port 8443] [--deny]

--deny answers 403 to every request (simulates a revoked token).
Every request is logged to stdout with the result.
"""

import argparse
import datetime
import hmac
import http.server
import ipaddress
import os
import secrets
import ssl
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def init(directory: str, ip: str, port: int) -> None:
    os.makedirs(directory, mode=0o700, exist_ok=True)
    with open(os.path.join(directory, "net.key"), "wb") as f:
        f.write(secrets.token_bytes(64))
    with open(os.path.join(directory, "token"), "w") as f:
        f.write(secrets.token_urlsafe(32) + "\n")
    with open(os.path.join(directory, "url"), "w") as f:
        f.write(f"https://{ip}:{port}/key\n")

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "haos-key-server-test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=30))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(ip))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    with open(os.path.join(directory, "server.key"), "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    with open(os.path.join(directory, "ca.pem"), "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    for name in os.listdir(directory):
        os.chmod(os.path.join(directory, name), 0o600)
    print(f"initialised {directory}")


def serve(directory: str, port: int, deny: bool) -> None:
    with open(os.path.join(directory, "net.key"), "rb") as f:
        net_key = f.read()
    with open(os.path.join(directory, "token")) as f:
        token = f.read().strip()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            auth = self.headers.get("Authorization", "")
            ok_token = hmac.compare_digest(auth, f"Bearer {token}")
            if self.path != "/key":
                code = 404
            elif deny or not ok_token:
                code = 403
            else:
                code = 200
            self.send_response(code)
            if code == 200:
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(net_key)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(net_key)
            else:
                self.end_headers()
            print(f"{datetime.datetime.now(datetime.timezone.utc):%H:%M:%S} {self.client_address[0]} {self.path} -> {code}", flush=True)

        def log_message(self, *args) -> None:
            pass

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(os.path.join(directory, "ca.pem"), os.path.join(directory, "server.key"))
    httpd = http.server.HTTPServer(("0.0.0.0", port), Handler)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    print(f"serving on :{port} deny={deny}", flush=True)
    httpd.serve_forever()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--init")
    p.add_argument("--serve")
    p.add_argument("--ip", default="10.0.2.2")
    p.add_argument("--port", type=int, default=8443)
    p.add_argument("--deny", action="store_true")
    a = p.parse_args()
    if a.init:
        init(a.init, a.ip, a.port)
    elif a.serve:
        serve(a.serve, a.port, a.deny)
    else:
        p.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
