// Illustrated village scene: a walled town (slots 19-40) inside a moat, resource fields (slots 1-18) around it.
// Everything is drawn as SVG at runtime in an oblique "painted" style; each slot is a clickable group.

import { openSlotPanel } from './slotpanel.js';

const NS = 'http://www.w3.org/2000/svg';
const INK = '#4a3420';
const C = {
  wall: '#efe2c0', wallD: '#cdb98f', wallL: '#f8efd6',
  roof: '#b5543a', roofL: '#cf6d4c', roofD: '#8e3f2c',
  wood: '#a77a47', woodD: '#74502b', woodL: '#c99a62',
  stone: '#b9b4a6', stoneD: '#8d887c', stoneL: '#d9d5c8',
  gold: '#d9a82f', goldL: '#f1d77a',
  win: '#5d6b7d', dark: '#3a2a1c',
  pine: '#3f7a3c', pineL: '#58994b', pineD: '#2f5f30',
  hay: '#e0b94a', hayD: '#c4962c',
  red: '#a63d3d', cream: '#f4ead0', iron: '#5d7fa6', ironD: '#3e5d84',
};

const W = 1000;
const CX = 500;
const CY = 500;
const TOWN_RX = 300;
const TOWN_RY = 262;
const RING_RX = 428;
const RING_RY = 412;
const GATE_ANGLES = [-140, -40, 40, 140];
const FIELD_ANGLE0 = -170;
const FIELD_ANGLE_STEP = 20;

// Anchors (base-centre of each sprite) for the town slots.
const TOWN_POS = {
  19: [500, 372, 1.25], // town hall
  39: [500, 530, 1], // rally point (plaza)
  20: [374, 352], 21: [630, 346],
  22: [300, 420], 23: [415, 438], 24: [585, 438], 25: [700, 420],
  26: [262, 510], 27: [738, 510],
  28: [330, 588], 29: [425, 618], 30: [575, 618], 31: [672, 588],
  32: [392, 688], 33: [446, 708], 34: [554, 708], 35: [608, 688],
  36: [400, 520], 37: [600, 520], 38: [500, 640],
};

// ---------- tiny SVG helpers ----------

function el(tag, attrs = {}, ...kids) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined) continue;
    e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k) e.append(k);
  return e;
}

function pts(list) {
  return list.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
}

function poly(list, fill, extra = {}) {
  return el('polygon', { points: pts(list), fill, stroke: INK, 'stroke-width': 1.5, 'stroke-linejoin': 'round', ...extra });
}

function line(x1, y1, x2, y2, stroke = INK, sw = 1.5, extra = {}) {
  return el('line', { x1, y1, x2, y2, stroke, 'stroke-width': sw, 'stroke-linecap': 'round', ...extra });
}

function ellipse(cx, cy, rx, ry, fill, extra = {}) {
  return el('ellipse', { cx, cy, rx, ry, fill, stroke: INK, 'stroke-width': 1.4, ...extra });
}

function rect(x, y, w, h, fill, extra = {}) {
  return el('rect', { x, y, width: w, height: h, fill, stroke: INK, 'stroke-width': 1.4, 'stroke-linejoin': 'round', ...extra });
}

function text(x, y, str, size, fill = INK, extra = {}) {
  const t = el('text', { x, y, 'text-anchor': 'middle', 'font-size': size, 'font-weight': 700, fill, 'font-family': 'var(--font-body)', ...extra });
  t.textContent = str;
  return t;
}

function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function lerp(a, b, t) {
  return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
}

// ---------- building blocks ----------

function shadow(cx, cy, rx, ry) {
  return el('ellipse', { cx, cy, rx: rx * 1.15, ry: ry * 1.25, fill: 'url(#sc-shadow)', stroke: 'none' });
}

// A window with frame, glass, muntins, optional shutters and flower box.
function windowAt(x, y, { w = 10, h = 12, shutters = null, flowers = false, lit = false } = {}) {
  const g = el('g', { transform: `translate(${x} ${y})` });
  if (shutters) {
    g.append(rect(-w / 2 - 5, 0, 4.5, h, shutters, { 'stroke-width': 1 }));
    g.append(rect(w / 2 + 0.5, 0, 4.5, h, shutters, { 'stroke-width': 1 }));
  }
  g.append(rect(-w / 2 - 1.5, -1.5, w + 3, h + 3, C.cream, { 'stroke-width': 1.1 }));
  g.append(rect(-w / 2, 0, w, h, lit ? '#ffd27a' : 'url(#sc-glass)', { 'stroke-width': 0.8 }));
  g.append(line(0, 0, 0, h, C.cream, 1.1));
  g.append(line(-w / 2, h / 2, w / 2, h / 2, C.cream, 1.1));
  g.append(rect(-w / 2 - 2.5, h + 1.5, w + 5, 2.6, C.stoneL, { 'stroke-width': 0.9 }));
  if (flowers) {
    g.append(rect(-w / 2 - 1, h + 3, w + 2, 3.4, C.woodD, { 'stroke-width': 0.8 }));
    for (const fx of [-w / 3, 0, w / 3]) g.append(el('circle', { cx: fx, cy: h + 2.4, r: 2.2, fill: fx === 0 ? '#e86b6b' : '#f2c14e', stroke: INK, 'stroke-width': 0.6 }));
  }
  return g;
}

// An arched plank door with a stone step and a small lantern.
function doorAt(x, { w = 16, h = 24 } = {}) {
  const g = el('g', { transform: `translate(${x} 0)` });
  g.append(rect(-w / 2 - 4, -3, w + 8, 4, C.stoneL, { 'stroke-width': 1 }));
  g.append(el('path', { d: `M${-w / 2 - 2} 0v${-h + w / 2}a${w / 2 + 2} ${w / 2 + 2} 0 0 1 ${w + 4} 0v${h - w / 2}z`, fill: C.stoneD, stroke: INK, 'stroke-width': 1.1 }));
  g.append(el('path', { d: `M${-w / 2} -3v${-h + w / 2 + 3}a${w / 2} ${w / 2} 0 0 1 ${w} 0v${h - w / 2 - 3}z`, fill: C.woodD, stroke: INK, 'stroke-width': 1.2 }));
  for (const px of [-w / 4, w / 4]) g.append(line(px, -3, px, -h + 5, C.dark, 0.9, { opacity: 0.7 }));
  g.append(el('circle', { cx: w / 4 + 1, cy: -h / 2 + 2, r: 1.3, fill: C.gold, stroke: INK, 'stroke-width': 0.5 }));
  return g;
}

// ---- textured, isometric houses ----

const AX = 0.9; // horizontal run of the iso axes per unit of length
const AY = 0.38; // vertical rise
let DEFS = null;
const MADE = new Set();

// Create (once per scene) a pattern in <defs> and return its url().
function pattern(key, w, h, build) {
  const id = 'px-' + key.replace(/[^a-z0-9]/gi, '');
  if (!MADE.has(id) && DEFS) {
    MADE.add(id);
    DEFS.append(el('pattern', { id, width: w, height: h, patternUnits: 'userSpaceOnUse' }, build()));
  }
  return `url(#${id})`;
}

function shade(hex, k) {
  const n = parseInt(hex.slice(1), 16);
  const f = (v) => Math.max(0, Math.min(255, Math.round(v * k)));
  return `#${[(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => f(v).toString(16).padStart(2, '0')).join('')}`;
}

function wallTexture(kind, color) {
  if (kind === 'stone') {
    return pattern(`stone${color}`, 30, 18, () => [
      rect(0, 0, 30, 18, color, { stroke: 'none' }),
      ...[0, 1].map((r) => [0, 1, 2].map((c) => rect(c * 15 - (r ? 7 : 0) + 0.4, r * 9 + 0.4, 14.2, 8.2, shade(color, 0.96 + ((c + r * 2) % 3) * 0.04), { stroke: shade(color, 0.6), 'stroke-width': 0.7, rx: 1.4 }))).flat(),
    ]);
  }
  if (kind === 'plank') {
    return pattern(`plank${color}`, 9, 34, () => [
      rect(0, 0, 9, 34, color, { stroke: 'none' }),
      line(0.3, 0, 0.3, 34, shade(color, 0.6), 1),
      line(4.8, 4, 4.8, 30, shade(color, 0.86), 0.6, { opacity: 0.8 }),
      ellipse(5.5, 13, 1.1, 1.8, shade(color, 0.7), { stroke: 'none', opacity: 0.8 }),
    ]);
  }
  return pattern(`plaster${color}`, 26, 22, () => [
    rect(0, 0, 26, 22, color, { stroke: 'none' }),
    el('circle', { cx: 5, cy: 6, r: 0.8, fill: shade(color, 0.86), opacity: 0.7 }),
    el('circle', { cx: 18, cy: 14, r: 0.9, fill: shade(color, 0.88), opacity: 0.7 }),
    el('circle', { cx: 12, cy: 18, r: 0.6, fill: '#fff', opacity: 0.5 }),
    el('circle', { cx: 22, cy: 4, r: 0.6, fill: '#fff', opacity: 0.45 }),
    line(0, 11, 26, 11, shade(color, 0.93), 0.6, { opacity: 0.5 }),
  ]);
}

function roofTexture(kind, color) {
  const dark = shade(color, 0.62);
  const light = shade(color, 1.18);
  if (kind === 'slate') {
    return pattern(`slate${color}`, 16, 10, () => [
      rect(0, 0, 16, 10, color, { stroke: 'none' }),
      rect(0.4, 0.4, 15.2, 4.2, shade(color, 1.06), { stroke: dark, 'stroke-width': 0.7 }),
      rect(-7.6, 5.4, 15.2, 4.2, shade(color, 0.94), { stroke: dark, 'stroke-width': 0.7 }),
      rect(8.4, 5.4, 15.2, 4.2, shade(color, 0.94), { stroke: dark, 'stroke-width': 0.7 }),
    ]);
  }
  if (kind === 'thatch') {
    return pattern(`thatch${color}`, 10, 12, () => [
      rect(0, 0, 10, 12, color, { stroke: 'none' }),
      ...[1, 3.5, 6, 8.5].map((x, i) => line(x, 0, x + 1.2, 12, i % 2 ? dark : light, 0.9, { opacity: 0.8 })),
      line(0, 11.5, 10, 11.5, dark, 1.2, { opacity: 0.6 }),
    ]);
  }
  return pattern(`tile${color}`, 14, 9, () => [
    rect(0, 0, 14, 9, color, { stroke: 'none' }),
    el('path', { d: 'M0 4.5a7 4.5 0 0 0 14 0V0H0z', fill: shade(color, 1.07), stroke: dark, 'stroke-width': 0.8 }),
    el('path', { d: 'M-7 9a7 4.5 0 0 0 14 0V4.5h-14z', fill: color, stroke: dark, 'stroke-width': 0.8 }),
    el('path', { d: 'M7 9a7 4.5 0 0 0 14 0V4.5H7z', fill: color, stroke: dark, 'stroke-width': 0.8 }),
    el('path', { d: 'M2 2.6q5 2.2 10 0', fill: 'none', stroke: light, 'stroke-width': 0.8, opacity: 0.7 }),
  ]);
}

let CLIP_N = 0;

