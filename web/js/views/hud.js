// Full-screen village scene with a HUD: name/queue pills, zoom buttons, and a drawer (queue, troops, movements, info).

import { api, ApiError } from '../api.js';
import { h, clear } from '../dom.js';
import { countdown } from '../clock.js';
import { fmtNum } from '../format.js';
import { queuePanel } from './slotpanel.js';
import { sceneFrame } from './scene.js';
import { unitLabel, unitsLine } from '../units.js';

const RES_KEYS = ['wood', 'stone', 'iron', 'food'];
const RES_LABELS = { wood: 'ไม้', stone: 'หิน', iron: 'เหล็ก', food: 'อาหาร' };
const MISSION_LABELS = {
  attack: 'โจมตี',
  raid: 'ปล้น',
  scout: 'สอดแนม',
  reinforce: 'ส่งทัพเสริม',
  settle: 'ตั้งหมู่บ้านใหม่',
  return: 'กลับบ้าน',
  trade: 'ขนส่งทรัพยากร',
};

// Heading with the village name and a rename button.
export function heading(ctx) {
  const v = ctx.village;
  const nameEl = h('h1', { class: 'village-name' }, v.village.name);
  const renameBtn = h('button', { class: 'btn small' }, 'เปลี่ยนชื่อ');
  renameBtn.addEventListener('click', async () => {
    const name = window.prompt('ชื่อหมู่บ้าน', v.village.name);
    if (name == null || name.trim() === '') return;
    try {
      await api.patch(`/villages/${ctx.villageId}`, { name: name.trim() });
      await ctx.refresh();
    } catch (err) {
      if (err instanceof ApiError) ctx.toast(err.message, true);
    }
  });
  return h('div', { class: 'village-heading' }, nameEl, renameBtn);
}

// Production rates row; the food rate is .negative when below zero.
function ratesRow(ctx) {
  const v = ctx.village;
  return h(
    'div',
    { class: 'rates-row' },
    'ผลิต/ชม.',
    ...RES_KEYS.map((k) =>
      h(
        'span',
        { class: 'rate' + (k === 'food' && (v.rates.food ?? 0) < 0 ? ' negative' : '') },
        `${RES_LABELS[k]} ${fmtNum(v.rates[k] ?? 0)}`,
      ),
    ),
  );
}

// Culture points of the player and the amount needed for the next village.
function cultureRow(ctx) {
  const player = (ctx.state && ctx.state.player) || {};
  const points = fmtNum(player.culture_points ?? 0);
  const next = player.culture_next == null ? 'สูงสุดแล้ว' : fmtNum(player.culture_next);
  return h('div', { class: 'rates-row' }, `แต้มวัฒนธรรม: ${points} / ${next}`);
}

// Troops-at-home panel.
function troopsPanel(ctx) {
  const rows = Object.entries(ctx.village.troops_home || {});
  const body = rows.length
    ? rows.map(([unit, count]) => h('div', { class: 'list-row' }, unitLabel(ctx, unit, ` x${count}`)))
    : [h('div', { class: 'list-row muted' }, 'ไม่มีทหาร')];
  return h('div', { class: 'panel' }, h('h2', { class: 'panel-heading' }, 'ทหารในหมู่บ้าน'), ...body);
}

// One movement row: direction arrow, mission, target, units, countdown.
function movementRow(ctx, m) {
  const arrow = m.direction === 'out' ? '→' : '←';
  const units = m.units == null ? null : unitsLine(ctx, m.units);
  return h(
    'div',
    { class: 'list-row movement' + (m.hostile ? ' negative' : '') },
    h('span', {}, `${arrow} ${MISSION_LABELS[m.mission] ?? m.mission}`),
    h('span', {}, `(${m.to.x}, ${m.to.y})`),
    units ? h('div', { class: 'movement-units' }, ...units) : null,
    h('span', { class: 'countdown', 'data-countdown': m.arrive_at }, countdown(m.arrive_at)),
  );
}

// Movements panel.
function movementsPanel(ctx) {
  const v = ctx.village;
  const body = v.movements.length
    ? v.movements.map((m) => movementRow(ctx, m))
    : [h('div', { class: 'list-row muted' }, 'ไม่มีทัพเคลื่อนที่')];
  return h('div', { class: 'panel' }, h('h2', { class: 'panel-heading' }, 'ทัพ'), ...body);
}


// Which drawer tab is open (kept across re-renders triggered by websocket refreshes).
let openTab = null;

const TABS = [
  { key: 'queue', label: 'ก่อสร้าง' },
  { key: 'troops', label: 'ทหาร' },
  { key: 'moves', label: 'ทัพ' },
  { key: 'info', label: 'ข้อมูล' },
];

function tabCount(ctx, key) {
  if (key === 'queue') return ctx.village.build_queue.length;
  if (key === 'moves') return ctx.village.movements.length;
  return 0;
}

function drawerBody(ctx, key) {
  if (key === 'queue') return [queuePanel(ctx)];
  if (key === 'troops') return [troopsPanel(ctx)];
  if (key === 'moves') return [movementsPanel(ctx)];
  return [heading(ctx), ratesRow(ctx), cultureRow(ctx)];
}

// Top-right pills describing the build queue (first two entries).
function queuePills(ctx) {
  const v = ctx.village;
  return v.build_queue.slice(0, 2).map((q) => {
    const b = (ctx.meta.buildings || {})[q.type] || {};
    return h(
      'div',
      { class: 'hud-pill hud-queue' },
      h('span', {}, `${b.name_th ?? q.type} -> ${q.target_level}`),
      h('span', { class: 'countdown', 'data-countdown': q.finishes_at }, countdown(q.finishes_at)),
    );
  });
}

// Render the scene page (zoom: 'all' or 'town') into el; returns the cleanup for the router.
export function renderScenePage(el, ctx, zoom) {
  clear(el);
  document.body.classList.add('scene-page');
  const drawer = h('div', { class: 'scene-drawer', hidden: true });
  const buttons = [];

  function showTab(key) {
    openTab = key;
    clear(drawer);
    if (key === null) {
      drawer.hidden = true;
    } else {
      drawer.hidden = false;
      drawer.append(
        h('button', { class: 'btn small drawer-close', type: 'button', onclick: () => showTab(null) }, 'ปิด'),
        ...drawerBody(ctx, key),
      );
    }
    buttons.forEach((b) => b.classList.toggle('active', b.dataset.tab === key));
  }

  const bar = h('div', { class: 'hud-bar' });
  for (const t of TABS) {
    const n = tabCount(ctx, t.key);
    const btn = h(
      'button',
      { class: 'hud-btn', type: 'button', dataset: { tab: t.key }, onclick: () => showTab(openTab === t.key ? null : t.key) },
      t.label,
      n > 0 ? h('span', { class: 'hud-count' }, String(n)) : null,
    );
    buttons.push(btn);
    bar.append(btn);
  }

  const name = h(
    'button',
    { class: 'hud-pill hud-name', type: 'button', onclick: () => showTab('info') },
    ctx.village.village.name,
  );
  const top = h('div', { class: 'hud-top' }, name, h('div', { class: 'hud-queues' }, ...queuePills(ctx)));

  const frame = sceneFrame(el, ctx, zoom);
  frame.append(top, drawer, bar);
  el.append(frame);
  showTab(openTab);
  return () => document.body.classList.remove('scene-page');
}
