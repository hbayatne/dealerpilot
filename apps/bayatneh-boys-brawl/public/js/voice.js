/**
 * The Talking Tom part: record a few seconds of a kid yelling, then play it
 * back through their character's voice.
 *
 * Pitch shifting is done the cheap and cheerful way — resampling with
 * playbackRate — because the chipmunk/slow-monster artefacts ARE the joke.
 */

import { audioContext, masterOut } from './sfx.js';

export const VOICES = {
  chipmunk: { name: 'Chipmunk', emoji: '\u{1F43F}', rate: 1.65, speechPitch: 2, speechRate: 1.25 },
  squeak:   { name: 'Squeaky Mouse', emoji: '\u{1F42D}', rate: 2.0, speechPitch: 2, speechRate: 1.5 },
  coach:    { name: 'Loud Coach', emoji: '\u{1F4E2}', rate: 0.95, speechPitch: 0.7, speechRate: 1.05, gain: 1.5, distort: 0.4 },
  hero:     { name: 'Movie Hero', emoji: '\u{1F9B8}', rate: 0.84, speechPitch: 0.55, speechRate: 0.9, echo: 0.35 },
  robot:    { name: 'Robot', emoji: '\u{1F916}', rate: 0.92, speechPitch: 0.4, speechRate: 0.85, ring: 62 },
  sneaky:   { name: 'Sneaky Whisper', emoji: '\u{1F977}', rate: 1.12, speechPitch: 1.4, speechRate: 1.1, highpass: 900, gain: 1.4 },
  giant:    { name: 'Giant', emoji: '\u{1F9CC}', rate: 0.62, speechPitch: 0.2, speechRate: 0.75 },
  monster:  { name: 'Swamp Monster', emoji: '\u{1F479}', rate: 0.5, speechPitch: 0.1, speechRate: 0.7, distort: 0.6 },
  normal:   { name: 'Just Me', emoji: '\u{1F604}', rate: 1, speechPitch: 1, speechRate: 1 }
};

export const MAX_RECORD_MS = 5000;

/** Mic access needs https (or localhost). Everything else works without it. */
export function canRecord() {
  return Boolean(window.isSecureContext && navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
}

function pickMimeType() {
  const options = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
  for (const type of options) {
    if (MediaRecorder.isTypeSupported?.(type)) return type;
  }
  return '';
}

let activeRecorder = null;

/** Anything shorter than this was a fumbled tap, not a sentence. */
const MIN_RECORD_MS = 400;

/**
 * Starts recording and hands back a controller IMMEDIATELY — before the
 * microphone has actually opened.
 *
 * That matters more than it looks. getUserMedia takes a moment, and the very
 * first hold also puts a permission prompt on screen. This used to be an
 * async function, so a kid who let go during that gap got back nothing to
 * stop: the recorder started afterwards with no handle on it, ran the full
 * five seconds, and then played back a take nobody asked for — and the next
 * hold stopped that orphan instead of its own take, so every recording after
 * it was one behind. Stopping before the stream arrives now simply cancels.
 *
 * @param {(blob: Blob|null, info: {ms: number, reason?: string}) => void} onStop
 * @param {{onStart?: () => void, onError?: (err: Error) => void}} [hooks]
 */
export function startRecording(onStop, { onStart, onError } = {}) {
  let stopped = false;          // stop() was asked for, whenever that happened
  let settled = false;          // onStop has been called exactly once
  let recorder = null;
  let startedAt = 0;

  const finish = (blob, info) => {
    if (settled) return;
    settled = true;
    activeRecorder = null;
    onStop(blob, info);
  };

  if (!canRecord()) {
    // Report asynchronously so the caller always gets its controller first.
    queueMicrotask(() => onError?.(new Error('no-mic')));
    return { stop() {}, get active() { return false; } };
  }

  navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
  }).then((stream) => {
    // Let go while the microphone was opening: bin the stream and say nothing.
    if (stopped) {
      stream.getTracks().forEach((t) => t.stop());
      finish(null, { ms: 0, reason: 'cancelled' });
      return;
    }

    const mimeType = pickMimeType();
    recorder = new MediaRecorder(stream, mimeType ? { mimeType, audioBitsPerSecond: 48000 } : undefined);
    const chunks = [];
    let timer = null;

    recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data); };
    recorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      clearTimeout(timer);
      const ms = Date.now() - startedAt;
      const blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
      if (ms < MIN_RECORD_MS) finish(null, { ms, reason: 'too-short' });
      else if (!blob.size) finish(null, { ms, reason: 'empty' });
      else finish(blob, { ms });
    };
    recorder.onerror = () => {
      stream.getTracks().forEach((t) => t.stop());
      clearTimeout(timer);
      finish(null, { ms: Date.now() - startedAt, reason: 'failed' });
    };

    startedAt = Date.now();
    recorder.start();
    activeRecorder = recorder;
    onStart?.();
    timer = setTimeout(() => { if (recorder.state === 'recording') recorder.stop(); }, MAX_RECORD_MS);
  }).catch((err) => {
    finish(null, { ms: 0, reason: 'denied' });
    onError?.(err instanceof Error ? err : new Error('mic-failed'));
  });

  return {
    stop() {
      if (stopped) return;
      stopped = true;
      if (recorder && recorder.state === 'recording') recorder.stop();
    },
    get active() { return !stopped && Boolean(recorder) && recorder.state === 'recording'; }
  };
}

