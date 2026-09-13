/**
 * Face Booth — grab a photo and crop it into the round head.
 *
 * Two ways in:
 *   - the phone's own camera app, via <input capture>. Works on plain http,
 *     which matters because the family server usually runs without https.
 *   - a live camera preview via getUserMedia, when the page is on https.
 *
 * The crop screen shows eye and mouth guides. Lining the face up with those is
 * what makes the cartoon eyes land in the right place later.
 */

import { h, overlay, toast } from './ui.js';
import { play } from './sfx.js';

const OUTPUT_SIZE = 320;

async function loadBitmap(source) {
  if (window.createImageBitmap) {
    try {
      return await createImageBitmap(source, { imageOrientation: 'from-image' });
    } catch {
      /* Safari < 17 has no imageOrientation option — fall through */
    }
    try {
      return await createImageBitmap(source);
    } catch { /* fall through */ }
  }
  const url = URL.createObjectURL(source);
  try {
    const img = new Image();
    await new Promise((resolve, reject) => {
      img.onload = resolve;
      img.onerror = () => reject(new Error('bad-image'));
      img.src = url;
    });
    return img;
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

/**
 * @returns {Promise<string|null>} a square JPEG data URL, or null if cancelled
 */
export function captureFace() {
  return new Promise((resolve) => {
    const ov = overlay('facebooth');
    let stream = null;

    const finish = (value) => {
      if (stream) stream.getTracks().forEach((t) => t.stop());
      ov.close();
      resolve(value);
    };

    /* ---------------------------------------------------------- pick step */

    function showPicker() {
      if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
      const fileInput = h('input', { type: 'file', accept: 'image/*', capture: 'user', style: { display: 'none' } });
      fileInput.addEventListener('change', async () => {
        const file = fileInput.files?.[0];
        if (!file) return;
        try {
          showCrop(await loadBitmap(file));
        } catch {
          toast('That picture would not open. Try another one.', '\u{1F615}');
        }
      });

      const galleryInput = h('input', { type: 'file', accept: 'image/*', style: { display: 'none' } });
      galleryInput.addEventListener('change', async () => {
        const file = galleryInput.files?.[0];
        if (!file) return;
        try {
          showCrop(await loadBitmap(file));
        } catch {
          toast('That picture would not open. Try another one.', '\u{1F615}');
        }
      });

      const buttons = [
        h('button', { class: 'big-btn', onclick: () => { play('select'); fileInput.click(); } },
          h('span', { class: 'big-btn-emoji' }, '\u{1F4F8}'), 'Take a silly photo'),
        h('button', { class: 'big-btn ghost', onclick: () => { play('select'); galleryInput.click(); } },
          h('span', { class: 'big-btn-emoji' }, '\u{1F5BC}'), 'Pick from photos')
      ];

      if (window.isSecureContext && navigator.mediaDevices?.getUserMedia) {
        buttons.push(
          h('button', { class: 'big-btn ghost', onclick: () => { play('select'); showLiveCamera(); } },
            h('span', { class: 'big-btn-emoji' }, '\u{1F3A5}'), 'Live camera')
        );
      }

      ov.panel.replaceChildren(
        h('h2', { class: 'sheet-title' }, 'Face Booth'),
        h('p', { class: 'sheet-sub' }, 'Pull your goofiest face. This is the head you will fight with.'),
        h('div', { class: 'stack' }, buttons),
        h('button', { class: 'text-btn', onclick: () => finish(null) }, 'Never mind'),
        fileInput,
        galleryInput
      );
    }

    /* -------------------------------------------------------- live camera */

    async function showLiveCamera() {
      const video = h('video', { autoplay: '', playsinline: '', muted: '', class: 'live-cam' });
      ov.panel.replaceChildren(
        h('h2', { class: 'sheet-title' }, 'Say BONK!'),
        h('div', { class: 'cam-wrap' }, video, h('div', { class: 'face-guide' , html: guideSvg() })),
        h('button', { class: 'big-btn', onclick: snap }, h('span', { class: 'big-btn-emoji' }, '\u{1F4F8}'), 'Snap!'),
        h('button', { class: 'text-btn', onclick: showPicker }, 'Back')
      );

      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: 'user', width: { ideal: 720 }, height: { ideal: 720 } },
          audio: false
        });
        video.srcObject = stream;
      } catch {
        toast('The camera said no. Try "Take a silly photo" instead.', '\u{1F937}');
        showPicker();
      }

      async function snap() {
        play('pop');
        const canvas = document.createElement('canvas');
        const size = Math.min(video.videoWidth, video.videoHeight) || 480;
        canvas.width = size;
        canvas.height = size;
        const ctx = canvas.getContext('2d');
        // Mirror it — kids expect to see themselves the way a mirror shows them.
        ctx.translate(size, 0);
        ctx.scale(-1, 1);
        ctx.drawImage(video, (video.videoWidth - size) / 2, (video.videoHeight - size) / 2, size, size, 0, 0, size, size);
        if (stream) { stream.getTracks().forEach((t) => t.stop()); stream = null; }
        const blob = await new Promise((r) => canvas.toBlob(r, 'image/jpeg', 0.92));
        showCrop(await loadBitmap(blob));
      }
    }

    /* --------------------------------------------------------- crop step */

    function showCrop(bitmap) {
      const canvas = h('canvas', { class: 'crop-canvas', width: OUTPUT_SIZE, height: OUTPUT_SIZE });
      const zoom = h('input', { type: 'range', min: '100', max: '320', value: '100', class: 'slider' });

      const view = {
        scale: 1,
        x: 0,
        y: 0,
        base: OUTPUT_SIZE / Math.min(bitmap.width, bitmap.height)
      };

      const ctx = canvas.getContext('2d');

      function draw() {
        ctx.clearRect(0, 0, OUTPUT_SIZE, OUTPUT_SIZE);
        ctx.fillStyle = '#1b1b2b';
        ctx.fillRect(0, 0, OUTPUT_SIZE, OUTPUT_SIZE);
        const scale = view.base * view.scale;
        const w = bitmap.width * scale;
        const hgt = bitmap.height * scale;
        ctx.drawImage(bitmap, OUTPUT_SIZE / 2 - w / 2 + view.x, OUTPUT_SIZE / 2 - hgt / 2 + view.y, w, hgt);
      }

      /* drag + pinch */
      const pointers = new Map();
      let pinchStart = null;

      canvas.addEventListener('pointerdown', (e) => {
        canvas.setPointerCapture(e.pointerId);
        pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      });
      canvas.addEventListener('pointermove', (e) => {
        if (!pointers.has(e.pointerId)) return;
        const prev = pointers.get(e.pointerId);
        pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

        const rect = canvas.getBoundingClientRect();
        const ratio = OUTPUT_SIZE / rect.width;

        if (pointers.size === 1) {
          view.x += (e.clientX - prev.x) * ratio;
          view.y += (e.clientY - prev.y) * ratio;
          draw();
        } else if (pointers.size === 2) {
          const [a, b] = [...pointers.values()];
          const dist = Math.hypot(a.x - b.x, a.y - b.y);
          if (pinchStart == null) pinchStart = { dist, scale: view.scale };
          else {
            view.scale = Math.max(1, Math.min(3.2, (pinchStart.scale * dist) / pinchStart.dist));
            zoom.value = String(Math.round(view.scale * 100));
            draw();
          }
        }
      });
      const release = (e) => {
        pointers.delete(e.pointerId);
        if (pointers.size < 2) pinchStart = null;
      };
      canvas.addEventListener('pointerup', release);
      canvas.addEventListener('pointercancel', release);

      zoom.addEventListener('input', () => {
        view.scale = Number(zoom.value) / 100;
        draw();
      });

      ov.panel.replaceChildren(
        h('h2', { class: 'sheet-title' }, 'Line up your face'),
        h('p', { class: 'sheet-sub' }, 'Drag and pinch until your eyes and mouth sit on the dotted marks.'),
        h('div', { class: 'crop-wrap' }, canvas, h('div', { class: 'face-guide', html: guideSvg() })),
        h('label', { class: 'slider-row' }, h('span', {}, '\u{1F50D}'), zoom),
        h('div', { class: 'row' },
          h('button', { class: 'big-btn', onclick: done }, h('span', { class: 'big-btn-emoji' }, '\u{2705}'), "That's the one!"),
          h('button', { class: 'big-btn ghost', onclick: showPicker }, h('span', { class: 'big-btn-emoji' }, '\u{1F504}'), 'Retake')
        )
      );
      draw();

      function done() {
        play('ding');
        finish(canvas.toDataURL('image/jpeg', 0.82));
      }
    }

    showPicker();
  });
}

