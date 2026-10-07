// Shared build queue panel and slot bottom sheet (BUILD.md section 10).

import { api, ApiError } from '../api.js';
import { h, icon, clear } from '../dom.js';
import { countdown } from '../clock.js';
import { fmtNum, fmtDuration, fmtRate } from '../format.js';
import { unitLabel } from '../units.js';

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

// Hourly output of a field: now, next level, and the table of every level.
function productionBlock(prod, level) {
  const rows = prod.levels;
  const cur = rows.find((r) => r.level === level);
  const next = rows.find((r) => r.level === level + 1);
  const label = RES_LABELS[prod.resource] ?? prod.resource;
  const box = h(
    'div',
    { class: 'slot-option production' },
    h('div', { class: 'slot-option-name' }, h('span', { class: 'unit-label' }, icon(prod.resource, 'ico unit-icon'), `กำลังผลิต${label}`)),
    h('div', { class: 'prod-line' }, `ตอนนี้ ${fmtRate(cur ? cur.per_hour : 0)} ต่อชม.`),
    next
      ? h('div', { class: 'prod-line' }, `เลเวล ${level + 1}: ${fmtRate(next.per_hour)} ต่อชม. (+${fmtRate(next.per_hour - (cur ? cur.per_hour : 0))})`)
      : h('div', { class: 'muted' }, 'เลเวลสูงสุดแล้ว'),
  );
  if (prod.multiplier !== 1) {
    box.append(h('div', { class: 'muted' }, `รวมตัวคูณความเร็วโลก/โบนัสแล้ว x${fmtRate(prod.multiplier)}`));
  }
  const table = h('table', { class: 'table prod-table' }, h('tr', {}, h('th', {}, 'เลเวล'), h('th', {}, 'ผลิต/ชม.'), h('th', {}, 'เพิ่มขึ้น')));
  rows.forEach((r, i) => {
    table.append(
      h(
        'tr',
        { class: r.level === level ? 'me' : '' },
        h('td', {}, String(r.level)),
        h('td', {}, fmtRate(r.per_hour)),
        h('td', {}, i === 0 ? '-' : `+${fmtRate(r.per_hour - rows[i - 1].per_hour)}`),
      ),
    );
  });
  box.append(h('details', {}, h('summary', {}, 'ตารางกำลังผลิตทุกเลเวล'), table));
  return box;
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
    h('div', { class: 'muted' }, `ช่างก่อสร้าง: ${v.build_queue.length}/${v.queue_limit}`),
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
  const queued = ctx.village.build_queue.find((q) => q.slot === slot);
  const underConstruction = queued !== undefined;
  const sheet = h('div', { class: 'bottom-sheet' });
  sheet.append(
    h('button', { class: 'btn', onclick: () => sheet.remove() }, 'ปิด'),
  );
  const queuedName = queued ? ((ctx.meta.buildings || {})[queued.type] || {}).name_th ?? queued.type : '';
  const title = view.current
    ? `${view.current.name_th ?? ''} เลเวล ${view.current.level}`
    : queued
      ? queuedName
      : `ช่องว่าง #${slot}`;
  sheet.append(h('h2', { class: 'panel-heading' }, title));
  if (queued) {
    sheet.append(
      h(
        'div',
        { class: 'slot-option build-progress' },
        h('div', { class: 'slot-option-name' }, `กำลังก่อสร้างเป็นเลเวล ${queued.target_level}`),
        h(
          'div',
          { class: 'prod-line' },
          'เสร็จในอีก ',
          h('span', { class: 'countdown', 'data-countdown': queued.finishes_at }, countdown(queued.finishes_at)),
        ),
      ),
    );
  }
  if (view.production && view.current) sheet.append(productionBlock(view.production, view.current.level));
  if (view.upgrade && !underConstruction) {
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
  for (const opt of underConstruction ? [] : view.options) {
    const btn = h(
      'button',
      { class: 'btn btn-primary', disabled: !opt.affordable },
      'สร้าง',
    );
    btn.addEventListener('click', () => doBuild(btn, ctx, slot, opt.type));
    sheet.append(
      costBlock(ctx, opt, btn, h('span', { class: 'unit-label' }, icon(opt.type, 'ico unit-icon'), opt.name_th)),
    );
  }
  if (view.current) await appendTraining(ctx, sheet, view.current);
  if (view.current && view.current.type === 'smithy') await appendSmithy(ctx, sheet);
  if (view.current && view.current.type === 'marketplace') await appendMarket(ctx, sheet);
  el.append(sheet);
}

// POST a smithy unit upgrade, toast the result, refresh; re-enable on error.
async function doUpgrade(btn, ctx, unit) {
  btn.disabled = true;
  try {
    await api.post(`/villages/${ctx.villageId}/upgrade`, { unit });
    ctx.toast('เริ่มอัปเกรดแล้ว');
    await ctx.refresh();
  } catch (err) {
    if (err instanceof ApiError) ctx.toast(err.message, true);
    btn.disabled = false;
  }
}

// Smithy section of the slot sheet: one block per upgradable unit.
async function appendSmithy(ctx, sheet) {
  let options;
  try {
    options = await api.get(`/villages/${ctx.villageId}/upgrades`);
  } catch {
    return;
  }
  sheet.append(h('h3', {}, 'อัปเกรดหน่วย'));
  if (!options.length) {
    sheet.append(h('div', { class: 'muted' }, 'ไม่มีหน่วยที่อัปเกรดได้'));
    return;
  }
  for (const opt of options) {
    const block = h('div', { class: 'slot-option' });
    block.append(h('div', { class: 'slot-option-name' }, `${opt.name_th} เลเวล ${opt.level}`));
    if (opt.target_level === null) {
      block.append(h('div', { class: 'muted' }, 'เลเวลสูงสุดแล้ว'));
      sheet.append(block);
      continue;
    }
    block.append(
      h('div', { class: 'cost-rows' }, ...costRows(ctx, opt.cost)),
      h('div', { class: 'muted' }, `เวลา ${fmtDuration(opt.time_s)}`),
    );
    for (const m of opt.missing) block.append(h('div', { class: 'negative' }, m));
    if (opt.finishes_at !== null) {
      block.append(
        h('span', { class: 'countdown', 'data-countdown': opt.finishes_at }, countdown(opt.finishes_at)),
      );
    } else {
      const btn = h('button', { class: 'btn btn-primary', disabled: !opt.affordable }, 'อัปเกรด');
      btn.addEventListener('click', () => doUpgrade(btn, ctx, opt.unit));
      block.append(btn);
    }
    sheet.append(block);
  }
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
        h('div', { class: 'slot-option-name' }, unitLabel(ctx, opt.unit)),
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
          h('span', {}, unitLabel(ctx, t.unit, `: ${t.count_done}/${t.count_total}`)),
          h('span', { class: 'countdown', 'data-countdown': t.next_at }, countdown(t.next_at)),
        ),
      )
    : [h('div', { class: 'list-row muted' }, 'ไม่มีคิวฝึก')];
  sheet.append(h('h3', {}, 'คิวฝึกทหาร'), ...rows);
}