// An isometric house: two textured walls, a lit/shaded gable or hip roof, windows, door, chimney.
function house({ w = 60, d = 40, h = 30, rh = 22, wall = C.wall, roof = C.roof, tex = 'plaster', roofTex = 'tile', door = true, wins = 2, x = 0, y = 0, timber = false, chimney = false, shutter = '#5f8a5a', flowers = false, lit = false, base = '#8d887c', barn = null, pilasters = false }) {
  const Lx = -AX * w;
  const Ly = -AY * w;
  const Rx = AX * d;
  const Ry = -AY * d;
  const g = el('g', { transform: `translate(${(x - (Lx + Rx) / 2).toFixed(1)} ${y})` });
  const P0 = [0, 0];
  const PL = [Lx, Ly];
  const PR = [Rx, Ry];
  const PB = [Lx + Rx, Ly + Ry];
  const up = (p, k) => [p[0], p[1] - k];

  // cast shadow (light from the upper left) + ground contact
  g.append(poly([P0, PL, PB, PR].map(([px, py]) => [px + h * 0.5 + 6, py + h * 0.14 + 3]), '#1d1408', { opacity: 0.26, stroke: 'none' }));
  g.append(poly([[-4, 3], [Lx - 4, Ly + 3], [PB[0], PB[1] + 3], [Rx + 4, Ry + 3]], '#1d1408', { opacity: 0.2, stroke: 'none' }));

  const faceL = el('g', { transform: `matrix(${-AX} ${-AY} 0 1 0 0)` });
  const faceR = el('g', { transform: `matrix(${AX} ${-AY} 0 1 0 0)` });
  const wallFill = wallTexture(tex === 'timber' ? 'plaster' : tex, wall);
  const baseFill = wallTexture('stone', base);
  // left wall (lit)
  faceL.append(rect(0, -h, w, h, wallFill, { stroke: 'none' }));
  faceL.append(rect(0, -h, w, h, 'url(#sc-ao)', { stroke: 'none' }));
  faceL.append(rect(0, -5, w, 5, baseFill, { stroke: INK, 'stroke-width': 0.7 }));
  // right wall (shaded)
  faceR.append(rect(0, -h, d, h, wallFill, { stroke: 'none' }));
  faceR.append(rect(0, -h, d, h, '#2a1a0c', { opacity: 0.3, stroke: 'none' }));
  faceR.append(rect(0, -h, d, h, 'url(#sc-ao)', { stroke: 'none' }));
  faceR.append(rect(0, -5, d, 5, baseFill, { stroke: INK, 'stroke-width': 0.7 }));
  faceR.append(rect(0, -5, d, 5, '#2a1a0c', { opacity: 0.3, stroke: 'none' }));
  if (timber) {
    for (const [face, len] of [[faceL, w], [faceR, d]]) {
      for (const f of [0, 0.33, 0.67, 1]) face.append(rect(f * (len - 3.4), -h, 3.4, h - 5, C.woodD, { 'stroke-width': 0.6 }));
      face.append(rect(0, -h * 0.55, len, 3, C.woodD, { 'stroke-width': 0.6 }));
      face.append(line(2, -h * 0.55, len * 0.33, -h + 1.5, C.woodD, 2));
    }
  }
  // gable end triangle on the right wall (pentagon wall)
  const gable = el('g', { transform: `matrix(${AX} ${-AY} 0 1 0 0)` });
  const aTop = -h - rh;
  gable.append(poly([[0, -h], [d, -h], [d / 2, aTop]], wallFill, { stroke: 'none' }));
  gable.append(poly([[0, -h], [d, -h], [d / 2, aTop]], '#2a1a0c', { opacity: 0.3, stroke: 'none' }));
  if (timber) gable.append(line(d / 2, -h, d / 2, aTop + 3, C.woodD, 2.4));
  // wall details
  const doorW = Math.min(18, w * 0.28);
  const doorU = w * 0.3;
  if (door) {
    const dd = doorAt(doorU, { w: doorW, h: Math.min(26, h * 0.82) });
    faceL.append(dd);
  }
  if (barn) {
    const bw = Math.min(w * 0.62, 40);
    const bu = w * 0.46;
    const bh = h * 0.86;
    faceL.append(el('path', { d: `M${bu - bw / 2} -5V${-bh + 8}a${bw / 2} 8 0 0 1 ${bw} 0V-5z`, fill: barn === 'open' || barn === 'gate' ? '#24180f' : shade('#8a5d33', 0.9), stroke: INK, 'stroke-width': 1.2 }));
    if (barn === 'gate') {
      for (let gx = bu - bw / 2 + 4; gx < bu + bw / 2 - 2; gx += 5) faceL.append(line(gx, -5, gx, -bh + 6, '#6b717a', 1.3));
      for (const gy of [-14, -22, -30]) faceL.append(line(bu - bw / 2 + 1, gy, bu + bw / 2 - 1, gy, '#6b717a', 1.2));
      faceL.append(el('path', { d: `M${bu - bw / 2 - 2} -5V${-bh + 8}a${bw / 2 + 2} 10 0 0 1 ${bw + 4} 0`, fill: 'none', stroke: C.stoneL, 'stroke-width': 3 }));
    }
    if (barn === 'closed') {
      faceL.append(line(bu, -5, bu, -bh, INK, 1));
      for (const sgn of [-1, 1]) {
        const x0 = bu + sgn * 2;
        const x1 = bu + sgn * (bw / 2 - 2);
        faceL.append(line(x0, -bh + 6, x1, -8, shade('#8a5d33', 0.6), 1.6));
        faceL.append(line(x0, -8, x1, -bh + 6, shade('#8a5d33', 0.6), 1.6));
      }
    }
    faceL.append(rect(bu - bw / 2 - 2, -5, 3, bh - 3, C.woodD, { 'stroke-width': 0.7 }));
    faceL.append(rect(bu + bw / 2 - 1, -5, 3, bh - 3, C.woodD, { 'stroke-width': 0.7 }));
  }
  if (pilasters) {
    for (const [face, len] of [[faceL, w], [faceR, d]]) {
      const n = Math.max(2, Math.round(len / 18));
      for (let i = 0; i <= n; i++) {
        const u = (i / n) * (len - 6);
        face.append(rect(u, -h + 2, 6, h - 7, C.wallL, { 'stroke-width': 0.7 }));
        face.append(rect(u, -h + 2, 6, h - 7, 'url(#sc-shade)', { stroke: 'none' }));
        face.append(rect(u - 1.5, -h, 9, 4, C.stoneL, { 'stroke-width': 0.7 }));
        face.append(rect(u - 1.5, -9, 9, 4, C.stoneL, { 'stroke-width': 0.7 }));
      }
    }
  }
  const winSlots = wins === 0 ? [] : wins === 1 ? [0.74] : wins === 2 ? [0.62, 0.9] : [0.55, 0.74, 0.93];
  for (const tt of winSlots) {
    const wu = w * tt;
    if (door && Math.abs(wu - doorU) < doorW) continue;
    faceL.append(windowAt(wu, -h * 0.72, { shutters: h > 24 ? shutter : null, flowers: flowers && h > 24, lit }));
  }
  if (d > 30 && h > 24) faceR.append(windowAt(d * 0.5, -h * 0.72, { shutters: shutter, lit }));

  g.append(faceL, faceR, gable);
  // wall outlines
  g.append(poly([P0, PL, up(PL, h), up(P0, h)], 'none'));
  g.append(poly([P0, PR, up(PR, h), up(P0, h)], 'none'));
  g.append(poly([up(P0, h), up(PR, h), [Rx / 2, Ry / 2 - h - rh]], 'none'));

  // roof (near slope): eave along the left wall, ridge above the middle of the depth
  const C0 = up(P0, h);
  const CL = up(PL, h);
  const A = [Rx / 2, Ry / 2 - h - rh];
  const B = [A[0] + Lx, A[1] + Ly];
  const e = [-Rx * 0.16, -Ry * 0.16 + 3];
  const c1 = [C0[0] - Lx * 0.05 + e[0], C0[1] - Ly * 0.05 + e[1]];
  const c2 = [CL[0] + Lx * 0.05 + e[0], CL[1] + Ly * 0.05 + e[1]];
  const b = [B[0] + Lx * 0.05, B[1] + Ly * 0.05];
  const a = [A[0] - Lx * 0.05, A[1] - Ly * 0.05];
  const sx = a[0] - c1[0];
  const sy = a[1] - c1[1];
  const slen = Math.hypot(sx, sy);
  const m = [Lx / w, Ly / w, sx / slen, sy / slen, c1[0], c1[1]];
  const det = m[0] * m[3] - m[1] * m[2];
  const loc = (p) => {
    const px = p[0] - m[4];
    const py = p[1] - m[5];
    return [(px * m[3] - py * m[2]) / det, (py * m[0] - px * m[1]) / det];
  };
  const roofG = el('g', { transform: `matrix(${m.map((v) => v.toFixed(4)).join(' ')})` });
  const lp = [c1, c2, b, a].map(loc);
  roofG.append(poly(lp, roofTexture(roofTex, roof), { stroke: 'none' }));
  roofG.append(poly(lp, 'url(#sc-roofshade2)', { stroke: 'none' }));
  g.append(roofG);
  // gable-end roof edge (barge boards) and outlines
  g.append(poly([c1, c2, b, a], 'none', { 'stroke-width': 1.5 }));
  g.append(line(c1[0], c1[1], c2[0], c2[1], shade(roof, 0.5), 2.6, { opacity: 0.85 }));
  g.append(line(a[0], a[1], b[0], b[1], shade(roof, 1.25), 2.6));
  g.append(line(c1[0], c1[1], a[0], a[1], shade(wall, 0.55), 2.4));
  // eave shadow on the wall below the roof
  g.append(poly([up(PL, h - 7), up(P0, h - 7), up(P0, h), up(PL, h)], 'url(#sc-eave)', { stroke: 'none', opacity: 0.9 }));
  if (chimney) {
    const q = [A[0] + Lx * 0.62, A[1] + Ly * 0.62 + 4];
    g.append(poly([[q[0] - 6, q[1] + 2], [q[0] + 2, q[1] - 2], [q[0] + 2, q[1] - 24], [q[0] - 6, q[1] - 20]], '#a89a86'));
    g.append(poly([[q[0] + 2, q[1] - 2], [q[0] + 8, q[1] - 5], [q[0] + 8, q[1] - 27], [q[0] + 2, q[1] - 24]], '#7a6d5c'));
    g.append(poly([[q[0] - 8, q[1] - 20], [q[0] + 1, q[1] - 24.5], [q[0] + 10, q[1] - 28], [q[0] + 1, q[1] - 23]], '#cfc4b0', { 'stroke-width': 1 }));
  }
  g.ridgeMid = [A[0] + Lx / 2 - (Lx + Rx) / 2 + x, A[1] + Ly / 2 + y];
  return g;
}

// Old call sites describe houses in the previous flat style; map them onto the iso house.
function hall(o) {
  const tex = o.tex ?? (o.planks ? 'plank' : o.timber ? 'timber' : 'plaster');
  return house({
    w: (o.w ?? 70) * 0.74,
    d: (o.d ?? 44) * 0.8,
    h: (o.h ?? 34) * 0.9,
    rh: (o.rh ?? 22) * 0.95,
    wall: o.wall ?? C.wall,
    roof: o.roof ?? C.roof,
    tex,
    roofTex: o.roofTex ?? (o.roof === '#7f8f9c' || o.roof === '#5f6975' ? 'slate' : 'tile'),
    door: o.door ?? true,
    wins: o.wins ?? 2,
    x: o.x ?? 0,
    y: o.y ?? 0,
    timber: !!o.timber,
    chimney: !!o.chimney,
    shutter: o.shutter ?? '#5f8a5a',
    flowers: !!o.flowers,
    lit: !!o.lit,
    barn: o.barn ?? null,
    pilasters: !!o.pilasters,
  });
}

// A round tower with an optional conical roof, stone courses and arrow slits.
function tower({ r = 18, h = 60, cone = 30, wall = C.wall, wallD = C.wallD, roof = C.roof, x = 0, y = 0, tex = 'plaster', roofTex = 'tile' }) {
  const g = el('g', { transform: `translate(${x} ${y})` });
  g.append(shadow(4, 3, r + 8, 7));
  g.append(el('path', { d: `M${-r} ${-h}V0a${r} ${r * 0.34} 0 0 0 ${2 * r} 0V${-h}z`, fill: wallTexture(tex, wall), stroke: INK, 'stroke-width': 1.4 }));
  g.append(el('path', { d: `M${-r} ${-h}V0a${r} ${r * 0.34} 0 0 0 ${2 * r} 0V${-h}z`, fill: 'url(#sc-shade)', stroke: 'none' }));
  g.append(el('path', { d: `M${r * 0.2} ${-h}V${r * 0.3}a${r * 0.8} ${r * 0.3} 0 0 0 ${r * 0.8} -${r * 0.34}V${-h}z`, fill: '#2a1a0c', opacity: 0.22 }));
  for (let cy = -h + 9; cy < -4; cy += 9) {
    g.append(el('path', { d: `M${-r} ${cy}a${r} ${r * 0.3} 0 0 0 ${2 * r} 0`, fill: 'none', stroke: wallD, 'stroke-width': 1, opacity: 0.8 }));
  }
  if (h > 44) g.append(rect(-1.8, -h * 0.55, 3.6, 10, C.dark, { 'stroke-width': 0.6 }));
  if (cone > 0) {
    g.append(el('path', { d: `M${-r - 5} ${-h}L0 ${-h - cone}L${r + 5} ${-h}a${r + 5} ${(r + 5) * 0.3} 0 0 1 ${-(2 * r + 10)} 0z`, fill: roofTexture(roofTex, roof), stroke: INK, 'stroke-width': 1.4, 'stroke-linejoin': 'round' }));
    for (let k = 1; k <= 3; k++) {
      const yy = -h - cone * (k / 4);
      const half = (r + 5) * (1 - k / 4);
      g.append(el('path', { d: `M${-half} ${yy}a${half} ${half * 0.3} 0 0 0 ${2 * half} 0`, fill: 'none', stroke: C.roofD, 'stroke-width': 1, opacity: 0.55 }));
    }
    g.append(el('path', { d: `M${-r - 5} ${-h}L0 ${-h - cone}L${r + 5} ${-h}a${r + 5} ${(r + 5) * 0.3} 0 0 1 ${-(2 * r + 10)} 0z`, fill: 'url(#sc-shade)', stroke: 'none' }));
    g.append(el('circle', { cx: 0, cy: -h - cone, r: 2.6, fill: C.gold, stroke: INK, 'stroke-width': 0.8 }));
  }
  return g;
}

function pine(x, y, s = 1) {
  const g = el('g', { transform: `translate(${x} ${y}) scale(${s})` });
  g.append(shadow(5, 1, 12, 4));
  g.append(rect(-2.5, -8, 5, 9, C.woodD, { 'stroke-width': 1 }));
  const tier = (yb, yt, hw, light) => {
    g.append(poly([[-hw, yb], [0, yt], [hw, yb]], light ? C.pineL : C.pine));
    g.append(poly([[0, yt], [hw, yb], [0, yb]], C.pineD, { opacity: 0.55, 'stroke-width': 0 }));
    g.append(poly([[-hw * 0.7, yb - 3], [-hw * 0.15, yt + 5], [-hw * 0.05, yb - 6]], '#8fc276', { opacity: 0.5, 'stroke-width': 0 }));
  };
  tier(-8, -34, 15, false);
  tier(-22, -46, 12, true);
  tier(-36, -58, 9, true);
  return g;
}

