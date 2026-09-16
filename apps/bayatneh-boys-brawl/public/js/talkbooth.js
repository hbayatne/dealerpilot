/**
 * Talk Booth — the Talking Tom bit.
 *
 * Hold the big button, say something daft, and the character repeats it in its
 * own silly voice. You can then replay the same clip through any other voice,
 * and poke the character to make it react.
 */

import { renderGoof } from './characters.js';
import { VOICES, MAX_RECORD_MS, playClip, speak, startRecording, blobToDataUrl, canRecord } from './voice.js';
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
    h('span', { class: 'talk-record-label' }, canRecord() ? 'HOLD AND TALK' : 'NO MIC \u{2014} TYPE BELOW'));

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
    try {
      await playClip(lastClip, voiceId, (level) => draw('talk', level));
    } finally {
      // Without the finally a failed decode wedged busy on forever and the
      // whole booth went silent until you left the screen and came back.
      draw('idle');
      busy = false;
    }
  }

  /**
   * Type it and the goofball says it. This is not just a nicety: the
   * microphone needs https, and over plain http on the home wifi there is no
   * recording at all — without this the whole repeat-after-me idea is dead on
   * the boys' iPads. speechSynthesis needs no permission and no secure page.
   */
  const typeInput = h('input', {
    class: 'name-input', type: 'text', maxlength: '80',
    placeholder: 'Type something silly...'
  });
  const sayTyped = () => {
    const text = typeInput.value.trim();
    if (!text || busy) return;
    busy = true;
    play('select');
    speak(text, voiceId, (level) => draw('talk', level)).finally(() => {
      draw('idle');
      busy = false;
    });
  };
  typeInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') sayTyped(); });
  const typeRow = h('div', { class: 'row tight' },
    typeInput,
    h('button', { class: 'mini-btn', onclick: sayTyped }, '\u{1F5E3} SAY IT'));

  /* hold to record */
  let recorder = null;
  let countdown = null;

  function stopTimerRing() {
    clearInterval(countdown);
    recordBtn.classList.remove('is-recording');
    timerRing.style.setProperty('--fill', '0');
  }

  function beginRecording(e) {
    e.preventDefault();
    if (!canRecord()) {
      toast('The microphone needs https \u{2014} type it instead!', '\u{2328}');
      typeInput.focus();
      return;
    }
    if (recorder) return;

    // Hold the pointer to this button for the whole gesture, so sliding a
    // thumb off mid-sentence no longer chops the recording in half.
    try { recordBtn.setPointerCapture(e.pointerId); } catch { /* not supported */ }

    recordBtn.classList.add('is-recording');
    let elapsed = 0;
    countdown = setInterval(() => {
      elapsed += 100;
      timerRing.style.setProperty('--fill', String(Math.min(1, elapsed / MAX_RECORD_MS)));
    }, 100);

    recorder = startRecording(async (blob, info) => {
      stopTimerRing();
      recorder = null;
      if (!blob) {
        if (info.reason === 'too-short') toast('Hold it down while you talk!', '\u{1F91A}');
        else if (info.reason === 'denied') toast('The microphone said no.', '\u{1F937}');
        else if (info.reason !== 'cancelled') toast('That did not record. Try again!', '\u{1F507}');
        return;
      }
      lastClip = await blobToDataUrl(blob);
      if (party?.status === 'joined') party.send({ type: 'voice', clip: lastClip });
      replay();
    }, {
      onError: () => { stopTimerRing(); recorder = null; toast('The microphone said no.', '\u{1F937}'); }
    });
  }

  function endRecording(e) {
    try { if (e?.pointerId != null) recordBtn.releasePointerCapture(e.pointerId); } catch { /* fine */ }
    if (recorder) recorder.stop();
  }

  recordBtn.addEventListener('pointerdown', beginRecording);
  recordBtn.addEventListener('pointerup', endRecording);
  recordBtn.addEventListener('pointercancel', endRecording);

  clear(mount).append(
    h('div', { class: 'screen talk' },
      h('header', { class: 'bar' },
        h('button', { class: 'mini-btn', onclick: onBack }, '\u{2190}'),
        h('h1', {}, 'Talk Booth'),
        h('span', { class: 'mini-btn ghost-space' })),
      stage,
      recordBtn,
      h('div', { class: 'lab-section' },
        h('div', { class: 'lab-label' }, canRecord() ? 'Or type it' : 'Type it and they say it'),
        typeRow),
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
