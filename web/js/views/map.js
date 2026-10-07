// Map view: full-screen illustrated world map. Drag to pan, wheel/pinch/buttons to zoom,
// tap a tile for a sheet with details and actions (send troops, raid, scout, reinforce, settle).

import { api, ApiError } from '../api.js';
import { h, clear, icon } from '../dom.js';
import { art } from './scene.js';

const { el, rect, poly, line, ellipse, text, shadow, pine, tree, bush, rock, mountain, hall, flag, addDefs } = art;

const T = 64; // tile size in svg units
const R = 10; // radius of the loaded area (API maximum)
const RELOAD_AT = 5; // reload when the view centre drifts this many tiles from the loaded centre
const INK = '#4a3420';
const REL = {
  mine: { fill: '#4a6fa5', label: 'ของคุณ' },
  ally: { fill: '#3f8a3a', label: 'พันธมิตร' },
  enemy: { fill: '#a63d3d', label: 'ผู้เล่นอื่น' },
  bot: { fill: '#8a6a3a', label: 'bot' },
};
const KIND_LABEL = { valley: 'ทุ่งราบ (ตั้งหมู่บ้านได้)', oasis: 'โอเอซิส', mountain: 'ภูเขา', lake: 'ทะเลสาบ', ruin: 'ซากโบราณ' };
const RES_LABEL = { wood: 'ไม้', stone: 'หิน', iron: 'เหล็ก', food: 'อาหาร' };

// View state survives re-renders (websocket refreshes) within the session.
const state = { cx: null, cy: null, vb: null, selected: null, find: null };

const FIND_TABS = [
  { key: 'village', label: 'หมู่บ้าน', filters: [['all', 'ทั้งหมด'], ['player', 'ผู้เล่น'], ['bot', 'bot']] },
  { key: 'oasis', label: 'โอเอซิส', filters: [['', 'ทั้งหมด'], ['wood', 'ไม้'], ['stone', 'หิน'], ['iron', 'เหล็ก'], ['food', 'อาหาร']] },
  { key: 'valley', label: 'ที่ว่างตั้งหมู่บ้าน', filters: [['', 'ทั้งหมด'], ['wood', 'ไม้เยอะ'], ['stone', 'หินเยอะ'], ['iron', 'เหล็กเยอะ'], ['food', 'อาหารเยอะ']] },
  { key: 'ruin', label: 'ซากโบราณ', filters: [] },
];

function relation(v) {
  if (v.is_mine) return 'mine';
  if (v.is_ally) return 'ally';
  if (v.is_bot) return 'bot';
  return 'enemy';
}

function hash(x, y) {
  let n = (x * 374761393 + y * 668265263) | 0;
  n = Math.imul(n ^ (n >>> 13), 1274126177);
  return ((n ^ (n >>> 16)) >>> 0) / 4294967296;
}

function wrapDiff(a, b, size) {
  let d = (((a - b) % size) + size) % size;
  if (d > size / 2) d -= size;
  return d;
}

function useIcon(name, x, y, s) {
  const u = el('use', { href: `img/icons.svg#i-${name}`, x, y, width: s, height: s });
  return u;
}

// ---- tile art (origin = tile top-left, size T) ----

function groundTile(t) {
  const g = el('g');
  const k = hash(t.x, t.y);
  if (k > 0.7) g.append(ellipse(T * k, T * (1 - k), T * 0.9, T * 0.5, k > 0.85 ? '#b6dc80' : '#7fae4c', { stroke: 'none', opacity: 0.22 }));
  for (let i = 0; i < 3; i++) {
    const gx = 8 + hash(t.x + i, t.y * 3) * 48;
    const gy = 10 + hash(t.y + i * 7, t.x) * 46;
    g.append(el('path', { d: `M${gx} ${gy}l-2 -5M${gx} ${gy}l2 -5M${gx} ${gy}l0 -6`, stroke: '#6f9f45', 'stroke-width': 1, fill: 'none', opacity: 0.7 }));
  }
  return g;
}

