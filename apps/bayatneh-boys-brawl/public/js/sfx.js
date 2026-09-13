/**
 * Every sound in the game is generated on the fly with the Web Audio API, so
 * there are no audio files to download and nothing to keep in sync.
 */

let ctx = null;
let master = null;
let muted = false;

function audio() {
  if (!ctx) {
    const Ctor = window.AudioContext || window.webkitAudioContext;
    if (!Ctor) return null;
    ctx = new Ctor();
    master = ctx.createGain();
    master.gain.value = 0.55;
    master.connect(ctx.destination);
  }
  // iOS suspends the context until a user gesture touches it.
  if (ctx.state === 'suspended') ctx.resume();
  return ctx;
}

/** Call from a tap handler once, so later sounds are allowed to play. */
export function unlockAudio() {
  const c = audio();
  if (!c) return;
  const buf = c.createBuffer(1, 1, 22050);
  const src = c.createBufferSource();
  src.buffer = buf;
  src.connect(master);
  src.start(0);
}

export function setMuted(value) {
  muted = value;
  if (master) master.gain.value = value ? 0 : 0.55;
}

export function isMuted() {
  return muted;
}

export function audioContext() {
  return audio();
}

export function masterOut() {
  audio();
  return master;
}

function noiseBuffer(c, seconds) {
  const frames = Math.floor(c.sampleRate * seconds);
  const buf = c.createBuffer(1, frames, c.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < frames; i++) data[i] = Math.random() * 2 - 1;
  return buf;
}

function envGain(c, at, peak, attack, decay) {
  const g = c.createGain();
  g.gain.setValueAtTime(0.0001, at);
  g.gain.exponentialRampToValueAtTime(peak, at + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, at + attack + decay);
  g.connect(master);
  return g;
}

function tone(type, from, to, at, duration, peak = 0.3) {
  const c = audio();
  if (!c) return;
  const osc = c.createOscillator();
  osc.type = type;
  osc.frequency.setValueAtTime(from, at);
  osc.frequency.exponentialRampToValueAtTime(Math.max(20, to), at + duration);
  osc.connect(envGain(c, at, peak, 0.01, duration));
  osc.start(at);
  osc.stop(at + duration + 0.05);
}

function burst(at, duration, filterFrom, filterTo, peak = 0.5) {
  const c = audio();
  if (!c) return;
  const src = c.createBufferSource();
  src.buffer = noiseBuffer(c, duration + 0.05);
  const filter = c.createBiquadFilter();
  filter.type = 'bandpass';
  filter.Q.value = 1.1;
  filter.frequency.setValueAtTime(filterFrom, at);
  filter.frequency.exponentialRampToValueAtTime(Math.max(60, filterTo), at + duration);
  src.connect(filter);
  filter.connect(envGain(c, at, peak, 0.005, duration));
  src.start(at);
  src.stop(at + duration + 0.05);
}

const SOUNDS = {
  slap() {
    const t = audio().currentTime;
    burst(t, 0.09, 3200, 700, 0.6);
    tone('triangle', 300, 90, t, 0.12, 0.25);
  },
  punch() {
    const t = audio().currentTime;
    burst(t, 0.14, 1200, 200, 0.55);
    tone('sine', 160, 50, t, 0.2, 0.4);
  },
  splat() {
    const t = audio().currentTime;
    burst(t, 0.22, 900, 160, 0.5);
    tone('sawtooth', 220, 60, t + 0.02, 0.25, 0.2);
  },
  fart() {
    const c = audio();
    const t = c.currentTime;
    const osc = c.createOscillator();
    osc.type = 'sawtooth';
    const lfo = c.createOscillator();
    const lfoGain = c.createGain();
    lfo.frequency.value = 22;
    lfoGain.gain.value = 45;
    lfo.connect(lfoGain);
    lfoGain.connect(osc.frequency);
    osc.frequency.setValueAtTime(120, t);
    osc.frequency.exponentialRampToValueAtTime(55, t + 0.45);
    const filter = c.createBiquadFilter();
    filter.type = 'lowpass';
    filter.frequency.value = 900;
    osc.connect(filter);
    filter.connect(envGain(c, t, 0.45, 0.02, 0.45));
    osc.start(t); lfo.start(t);
    osc.stop(t + 0.55); lfo.stop(t + 0.55);
  },
  boing() {
    const c = audio();
    const t = c.currentTime;
    const osc = c.createOscillator();
    osc.type = 'sine';
    osc.frequency.setValueAtTime(600, t);
    for (let i = 0; i < 7; i++) {
      osc.frequency.exponentialRampToValueAtTime(i % 2 ? 200 : 520 - i * 45, t + 0.05 + i * 0.055);
    }
    osc.connect(envGain(c, t, 0.35, 0.01, 0.45));
    osc.start(t);
    osc.stop(t + 0.55);
  },
  whoosh() {
    burst(audio().currentTime, 0.28, 400, 3000, 0.28);
  },
  zap() {
    const t = audio().currentTime;
    tone('square', 1400, 180, t, 0.22, 0.22);
    burst(t, 0.16, 4000, 900, 0.28);
  },
  thud() {
    const t = audio().currentTime;
    tone('sine', 110, 35, t, 0.3, 0.5);
    burst(t, 0.1, 500, 90, 0.3);
  },
  ding() {
    const t = audio().currentTime;
    tone('sine', 1320, 1300, t, 0.5, 0.25);
    tone('sine', 1980, 1950, t, 0.4, 0.12);
  },
  select() {
    tone('square', 660, 900, audio().currentTime, 0.07, 0.15);
  },
  no() {
    tone('square', 240, 150, audio().currentTime, 0.16, 0.2);
  },
  countdown() {
    tone('square', 520, 520, audio().currentTime, 0.14, 0.22);
  },
  cheer() {
    const c = audio();
    const t = c.currentTime;
    [523, 659, 784, 1047].forEach((f, i) => tone('triangle', f, f, t + i * 0.09, 0.2, 0.24));
    burst(t + 0.2, 0.9, 1800, 700, 0.16);
  },
  lose() {
    const c = audio();
    const t = c.currentTime;
    [392, 349, 311, 262].forEach((f, i) => tone('sawtooth', f, f * 0.98, t + i * 0.15, 0.24, 0.2));
  },
  block() {
    const t = audio().currentTime;
    tone('square', 900, 640, t, 0.1, 0.18);
    burst(t, 0.06, 2600, 1600, 0.2);
  },
  pop() {
    tone('sine', 900, 300, audio().currentTime, 0.08, 0.25);
  }
};

export function play(name) {
  if (muted) return;
  const c = audio();
  if (!c || !SOUNDS[name]) return;
  try {
    SOUNDS[name]();
  } catch {
    /* a failed sound effect should never stop the fight */
  }
}
