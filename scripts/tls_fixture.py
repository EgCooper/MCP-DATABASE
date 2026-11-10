"""Create ephemeral TLS test certificates; never use these keys in production."""

import argparse
import os
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory', type=Path)
args = parser.parse_args()
args.directory.mkdir(parents=True, mode=0o755, exist_ok=False)
root = args.directory.resolve()

def run(*argv):
    subprocess.run(['openssl', *argv], cwd=root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

for name in ('ca', 'wrong-ca'):
    run('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '2', '-subj', '/CN=Ephemeral Acceptance CA',
        '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign',
        '-addext', 'subjectKeyIdentifier=hash', '-keyout', name + '.key', '-out', name + '.crt')
run('req', '-newkey', 'rsa:2048', '-nodes', '-subj', '/CN=localhost', '-keyout', 'server.key', '-out', 'server.csr')
(root/'server.ext').write_text('subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n'
    'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nauthorityKeyIdentifier=keyid,issuer\n')
run('x509', '-req', '-in', 'server.csr', '-CA', 'ca.crt', '-CAkey', 'ca.key', '-CAcreateserial',
    '-days', '2', '-extfile', 'server.ext', '-out', 'server.crt')
# Directory must be mounted below a private host parent. The DB container UID
# needs read access to its disposable server key; CA private keys stay host-only.
os.chmod(root/'server.key', 0o644)
print('Ephemeral certificates created; mount server.key/server.crt/ca.crt in the disposable DB only.')
