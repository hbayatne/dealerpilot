/**
 * The arena screen: draws the fighters, plays the slapstick, and owns the
 * control pads.
 *
 * In a couch fight this device runs the Fight itself. In a party, only the
 * host runs it — everyone else drives a copy of the last snapshot the host
 * sent, and forwards their button presses upstream.
 */

import { renderGoof, renderHead, SPECIES } from './characters.js';
import { Fight, movesFor, readSnapshot } from './fight.js';
import { h, clear, popText, confetti, shake, toast } from './ui.js';
import { play } from './sfx.js';
import { playClip, speak, startRecording, blobToDataUrl, canRecord } from './voice.js';

const COMMENTARY = [
  'Ooooooh that had to sting!',
  'Right in the snack hole!',
  'Somebody call a grown-up!',
  'That was a LOT of noise.',
  'He is going to remember that one.',
  'BONK delivered!',
  'Straight to the noggin!'
];

const SEATS = {
  2: [25, 75],
  3: [16, 50, 84],
  4: [12, 37, 63, 88],
  5: [10, 30, 50, 70, 90],
  6: [8, 24, 42, 58, 76, 92]
};

export class Arena {
  /**
   * @param {object} options
   * @param {HTMLElement} options.mount
   * @param {{id:string, character:object}[]} options.entries
   * @param {string[]} options.controls    player ids this device drives
   * @param {import('./net.js').Party|null} options.party
   * @param {boolean} options.isHost
   * @param {() => void} options.onExit
   * @param {() => void} [options.onRematch]
   */
  constructor(options) {
    this.opt = options;
    this.entries = options.entries;
    this.controls = options.controls;
    this.party = options.party || null;
    this.isHost = options.isHost;
    this.charactersById = Object.fromEntries(this.entries.map((e) => [e.id, e.character]));

    this.fight = this.isHost ? new Fight(this.entries) : null;
    this.bots = new Map(this.entries.filter((e) => e.bot).map((e) => [e.id, { next: 2000 }]));
    this.view = null;          // last snapshot, reshaped for rendering
    this.seenFx = new Set();
    this.lastMood = new Map();
    this.talkLevel = new Map();
    this.running = true;
    this.unsubscribes = [];

    this.build();

    if (this.fight) {
      this.fight.on('fx', (fx) => {
        this.handleFx(fx);
        this.party?.send({ type: 'fx', fx });
      });
      this.fight.on('over', () => this.pushState());
    }

    if (this.party) this.wireParty();

    this.lastFrame = performance.now();
    this.lastPush = 0;
    this.frame = requestAnimationFrame(this.loop);
  }

  /* ----------------------------------------------------------------- DOM */

  build() {
    const mount = clear(this.opt.mount);

    this.hpRow = h('div', { class: 'hp-row' });
    this.stage = h('div', { class: 'stage' });
    this.announcer = h('div', { class: 'announcer' });
    this.pads = h('div', { class: 'pads' });
    this.countdownEl = h('div', { class: 'countdown' });

    this.fighters = new Map();
    this.bars = new Map();

    const seats = SEATS[this.entries.length] || SEATS[4];
    this.entries.forEach((entry, index) => {
      const left = seats[index] ?? 50;
      const facing = left <= 50 ? 1 : -1;
      const fx = h('div', { class: 'fighter-fx' });
      const art = h('div', { class: 'fighter-art' });
      const node = h('div', {
        class: 'fighter',
        dataset: { id: entry.id },
        style: { left: `${left}%` }
      }, fx, art, h('div', { class: 'fighter-tag' }, entry.character.name));
      this.stage.append(node);
      this.fighters.set(entry.id, { node, art, fx, facing, left });

      const bar = h('div', { class: 'hp-fill' });
      const stam = h('div', { class: 'stam-fill' });
      const head = h('div', { class: 'hp-head', html: renderHead(entry.character) });
      const card = h('div', { class: 'hp-card', dataset: { id: entry.id } },
        head,
        h('div', { class: 'hp-meta' },
          h('div', { class: 'hp-name' }, entry.character.name),
          h('div', { class: 'hp-bar' }, bar),
          h('div', { class: 'stam-bar' }, stam))
      );
      this.hpRow.append(card);
      this.bars.set(entry.id, { bar, stam, card, head });
    });

    for (const id of this.controls) this.pads.append(this.buildPad(id));
    this.pads.dataset.count = String(this.controls.length);

    mount.append(
      h('div', { class: 'arena', dataset: { players: String(this.entries.length) } },
        this.hpRow,
        h('div', { class: 'stage-wrap' }, this.stage, this.announcer, this.countdownEl),
        this.pads,
        h('button', { class: 'quit-btn', onclick: () => this.confirmExit() }, '\u{2716}')
      )
    );

    this.renderAllGoofs();
  }

