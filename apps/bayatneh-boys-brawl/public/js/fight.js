/**
 * The rules of a bonk fight. No DOM in here on purpose — the same class runs
 * on one iPad for a couch fight, or on the host's device for a party, and both
 * cases render from the snapshots it produces.
 *
 * Nothing hurts. Everyone gets back up. Worst case you end up with swirly eyes.
 */

import { SPECIES } from './characters.js';

export const MOVES = {
  slap: { id: 'slap', name: 'SLAP', emoji: '\u{1F590}', damage: [7, 12], cooldown: 800, stun: 110, sfx: 'slap', pop: 'SLAP!', style: 'jab' },
  pie: { id: 'pie', name: 'PIE', emoji: '\u{1F967}', damage: [13, 19], cooldown: 3200, stun: 330, sfx: 'splat', pop: 'SPLAT!', style: 'throw' },
  fart: { id: 'fart', name: 'FART BLAST', emoji: '\u{1F4A8}', damage: [11, 18], cooldown: 5200, stun: 300, sfx: 'fart', pop: 'PFFFFT!', style: 'blast' }
};

export function signatureMove(speciesId) {
  const sig = SPECIES[speciesId].signature;
  return {
    id: 'signature',
    name: sig.name,
    emoji: sig.emoji,
    damage: sig.damage,
    cooldown: sig.cooldown,
    stun: 700,
    sfx: 'punch',
    pop: 'MEGA BONK!',
    style: 'charge',
    shout: sig.shout
  };
}

export function movesFor(speciesId) {
  return [MOVES.slap, MOVES.pie, MOVES.fart, signatureMove(speciesId)];
}

const START_HP = 140;
const BLOCK_DRAIN = 48;      // stamina per second while holding block
const STAMINA_REGEN = 24;    // stamina per second otherwise
const BLOCK_HIT_COST = 16;   // extra stamina for actually soaking a hit
const BLOCK_REDUCTION = 0.25;

export const SILLY_EVENTS = [
  { id: 'banana', emoji: '\u{1F34C}', text: '{name} slipped on a banana peel!', damage: 6, sfx: 'boing', stun: 500 },
  { id: 'cow', emoji: '\u{1F404}', text: 'A cow fell out of the sky onto {name}!', damage: 13, sfx: 'thud', stun: 700 },
  { id: 'pizza', emoji: '\u{1F355}', text: '{name} found a pizza and feels great!', heal: 18, sfx: 'ding' },
  { id: 'tickle', emoji: '\u{1FAB6}', text: 'A feather is tickling {name}!', stun: 1600, sfx: 'pop' },
  { id: 'bigheads', emoji: '\u{1F388}', text: 'BIG HEAD STORM! Everybody inflates!', global: 'bigheads', sfx: 'boing' },
  { id: 'sock', emoji: '\u{1F9E6}', text: 'A smelly sock landed on {name}. Gross.', damage: 8, sfx: 'splat', stun: 300 },
  { id: 'slowmo', emoji: '\u{1F40C}', text: 'SLOW MOTION! Everything goes floppy!', global: 'slowmo', sfx: 'boing' }
];

let fxSeq = 0;

export class Fight {
  /**
   * @param {{id:string, character:object}[]} entries
   * @param {{sillyEvents?:boolean}} [options]
   */
  constructor(entries, options = {}) {
    this.options = { sillyEvents: true, ...options };
    this.phase = 'countdown';
    this.countdown = 3200;
    this.clock = 0;
    this.nextSilly = 12000 + Math.random() * 6000;
    this.globalEffect = null;
    this.globalUntil = 0;
    this.winner = null;
    this.listeners = new Map();

    this.players = new Map();
    for (const entry of entries) {
      this.players.set(entry.id, {
        id: entry.id,
        character: entry.character,
        hp: START_HP,
        maxHp: START_HP,
        stamina: 100,
        blocking: false,
        stunUntil: 0,
        ko: false,
        mood: 'idle',
        moodUntil: 0,
        // Staggered so nobody can dump all four moves in the first two seconds.
        cooldowns: { pie: 2500, fart: 4500, signature: 6500 },
        target: null,
        hits: 0
      });
    }
    this.autoTargetEveryone();
  }

