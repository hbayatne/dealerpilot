'use strict';
/**
 * BONK BROS party server.
 *
 * Two jobs, both small:
 *   1. Serve the static game out of ../public
 *   2. Relay websocket messages between everyone in the same 4-letter room
 *
 * The server is a dumb pipe on purpose. The player who made the room is the
 * "host" and their browser runs the actual fight simulation, so the rules live
 * in one place (public/js/arena.js) no matter how the players are connected.
 */

const http = require('http');
const https = require('https');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { WebSocketServer } = require('ws');

const PUBLIC_DIR = path.join(__dirname, '..', 'public');
const CERT_DIR = path.join(__dirname, '..', '.cert');
const PORT = Number(process.env.PORT) || 8080;
const USE_HTTPS = process.argv.includes('--https');
const MAX_PER_ROOM = 6;

/* ------------------------------------------------------------------ static */

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon',
  '.webmanifest': 'application/manifest+json'
};

function serveStatic(req, res) {
  const url = new URL(req.url, 'http://x');
  let rel = decodeURIComponent(url.pathname);
  if (rel === '/' || rel === '') rel = '/index.html';

  // Resolve inside PUBLIC_DIR only. Anything that escapes is a 403.
  const abs = path.resolve(PUBLIC_DIR, '.' + rel);
  if (abs !== PUBLIC_DIR && !abs.startsWith(PUBLIC_DIR + path.sep)) {
    res.writeHead(403).end('nope');
    return;
  }

  fs.readFile(abs, (err, buf) => {
    if (err) {
      res.writeHead(404, { 'content-type': 'text/plain' }).end('404');
      return;
    }
    res.writeHead(200, {
      'content-type': MIME[path.extname(abs).toLowerCase()] || 'application/octet-stream',
      'cache-control': 'no-cache'
    }).end(buf);
  });
}

/* ------------------------------------------------------------------- rooms */

/** @type {Map<string, {code:string, hostId:string, clients:Map<string,object>}>} */
const rooms = new Map();

// No O/0/I/1 — a 5 year old has to read these off a screen.
const CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';

function makeCode() {
  for (let attempt = 0; attempt < 200; attempt++) {
    let code = '';
    for (let i = 0; i < 4; i++) {
      code += CODE_ALPHABET[Math.floor(Math.random() * CODE_ALPHABET.length)];
    }
    if (!rooms.has(code)) return code;
  }
  throw new Error('room codes exhausted');
}

let nextClientId = 1;

function send(ws, msg) {
  if (ws.readyState === ws.OPEN) ws.send(JSON.stringify(msg));
}

function broadcast(room, msg, exceptId) {
  for (const client of room.clients.values()) {
    if (client.id !== exceptId) send(client.ws, msg);
  }
}

function roster(room) {
  return [...room.clients.values()].map((c) => ({ id: c.id, profile: c.profile }));
}

function leave(client) {
  const room = rooms.get(client.code);
  if (!room) return;
  room.clients.delete(client.id);

  if (room.clients.size === 0) {
    rooms.delete(room.code);
    return;
  }
  // Host walked off with the laptop — promote whoever has been here longest.
  if (room.hostId === client.id) {
    room.hostId = room.clients.keys().next().value;
    broadcast(room, { t: 'host', id: room.hostId });
  }
  broadcast(room, { t: 'peer-leave', id: client.id });
}

/* -------------------------------------------------------------- ws handling */

function handleMessage(client, raw) {
  let msg;
  try {
    msg = JSON.parse(raw);
  } catch {
    return;
  }
  if (!msg || typeof msg.t !== 'string') return;

  if (msg.t === 'hello') {
    if (client.code) return; // already seated
    const wanted = String(msg.code || '').toUpperCase().trim();
    client.profile = msg.profile || {};

    let room;
    if (!wanted) {
      room = { code: makeCode(), hostId: client.id, clients: new Map() };
      rooms.set(room.code, room);
    } else {
      room = rooms.get(wanted);
      if (!room) {
        send(client.ws, { t: 'error', code: 'no-room', message: `No party called ${wanted}` });
        return;
      }
      if (room.clients.size >= MAX_PER_ROOM) {
        send(client.ws, { t: 'error', code: 'full', message: 'That party is full!' });
        return;
      }
    }

    client.code = room.code;
    room.clients.set(client.id, client);

    send(client.ws, {
      t: 'welcome',
      id: client.id,
      code: room.code,
      hostId: room.hostId,
      peers: roster(room).filter((p) => p.id !== client.id)
    });
    broadcast(room, { t: 'peer-join', id: client.id, profile: client.profile }, client.id);
    return;
  }

  const room = rooms.get(client.code);
  if (!room) return;

  if (msg.t === 'profile') {
    client.profile = msg.profile || {};
    broadcast(room, { t: 'peer-profile', id: client.id, profile: client.profile }, client.id);
    return;
  }

  if (msg.t === 'relay') {
    const out = { t: 'relay', from: client.id, payload: msg.payload };
    if (msg.to) {
      const target = room.clients.get(msg.to);
      if (target) send(target.ws, out);
    } else {
      broadcast(room, out, client.id);
    }
  }
}

/* -------------------------------------------------------------------- boot */

function createServer() {
  if (!USE_HTTPS) return http.createServer(serveStatic);

  const key = path.join(CERT_DIR, 'key.pem');
  const cert = path.join(CERT_DIR, 'cert.pem');
  if (!fs.existsSync(key) || !fs.existsSync(cert)) {
    console.error('\n  No certificate found. Run:  npm run cert\n');
    process.exit(1);
  }
  return https.createServer({ key: fs.readFileSync(key), cert: fs.readFileSync(cert) }, serveStatic);
}

const server = createServer();
const wss = new WebSocketServer({ server, path: '/ws', maxPayload: 8 * 1024 * 1024 });

wss.on('connection', (ws) => {
  const client = { id: 'p' + nextClientId++, ws, code: null, profile: {} };
  ws.isAlive = true;
  ws.on('pong', () => { ws.isAlive = true; });
  ws.on('message', (raw) => handleMessage(client, raw));
  ws.on('close', () => leave(client));
  ws.on('error', () => leave(client));
});

// Phones sleep, wifi drops, sockets go quiet without closing. Reap the dead.
const heartbeat = setInterval(() => {
  for (const ws of wss.clients) {
    if (!ws.isAlive) { ws.terminate(); continue; }
    ws.isAlive = false;
    ws.ping();
  }
}, 30000);
wss.on('close', () => clearInterval(heartbeat));

function lanAddresses() {
  const out = [];
  for (const list of Object.values(os.networkInterfaces())) {
    for (const net of list || []) {
      if (net.family === 'IPv4' && !net.internal) out.push(net.address);
    }
  }
  return out;
}

server.listen(PORT, () => {
  const scheme = USE_HTTPS ? 'https' : 'http';
  const addresses = lanAddresses();
  console.log('');
  console.log('  ####  BONK BROS is up  ####');
  console.log('');
  console.log(`  This device : ${scheme}://localhost:${PORT}`);
  for (const ip of addresses) {
    console.log(`  Kids' iPads : ${scheme}://${ip}:${PORT}`);
  }
  if (!addresses.length) console.log('  (no LAN address found — is wifi on?)');
  if (!USE_HTTPS) {
    console.log('');
    console.log('  Voice recording needs https. Run `npm run cert` then `npm run start:https`.');
  }
  console.log('');
});
