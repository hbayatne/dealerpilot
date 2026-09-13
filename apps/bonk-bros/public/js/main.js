/**
 * BONK BROS — app shell and screen router.
 */

import { blankCharacter, randomCharacter, renderGoof, renderHead, SPECIES } from './characters.js';
import * as store from './store.js';
import { renderLab } from './lab.js';
import { renderTalkBooth } from './talkbooth.js';
import { Arena } from './arena.js';
import { Party } from './net.js';
import { h, clear, toast, overlay } from './ui.js';
import { play, unlockAudio, setMuted, isMuted } from './sfx.js';
import { canRecord } from './voice.js';

const app = document.getElementById('app');
const party = new Party();
let arena = null;

/* ------------------------------------------------------------------- utils */

function tearDown() {
  if (arena) { arena.destroy(); arena = null; }
}

function needsCharacter() {
  return store.getCharacters().length === 0;
}

function muteButton() {
  const btn = h('button', { class: 'mini-btn' }, isMuted() ? '\u{1F507}' : '\u{1F50A}');
  btn.addEventListener('click', () => {
    const next = !isMuted();
    setMuted(next);
    store.setSetting('muted', next);
    btn.textContent = next ? '\u{1F507}' : '\u{1F50A}';
  });
  return btn;
}

/* ------------------------------------------------------------------- title */

function showTitle() {
  tearDown();
  const heads = h('div', { class: 'floating-heads' });
  const saved = store.getCharacters();
  for (let i = 0; i < Math.min(6, Math.max(3, saved.length)); i++) {
    const character = saved[i % Math.max(1, saved.length)] || randomCharacter();
    const head = h('div', {
      class: 'floating-head',
      html: renderHead(character, ['idle', 'win', 'attack'][i % 3]),
      style: {
        left: `${8 + (i * 15) % 84}%`,
        animationDelay: `${i * 0.7}s`,
        animationDuration: `${5 + (i % 3)}s`
      }
    });
    heads.append(head);
  }

  clear(app).append(
    h('div', { class: 'screen title-screen' },
      heads,
      h('div', { class: 'title-block' },
        h('h1', { class: 'logo' }, h('span', {}, 'BONK'), h('span', { class: 'logo-2' }, 'BROS')),
        h('p', { class: 'tagline' }, 'Put your face on a goofball. Smack your brothers. Talk nonsense.'),
        h('button', {
          class: 'big-btn giant',
          onclick: () => { unlockAudio(); play('boing'); needsCharacter() ? newCharacter() : showHome(); }
        }, h('span', { class: 'big-btn-emoji' }, '\u{1F44A}'), needsCharacter() ? 'Make my goofball' : 'PLAY'))));
}

/* -------------------------------------------------------------------- home */

function showHome() {
  tearDown();
  const me = store.getActive();
  if (!me) return newCharacter();

  clear(app).append(
    h('div', { class: 'screen home' },
      h('header', { class: 'bar' },
        h('button', { class: 'mini-btn', onclick: showTitle }, '\u{2190}'),
        h('h1', {}, 'BONK BROS'),
        muteButton()),

      h('div', { class: 'home-hero' },
        h('div', { class: 'home-art', html: renderGoof(me, { mood: 'idle' }) }),
        h('div', { class: 'home-meta' },
          h('div', { class: 'home-name' }, me.name),
          h('div', { class: 'home-species' }, `${SPECIES[me.species].emoji} ${SPECIES[me.species].name}`),
          h('button', { class: 'mini-btn wide', onclick: () => editCharacter(me) }, '\u{1F527} Change me'),
          h('button', { class: 'mini-btn wide', onclick: showRoster }, '\u{1F465} My goofballs'))),

      h('div', { class: 'menu' },
        menuButton('\u{1F30D}', 'Party fight', 'Play with your brothers on their own devices', showParty),
        menuButton('\u{1F6CB}', 'Couch fight', 'Share this screen', showCouchSetup),
        menuButton('\u{1F916}', 'Fight a robot', 'Practise on your own', startBotFight),
        menuButton('\u{1F3A4}', 'Talk Booth', 'Make your goofball repeat you', () => showTalk(me)))));
}

function menuButton(emoji, title, sub, onClick) {
  return h('button', { class: 'menu-btn', onclick: () => { unlockAudio(); play('select'); onClick(); } },
    h('span', { class: 'menu-emoji' }, emoji),
    h('span', { class: 'menu-text' }, h('strong', {}, title), h('small', {}, sub)));
}

/* ---------------------------------------------------------------- roster */

