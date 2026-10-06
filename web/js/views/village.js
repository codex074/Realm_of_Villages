// Village view: fields grid, build queue, troops and movements (BUILD.md section 10).

import { api, ApiError } from '../api.js';
import { h, clear } from '../dom.js';
import { countdown } from '../clock.js';
import { fmtNum } from '../format.js';
import { queuePanel, openSlotPanel } from './slotpanel.js';

const RES_KEYS = ['wood', 'stone', 'iron', 'food'];
const RES_LABELS = { wood: 'ไม้', stone: 'หิน', iron: 'เหล็ก', food: 'อาหาร' };
const MISSION_LABELS = {
  attack: 'โจมตี',
  raid: 'ปล้น',
  scout: 'สอดแนม',
  reinforce: 'ส่งทัพเสริม',
  settle: 'ตั้งหมู่บ้านใหม่',
  return: 'กลับบ้าน',
};

// Heading with the village name and a rename button.
function heading(ctx) {
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

// One field slot cell (slots 1..18).
function fieldCell(el, ctx, b) {
  const meta = (ctx.meta.buildings || {})[b.type] || {};
  const classes = ['slot'];
  if (b.type) {
    if (meta.produces) classes.push(meta.produces);
    else classes.push('empty');
  } else {
    classes.push('empty');
  }
  if (ctx.village.build_queue.some((q) => q.slot === b.slot)) classes.push('building');
  const cell = h(
    'div',
    { class: classes.join(' ') },
    h('div', { class: 'slot-level' }, String(b.level)),
    h('div', { class: 'slot-label' }, b.name_th ?? 'ว่าง'),
  );
  cell.addEventListener('click', () => openSlotPanel(el, ctx, b.slot));
  return cell;
}

// Troops-at-home panel.
function troopsPanel(ctx) {
  const rows = Object.entries(ctx.village.troops_home || {});
  const body = rows.length
    ? rows.map(([unit, count]) =>
        h('div', { class: 'list-row' }, `${(ctx.meta.units || {})[unit]?.name_th ?? unit} x${count}`),
      )
    : [h('div', { class: 'list-row muted' }, 'ไม่มีทหาร')];
  return h('div', { class: 'panel' }, h('h2', { class: 'panel-heading' }, 'ทหารในหมู่บ้าน'), ...body);
}

// One movement row: direction arrow, mission, target, units, countdown.
function movementRow(ctx, m) {
  const arrow = m.direction === 'out' ? '→' : '←';
  const units =
    m.units == null
      ? null
      : Object.entries(m.units)
          .map(([unit, count]) => `${(ctx.meta.units || {})[unit]?.name_th ?? unit} x${count}`)
          .join(', ');
  return h(
    'div',
    { class: 'list-row movement' + (m.hostile ? ' negative' : '') },
    h('span', {}, `${arrow} ${MISSION_LABELS[m.mission] ?? m.mission}`),
    h('span', {}, `(${m.to.x}, ${m.to.y})`),
    units ? h('div', { class: 'movement-units' }, units) : null,
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

// Render the village page into el.
export async function render(el, ctx) {
  clear(el);
  const v = ctx.village;
  const grid = h('div', { class: 'field-grid' });
  for (const b of v.buildings) {
    if (b.slot >= 1 && b.slot <= 18) grid.append(fieldCell(el, ctx, b));
  }
  el.append(
    heading(ctx),
    ratesRow(ctx),
    h('div', { class: 'panel' }, grid),
    queuePanel(ctx),
    troopsPanel(ctx),
    movementsPanel(ctx),
  );
}