function bush(x, y, s = 1) {
  return el('g', { transform: `translate(${x} ${y}) scale(${s})` }, ellipse(0, 0, 11, 8, C.pineL, { 'stroke-width': 1.1 }), ellipse(6, -3, 7, 6, C.pine, { 'stroke-width': 1 }));
}

function rock(x, y, s = 1, fill = C.stone, fillL = C.stoneL) {
  return el(
    'g',
    { transform: `translate(${x} ${y}) scale(${s})` },
    shadow(4, 2, 22, 5),
    poly([[-18, 0], [-14, -16], [-2, -24], [14, -18], [20, -4], [14, 2]], fill),
    poly([[-14, -16], [-2, -24], [14, -18], [2, -12]], fillL, { opacity: 0.9, 'stroke-width': 0.8 }),
    poly([[2, -12], [14, -18], [20, -4], [14, 2], [4, 1]], '#000', { opacity: 0.2, 'stroke-width': 0 }),
    line(-6, -10, -2, -2, INK, 0.9, { opacity: 0.5 }),
  );
}

function crate(x, y, s = 1) {
  return el(
    'g',
    { transform: `translate(${x} ${y}) scale(${s})` },
    poly([[0, 0], [14, -5], [14, -19], [0, -14]], C.woodD),
    rect(-14, -14, 14, 14, C.woodL, { 'stroke-width': 1.2 }),
    poly([[-14, -14], [0, -14], [14, -19], [0, -19]], C.woodL),
    line(-14, -14, 0, 0, C.woodD, 1),
  );
}

function log(x, y) {
  return el('g', { transform: `translate(${x} ${y})` }, rect(-14, -7, 28, 9, C.wood, { rx: 4 }), ellipse(14, -2.5, 3.5, 4.5, C.woodL, { 'stroke-width': 1 }));
}

function flag(x, y, h = 46, color = C.red) {
  return el(
    'g',
    { transform: `translate(${x} ${y})` },
    line(0, 0, 0, -h, C.woodD, 3),
    el('path', { d: `M1 ${-h}h20l-5 8 5 8H1z`, fill: color, stroke: INK, 'stroke-width': 1.2, class: 'sc-flag' }),
    el('circle', { cx: 0, cy: -h, r: 3, fill: C.gold, stroke: INK, 'stroke-width': 1 }),
  );
}

function smoke(x, y) {
  return el(
    'g',
    { opacity: 0.8, class: 'sc-smoke' },
    el('circle', { cx: x, cy: y, r: 5, fill: '#e8e8e8', stroke: INK, 'stroke-width': 0.8 }),
    el('circle', { cx: x + 5, cy: y - 10, r: 7, fill: '#f0f0f0', stroke: INK, 'stroke-width': 0.8 }),
    el('circle', { cx: x + 2, cy: y - 22, r: 9, fill: '#f6f6f6', stroke: INK, 'stroke-width': 0.8 }),
  );
}

function horse(x, y, s = 1) {
  const g = el('g', { transform: `translate(${x} ${y}) scale(${s})` });
  g.append(ellipse(0, -14, 14, 8, '#8a5a34'));
  g.append(rect(-11, -9, 3.5, 12, '#6e4527', { 'stroke-width': 1 }));
  g.append(rect(8, -9, 3.5, 12, '#6e4527', { 'stroke-width': 1 }));
  g.append(poly([[10, -18], [20, -30], [26, -27], [18, -14]], '#8a5a34'));
  g.append(el('path', { d: 'M-14 -16q-8 4-9 12', stroke: '#3a2412', 'stroke-width': 2.5, fill: 'none' }));
  return g;
}

// ---------- town building sprites (origin = base centre) ----------

const SPRITES = {
  town_hall(level) {
    const g = el('g');
    g.append(tower({ r: 17, h: 66, cone: 30, wall: C.wallL, x: -64, y: -18 }));
    g.append(el('g', { transform: 'translate(-64 -56)' }, el('circle', { r: 7, fill: C.cream, stroke: INK, 'stroke-width': 1.2 }), line(0, 0, 0, -4.5, INK, 1.2), line(0, 0, 3.4, 1, INK, 1.2)));
    g.append(hall({ w: 84, d: 50, h: 40, rh: 26, wins: 3, x: -6, timber: true, chimney: true, flowers: true, shutter: '#7a3b2e' }));
    g.append(flag(62, -24, 56));
    g.append(rect(-14, -64, 28, 6, C.gold, { 'stroke-width': 1 }));
    return g;
  },
  rally_point() {
    const g = el('g');
    g.append(ellipse(0, 4, 60, 18, '#b99a62', { opacity: 0.55, stroke: 'none' }));
    g.append(flag(-18, 0, 58));
    g.append(flag(18, 4, 50));
    for (const x of [-48, 46]) {
      g.append(line(x, 6, x, -24, C.woodD, 3));
      g.append(line(x - 11, -17, x + 11, -17, C.woodD, 3));
      g.append(el('circle', { cx: x, cy: -28, r: 7, fill: C.hay, stroke: INK, 'stroke-width': 1.2 }));
    }
    return g;
  },
  warehouse() {
    const g = el('g');
    g.append(hall({ w: 84, d: 50, h: 28, rh: 20, wall: C.woodL, roof: '#7f8f9c', door: false, wins: 0, x: -6, planks: true, chimney: true, barn: 'closed' }));
    g.append(crate(56, 4, 1.1));
    g.append(crate(70, -2, 0.9));
    g.append(crate(62, -14, 0.9));
    return g;
  },
  granary() {
    const g = el('g');
    g.append(tower({ r: 26, h: 52, cone: 34, wall: C.hay, wallD: C.hayD, roof: C.roof, x: -6, tex: 'plank' }));
    g.append(line(-32, -22, 20, -22, C.hayD, 1.4));
    g.append(line(-32, -38, 20, -38, C.hayD, 1.4));
    g.append(el('path', { d: 'M-14 0v-15a8 8 0 0 1 16 0v15z', fill: C.woodD, stroke: INK, 'stroke-width': 1.3 }));
    g.append(ellipse(46, 2, 14, 10, C.hay));
    g.append(ellipse(46, -4, 11, 8, C.goldL, { 'stroke-width': 1 }));
    g.append(ellipse(30, 8, 10, 7, C.hay));
    return g;
  },
  barracks() {
    const g = el('g');
    g.append(hall({ w: 92, d: 52, h: 30, rh: 22, wall: '#e8dcc0', roof: '#6d7f5a', roofL: '#88996f', roofD: '#4b5a3b', wins: 3, x: -10, timber: true, shutter: '#7a5a3a' }));
    g.append(flag(-62, 6, 54));
    g.append(flag(62, 8, 48));
    g.append(line(46, 8, 46, -22, C.woodD, 2.5));
    g.append(line(54, 8, 54, -22, C.woodD, 2.5));
    g.append(line(42, -10, 58, -10, C.woodD, 2.5));
    return g;
  },
  smithy() {
    const g = el('g');
    g.append(hall({ w: 74, d: 48, h: 30, rh: 20, wall: '#d8cfc0', wallD: '#a9a091', roof: '#5f6975', roofL: '#7a8694', roofD: '#3f4852', wins: 1, door: false, x: -8, tex: 'stone', lit: true }));
    g.append(rect(30, -64, 12, 34, C.stoneD, { 'stroke-width': 1.3 }));
    g.append(smoke(36, -66));
    g.append(el('path', { d: 'M-22 0v-20a14 14 0 0 1 28 0v20z', fill: '#2d2118', stroke: INK, 'stroke-width': 1.4 }));
    g.append(el('path', { d: 'M-14 0v-12a6 6 0 0 1 12 0v12z', fill: '#ff8a1f' }));
    g.append(poly([[44, 6], [66, 6], [62, -2], [50, -2]], C.ironD));
    g.append(rect(50, -10, 12, 8, C.iron, { 'stroke-width': 1.1 }));
    return g;
  },
  stable() {
    const g = el('g');
    g.append(hall({ w: 86, d: 50, h: 28, rh: 18, wall: '#b08a5a', roof: '#6f4a2a', roofTex: 'thatch', door: false, wins: 0, x: -4, planks: true, barn: 'open' }));
    g.append(horse(-30, 12, 0.9));
    g.append(horse(22, 14, 0.95));
    g.append(rect(-52, 12, 3, 12, C.woodD, { 'stroke-width': 0.8 }));
    g.append(line(-52, 16, -8, 22, C.woodD, 2));
    g.append(ellipse(62, 8, 12, 8, C.hay));
    g.append(ellipse(62, 2, 9, 6, C.goldL, { 'stroke-width': 1 }));
    return g;
  },
  workshop() {
    const g = el('g');
    g.append(hall({ w: 76, d: 46, h: 30, rh: 20, wall: '#dccfae', roof: '#7a5a3a', roofL: '#98734c', roofD: '#533a24', wins: 2, x: -14, planks: true, shutter: '#8a5a3a' }));
    // wooden A-frame with a ram
    g.append(line(34, 6, 48, -34, C.woodD, 4));
    g.append(line(66, 6, 52, -34, C.woodD, 4));
    g.append(line(44, -16, 56, -16, C.woodD, 3));
    g.append(rect(30, -4, 40, 8, C.wood, { 'stroke-width': 1.2 }));
    g.append(el('circle', { cx: 46, cy: 8, r: 6, fill: C.woodL, stroke: INK, 'stroke-width': 1.2 }));
    g.append(el('circle', { cx: 64, cy: 8, r: 6, fill: C.woodL, stroke: INK, 'stroke-width': 1.2 }));
    return g;
  },
  hideout() {
    const g = el('g');
    g.append(shadow(0, 3, 60, 10));
    g.append(el('path', { d: 'M-56 2C-52 -34 -26 -52 2 -52S54 -34 58 2z', fill: '#6fa24c', stroke: INK, 'stroke-width': 1.5 }));
    g.append(el('path', { d: 'M-30 -22q18-16 40-8', fill: 'none', stroke: '#9bc872', 'stroke-width': 4, opacity: 0.8 }));
    g.append(el('path', { d: 'M-14 2v-18a14 14 0 0 1 28 0v18z', fill: C.woodD, stroke: INK, 'stroke-width': 1.4 }));
    g.append(line(0, -30, 0, 2, C.dark, 1.2));
    g.append(bush(-44, 6, 0.9));
    g.append(bush(48, 8, 0.8));
    return g;
  },
  marketplace() {
    const g = el('g');
    const stall = (x, y, c1) => {
      const s = el('g', { transform: `translate(${x} ${y})` });
      s.append(line(-22, 0, -22, -28, C.woodD, 3));
      s.append(line(22, 0, 22, -28, C.woodD, 3));
      s.append(rect(-24, -12, 48, 10, C.woodL, { 'stroke-width': 1.2 }));
      for (let i = 0; i < 4; i++) {
        s.append(poly([[-26 + i * 13, -28], [-13 + i * 13, -28], [-11 + i * 13, -40 + 0], [-24 + i * 13, -40]], i % 2 ? C.cream : c1, { 'stroke-width': 1 }));
      }
      s.append(el('circle', { cx: -10, cy: -15, r: 4.5, fill: '#7fb04e', stroke: INK, 'stroke-width': 0.9 }));
      s.append(el('circle', { cx: 2, cy: -15, r: 4.5, fill: '#d55a42', stroke: INK, 'stroke-width': 0.9 }));
      s.append(el('circle', { cx: 13, cy: -15, r: 4.5, fill: C.gold, stroke: INK, 'stroke-width': 0.9 }));
      return s;
    };
    g.append(stall(-30, -6, C.red));
    g.append(stall(34, 6, '#4a7fa8'));
    g.append(crate(0, 12, 1));
    return g;
  },
  palace() {
    const g = el('g');
    const hs = hall({ w: 100, d: 70, h: 44, rh: 22, wall: '#f1e8d0', roof: '#a8483a', wins: 3, flowers: true, shutter: '#7a3b2e', x: 0, tex: 'stone', pilasters: true });
    g.append(hs);
    const [rx, ry] = hs.ridgeMid;
    const dome = el('g', { transform: `translate(${rx.toFixed(1)} ${(ry + 6).toFixed(1)})` });
    dome.append(shadow(2, 4, 24, 8));
    dome.append(rect(-17, -16, 34, 18, C.wall, { rx: 3 }));
    dome.append(rect(-17, -16, 34, 18, 'url(#sc-shade)', { stroke: 'none', rx: 3 }));
    for (const dx of [-11, 0, 11]) dome.append(el('path', { d: `M${dx - 3} 0v-9a3 3 0 0 1 6 0v9z`, fill: C.woodD, stroke: INK, 'stroke-width': 0.8 }));
    dome.append(el('path', { d: 'M-22 -16a22 24 0 0 1 44 0z', fill: C.gold, stroke: INK, 'stroke-width': 1.4 }));
    dome.append(el('path', { d: 'M-22 -16a22 24 0 0 1 44 0z', fill: 'url(#sc-shade)', stroke: 'none' }));
    dome.append(el('path', { d: 'M-14 -26q8-9 18-6', fill: 'none', stroke: '#fff3b0', 'stroke-width': 3.2, opacity: 0.85, 'stroke-linecap': 'round' }));
    dome.append(line(0, -40, 0, -52, C.woodD, 2));
    dome.append(flag(0, -52, 14, C.red));
    g.append(dome);
    return g;
  },
  monument() {
    const g = el('g');
    g.append(poly([[-62, 8], [0, -8], [62, 8], [0, 24]], '#e6e0d0'));
    g.append(poly([[-40, 4], [0, -6], [40, 4], [0, 14]], C.stoneL));
    g.append(rect(-18, -26, 36, 28, C.stoneL));
    g.append(poly([[18, -26], [28, -30], [28, -2], [18, 2]], C.stone));
    g.append(el('path', { d: 'M-10 -26c0-10 4-14 10-14s10 4 10 14z', fill: C.cream, stroke: INK, 'stroke-width': 1.3 }));
    g.append(el('circle', { cx: 0, cy: -58, r: 7, fill: C.cream, stroke: INK, 'stroke-width': 1.3 }));
    g.append(el('path', { d: 'M-8 -50h16l4 24h-24z', fill: C.cream, stroke: INK, 'stroke-width': 1.3 }));
    g.append(line(8, -50, 20, -70, C.goldL, 3));
    g.append(el('path', { d: 'M20 -72l4 8-9 0z', fill: C.gold, stroke: INK, 'stroke-width': 1 }));
    return g;
  },
};