export function stopRecording() {
  if (activeRecorder && activeRecorder.state === 'recording') activeRecorder.stop();
}

/* ------------------------------------------------------- clip encode/decode */

export function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

async function dataUrlToArrayBuffer(dataUrl) {
  const res = await fetch(dataUrl);
  return res.arrayBuffer();
}

const decodeCache = new Map();

async function decode(dataUrl) {
  if (decodeCache.has(dataUrl)) return decodeCache.get(dataUrl);
  const ctx = audioContext();
  if (!ctx) return null;
  const buffer = await ctx.decodeAudioData(await dataUrlToArrayBuffer(dataUrl));
  if (decodeCache.size > 12) decodeCache.clear();
  decodeCache.set(dataUrl, buffer);
  return buffer;
}

function distortionCurve(amount) {
  const n = 1024;
  const curve = new Float32Array(n);
  const k = amount * 60;
  for (let i = 0; i < n; i++) {
    const x = (i * 2) / n - 1;
    curve[i] = ((3 + k) * x * 20 * Math.PI) / (Math.PI + k * Math.abs(x));
  }
  return curve;
}

/**
 * Plays a recorded clip in a character's voice.
 * @param {string} dataUrl
 * @param {string} voiceId
 * @param {(level:number)=>void} [onLevel] 0..1, for animating the mouth
 * @returns {Promise<void>} resolves when playback finishes
 */
export async function playClip(dataUrl, voiceId, onLevel) {
  const ctx = audioContext();
  if (!ctx) return;
  const buffer = await decode(dataUrl);
  if (!buffer) return;

  const voice = VOICES[voiceId] || VOICES.normal;
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.playbackRate.value = voice.rate;

  /** @type {AudioNode} */
  let node = source;
  /** Oscillators that have to be stopped when the clip finishes. */
  const stopWithSource = [];

  if (voice.highpass) {
    const hp = ctx.createBiquadFilter();
    hp.type = 'highpass';
    hp.frequency.value = voice.highpass;
    node.connect(hp);
    node = hp;
  }

  if (voice.distort) {
    const shaper = ctx.createWaveShaper();
    shaper.curve = distortionCurve(voice.distort);
    shaper.oversample = '2x';
    node.connect(shaper);
    node = shaper;
  }

  if (voice.ring) {
    // Ring modulation: a gain node whose gain is swung around zero by an
    // oscillator. Classic tinny robot.
    const ring = ctx.createGain();
    ring.gain.value = 0;
    const osc = ctx.createOscillator();
    osc.frequency.value = voice.ring;
    osc.connect(ring.gain);
    osc.start();
    // Tracked rather than hung off source.onended: the promise below owns that
    // handler, and assigning it there would leave this oscillator running for
    // the rest of the session, one more every time a robot spoke.
    stopWithSource.push(osc);
    node.connect(ring);
    node = ring;
  }

  const out = ctx.createGain();
  out.gain.value = voice.gain || 1;
  node.connect(out);

  if (voice.echo) {
    const delay = ctx.createDelay();
    delay.delayTime.value = 0.16;
    const feedback = ctx.createGain();
    feedback.gain.value = voice.echo;
    out.connect(delay);
    delay.connect(feedback);
    feedback.connect(delay);
    delay.connect(masterOut());
  }

  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  out.connect(analyser);
  out.connect(masterOut());

  const data = new Uint8Array(analyser.fftSize);
  let running = true;

  if (onLevel) {
    const tick = () => {
      if (!running) return;
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) {
        const v = (data[i] - 128) / 128;
        sum += v * v;
      }
      onLevel(Math.min(1, Math.sqrt(sum / data.length) * 4.5));
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }

  return new Promise((resolve) => {
    source.onended = () => {
      running = false;
      for (const osc of stopWithSource) {
        try { osc.stop(); } catch { /* already stopped */ }
      }
      onLevel?.(0);
      resolve();
    };
    source.start();
  });
}

/* ----------------------------------------------------------------- speaking */

let speechReady = false;

export function canSpeak() {
  return Boolean(window.speechSynthesis && window.SpeechSynthesisUtterance);
}

/** Says text out loud in a character's voice. No microphone needed. */
export function speak(text, voiceId, onLevel) {
  if (!canSpeak() || !text) return Promise.resolve();
  const voice = VOICES[voiceId] || VOICES.normal;

  return new Promise((resolve) => {
    try {
      if (!speechReady) { window.speechSynthesis.cancel(); speechReady = true; }
      const utter = new SpeechSynthesisUtterance(text);
      utter.pitch = voice.speechPitch;
      utter.rate = voice.speechRate;
      utter.volume = 1;

      // No real amplitude to read from speech synthesis, so fake a flapping
      // mouth for as long as it is talking.
      let flapping = true;
      if (onLevel) {
        const flap = () => {
          if (!flapping) return;
          onLevel(0.25 + Math.random() * 0.75);
          setTimeout(flap, 90);
        };
        flap();
      }
      const done = () => {
        flapping = false;
        onLevel?.(0);
        resolve();
      };
      utter.onend = done;
      utter.onerror = done;
      window.speechSynthesis.speak(utter);
      // Safari sometimes never fires onend. Belt and braces.
      setTimeout(done, Math.min(9000, 1600 + text.length * 110));
    } catch {
      resolve();
    }
  });
}

export function stopSpeaking() {
  try { window.speechSynthesis?.cancel(); } catch { /* ignore */ }
}
