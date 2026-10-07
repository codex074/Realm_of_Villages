// Village view: fields grid, build queue, troops and movements (BUILD.md section 10).

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

// Render the village page into el.
export async function render(el, ctx) {
  clear(el);
  const v = ctx.village;
  el.append(
    heading(ctx),
    ratesRow(ctx),
    cultureRow(ctx),
    sceneFrame(el, ctx, 'all'),
    queuePanel(ctx),
    troopsPanel(ctx),
    movementsPanel(ctx),
  );
}