// ---------- field sprites ----------

// An isometric stone/crate block (no roof) with textured faces.
function block(x, y, w = 14, d = 12, h = 10, color = '#c9c4b6', tex = 'stone') {
  const Lx = -AX * w;
  const Ly = -AY * w;
  const Rx = AX * d;
  const Ry = -AY * d;
  const g = el('g', { transform: `translate(${x} ${y})` });
  g.append(shadow(h * 0.4 + 4, 2, w * 0.9, 5));
  g.append(poly([[0, 0], [Lx, Ly], [Lx, Ly - h], [0, -h]], wallTexture(tex, color)));
  g.append(poly([[0, 0], [Rx, Ry], [Rx, Ry - h], [0, -h]], wallTexture(tex, shade(color, 0.78))));
  g.append(poly([[0, 0], [Rx, Ry], [Rx, Ry - h], [0, -h]], '#2a1a0c', { opacity: 0.22, 'stroke-width': 0 }));
  g.append(poly([[0, -h], [Lx, Ly - h], [Lx + Rx, Ly + Ry - h], [Rx, Ry - h]], shade(color, 1.14)));
  return g;
}

// A pile of logs with barked sides and ringed ends.
function logPile(x, y, rows = 3) {
  const g = el('g', { transform: `translate(${x} ${y})` });
  const bark = pattern('bark', 9, 9, () => [
    rect(0, 0, 9, 9, '#8a5d33', { stroke: 'none' }),
    line(0, 2, 9, 2, '#6b4526', 0.9),
    line(0, 5.5, 9, 5.5, '#a67a4a', 0.9),
    line(0, 8, 9, 8, '#6b4526', 0.7),
  ]);
  g.append(shadow(2, 4, 26, 6));
  for (let r = 0; r < rows; r++) {
    for (let i = 0; i < rows - r; i++) {
      const lx = (i - (rows - r - 1) / 2) * 11;
      const ly = -r * 8;
      g.append(rect(lx - 13, ly - 4.5, 26, 9, bark, { rx: 4, 'stroke-width': 1 }));
      g.append(ellipse(lx + 13, ly, 3.6, 4.6, '#dcb780', { 'stroke-width': 0.9 }));
      g.append(ellipse(lx + 13, ly, 1.8, 2.4, 'none', { stroke: '#8a5d33', 'stroke-width': 0.7 }));
    }
  }
  return g;
}

function hayBale(x, y, s = 1) {
  const g = el('g', { transform: `translate(${x} ${y}) scale(${s})` });
  g.append(shadow(3, 3, 14, 4));
  g.append(rect(-12, -14, 24, 14, C.hay, { rx: 6 }));
  g.append(rect(-12, -14, 24, 14, 'url(#sc-shade)', { rx: 6, stroke: 'none' }));
  g.append(ellipse(12, -7, 4, 7, C.goldL, { 'stroke-width': 1 }));
  g.append(ellipse(12, -7, 2, 4, 'none', { stroke: C.hayD, 'stroke-width': 0.8 }));
  for (const bx of [-5, 3]) g.append(line(bx, -14, bx, 0, C.woodD, 1.3, { opacity: 0.85 }));
  return g;
}

const FIELD_SPRITES = {
  woodcutter(level) {
    const g = el('g');
    const trees = 2 + Math.min(3, Math.floor(level / 3));
    const spots = [[-52, 6], [-34, -8], [54, -10], [38, -22], [-8, -24]];
    for (let i = 0; i < trees; i++) g.append(pine(spots[i][0], spots[i][1] + 8, 0.95));
    g.append(hall({ w: 46, d: 30, h: 22, rh: 16, wall: C.woodL, roof: '#6f4a2a', roofTex: 'thatch', wins: 1, door: true, x: -8, y: 10, planks: true }));
    g.append(logPile(40, 18, Math.min(4, 2 + Math.floor(level / 4))));
    // chopping stump with an axe
    const stump = el('g', { transform: 'translate(-48 24)' });
    stump.append(shadow(2, 3, 12, 4));
    stump.append(rect(-8, -9, 16, 10, '#8a5d33', { rx: 2 }));
    stump.append(ellipse(0, -9, 8, 3.2, '#dcb780', { 'stroke-width': 1 }));
    stump.append(line(0, -10, 10, -22, C.woodD, 2.6));
    stump.append(poly([[8, -26], [16, -22], [11, -17], [8, -21]], '#9aa3ad'));
    g.append(stump);
    return g;
  },
  quarry(level) {
    const g = el('g');
    const stone = wallTexture('stone', '#aaa599');
    g.append(shadow(0, 12, 72, 12));
    // terraced rock face with a lit top and a shaded right side
    g.append(poly([[-64, 12], [-60, -12], [-38, -30], [-8, -38], [26, -30], [54, -14], [64, 12]], stone));
    g.append(poly([[-60, -12], [-38, -30], [-8, -38], [-16, -22], [-44, -8]], '#fff', { opacity: 0.2, 'stroke-width': 0 }));
    g.append(poly([[-8, -38], [26, -30], [54, -14], [64, 12], [22, 12], [14, -14]], '#2a1a0c', { opacity: 0.26, 'stroke-width': 0 }));
    for (const [a, b] of [[[-52, -2], [-22, -12]], [[-22, -12], [14, -12]], [[14, -12], [50, -2]], [[-34, -22], [0, -26]]]) g.append(line(a[0], a[1], b[0], b[1], '#5c574c', 1.6));
    // the cut face
    g.append(poly([[-24, 12], [-18, -8], [8, -10], [14, 12]], '#d8d2c0'));
    g.append(poly([[8, -10], [14, 12], [28, 12], [20, -8]], '#8d877a'));
    g.append(line(-12, -2, 8, -3, '#5c574c', 1));
    // blocks waiting to be carried off
    const n = 1 + Math.min(4, Math.floor(level / 2));
    const spots = [[34, 22], [50, 18], [42, 11], [-44, 24], [-30, 20]];
    for (let i = 0; i < n; i++) g.append(block(spots[i][0], spots[i][1], 13, 11, 9));
    // wooden crane
    g.append(line(-30, 14, -30, -30, C.woodD, 4));
    g.append(line(-30, -30, -6, -22, C.woodD, 3.4));
    g.append(line(-6, -22, -6, -8, '#6b5a40', 1.2));
    g.append(block(-6, -4, 9, 8, 7, '#c9c4b6'));
    return g;
  },
  iron_mine(level) {
    const g = el('g');
    const rockTex = wallTexture('stone', '#7b7f89');
    g.append(shadow(0, 12, 74, 12));
    g.append(poly([[-66, 12], [-38, -32], [-16, -14], [12, -54], [42, -22], [66, 12]], rockTex));
    g.append(poly([[-38, -32], [-16, -14], [-34, -6]], '#fff', { opacity: 0.18, 'stroke-width': 0 }));
    g.append(poly([[12, -54], [42, -22], [66, 12], [24, 12], [18, -20]], '#14110d', { opacity: 0.34, 'stroke-width': 0 }));
    g.append(poly([[12, -54], [26, -38], [4, -34]], '#cfd8e0', { opacity: 0.6, 'stroke-width': 0 }));
    // timber-framed entrance
    g.append(el('path', { d: 'M-20 12v-24a20 20 0 0 1 40 0v24z', fill: '#17110b', stroke: INK, 'stroke-width': 1.5 }));
    g.append(rect(-26, -36, 52, 6, C.woodD, { 'stroke-width': 0.9 }));
    g.append(rect(-26, -36, 6, 50, C.wood, { 'stroke-width': 0.9 }));
    g.append(rect(20, -36, 6, 50, C.wood, { 'stroke-width': 0.9 }));
    g.append(line(-26, -12, -14, -30, C.woodD, 3));
    g.append(line(26, -12, 14, -30, C.woodD, 3));
    g.append(el('circle', { cx: 0, cy: -26, r: 2.6, fill: '#ffd27a', stroke: INK, 'stroke-width': 0.8 }));
    g.append(el('circle', { cx: 0, cy: -26, r: 8, fill: '#ffd27a', opacity: 0.25 }));
    // rails coming out of the mine
    for (const sx of [-8, 8]) g.append(line(sx * 0.7, 12, sx * 1.9, 34, '#5a5f66', 2.2));
    for (let k = 0; k < 4; k++) {
      const yy = 16 + k * 5.5;
      g.append(line(-12 - k * 1.4, yy, 12 + k * 1.4, yy, C.woodD, 2));
    }
    // ore cart + ore piles
    const cart = el('g', { transform: 'translate(34 26)' });
    cart.append(shadow(2, 3, 18, 5));
    cart.append(poly([[-14, -14], [14, -14], [10, 0], [-10, 0]], '#6b4a2a'));
    cart.append(poly([[-14, -14], [14, -14], [14, -11], [-14, -11]], '#8a6238', { 'stroke-width': 0.8 }));
    for (const [ox, oy, orr] of [[-7, -17, 5], [1, -19, 6], [8, -16, 4.5]]) cart.append(poly([[ox - orr, oy + 3], [ox - orr * 0.6, oy - orr], [ox + orr * 0.5, oy - orr * 0.9], [ox + orr, oy + 2]], '#8aa0bd'));
    cart.append(el('circle', { cx: -7, cy: 1, r: 3.6, fill: '#4a4f57', stroke: INK, 'stroke-width': 1 }));
    cart.append(el('circle', { cx: 7, cy: 1, r: 3.6, fill: '#4a4f57', stroke: INK, 'stroke-width': 1 }));
    g.append(cart);
    for (let i = 0; i < Math.min(3, Math.floor(level / 3) + 1); i++) g.append(rock(-52 + i * 11, 22 - i * 3, 0.55, '#8aa0bd', '#c5d4e6'));
    return g;
  },
  farm(level) {
    const g = el('g');
    const T = [0, -26];
    const R = [66, 0];
    const B = [0, 28];
    const Lv = [-66, 0];
    const lerpP = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
    // tilled field: soil border, golden crop, furrows
    g.append(shadow(0, 8, 76, 14));
    g.append(poly([T, R, B, Lv], '#8a6538', { 'stroke-width': 1.4 }));
    const shrink = (p) => [p[0] * 0.88, p[1] * 0.86 + 0.5];
    const ip = [T, R, B, Lv].map(shrink);
    g.append(poly(ip, '#e2bb4e', { 'stroke-width': 0.8 }));
    for (let k = 1; k < 9; k++) {
      const a = lerpP(ip[3], ip[2], k / 9);
      const b = lerpP(ip[0], ip[1], k / 9);
      g.append(line(a[0], a[1], b[0], b[1], '#a8802c', 1.3, { opacity: 0.9 }));
      for (let s = 0.08; s < 0.95; s += 0.085) {
        const p = lerpP(a, b, s);
        g.append(line(p[0], p[1], p[0] + 0.8, p[1] - 4.5, s * 100 % 3 < 1 ? '#fff0a0' : '#c9962c', 1.5));
      }
    }
    g.append(poly(ip, 'url(#sc-shade)', { stroke: 'none', opacity: 0.6 }));
    // wooden fence along the front edges
    for (const [a, b] of [[Lv, B], [B, R]]) {
      for (let k = 0; k <= 6; k++) {
        const p = lerpP(a, b, k / 6);
        g.append(line(p[0], p[1], p[0], p[1] - 7, C.woodD, 2));
      }
      g.append(line(a[0], a[1] - 5, b[0], b[1] - 5, C.wood, 1.6));
    }
    if (level >= 3) g.append(hall({ w: 34, d: 24, h: 18, rh: 14, wall: '#d9a07a', wins: 0, door: true, x: -44, y: -10, planks: true }));
    if (level >= 6) {
      const mill = el('g', { transform: 'translate(48 -2)' });
      mill.append(tower({ r: 11, h: 36, cone: 16, wall: C.wallL, tex: 'plaster' }));
      const sails = el('g', { class: 'sc-sails', transform: 'translate(0 -37)' });
      for (const ang of [0, 90, 180, 270]) {
        sails.append(el('g', { transform: `rotate(${ang + 20})` }, line(0, 0, 0, -26, C.woodD, 2.4), poly([[1, -8], [8, -10], [8, -25], [1, -25]], '#f2e8cc', { 'stroke-width': 0.8 })));
      }
      mill.append(sails);
      g.append(mill);
    } else {
      g.append(hayBale(50, 20, 0.9));
      if (level >= 2) g.append(hayBale(64, 24, 0.8));
    }
    // scarecrow
    g.append(line(0, 4, 0, -16, C.woodD, 2.5));
    g.append(line(-8, -10, 8, -10, C.woodD, 2.5));
    g.append(el('circle', { cx: 0, cy: -19, r: 3.4, fill: C.hay, stroke: INK, 'stroke-width': 0.9 }));
    return g;
  },
};

