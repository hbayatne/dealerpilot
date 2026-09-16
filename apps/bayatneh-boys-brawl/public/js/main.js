/**
 * BAYATNEH BOYS BRAWL — app shell and screen router.
 */

import { blankCharacter, randomCharacter, renderGoof, renderHead, SPECIES } from './characters.js';
import { STARTERS, loadStarterFace } from './starters.js';
import * as store from './store.js';
import { renderLab } from './lab.js';
import { renderTalkBooth } from './talkbooth.js';
import { Arena } from './arena.js';
import { Party } from './net.js';
import { DEFAULT_TARGET_SCORE } from './fight.js';
import { h, clear, toast, overlay } from './ui.js';
import { play, unlockAudio, setMuted, isMuted } from './sfx.js';
import { canRecord } from './voice.js';
import { playMusic, stopMusic, setMusicVolume } from './music.js';

const app = document.getElementById('app');
const party = new Party();
let arena = null;

/* ------------------------------------------------------------------- utils */

/**
 * Party mode needs the little websocket server that ships with this app. When
 * the game is served from anywhere else — a static host, a published copy of
 * public/ — there is nothing to connect to, so the menu says so rather than
 * handing a five year old a button that only produces an error.
 */
let partyAvailable = false;

async function detectParty() {
  try {
    const response = await fetch('party-available', { cache: 'no-store' });
    partyAvailable = response.ok && (await response.json())?.party === true;
  } catch {
    partyAvailable = false;
  }
}

function tearDown() {
  if (arena) { arena.destroy(); arena = null; }
}

function needsCharacter() {
  return store.getCharacters().length === 0;
}

/** Music is off whenever everything is muted, or the music toggle is off. */
function refreshMusicVolume() {
  setMusicVolume(isMuted() || store.getSetting('musicOff') ? 0 : 0.22);
}

function muteButton() {
  const btn = h('button', { class: 'mini-btn' }, isMuted() ? '\u{1F507}' : '\u{1F50A}');
  btn.addEventListener('click', () => {
    const next = !isMuted();
    setMuted(next);
    store.setSetting('muted', next);
    refreshMusicVolume();
    btn.textContent = next ? '\u{1F507}' : '\u{1F50A}';
  });
  return btn;
}

function musicButton() {
  const label = () => (store.getSetting('musicOff') ? '\u{1F507}\u{1F3B5}' : '\u{1F3B5}');
  const btn = h('button', { class: 'mini-btn music-btn' }, label());
  btn.addEventListener('click', () => {
    store.setSetting('musicOff', !store.getSetting('musicOff'));
    refreshMusicVolume();
    btn.textContent = label();
    play('select');
  });
  return btn;
}

/* ------------------------------------------------------------------- title */

/** Splits a word into per-letter spans so each one can animate on its own. */
function letters(word, className) {
  return h('span', { class: `word ${className}` },
    [...word].map((ch, i) => h('span', { class: 'ltr', style: { '--i': String(i) } }, ch)));
}

function showTitle() {
  tearDown();
  playMusic('menu');

  const heads = h('div', { class: 'floating-heads' });
  const saved = store.getCharacters();
  const pool = saved.length ? saved : [randomCharacter(), randomCharacter(), randomCharacter()];
  for (let i = 0; i < Math.min(7, Math.max(4, pool.length * 2)); i++) {
    const character = pool[i % pool.length];
    const head = h('div', {
      class: 'floating-head',
      html: renderHead(character, ['idle', 'win', 'attack', 'ko'][i % 4]),
      style: {
        left: `${6 + (i * 14.5) % 88}%`,
        animationDelay: `${i * 1.1}s`,
        animationDuration: `${7 + (i % 4) * 1.5}s`,
        '--spin': `${i % 2 ? 1 : -1}`
      },
      // Poking a drifting head should do something. It always should.
      onclick: (e) => {
        play(['boing', 'pop', 'slap', 'fart'][Math.floor(Math.random() * 4)]);
        e.currentTarget.classList.remove('is-poked');
        void e.currentTarget.offsetWidth;
        e.currentTarget.classList.add('is-poked');
      }
    });
    heads.append(head);
  }

  clear(app).append(
    h('div', { class: 'screen title-screen' },
      h('div', { class: 'hero-rays' }),
      h('div', { class: 'hero-blobs' }, [0, 1, 2, 3, 4].map((i) =>
        h('span', { class: `blob blob-${i}` }))),
      heads,
      h('div', { class: 'title-controls' }, musicButton(), muteButton()),
      h('div', { class: 'title-block' },
        h('h1', { class: 'logo' },
          letters('BAYATNEH', 'word-1'),
          letters('BOYS', 'word-2'),
          letters('BRAWL', 'word-3')),
        h('p', { class: 'tagline' }, 'Put your face on a goofball. Smack your brothers. Talk nonsense.'),
        h('button', {
          class: 'big-btn giant',
          onclick: () => {
            unlockAudio();
            playMusic('menu');
            refreshMusicVolume();
            play('boing');
            needsCharacter() ? showWhoIsPlaying() : showHome();
          }
        }, h('span', { class: 'big-btn-emoji' }, '\u{1F44A}'), needsCharacter() ? "Who's playing?" : 'PLAY'))));
}

