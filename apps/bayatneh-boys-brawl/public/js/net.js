/**
 * Party networking.
 *
 * The server is only a relay — whoever created the room is the host and their
 * browser runs the fight. Everything below is transport plumbing:
 *
 *   party.send(payload)          broadcast to the room
 *   party.send(payload, peerId)  whisper to one player
 *   party.on('hit', handler)     listen for a message type
 */

export class Party {
  constructor() {
    this.ws = null;
    this.selfId = null;
    this.hostId = null;
    this.code = null;
    this.peers = new Map(); // id -> profile
    this.handlers = new Map();
    this.status = 'idle'; // idle | connecting | joined | closed | error
    this._intentionalClose = false;
  }

  get isHost() {
    return this.selfId != null && this.selfId === this.hostId;
  }

  /** Everyone in the room including me, in a stable order. */
  roster() {
    const list = [...this.peers.entries()].map(([id, profile]) => ({ id, profile }));
    list.sort((a, b) => (a.id < b.id ? -1 : 1));
    return list;
  }

  on(type, handler) {
    if (!this.handlers.has(type)) this.handlers.set(type, new Set());
    this.handlers.get(type).add(handler);
    return () => this.handlers.get(type)?.delete(handler);
  }

  emit(type, ...args) {
    // Copy first. A handler may tear itself down and register a replacement —
    // that is exactly what a rematch does — and iterating the live Set would
    // then run the brand new handler inside this same loop, forever.
    for (const handler of [...(this.handlers.get(type) || [])]) {
      try { handler(...args); } catch (err) { console.error('[party]', type, err); }
    }
  }

  socketUrl() {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    return `${scheme}://${location.host}/ws`;
  }

  /**
   * @param {{code?:string, profile:object}} options - no code means "make me a new room"
   */
  connect({ code = '', profile }) {
    this.disconnect();
    this._intentionalClose = false;
    this.status = 'connecting';

    return new Promise((resolve, reject) => {
      let settled = false;
      const fail = (message) => {
        if (settled) return;
        settled = true;
        this.status = 'error';
        reject(new Error(message));
      };

      let ws;
      try {
        ws = new WebSocket(this.socketUrl());
      } catch {
        fail('Could not reach the party server.');
        return;
      }
      this.ws = ws;

      const giveUp = setTimeout(() => { ws.close(); fail('The party server did not answer.'); }, 8000);

      ws.onopen = () => ws.send(JSON.stringify({ t: 'hello', code, profile }));

      ws.onmessage = (event) => {
        let msg;
        try { msg = JSON.parse(event.data); } catch { return; }

        if (msg.t === 'welcome') {
          clearTimeout(giveUp);
          settled = true;
          this.status = 'joined';
          this.selfId = msg.id;
          this.hostId = msg.hostId;
          this.code = msg.code;
          this.peers = new Map([[msg.id, profile]]);
          for (const peer of msg.peers) this.peers.set(peer.id, peer.profile);
          this.emit('roster', this.roster());
          resolve({ id: msg.id, code: msg.code, isHost: this.isHost });
          return;
        }

        if (msg.t === 'error') { clearTimeout(giveUp); ws.close(); fail(msg.message || 'Could not join.'); return; }

        if (msg.t === 'peer-join') {
          this.peers.set(msg.id, msg.profile);
          this.emit('roster', this.roster());
          this.emit('join', msg.id, msg.profile);
          return;
        }
        if (msg.t === 'peer-profile') {
          this.peers.set(msg.id, msg.profile);
          this.emit('roster', this.roster());
          return;
        }
        if (msg.t === 'peer-leave') {
          this.peers.delete(msg.id);
          this.emit('roster', this.roster());
          this.emit('leave', msg.id);
          return;
        }
        if (msg.t === 'host') {
          this.hostId = msg.id;
          this.emit('host', msg.id, this.isHost);
          return;
        }
        if (msg.t === 'relay' && msg.payload && msg.payload.type) {
          this.emit(msg.payload.type, msg.payload, msg.from);
        }
      };

      ws.onerror = () => fail('Could not reach the party server.');
      ws.onclose = () => {
        clearTimeout(giveUp);
        if (!settled) { fail('Connection closed before joining.'); return; }
        this.status = 'closed';
        if (!this._intentionalClose) this.emit('dropped');
      };
    });
  }

  updateProfile(profile) {
    if (this.selfId) this.peers.set(this.selfId, profile);
    this._raw({ t: 'profile', profile });
    this.emit('roster', this.roster());
  }

  send(payload, to = null) {
    this._raw({ t: 'relay', to, payload });
  }

  _raw(msg) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  disconnect() {
    this._intentionalClose = true;
    if (this.ws) { try { this.ws.close(); } catch { /* already gone */ } }
    this.ws = null;
    this.selfId = null;
    this.hostId = null;
    this.code = null;
    this.peers.clear();
    this.status = 'idle';
  }
}
