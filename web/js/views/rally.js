// Rally view: send-troops form with live preview, reinforcements and movements.

import { api, ApiError } from '../api.js';
import { h, clear } from '../dom.js';
import { countdown } from '../clock.js';
import { fmtNum, fmtDuration, fmtTime } from '../format.js';

const MISSION_LABELS = {
  attack: 'โจมตี',
  raid: 'ปล้น',
  scout: 'สอดแนม',
  reinforce: 'ส่งทัพเสริม',
  settle: 'ตั้งหมู่บ้านใหม่',
  return: 'กลับบ้าน',
};
const PREVIEW_DEBOUNCE_MS = 300;

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

// Reinforcements-here panel with a recall button per group.
function reinforcementsPanel(ctx) {
  const v = ctx.village;
  const body = v.reinforcements_here.length
    ? v.reinforcements_here.map((r) => {
        const units = Object.entries(r.units || {})
          .map(([unit, count]) => `${(ctx.meta.units || {})[unit]?.name_th ?? unit} x${count}`)
          .join(', ');
        const recallBtn = h('button', { class: 'btn small' }, 'เรียกกลับ');
        recallBtn.addEventListener('click', async () => {
          try {
            for (const id of r.troop_ids) await api.post(`/troops/${id}/recall`);
            ctx.toast('เรียกทัพกลับแล้ว');
            await ctx.refresh();
          } catch (err) {
            if (err instanceof ApiError) ctx.toast(err.message, true);
          }
        });
        return h(
          'div',
          { class: 'list-row' },
          h('span', {}, `${r.from_village.name}: ${units}`),
          recallBtn,
        );
      })
    : [h('div', { class: 'list-row muted' }, 'ไม่มีทัพเสริม')];
  return h(
    'div',
    { class: 'panel' },
    h('h2', { class: 'panel-heading' }, 'ทัพเสริมในหมู่บ้านนี้'),
    ...body,
  );
}

