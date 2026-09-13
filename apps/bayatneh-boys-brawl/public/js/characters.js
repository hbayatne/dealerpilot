/**
 * Everything about what a goofball looks like.
 *
 * A character is plain data (see blankCharacter). renderGoof turns that data
 * into an SVG string. The face photo is dropped in as an <image> clipped to the
 * head circle, and cartoon eyes and a mouth are drawn ON TOP of it — that
 * overlay is what makes the photo pull faces when it gets bonked.
 */

export const SPECIES = {
  footballer: {
    name: 'Footballer',
    emoji: '\u{1F3C8}',
    blurb: 'Big pads. Bigger head.',
    skin: '#e8b892',
    outfit: '#1f6feb',
    voice: 'coach',
    signature: { id: 'tackle', name: 'FLYING TACKLE', emoji: '\u{1F3C8}', damage: [24, 34], cooldown: 7000, shout: 'HUT HUT HUUUT!' }
  },
  monkey: {
    name: 'Monkey',
    emoji: '\u{1F412}',
    blurb: 'Smells like bananas.',
    skin: '#a9743f',
    outfit: '#f0a830',
    voice: 'chipmunk',
    signature: { id: 'banana', name: 'BANANA BONK', emoji: '\u{1F34C}', damage: [22, 32], cooldown: 6500, shout: 'OOH OOH AAH AAH!' }
  },
  superhero: {
    name: 'Superhero',
    emoji: '\u{1F9B8}',
    blurb: 'Saves the world. Mostly.',
    skin: '#e8b892',
    outfit: '#d92b2b',
    voice: 'hero',
    signature: { id: 'laserburp', name: 'LASER BURP', emoji: '⚡', damage: [25, 35], cooldown: 7500, shout: 'BUUUURRRP OF JUSTICE!' }
  },
  robot: {
    name: 'Robot',
    emoji: '\u{1F916}',
    blurb: 'Beep. Boop. Bonk.',
    skin: '#b9c4d0',
    outfit: '#5b6bff',
    voice: 'robot',
    signature: { id: 'rocketboots', name: 'ROCKET BOOTY', emoji: '\u{1F680}', damage: [23, 33], cooldown: 7000, shout: 'IGNITION SEQUENCE... TOOT!' }
  },
  ninja: {
    name: 'Ninja',
    emoji: '\u{1F977}',
    blurb: 'You did not see him.',
    skin: '#e8b892',
    outfit: '#2b2f45',
    voice: 'sneaky',
    signature: { id: 'noogie', name: 'SNEAKY NOOGIE', emoji: '\u{1F91C}', damage: [21, 31], cooldown: 6000, shout: 'NOOGIE JUTSU!' }
  },
  wrestler: {
    name: 'Wrestler',
    emoji: '\u{1F93C}',
    blurb: 'Has a shiny belt.',
    skin: '#d99a6c',
    outfit: '#8b2fd6',
    voice: 'giant',
    signature: { id: 'bellyflop', name: 'BELLY FLOP', emoji: '\u{1F4A5}', damage: [26, 36], cooldown: 8000, shout: 'INCOMING BELLYYYY!' }
  }
};

export const SKIN_COLORS = ['#f7d7bd', '#e8b892', '#d99a6c', '#b3714a', '#8a5230', '#5d3620', '#a9743f', '#7fd67f'];
export const OUTFIT_COLORS = ['#d92b2b', '#1f6feb', '#f0a830', '#22b573', '#8b2fd6', '#ff69b4', '#2b2f45', '#00c8d7', '#ff6a00', '#ffffff'];

export const HATS = {
  none: { name: 'Nothing', emoji: '\u{1F6AB}' },
  helmet: { name: 'Football Helmet', emoji: '\u{1F3C8}' },
  cap: { name: 'Backwards Cap', emoji: '\u{1F9E2}' },
  crown: { name: 'Crown', emoji: '\u{1F451}' },
  propeller: { name: 'Propeller Hat', emoji: '\u{1F300}' },
  tophat: { name: 'Tiny Top Hat', emoji: '\u{1F3A9}' },
  headband: { name: 'Headband', emoji: '\u{1F94B}' },
  antenna: { name: 'Antenna', emoji: '\u{1F4E1}' },
  horns: { name: 'Devil Horns', emoji: '\u{1F608}' },
  halo: { name: 'Halo', emoji: '\u{1F607}' },
  bucket: { name: 'Bucket', emoji: '\u{1FAA3}' }
};