  buildPad(playerId) {
    const character = this.charactersById[playerId];
    const moves = movesFor(character.species);
    const pad = h('div', { class: 'pad', dataset: { id: playerId } });
    const buttons = new Map();

    const targetRow = h('div', { class: 'target-row' });
    const showTargets = this.entries.length > 2;
    if (showTargets) {
      for (const entry of this.entries) {
        if (entry.id === playerId) continue;
        const btn = h('button', {
          class: 'target-btn',
          dataset: { id: entry.id },
          html: renderHead(entry.character),
          onclick: () => this.setTarget(playerId, entry.id)
        });
        targetRow.append(btn);
      }
    }

    const moveGrid = h('div', { class: 'move-grid' });
    for (const move of moves) {
      const sweep = h('div', { class: 'cd-sweep' });
      const btn = h('button', {
        class: `move-btn move-${move.id}`,
        onclick: () => this.doAttack(playerId, move.id)
      }, sweep, h('span', { class: 'move-emoji' }, move.emoji), h('span', { class: 'move-name' }, move.name));
      moveGrid.append(btn);
      buttons.set(move.id, { btn, sweep, move });
    }

    const blockBtn = h('button', { class: 'block-btn' }, '\u{1F6E1}\u{FE0F}', h('span', {}, 'HOLD TO BLOCK'));
    const holdOn = (e) => { e.preventDefault(); this.setBlocking(playerId, true); };
    const holdOff = () => this.setBlocking(playerId, false);
    blockBtn.addEventListener('pointerdown', holdOn);
    blockBtn.addEventListener('pointerup', holdOff);
    blockBtn.addEventListener('pointercancel', holdOff);
    blockBtn.addEventListener('pointerleave', holdOff);

    const tauntBtn = h('button', { class: 'taunt-btn' }, '\u{1F4E2}', h('span', {}, canRecord() ? 'TAUNT · hold to record' : 'TAUNT'));
    this.wireTaunt(tauntBtn, playerId);

    pad.append(...[
      h('div', { class: 'pad-name' }, `${SPECIES[character.species].emoji} ${character.name}`),
      showTargets ? h('div', { class: 'pad-label' }, 'Who are you bonking?') : null,
      showTargets ? targetRow : null,
      moveGrid,
      h('div', { class: 'pad-bottom' }, blockBtn, tauntBtn)
    ].filter(Boolean));

    pad._buttons = buttons;
    pad._targetRow = targetRow;
    return pad;
  }

  /**
   * Tap speaks the catchphrase, hold records a real voice clip and sends it to
   * everybody in the room. That is the Talking Tom bit, in the middle of a fight.
   */
  wireTaunt(button, playerId) {
    let holdTimer = null;
    let recorder = null;
    let recording = false;

    const startHold = (e) => {
      e.preventDefault();
      holdTimer = setTimeout(async () => {
        if (!canRecord()) return;
        try {
          recording = true;
          button.classList.add('is-recording');
          recorder = await startRecording(async (blob) => {
            recording = false;
            button.classList.remove('is-recording');
            if (!blob) return;
            const clip = await blobToDataUrl(blob);
            this.broadcastVoice(playerId, clip);
          });
        } catch {
          recording = false;
          button.classList.remove('is-recording');
          toast('The microphone said no.', '\u{1F3A4}');
        }
      }, 260);
    };

    const endHold = () => {
      clearTimeout(holdTimer);
      if (recording && recorder) {
        recorder.stop();
      } else if (!recording) {
        this.broadcastSay(playerId);
      }
    };

    button.addEventListener('pointerdown', startHold);
    button.addEventListener('pointerup', endHold);
    button.addEventListener('pointercancel', () => { clearTimeout(holdTimer); recorder?.stop(); });
  }