// ---------- scene pieces ----------

function badge(x, y, level) {
  const g = el('g', { transform: `translate(${x} ${y})`, class: 'sc-badge' });
  g.append(el('circle', { r: 17, fill: C.cream, stroke: C.gold, 'stroke-width': 3.5 }));
  g.append(text(0, 6.5, level > 0 ? String(level) : '+', 19, INK));
  return g;
}

// Wrap a badge so it sits on the top layer but still opens its slot when tapped.
function placed(node, x, y, slot, open) {
  const g = el('g', { transform: `translate(${x.toFixed(1)} ${y.toFixed(1)})`, style: 'cursor:pointer' }, node);
  g.addEventListener('click', open(slot));
  return g;
}

function scaffolding() {
  return el(
    'g',
    { opacity: 0.9, 'pointer-events': 'none' },
    line(-46, 4, -46, -76, C.woodD, 4),
    line(46, 4, 46, -76, C.woodD, 4),
    line(-46, -26, 46, -26, C.woodD, 3.5),
    line(-46, -54, 46, -54, C.woodD, 3.5),
    line(-46, 4, 46, -54, C.woodL, 2.5),
    line(46, 4, -46, -54, C.woodL, 2.5),
    text(0, -84, '🔨', 28),
  );
}

function plot() {
  const g = el('g');
  g.append(ellipse(0, 0, 48, 20, '#a67c4b', { opacity: 0.5, 'stroke-dasharray': '6 5', 'stroke-width': 2, stroke: '#6f4a2a' }));
  g.append(ellipse(0, -2, 38, 14, '#c49a64', { opacity: 0.35, stroke: 'none' }));
  return g;
}

// ---------- terrain ----------

function addDefs(root) {
  const defs = el(
    'defs',
    {},
    el('radialGradient', { id: 'sc-grass', cx: '50%', cy: '48%', r: '75%' }, el('stop', { offset: 0, 'stop-color': '#9ccb62' }), el('stop', { offset: 1, 'stop-color': '#6f9f45' })),
    el('linearGradient', { id: 'sc-water', x1: 0, y1: 0, x2: 0, y2: 1 }, el('stop', { offset: 0, 'stop-color': '#8fc8e4' }), el('stop', { offset: 1, 'stop-color': '#5fa3c8' })),
    el('linearGradient', { id: 'sc-shade', x1: 0, y1: 0, x2: 1, y2: 0 }, el('stop', { offset: 0, 'stop-color': '#fff', 'stop-opacity': 0.34 }), el('stop', { offset: 0.5, 'stop-color': '#fff', 'stop-opacity': 0 }), el('stop', { offset: 1, 'stop-color': '#3a2a1c', 'stop-opacity': 0.22 })),
    el('linearGradient', { id: 'sc-roofshade', x1: 0, y1: 0, x2: 0, y2: 1 }, el('stop', { offset: 0, 'stop-color': '#fff', 'stop-opacity': 0.28 }), el('stop', { offset: 1, 'stop-color': '#2a1608', 'stop-opacity': 0.2 })),
    el('linearGradient', { id: 'sc-glass', x1: 0, y1: 0, x2: 1, y2: 1 }, el('stop', { offset: 0, 'stop-color': '#a8c6dc' }), el('stop', { offset: 1, 'stop-color': '#4f6a85' })),
    el('radialGradient', { id: 'sc-shadow', cx: '50%', cy: '50%', r: '50%' }, el('stop', { offset: 0, 'stop-color': '#1d1408', 'stop-opacity': 0.42 }), el('stop', { offset: 1, 'stop-color': '#1d1408', 'stop-opacity': 0 })),
    el('radialGradient', { id: 'sc-town', cx: '50%', cy: '50%', r: '60%' }, el('stop', { offset: 0, 'stop-color': '#a9d06c' }), el('stop', { offset: 1, 'stop-color': '#7fae4c' })),
  );
  defs.append(
    el('linearGradient', { id: 'sc-ao', x1: 0, y1: 0, x2: 0, y2: 1 }, el('stop', { offset: 0, 'stop-color': '#1d1408', 'stop-opacity': 0 }), el('stop', { offset: 0.7, 'stop-color': '#1d1408', 'stop-opacity': 0 }), el('stop', { offset: 1, 'stop-color': '#1d1408', 'stop-opacity': 0.34 })),
    el('linearGradient', { id: 'sc-eave', x1: 0, y1: 0, x2: 0, y2: 1 }, el('stop', { offset: 0, 'stop-color': '#1d1408', 'stop-opacity': 0.5 }), el('stop', { offset: 1, 'stop-color': '#1d1408', 'stop-opacity': 0 })),
    el('linearGradient', { id: 'sc-roofshade2', x1: 0, y1: 0, x2: 0, y2: 1 }, el('stop', { offset: 0, 'stop-color': '#1d1408', 'stop-opacity': 0.28 }), el('stop', { offset: 0.5, 'stop-color': '#1d1408', 'stop-opacity': 0 }), el('stop', { offset: 1, 'stop-color': '#fff', 'stop-opacity': 0.22 })),
  );
  DEFS = defs;
  MADE.clear();
  root.append(defs);
}

function drawTerrain(root, rng, fieldAnchors, fieldTypes) {
  addDefs(root);
  root.append(rect(-700, -700, W + 1400, W + 1400, 'url(#sc-grass)', { stroke: 'none' }));
  // painterly patches
  for (let i = 0; i < 26; i++) {
    root.append(ellipse(rng() * W, rng() * W, 40 + rng() * 90, 20 + rng() * 40, rng() > 0.5 ? '#b3d97d' : '#5d8f3c', { opacity: 0.16, stroke: 'none' }));
  }
  // outer roads from the gates
  const roads = el('g', { fill: 'none', 'stroke-linecap': 'round' });
  const roadPts = [];
  for (const a of GATE_ANGLES) {
    const r = (a * Math.PI) / 180;
    const gx = CX + TOWN_RX * Math.cos(r);
    const gy = CY + TOWN_RY * Math.sin(r);
    const ex = CX + 700 * Math.cos(r);
    const ey = CY + 640 * Math.sin(r) + (Math.sin(r) > 0 ? 20 : -20);
    const mx = (gx + ex) / 2 + (Math.cos(r) > 0 ? 18 : -18);
    const my = (gy + ey) / 2 + 22;
    const d = `M${gx.toFixed(0)} ${gy.toFixed(0)}Q${mx.toFixed(0)} ${my.toFixed(0)} ${ex.toFixed(0)} ${ey.toFixed(0)}`;
    roads.append(el('path', { d, stroke: '#a98a58', 'stroke-width': 30, opacity: 0.55 }));
    roads.append(el('path', { d, stroke: '#dcc690', 'stroke-width': 22 }));
    for (const t of [0.35, 0.55, 0.75, 0.95]) {
      roadPts.push([(1 - t) * (1 - t) * gx + 2 * t * (1 - t) * mx + t * t * ex, (1 - t) * (1 - t) * gy + 2 * t * (1 - t) * my + t * t * ey]);
    }
  }
  root.append(roads);

  // themed decoration outside the ring, picked by the nearest field's type
  const near = (x, y) => {
    let best = null;
    let bd = 1e9;
    fieldAnchors.forEach(([fx, fy], i) => {
      const d = (fx - x) ** 2 + (fy - y) ** 2;
      if (d < bd) {
        bd = d;
        best = fieldTypes[i];
      }
    });
    return best;
  };
  const decor = [];
  const townOnly = fieldAnchors.length === 0;
  for (let i = 0; i < (townOnly ? 420 : 160); i++) {
    const x = 20 + rng() * (W - 40);
    const y = 20 + rng() * (W - 40);
    const nx = (x - CX) / (TOWN_RX + 75);
    const ny = (y - CY) / (TOWN_RY + 75);
    if (nx * nx + ny * ny < 1) continue; // inside the moat
    if (fieldAnchors.some(([fx, fy]) => Math.hypot(fx - x, fy - y) < 78)) continue;
    if (roadPts.some(([rx, ry]) => Math.hypot(rx - x, ry - y) < 46)) continue;
    const rr = (x - CX) ** 2 / RING_RX ** 2 + (y - CY) ** 2 / RING_RY ** 2;
    if (!townOnly && rr < 0.82) continue; // keep the band between moat and fields calm
    const r0 = rng();
    decor.push({ x, y, kind: townOnly ? (r0 < 0.88 ? 'woodcutter' : 'quarry') : near(x, y), r: r0 });
  }
  decor.sort((a, b) => a.y - b.y);
  const deco = el('g', { 'pointer-events': 'none' });
  for (const d of decor) {
    const s = 0.8 + d.r * 0.5;
    if (d.kind === 'woodcutter') deco.append(d.r > 0.55 ? pine(d.x, d.y, s) : d.r > 0.12 ? tree(d.x, d.y, s, Math.floor(d.r * 30)) : bush(d.x, d.y, s));
    else if (d.kind === 'quarry') deco.append(rock(d.x, d.y, s * 1.2));
    else if (d.kind === 'iron_mine') deco.append(rock(d.x, d.y, s * 1.3, '#6b6f78', '#9aa0aa'));
    else {
      deco.append(
        el('path', {
          d: `M${d.x - 40 * s} ${d.y}c-6-16 20-26 44-22s44 6 36 24c-14 14-70 12-80-2z`,
          fill: C.hay,
          stroke: INK,
          'stroke-width': 1.2,
          opacity: 0.95,
        }),
      );
      if (d.r > 0.6) deco.append(bush(d.x + 60 * s, d.y + 10, 0.8));
    }
  }
  root.append(deco);

  // moat (river) around the wall
  const mrx = TOWN_RX + 42;
  const mry = TOWN_RY + 38;
  root.append(ellipse(CX, CY + 6, mrx + 30, mry + 30, '#7f8f6a', { opacity: 0.35, stroke: 'none' }));
  root.append(el('ellipse', { cx: CX, cy: CY + 4, rx: mrx, ry: mry, fill: 'none', stroke: '#b9b0a0', 'stroke-width': 66 }));
  root.append(el('ellipse', { cx: CX, cy: CY + 4, rx: mrx, ry: mry, fill: 'none', stroke: 'url(#sc-water)', 'stroke-width': 54 }));
  root.append(el('ellipse', { cx: CX, cy: CY + 4, rx: mrx, ry: mry, fill: 'none', stroke: '#e9f6fb', 'stroke-width': 3, 'stroke-dasharray': '34 22', opacity: 0.85, class: 'sc-foam' }));
  // bank stones
  for (let i = 0; i < 46; i++) {
    const a = (i / 46) * Math.PI * 2 + rng() * 0.1;
    const o = rng() > 0.5 ? 34 : -34;
    const px = CX + (mrx + o) * Math.cos(a);
    const py = CY + 4 + (mry + o) * Math.sin(a);
    root.append(rock(px, py, 0.32 + rng() * 0.25, C.stoneD, C.stone));
  }
  // town ground
  root.append(el('ellipse', { cx: CX, cy: CY, rx: TOWN_RX - 8, ry: TOWN_RY - 8, fill: 'url(#sc-town)', stroke: 'none' }));
}

function drawPlaza(root) {
  const g = el('g', { 'pointer-events': 'none' });
  const cobble = pattern('cobble', 16, 12, () => [
    rect(0, 0, 16, 12, '#c9c3b5', { stroke: 'none' }),
    ellipse(4, 3, 3.6, 2.4, '#d8d3c7', { stroke: '#9a958a', 'stroke-width': 0.6 }),
    ellipse(12, 3, 3.4, 2.3, '#cfc9bc', { stroke: '#9a958a', 'stroke-width': 0.6 }),
    ellipse(0, 9, 3.4, 2.4, '#d4cfc2', { stroke: '#9a958a', 'stroke-width': 0.6 }),
    ellipse(8, 9, 3.6, 2.4, '#ddd8cc', { stroke: '#9a958a', 'stroke-width': 0.6 }),
    ellipse(16, 9, 3.4, 2.4, '#d4cfc2', { stroke: '#9a958a', 'stroke-width': 0.6 }),
  ]);
  const road = (d) => {
    g.append(el('path', { d, fill: 'none', stroke: '#7d786d', 'stroke-width': 44, 'stroke-linecap': 'round', opacity: 0.85 }));
    g.append(el('path', { d, fill: 'none', stroke: cobble, 'stroke-width': 38, 'stroke-linecap': 'round' }));
  };
  for (const a of GATE_ANGLES) {
    const r = (a * Math.PI) / 180;
    const gx = CX + (TOWN_RX - 6) * Math.cos(r);
    const gy = CY + (TOWN_RY - 6) * Math.sin(r);
    road(`M${CX} ${CY + 20}Q${(CX + gx) / 2 + (Math.cos(r) > 0 ? -20 : 20)} ${(CY + gy) / 2 + 20} ${gx.toFixed(0)} ${gy.toFixed(0)}`);
  }
  g.append(ellipse(CX, CY + 20, 104, 48, '#8a8579', { stroke: INK, 'stroke-width': 1.4 }));
  g.append(ellipse(CX, CY + 20, 98, 44, cobble, { stroke: 'none' }));
  g.append(ellipse(CX, CY + 20, 40, 18, 'none', { stroke: '#9a958a', 'stroke-width': 2, 'stroke-dasharray': '5 4' }));
  root.append(g);
}