function showRoster() {
  tearDown();
  const grid = h('div', { class: 'roster-grid' });
  const active = store.getActive();

  for (const character of store.getCharacters()) {
    grid.append(h('button', {
      class: `roster-card ${character.id === active?.id ? 'is-on' : ''}`,
      onclick: () => { play('select'); store.setActive(character.id); showRoster(); },
      ondblclick: () => editCharacter(character)
    },
      h('div', { class: 'roster-art', html: renderGoof(character, { mood: 'idle' }) }),
      h('div', { class: 'roster-name' }, character.name),
      h('span', {
        class: 'roster-edit',
        onclick: (e) => { e.stopPropagation(); editCharacter(character); }
      }, '\u{1F527}')));
  }

  grid.append(h('button', { class: 'roster-card is-new', onclick: newCharacter },
    h('div', { class: 'roster-plus' }, '+'),
    h('div', { class: 'roster-name' }, 'New goofball')));

  clear(app).append(
    h('div', { class: 'screen' },
      h('header', { class: 'bar' },
        h('button', { class: 'mini-btn', onclick: showHome }, '\u{2190}'),
        h('h1', {}, 'My goofballs'),
        h('span', { class: 'mini-btn ghost-space' })),
      h('p', { class: 'hint' }, 'Tap to pick who you play as. Tap the spanner to change them.'),
      grid));
}

function newCharacter() {
  editCharacter(blankCharacter(), true);
}

function editCharacter(character, isNew = false) {
  tearDown();
  renderLab(app, {
    character,
    onSave: (saved) => {
      store.saveCharacter(saved);
      toast(`${saved.name} is ready to rumble!`, '\u{1F44A}');
      showHome();
    },
    onBack: () => (isNew && needsCharacter() ? showTitle() : showHome()),
    onDelete: isNew ? null : (id) => {
      store.deleteCharacter(id);
      needsCharacter() ? showTitle() : showRoster();
    }
  });
}

function showTalk(character) {
  tearDown();
  renderTalkBooth(app, { character, party, onBack: showHome });
}

/* -------------------------------------------------------------- couch mode */

function showCouchSetup() {
  tearDown();
  const characters = store.getCharacters();
  if (characters.length < 2) {
    toast('Make one more goofball first!', '\u{1F465}');
    return newCharacter();
  }

  const chosen = new Set([store.getActive()?.id, characters.find((c) => c.id !== store.getActive()?.id)?.id].filter(Boolean));
  const grid = h('div', { class: 'roster-grid small' });
  const startBtn = h('button', { class: 'big-btn' }, h('span', { class: 'big-btn-emoji' }, '\u{1F44A}'), 'FIGHT!');

  function refresh() {
    clear(grid);
    for (const character of characters) {
      grid.append(h('button', {
        class: `roster-card ${chosen.has(character.id) ? 'is-on' : ''}`,
        onclick: () => {
          play('select');
          if (chosen.has(character.id)) chosen.delete(character.id);
          else if (chosen.size < 4) chosen.add(character.id);
          else toast('Four fighters is the limit on one screen.', '\u{270B}');
          refresh();
        }
      },
        h('div', { class: 'roster-art', html: renderGoof(character, { mood: 'idle' }) }),
        h('div', { class: 'roster-name' }, character.name)));
    }
    startBtn.disabled = chosen.size < 2;
  }

  startBtn.addEventListener('click', () => {
    const entries = characters.filter((c) => chosen.has(c.id)).map((c) => ({ id: c.id, character: c }));
    // "Again!" has to re-run this same line-up, not drop them back on the picker.
    const run = () => startFight({
      entries, controls: entries.map((e) => e.id), isHost: true, party: null, replay: run
    });
    run();
  });

  clear(app).append(
    h('div', { class: 'screen' },
      h('header', { class: 'bar' },
        h('button', { class: 'mini-btn', onclick: showHome }, '\u{2190}'),
        h('h1', {}, 'Couch fight'),
        h('span', { class: 'mini-btn ghost-space' })),
      h('p', { class: 'hint' }, 'Pick 2 to 4 goofballs. Everyone gets their own buttons on this screen.'),
      grid,
      h('div', { class: 'lab-actions' }, startBtn)));

  refresh();
}

function startBotFight() {
  const me = store.getActive();
  const bot = randomCharacter(null);
  bot.species = 'robot';
  bot.skin = '#b9c4d0';
  bot.hat = 'antenna';
  bot.faceGear = 'none';
  bot.voice = 'robot';
  bot.name = ['Robo Reggie', 'Clanky Pete', 'Sir Beeps-a-Lot', 'Tin Terry'][Math.floor(Math.random() * 4)];
  bot.catchphrase = 'Beep boop. You are quite good at this.';
  bot.id = 'bot1';
  const entries = [
    { id: me.id, character: me },
    { id: 'bot1', character: bot, bot: true }
  ];
  startFight({ entries, controls: [me.id], isHost: true, party: null, replay: startBotFight });
}

/* -------------------------------------------------------------- party mode */

