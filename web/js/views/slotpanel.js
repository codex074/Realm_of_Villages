// Shared build queue panel and slot bottom sheet (BUILD.md section 10).

import { api, ApiError } from '../api.js';
import { h } from '../dom.js';
import { countdown } from '../clock.js';
import { fmtNum, fmtDuration } from '../format.js';

const RES_KEYS = ['wood', 'stone', 'iron', 'food'];
const RES_LABELS = { wood: 'ไม้', stone: 'หิน', iron: 'เหล็ก', food: 'อาหาร' };

// Cost rows for the four resources, flagged .negative when the village lacks them.
function costRows(ctx, cost) {
  return RES_KEYS.map((k) => {
    const need = cost[k] ?? 0;
    const have = ctx.village.resources[k] ?? 0;
    return h(
      'span',
      { class: 'cost' + (have < need ? ' negative' : '') },
      `${RES_LABELS[k]} ${fmtNum(need)}`,
    );
  });
}

// One block per upgrade/option: optional name, costs, build time, missing, button.
function costBlock(ctx, cost, btn, name) {
  const block = h('div', { class: 'slot-option' });
  if (name) block.append(h('div', { class: 'slot-option-name' }, name));
  block.append(
    h('div', { class: 'cost-rows' }, ...costRows(ctx, cost.cost)),
    h('div', { class: 'muted' }, `เวลา ${fmtDuration(cost.time_s)}`),
  );
  for (const m of cost.missing) block.append(h('div', { class: 'negative' }, m));
  block.append(btn);
  return block;
}

// POST a build/upgrade, toast the result, refresh; re-enable the button on error.
async function doBuild(btn, ctx, slot, type) {
  btn.disabled = true;
  try {
    await api.post(`/villages/${ctx.villageId}/build`, { slot, type });
    ctx.toast('เริ่มก่อสร้างแล้ว');
    await ctx.refresh();
  } catch (err) {
    if (err instanceof ApiError) ctx.toast(err.message, true);
    btn.disabled = false;
  }
}

// Build queue panel: heading, one row per queued entry with countdown, capacity text.
export function queuePanel(ctx) {
  const v = ctx.village;
  const rows = v.build_queue.map((q) => {
    const b = (ctx.meta.buildings || {})[q.type] || {};
    return h(
      'div',
      { class: 'list-row' },
      h('span', {}, `${b.name_th ?? q.type} -> เลเวล ${q.target_level}`),
      h('span', { class: 'countdown', 'data-countdown': q.finishes_at }, countdown(q.finishes_at)),
    );
  });
  const body = rows.length
    ? rows
    : [h('div', { class: 'list-row muted' }, 'ไม่มีการก่อสร้าง')];
  return h(
    'div',
    { class: 'panel' },
    h('h2', { class: 'panel-heading' }, 'คิวก่อสร้าง'),
    ...body,
    h('div', { class: 'muted' }, `ช่องก่อสร้าง: ${v.build_queue.length}/${v.queue_limit}`),
  );
}

// Open (or replace) the bottom sheet for one building slot with its SlotView.
export async function openSlotPanel(el, ctx, slot) {
  for (const s of el.querySelectorAll('.bottom-sheet')) s.remove();
  let view;
  try {
    view = await api.get(`/villages/${ctx.villageId}/slots/${slot}`);
  } catch (err) {
    if (err instanceof ApiError) ctx.toast(err.message, true);
    return;
  }
  const underConstruction = ctx.village.build_queue.some((q) => q.slot === slot);
  const sheet = h('div', { class: 'bottom-sheet' });
  sheet.append(
    h('button', { class: 'btn', onclick: () => sheet.remove() }, 'ปิด'),
  );
  const title = view.current
    ? `${view.current.name_th ?? ''} เลเวล ${view.current.level}`
    : `ช่องว่าง #${slot}`;
  sheet.append(h('h2', { class: 'panel-heading' }, title));
  if (underConstruction) {
    sheet.append(h('div', { class: 'muted' }, 'กำลังก่อสร้างอยู่'));
  }
  if (view.upgrade) {
    const btn = h(
      'button',
      {
        class: 'btn btn-primary',
        disabled: !view.upgrade.affordable || underConstruction,
      },
      `อัปเกรดเป็นเลเวล ${view.current.level + 1}`,
    );
    btn.addEventListener('click', () => doBuild(btn, ctx, slot, view.current.type));
    sheet.append(costBlock(ctx, view.upgrade, btn));
  }
  for (const opt of view.options) {
    const btn = h(
      'button',
      { class: 'btn btn-primary', disabled: !opt.affordable || underConstruction },
      'สร้าง',
    );
    btn.addEventListener('click', () => doBuild(btn, ctx, slot, opt.type));
    sheet.append(costBlock(ctx, opt, btn, opt.name_th));
  }
  if (view.current) await appendTraining(ctx, sheet, view.current);
  el.append(sheet);
}

// POST a train order, toast the result, refresh; re-enable the button on error.
async function doTrain(btn, input, ctx, unit, count) {
  btn.disabled = true;
  try {
    await api.post(`/villages/${ctx.villageId}/train`, { unit, count });
    ctx.toast('เริ่มฝึกแล้ว');
    await ctx.refresh();
  } catch (err) {
    if (err instanceof ApiError) ctx.toast(err.message, true);
    btn.disabled = false;
    input.disabled = false;
  }
}

// Training section of the slot sheet: train options and the training queue.
async function appendTraining(ctx, sheet, current) {
  let options;
  try {
    options = (await api.get(`/villages/${ctx.villageId}/train-options`)).filter(
      (o) => o.building === current.type,
    );
  } catch {
    options = [];
  }
  if (options.length) {
    sheet.append(h('h3', {}, 'ฝึกทหาร'));
    for (const opt of options) {
      const input = h('input', {
        type: 'number',
        min: '1',
        value: '1',
        max: opt.max_affordable > 0 ? String(opt.max_affordable) : null,
      });
      const btn = h(
        'button',
        { class: 'btn btn-primary', disabled: opt.missing.length > 0 || opt.max_affordable === 0 },
        'ฝึก',
      );
      btn.addEventListener('click', () =>
        doTrain(btn, input, ctx, opt.unit, Number(input.value) || 1),
      );
      const block = h(
        'div',
        { class: 'slot-option' },
        h('div', { class: 'slot-option-name' }, opt.name_th),
        h('div', { class: 'cost-rows' }, ...costRows(ctx, opt.cost)),
        h('div', { class: 'muted' }, `เวลา ${fmtDuration(opt.time_s)}`),
      );
      for (const m of opt.missing) block.append(h('div', { class: 'negative' }, m));
      block.append(
        h('div', { class: 'unit-row' }, h('span', {}, 'จำนวน'), input),
        h('div', { class: 'muted' }, `ฝึกได้สูงสุด ${opt.max_affordable}`),
        btn,
      );
      sheet.append(block);
    }
  }
  const queue = (ctx.village.training || []).filter((t) => t.building === current.type);
  const rows = queue.length
    ? queue.map((t) =>
        h(
          'div',
          { class: 'list-row' },
          h('span', {}, `${(ctx.meta.units || {})[t.unit]?.name_th ?? t.unit}: ${t.count_done}/${t.count_total}`),
          h('span', { class: 'countdown', 'data-countdown': t.next_at }, countdown(t.next_at)),
        ),
      )
    : [h('div', { class: 'list-row muted' }, 'ไม่มีคิวฝึก')];
  sheet.append(h('h3', {}, 'คิวฝึกทหาร'), ...rows);
}