/* ------------------------------------------------------------ who's playing */

/**
 * First run: offer the brothers as one-tap characters instead of dropping a
 * five year old straight into a settings screen. Everything picked here is
 * still editable afterwards, photo included.
 */
function showWhoIsPlaying() {
  tearDown();
  playMusic('menu');
  const grid = h('div', { class: 'roster-grid' });

  for (const starter of STARTERS) {
    const preview = blankCharacter({ ...starter, face: null });
    grid.append(h('button', {
      class: 'roster-card',
      onclick: () => pickStarter(starter)
    },
      h('div', { class: 'roster-art', html: renderGoof(preview, { mood: 'idle' }) }),
      h('div', { class: 'roster-name' }, starter.name),
      h('div', { class: 'roster-sub' }, starter.face ? '\u{1F4F8} photo ready' : '\u{1F4F7} take a photo')));
  }

  grid.append(h('button', { class: 'roster-card is-new', onclick: newCharacter },
    h('div', { class: 'roster-plus' }, '+'),
    h('div', { class: 'roster-name' }, 'Somebody else')));

  clear(app).append(
    h('div', { class: 'screen' },
      h('header', { class: 'bar' },
        h('button', { class: 'mini-btn', onclick: showTitle }, '\u{2190}'),
        h('h1', {}, "Who's playing?"),
        muteButton()),
      h('p', { class: 'hint' }, 'Tap your name. You can change absolutely everything afterwards.'),
      grid));
}

async function pickStarter(starter) {
  play('select');
  const face = await loadStarterFace(starter);
  const character = blankCharacter({ ...starter, face });
  store.saveCharacter(character);
  if (face) {
    toast(`Hello ${character.name}!`, '\u{1F44B}');
    showHome();
  } else {
    // No photo shipped for this one — go and take one.
    editCharacter(character);
  }
}

/* -------------------------------------------------------------------- home */

function showHome() {
  tearDown();
  playMusic('menu');
  const me = store.getActive();
  if (!me) return newCharacter();

  clear(app).append(
    h('div', { class: 'screen home' },
      h('header', { class: 'bar' },
        h('button', { class: 'mini-btn', onclick: showTitle }, '\u{2190}'),
        h('h1', {}, 'Bayatneh Boys'),
        muteButton()),

      h('div', { class: 'home-hero' },
        h('div', { class: 'home-art', html: renderGoof(me, { mood: 'idle' }) }),
        h('div', { class: 'home-meta' },
          h('div', { class: 'home-name' }, me.name),
          h('div', { class: 'home-species' }, `${SPECIES[me.species].emoji} ${SPECIES[me.species].name}`),
          h('button', { class: 'mini-btn wide', onclick: () => editCharacter(me) }, '\u{1F527} Change me'),
          h('button', { class: 'mini-btn wide', onclick: showRoster }, '\u{1F465} My goofballs'))),

      h('div', { class: 'menu' },
        partyAvailable
          ? menuButton('\u{1F30D}', 'Party fight', 'Play with your brothers on their own devices', showParty)
          : menuButton('\u{1F30D}', 'Party fight', 'Needs the home server \u{2014} ask Dad to start it', explainParty),
        menuButton('\u{1F6CB}', 'Couch rumble', 'All of you on this one screen', showCouchSetup),
        menuButton('\u{1F916}', 'Fight a robot', 'Practise on your own', startBotFight),
        menuButton('\u{1F3A4}', 'Talk Booth', 'Make your goofball repeat you', () => showTalk(me)),
        menuButton('\u{1F3C6}', 'Scoreboard', scoreboardSub(), showScoreboard))));
}

