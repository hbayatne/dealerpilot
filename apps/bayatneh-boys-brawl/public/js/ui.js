/** Small DOM helpers so the rest of the code can stay about the game. */

export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'html') el.innerHTML = value;
    else if (key === 'style' && typeof value === 'object') Object.assign(el.style, value);
    else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else el.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat(3)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export const qs = (sel, root = document) => root.querySelector(sel);
export const qsa = (sel, root = document) => [...root.querySelectorAll(sel)];

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

/** A full-screen layer. Returns { root, close }. */
export function overlay(className = '') {
  const panel = h('div', { class: 'sheet' });
  const root = h('div', { class: `overlay ${className}` }, panel);
  document.body.append(root);
  requestAnimationFrame(() => root.classList.add('is-open'));
  return {
    root,
    panel,
    close() {
      root.classList.remove('is-open');
      setTimeout(() => root.remove(), 220);
    }
  };
}

let toastTimer = null;

export function toast(message, emoji = '') {
  let bar = qs('#toast');
  if (!bar) {
    bar = h('div', { id: 'toast', class: 'toast' });
    document.body.append(bar);
  }
  bar.textContent = emoji ? `${emoji} ${message}` : message;
  bar.classList.add('is-on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => bar.classList.remove('is-on'), 2400);
}

/** Comic-book word that pops out of a point and floats away. */
export function popText(container, text, { x = 50, y = 40, tone = 'hit' } = {}) {
  const node = h('div', { class: `pop pop-${tone}`, style: { left: `${x}%`, top: `${y}%` } }, text);
  container.append(node);
  setTimeout(() => node.remove(), 900);
}

export function confetti(container, count = 34) {
  const colors = ['#ffd93d', '#ff6b6b', '#4dd4ac', '#5b8cff', '#ff9ff3', '#ffa62b'];
  for (let i = 0; i < count; i++) {
    const bit = h('div', {
      class: 'confetti',
      style: {
        left: `${Math.random() * 100}%`,
        background: colors[i % colors.length],
        animationDelay: `${Math.random() * 0.5}s`,
        animationDuration: `${1.4 + Math.random() * 1.2}s`,
        transform: `rotate(${Math.random() * 360}deg)`
      }
    });
    container.append(bit);
    setTimeout(() => bit.remove(), 3000);
  }
}

export function shake(el, strength = 'normal') {
  el.classList.remove('shake-normal', 'shake-big');
  void el.offsetWidth; // restart the animation
  el.classList.add(strength === 'big' ? 'shake-big' : 'shake-normal');
}
