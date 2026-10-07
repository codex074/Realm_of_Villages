// Ranking view: leaderboard table with the player's row highlighted (BUILD.md section 10).

import { api, ApiError } from '../api.js';
import { h, clear } from '../dom.js';
import { fmtNum } from '../format.js';

// Render the ranking table into el.
export async function render(el, ctx) {
  let rows;
  try {
    rows = await api.get('/ranking');
  } catch (err) {
    if (err instanceof ApiError) ctx.toast(err.message, true);
    return;
  }
  clear(el);
  el.append(h('h1', { class: 'village-name' }, 'อันดับ'));
  const table = h(
    'table',
    { class: 'table' },
    h(
      'tr',
      {},
      h('th', {}, 'อันดับ'),
      h('th', {}, 'ชื่อ'),
      h('th', {}, 'เผ่า'),
      h('th', {}, 'หมู่บ้าน'),
      h('th', {}, 'ประชากร'),
    ),
  );
  for (const row of rows) {
    const nameCell = h('td', {}, row.name);
    if (row.is_bot) nameCell.append(h('span', { class: 'tag' }, 'bot'));
    table.append(
      h(
        'tr',
        { class: row.player_id === ctx.state?.player?.id ? 'me' : '' },
        h('td', {}, String(row.rank)),
        nameCell,
        h('td', {}, (ctx.meta.tribes || {})[row.tribe]?.name_th ?? row.tribe),
        h('td', {}, fmtNum(row.villages)),
        h('td', {}, fmtNum(row.population)),
      ),
    );
  }
  el.append(table);
}