export const FACE_GEAR = {
  none: { name: 'Nothing', emoji: '\u{1F6AB}' },
  shades: { name: 'Cool Shades', emoji: '\u{1F576}' },
  nerd: { name: 'Big Glasses', emoji: '\u{1F453}' },
  mask: { name: 'Hero Mask', emoji: '\u{1F3AD}' },
  mustache: { name: 'Mustache', emoji: '\u{1F468}' },
  unibrow: { name: 'Unibrow', emoji: '\u{1F928}' },
  beard: { name: 'Big Beard', emoji: '\u{1F9D4}' },
  snorkel: { name: 'Snorkel', emoji: '\u{1F93F}' }
};

export const HEAD_SIZES = [
  { id: 'normal', name: 'Normal', scale: 1 },
  { id: 'big', name: 'Big', scale: 1.35 },
  { id: 'huge', name: 'HUGE', scale: 1.8 },
  { id: 'planet', name: 'PLANET', scale: 2.4 }
];

export const BODY_SIZES = [
  { id: 'shrimp', name: 'Shrimp', scale: 0.75 },
  { id: 'normal', name: 'Normal', scale: 1 },
  { id: 'chonk', name: 'Chonk', scale: 1.3 }
];

const NAME_BITS_A = ['Turbo', 'Captain', 'Sir', 'Mega', 'Stinky', 'Danger', 'Wobble', 'Nacho', 'Doctor', 'Baron'];
const NAME_BITS_B = ['Toenail', 'Meatball', 'Banana', 'Noodle', 'Pancake', 'Sockmonster', 'Burpington', 'Pickles', 'Thunderpants', 'Waffle'];

export const CATCHPHRASES = [
  'You smell like feet!',
  'Prepare to be bonked!',
  'I am the boss of this couch!',
  'My head is bigger than yours!',
  'Nobody out-burps me!',
  'That tickled, do it again!'
];

export function randomName() {
  const a = NAME_BITS_A[Math.floor(Math.random() * NAME_BITS_A.length)];
  const b = NAME_BITS_B[Math.floor(Math.random() * NAME_BITS_B.length)];
  return `${a} ${b}`;
}

export function blankCharacter(overrides = {}) {
  const speciesId = overrides.species || 'monkey';
  const species = SPECIES[speciesId];
  return {
    id: 'c' + Math.random().toString(36).slice(2, 9),
    name: randomName(),
    species: speciesId,
    skin: species.skin,
    outfit: species.outfit,
    hat: 'none',
    faceGear: 'none',
    headSize: 'big',
    bodySize: 'normal',
    voice: species.voice,
    number: String(Math.floor(Math.random() * 89) + 10),
    catchphrase: CATCHPHRASES[Math.floor(Math.random() * CATCHPHRASES.length)],
    face: null, // data URL of the cropped photo
    ...overrides
  };
}

/** Swapping species should drag its default look along, but keep the face+name. */
export function applySpecies(character, speciesId) {
  const species = SPECIES[speciesId];
  return {
    ...character,
    species: speciesId,
    skin: species.skin,
    outfit: species.outfit,
    voice: species.voice
  };
}

export function randomCharacter(face = null) {
  const ids = Object.keys(SPECIES);
  const speciesId = ids[Math.floor(Math.random() * ids.length)];
  const pick = (obj) => {
    const keys = Object.keys(obj);
    return keys[Math.floor(Math.random() * keys.length)];
  };
  return blankCharacter({
    species: speciesId,
    face,
    skin: SKIN_COLORS[Math.floor(Math.random() * SKIN_COLORS.length)],
    outfit: OUTFIT_COLORS[Math.floor(Math.random() * OUTFIT_COLORS.length)],
    hat: pick(HATS),
    faceGear: pick(FACE_GEAR),
    headSize: HEAD_SIZES[Math.floor(Math.random() * HEAD_SIZES.length)].id,
    bodySize: BODY_SIZES[Math.floor(Math.random() * BODY_SIZES.length)].id
  });
}

