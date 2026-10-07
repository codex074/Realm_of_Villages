// Reports list and detail views (BUILD.md section 10).

import { api, ApiError } from '../api.js';
import { h, clear } from '../dom.js';
import { fmtNum, fmtTime } from '../format.js';

const RES_KEYS = ['wood', 'stone', 'iron', 'food'];
const RES_LABELS = { wood: 'ไม้', stone: 'หิน', iron: 'เหล็ก', food: 'อาหาร' };

// Thai name for a unit key, falling back to the key itself.
function unitName(ctx, key) {
  return (ctx.meta.units || {})[key]?.name_th ?? key;
}

// Units table with columns: unit / count / losses.
function unitsTable(ctx, units, losses) {
  const rows = Object.entries(units || {}).map(([unit, count]) =>
    h(
      'tr',
      {},
      h('td', {}, unitName(ctx, unit)),
      h('td', {}, fmtNum(count)),
      h('td', {}, fmtNum(losses?.[unit] ?? 0)),
    ),
  );
  return h(
    'table',
    { class: 'table' },
    h('tr', {}, h('th', {}, 'หน่วย'), h('th', {}, 'จำนวน'), h('th', {}, 'ตาย')),
    ...rows,
  );
}

// Battle report: result banner, powers, attacker/defender tables, loot, wall.
function battleDetail(ctx, data) {
  const el = h(
    'div',
    { class: 'panel' },
    data.attacker_won
      ? h('div', { class: 'banner' }, 'ฝ่ายโจมตีชนะ')
      : h('div', { class: 'banner negative' }, 'ฝ่ายโจมตีแพ้'),
    h('div', {}, `พลังโจมตี ${fmtNum(data.attack_power ?? 0)}`),
    h('div', {}, `พลังป้องกัน ${fmtNum(data.defense_power ?? 0)}`),
    h('h3', {}, 'ผู้โจมตี'),
    h('div', {}, `${data.attacker?.player ?? ''} (${data.attacker?.village?.name ?? ''})`),
    unitsTable(ctx, data.attacker?.units, data.attacker?.losses),
  );
  const defenders = data.defenders || [];
  for (const d of defenders) {
    el.append(h('h3', {}, `ผู้ป้องกัน ${d.player ?? ''}`), unitsTable(ctx, d.units, d.losses));
  }
  if (defenders.length === 0) el.append(h('div', { class: 'muted' }, 'ไม่มีผู้ป้องกัน'));
  if (data.loot) {
    el.append(
      h('h3', {}, 'ของที่ปล้นได้'),
      ...RES_KEYS.map((k) => h('div', {}, `${RES_LABELS[k]} ${fmtNum(data.loot[k] ?? 0)}`)),
    );
  }
  if (data.wall && data.wall.before !== data.wall.after) {
    el.append(h('div', {}, `กำแพงเลเวล ${data.wall.before} -> ${data.wall.after}`));
  }
  return el;
}

// Scout report: success flag, resources, troops, wall level, buildings.
function scoutDetail(ctx, data) {
  const el = h(
    'div',
    { class: 'panel' },
    h('div', { class: 'banner' }, data.success ? 'สอดแนมสำเร็จ' : 'สอดแนมไม่สำเร็จ'),
  );
  if (!data.success) return el;
  el.append(
    h('h3', {}, 'ทรัพยากร'),
    ...RES_KEYS.map((k) => h('div', {}, `${RES_LABELS[k]} ${fmtNum(data.resources?.[k] ?? 0)}`)),
  );
  const entries = Object.entries(data.troops || {});
  el.append(
    h('h3', {}, 'ทหารในหมู่บ้าน'),
    entries.length
      ? entries.map(([u, c]) => h('div', {}, `${unitName(ctx, u)} x${c}`))
      : h('div', { class: 'muted' }, 'ไม่มีทหาร'),
  );
  if (data.wall != null) el.append(h('div', {}, `กำแพงเลเวล ${data.wall}`));
  const buildings = data.buildings || {};
  if (Object.keys(buildings).length > 0) {
    el.append(
      h('h3', {}, 'อาคาร'),
      ...Object.entries(buildings).map(([k, level]) =>
        h('div', {}, `${(ctx.meta.buildings || {})[k]?.name_th ?? k} เลเวล ${level}`),
      ),
    );
  }
  return el;
}

// Reinforce report: one line listing the moved units.
function reinforceDetail(ctx, data) {
  const units = Object.entries(data.units || {})
    .map(([u, c]) => `${unitName(ctx, u)} x${c}`)
    .join(', ');
  return h('div', { class: 'panel' }, h('div', {}, units));
}

// Info report: starvation losses and/or round-end winner and top list.
function infoDetail(ctx, data) {
  const el = h('div', { class: 'panel' });
  if (data.killed) {
    el.append(
      h('h3', {}, 'ทหารที่ตาย'),
      ...Object.entries(data.killed).map(([u, c]) => h('div', {}, `${unitName(ctx, u)} x${c}`)),
    );
  }
  if (data.ruins) {
    el.append(
      h('h3', {}, 'ซากโบราณ'),
      ...data.ruins.map((r) => h('div', {}, `(${r.x}, ${r.y})`)),
    );
  }
  if (data.winner) {
    if (data.reason === 'monument') el.append(h('div', {}, 'ชนะด้วยอนุสาวรีย์'));
    el.append(
      h('div', {}, `ผู้ชนะ ${data.winner.name}`),
      h('div', {}, `อันดับของคุณ ${data.your_rank}`),
      ...(data.top || []).map((row) =>
        h('div', {}, `${row.rank}. ${row.name} (${fmtNum(row.population)})`),
      ),
    );
  }
  return el;
}

// Render the report list into el.
async function renderList(el, ctx) {
  const reports = await api.get('/reports');
  clear(el);
  el.append(h('h1', { class: 'village-name' }, 'รายงาน'));
  if (!reports.length) {
    el.append(h('div', { class: 'muted' }, 'ไม่มีรายงาน'));
    return;
  }
  for (const r of reports) {
    const row = h(
      'div',
      { class: 'list-row clickable' },
      h('span', { class: r.is_read ? '' : 'unread' }, r.title),
      h('span', { class: 'muted' }, fmtTime(r.created_at)),
    );
    row.addEventListener('click', () => ctx.navigate('#/reports/' + r.id));
    el.append(row);
  }
}

// Render one report detail into el; fires 'reports-read' once after the fetch.
async function renderDetail(el, ctx, id) {
  const r = await api.get('/reports/' + id);
  clear(el);
  window.dispatchEvent(new CustomEvent('reports-read'));
  const back = h('button', { class: 'btn' }, 'กลับไปรายการ');
  back.addEventListener('click', () => ctx.navigate('#/reports'));
  el.append(
    back,
    h('h1', { class: 'village-name' }, r.title),
    h('div', { class: 'muted' }, fmtTime(r.created_at)),
  );
  const d = r.data || {};
  if (r.kind === 'battle') el.append(battleDetail(ctx, d));
  else if (r.kind === 'scout') el.append(scoutDetail(ctx, d));
  else if (r.kind === 'reinforce') el.append(reinforceDetail(ctx, d));
  else if (r.kind === 'info') el.append(infoDetail(ctx, d));
}

// Render the reports view (list or detail) into el.
export async function render(el, ctx, params) {
  try {
    if (params.id == null) await renderList(el, ctx);
    else await renderDetail(el, ctx, params.id);
  } catch (err) {
    if (err instanceof ApiError) ctx.toast(err.message, true);
  }
}