/** "Waleed is winning" on the menu button, or a nudge if nobody has won yet. */
function scoreboardSub() {
  const board = store.getScoreboard();
  const top = board[0];
  if (!top || !top.wins) return 'Nobody has won a brawl yet';
  const drawn = board.filter((row) => row.wins === top.wins);
  return drawn.length > 1
    ? `${drawn.map((row) => row.character.name).join(' and ')} are tied on ${top.wins}`
    : `${top.character.name} is winning with ${top.wins}`;
}

/** Who has won the most brawls on this device. Brothers keep score. */
function showScoreboard() {
  tearDown();
  playMusic('menu');
  const board = store.getScoreboard();
  const most = board[0]?.wins || 0;
  const list = h('div', { class: 'score-list' });

  board.forEach((row, index) => {
    list.append(h('div', { class: `score-row ${row.wins && row.wins === most ? 'is-top' : ''}` },
      h('div', { class: 'score-rank' }, row.wins && row.wins === most ? '\u{1F451}' : `${index + 1}`),
      h('div', { class: 'score-head', html: renderHead(row.character, row.wins === most && most ? 'win' : 'idle') }),
      h('div', { class: 'score-name' }, row.character.name),
      h('div', { class: 'score-wins' },
        h('strong', {}, String(row.wins)),
        h('small', {}, row.wins === 1 ? 'win' : 'wins'))));
  });

  clear(app).append(
    h('div', { class: 'screen' },
      h('header', { class: 'bar' },
        h('button', { class: 'mini-btn', onclick: showHome }, '\u{2190}'),
        h('h1', {}, 'Scoreboard'),
        muteButton()),
      h('p', { class: 'hint' }, most
        ? 'Every brawl won on this device. Winner gets the crown.'
        : 'Win a brawl and your name goes up here.'),
      list,
      h('div', { class: 'lab-actions' },
        h('button', {
          class: 'mini-btn wide',
          onclick: () => {
            if (confirm('Wipe the scoreboard and start again?')) {
              store.resetScoreboard();
              play('boing');
              showScoreboard();
            }
          }
        }, '\u{1F9F9} Start again'))));
}

function explainParty() {
  toast('Party fights need the game running on the home computer.', '\u{1F4BB}');
}

/**
 * Two ways to fight. Rumble exists because elimination puts the youngest out
 * first and leaves him watching his brothers — in a rumble nobody is ever out.
 */
function modePicker(initial, onChange) {
  let mode = initial;
  const row = h('div', { class: 'mode-row' });
  const options = [
    { id: 'rumble', emoji: '\u{1F4A5}', name: 'RUMBLE', sub: `Nobody is ever out. First to ${DEFAULT_TARGET_SCORE} bonks wins.` },
    { id: 'elimination', emoji: '\u{1F3C6}', name: 'Last One Standing', sub: 'Get knocked out and you are done.' }
  ];
  const paint = () => {
    clear(row);
    for (const option of options) {
      row.append(h('button', {
        class: `mode-btn ${option.id === mode ? 'is-on' : ''}`,
        onclick: () => { play('select'); mode = option.id; onChange(mode); paint(); }
      },
        h('span', { class: 'mode-emoji' }, option.emoji),
        h('span', { class: 'mode-text' }, h('strong', {}, option.name), h('small', {}, option.sub))));
    }
  };
  paint();
  return row;
}

function menuButton(emoji, title, sub, onClick) {
  return h('button', { class: 'menu-btn', onclick: () => { unlockAudio(); play('select'); onClick(); } },
    h('span', { class: 'menu-emoji' }, emoji),
    h('span', { class: 'menu-text' }, h('strong', {}, title), h('small', {}, sub)));
}

/* ---------------------------------------------------------------- roster */

function showRoster() {
  tearDown();
  playMusic('menu');
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

  grid.append(h('button', { class: 'roster-card is-new', onclick: showWhoIsPlaying },
    h('div', { class: 'roster-plus' }, '\u{1F465}'),
    h('div', { class: 'roster-name' }, 'The brothers')));

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
  playMusic('menu');
  renderLab(app, {
    character,
    onSave: (saved) => {
      store.saveCharacter(saved);
      toast(`${saved.name} is ready to rumble!`, '\u{1F44A}');
      showHome();
    },
    onBack: () => (needsCharacter() ? showWhoIsPlaying() : showHome()),
    onDelete: isNew ? null : (id) => {
      store.deleteCharacter(id);
      needsCharacter() ? showWhoIsPlaying() : showRoster();
    }
  });
}