/* ------------------------------------------------------------------ drawing */

const HEAD = { cx: 100, cy: 82, r: 52 };

function shade(hex, amount) {
  const n = parseInt(hex.replace('#', ''), 16);
  const clamp = (v) => Math.max(0, Math.min(255, Math.round(v)));
  const r = clamp(((n >> 16) & 255) + amount);
  const g = clamp(((n >> 8) & 255) + amount);
  const b = clamp((n & 255) + amount);
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, '0')}`;
}

/** White text on a dark jersey, dark text on a light one. */
export function contrastInk(hex) {
  const n = parseInt(hex.replace('#', ''), 16);
  const luma = 0.299 * ((n >> 16) & 255) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255);
  return luma > 150 ? '#1b1b2b' : '#ffffff';
}

const OUTLINE = '#14142a';

/** Limbs are drawn twice: a fat dark line, then a thinner coloured one on top.
 *  That is the cheapest way to get a cartoon outline out of an SVG line. */
function limb(x1, y1, x2, y2, color, width = 15) {
  return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${OUTLINE}" stroke-width="${width + 6}" stroke-linecap="round"/>`
    + `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${color}" stroke-width="${width}" stroke-linecap="round"/>`;
}

function bodyFor(character) {
  const { outfit, skin } = character;
  const dark = shade(outfit, -40);
  const ink = contrastInk(outfit);
  const outline = `stroke="${OUTLINE}" stroke-width="4" stroke-linejoin="round"`;
  const parts = [];

  // Behind-the-body extras
  if (character.species === 'superhero') {
    parts.push(`<path class="cape" d="M74 138 Q100 128 126 138 L150 232 Q100 214 50 232 Z" fill="${dark}" ${outline}/>`);
  }
  if (character.species === 'monkey') {
    parts.push(`<path class="tail" d="M132 196 Q176 196 172 158 Q170 138 152 142" fill="none" stroke="${OUTLINE}" stroke-width="17" stroke-linecap="round"/>`);
    parts.push(`<path class="tail" d="M132 196 Q176 196 172 158 Q170 138 152 142" fill="none" stroke="${shade(skin, -25)}" stroke-width="11" stroke-linecap="round"/>`);
  }

  // Legs + feet
  const footFill = character.species === 'monkey' ? shade(skin, -20) : shade(outfit, -60);
  parts.push(limb(86, 198, 82, 244, dark, 16));
  parts.push(limb(114, 198, 118, 244, dark, 16));
  parts.push(`<ellipse class="foot" cx="76" cy="249" rx="18" ry="10" fill="${footFill}" ${outline}/>`);
  parts.push(`<ellipse class="foot" cx="124" cy="249" rx="18" ry="10" fill="${footFill}" ${outline}/>`);

  // Torso
  if (character.species === 'robot') {
    parts.push(`<rect x="64" y="132" width="72" height="74" rx="10" fill="${outfit}" ${outline}/>`);
    parts.push(`<rect x="76" y="146" width="48" height="28" rx="6" fill="${shade(outfit, 60)}" opacity="0.7"/>`);
    parts.push(`<circle cx="86" cy="192" r="5" fill="${dark}"/><circle cx="114" cy="192" r="5" fill="${dark}"/>`);
  } else {
    parts.push(`<path d="M68 138 Q100 126 132 138 L136 198 Q100 212 64 198 Z" fill="${outfit}" ${outline}/>`);
  }

  // Species torso details
  if (character.species === 'footballer') {
    parts.push(`<path d="M56 146 Q100 122 144 146 L138 164 Q100 146 62 164 Z" fill="${shade(outfit, 45)}" ${outline}/>`);
    parts.push(`<text x="100" y="192" text-anchor="middle" font-family="Impact, sans-serif" font-size="32" fill="${ink}">${escapeXml(character.number)}</text>`);
  }
  if (character.species === 'superhero') {
    parts.push(`<path d="M100 148 l17 27 -17 27 -17 -27 Z" fill="${shade(outfit, 70)}" ${outline}/>`);
    parts.push(`<text x="100" y="186" text-anchor="middle" font-family="Impact, sans-serif" font-size="24" fill="${dark}">${escapeXml((character.name || '?').trim().charAt(0).toUpperCase() || '?')}</text>`);
  }
  if (character.species === 'monkey') {
    parts.push(`<ellipse cx="100" cy="176" rx="26" ry="24" fill="${shade(skin, 45)}" ${outline}/>`);
  }
  if (character.species === 'ninja') {
    parts.push(`<path d="M66 172 L136 164 L138 178 L68 186 Z" fill="#d92b2b" ${outline}/>`);
  }
  if (character.species === 'wrestler') {
    parts.push(`<path d="M64 190 L136 190 L136 204 L64 204 Z" fill="#3a2a10" ${outline}/>`);
    parts.push(`<ellipse cx="100" cy="197" rx="15" ry="12" fill="#ffcc33" stroke="${OUTLINE}" stroke-width="3"/>`);
  }

  // Arms + mitten hands. Never the same colour as the torso, or they vanish.
  const armColor = character.species === 'monkey' || character.species === 'wrestler'
    ? skin
    : shade(outfit, -28);
  const armWidth = character.species === 'wrestler' ? 19 : 15;
  parts.push(`<g class="arm arm-l">${limb(72, 148, 42, 188, armColor, armWidth)}<circle cx="40" cy="193" r="13" fill="${skin}" ${outline}/></g>`);
  parts.push(`<g class="arm arm-r">${limb(128, 148, 158, 188, armColor, armWidth)}<circle cx="160" cy="193" r="13" fill="${skin}" ${outline}/></g>`);

  return parts.join('');
}