  /* ------------------------------------------------------------- networking */

  wireParty() {
    const add = (type, fn) => this.unsubscribes.push(this.party.on(type, fn));

    if (this.isHost) {
      add('input', (msg, from) => this.fight?.attack(from, msg.move));
      add('target', (msg, from) => this.fight?.setTarget(from, msg.targetId));
      add('block', (msg, from) => this.fight?.setBlocking(from, msg.on));
      add('leave', (id) => {
        const player = this.fight?.players.get(id);
        if (player && !player.ko) this.fight.knockOut(player, null);
      });
    } else {
      add('state', (msg) => { this.view = readSnapshot(msg.snapshot, this.charactersById); });
      add('fx', (msg) => this.handleFx(msg.fx));
    }

    add('voice', (msg, from) => this.playVoiceFrom(from, msg.clip));
    add('say', (msg, from) => this.sayFrom(from, msg.text));
    add('rematch', () => this.opt.onRematch?.());
    add('host', () => {
      // The host's browser was running the fight. Without it there is no
      // fight left to watch, so bail out rather than freeze on the last frame.
      if (!this.fight) {
        toast('The host left, so that fight is over.', '\u{1F44B}');
        this.exit();
      }
    });
    add('dropped', () => {
      toast('Lost the party connection.', '\u{1F4F5}');
      this.exit();
    });
  }

  pushState() {
    if (!this.isHost || !this.party || !this.fight) return;
    this.party.send({ type: 'state', snapshot: this.fight.snapshot() });
  }

  doAttack(playerId, moveId) {
    if (this.isHost) {
      const result = this.fight.attack(playerId, moveId);
      if (result === 'cooldown' || result === 'stunned') play('no');
    } else {
      this.party?.send({ type: 'input', move: moveId }, this.party.hostId);
    }
  }

  setTarget(playerId, targetId) {
    play('select');
    if (this.isHost) this.fight.setTarget(playerId, targetId);
    else this.party?.send({ type: 'target', targetId }, this.party.hostId);
  }

  setBlocking(playerId, on) {
    if (this.isHost) this.fight.setBlocking(playerId, on);
    else this.party?.send({ type: 'block', on }, this.party.hostId);
  }

  broadcastVoice(playerId, clip) {
    this.playVoiceFrom(playerId, clip);
    this.party?.send({ type: 'voice', clip });
  }

  broadcastSay(playerId) {
    const text = this.charactersById[playerId]?.catchphrase || 'Bonk!';
    this.sayFrom(playerId, text);
    this.party?.send({ type: 'say', text });
  }

  async playVoiceFrom(playerId, clip) {
    const character = this.charactersById[playerId];
    if (!character) return;
    const fighter = this.fighters.get(playerId);
    fighter?.node.classList.add('is-talking');
    await playClip(clip, character.voice, (level) => this.setTalkLevel(playerId, level));
    fighter?.node.classList.remove('is-talking');
    this.setTalkLevel(playerId, 0);
  }

  async sayFrom(playerId, text) {
    const character = this.charactersById[playerId];
    if (!character) return;
    const fighter = this.fighters.get(playerId);
    this.speechBubble(playerId, text);
    fighter?.node.classList.add('is-talking');
    await speak(text, character.voice, (level) => this.setTalkLevel(playerId, level));
    fighter?.node.classList.remove('is-talking');
    this.setTalkLevel(playerId, 0);
  }

  speechBubble(playerId, text) {
    const fighter = this.fighters.get(playerId);
    if (!fighter) return;
    const bubble = h('div', { class: 'bubble' }, text);
    fighter.node.append(bubble);
    setTimeout(() => bubble.remove(), 2600);
  }

