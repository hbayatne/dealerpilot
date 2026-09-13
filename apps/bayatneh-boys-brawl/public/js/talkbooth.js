/**
 * Talk Booth — the Talking Tom bit.
 *
 * Hold the big button, say something daft, and the character repeats it in its
 * own silly voice. You can then replay the same clip through any other voice,
 * and poke the character to make it react.
 */

import { renderGoof } from './characters.js';
import { VOICES, playClip, speak, startRecording, blobToDataUrl, canRecord } from './voice.js';
import { h, clear, toast, popText } from './ui.js';
import { play } from './sfx.js';

const POKES = [
  { id: 'poke', emoji: '\u{1F449}', label: 'Poke', mood: 'hit', pop: 'OI!', line: 'Hey! Do not poke me!', sfx: 'pop' },
  { id: 'tickle', emoji: '\u{1FAB6}', label: 'Tickle', mood: 'win', pop: 'HEEHEE!', line: 'Hahaha stop it that tickles!', sfx: 'boing' },
  { id: 'slap', emoji: '\u{1F590}', label: 'Slap', mood: 'hit', pop: 'BONK!', line: 'Ouch! My beautiful face!', sfx: 'slap' },
  { id: 'burp', emoji: '\u{1F4A8}', label: 'Burp', mood: 'attack', pop: 'BUUURP', line: 'Excuse me. That was a big one.', sfx: 'fart' },
  { id: 'dizzy', emoji: '\u{1F4AB}', label: 'Spin', mood: 'ko', pop: 'WOOOAH', line: 'The room is spinning!', sfx: 'boing' }
];

export function renderTalkBooth(mount, { character, party, onBack }) {
  let lastClip = null;
  let voiceId = character.voice;
  let busy = false;

  const stageArt = h('div', { class: 'talk-art' });
  const stage = h('div', { class: 'talk-stage' }, stageArt);

  function draw(mood = 'idle', mouthOpen = 0) {
    stageArt.innerHTML = renderGoof(character, { mood, mouthOpen });
  }

  const recordBtn = h('button', { class: 'talk-record' },
    h('span', { class: 'talk-record-emoji' }, '\u{1F3A4}'),
    h('span', { class: 'talk-record-label' }, canRecord() ? 'HOLD AND TALK' : 'MIC NEEDS HTTPS'));

  const timerRing = h('div', { class: 'talk-timer' });
  recordBtn.append(timerRing);

  const voiceRow = h('div', { class: 'chip-row' });
  for (const [id, voice] of Object.entries(VOICES)) {
    voiceRow.append(h('button', {
      class: `chip ${id === voiceId ? 'is-on' : ''}`,
      onclick: () => {
        voiceId = id;
        for (const chip of voiceRow.children) chip.classList.remove('is-on');
        voiceRow.children[Object.keys(VOICES).indexOf(id)].classList.add('is-on');
        play('select');
        if (lastClip) replay();
        else speak(character.catchphrase, id, (level) => draw('talk', level)).then(() => draw('idle'));
      }
    }, h('span', { class: 'chip-emoji' }, voice.emoji), h('span', { class: 'chip-label' }, voice.name)));
  }

  const pokeRow = h('div', { class: 'poke-row' });
  for (const poke of POKES) {
    pokeRow.append(h('button', {
      class: 'poke-btn',
      onclick: async () => {
        if (busy) return;
        busy = true;
        play(poke.sfx);
        draw(poke.mood);
        popText(stage, poke.pop, { x: 50, y: 12, tone: 'hit' });
        stage.classList.add('is-poked');
        setTimeout(() => stage.classList.remove('is-poked'), 500);
        await speak(poke.line, voiceId, (level) => draw('talk', level));
        draw('idle');
        busy = false;
      }
    }, h('span', { class: 'poke-emoji' }, poke.emoji), poke.label));
  }

  async function replay() {
    if (!lastClip || busy) return;
    busy = true;
    await playClip(lastClip, voiceId, (level) => draw('talk', level));
    draw('idle');
    busy = false;
  }

  /* hold to record */
  let recorder = null;
  let countdown = null;

  async function beginRecording(e) {
    e.preventDefault();
    if (!canRecord()) {
      toast('Recording needs https. Everything else still works!', '\u{1F512}');
      return;
    }
    if (recorder) return;
    try {
      recordBtn.classList.add('is-recording');
      let elapsed = 0;
      countdown = setInterval(() => {
        elapsed += 100;
        timerRing.style.setProperty('--fill', String(Math.min(1, elapsed / 5000)));
      }, 100);

      recorder = await startRecording(async (blob) => {
        clearInterval(countdown);
        recordBtn.classList.remove('is-recording');
        timerRing.style.setProperty('--fill', '0');
        recorder = null;
        if (!blob) { toast('Too quiet! Say it louder.', '\u{1F442}'); return; }
        lastClip = await blobToDataUrl(blob);
        if (party?.status === 'joined') party.send({ type: 'voice', clip: lastClip });
        replay();
      });
    } catch {
      recordBtn.classList.remove('is-recording');
      recorder = null;
      toast('The microphone said no.', '\u{1F937}');
    }
  }

  function endRecording() {
    if (recorder) recorder.stop();
  }

  recordBtn.addEventListener('pointerdown', beginRecording);
  recordBtn.addEventListener('pointerup', endRecording);
  recordBtn.addEventListener('pointercancel', endRecording);
  recordBtn.addEventListener('pointerleave', endRecording);

  clear(mount).append(
    h('div', { class: 'screen talk' },
      h('header', { class: 'bar' },
        h('button', { class: 'mini-btn', onclick: onBack }, '\u{2190}'),
        h('h1', {}, 'Talk Booth'),
        h('span', { class: 'mini-btn ghost-space' })),
      stage,
      recordBtn,
      h('div', { class: 'talk-row' },
        h('button', { class: 'mini-btn wide', onclick: replay }, '\u{1F501} Say it again'),
        h('button', {
          class: 'mini-btn wide',
          onclick: () => speak(character.catchphrase, voiceId, (level) => draw('talk', level)).then(() => draw('idle'))
        }, '\u{1F4AC} Catchphrase')),
      h('div', { class: 'lab-section' }, h('div', { class: 'lab-label' }, 'Say it as...'), voiceRow),
      h('div', { class: 'lab-section' }, h('div', { class: 'lab-label' }, 'Mess with them'), pokeRow),
      party?.status === 'joined'
        ? h('p', { class: 'hint' }, '\u{1F4E1} Your brothers hear everything you record.')
        : null));

  draw('idle');
}
