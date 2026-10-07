// Center view: slots 19-40 grid (BUILD.md section 10).

import { h, clear, icon } from '../dom.js';
import { queuePanel, openSlotPanel } from './slotpanel.js';

const HEADING = 'ใจกลางหมู่บ้าน';
const EMPTY = 'ว่าง';

// One center slot cell (slots 19..40).
function centerCell(el, ctx, b) {
  const classes = ['slot'];
  if (b.type) {
    const meta = (ctx.meta.buildings || {})[b.type] || {};
    if (meta.produces) classes.push(meta.produces);
  } else {
    classes.push('empty');
  }
  if (ctx.village.build_queue.some((q) => q.slot === b.slot)) classes.push('building');
  const cell = h(
    'div',
    { class: classes.join(' ') },
    b.type ? icon(b.type, 'ico slot-icon') : null,
    h('div', { class: 'slot-label' }, b.name_th ?? EMPTY),
    b.type ? h('div', { class: 'slot-level' }, String(b.level)) : null,
  );
  cell.addEventListener('click', () => openSlotPanel(el, ctx, b.slot));
  return cell;
}

// Render the center page into el.
export async function render(el, ctx) {
  clear(el);
  const grid = h('div', { class: 'center-grid' });
  for (const b of ctx.village.buildings) {
    if (b.slot >= 19 && b.slot <= 40) grid.append(centerCell(el, ctx, b));
  }
  el.append(
    h('h1', { class: 'village-name' }, HEADING),
    queuePanel(ctx),
    h('div', { class: 'panel' }, grid),
  );
}
