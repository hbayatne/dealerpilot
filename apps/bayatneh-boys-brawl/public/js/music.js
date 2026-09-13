/**
 * The soundtrack. Like the sound effects, every note is generated at runtime —
 * there is nothing to download and nothing to keep in sync.
 *
 * A lookahead scheduler queues notes a fraction of a second early against the
 * audio clock, because setInterval on its own is far too jittery to keep time
 * with (and phones throttle it hard when the screen dims).
 */

import { audioContext } from './sfx.js';

const SEMITONES = { C: 0, 'C#': 1, D: 2, 'D#': 3, E: 4, F: 5, 'F#': 6, G: 7, 'G#': 8, A: 9, 'A#': 10, B: 11 };

/** "A4" -> 440 */
function hz(note) {
  const parts = /^([A-G]#?)(-?\d)$/.exec(note);
  if (!parts) return 440;
  const midi = SEMITONES[parts[1]] + (Number(parts[2]) + 1) * 12;
  return 440 * Math.pow(2, (midi - 69) / 12);
}

/** Turns {step: note} into a 32-slot array, so patterns stay readable. */
function line(spec, steps = 32) {
  const out = new Array(steps).fill(null);
  for (const [at, note] of Object.entries(spec)) out[Number(at)] = note;
  return out;
}

/** Turns [0, 4, 8] into a 32-slot array of 1s and 0s. */
function hits(list, steps = 32) {
  const out = new Array(steps).fill(0);
  for (const at of list) out[at] = 1;
  return out;
}

const EVERY_OTHER = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30];

const TRACKS = {
  // Bouncy, major, oom-pah bass. Plays on the menus.
  menu: {
    bpm: 126,
    steps: 32,
    bass: line({
      0: 'C2', 3: 'C3', 4: 'G2', 6: 'C3',
      8: 'G1', 11: 'G2', 12: 'D2', 14: 'G2',
      16: 'A1', 19: 'A2', 20: 'E2', 22: 'A2',
      24: 'F1', 27: 'F2', 28: 'C2', 30: 'F2'
    }),
    lead: line({
      0: 'E5', 2: 'G5', 4: 'A5', 6: 'G5',
      8: 'D5', 10: 'B4', 12: 'D5', 15: 'E5',
      16: 'C5', 18: 'E5', 20: 'A5', 22: 'E5',
      24: 'F5', 26: 'A5', 28: 'G5', 31: 'E5'
    }),
    kick: hits([0, 4, 6, 8, 12, 16, 20, 22, 24, 28]),
    snare: hits([4, 12, 20, 28]),
    hat: hits(EVERY_OTHER)
  },

  // Faster, minor, driving eighths. Plays in the arena.
  fight: {
    bpm: 148,
    steps: 32,
    bass: line({
      0: 'A1', 2: 'A1', 4: 'A1', 6: 'E2',
      8: 'F1', 10: 'F1', 12: 'F1', 14: 'C2',
      16: 'G1', 18: 'G1', 20: 'G1', 22: 'D2',
      24: 'A1', 26: 'A1', 28: 'C2', 30: 'E2'
    }),
    lead: line({
      0: 'A4', 3: 'C5', 4: 'E5', 6: 'D5',
      8: 'C5', 11: 'A4', 12: 'C5', 14: 'F5',
      16: 'D5', 19: 'B4', 20: 'D5', 22: 'G5',
      24: 'E5', 26: 'D5', 28: 'C5', 30: 'B4'
    }),
    kick: hits([0, 2, 4, 8, 10, 12, 16, 18, 20, 24, 26, 28, 30]),
    snare: hits([4, 12, 20, 28]),
    hat: hits([...EVERY_OTHER, 7, 15, 23, 31])
  },

  // Slow, silly, sparse. Plays behind the winner screen.
  victory: {
    bpm: 110,
    steps: 16,
    bass: line({ 0: 'C2', 4: 'F2', 8: 'G2', 12: 'C2' }, 16),
    lead: line({ 0: 'C5', 2: 'E5', 4: 'G5', 6: 'C6', 8: 'B5', 10: 'G5', 12: 'C6', 14: 'G5' }, 16),
    kick: hits([0, 4, 8, 12], 16),
    snare: hits([2, 6, 10, 14], 16),
    hat: hits([0, 2, 4, 6, 8, 10, 12, 14], 16)
  }
};

const LOOKAHEAD_SECONDS = 0.15;
const TICK_MS = 25;

let musicGain = null;
let noiseBuffer = null;
let timer = null;
let track = null;
let trackName = null;
let step = 0;
let nextStepTime = 0;
let volume = 0.22;
let ducked = false;

function setup() {
  const ctx = audioContext();
  if (!ctx) return null;
  if (!musicGain) {
    musicGain = ctx.createGain();
    musicGain.gain.value = 0;
    musicGain.connect(ctx.destination);
  }
  if (!noiseBuffer) {
    const frames = Math.floor(ctx.sampleRate * 0.4);
    noiseBuffer = ctx.createBuffer(1, frames, ctx.sampleRate);
    const data = noiseBuffer.getChannelData(0);
    for (let i = 0; i < frames; i++) data[i] = Math.random() * 2 - 1;
  }
  return ctx;
}