  /* ----------------------------------------------------------------- effects */

  handleFx(fx) {
    if (this.seenFx.has(fx.seq)) return;
    this.seenFx.add(fx.seq);
    if (this.seenFx.size > 400) this.seenFx.clear();

    if (fx.sfx) play(fx.sfx);

    if (fx.kind === 'countdown') {
      this.countdownEl.textContent = fx.value > 0 ? String(fx.value) : 'BONK!';
      this.countdownEl.classList.remove('is-pop');
      void this.countdownEl.offsetWidth;
      this.countdownEl.classList.add('is-pop');
      play('countdown');
      return;
    }

    if (fx.kind === 'start') {
      this.countdownEl.textContent = '';
      this.announce('\u{1F44A} FIGHT!');
      return;
    }

    if (fx.kind === 'hit') {
      this.playHit(fx);
      return;
    }

    if (fx.kind === 'ko') {
      const victim = this.fighters.get(fx.to);
      victim?.node.classList.add('is-ko');
      this.announce(`\u{1F4AB} ${this.charactersById[fx.to]?.name} has swirly eyes!`);
      return;
    }

    if (fx.kind === 'silly') {
      this.announce(`${fx.emoji} ${fx.text}`);
      if (fx.to) {
        const victim = this.fighters.get(fx.to);
        if (victim) {
          shake(victim.node);
          this.floatEmoji(victim, fx.emoji);
          if (fx.damage) this.damageNumber(fx.to, fx.damage, false);
          if (fx.heal) this.damageNumber(fx.to, fx.heal, false, true);
        }
      }
      if (fx.global === 'bigheads') this.stage.classList.add('big-heads');
      if (fx.global === 'slowmo') this.stage.classList.add('slow-mo');
      if (fx.global) {
        setTimeout(() => this.stage.classList.remove('big-heads', 'slow-mo'), 7000);
      }
    }
  }

  playHit(fx) {
    const attacker = this.fighters.get(fx.from);
    const victim = this.fighters.get(fx.to);
    if (!attacker || !victim) return;

    attacker.node.classList.remove('atk-jab', 'atk-throw', 'atk-blast', 'atk-charge');
    void attacker.node.offsetWidth;
    attacker.node.classList.add(`atk-${fx.style}`);
    attacker.node.style.setProperty('--lunge', victim.left > attacker.left ? '1' : '-1');
    setTimeout(() => attacker.node.classList.remove(`atk-${fx.style}`), 620);

    if (fx.style === 'throw' || fx.style === 'blast') {
      this.projectile(attacker, victim, fx.emoji, fx.style);
    }

    const land = fx.style === 'throw' ? 260 : 90;
    setTimeout(() => {
      shake(victim.node, fx.damage > 20 ? 'big' : 'normal');
      if (fx.damage > 20) shake(this.stage, 'big');
      popText(victim.node, fx.pop, { x: 50, y: 14, tone: fx.blocked ? 'block' : 'hit' });
      this.damageNumber(fx.to, fx.damage, fx.blocked);
      this.starBurst(victim);
      if (navigator.vibrate && this.controls.includes(fx.to)) navigator.vibrate(fx.blocked ? 20 : 60);
      if (!fx.blocked && fx.damage > 20 && Math.random() < 0.6) {
        this.announce(COMMENTARY[Math.floor(Math.random() * COMMENTARY.length)]);
      }
    }, land);

    if (fx.shout && Math.random() < 0.5) this.speechBubble(fx.from, fx.shout);
  }

  projectile(from, to, emoji, style) {
    const node = h('div', { class: `projectile p-${style}` }, emoji);
    node.style.left = `${from.left}%`;
    this.stage.append(node);
    requestAnimationFrame(() => {
      node.style.left = `${to.left}%`;
      node.style.transform = 'translate(-50%, -50%) rotate(720deg) scale(1.4)';
    });
    setTimeout(() => node.remove(), 700);
  }