function gatePos(a) {
  const r = (a * Math.PI) / 180;
  return [CX + TOWN_RX * Math.cos(r), CY + TOWN_RY * Math.sin(r)];
}

function gateSprite(level) {
  const g = el('g');
  const hh = 38 + Math.min(14, level);
  const stone = '#ddd5bf';
  g.append(tower({ r: 11, h: hh + 16, cone: 20, wall: stone, tex: 'stone', roof: '#a8483a', x: -36, y: -4 }));
  g.append(house({ w: 36, d: 28, h: hh, rh: 13, wall: stone, tex: 'stone', roof: '#a8483a', door: false, wins: 0, barn: 'gate', x: 0, y: 4 }));
  g.append(tower({ r: 11, h: hh + 16, cone: 20, wall: stone, tex: 'stone', roof: '#a8483a', x: 36, y: -8 }));
  return g;
}

function bridge(a) {
  const [x, y] = gatePos(a);
  const r = (a * Math.PI) / 180;
  const nx = Math.cos(r);
  const ny = Math.sin(r);
  const g = el('g', { 'pointer-events': 'none' });
  const x1 = x;
  const y1 = y + 4;
  const x2 = x + nx * 95;
  const y2 = y + 4 + ny * 95;
  g.append(line(x1, y1, x2, y2, '#6f4a2a', 36, { opacity: 0.9 }));
  g.append(line(x1, y1, x2, y2, '#c99a62', 28));
  for (let t = 0.1; t < 1; t += 0.14) {
    const px = x1 + (x2 - x1) * t;
    const py = y1 + (y2 - y1) * t;
    g.append(line(px - ny * 14, py + nx * 14, px + ny * 14, py - nx * 14, '#74502b', 1.6));
  }
  return g;
}

// The wall ring: returns { back, front } groups (back is drawn before the buildings, front after).
function drawWall(level, onClick, title) {
  const built = level > 0;
  const H = built ? 22 + level * 1.6 : 0;
  const back = el('g', { class: 'hit', style: 'cursor:pointer' });
  const front = el('g', { class: 'hit', style: 'cursor:pointer' });
  const arc = (cy, dir) => `M${CX - TOWN_RX} ${cy}A${TOWN_RX} ${TOWN_RY} 0 0 ${dir} ${CX + TOWN_RX} ${cy}`;
  if (!built) {
    // wooden stakes along the ring
    for (const g of [back, front]) g.append(el('title', {}, title));
    for (let i = 0; i < 70; i++) {
      const a = (i / 70) * Math.PI * 2;
      const x = CX + TOWN_RX * Math.cos(a);
      const y = CY + TOWN_RY * Math.sin(a);
      const grp = Math.sin(a) < 0 ? back : front;
      grp.append(line(x, y, x, y - 14, C.woodD, 4));
      grp.append(line(x, y - 14, x, y - 17, C.woodL, 4));
    }
    back.addEventListener('click', onClick);
    front.addEventListener('click', onClick);
    return { back, front, H };
  }
  // back half: inner wall face
  back.append(el('title', {}, title));
  back.append(el('path', { d: `${arc(CY, 1)}L${CX + TOWN_RX} ${CY - H}A${TOWN_RX} ${TOWN_RY} 0 0 0 ${CX - TOWN_RX} ${CY - H}z`, fill: wallTexture('stone', '#cdbd9a'), stroke: INK, 'stroke-width': 1.4, 'stroke-linejoin': 'round' }));
  back.append(el('path', { d: arc(CY, 1), fill: 'none', stroke: '#1d1408', 'stroke-width': 10, opacity: 0.18 }));
  back.append(el('path', { d: arc(CY - H, 1), fill: 'none', stroke: INK, 'stroke-width': 16 }));
  back.append(el('path', { d: arc(CY - H, 1), fill: 'none', stroke: roofTexture('tile', '#b5543a'), 'stroke-width': 14 }));
  back.append(el('path', { d: arc(CY - H, 1), fill: 'none', stroke: 'url(#sc-roofshade2)', 'stroke-width': 14, opacity: 0.5 }));
  // front half: outer wall face
  front.append(el('title', {}, title));
  front.append(el('path', { d: `${arc(CY, 0)}L${CX + TOWN_RX} ${CY - H}A${TOWN_RX} ${TOWN_RY} 0 0 1 ${CX - TOWN_RX} ${CY - H}z`, fill: wallTexture('stone', '#ece2c6'), stroke: INK, 'stroke-width': 1.4, 'stroke-linejoin': 'round' }));
  for (let i = 1; i < 36; i++) {
    const a = Math.PI * (i / 36);
    const x = CX - TOWN_RX * Math.cos(a);
    const y = CY + TOWN_RY * Math.sin(a);
    front.append(line(x, y, x, y - H, C.wallD, 1, { opacity: 0.25 }));
  }
  front.append(el('path', { d: arc(CY, 0), fill: 'none', stroke: '#1d1408', 'stroke-width': 8, opacity: 0.16 }));
  front.append(el('path', { d: arc(CY - H, 0), fill: 'none', stroke: INK, 'stroke-width': 16 }));
  front.append(el('path', { d: arc(CY - H, 0), fill: 'none', stroke: roofTexture('tile', '#b5543a'), 'stroke-width': 14 }));
  front.append(el('path', { d: arc(CY - H, 0), fill: 'none', stroke: 'url(#sc-roofshade2)', 'stroke-width': 14, opacity: 0.5 }));
  front.addEventListener('click', onClick);
  back.addEventListener('click', onClick);
  return { back, front, H };
}

// ---------- main ----------

// Build the SVG scene. zoom: 'all' (fields + town) or 'town' (zoomed on the walled town).
export function renderScene(el0, ctx, { zoom = 'all' } = {}) {
  if (zoom === 'all') return renderLand(el0, ctx);
  const v = ctx.village;
  const bySlot = new Map(v.buildings.map((b) => [b.slot, b]));
  const queued = new Set(v.build_queue.map((q) => q.slot));
  const rng = mulberry32((v.village.id || 1) * 7919);
  const meta = ctx.meta.buildings || {};

  const viewBox = zoom === 'town' ? '175 190 650 600' : `0 0 ${W} ${W}`;
  const svg = el('svg', { class: 'scene scene-' + zoom, viewBox, preserveAspectRatio: 'xMidYMid meet', role: 'img', 'aria-label': 'หมู่บ้าน' });

  // field anchors around the ring
  const fieldAnchors = [];
  const fieldTypes = [];

  drawTerrain(svg, rng, fieldAnchors, fieldTypes);

  const slotTitle = (b) => (b && b.type ? `${b.name_th} เลเวล ${b.level}` : 'ช่องว่าง');
  const open = (slot) => () => openSlotPanel(el0, ctx, slot);

  const wallB = bySlot.get(40) || { type: 'wall', level: 0, name_th: 'กำแพง' };
  const wall = drawWall(wallB.level, open(40), slotTitle(wallB));

  // resource fields (behind the town in painter's order when above, in front when below the centre)
  const badges = el('g');
  const fieldLayer = el('g');
  const fields = fieldAnchors.map(([x, y], i) => ({ slot: i + 1, x, y }));
  fields.sort((a, b) => a.y - b.y);
  for (const f of fields) {
    const b = bySlot.get(f.slot);
    if (!b || !b.type) continue;
    const g = el('g', { class: 'hit', style: 'cursor:pointer', transform: `translate(${f.x.toFixed(1)} ${f.y.toFixed(1)})` });
    g.append(el('title', {}, slotTitle(b)));
    const scale = 0.95 + Math.min(b.level, 12) * 0.018;
    const sprite = (FIELD_SPRITES[b.type] || FIELD_SPRITES.farm)(b.level);
    const inner = el('g', { transform: `scale(${scale})`, opacity: b.level === 0 ? 0.5 : 1 });
    if (b.level === 0) inner.append(plot());
    inner.append(sprite);
    g.append(inner);
    if (queued.has(f.slot)) g.append(scaffolding());
    badges.append(placed(badge(0, 0, b.level), f.x, f.y + 30, f.slot, open));
    g.addEventListener('click', open(f.slot));
    fieldLayer.append(g);
  }
  svg.append(fieldLayer);

  svg.append(wall.back);
  drawPlaza(svg);

  // town items sorted by y (painter's algorithm); gates are items too
  const items = [];
  for (const [slotStr, pos] of Object.entries(TOWN_POS)) {
    const slot = Number(slotStr);
    items.push({ kind: 'slot', slot, x: pos[0], y: pos[1], s: pos[2] || 1 });
  }
  GATE_ANGLES.forEach((a) => {
    const [x, y] = gatePos(a);
    items.push({ kind: 'gate', x, y: y + 6, a });
  });
  // garden trees and bushes in the free spots between buildings
  const anchorsXY = Object.values(TOWN_POS);
  for (let i = 0; i < 260; i++) {
    const x = CX + (rng() - 0.5) * 2 * (TOWN_RX - 30);
    const y = CY + (rng() - 0.5) * 2 * (TOWN_RY - 30);
    if (((x - CX) / (TOWN_RX - 26)) ** 2 + ((y - CY) / (TOWN_RY - 26)) ** 2 > 1) continue;
    if (anchorsXY.some(([ax, ay]) => Math.abs(ax - x) < 50 && y - ay < 18 && ay - y < 70)) continue;
    if (((x - CX) / 120) ** 2 + ((y - CY - 20) / 62) ** 2 < 1) continue;
    const onRoad = GATE_ANGLES.some((a) => {
      const r = (a * Math.PI) / 180;
      const gx = CX + TOWN_RX * Math.cos(r);
      const gy = CY + TOWN_RY * Math.sin(r);
      const t2 = ((x - CX) * (gx - CX) + (y - CY) * (gy - CY)) / ((gx - CX) ** 2 + (gy - CY) ** 2);
      if (t2 < 0 || t2 > 1) return false;
      return Math.hypot(CX + t2 * (gx - CX) - x, CY + t2 * (gy - CY) - y) < 34;
    });
    if (onRoad) continue;
    if (items.some((o) => o.kind === 'tree' && Math.hypot(o.x - x, o.y - y) < 26)) continue;
    items.push({ kind: 'tree', x, y, r: rng() });
  }
  items.sort((p, q) => p.y - q.y);

  const town = el('g');
  const frontItems = el('g');
  for (const it of items) {
    if (it.kind === 'tree') {
      const node = it.r < 0.55 ? tree(it.x, it.y, 0.62 + it.r * 0.4, Math.floor(it.r * 10)) : it.r < 0.8 ? bush(it.x, it.y, 0.9) : pine(it.x, it.y, 0.6);
      node.setAttribute('pointer-events', 'none');
      (it.y > CY + 60 ? frontItems : town).append(node);
      continue;
    }
    if (it.kind === 'gate') {
      const target = Math.sin((it.a * Math.PI) / 180) < 0 ? town : frontItems;
      const br = bridge(it.a);
      svg.insertBefore(br, wall.back);
      const gg = el('g', { transform: `translate(${it.x.toFixed(1)} ${it.y.toFixed(1)}) scale(0.9)`, 'pointer-events': 'none' }, gateSprite(wallB.level));
      target.append(gg);
      continue;
    }
    const b = bySlot.get(it.slot);
    const g = el('g', { class: 'hit', style: 'cursor:pointer', transform: `translate(${it.x} ${it.y})` });
    g.append(el('title', {}, slotTitle(b)));
    const built = b && b.type;
    if (!built) {
      g.append(plot());
      g.append(el('g', { 'pointer-events': 'none' }, el('circle', { cx: 0, cy: -2, r: 14, fill: C.cream, stroke: C.gold, 'stroke-width': 3, opacity: 0.9 }), text(0, 6, '+', 24, '#7a6544')));
    } else {
      const lvl = b.level;
      const sc = it.s * (0.88 + Math.min(lvl, 20) * 0.012);
      const inner = el('g', { transform: `scale(${sc})`, opacity: lvl === 0 ? 0.5 : 1 });
      if (lvl === 0) inner.append(plot());
      inner.append((SPRITES[b.type] || SPRITES.warehouse)(lvl));
      g.append(inner);
      if (queued.has(it.slot)) g.append(scaffolding());
      badges.append(placed(badge(0, 0, lvl), it.x, it.y + 22, it.slot, open));
    }
    g.addEventListener('click', open(it.slot));
    (it.y > CY + 60 ? frontItems : town).append(g);
  }
  svg.append(town);
  svg.append(wall.front);
  svg.append(frontItems);
  svg.append(badges);
  void meta;
  return svg;
}

