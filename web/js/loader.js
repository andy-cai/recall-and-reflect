// The wait as a tiny ritual: scattered points (things you know) find each
// other, link into a brief constellation, breathe once, and dissolve — a new
// figure every cycle, so no two waits look alike. This is the app's only
// loading animation; it replaces the spinner on every page load.
//
// Quiet by design: hairline links, slow easings, the single accent color.
// Honors prefers-reduced-motion with one still constellation.
import { el } from './store.js';

const NS = 'http://www.w3.org/2000/svg';
const W = 180, H = 110;

const rnd = (a, b) => a + Math.random() * (b - a);
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// Spread n points with breathing room, then order them as a nearest-neighbor
// chain so the links read as a figure instead of a scribble.
function constellation(n) {
  const pts = [];
  let guard = 0;
  while (pts.length < n && guard++ < 400) {
    const p = { x: rnd(16, W - 16), y: rnd(14, H - 14) };
    if (pts.every(q => Math.hypot(p.x - q.x, p.y - q.y) > 30)) pts.push(p);
  }
  const chain = [pts.shift()];
  while (pts.length) {
    const last = chain[chain.length - 1];
    pts.sort((a, b) => Math.hypot(a.x - last.x, a.y - last.y) - Math.hypot(b.x - last.x, b.y - last.y));
    chain.push(pts.shift());
  }
  return chain;
}

function dot(p, r) {
  const c = document.createElementNS(NS, 'circle');
  c.setAttribute('cx', p.x); c.setAttribute('cy', p.y); c.setAttribute('r', r);
  return c;
}

function link(a, b) {
  const l = document.createElementNS(NS, 'line');
  l.setAttribute('x1', a.x); l.setAttribute('y1', a.y);
  l.setAttribute('x2', b.x); l.setAttribute('y2', b.y);
  return l;
}

export function loaderEl() {
  const node = el('div', { class: 'loader', role: 'status', 'aria-label': 'Loading' });
  const svg = document.createElementNS(NS, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('width', W);
  svg.setAttribute('height', H);
  node.append(svg);

  if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
    const pts = constellation(5);
    for (let i = 1; i < pts.length; i++) svg.append(link(pts[i - 1], pts[i]));
    pts.forEach(p => svg.append(dot(p, rnd(1.4, 2.2))));
    return node;
  }

  async function cycle() {
    const pts = constellation(4 + Math.floor(Math.random() * 3));
    const closed = Math.random() < 0.25;   // some figures close the loop

    // the points arrive…
    pts.forEach((p, i) => {
      const c = dot(p, rnd(1.4, 2.2));
      c.style.opacity = '0';
      svg.append(c);
      c.animate([{ opacity: 0 }, { opacity: 0.9 }],
        { duration: 380, delay: i * 110, fill: 'forwards', easing: 'ease-out' });
    });
    await sleep(pts.length * 110 + 320);
    if (!node.isConnected) return;

    // …and find each other
    const pairs = pts.slice(1).map((p, i) => [pts[i], p]);
    if (closed) pairs.push([pts[pts.length - 1], pts[0]]);
    for (const [a, b] of pairs) {
      const ln = link(a, b);
      const len = Math.hypot(b.x - a.x, b.y - a.y);
      ln.style.strokeDasharray = String(len);
      ln.style.strokeDashoffset = String(len);
      svg.append(ln);
      ln.animate([{ strokeDashoffset: len }, { strokeDashoffset: 0 }],
        { duration: 300, fill: 'forwards', easing: 'ease-in-out' });
      await sleep(170);
      if (!node.isConnected) return;
    }

    // the figure breathes once, then dissolves
    svg.animate([{ opacity: 1 }, { opacity: 0.55 }, { opacity: 1 }],
      { duration: 900, easing: 'ease-in-out' });
    await sleep(950);
    const fade = svg.animate([{ opacity: 1 }, { opacity: 0 }],
      { duration: 420, fill: 'forwards', easing: 'ease-in' });
    await sleep(440);
    svg.replaceChildren();
    fade.cancel();   // restore opacity for the next figure
  }

  (async () => {
    await sleep(0);   // let the caller append us first
    while (node.isConnected) await cycle();
  })();

  return node;
}
