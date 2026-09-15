/**
 * Character Lab — where a kid turns their face into a goofball.
 */

import {
  SPECIES, SKIN_COLORS, OUTFIT_COLORS, HATS, FACE_GEAR,
  HEAD_SIZES, BODY_SIZES, EYE_STYLES, CATCHPHRASES,
  renderGoof, applySpecies, randomCharacter, randomName
} from './characters.js';
import { VOICES, speak } from './voice.js';
import { captureFace } from './facebooth.js';
import { h, clear, toast } from './ui.js';
import { play } from './sfx.js';

export function renderLab(mount, { character, onSave, onBack, onDelete }) {
  let draft = { ...character };

  const preview = h('div', { class: 'lab-preview' });
  const nameInput = h('input', {
    class: 'name-input', type: 'text', maxlength: '18',
    value: draft.name, placeholder: 'Name me!'
  });
  nameInput.addEventListener('input', () => { draft.name = nameInput.value; paint(); });

  const sections = h('div', { class: 'lab-sections' });

  function paint() {
    preview.innerHTML = renderGoof(draft, { mood: 'idle' });
  }

  /** A horizontal strip of tappable chips. */
  function chipRow(label, items, isActive, onPick) {
    const row = h('div', { class: 'chip-row' });
    for (const item of items) {
      const chip = h('button', {
        class: `chip ${isActive(item) ? 'is-on' : ''}`,
        onclick: () => {
          play('select');
          onPick(item);
          paint();
          refresh();
        }
      }, item.swatch
        ? h('span', { class: 'swatch', style: { background: item.swatch } })
        : h('span', {
            class: 'chip-emoji',
            style: item.emojiScale ? { fontSize: `${item.emojiScale}px` } : null
          }, item.emoji || ''),
        item.label ? h('span', { class: 'chip-label' }, item.label) : null);
      row.append(chip);
    }
    return h('div', { class: 'lab-section' }, h('div', { class: 'lab-label' }, label), row);
  }

  function refresh() {
    clear(sections);

    sections.append(chipRow('Who are you?',
      Object.entries(SPECIES).map(([id, s]) => ({ id, emoji: s.emoji, label: s.name })),
      (item) => item.id === draft.species,
      (item) => { draft = applySpecies(draft, item.id); }));

    sections.append(chipRow('Skin / fur',
      SKIN_COLORS.map((c) => ({ id: c, swatch: c })),
      (item) => item.id === draft.skin,
      (item) => { draft.skin = item.id; }));

    sections.append(chipRow('Outfit',
      OUTFIT_COLORS.map((c) => ({ id: c, swatch: c })),
      (item) => item.id === draft.outfit,
      (item) => { draft.outfit = item.id; }));

    sections.append(chipRow('On your head',
      Object.entries(HATS).map(([id, hat]) => ({ id, emoji: hat.emoji, label: hat.name })),
      (item) => item.id === draft.hat,
      (item) => { draft.hat = item.id; }));

    sections.append(chipRow('On your face',
      Object.entries(FACE_GEAR).map(([id, gear]) => ({ id, emoji: gear.emoji, label: gear.name })),
      (item) => item.id === draft.faceGear,
      (item) => { draft.faceGear = item.id; }));

    sections.append(chipRow('Cartoon eyes',
      EYE_STYLES.map((e, i) => ({ id: e.id, emoji: e.emoji, label: e.name, emojiScale: 15 + i * 6 })),
      (item) => item.id === (draft.eyeStyle || 'normal'),
      (item) => { draft.eyeStyle = item.id; }));

    sections.append(chipRow('Head size',
      HEAD_SIZES.map((s, i) => ({ id: s.id, emoji: '\u{1F642}', label: s.name, emojiScale: 13 + i * 6 })),
      (item) => item.id === draft.headSize,
      (item) => { draft.headSize = item.id; }));

    sections.append(chipRow('Body size',
      BODY_SIZES.map((s, i) => ({ id: s.id, emoji: '\u{1F9CD}', label: s.name, emojiScale: 16 + i * 7 })),
      (item) => item.id === draft.bodySize,
      (item) => { draft.bodySize = item.id; }));

    sections.append(chipRow('Voice',
      Object.entries(VOICES).map(([id, v]) => ({ id, emoji: v.emoji, label: v.name })),
      (item) => item.id === draft.voice,
      (item) => {
        draft.voice = item.id;
        speak(`Hi, I am ${draft.name || 'a goofball'}`, item.id);
      }));

    const phraseInput = h('input', {
      class: 'name-input', type: 'text', maxlength: '48',
      value: draft.catchphrase, placeholder: 'Say something silly'
    });
    phraseInput.addEventListener('input', () => { draft.catchphrase = phraseInput.value; });

    sections.append(h('div', { class: 'lab-section' },
      h('div', { class: 'lab-label' }, 'Catchphrase'),
      h('div', { class: 'row tight' },
        phraseInput,
        h('button', {
          class: 'mini-btn',
          onclick: () => {
            draft.catchphrase = CATCHPHRASES[Math.floor(Math.random() * CATCHPHRASES.length)];
            phraseInput.value = draft.catchphrase;
            speak(draft.catchphrase, draft.voice);
          }
        }, '\u{1F3B2}'),
        h('button', {
          class: 'mini-btn',
          onclick: () => speak(draft.catchphrase || 'Bonk!', draft.voice)
        }, '\u{1F50A}'))));

    if (draft.species === 'footballer') {
      const numberInput = h('input', {
        class: 'name-input short', type: 'text', inputmode: 'numeric', maxlength: '2', value: draft.number
      });
      numberInput.addEventListener('input', () => {
        draft.number = numberInput.value.replace(/\D/g, '').slice(0, 2);
        paint();
      });
      sections.append(h('div', { class: 'lab-section' },
        h('div', { class: 'lab-label' }, 'Jersey number'), h('div', { class: 'row tight' }, numberInput)));
    }
  }

  clear(mount).append(
    h('div', { class: 'screen lab' },
      h('header', { class: 'bar' },
        h('button', { class: 'mini-btn', onclick: onBack }, '\u{2190}'),
        h('h1', {}, 'Character Lab'),
        onDelete
          ? h('button', {
              class: 'mini-btn danger',
              onclick: () => {
                if (confirm(`Throw ${draft.name} in the bin?`)) onDelete(draft.id);
              }
            }, '\u{1F5D1}')
          : h('span', { class: 'mini-btn ghost-space' })),

      h('div', { class: 'lab-top' },
        preview,
        h('div', { class: 'lab-top-controls' },
          nameInput,
          h('div', { class: 'row tight' },
            h('button', {
              class: 'mini-btn wide',
              onclick: async () => {
                const face = await captureFace();
                if (face) { draft.face = face; paint(); toast('Looking good!', '\u{1F60E}'); }
              }
            }, '\u{1F4F8} Face'),
            h('button', {
              class: 'mini-btn wide',
              onclick: () => {
                play('boing');
                const face = draft.face;
                draft = { ...randomCharacter(face), id: draft.id, name: randomName() };
                nameInput.value = draft.name;
                paint();
                refresh();
              }
            }, '\u{1F3B2} Surprise me')))),

      sections,

      h('div', { class: 'lab-actions' },
        h('button', {
          class: 'big-btn',
          onclick: () => {
            if (!draft.name.trim()) draft.name = randomName();
            play('ding');
            onSave({ ...draft });
          }
        }, h('span', { class: 'big-btn-emoji' }, '\u{2705}'), 'Save goofball'))));

  paint();
  refresh();
}