function showParty() {
  tearDown();
  const me = store.getActive();

  const codeInput = h('input', {
    class: 'code-input', type: 'text', maxlength: '4', inputmode: 'text',
    autocapitalize: 'characters', placeholder: 'CODE'
  });
  codeInput.addEventListener('input', () => {
    codeInput.value = codeInput.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
  });

  const join = async (code) => {
    const busy = overlay('busy');
    busy.panel.append(h('div', { class: 'spinner' }), h('p', {}, code ? `Looking for party ${code}...` : 'Starting a party...'));
    try {
      await party.connect({ code, profile: me });
      busy.close();
      showLobby();
    } catch (err) {
      busy.close();
      play('no');
      toast(err.message || 'Could not join.', '\u{1F615}');
    }
  };

  clear(app).append(
    h('div', { class: 'screen' },
      h('header', { class: 'bar' },
        h('button', { class: 'mini-btn', onclick: showHome }, '\u{2190}'),
        h('h1', {}, 'Party fight'),
        h('span', { class: 'mini-btn ghost-space' })),
      h('div', { class: 'party-me', html: renderHead(me) }),
      h('p', { class: 'hint' }, `Playing as ${me.name}`),
      h('div', { class: 'stack' },
        h('button', { class: 'big-btn', onclick: () => join('') },
          h('span', { class: 'big-btn-emoji' }, '\u{1F389}'), 'Start a new party'),
        h('div', { class: 'join-row' },
          codeInput,
          h('button', {
            class: 'big-btn',
            onclick: () => {
              if (codeInput.value.length !== 4) { play('no'); toast('The code is 4 letters.', '\u{1F522}'); return; }
              join(codeInput.value);
            }
          }, 'Join'))),
      h('p', { class: 'hint small' }, 'Everyone has to be on the same wifi and open the same address.')));
}

function showLobby() {
  tearDown();
  const list = h('div', { class: 'lobby-list' });
  const startBtn = h('button', { class: 'big-btn' }, h('span', { class: 'big-btn-emoji' }, '\u{1F44A}'), 'FIGHT!');
  const waiting = h('p', { class: 'hint' }, 'Waiting for the host to start...');

  const refresh = () => {
    clear(list);
    for (const { id, profile } of party.roster()) {
      list.append(h('div', { class: `lobby-card ${id === party.selfId ? 'is-me' : ''}` },
        h('div', { class: 'lobby-art', html: renderGoof(profile, { mood: 'idle' }) }),
        h('div', { class: 'lobby-name' }, profile.name || '???'),
        h('div', { class: 'lobby-tag' }, [
          id === party.hostId ? '\u{1F451} host' : null,
          id === party.selfId ? 'you' : null
        ].filter(Boolean).join(' \u{00B7} '))));
    }
    startBtn.hidden = !party.isHost;
    waiting.hidden = party.isHost;
    startBtn.disabled = party.roster().length < 2;
    startBtn.textContent = party.roster().length < 2 ? 'Waiting for a brother...' : 'FIGHT!';
  };

  const offRoster = party.on('roster', refresh);
  const offHost = party.on('host', refresh);
  const offBegin = party.on('begin', (msg) => {
    cleanup();
    beginPartyFight(msg.entries, false);
  });
  const offDropped = party.on('dropped', () => {
    cleanup();
    toast('The party ended.', '\u{1F4F5}');
    showHome();
  });

  function cleanup() { offRoster(); offHost(); offBegin(); offDropped(); }

  startBtn.addEventListener('click', () => {
    const entries = party.roster().map(({ id, profile }) => ({ id, character: profile }));
    party.send({ type: 'begin', entries });
    cleanup();
    beginPartyFight(entries, true);
  });

  clear(app).append(
    h('div', { class: 'screen' },
      h('header', { class: 'bar' },
        h('button', {
          class: 'mini-btn',
          onclick: () => { cleanup(); party.disconnect(); showHome(); }
        }, '\u{2190}'),
        h('h1', {}, 'Party lobby'),
        muteButton()),
      h('div', { class: 'code-badge' }, h('small', {}, 'Party code'), h('strong', {}, party.code || '----')),
      h('p', { class: 'hint' }, 'Tell your brothers this code. They tap Join and type it in.'),
      list,
      h('div', { class: 'lab-actions' }, startBtn, waiting),
      h('button', {
        class: 'mini-btn wide',
        onclick: () => { cleanup(); showTalk(store.getActive()); }
      }, '\u{1F3A4} Talk Booth')));

  refresh();
}

function beginPartyFight(entries, isHost) {
  startFight({
    entries,
    controls: [party.selfId],
    isHost,
    party,
    replay: () => beginPartyFight(entries, isHost),
    onExit: () => { party.disconnect(); showHome(); }
  });
}

/* ------------------------------------------------------------------- fight */

function startFight({ entries, controls, isHost, party: net, replay, onExit }) {
  tearDown();
  arena = new Arena({
    mount: app,
    entries,
    controls,
    party: net,
    isHost,
    onExit: onExit || showHome,
    onRematch: () => { tearDown(); replay(); }
  });
}

/* -------------------------------------------------------------------- boot */

setMuted(Boolean(store.getSetting('muted')));

document.addEventListener('pointerdown', function once() {
  unlockAudio();
  document.removeEventListener('pointerdown', once);
}, { once: true });

if (!canRecord()) {
  console.info('[bonk] microphone unavailable — page is not a secure context');
}

window.addEventListener('error', (e) => console.error('[bonk]', e.message));

showTitle();