function terrainArt(t) {
  const g = el('g', { 'pointer-events': 'none' });
  const k = hash(t.y, t.x);
  if (t.kind === 'mountain') {
    g.append(mountain(T / 2 - 4, T - 6, 0.62, k > 0.4));
    if (k > 0.6) g.append(rock(T * 0.78, T - 4, 0.35, '#8d887c', '#b9b4a6'));
  } else if (t.kind === 'lake') {
    g.append(el('ellipse', { cx: T / 2, cy: T / 2, rx: T * 0.62, ry: T * 0.56, fill: '#cdb985', stroke: 'none' }));
    g.append(el('ellipse', { cx: T / 2, cy: T / 2, rx: T * 0.56, ry: T * 0.5, fill: 'url(#sc-water)', stroke: 'none' }));
    g.append(el('path', { d: `M${T * 0.3} ${T * 0.45}q6 -3 12 0t12 0M${T * 0.42} ${T * 0.62}q5 -3 10 0t10 0`, stroke: '#e9f6fb', 'stroke-width': 1.5, fill: 'none', opacity: 0.85 }));
  } else if (t.kind === 'oasis') {
    g.append(shadow(T / 2 + 4, T * 0.66, 24, 7));
    g.append(ellipse(T / 2, T * 0.62, 22, 11, 'url(#sc-water)', { stroke: '#3f7fa6', 'stroke-width': 1.2 }));
    const palm = (x, y, s) => {
      const p = el('g', { transform: `translate(${x} ${y}) scale(${s})` });
      p.append(el('path', { d: 'M0 0q3 -12 -2 -26', stroke: '#8a5d33', 'stroke-width': 3, fill: 'none' }));
      for (const a of [-60, -20, 20, 60, 120, 160]) {
        p.append(el('path', { d: 'M-2 -26q10 -6 18 2q-10 -2 -18 -2z', fill: '#4f8f3a', stroke: INK, 'stroke-width': 0.8, transform: `rotate(${a} -2 -26)` }));
      }
      return p;
    };
    g.append(palm(T * 0.24, T * 0.6, 0.9));
    g.append(palm(T * 0.78, T * 0.56, 0.75));
    if (t.oasis_type) {
      g.append(el('circle', { cx: T - 13, cy: 13, r: 10, fill: '#f4ead0', stroke: '#c9a227', 'stroke-width': 2 }));
      g.append(useIcon(t.oasis_type, T - 21, 5, 16));
    }
  } else if (t.kind === 'ruin') {
    g.append(shadow(T / 2 + 3, T * 0.78, 24, 6));
    g.append(poly([[10, T * 0.8], [T - 10, T * 0.8], [T - 14, T * 0.72], [14, T * 0.72]], '#d9d0b8'));
    for (const [x, hgt] of [[18, 30], [30, 20], [42, 34]]) {
      g.append(rect(x - 4, T * 0.72 - hgt, 8, hgt, '#ece2c6', { 'stroke-width': 1 }));
      g.append(rect(x - 5.5, T * 0.72 - hgt - 3, 11, 3.5, '#d9d0b8', { 'stroke-width': 0.8 }));
    }
    g.append(rock(T * 0.78, T * 0.86, 0.3, '#cfc6ae', '#ece2c6'));
  } else {
    // valley: sometimes a few trees or bushes so the land is not empty
    if (!t.village) {
      if (k > 0.82) {
        g.append(tree(T * 0.3, T * 0.7, 0.55, Math.floor(k * 10)));
        g.append(pine(T * 0.7, T * 0.78, 0.45));
      } else if (k > 0.68) g.append(bush(T * 0.6, T * 0.7, 0.8));
      else if (k < 0.06) g.append(rock(T * 0.5, T * 0.72, 0.4));
    }
  }
  return g;
}

function villageArt(t) {
  const v = t.village;
  const rel = REL[relation(v)];
  const g = el('g', { 'pointer-events': 'none' });
  g.append(el('ellipse', { cx: T / 2, cy: T * 0.7, rx: T * 0.5, ry: T * 0.3, fill: '#d9c08a', stroke: rel.fill, 'stroke-width': 3 }));
  g.append(el('ellipse', { cx: T / 2, cy: T * 0.7, rx: T * 0.5, ry: T * 0.3, fill: rel.fill, opacity: 0.18, stroke: 'none' }));
  const n = v.population >= 150 ? 3 : v.population >= 40 ? 2 : 1;
  const spots = [[T * 0.5, T * 0.8], [T * 0.24, T * 0.64], [T * 0.72, T * 0.58]].slice(0, n);
  spots.sort((a, b) => a[1] - b[1]);
  for (const [x, y] of spots) {
    g.append(el('g', { transform: `translate(${x} ${y}) scale(0.42)` }, hall({ w: 60, d: 44, h: 30, rh: 22, roof: v.is_bot ? '#7f8f9c' : '#b5543a', roofTex: v.is_bot ? 'slate' : 'tile', wins: 1 })));
  }
  g.append(flag(T * 0.9, T * 0.72, 34, rel.fill));
  return g;
}