/** Faces arrive from other players' devices, so only allow real image data. */
function safeFace(value) {
  return typeof value === 'string' && /^data:image\/(png|jpeg|jpg|webp|gif);base64,[A-Za-z0-9+/=]+$/.test(value)
    ? value
    : null;
}

function faceCircle(character, uid) {
  const clipId = `clip-${uid}`;
  const face = safeFace(character.face);
  const inner = face
    ? `<image href="${face}" x="${HEAD.cx - HEAD.r}" y="${HEAD.cy - HEAD.r}" width="${HEAD.r * 2}" height="${HEAD.r * 2}" preserveAspectRatio="xMidYMid slice" clip-path="url(#${clipId})"/>`
    : `<circle cx="${HEAD.cx}" cy="${HEAD.cy}" r="${HEAD.r}" fill="${character.skin}"/>
       <text x="${HEAD.cx}" y="${HEAD.cy + 18}" text-anchor="middle" font-size="46" opacity="0.3">?</text>`;

  return `<defs><clipPath id="${clipId}"><circle cx="${HEAD.cx}" cy="${HEAD.cy}" r="${HEAD.r}"/></clipPath></defs>
    <circle cx="${HEAD.cx}" cy="${HEAD.cy}" r="${HEAD.r}" fill="${character.skin}"/>
    ${inner}
    <circle cx="${HEAD.cx}" cy="${HEAD.cy}" r="${HEAD.r}" fill="none" stroke="${OUTLINE}" stroke-width="5"/>`;
}

function earsFor(character) {
  if (character.species !== 'monkey') return '';
  const inner = shade(character.skin, 45);
  const ear = (cx) => `<circle cx="${cx}" cy="${HEAD.cy}" r="18" fill="${character.skin}" stroke="${OUTLINE}" stroke-width="4"/>
      <circle cx="${cx}" cy="${HEAD.cy}" r="9" fill="${inner}"/>`;
  return `<g class="ears">${ear(HEAD.cx - HEAD.r - 5)}${ear(HEAD.cx + HEAD.r + 5)}</g>`;
}

/*
 * Hats sit on the CROWN of the head. The eyes live at y = HEAD.cy - 8 (74), so
 * nothing here is allowed below about y = 66 or it covers the face — which is
 * the whole point of the game.
 */
const CROWN = HEAD.cy - HEAD.r; // 30