// POST a trade shipment, toast the result, refresh; re-enable the button on error.
async function doSend(btn, ctx, toVillageId, inputs) {
  btn.disabled = true;
  try {
    await api.post(`/villages/${ctx.villageId}/trade/send`, {
      to_village_id: toVillageId,
      wood: Number(inputs.wood.value) || 0,
      stone: Number(inputs.stone.value) || 0,
      iron: Number(inputs.iron.value) || 0,
      food: Number(inputs.food.value) || 0,
    });
    ctx.toast('ส่งทรัพยากรแล้ว');
    await ctx.refresh();
  } catch (err) {
    if (err instanceof ApiError) ctx.toast(err.message, true);
    btn.disabled = false;
  }
}

// POST an NPC exchange, toast the result, refresh; re-enable the button on error.
async function doExchange(btn, ctx, give, take, amount) {
  btn.disabled = true;
  try {
    await api.post(`/villages/${ctx.villageId}/trade/exchange`, { give, take, amount });
    ctx.toast('แลกทรัพยากรแล้ว');
    await ctx.refresh();
  } catch (err) {
    if (err instanceof ApiError) ctx.toast(err.message, true);
    btn.disabled = false;
  }
}

// Marketplace section of the slot sheet: send resources and NPC exchange.
async function appendMarket(ctx, sheet) {
  let info;
  try {
    info = await api.get(`/villages/${ctx.villageId}/market`);
  } catch {
    return;
  }
  const have = (k) => Math.floor(ctx.village.resources[k] ?? 0);
  const resLabel = (k) => h('span', { class: 'unit-label' }, icon(k, 'ico unit-icon'), RES_LABELS[k]);

  // ---- send to my other villages ----
  sheet.append(h('h3', { class: 'market-head' }, icon('marketplace', 'ico unit-icon'), ' ส่งทรัพยากรไปหมู่บ้านอื่นของคุณ'));
  const others = (ctx.state.villages || []).filter((v) => v.id !== ctx.villageId);
  if (!others.length) {
    sheet.append(h('div', { class: 'slot-option muted' }, 'ยังไม่มีหมู่บ้านปลายทาง (ต้องมีหมู่บ้านมากกว่า 1 แห่ง)'));
  } else {
    const dest = h('select', {}, ...others.map((v) => h('option', { value: String(v.id) }, `${v.name} (${v.x}, ${v.y})`)));
    const inputs = {};
    const total = h('div', { class: 'market-total' });
    const updateTotal = () => {
      const sum = RES_KEYS.reduce((a, k) => a + (Number(inputs[k].value) || 0), 0);
      total.textContent = `รวม ${fmtNum(sum)} / ${fmtNum(info.capacity)} ต่อเที่ยว`;
      total.classList.toggle('negative', sum > info.capacity);
    };
    const rows = RES_KEYS.map((k) => {
      inputs[k] = h('input', { type: 'number', min: '0', value: '0' });
      inputs[k].addEventListener('input', updateTotal);
      const maxBtn = h('button', { class: 'btn small', type: 'button' }, 'สูงสุด');
      maxBtn.addEventListener('click', () => {
        const used = RES_KEYS.filter((o) => o !== k).reduce((a, o) => a + (Number(inputs[o].value) || 0), 0);
        inputs[k].value = String(Math.max(0, Math.min(have(k), info.capacity - used)));
        updateTotal();
      });
      return h('div', { class: 'market-row' }, resLabel(k), h('span', { class: 'muted' }, `มี ${fmtNum(have(k))}`), inputs[k], maxBtn);
    });
    updateTotal();
    const sendBtn = h('button', { class: 'btn btn-primary' }, 'ส่งทรัพยากร');
    sendBtn.addEventListener('click', () => doSend(sendBtn, ctx, Number(dest.value), inputs));
    sheet.append(h('div', { class: 'slot-option' }, ...rows, total, h('div', { class: 'market-row' }, h('span', {}, 'ไปที่'), dest), sendBtn));
  }

  // ---- exchange with the NPC trader ----
  sheet.append(h('h3', { class: 'market-head' }, icon('marketplace', 'ico unit-icon'), ' แลกกับพ่อค้า'));
  const giveSel = h('select', {}, ...RES_KEYS.map((k) => h('option', { value: k }, RES_LABELS[k])));
  const takeSel = h('select', {}, ...RES_KEYS.map((k) => h('option', { value: k }, RES_LABELS[k])));
  takeSel.value = 'food';
  const amount = h('input', { type: 'number', min: '1', value: '100' });
  const preview = h('div', { class: 'market-preview' });
  const updatePreview = () => {
    const n = Number(amount.value) || 0;
    clear(preview);
    preview.append(
      'ให้ ', h('b', {}, fmtNum(n)), ' ', resLabel(giveSel.value), ' → ได้ ', h('b', {}, fmtNum(Math.floor(n * (1 - info.fee)))), ' ', resLabel(takeSel.value),
    );
    if (n > have(giveSel.value)) preview.append(h('div', { class: 'negative' }, `มี${RES_LABELS[giveSel.value]}ไม่พอ (มี ${fmtNum(have(giveSel.value))})`));
    if (giveSel.value === takeSel.value) preview.append(h('div', { class: 'negative' }, 'เลือกทรัพยากรคนละชนิด'));
  };
  for (const e of [amount, giveSel, takeSel]) e.addEventListener('input', updatePreview);
  for (const e of [giveSel, takeSel]) e.addEventListener('change', updatePreview);
  const allBtn = h('button', { class: 'btn small', type: 'button' }, 'ทั้งหมด');
  allBtn.addEventListener('click', () => {
    amount.value = String(have(giveSel.value));
    updatePreview();
  });
  updatePreview();
  const exBtn = h('button', { class: 'btn btn-primary' }, 'แลก');
  exBtn.addEventListener('click', () => doExchange(exBtn, ctx, giveSel.value, takeSel.value, Number(amount.value) || 0));
  sheet.append(
    h('div', { class: 'slot-option' },
      h('div', { class: 'market-row' }, h('span', {}, 'ให้'), giveSel, amount, allBtn),
      h('div', { class: 'market-row' }, h('span', {}, 'รับ'), takeSel),
      preview,
      h('div', { class: 'muted' }, `ค่าธรรมเนียม ${Math.round(info.fee * 100)}%`),
      exBtn,
    ),
  );
}