// Render the rally page into el.
export async function render(el, ctx, params) {
  clear(el);
  const v = ctx.village;
  const vid = params.vid;
  const troops = Object.entries(v.troops_home || {}).filter(([, count]) => count > 0);

  const unitInputs = new Map();
  const unitRows = h('div', { class: 'unit-rows' });
  if (troops.length === 0) {
    unitRows.append(h('div', { class: 'list-row muted' }, 'ไม่มีทหารให้ส่ง'));
  } else {
    for (const [unit, count] of troops) {
      const input = h('input', {
        type: 'number',
        min: '0',
        max: String(count),
        value: '0',
      });
      unitInputs.set(unit, input);
      const maxBtn = h('button', { class: 'btn small' }, 'ทั้งหมด');
      maxBtn.addEventListener('click', () => {
        input.value = String(count);
        schedulePreview();
      });
      input.addEventListener('input', schedulePreview);
      unitRows.append(
        h(
          'div',
          { class: 'unit-row' },
          h('span', {}, `${(ctx.meta.units || {})[unit]?.name_th ?? unit} (มี ${count})`),
          input,
          maxBtn,
        ),
      );
    }
  }

  const mission = h('select', {},
    h('option', { value: 'attack' }, 'โจมตี'),
    h('option', { value: 'raid' }, 'ปล้น'),
    h('option', { value: 'scout' }, 'สอดแนม'),
    h('option', { value: 'reinforce' }, 'ส่งทัพเสริม'),
    h('option', { value: 'settle' }, 'ตั้งหมู่บ้านใหม่'),
  );
  const wantedMission = params.query.get('mission');
  if (wantedMission && [...mission.options].some((o) => o.value === wantedMission)) {
    mission.value = wantedMission;
  }
  const xInput = h('input', {
    type: 'number',
    value: params.query.get('x') ?? '',
  });
  const yInput = h('input', {
    type: 'number',
    value: params.query.get('y') ?? '',
  });

  const catapultSelect = h('select', {}, h('option', { value: '' }, 'สุ่ม'));
  for (const [key, bd] of Object.entries(ctx.meta.buildings || {})) {
    if (bd.kind === 'center') catapultSelect.append(h('option', { value: key }, bd.name_th));
  }
  const catapultRow = h('div', { class: 'form-row' },
    h('label', { class: 'form-label' }, 'เป้าเครื่องยิงหิน'),
    catapultSelect,
  );
  catapultRow.hidden = true;

  const result = h('div', { class: 'panel' });

  const sendBtn = h('button', { class: 'btn btn-primary', disabled: true }, 'ส่ง');

  let previewTimer = null;
  let lastPreviewErrors = null;

  // Collect the current form body (or null when it is not sendable).
  function currentBody() {
    const toX = parseInt(xInput.value, 10);
    const toY = parseInt(yInput.value, 10);
    const units = {};
    for (const [unit, input] of unitInputs) {
      const count = parseInt(input.value, 10) || 0;
      if (count > 0) units[unit] = count;
    }
    if (Object.keys(units).length === 0) return null;
    if (!Number.isInteger(toX) || !Number.isInteger(toY)) return null;
    const hasCatapult = (units.catapult ?? 0) > 0;
    const showCatapult = hasCatapult && mission.value === 'attack';
    return {
      to_x: toX,
      to_y: toY,
      mission: mission.value,
      units,
      catapult_target: showCatapult ? catapultSelect.value || null : null,
    };
  }

  function updateSendState() {
    const body = currentBody();
    sendBtn.disabled = !body || (lastPreviewErrors != null && lastPreviewErrors.length > 0);
  }

  function showResult(preview) {
    clear(result);
    result.append(h('div', { class: 'list-row' }, `เวลาถึง: ${fmtTime(preview.arrive_at)}`));
    result.append(h('div', { class: 'list-row' }, `ใช้เวลา: ${fmtDuration(preview.travel_time_s)}`));
    result.append(h('div', { class: 'list-row' }, `ระยะทาง: ${preview.distance.toFixed(1)}`));
    result.append(h('div', { class: 'list-row' }, `บรรทุกได้: ${fmtNum(preview.carry)}`));
    for (const e of preview.errors || []) result.append(h('div', { class: 'list-row negative' }, e));
    lastPreviewErrors = preview.errors || [];
    updateSendState();
  }

  function clearResult() {
    clear(result);
    lastPreviewErrors = null;
    updateSendState();
  }

  async function doPreview() {
    const body = currentBody();
    if (!body) {
      clearResult();
      return;
    }
    try {
      const preview = await api.post(`/villages/${vid}/send/preview`, body);
      showResult(preview);
    } catch (err) {
      if (err instanceof ApiError) ctx.toast(err.message, true);
    }
  }

  function schedulePreview() {
    catapultRow.hidden = !((currentBody()?.units?.catapult ?? 0) > 0 && mission.value === 'attack');
    clearTimeout(previewTimer);
    previewTimer = setTimeout(doPreview, PREVIEW_DEBOUNCE_MS);
  }

  [mission, xInput, yInput, catapultSelect].forEach((elm) =>
    elm.addEventListener('change', schedulePreview),
  );

  sendBtn.addEventListener('click', async () => {
    const body = currentBody();
    if (!body) return;
    try {
      await api.post(`/villages/${vid}/send`, body);
      ctx.toast('ส่งทัพแล้ว');
      await ctx.refresh();
    } catch (err) {
      if (err instanceof ApiError) ctx.toast(err.message, true);
    }
  });

  el.append(
    h('h1', { class: 'village-name' }, 'ส่งทัพ'),
    h('div', { class: 'panel rally-form' },
      unitRows,
      h('div', { class: 'form-row' }, mission),
      h('div', { class: 'form-row form-row-inline' },
        h('label', { class: 'form-label' }, 'x'),
        xInput,
        h('label', { class: 'form-label' }, 'y'),
        yInput,
      ),
      catapultRow,
      result,
      sendBtn,
    ),
    reinforcementsPanel(ctx),
    movementsPanel(ctx),
  );

  // Initial preview if the form is already filled.
  if (currentBody()) doPreview();

  return () => {
    clearTimeout(previewTimer);
  };
}