function hatFor(character) {
  const c = HEAD.cx;
  const t = CROWN;
  const outfit = character.outfit;
  const dark = shade(outfit, -45);
  const outline = `stroke="${OUTLINE}" stroke-width="4" stroke-linejoin="round"`;

  switch (character.hat) {
    case 'helmet': {
      // A shell with a hole punched in it for the face, so the expression
      // still shows. evenodd turns the two subpaths into a ring.
      const shell = `M${c} ${HEAD.cy} m-61 0 a61 61 0 1 1 122 0 a61 61 0 1 1 -122 0 Z`
        + ` M${c} ${HEAD.cy + 12} m-41 0 a41 47 0 1 0 82 0 a41 47 0 1 0 -82 0 Z`;
      return `<g class="hat">
        <path d="${shell}" fill-rule="evenodd" fill="${outfit}" ${outline}/>
        <rect x="${c - 61}" y="${t + 18}" width="122" height="13" rx="6" fill="${dark}"/>
        <circle cx="${c - 52}" cy="${HEAD.cy + 14}" r="11" fill="${dark}" stroke="${OUTLINE}" stroke-width="3"/>
        <g stroke="#e6e6ef" stroke-width="5" stroke-linecap="round" fill="none">
          <path d="M${c - 33} ${HEAD.cy + 40} q33 16 66 0"/>
          <path d="M${c - 26} ${HEAD.cy + 52} q26 12 52 0"/>
          <path d="M${c} ${HEAD.cy + 34} v22"/>
        </g>
        <circle cx="${c}" cy="${t - 4}" r="7" fill="${dark}" ${outline}/>
      </g>`;
    }
    case 'cap':
      return `<g class="hat">
        <path d="M${c - 52} ${t + 26} Q${c - 50} ${t - 28} ${c} ${t - 28} Q${c + 50} ${t - 28} ${c + 52} ${t + 26} Z" fill="${outfit}" ${outline}/>
        <path d="M${c - 52} ${t + 14} q-30 2 -30 14 q0 10 30 8 z" fill="${dark}" ${outline}/>
        <circle cx="${c}" cy="${t - 30}" r="7" fill="${dark}" ${outline}/>
      </g>`;
    case 'crown':
      return `<g class="hat"><path d="M${c - 44} ${t + 14} l0 -40 l22 20 l22 -30 l22 30 l22 -20 l0 40 z" fill="#ffcc33" ${outline}/>
        <circle cx="${c}" cy="${t - 2}" r="6" fill="#d92b2b" stroke="${OUTLINE}" stroke-width="3"/></g>`;
    case 'propeller':
      return `<g class="hat">
        <path d="M${c - 46} ${t + 22} Q${c - 46} ${t - 26} ${c} ${t - 26} Q${c + 46} ${t - 26} ${c + 46} ${t + 22} Z" fill="#22b573" ${outline}/>
        <path d="M${c - 46} ${t + 22} Q${c - 46} ${t - 26} ${c} ${t - 26} L${c} ${t + 22} Z" fill="#f0a830"/>
        <line x1="${c}" y1="${t - 26}" x2="${c}" y2="${t - 44}" stroke="${OUTLINE}" stroke-width="5"/>
        <g class="propeller"><ellipse cx="${c}" cy="${t - 46}" rx="36" ry="6" fill="#d92b2b" stroke="${OUTLINE}" stroke-width="3"/></g>
      </g>`;
    case 'tophat':
      return `<g class="hat">
        <rect x="${c - 22}" y="${t - 48}" width="44" height="50" rx="4" fill="#1b1b2b" ${outline}/>
        <rect x="${c - 38}" y="${t - 4}" width="76" height="10" rx="5" fill="#1b1b2b" ${outline}/>
        <rect x="${c - 22}" y="${t - 14}" width="44" height="10" fill="#d92b2b"/></g>`;
    case 'headband':
      return `<g class="hat"><rect x="${c - 54}" y="${t + 18}" width="108" height="16" rx="8" fill="#d92b2b" ${outline}/>
        <path d="M${c + 50} ${t + 26} q28 8 36 30 q-24 -6 -36 -14 z" fill="#d92b2b" ${outline}/></g>`;
    case 'antenna':
      return `<g class="hat"><line x1="${c}" y1="${t + 6}" x2="${c}" y2="${t - 34}" stroke="${OUTLINE}" stroke-width="7"/>
        <line x1="${c}" y1="${t + 6}" x2="${c}" y2="${t - 34}" stroke="#8b95a5" stroke-width="4"/>
        <circle class="blink" cx="${c}" cy="${t - 40}" r="10" fill="#ff3b3b" ${outline}/></g>`;
    case 'horns':
      return `<g class="hat">
        <path d="M${c - 32} ${t + 12} q-16 -34 4 -44 q8 24 20 32 z" fill="#d92b2b" ${outline}/>
        <path d="M${c + 32} ${t + 12} q16 -34 -4 -44 q-8 24 -20 32 z" fill="#d92b2b" ${outline}/></g>`;
    case 'halo':
      return `<g class="hat"><ellipse cx="${c}" cy="${t - 28}" rx="36" ry="10" fill="none" stroke="${OUTLINE}" stroke-width="11"/>
        <ellipse cx="${c}" cy="${t - 28}" rx="36" ry="10" fill="none" stroke="#ffe066" stroke-width="6"/></g>`;
    case 'bucket':
      return `<g class="hat"><path d="M${c - 40} ${t - 24} l80 0 l-10 46 l-60 0 z" fill="#9aa7b4" ${outline}/>
        <ellipse cx="${c}" cy="${t - 24}" rx="40" ry="9" fill="#c3ced9" ${outline}/></g>`;
    default:
      return '';
  }
}