  on(type, handler) {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type).add(handler);
    return () => this.listeners.get(type)?.delete(handler);
  }

  emit(type, payload) {
    // Copied for the same reason as Party.emit: a listener is allowed to add
    // or remove listeners while it runs.
    for (const handler of [...(this.listeners.get(type) || [])]) handler(payload);
  }

  alive() {
    return [...this.players.values()].filter((p) => !p.ko);
  }

  opponentsOf(id) {
    return [...this.players.values()].filter((p) => p.id !== id && !p.ko);
  }

  autoTargetEveryone() {
    for (const player of this.players.values()) {
      const current = player.target && this.players.get(player.target);
      if (!current || current.ko) {
        player.target = this.opponentsOf(player.id)[0]?.id || null;
      }
    }
  }

  /* ------------------------------------------------------------- commands */

  setTarget(playerId, targetId) {
    const player = this.players.get(playerId);
    if (!player || player.ko) return;
    if (this.players.has(targetId) && targetId !== playerId) player.target = targetId;
  }

  setBlocking(playerId, on) {
    const player = this.players.get(playerId);
    if (!player || player.ko) return;
    player.blocking = Boolean(on) && player.stamina > 3;
  }

  /**
   * @returns {'ok'|'cooldown'|'stunned'|'blocking'|'no-target'|'not-fighting'}
   */
  attack(playerId, moveId) {
    if (this.phase !== 'fighting') return 'not-fighting';
    const player = this.players.get(playerId);
    if (!player || player.ko) return 'not-fighting';
    if (this.clock < player.stunUntil) return 'stunned';
    if (player.blocking) return 'blocking';

    const move = moveId === 'signature' ? signatureMove(player.character.species) : MOVES[moveId];
    if (!move) return 'not-fighting';
    if ((player.cooldowns[move.id] || 0) > this.clock) return 'cooldown';

    this.autoTargetEveryone();
    const target = player.target && this.players.get(player.target);
    if (!target || target.ko) return 'no-target';

    const speed = this.globalEffect === 'slowmo' ? 1.6 : 1;
    player.cooldowns[move.id] = this.clock + move.cooldown * speed;
    this.setMood(player, 'attack', 480);

    const [lo, hi] = move.damage;
    let damage = Math.round(lo + Math.random() * (hi - lo));
    let blocked = false;

    if (target.blocking && target.stamina > 0) {
      damage = Math.max(1, Math.round(damage * BLOCK_REDUCTION));
      target.stamina = Math.max(0, target.stamina - BLOCK_HIT_COST);
      if (target.stamina === 0) target.blocking = false;
      blocked = true;
    } else if (this.clock < target.stunUntil) {
      damage = Math.round(damage * 1.3);
    }

    target.hp = Math.max(0, target.hp - damage);
    target.hits++;
    if (!blocked) target.stunUntil = Math.max(target.stunUntil, this.clock + move.stun);
    this.setMood(target, blocked ? 'block' : 'hit', blocked ? 300 : 620);

    this.emit('fx', {
      seq: ++fxSeq,
      kind: 'hit',
      from: player.id,
      to: target.id,
      move: move.id,
      moveName: move.name,
      emoji: move.emoji,
      style: move.style,
      damage,
      blocked,
      pop: blocked ? 'BLOCKED!' : move.pop,
      sfx: blocked ? 'block' : move.sfx,
      shout: move.shout || null
    });

    if (target.hp === 0) this.knockOut(target, player);
    return 'ok';
  }

  knockOut(target, by) {
    target.ko = true;
    target.blocking = false;
    this.setMood(target, 'ko', 999999);
    this.emit('fx', { seq: ++fxSeq, kind: 'ko', to: target.id, from: by?.id || null, sfx: 'lose' });
    this.autoTargetEveryone();
    this.checkOver();
  }

  setMood(player, mood, ms) {
    // A knockout expression sticks. Nothing overrides swirly eyes.
    if (player.ko && mood !== 'ko') return;
    player.mood = mood;
    player.moodUntil = this.clock + ms;
  }

  checkOver() {
    if (this.phase === 'over') return;
    const standing = this.alive();
    if (standing.length <= 1) {
      this.phase = 'over';
      this.winner = standing[0]?.id || null;
      if (this.winner) this.setMood(this.players.get(this.winner), 'win', 999999);
      this.emit('over', { winner: this.winner });
    }
  }

  /* ----------------------------------------------------------------- tick */

  /** @param {number} dt milliseconds since the last tick */
  tick(dt) {
    if (this.phase === 'over') return;
    this.clock += dt;

    if (this.phase === 'countdown') {
      const before = Math.ceil(this.countdown / 1000);
      this.countdown -= dt;
      const after = Math.ceil(this.countdown / 1000);
      if (after !== before) this.emit('fx', { seq: ++fxSeq, kind: 'countdown', value: Math.max(0, after) });
      if (this.countdown <= 0) {
        this.phase = 'fighting';
        this.emit('fx', { seq: ++fxSeq, kind: 'start' });
      }
      return;
    }

    const seconds = dt / 1000;
    for (const player of this.players.values()) {
      if (player.ko) continue;
      if (player.blocking) {
        player.stamina = Math.max(0, player.stamina - BLOCK_DRAIN * seconds);
        if (player.stamina === 0) player.blocking = false;
      } else {
        player.stamina = Math.min(100, player.stamina + STAMINA_REGEN * seconds);
      }
      if (this.clock > player.moodUntil && player.mood !== 'idle') {
        player.mood = player.blocking ? 'block' : 'idle';
      }
      if (player.blocking) player.mood = 'block';
    }

    if (this.globalEffect && this.clock > this.globalUntil) this.globalEffect = null;

    if (this.options.sillyEvents && this.clock > this.nextSilly && this.alive().length > 1) {
      this.nextSilly = this.clock + 11000 + Math.random() * 8000;
      this.runSillyEvent();
    }
  }

  runSillyEvent() {
    const event = SILLY_EVENTS[Math.floor(Math.random() * SILLY_EVENTS.length)];
    const victims = this.alive();
    const victim = victims[Math.floor(Math.random() * victims.length)];

    if (event.global) {
      this.globalEffect = event.global;
      this.globalUntil = this.clock + 7000;
      this.emit('fx', { seq: ++fxSeq, kind: 'silly', event: event.id, emoji: event.emoji, text: event.text, sfx: event.sfx, global: event.global });
      return;
    }

    if (event.damage) {
      victim.hp = Math.max(0, victim.hp - event.damage);
      this.setMood(victim, 'hit', 700);
    }
    if (event.heal) {
      victim.hp = Math.min(victim.maxHp, victim.hp + event.heal);
      this.setMood(victim, 'win', 900);
    }
    if (event.stun) victim.stunUntil = Math.max(victim.stunUntil, this.clock + event.stun);

    this.emit('fx', {
      seq: ++fxSeq,
      kind: 'silly',
      event: event.id,
      emoji: event.emoji,
      to: victim.id,
      damage: event.damage || 0,
      heal: event.heal || 0,
      text: event.text.replace('{name}', victim.character.name),
      sfx: event.sfx
    });

    if (victim.hp === 0) this.knockOut(victim, null);
  }

  /* ------------------------------------------------------------ snapshots */

  snapshot() {
    return {
      phase: this.phase,
      clock: Math.round(this.clock),
      countdown: Math.max(0, Math.ceil(this.countdown / 1000)),
      globalEffect: this.globalEffect,
      winner: this.winner,
      players: [...this.players.values()].map((p) => ({
        id: p.id,
        hp: Math.round(p.hp),
        maxHp: p.maxHp,
        stamina: Math.round(p.stamina),
        blocking: p.blocking,
        stunned: this.clock < p.stunUntil,
        ko: p.ko,
        mood: p.mood,
        target: p.target,
        cooldowns: Object.fromEntries(
          Object.entries(p.cooldowns).map(([k, v]) => [k, Math.max(0, Math.round(v - this.clock))])
        )
      }))
    };
  }
}

/** What a non-host client keeps: the last snapshot, reshaped for rendering. */
export function readSnapshot(snapshot, charactersById) {
  return {
    phase: snapshot.phase,
    countdown: snapshot.countdown,
    globalEffect: snapshot.globalEffect,
    winner: snapshot.winner,
    players: snapshot.players.map((p) => ({ ...p, character: charactersById[p.id] }))
  };
}