function showTalk(character) {
  tearDown();
  stopMusic();
  renderTalkBooth(app, { character, party, onBack: showHome });
}

/* -------------------------------------------------------------- couch mode */

function showCouchSetup() {
  tearDown();
  playMusic('menu');
  const characters = store.getCharacters();
  if (characters.length < 2) {
    toast('Make one more goofball first!', '\u{1F465}');
    return newCharacter();
  }

  const chosen = new Set([store.getActive()?.id, characters.find((c) => c.id !== store.getActive()?.id)?.id].filter(Boolean));
  const grid = h('div', { class: 'roster-grid small' });
  const startBtn = h('button', { class: 'big-btn' }, h('span', { class: 'big-btn-emoji' }, '\u{1F44A}'), 'FIGHT!');
  let mode = store.getSetting('lastMode') || 'rumble';

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
    store.setSetting('lastMode', mode);
    // "Again!" has to re-run this same line-up, not drop them back on the picker.
    const run = () => startFight({
      entries, controls: entries.map((e) => e.id), isHost: true, party: null, mode, replay: run
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
      modePicker(mode, (m) => { mode = m; }),
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
  startFight({ entries, controls: [me.id], isHost: true, party: null, mode: 'elimination', replay: startBotFight });
}

/* -------------------------------------------------------------- party mode */

function showParty() {
  tearDown();
  playMusic('menu');
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
  playMusic('menu');
  const list = h('div', { class: 'lobby-list' });
  const startBtn = h('button', { class: 'big-btn' }, h('span', { class: 'big-btn-emoji' }, '\u{1F44A}'), 'FIGHT!');
  const waiting = h('p', { class: 'hint' }, 'Waiting for the host to start...');
  let mode = store.getSetting('lastMode') || 'rumble';
  const picker = modePicker(mode, (m) => { mode = m; });

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
    picker.hidden = !party.isHost;
    waiting.hidden = party.isHost;
    startBtn.disabled = party.roster().length < 2;
    startBtn.textContent = party.roster().length < 2 ? 'Waiting for a brother...' : 'FIGHT!';
  };

  const offRoster = party.on('roster', refresh);
  const offHost = party.on('host', refresh);
  const offBegin = party.on('begin', (msg) => {
    cleanup();
    beginPartyFight(msg.entries, false, msg.mode || 'elimination');
  });
  const offDropped = party.on('dropped', () => {
    cleanup();
    toast('The party ended.', '\u{1F4F5}');
    showHome();
  });

  function cleanup() { offRoster(); offHost(); offBegin(); offDropped(); }

  startBtn.addEventListener('click', () => {
    const entries = party.roster().map(({ id, profile }) => ({ id, character: profile }));
    store.setSetting('lastMode', mode);
    party.send({ type: 'begin', entries, mode });
    cleanup();
    beginPartyFight(entries, true, mode);
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
      picker,
      h('div', { class: 'lab-actions' }, startBtn, waiting),
      h('button', {
        class: 'mini-btn wide',
        onclick: () => { cleanup(); showTalk(store.getActive()); }
      }, '\u{1F3A4} Talk Booth')));

  refresh();
}

function beginPartyFight(entries, isHost, mode = 'elimination') {
  startFight({
    entries,
    controls: [party.selfId],
    isHost,
    party,
    mode,
    replay: () => beginPartyFight(entries, isHost, mode),
    onExit: () => { party.disconnect(); showHome(); }
  });
}

/* ------------------------------------------------------------------- fight */

function startFight({ entries, controls, isHost, party: net, mode = 'elimination', replay, onExit }) {
  tearDown();
  arena = new Arena({
    mount: app,
    entries,
    controls,
    party: net,
    isHost,
    mode,
    onExit: onExit || showHome,
    onRematch: () => { tearDown(); replay(); }
  });
}

/* -------------------------------------------------------------------- boot */

setMuted(Boolean(store.getSetting('muted')));
refreshMusicVolume();

document.addEventListener('pointerdown', function once() {
  unlockAudio();
  document.removeEventListener('pointerdown', once);
}, { once: true });

if (!canRecord()) {
  console.info('[bonk] microphone unavailable — page is not a secure context');
}

window.addEventListener('error', (e) => console.error('[bonk]', e.message));

detectParty().then(() => {
  // The title screen does not use it, so redrawing is unnecessary — the home
  // screen is built after this resolves in every path that reaches it.
  if (document.querySelector('.home')) showHome();
});

showTitle();