/**
 * Face gear comes in two layers. Things you look THROUGH (a hero mask, a beard)
 * go under the cartoon eyes so the expression still reads; things you look AT
 * (sunglasses, a snorkel) go over the top.
 */
function faceGearFor(character, layer) {
  const c = HEAD.cx;
  const eyeY = HEAD.cy - 8;
  const gear = character.faceGear;
  const outline = `stroke="${OUTLINE}" stroke-width="3.5" stroke-linejoin="round"`;

  if (layer === 'under') {
    if (gear === 'mask') {
      return `<g class="gear"><path d="M${c - 49} ${eyeY - 20} q49 -16 98 0 q-7 34 -20 34 q-29 -13 -58 0 q-13 0 -20 -34 z" fill="${shade(character.outfit, -30)}" ${outline}/></g>`;
    }
    if (gear === 'beard') {
      return `<g class="gear"><path d="M${c - 42} ${HEAD.cy + 2} q6 54 42 58 q36 -4 42 -58 q-42 28 -84 0 z" fill="#d5d5df" ${outline}/></g>`;
    }
    return '';
  }

  switch (gear) {
    case 'shades':
      return `<g class="gear"><rect x="${c - 44}" y="${eyeY - 14}" width="38" height="26" rx="9" fill="#141422" ${outline}/>
        <rect x="${c + 6}" y="${eyeY - 14}" width="38" height="26" rx="9" fill="#141422" ${outline}/>
        <rect x="${c - 8}" y="${eyeY - 5}" width="16" height="7" fill="#141422"/></g>`;
    case 'nerd':
      return `<g class="gear"><circle cx="${c - 22}" cy="${eyeY}" r="21" fill="#ffffff" opacity="0.3" stroke="${OUTLINE}" stroke-width="5"/>
        <circle cx="${c + 22}" cy="${eyeY}" r="21" fill="#ffffff" opacity="0.3" stroke="${OUTLINE}" stroke-width="5"/>
        <line x1="${c - 3}" y1="${eyeY}" x2="${c + 3}" y2="${eyeY}" stroke="${OUTLINE}" stroke-width="5"/></g>`;
    case 'mustache':
      return `<g class="gear"><path d="M${c} ${HEAD.cy + 14} q-15 -15 -32 -5 q11 18 32 9 q21 9 32 -9 q-17 -10 -32 5 z" fill="#3a2a18" ${outline}/></g>`;
    case 'unibrow':
      return `<g class="gear"><path d="M${c - 42} ${eyeY - 24} q42 -16 84 0 q-42 -5 -84 0 z" fill="#3a2a18" stroke="#3a2a18" stroke-width="9" stroke-linejoin="round"/></g>`;
    case 'snorkel':
      return `<g class="gear"><rect x="${c - 47}" y="${eyeY - 19}" width="94" height="36" rx="15" fill="#00c8d7" opacity="0.4" stroke="#0d7f89" stroke-width="5"/>
        <path d="M${c + 45} ${eyeY - 15} q24 -6 24 -32" fill="none" stroke="${OUTLINE}" stroke-width="11" stroke-linecap="round"/>
        <path d="M${c + 45} ${eyeY - 15} q24 -6 24 -32" fill="none" stroke="#f0a830" stroke-width="7" stroke-linecap="round"/></g>`;
    default:
      return '';
  }
}