function label(t) {
  const v = t.village;
  const rel = REL[relation(v)];
  const name = v.name.length > 14 ? v.name.slice(0, 13) + '…' : v.name;
  const w = Math.max(40, name.length * 7.2 + 14);
  return el(
    'g',
    { class: 'map-label', transform: `translate(${T / 2} ${T + 2})`, 'pointer-events': 'none' },
    rect(-w / 2, -9, w, 16, '#f4ead0', { rx: 8, stroke: rel.fill, 'stroke-width': 1.6 }),
    text(0, 3.5, name, 10.5, INK),
  );
}

// ---- page ----

export async function render(el0, ctx, params) {
  clear(el0);
  document.body.classList.add('scene-page');
  const home = ctx.village ? ctx.village.village : { x: 0, y: 0 };
  const qx = parseInt(params.query.get('x'), 10);
  const qy = parseInt(params.query.get('y'), 10);
  if (Number.isInteger(qx) && Number.isInteger(qy)) {
    state.cx = qx;
    state.cy = qy;
    if (params.query.get('keep') !== '1') state.vb = null;
    if (params.query.get('sel') === '1') state.selected = { x: qx, y: qy };
  } else if (state.cx === null) {
    state.cx = home.x;
    state.cy = home.y;
  }

  const frame = h('div', { class: 'scene-frame map-frame' });
  const sheet = h('div', { class: 'scene-drawer map-sheet', hidden: true });
  el0.append(frame);
  let map;
  try {
    map = await api.get(`/map?cx=${state.cx}&cy=${state.cy}&r=${R}`);
  } catch (err) {
    if (err instanceof ApiError) ctx.toast(err.message, true);
    return () => document.body.classList.remove('scene-page');
  }
  const size = map.size;
  const cx = map.center.x;
  const cy = map.center.y;

  // world coordinates: tile (dx, dy) relative to the loaded centre, centre tile at (0, 0)
  const svg = el('svg', { class: 'scene map-svg', preserveAspectRatio: 'xMidYMid meet' });
  addDefs(svg);
  svg.append(rect(-R * T - 2000, -R * T - 2000, (2 * R + 1) * T + 4000, (2 * R + 1) * T + 4000, '#8fbf5a', { stroke: 'none' }));
  const ground = el('g');
  const terrain = el('g');
  const grid = el('g', { class: 'map-grid', 'pointer-events': 'none' });
  const labels = el('g');
  const tiles = map.tiles.map((t) => ({ ...t, dx: wrapDiff(t.x, cx, size), dy: wrapDiff(t.y, cy, size) }));
  tiles.sort((a, b) => a.dy - b.dy || a.dx - b.dx);
  const byPos = new Map(tiles.map((t) => [`${t.dx},${t.dy}`, t]));
  for (const t of tiles) {
    const ox = t.dx * T;
    const oy = t.dy * T;
    ground.append(el('g', { transform: `translate(${ox} ${oy})` }, groundTile(t)));
    grid.append(rect(ox, oy, T, T, 'none', { stroke: '#4a3420', 'stroke-width': 0.6, opacity: 0.12 }));
  }
  for (const t of tiles) {
    const ox = t.dx * T;
    const oy = t.dy * T;
    const g = el('g', { transform: `translate(${ox} ${oy})` });
    g.append(terrainArt(t));
    if (t.village) {
      g.append(villageArt(t));
      labels.append(el('g', { transform: `translate(${ox} ${oy})` }, label(t)));
    }
    if (t.oasis && t.oasis.owner_village_id != null) {
      g.append(rect(3, 3, T - 6, T - 6, 'none', { stroke: t.oasis.owned_by_me ? REL.mine.fill : REL.enemy.fill, 'stroke-width': 2.5, rx: 6, 'stroke-dasharray': '6 4' }));
    }
    terrain.append(g);
  }
  // home marker
  const hx = wrapDiff(home.x, cx, size);
  const hy = wrapDiff(home.y, cy, size);
  const homeRing = rect(hx * T + 2, hy * T + 2, T - 4, T - 4, 'none', { stroke: '#c9a227', 'stroke-width': 3, rx: 8, 'pointer-events': 'none' });
  const selRing = rect(0, 0, T - 2, T - 2, 'none', { class: 'map-sel', stroke: '#fff3b0', 'stroke-width': 3.5, rx: 8, 'pointer-events': 'none', visibility: 'hidden' });
  svg.append(ground, grid, terrain, homeRing, selRing, labels);
  frame.append(svg);

  // ---- view box, pan and zoom ----
  const vb = state.vb ? { ...state.vb } : null;
  const view = vb || { x: 0, y: 0, w: 0, h: 0 };
  const fit = () => {
    const r = frame.getBoundingClientRect();
    const px = r.width < 600 ? 50 : 66; // pixels per tile on first load
    view.w = (r.width / px) * T;
    view.h = (r.height / px) * T;
    view.x = (wrapDiff(state.cx, cx, size) + 0.5) * T - view.w / 2;
    view.y = (wrapDiff(state.cy, cy, size) + 0.5) * T - view.h / 2;
  };
  if (!vb) fit();
  const ppu = () => {
    const r = svg.getBoundingClientRect();
    return Math.min(r.width / view.w, r.height / view.h) || 1;
  };
  const apply = () => {
    const lim = (R + 0.5) * T;
    const mx = view.x + view.w / 2;
    const my = view.y + view.h / 2;
    if (mx < -lim) view.x += -lim - mx;
    if (mx > lim) view.x -= mx - lim;
    if (my < -lim) view.y += -lim - my;
    if (my > lim) view.y -= my - lim;
    svg.setAttribute('viewBox', `${view.x.toFixed(1)} ${view.y.toFixed(1)} ${view.w.toFixed(1)} ${view.h.toFixed(1)}`);
    svg.classList.toggle('far', ppu() * T < 40);
    state.vb = { ...view };
    const ccx = Math.round((view.x + view.w / 2) / T - 0.5);
    const ccy = Math.round((view.y + view.h / 2) / T - 0.5);
    coordText.textContent = `(${wrapCoord(cx + ccx)}, ${wrapCoord(cy + ccy)})`;
  };
  const wrapCoord = (c) => {
    const half = Math.floor(size / 2);
    return ((((c + half) % size) + size) % size) - half;
  };
  const zoomAt = (clientX, clientY, f) => {
    const r = svg.getBoundingClientRect();
    const p = ppu();
    const offX = (r.width - view.w * p) / 2;
    const offY = (r.height - view.h * p) / 2;
    const ux = view.x + (clientX - r.left - offX) / p;
    const uy = view.y + (clientY - r.top - offY) / p;
    const nw = Math.min(T * 24, Math.max(T * 3, view.w / f));
    const nh = (nw / view.w) * view.h;
    view.x = ux - ((ux - view.x) / view.w) * nw;
    view.y = uy - ((uy - view.y) / view.h) * nh;
    view.w = nw;
    view.h = nh;
    apply();
  };
  const zoomCentre = (f) => {
    const r = svg.getBoundingClientRect();
    zoomAt(r.left + r.width / 2, r.top + r.height / 2, f);
  };
  // reload around the view centre after a long pan
  const maybeReload = () => {
    const mx = (view.x + view.w / 2) / T - 0.5;
    const my = (view.y + view.h / 2) / T - 0.5;
    if (Math.abs(mx) < RELOAD_AT && Math.abs(my) < RELOAD_AT) return;
    const nx = wrapCoord(cx + Math.round(mx));
    const ny = wrapCoord(cy + Math.round(my));
    state.vb = { ...view, x: view.x - Math.round(mx) * T, y: view.y - Math.round(my) * T };
    state.cx = nx;
    state.cy = ny;
    ctx.navigate(`#/map?x=${nx}&y=${ny}&keep=1`);
  };

  const pts = new Map();
  let moved = 0;
  let pinch = 0;
  svg.addEventListener('pointerdown', (e) => {
    pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.size === 1) moved = 0;
    if (pts.size === 2) {
      const [a, b] = [...pts.values()];
      pinch = Math.hypot(a.x - b.x, a.y - b.y);
    }
  });
  svg.addEventListener('pointermove', (e) => {
    const prev = pts.get(e.pointerId);
    if (!prev) return;
    const cur = { x: e.clientX, y: e.clientY };
    pts.set(e.pointerId, cur);
    if (pts.size === 1) {
      moved += Math.abs(cur.x - prev.x) + Math.abs(cur.y - prev.y);
      if (moved > 6) {
        const p = ppu();
        view.x -= (cur.x - prev.x) / p;
        view.y -= (cur.y - prev.y) / p;
        apply();
      }
    } else if (pts.size === 2) {
      const [a, b] = [...pts.values()];
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if (pinch > 0) zoomAt((a.x + b.x) / 2, (a.y + b.y) / 2, d / pinch);
      pinch = d;
      moved = 99;
    }
  });
  const up = (e) => {
    if (!pts.has(e.pointerId)) return;
    pts.delete(e.pointerId);
    pinch = 0;
    if (pts.size === 0 && moved > 6) maybeReload();
  };
  const tileAt = (clientX, clientY) => {
    const r = svg.getBoundingClientRect();
    const p = ppu();
    const ux = view.x + (clientX - r.left - (r.width - view.w * p) / 2) / p;
    const uy = view.y + (clientY - r.top - (r.height - view.h * p) / 2) / p;
    return byPos.get(`${Math.floor(ux / T)},${Math.floor(uy / T)}`);
  };
  svg.addEventListener('click', (e) => {
    if (moved > 6) return;
    const t = tileAt(e.clientX, e.clientY);
    if (t) select(t);
  });
  svg.addEventListener('pointerup', up);
  svg.addEventListener('pointercancel', up);
  svg.addEventListener('wheel', (e) => {
    e.preventDefault();
    zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.18 : 1 / 1.18);
  }, { passive: false });

  // ---- tile sheet ----
  function dist(t) {
    const dx = Math.abs(wrapDiff(t.x, home.x, size));
    const dy = Math.abs(wrapDiff(t.y, home.y, size));
    return Math.sqrt(dx * dx + dy * dy);
  }
  function select(t) {
    state.selected = { x: t.x, y: t.y };
    findPanel.hidden = true;
    state.find = null;
    selRing.setAttribute('x', t.dx * T + 1);
    selRing.setAttribute('y', t.dy * T + 1);
    selRing.setAttribute('visibility', 'visible');
    clear(sheet);
    sheet.hidden = false;
    const v = t.village;
    const titleText = v ? v.name : KIND_LABEL[t.kind] ?? t.kind;
    sheet.append(
      h('button', { class: 'btn small drawer-close', type: 'button', onclick: () => { sheet.hidden = true; state.selected = null; selRing.setAttribute('visibility', 'hidden'); } }, 'ปิด'),
      h('h2', { class: 'panel-heading' }, titleText),
      h('div', { class: 'map-facts' },
        h('span', { class: 'map-chip' }, `(${t.x}, ${t.y})`),
        h('span', { class: 'map-chip' }, `ห่าง ${dist(t).toFixed(1)} ช่อง`),
        v ? h('span', { class: 'map-chip', style: { borderColor: REL[relation(v)].fill } }, REL[relation(v)].label) : null,
      ),
    );
    const rows = [];
    if (v) {
      rows.push(['ผู้เล่น', v.player_name]);
      rows.push(['เผ่า', (ctx.meta.tribes || {})[v.tribe]?.name_th ?? v.tribe]);
      rows.push(['ประชากร', String(v.population)]);
      if (v.alliance) rows.push(['พันธมิตร', v.alliance]);
    } else if (t.oasis && t.kind === 'oasis') {
      rows.push(['โบนัสผลิต', `${RES_LABEL[t.oasis_type] ?? t.oasis_type} +25%`]);
      rows.push(['สัตว์ป่า', String(t.oasis.animals)]);
      rows.push(['เจ้าของ', t.oasis.owner_village_id == null ? 'ยังไม่มี' : t.oasis.owned_by_me ? 'ของคุณ' : 'มีเจ้าของแล้ว']);
    } else if (t.oasis && t.kind === 'ruin') {
      rows.push(['ผู้พิทักษ์', String(t.oasis.animals)]);
      rows.push(['เจ้าของ', t.oasis.owner_village_id == null ? 'ยังไม่มี' : t.oasis.owned_by_me ? 'ของคุณ' : 'มีเจ้าของแล้ว']);
    } else if (t.kind === 'valley' && t.layout) {
      const [w, s, i, f] = t.layout.split('-');
      rows.push(['ทุ่งทรัพยากร', `ไม้ ${w} · หิน ${s} · เหล็ก ${i} · อาหาร ${f}`]);
    }
    for (const [k, val] of rows) sheet.append(h('div', { class: 'list-row' }, h('span', { class: 'muted' }, k), h('span', {}, val)));

    const go = (mission) => ctx.navigate(`#/rally/${ctx.villageId}?x=${t.x}&y=${t.y}${mission ? `&mission=${mission}` : ''}`);
    const actions = h('div', { class: 'map-actions' });
    const btn = (label2, mission, primary) => h('button', { class: 'btn' + (primary ? ' btn-primary' : ''), type: 'button', onclick: () => go(mission) }, label2);
    if (v && v.is_mine) {
      actions.append(h('button', { class: 'btn btn-primary', type: 'button', onclick: () => ctx.navigate(`#/v/${v.id}`) }, 'เข้าหมู่บ้าน'));
    } else if (v && v.is_ally) {
      actions.append(btn('ส่งกำลังเสริม', 'reinforce', true));
    } else if (v) {
      actions.append(btn('โจมตี', 'attack', true), btn('ปล้น', 'raid'), btn('สอดแนม', 'scout'), btn('ส่งกำลังเสริม', 'reinforce'));
    } else if (t.kind === 'oasis' || t.kind === 'ruin') {
      actions.append(btn('โจมตี', 'attack', true), btn('ปล้น', 'raid'));
    } else if (t.kind === 'valley') {
      actions.append(btn('ตั้งหมู่บ้านที่นี่', 'settle', true));
    }
    if (actions.childElementCount) sheet.append(actions);
  }

  // ---- HUD ----
  const xIn = h('input', { type: 'number', value: String(state.cx), 'aria-label': 'x' });
  const yIn = h('input', { type: 'number', value: String(state.cy), 'aria-label': 'y' });
  const coordText = h('span', { class: 'map-coord' }, '');
  const search = h(
    'form',
    {
      class: 'hud-pill map-search',
      onsubmit: (e) => {
        e.preventDefault();
        const nx = parseInt(xIn.value, 10);
        const ny = parseInt(yIn.value, 10);
        if (!Number.isInteger(nx) || !Number.isInteger(ny)) return;
        state.vb = null;
        ctx.navigate(`#/map?x=${nx}&y=${ny}`);
      },
    },
    h('span', {}, 'X'),
    xIn,
    h('span', {}, 'Y'),
    yIn,
    h('button', { class: 'btn small', type: 'submit' }, 'ไป'),
  );
  const homeBtn = h('button', { class: 'hud-pill', type: 'button', onclick: () => { state.vb = null; ctx.navigate(`#/map?x=${home.x}&y=${home.y}`); } }, '⌂ หมู่บ้านของฉัน');
  const findPanel = h('div', { class: 'scene-drawer map-find', hidden: true });
  const findBtn = h('button', { class: 'hud-pill map-find-btn', type: 'button', onclick: () => toggleFind() }, '🔍 ค้นหาใกล้สุด');

  function toggleFind(force) {
    const open = force ?? findPanel.hidden;
    if (!open) {
      findPanel.hidden = true;
      state.find = null;
      return;
    }
    if (!state.find) state.find = { kind: 'village', filter: 'all' };
    sheet.hidden = true;
    drawFind();
  }

  async function drawFind() {
    const f = state.find;
    clear(findPanel);
    findPanel.hidden = false;
    const tab = FIND_TABS.find((x) => x.key === f.kind);
    findPanel.append(
      h('button', { class: 'btn small drawer-close', type: 'button', onclick: () => toggleFind(false) }, 'ปิด'),
      h('h2', { class: 'panel-heading' }, `ใกล้หมู่บ้าน (${home.x}, ${home.y}) ที่สุด`),
      h('div', { class: 'find-tabs' }, ...FIND_TABS.map((x) =>
        h('button', { class: 'find-chip' + (x.key === f.kind ? ' active' : ''), type: 'button', onclick: () => { state.find = { kind: x.key, filter: x.filters[0] ? x.filters[0][0] : '' }; drawFind(); } }, x.label))),
    );
    if (tab.filters.length) {
      findPanel.append(h('div', { class: 'find-tabs find-filters' }, ...tab.filters.map(([val, lab]) =>
        h('button', { class: 'find-chip small' + (val === f.filter ? ' active' : ''), type: 'button', onclick: () => { state.find = { ...f, filter: val }; drawFind(); } }, lab))));
    }
    const list = h('div', { class: 'find-list' }, h('div', { class: 'muted' }, 'กำลังค้นหา...'));
    findPanel.append(list);
    const q = new URLSearchParams({ kind: f.kind, from_x: home.x, from_y: home.y, limit: '25' });
    if (f.kind === 'village') q.set('who', f.filter || 'all');
    else if (f.filter) q.set('resource', f.filter);
    let rows;
    try {
      rows = await api.get(`/map/nearest?${q}`);
    } catch (err) {
      if (err instanceof ApiError) ctx.toast(err.message, true);
      return;
    }
    if (state.find !== f) return;
    clear(list);
    if (!rows.length) list.append(h('div', { class: 'muted' }, 'ไม่พบ'));
    for (const r of rows) {
      let iconName = 'village';
      let title = '';
      let sub = '';
      if (r.kind === 'village') {
        title = r.name;
        sub = `${r.player_name}${r.is_bot ? ' · bot' : ''}${r.is_ally ? ' · พันธมิตร' : ''}`;
      } else if (r.kind === 'oasis') {
        iconName = r.oasis_type || 'oasis';
        title = `โอเอซิส${RES_LABEL[r.oasis_type] ?? ''} +25%`;
        sub = `สัตว์ป่า ${r.animals}${r.owned ? ' · มีเจ้าของ' : ''}`;
      } else if (r.kind === 'valley') {
        iconName = 'map';
        const [w, s2, i2, fd] = (r.layout || '').split('-');
        title = 'ที่ว่างตั้งหมู่บ้าน';
        sub = `ไม้ ${w} · หิน ${s2} · เหล็ก ${i2} · อาหาร ${fd}`;
      } else {
        iconName = 'ruin';
        title = 'ซากโบราณ';
        sub = `ผู้พิทักษ์ ${r.animals}${r.owned ? ' · มีเจ้าของ' : ''}`;
      }
      list.append(
        h(
          'button',
          {
            class: 'find-row',
            type: 'button',
            onclick: () => {
              state.vb = null;
              state.find = null;
              findPanel.hidden = true;
              ctx.navigate(`#/map?x=${r.x}&y=${r.y}&sel=1`);
            },
          },
          icon(iconName, 'ico find-ico'),
          h('span', { class: 'find-main' }, h('b', {}, title), h('span', { class: 'muted' }, sub)),
          h('span', { class: 'find-dist' }, h('b', {}, `${r.distance.toFixed(1)}`), h('span', { class: 'muted' }, `(${r.x}, ${r.y})`)),
        ),
      );
    }
  }
  const legend = h(
    'div',
    { class: 'hud-pill map-legend' },
    ...Object.values(REL).map((r2) => h('span', { class: 'legend-item' }, h('i', { style: { background: r2.fill } }), r2.label)),
  );
  const top = h('div', { class: 'hud-top map-top' }, h('div', { class: 'map-top-left' }, search, coordText), h('div', { class: 'map-top-right' }, findBtn, homeBtn, legend));
  const zoomBox = h(
    'div',
    { class: 'hud-zoombox map-zoombox' },
    h('button', { class: 'hud-zoom', type: 'button', title: 'ซูมเข้า', onclick: () => zoomCentre(1.4) }, '+'),
    h('button', { class: 'hud-zoom', type: 'button', title: 'ซูมออก', onclick: () => zoomCentre(1 / 1.4) }, '−'),
  );
  frame.append(top, zoomBox, sheet, findPanel);
  if (state.find) drawFind();

  apply();
  const ro = new ResizeObserver(() => apply());
  ro.observe(frame);
  if (state.selected) {
    const t = tiles.find((tt) => tt.x === state.selected.x && tt.y === state.selected.y);
    if (t) select(t);
  }
  return () => {
    ro.disconnect();
    document.body.classList.remove('scene-page');
  };
}
