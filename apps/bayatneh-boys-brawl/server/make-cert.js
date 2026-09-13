'use strict';
/**
 * Makes a self-signed certificate for the LAN so browsers treat the game as a
 * "secure context" — which is the only way they'll hand over the microphone.
 *
 * The cert lists every LAN IP this machine currently has, so http://192.168.x.x
 * style addresses work without a hostname.
 */

const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const CERT_DIR = path.join(__dirname, '..', '.cert');

function lanAddresses() {
  const out = [];
  for (const list of Object.values(os.networkInterfaces())) {
    for (const net of list || []) {
      if (net.family === 'IPv4' && !net.internal) out.push(net.address);
    }
  }
  return out;
}

try {
  execFileSync('openssl', ['version'], { stdio: 'ignore' });
} catch {
  console.error('\n  openssl is not installed, so I can\'t make a certificate.');
  console.error('  The game still works over plain http — everything except');
  console.error('  microphone recording.\n');
  process.exit(1);
}

fs.mkdirSync(CERT_DIR, { recursive: true });

const names = ['DNS:localhost', 'IP:127.0.0.1', ...lanAddresses().map((ip) => `IP:${ip}`)];

execFileSync('openssl', [
  'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-sha256', '-days', '825',
  '-keyout', path.join(CERT_DIR, 'key.pem'),
  '-out', path.join(CERT_DIR, 'cert.pem'),
  '-subj', '/CN=Bayatneh Boys Brawl',
  '-addext', `subjectAltName=${names.join(',')}`
], { stdio: 'inherit' });

console.log('');
console.log('  Certificate written to .cert/');
console.log('  Covers: ' + names.join(', '));
console.log('');
console.log('  Now run:  npm run start:https');
console.log('  Each device will warn once that the site is "not private" —');
console.log('  that is expected for a home-made certificate. See the README.');
console.log('');