/* ------------------------------------------------------------- expressions */

const EYE = { dx: 21, dy: -8, rx: 12, ry: 13.5 };

function eyes(mood) {
  const c = HEAD.cx;
  const y = HEAD.cy + EYE.dy;
  const L = c - EYE.dx;
  const R = c + EYE.dx;
  const white = (x, ry = EYE.ry) => `<ellipse cx="${x}" cy="${y}" rx="${EYE.rx}" ry="${ry}" fill="#fff" stroke="#1b1b2b" stroke-width="2.5"/>`;
  const pupil = (x, ox = 0, oy = 0, r = 6) => `<circle cx="${x + ox}" cy="${y + oy}" r="${r}" fill="#1b1b2b"/>`;

  switch (mood) {
    case 'hit':
      return `${white(L, 18)}${white(R, 18)}${pupil(L, 0, 0, 9)}${pupil(R, 0, 0, 9)}`;
    case 'ko':
      return `<g stroke="#1b1b2b" stroke-width="3.5" fill="none">
        <path d="M${L} ${y} m-11 0 a11 11 0 1 1 6 10 a7 7 0 1 1 2 -13"/>
        <path d="M${R} ${y} m-11 0 a11 11 0 1 1 6 10 a7 7 0 1 1 2 -13"/></g>`;
    case 'attack':
      return `${white(L, 11)}${white(R, 11)}${pupil(L, 3, 2)}${pupil(R, -3, 2)}
        <path d="M${L - 15} ${y - 17} l28 8" stroke="#1b1b2b" stroke-width="6" stroke-linecap="round"/>
        <path d="M${R + 15} ${y - 17} l-28 8" stroke="#1b1b2b" stroke-width="6" stroke-linecap="round"/>`;
    case 'win':
      return `<g stroke="#1b1b2b" stroke-width="5" fill="none" stroke-linecap="round">
        <path d="M${L - 13} ${y + 4} q13 -18 26 0"/><path d="M${R - 13} ${y + 4} q13 -18 26 0"/></g>`;
    case 'block':
      return `${white(L, 9)}${white(R, 9)}${pupil(L, 0, 0, 5)}${pupil(R, 0, 0, 5)}`;
    case 'talk':
    case 'idle':
    default:
      return `${white(L)}${white(R)}${pupil(L, 1, 1)}${pupil(R, -1, 1)}`;
  }
}

/**
 * @param {string} mood
 * @param {number} open 0..1, drives the mouth while talking
 */
function mouth(mood, open = 0) {
  const c = HEAD.cx;
  const y = HEAD.cy + 26;
  switch (mood) {
    case 'hit':
      return `<ellipse cx="${c}" cy="${y}" rx="15" ry="18" fill="#5c1d1d"/><ellipse cx="${c}" cy="${y + 9}" rx="9" ry="7" fill="#ff6b81"/>`;
    case 'ko':
      return `<path d="M${c - 22} ${y} q11 -12 22 0 q11 12 22 0" fill="none" stroke="#1b1b2b" stroke-width="5" stroke-linecap="round"/>
        <path d="M${c + 6} ${y + 4} q10 20 -2 24 q-10 -6 -6 -24 z" fill="#ff6b81"/>`;
    case 'attack':
      return `<path d="M${c - 26} ${y - 8} q26 -6 52 0 q-8 30 -26 30 q-18 0 -26 -30 z" fill="#5c1d1d"/>
        <path d="M${c - 22} ${y - 6} q22 6 44 0" fill="none" stroke="#fff" stroke-width="6"/>`;
    case 'win':
      return `<path d="M${c - 28} ${y - 8} q28 34 56 0 z" fill="#5c1d1d"/>
        <path d="M${c - 26} ${y - 7} q26 8 52 0" fill="none" stroke="#fff" stroke-width="7"/>`;
    case 'block':
      return `<rect x="${c - 20}" y="${y - 6}" width="40" height="14" rx="4" fill="#fff" stroke="#1b1b2b" stroke-width="2.5"/>
        <line x1="${c - 7}" y1="${y - 6}" x2="${c - 7}" y2="${y + 8}" stroke="#1b1b2b" stroke-width="2"/>
        <line x1="${c + 7}" y1="${y - 6}" x2="${c + 7}" y2="${y + 8}" stroke="#1b1b2b" stroke-width="2"/>`;
    case 'talk': {
      const ry = 4 + open * 20;
      return `<ellipse cx="${c}" cy="${y + 2}" rx="${18 + open * 5}" ry="${ry}" fill="#5c1d1d"/>
        <ellipse cx="${c}" cy="${y + ry - 1}" rx="${9 + open * 3}" ry="${3 + open * 5}" fill="#ff6b81"/>`;
    }
    default:
      return `<path d="M${c - 22} ${y - 4} q22 20 44 0" fill="none" stroke="#1b1b2b" stroke-width="5" stroke-linecap="round"/>`;
  }
}

