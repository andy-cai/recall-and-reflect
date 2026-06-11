// Living backgrounds — a fixed layer behind the app, one scene per view.
//
//   reflect : the brand halo + fireflies (the writing room, full effect)
//   today   : aurora silk warmed with amber (comforting arrival)
//   recall  : ultra-dim halo only — reviews stay distraction-free
//   library : faint breathing contour lines (the map of what you know)
//
// Deliberately slow (16s–4min loops). Honors prefers-reduced-motion (one
// static frame, no animation) and the Settings toggle. Light theme gets a
// single soft warm veil instead of the dark scenes.

const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;

let host = null;
let current = null;
let raf = 0;
let painters = [];   // canvas painters: fn(tSeconds)

export function ambientEnabled() {
  return localStorage.getItem('rr-ambient') !== 'off';
}

export function setAmbientEnabled(on) {
  localStorage.setItem('rr-ambient', on ? 'on' : 'off');
  const name = current;
  current = null;
  setAmbient(name || '');
}

export function setAmbient(name) {
  if (!host) host = document.getElementById('ambient');
  if (!host || name === current) return;
  current = name;
  cancelAnimationFrame(raf);
  raf = 0;
  painters = [];
  host.innerHTML = '';
  host.removeAttribute('class');
  if (!name || !ambientEnabled()) return;

  const light = document.documentElement.getAttribute('data-theme') === 'light';
  if (light) {
    host.className = 'amb-veil';   // one soft warm wash for all views
    return;
  }

  if (name === 'reflect') { halo(1); fireflies(); }
  else if (name === 'today') { aurora(); }
  else if (name === 'recall') { halo(0.45); }
  else if (name === 'library') { contours(); }

  if (painters.length) startLoop();
}

// re-apply when the theme flips
addEventListener('rr-theme', () => { const n = current; current = null; setAmbient(n || ''); });
document.addEventListener('visibilitychange', () => {
  if (document.hidden) { cancelAnimationFrame(raf); raf = 0; }
  else if (painters.length && !raf) startLoop();
});
addEventListener('resize', () => { const n = current; current = null; setAmbient(n || ''); });

function startLoop() {
  if (REDUCED) { painters.forEach(p => p(0)); return; }   // single still frame
  const loop = (ms) => { painters.forEach(p => p(ms / 1000)); raf = requestAnimationFrame(loop); };
  raf = requestAnimationFrame(loop);
}

function div(cls) {
  const d = document.createElement('div');
  d.className = cls;
  host.append(d);
  return d;
}

function canvas() {
  const cv = document.createElement('canvas');
  host.append(cv);
  cv.width = innerWidth * devicePixelRatio;
  cv.height = innerHeight * devicePixelRatio;
  const g = cv.getContext('2d');
  g.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
  return [g, innerWidth, innerHeight];
}

/* ---------- CSS scenes ---------- */

function halo(strength) {
  host.classList.add('amb-halo');
  host.style.setProperty('--halo-o', String(0.30 * strength));
  div('amb-ring');
  if (strength >= 1) div('amb-spark');
}

function aurora() {
  host.classList.add('amb-aurora');
  div('amb-blob amb-b1');   // deep green field
  div('amb-blob amb-b2');   // sage drift
  div('amb-blob amb-b3');   // comforting amber, low corner
}

/* ---------- canvas scenes ---------- */

function fireflies() {
  const [g, W, H] = canvas();
  const P = Array.from({ length: 26 }, () => ({
    x: Math.random() * W, y: Math.random() * H, r: 0.7 + Math.random() * 1.5,
    vy: 3 + Math.random() * 7, sway: 10 + Math.random() * 22, ph: Math.random() * 7,
    tw: 0.3 + Math.random() * 0.9, cream: Math.random() < 0.25,
  }));
  painters.push(t => {
    g.clearRect(0, 0, W, H);
    for (const p of P) {
      const y = ((p.y - t * p.vy) % (H + 40) + H + 40) % (H + 40) - 20;
      const x = p.x + Math.sin(t * 0.3 + p.ph) * p.sway;
      const a = 0.10 + 0.30 * (0.5 + 0.5 * Math.sin(t * p.tw + p.ph * 3));
      g.beginPath();
      g.fillStyle = p.cream ? `rgba(236,227,209,${a})` : `rgba(213,154,82,${a})`;
      g.shadowColor = p.cream ? 'rgba(236,227,209,.6)' : 'rgba(213,154,82,.6)';
      g.shadowBlur = 7;
      g.arc(x, y, p.r, 0, 7);
      g.fill();
      g.shadowBlur = 0;
    }
  });
}

function contours() {
  const [g, W, H] = canvas();
  const cx = W * 0.7, cy = H * 0.35;
  const rings = Array.from({ length: 14 }, (_, i) => ({
    R: 60 + i * 64,
    h: Array.from({ length: 4 }, (_, k) => ({
      a: (8 + Math.random() * 14) * (1 + i * 0.06),
      f: k + 2, ph: Math.random() * 7, s: (Math.random() - 0.5) * 0.1,
    })),
  }));
  painters.push(t => {
    g.clearRect(0, 0, W, H);
    rings.forEach((ring, i) => {
      g.beginPath();
      for (let s = 0; s <= 120; s++) {
        const th = (s / 120) * Math.PI * 2;
        let r = ring.R;
        for (const w of ring.h) r += w.a * Math.sin(w.f * th + w.ph + t * w.s * 3);
        const x = cx + r * Math.cos(th), y = cy + r * Math.sin(th);
        s ? g.lineTo(x, y) : g.moveTo(x, y);
      }
      g.closePath();
      g.strokeStyle = i % 4 === 2 ? 'rgba(213,154,82,.07)' : 'rgba(111,169,160,.045)';
      g.lineWidth = 1.1;
      g.stroke();
    });
  });
}
