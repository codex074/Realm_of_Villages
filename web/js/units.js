// Unit labels with the hand-drawn unit icon (web/img/icons.svg).

import { h, icon } from './dom.js';

// Thai unit name for a key, falling back to the key.
export function unitName(ctx, key) {
  return (ctx.meta.units || {})[key]?.name_th ?? key;
}

// <span class="unit-label"><svg icon/> name[suffix]</span>
export function unitLabel(ctx, key, suffix = '') {
  return h('span', { class: 'unit-label' }, icon(key, 'ico unit-icon'), `${unitName(ctx, key)}${suffix}`);
}

// A wrapping list of unit labels with counts ("name x5"); returns an array of nodes.
export function unitsLine(ctx, units) {
  return Object.entries(units || {}).map(([unit, count]) => unitLabel(ctx, unit, ` x${count}`));
}