function escapeXml(value) {
  return String(value ?? '').replace(/[<>&"']/g, (ch) => (
    { '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;', "'": '&apos;' }[ch]
  ));
}

let uidCounter = 0;

const HEAD_PIVOT_Y = HEAD.cy + HEAD.r - 4; // the chin: heads grow upward from here

/**
 * The viewBox is worked out per character instead of being fixed, because a
 * PLANET-sized head is nearly three times the width of a normal one and a
 * fixed box would either clip it or leave normal heads floating in space.
 */
function viewBoxFor(headScale) {
  const s = headScale;
  // Head pivots on its own chin (HEAD_PIVOT_Y) so it always stays attached.
  const topOfHat = HEAD_PIVOT_Y + (CROWN - 46 - HEAD_PIVOT_Y) * s;
  const halfWidth = (HEAD.r + 24) * s;
  const minX = Math.min(24, HEAD.cx - halfWidth) - 8;
  const maxX = Math.max(176, HEAD.cx + halfWidth) + 8;
  const minY = topOfHat - 8;
  const maxY = 266;
  return `${minX} ${minY} ${maxX - minX} ${maxY - minY}`;
}

/**
 * @param {object} character
 * @param {{mood?:string, mouthOpen?:number, facing?:number}} [opts]
 * @returns {string} an <svg> element
 */
export function renderGoof(character, opts = {}) {
  const mood = opts.mood || 'idle';
  const uid = ++uidCounter;
  const headScale = (HEAD_SIZES.find((h) => h.id === character.headSize) || HEAD_SIZES[1]).scale;
  const bodyScale = (BODY_SIZES.find((b) => b.id === character.bodySize) || BODY_SIZES[1]).scale;
  const facing = opts.facing === -1 ? -1 : 1;

  const headTransform = `translate(${HEAD.cx} ${HEAD_PIVOT_Y}) scale(${headScale}) translate(${-HEAD.cx} ${-HEAD_PIVOT_Y})`;
  const bodyTransform = `translate(${HEAD.cx} 250) scale(${bodyScale}) translate(${-HEAD.cx} -250)`;

  return `<svg class="goof goof-${character.species} mood-${mood}" viewBox="${viewBoxFor(headScale)}" preserveAspectRatio="xMidYMax meet" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${escapeXml(character.name)}">
    <g transform="translate(${facing === -1 ? 200 : 0} 0) scale(${facing} 1)">
      <g class="goof-body" transform="${bodyTransform}">${bodyFor(character)}</g>
      <g class="goof-head" transform="${headTransform}">
        ${earsFor(character)}
        ${faceCircle(character, uid)}
        ${faceGearFor(character, 'under')}
        <g class="goof-features">${eyes(mood)}${mouth(mood, opts.mouthOpen || 0)}</g>
        ${faceGearFor(character, 'over')}
        ${hatFor(character)}
      </g>
    </g>
  </svg>`;
}

/** Just the head — used for lobby chips, target buttons and score rows. */
export function renderHead(character, mood = 'idle') {
  const uid = ++uidCounter;
  return `<svg class="goof-head-only" viewBox="16 -22 168 168" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    ${earsFor(character)}
    ${faceCircle(character, uid)}
    ${faceGearFor(character, 'under')}
    <g class="goof-features">${eyes(mood)}${mouth(mood)}</g>
    ${faceGearFor(character, 'over')}
    ${hatFor(character)}
  </svg>`;
}