/** Dotted eye/mouth marks that match where the cartoon features get drawn. */
function guideSvg() {
  // characters.js puts the head at centre (100,82) r52, the eyes at
  // (+/-21, -8) and the mouth at (0, +26). Those are re-expressed here as
  // percentages of the crop square so the two files stay in step.
  const pct = (v) => ((v + 52) / 104) * 100;
  const eyeY = pct(-8);
  const mouthY = pct(26);
  return `<svg viewBox="0 0 100 100" preserveAspectRatio="none" class="guide-svg">
    <circle cx="50" cy="50" r="49" fill="none" stroke="#fff" stroke-width="1.2" stroke-dasharray="3 3" opacity="0.85"/>
    <ellipse cx="${pct(-21)}" cy="${eyeY}" rx="12" ry="14" fill="none" stroke="#ffd93d" stroke-width="1.4" stroke-dasharray="3 2"/>
    <ellipse cx="${pct(21)}" cy="${eyeY}" rx="12" ry="14" fill="none" stroke="#ffd93d" stroke-width="1.4" stroke-dasharray="3 2"/>
    <path d="M${pct(-20)} ${mouthY} q${(20 / 104) * 100} ${(14 / 104) * 100} ${(40 / 104) * 100} 0"
          fill="none" stroke="#ff6b6b" stroke-width="1.4" stroke-dasharray="3 2"/>
  </svg>`;
}