const BOXES = { all: [0, 0, 1000, 760], town: [150, 150, 700, 700] };
const savedView = {};

// The full-screen frame around the scene: fits the whole picture to the screen, drag to pan, wheel/pinch to zoom.
export function sceneFrame(el0, ctx, zoom) {
  const frame = document.createElement('div');
  frame.className = 'scene-frame';
  const svg = renderScene(el0, ctx, { zoom });
  svg.removeAttribute('role');
  frame.append(svg);
  const base = BOXES[zoom];
  const vb = savedView[zoom] ? { ...savedView[zoom] } : { x: base[0], y: base[1], w: base[2], h: base[3] };

  const pxPerUnit = () => {
    const r = svg.getBoundingClientRect();
    return Math.min(r.width / vb.w, r.height / vb.h) || 1;
  };
  const apply = () => {
    const cx = vb.x + vb.w / 2;
    const cy = vb.y + vb.h / 2;
    const lo = -150;
    const hi = W + 150;
    if (cx < lo) vb.x += lo - cx;
    if (cx > hi) vb.x -= cx - hi;
    if (cy < lo) vb.y += lo - cy;
    if (cy > hi) vb.y -= cy - hi;
    svg.setAttribute('viewBox', `${vb.x.toFixed(1)} ${vb.y.toFixed(1)} ${vb.w.toFixed(1)} ${vb.h.toFixed(1)}`);
    savedView[zoom] = { ...vb };
    // keep the level badges readable at any zoom
    const k = Math.min(2.6, Math.max(0.3, 12 / (17 * pxPerUnit())));
    svg.style.setProperty('--bk', k.toFixed(2));
  };
  const zoomAt = (clientX, clientY, factor) => {
    const r = svg.getBoundingClientRect();
    const ppu = pxPerUnit();
    // svg point under the cursor (meet: the picture is centred in the element)
    const offX = (r.width - vb.w * ppu) / 2;
    const offY = (r.height - vb.h * ppu) / 2;
    const ux = vb.x + (clientX - r.left - offX) / ppu;
    const uy = vb.y + (clientY - r.top - offY) / ppu;
    const nw = Math.min(base[2], Math.max(base[2] / 3.5, vb.w / factor));
    const nh = (nw / vb.w) * vb.h;
    const fx = (ux - vb.x) / vb.w;
    const fy = (uy - vb.y) / vb.h;
    vb.x = ux - fx * nw;
    vb.y = uy - fy * nh;
    vb.w = nw;
    vb.h = nh;
    apply();
  };
  const zoomCentre = (factor) => {
    const r = svg.getBoundingClientRect();
    zoomAt(r.left + r.width / 2, r.top + r.height / 2, factor);
  };
  const reset = () => {
    vb.x = base[0];
    vb.y = base[1];
    vb.w = base[2];
    vb.h = base[3];
    apply();
  };

  // pointer interaction
  const pts = new Map();
  let moved = 0;
  let pinch = 0;
  const dist = () => {
    const [a, b] = [...pts.values()];
    return Math.hypot(a.x - b.x, a.y - b.y);
  };
  svg.addEventListener('pointerdown', (e) => {
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 1) moved = 0;
    if (pts.size === 2) pinch = dist();
  });
  svg.addEventListener('pointermove', (e) => {
    const prev = pts.get(e.pointerId);
    if (!prev) return;
    const cur = { x: e.clientX, y: e.clientY };
    if (pts.size === 1) {
      const dx = cur.x - prev.x;
      const dy = cur.y - prev.y;
      moved += Math.abs(dx) + Math.abs(dy);
      if (moved > 8) {
        const ppu = pxPerUnit();
        vb.x -= dx / ppu;
        vb.y -= dy / ppu;
        apply();
      }
    } else if (pts.size === 2) {
      pts.set(e.pointerId, cur);
      const d = dist();
      const [a, b] = [...pts.values()];
      if (pinch > 0) zoomAt((a.x + b.x) / 2, (a.y + b.y) / 2, d / pinch);
      pinch = d;
      moved = 99;
    }
    pts.set(e.pointerId, cur);
  });
  const up = (e) => {
    pts.delete(e.pointerId);
    pinch = 0;
  };
  svg.addEventListener('pointerup', up);
  svg.addEventListener('pointercancel', up);
  svg.addEventListener('pointerleave', up);
  // a drag must not count as a tap on a building
  svg.addEventListener(
    'click',
    (e) => {
      if (moved > 8) {
        e.stopPropagation();
        e.preventDefault();
        moved = 0;
      }
    },
    true,
  );
  svg.addEventListener(
    'wheel',
    (e) => {
      e.preventDefault();
      zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.18 : 1 / 1.18);
    },
    { passive: false },
  );

  const btn = (label, title, fn) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'hud-zoom';
    b.textContent = label;
    b.title = title;
    b.addEventListener('click', fn);
    return b;
  };
  const zoomBox = document.createElement('div');
  zoomBox.className = 'hud-zoombox';
  zoomBox.append(btn('+', 'ซูมเข้า', () => zoomCentre(1.4)), btn('−', 'ซูมออก', () => zoomCentre(1 / 1.4)), btn('⤢', 'พอดีจอ', reset));
  frame.append(zoomBox);

  apply();
  new ResizeObserver(apply).observe(frame);
  return frame;
}

// ---------- resource landscape (village page): fields as terrain zones around a small walled village ----------

const LW = 1000;
const LH = 760;
const LCX = 500;
const LCY = 385;

// A round deciduous tree (three-lobed canopy with a lit side).
function tree(x, y, s = 1, hue = 0) {
  const greens = [['#4f8f3a', '#6fb04e', '#2f6a2a'], ['#5a9a3e', '#82bf5a', '#376f2c'], ['#467f36', '#62a147', '#2a5c25']][hue % 3];
  const g = el('g', { transform: `translate(${x.toFixed(1)} ${y.toFixed(1)}) scale(${s.toFixed(2)})` });
  g.append(shadow(6, 2, 15, 5));
  g.append(rect(-2.5, -10, 5, 11, C.woodD, { 'stroke-width': 0.9 }));
  g.append(el('circle', { cx: -7, cy: -17, r: 10, fill: greens[0], stroke: INK, 'stroke-width': 1.1 }));
  g.append(el('circle', { cx: 7, cy: -16, r: 10, fill: greens[2], stroke: INK, 'stroke-width': 1.1 }));
  g.append(el('circle', { cx: 0, cy: -26, r: 11, fill: greens[0], stroke: INK, 'stroke-width': 1.1 }));
  g.append(el('circle', { cx: -4, cy: -29, r: 5.5, fill: greens[1], opacity: 0.9 }));
  g.append(el('circle', { cx: -10, cy: -19, r: 4, fill: greens[1], opacity: 0.8 }));
  return g;
}

// A rocky mountain with a shaded right face and a snow cap.
function mountain(x, y, s = 1, snow = true) {
  const g = el('g', { transform: `translate(${x.toFixed(1)} ${y.toFixed(1)}) scale(${s.toFixed(2)})` });
  g.append(shadow(14, 2, 54, 9));
  g.append(poly([[-48, 0], [-16, -52], [-4, -40], [8, -72], [50, 0]], '#9a9fa8'));
  g.append(poly([[8, -72], [50, 0], [12, 0], [2, -30]], '#5f6570', { 'stroke-width': 0 }));
  g.append(poly([[-16, -52], [-4, -40], [-12, -20], [-26, -30]], '#c3c7ce', { 'stroke-width': 0 }));
  g.append(line(-30, -18, -14, -10, '#6b717a', 1.2));
  g.append(line(16, -36, 24, -20, '#454a52', 1.2));
  if (snow) {
    g.append(poly([[8, -72], [19, -50], [12, -54], [6, -46], [0, -54], [-3, -52]], '#f6f8fb', { 'stroke-width': 1 }));
    g.append(poly([[-16, -52], [-9, -44], [-14, -42], [-20, -45]], '#f6f8fb', { 'stroke-width': 0.9 }));
  }
  g.append(poly([[-48, 0], [-16, -52], [-4, -40], [8, -72], [50, 0]], 'none', { 'stroke-width': 1.5 }));
  return g;
}

function blobPath(cx, cy, rx, ry, rng, n = 10, wobble = 0.18) {
  const pts0 = [];
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2;
    const k = 1 + (rng() - 0.5) * 2 * wobble;
    pts0.push([cx + Math.cos(a) * rx * k, cy + Math.sin(a) * ry * k]);
  }
  let d = '';
  for (let i = 0; i < n; i++) {
    const p = pts0[i];
    const q = pts0[(i + 1) % n];
    const m = [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2];
    d += i === 0 ? `M${m[0].toFixed(1)} ${m[1].toFixed(1)}` : '';
    const nx = pts0[(i + 1) % n];
    const mm = [(nx[0] + pts0[(i + 2) % n][0]) / 2, (nx[1] + pts0[(i + 2) % n][1]) / 2];
    d += `Q${nx[0].toFixed(1)} ${nx[1].toFixed(1)} ${mm[0].toFixed(1)} ${mm[1].toFixed(1)}`;
  }
  return d + 'Z';
}

function lake(cx, cy, rx, ry, rng) {
  const g = el('g', { 'pointer-events': 'none' });
  g.append(el('path', { d: blobPath(cx, cy, rx + 9, ry + 7, rng, 9, 0.12), fill: '#cdb985', stroke: INK, 'stroke-width': 1.3 }));
  g.append(el('path', { d: blobPath(cx, cy, rx, ry, rng, 9, 0.12), fill: 'url(#sc-water)', stroke: '#3f7fa6', 'stroke-width': 1.4 }));
  for (let i = 0; i < 4; i++) {
    const yy = cy - ry * 0.4 + i * ry * 0.28;
    g.append(el('path', { d: `M${cx - rx * 0.45 + i * 6} ${yy}q8 -4 16 0t16 0`, fill: 'none', stroke: '#e9f6fb', 'stroke-width': 1.6, opacity: 0.8 }));
  }
  return g;
}

// ---- field zones ----

function zoneGround(rng, rx, ry, fill, edge) {
  return el('path', { d: blobPath(0, 0, rx, ry, rng, 10, 0.16), fill, stroke: edge, 'stroke-width': 1.6 });
}

const ZONES = {
  farm(level, rng) {
    const g = el('g');
    g.append(shadow(4, 6, 62, 34));
    g.append(zoneGround(rng, 60, 34, '#e8c255', '#9b7424'));
    g.append(el('path', { d: blobPath(0, 0, 52, 28, rng, 10, 0.1), fill: '#f2d36c', stroke: 'none', opacity: 0.8 }));
    for (let i = -3; i <= 3; i++) {
      g.append(el('path', { d: `M${-48 + Math.abs(i) * 4} ${i * 7}q48 ${i % 2 ? -5 : 5} ${96 - Math.abs(i) * 8} 0`, fill: 'none', stroke: '#b98d2c', 'stroke-width': 1.3, opacity: 0.8 }));
      for (let k = 0; k < 11; k++) {
        const x = -42 + Math.abs(i) * 4 + k * (84 - Math.abs(i) * 8) / 10;
        g.append(line(x, i * 7 - 1, x + 0.8, i * 7 - 5, k % 3 ? '#fff0a0' : '#c9962c', 1.3));
      }
    }
    const bales = Math.min(4, Math.ceil(level / 3));
    for (let i = 0; i < bales; i++) g.append(hayBale(-30 + i * 18, 22 - (i % 2) * 6, 0.62));
    if (level >= 5) g.append(hall({ w: 26, d: 18, h: 13, rh: 10, wall: '#d9a07a', wins: 0, door: true, x: 40, y: 4, planks: true }));
    return g;
  },
  woodcutter(level, rng) {
    const g = el('g');
    g.append(zoneGround(rng, 58, 36, '#4d8a37', '#2e5a24'));
    const spots = [];
    for (let i = 0; i < 16; i++) spots.push([(rng() - 0.5) * 96, (rng() - 0.5) * 52]);
    spots.sort((a, b) => a[1] - b[1]);
    const hutAt = level >= 1 ? [16, 16] : null;
    spots.forEach(([x, y], i) => {
      if (hutAt && Math.hypot(x - hutAt[0], y - hutAt[1]) < 22) return;
      g.append(i % 4 === 0 ? pine(x, y + 8, 0.65) : tree(x, y + 10, 0.72, i));
    });
    if (hutAt) {
      g.append(hall({ w: 24, d: 16, h: 12, rh: 9, wall: C.woodL, roof: '#6f4a2a', roofTex: 'thatch', wins: 0, door: true, x: hutAt[0], y: hutAt[1] + 8, planks: true }));
      if (level >= 3) g.append(el('g', { transform: `translate(${hutAt[0] + 26} ${hutAt[1] + 12}) scale(0.55)` }, logPile(0, 0, Math.min(4, 2 + Math.floor(level / 5)))));
    }
    return g;
  },
  quarry(level, rng) {
    const g = el('g');
    g.append(zoneGround(rng, 58, 34, '#a76a3e', '#6b3f22'));
    const tiers = ['#b97a48', '#9d6036', '#874f2c', '#6e3f22'];
    tiers.forEach((c, i) => {
      g.append(el('path', { d: blobPath(4 * i, 3 * i, 46 - i * 10, 26 - i * 6, rng, 9, 0.1), fill: c, stroke: '#4f2d17', 'stroke-width': 1.1 }));
      g.append(el('path', { d: `M${-40 + i * 10} ${-4 + i * 4}q${40 - i * 8} -8 ${80 - i * 18} 0`, fill: 'none', stroke: '#d7a06a', 'stroke-width': 1.4, opacity: 0.6 }));
    });
    const n = 1 + Math.min(4, Math.floor(level / 2));
    for (let i = 0; i < n; i++) g.append(block(-36 + i * 13, 26 - (i % 2) * 5, 9, 8, 7, '#c9a27a'));
    if (level >= 4) {
      g.append(line(36, 22, 36, -8, C.woodD, 2.6));
      g.append(line(36, -8, 22, -2, C.woodD, 2.2));
    }
    return g;
  },
  iron_mine(level, rng) {
    const g = el('g');
    g.append(zoneGround(rng, 58, 32, '#8e8f86', '#565851'));
    g.append(mountain(-26, 14, 0.62, true));
    g.append(mountain(22, 18, 0.74, true));
    if (level >= 1) {
      g.append(el('path', { d: 'M8 24v-12a9 9 0 0 1 18 0v12z', fill: '#17110b', stroke: INK, 'stroke-width': 1.2 }));
      g.append(rect(5, 6, 3, 18, C.wood, { 'stroke-width': 0.7 }));
      g.append(rect(26, 6, 3, 18, C.wood, { 'stroke-width': 0.7 }));
      g.append(rect(4, 4, 26, 3.5, C.woodD, { 'stroke-width': 0.7 }));
    }
    if (level >= 3) {
      const cart = el('g', { transform: 'translate(-8 30) scale(0.6)' });
      cart.append(poly([[-14, -14], [14, -14], [10, 0], [-10, 0]], '#6b4a2a'));
      cart.append(poly([[-10, -14], [-4, -22], [4, -20], [10, -14]], '#8aa0bd'));
      cart.append(el('circle', { cx: -7, cy: 1, r: 3.6, fill: '#4a4f57', stroke: INK }));
      cart.append(el('circle', { cx: 7, cy: 1, r: 3.6, fill: '#4a4f57', stroke: INK }));
      g.append(cart);
    }
    return g;
  },
};