/* ------------------------------------------------------------- the voices */

function envelope(ctx, at, peak, attack, hold, release) {
  const g = ctx.createGain();
  g.gain.setValueAtTime(0.0001, at);
  g.gain.exponentialRampToValueAtTime(peak, at + attack);
  g.gain.setValueAtTime(peak, at + attack + hold);
  g.gain.exponentialRampToValueAtTime(0.0001, at + attack + hold + release);
  g.connect(musicGain);
  return g;
}

function bassVoice(ctx, at, note) {
  const osc = ctx.createOscillator();
  osc.type = 'triangle';
  osc.frequency.value = hz(note);
  const filter = ctx.createBiquadFilter();
  filter.type = 'lowpass';
  filter.frequency.value = 900;
  osc.connect(filter);
  filter.connect(envelope(ctx, at, 0.55, 0.008, 0.05, 0.16));
  osc.start(at);
  osc.stop(at + 0.3);
}

function leadVoice(ctx, at, note) {
  const frequency = hz(note);
  const gain = envelope(ctx, at, 0.16, 0.006, 0.04, 0.2);
  const filter = ctx.createBiquadFilter();
  filter.type = 'lowpass';
  filter.frequency.setValueAtTime(4200, at);
  filter.frequency.exponentialRampToValueAtTime(1400, at + 0.22);
  filter.connect(gain);

  // Two slightly detuned squares — the cheap way to sound like a toy.
  for (const cents of [-6, 6]) {
    const osc = ctx.createOscillator();
    osc.type = 'square';
    osc.frequency.value = frequency;
    osc.detune.value = cents;
    osc.connect(filter);
    osc.start(at);
    osc.stop(at + 0.32);
  }
}

function kickVoice(ctx, at) {
  const osc = ctx.createOscillator();
  osc.type = 'sine';
  osc.frequency.setValueAtTime(150, at);
  osc.frequency.exponentialRampToValueAtTime(45, at + 0.11);
  osc.connect(envelope(ctx, at, 0.75, 0.004, 0.02, 0.12));
  osc.start(at);
  osc.stop(at + 0.2);
}

function noiseVoice(ctx, at, { cutoff, peak, length, type = 'highpass' }) {
  const src = ctx.createBufferSource();
  src.buffer = noiseBuffer;
  const filter = ctx.createBiquadFilter();
  filter.type = type;
  filter.frequency.value = cutoff;
  src.connect(filter);
  filter.connect(envelope(ctx, at, peak, 0.003, 0.005, length));
  src.start(at);
  src.stop(at + length + 0.05);
}

/* --------------------------------------------------------------- sequencer */

function playStep(ctx, index, at) {
  if (track.bass[index]) bassVoice(ctx, at, track.bass[index]);
  if (track.lead[index]) leadVoice(ctx, at, track.lead[index]);
  if (track.kick[index]) kickVoice(ctx, at);
  if (track.snare[index]) noiseVoice(ctx, at, { cutoff: 1400, peak: 0.28, length: 0.1 });
  if (track.hat[index]) {
    noiseVoice(ctx, at, { cutoff: 7500, peak: index % 4 === 0 ? 0.09 : 0.05, length: 0.025 });
  }
}

function tick() {
  const ctx = setup();
  if (!ctx || !track) return;

  const secondsPerStep = 60 / track.bpm / 4;
  // A backgrounded tab starves the timer; rather than machine-gun the backlog,
  // pick the clock back up from now.
  if (nextStepTime < ctx.currentTime) nextStepTime = ctx.currentTime + 0.03;

  while (nextStepTime < ctx.currentTime + LOOKAHEAD_SECONDS) {
    playStep(ctx, step, nextStepTime);
    nextStepTime += secondsPerStep;
    step = (step + 1) % track.steps;
  }
}

/* ------------------------------------------------------------------- api */

function applyVolume() {
  if (!musicGain) return;
  const ctx = audioContext();
  const target = ducked ? volume * 0.15 : volume;
  musicGain.gain.cancelScheduledValues(ctx.currentTime);
  musicGain.gain.setTargetAtTime(target, ctx.currentTime, 0.08);
}

/** Starts a track, or switches to it. Re-calling with the same name is a no-op. */
export function playMusic(name) {
  if (!TRACKS[name]) return;
  if (trackName === name && timer) return;
  const ctx = setup();
  if (!ctx) return;

  track = TRACKS[name];
  trackName = name;
  step = 0;
  nextStepTime = ctx.currentTime + 0.08;

  if (!timer) timer = setInterval(tick, TICK_MS);
  applyVolume();
  tick();
}

export function stopMusic() {
  clearInterval(timer);
  timer = null;
  track = null;
  trackName = null;
  if (musicGain) {
    const ctx = audioContext();
    musicGain.gain.cancelScheduledValues(ctx.currentTime);
    musicGain.gain.setTargetAtTime(0, ctx.currentTime, 0.05);
  }
}

export function currentTrack() {
  return trackName;
}

/** 0 silences the music without stopping it. */
export function setMusicVolume(value) {
  volume = Math.max(0, Math.min(1, value));
  applyVolume();
}

/** Drops the music right down — used while a microphone is recording. */
export function duckMusic(on) {
  ducked = Boolean(on);
  applyVolume();
}