  starBurst(fighter) {
    for (let i = 0; i < 5; i++) {
      const star = h('div', { class: 'star' }, ['⭐', '\u{1F4A5}', '✨'][i % 3]);
      star.style.setProperty('--dx', `${(Math.random() - 0.5) * 160}px`);
      star.style.setProperty('--dy', `${-40 - Math.random() * 90}px`);
      fighter.fx.append(star);
      setTimeout(() => star.remove(), 800);
    }
  }

  floatEmoji(fighter, emoji) {
    const node = h('div', { class: 'float-emoji' }, emoji);
    fighter.fx.append(node);
    setTimeout(() => node.remove(), 1400);
  }

  damageNumber(playerId, amount, blocked, healing = false) {
    const fighter = this.fighters.get(playerId);
    if (!fighter) return;
    const node = h('div', {
      class: `dmg ${healing ? 'is-heal' : ''} ${blocked ? 'is-blocked' : ''}`
    }, healing ? `+${amount}` : `-${amount}`);
    node.style.left = `${40 + Math.random() * 20}%`;
    fighter.fx.append(node);
    setTimeout(() => node.remove(), 1100);
  }

  announce(text) {
    this.announcer.textContent = text;
    this.announcer.classList.remove('is-on');
    void this.announcer.offsetWidth;
    this.announcer.classList.add('is-on');
  }

  /* ------------------------------------------------------------- rendering */

  setTalkLevel(playerId, level) {
    this.talkLevel.set(playerId, level);
    const fighter = this.fighters.get(playerId);
    if (!fighter) return;
    const character = this.charactersById[playerId];
    const state = this.view?.players.find((p) => p.id === playerId);
    if (level > 0) {
      fighter.art.innerHTML = renderGoof(character, { mood: 'talk', mouthOpen: level, facing: fighter.facing });
      this.lastMood.set(playerId, `talk:${Math.round(level * 4)}`);
    } else {
      const mood = state?.mood || 'idle';
      fighter.art.innerHTML = renderGoof(character, { mood, facing: fighter.facing });
      this.lastMood.set(playerId, mood);
    }
  }

  renderAllGoofs() {
    for (const entry of this.entries) {
      const fighter = this.fighters.get(entry.id);
      fighter.art.innerHTML = renderGoof(entry.character, { mood: 'idle', facing: fighter.facing });
      this.lastMood.set(entry.id, 'idle');
    }
  }

  paint() {
    const view = this.view;
    if (!view) return;

    for (const player of view.players) {
      const bars = this.bars.get(player.id);
      if (bars) {
        bars.bar.style.width = `${(player.hp / (player.maxHp || 140)) * 100}%`;
        bars.bar.dataset.low = player.hp <= (player.maxHp || 140) * 0.3 ? 'yes' : 'no';
        bars.stam.style.width = `${player.stamina}%`;
        bars.card.classList.toggle('is-ko', player.ko);
      }

      const fighter = this.fighters.get(player.id);
      if (!fighter) continue;
      fighter.node.classList.toggle('is-ko', player.ko);
      fighter.node.classList.toggle('is-blocking', player.blocking);
      fighter.node.classList.toggle('is-stunned', player.stunned);

      // Only redraw the SVG when the expression actually changes.
      const talking = (this.talkLevel.get(player.id) || 0) > 0;
      if (!talking && this.lastMood.get(player.id) !== player.mood) {
        fighter.art.innerHTML = renderGoof(this.charactersById[player.id], { mood: player.mood, facing: fighter.facing });
        this.lastMood.set(player.id, player.mood);
      }
    }

    // Cooldown sweeps + who each pad is aiming at
    for (const pad of this.pads.children) {
      const id = pad.dataset.id;
      const me = view.players.find((p) => p.id === id);
      if (!me) continue;
      for (const [moveId, entry] of pad._buttons) {
        const remaining = me.cooldowns?.[moveId] || 0;
        const ratio = Math.max(0, Math.min(1, remaining / entry.move.cooldown));
        entry.sweep.style.transform = `scaleY(${ratio})`;
        entry.btn.classList.toggle('is-cooling', ratio > 0.02);
      }
      pad.classList.toggle('is-out', me.ko);
      for (const btn of pad._targetRow?.children || []) {
        btn.classList.toggle('is-target', btn.dataset.id === me.target);
        btn.classList.toggle('is-down', Boolean(view.players.find((p) => p.id === btn.dataset.id)?.ko));
      }
    }

    if (view.phase === 'over' && !this.finished) {
      this.finished = true;
      this.showResult(view.winner);
    }
  }