// The small walled village in the middle of the landscape; tapping it opens the village centre.
function villageCore(ctx, bySlot) {
  const g = el('g', { class: 'hit', style: 'cursor:pointer', transform: `translate(${LCX} ${LCY}) scale(1.25)` });
  g.append(el('title', {}, 'ใจกลางหมู่บ้าน'));
  g.append(shadow(6, 10, 96, 60));
  g.append(el('ellipse', { cx: 0, cy: 0, rx: 92, ry: 62, fill: '#7fb6d6', stroke: '#3f7fa6', 'stroke-width': 2 }));
  g.append(el('ellipse', { cx: 0, cy: -2, rx: 80, ry: 53, fill: '#9ccb62', stroke: INK, 'stroke-width': 1.4 }));
  const wallLvl = (bySlot.get(40) || {}).level || 0;
  const wallFill = wallTexture('stone', '#ddd3b8');
  if (wallLvl > 0) {
    g.append(el('ellipse', { cx: 0, cy: -2, rx: 80, ry: 53, fill: 'none', stroke: INK, 'stroke-width': 9 }));
    g.append(el('ellipse', { cx: 0, cy: -2, rx: 80, ry: 53, fill: 'none', stroke: wallFill, 'stroke-width': 7 }));
    g.append(el('ellipse', { cx: 0, cy: -5, rx: 80, ry: 53, fill: 'none', stroke: '#b5543a', 'stroke-width': 2.4 }));
  } else {
    for (let i = 0; i < 40; i++) {
      const a = (i / 40) * Math.PI * 2;
      const x = 80 * Math.cos(a);
      const y = -2 + 53 * Math.sin(a);
      g.append(line(x, y, x, y - 7, C.woodD, 2.4));
    }
  }
  g.append(el('ellipse', { cx: 0, cy: 4, rx: 20, ry: 11, fill: '#cfc8b8', stroke: '#9a958a', 'stroke-width': 1.2 }));
  // a few roofs standing for the buildings that exist
  const built = [];
  for (let s = 19; s <= 38; s++) {
    const b = bySlot.get(s);
    if (b && b.type && b.level > 0) built.push(b);
  }
  const spots = [[-46, -14], [-18, -30], [16, -30], [46, -14], [-56, 12], [56, 12], [-30, 28], [30, 28], [0, -36], [-40, -30], [40, -30], [0, 34]];
  const show = Math.max(3, Math.min(spots.length, built.length));
  spots
    .slice(0, show)
    .sort((a, b) => a[1] - b[1])
    .forEach(([x, y], i) => {
      g.append(el('g', { transform: `translate(${x} ${y + 8}) scale(0.32)` }, hall({ w: 60, d: 44, h: 30, rh: 22, roof: i % 3 === 1 ? '#7f8f9c' : '#b5543a', roofTex: i % 3 === 1 ? 'slate' : 'tile', wins: 1, timber: i % 2 === 0 })));
    });
  g.append(flag(0, 2, 34));
  g.append(el('g', { transform: 'translate(0 70)' }, rect(-56, -11, 112, 22, C.cream, { rx: 11, stroke: C.plank || '#6b4a2b', 'stroke-width': 2 }), text(0, 6, 'ใจกลางหมู่บ้าน', 14, INK)));
  g.addEventListener('click', () => ctx.navigate(`#/v/${ctx.villageId}/center`));
  return g;
}

// The village page: 18 fields as terrain zones around the walled village, with forests, mountains and lakes.
function renderLand(el0, ctx) {
  const v = ctx.village;
  const bySlot = new Map(v.buildings.map((b) => [b.slot, b]));
  const queued = new Set(v.build_queue.map((q) => q.slot));
  const rng = mulberry32((v.village.id || 1) * 104729);
  const svg = el('svg', { class: 'scene scene-all', viewBox: `0 0 ${LW} ${LH}`, preserveAspectRatio: 'xMidYMid meet' });
  addDefs(svg);
  svg.append(rect(-800, -800, LW + 1600, LH + 1600, 'url(#sc-grass)', { stroke: 'none' }));
  for (let i = 0; i < 40; i++) {
    svg.append(ellipse(rng() * LW, rng() * LH, 40 + rng() * 110, 20 + rng() * 50, rng() > 0.5 ? '#b3d97d' : '#5d8f3c', { opacity: 0.15, stroke: 'none' }));
  }

  // field anchors: one organic ring, same-type slots stay together
  const anchors = [];
  for (let slot = 1; slot <= 18; slot++) {
    const a = ((-160 + (slot - 1) * 20) * Math.PI) / 180;
    const wob = slot % 2 ? 1.0 : 0.8;
    anchors.push({ slot, x: LCX + 310 * wob * Math.cos(a), y: LCY + 232 * wob * Math.sin(a) + 6 });
  }

  // paths: a ring road around the fields, one around the village, and four roads to the edge
  const paths = el('g', { fill: 'none', 'stroke-linecap': 'round', 'pointer-events': 'none' });
  const road = (d, w) => {
    paths.append(el('path', { d, stroke: '#8a6d42', 'stroke-width': w + 4, opacity: 0.45 }));
    paths.append(el('path', { d, stroke: '#d9c08a', 'stroke-width': w }));
  };
  road(`M${LCX - 395} ${LCY}a395 300 0 1 0 790 0a395 300 0 1 0 -790 0`, 7);
  road(`M${LCX - 140} ${LCY}a140 100 0 1 0 280 0a140 100 0 1 0 -280 0`, 6);
  for (const a of [-140, -40, 40, 140]) {
    const r = (a * Math.PI) / 180;
    road(`M${LCX + 92 * Math.cos(r)} ${LCY + 62 * Math.sin(r)}Q${LCX + 260 * Math.cos(r) + 20} ${LCY + 210 * Math.sin(r)} ${LCX + 640 * Math.cos(r)} ${LCY + 470 * Math.sin(r)}`, 8);
  }
  svg.append(paths);

  // lakes and a river
  const lakes = [[110, 640, 70, 38], [880, 600, 62, 34], [820, 70, 52, 26], [330, -150, 80, 36], [640, 900, 74, 34]];
  svg.append(el('path', { d: `M${lakes[2][0] - 40} ${lakes[2][1] + 10}C760 180 960 260 940 380S860 520 ${lakes[1][0]} ${lakes[1][1] - 20}`, fill: 'none', stroke: '#3f7fa6', 'stroke-width': 14, 'stroke-linecap': 'round', 'pointer-events': 'none' }));
  svg.append(el('path', { d: `M${lakes[2][0] - 40} ${lakes[2][1] + 10}C760 180 960 260 940 380S860 520 ${lakes[1][0]} ${lakes[1][1] - 20}`, fill: 'none', stroke: '#8fc8e4', 'stroke-width': 10, 'stroke-linecap': 'round', 'pointer-events': 'none' }));
  svg.append(el('path', { d: `M30 420C90 470 70 560 ${lakes[0][0]} ${lakes[0][1] - 30}`, fill: 'none', stroke: '#3f7fa6', 'stroke-width': 12, 'stroke-linecap': 'round', 'pointer-events': 'none' }));
  svg.append(el('path', { d: `M30 420C90 470 70 560 ${lakes[0][0]} ${lakes[0][1] - 30}`, fill: 'none', stroke: '#8fc8e4', 'stroke-width': 8, 'stroke-linecap': 'round', 'pointer-events': 'none' }));
  for (const [x, y, rx, ry] of lakes) svg.append(lake(x, y, rx, ry, rng));

  // scenery outside the field ring: forests, mountain ranges at the corners
  const decor = [];
  const mounts = [[70, 90, 1.3], [150, 60, 1.0], [930, 200, 1.2], [90, 300, 0.9], [640, 720, 1.0], [300, 740, 1.1], [960, 700, 0.9], [560, 40, 0.8], [200, -120, 1.4], [760, -90, 1.2], [480, -200, 1.0], [120, 900, 1.3], [820, 920, 1.4], [460, 960, 1.0]];
  for (const [x, y, s] of mounts) decor.push({ y, node: mountain(x, y, s) });
  for (let i = 0; i < 1000; i++) {
    const x = -60 + rng() * (LW + 120);
    const y = -300 + rng() * (LH + 600);
    const nx = (x - LCX) / 405;
    const ny = (y - LCY) / 310;
    if (nx * nx + ny * ny < 1) continue;
    if (lakes.some(([lx, ly, rx, ry]) => ((x - lx) / (rx + 16)) ** 2 + ((y - ly) / (ry + 14)) ** 2 < 1)) continue;
    if (mounts.some(([mx, my, s]) => Math.abs(x - mx) < 46 * s && y < my + 6 && y > my - 70 * s)) continue;
    // clustered forests: keep trees where a low-frequency noise is high
    const noise = Math.sin(x * 0.013 + 1.3) * Math.cos(y * 0.017 - 0.4) + Math.sin((x + y) * 0.007);
    if (noise < 0.15) continue;
    const r = rng();
    decor.push({ y, node: r < 0.35 ? pine(x, y, 0.7 + r) : tree(x, y, 0.7 + r * 0.6, i) });
  }
  decor.sort((a, b) => a.y - b.y);
  const deco = el('g', { 'pointer-events': 'none' });
  for (const d of decor) deco.append(d.node);
  svg.append(deco);

  // fields + village core in painter's order
  const open = (slot) => () => openSlotPanel(el0, ctx, slot);
  const badges = el('g');
  const items = anchors.map((a) => ({ ...a, kind: 'field' }));
  items.push({ kind: 'core', y: LCY });
  items.sort((p, q) => p.y - q.y);
  for (const it of items) {
    if (it.kind === 'core') {
      svg.append(villageCore(ctx, bySlot));
      continue;
    }
    const b = bySlot.get(it.slot);
    if (!b || !b.type) continue;
    const g = el('g', { class: 'hit', style: 'cursor:pointer', transform: `translate(${it.x.toFixed(1)} ${it.y.toFixed(1)})` });
    g.append(el('title', {}, `${b.name_th} เลเวล ${b.level}`));
    const zr = mulberry32((v.village.id || 1) * 31 + it.slot * 977);
    const inner = el('g', { transform: `scale(${(1.3 + Math.min(b.level, 15) * 0.012).toFixed(3)})`, opacity: b.level === 0 ? 0.62 : 1 });
    inner.append((ZONES[b.type] || ZONES.farm)(b.level, zr));
    g.append(inner);
    if (queued.has(it.slot)) g.append(el('g', { transform: 'scale(0.7)' }, scaffolding()));
    badges.append(placed(badge(0, 0, b.level), it.x, it.y - 4, it.slot, open));
    g.addEventListener('click', open(it.slot));
    svg.append(g);
  }
  svg.append(badges);
  return svg;
}

// Drawing helpers shared with the map page.
export const art = { el, rect, poly, line, ellipse, text, shadow, pine, tree, bush, rock, mountain, hall, flag, addDefs, mulberry32 };