  showResult(winnerId) {
    const winner = winnerId ? this.charactersById[winnerId] : null;
    play(this.controls.includes(winnerId) ? 'cheer' : 'ding');

    const panel = h('div', { class: 'result' },
      h('div', { class: 'result-crown' }, '\u{1F451}'),
      winner ? h('div', { class: 'result-head', html: renderHead(winner, 'win') }) : h('div', { class: 'result-crown' }, '\u{1F4A5}'),
      h('h2', {}, winner ? `${winner.name} WINS!` : 'Nobody wins!'),
      h('p', {}, winner ? SPECIES[winner.species].blurb : 'Everybody fell over.'),
      h('div', { class: 'row' },
        (this.isHost || !this.party) ? h('button', { class: 'big-btn', onclick: () => this.rematch() },
          h('span', { class: 'big-btn-emoji' }, '\u{1F501}'), 'Again!') : null,
        h('button', { class: 'big-btn ghost', onclick: () => this.exit() },
          h('span', { class: 'big-btn-emoji' }, '\u{1F3E0}'), 'Done')
      )
    );
    this.opt.mount.append(panel);
    confetti(panel, 40);
    if (winner) setTimeout(() => speak(winner.catchphrase, winner.voice), 700);
  }

  rematch() {
    this.party?.send({ type: 'rematch' });
    this.opt.onRematch?.();
  }

  loop = (now) => {
    if (!this.running) return;
    const dt = Math.min(100, now - this.lastFrame);
    this.lastFrame = now;

    if (this.fight) {
      this.fight.tick(dt);
      this.tickBots(dt);
      this.view = readSnapshot(this.fight.snapshot(), this.charactersById);
      if (this.party && now - this.lastPush > 90) {
        this.lastPush = now;
        this.pushState();
      }
    }

    this.paint();
    this.frame = requestAnimationFrame(this.loop);
  };

  /**
   * A deliberately mediocre opponent. It hesitates, it blocks at silly moments,
   * and it never spams — the point is that a five year old can beat it.
   */
  tickBots(dt) {
    if (!this.fight || this.fight.phase !== 'fighting' || !this.bots.size) return;

    for (const [id, brain] of this.bots) {
      const me = this.fight.players.get(id);
      if (!me || me.ko) continue;

      brain.next -= dt;
      if (brain.next > 0) continue;
      brain.next = 700 + Math.random() * 900;

      if (me.blocking) { this.fight.setBlocking(id, false); continue; }

      if (Math.random() < 0.18) {
        this.fight.setBlocking(id, true);
        brain.next = 500 + Math.random() * 700;
        continue;
      }

      const ready = movesFor(me.character.species)
        .filter((move) => (me.cooldowns[move.id] || 0) <= this.fight.clock);
      if (!ready.length) continue;

      // Reach for the big move when it is up, otherwise flail.
      const pick = ready.find((m) => m.id === 'signature' && Math.random() < 0.7)
        || ready[Math.floor(Math.random() * ready.length)];
      this.fight.attack(id, pick.id);
    }
  }

  /** Mid-fight this is a big deal in a party, so make it deliberate. */
  confirmExit() {
    const live = this.view && this.view.phase !== 'over';
    if (live && !confirm('Leave the fight?')) return;
    this.exit();
  }

  exit() {
    this.destroy();
    this.opt.onExit();
  }

  destroy() {
    this.running = false;
    cancelAnimationFrame(this.frame);
    for (const off of this.unsubscribes) off();
    this.unsubscribes = [];
  }
}
