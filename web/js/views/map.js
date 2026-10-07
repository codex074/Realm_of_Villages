// Map view: canvas 15x15 grid, pan by drag, arrow/coord controls, tile info panel.

import { api, ApiError } from '../api.js';
import { h, clear } from '../dom.js';

const CELL = 40;
const SIZE = 15;
const RADIUS = 7;
const TILE_COLORS = {
  valley: '#cfe3b4',
  oasis: '#7fbf6a',
  mountain: '#a08c74',
  lake: '#7fb2d9',
  ruin: '#9b7fc4',
};
const TILE_LABELS = {
  valley: 'หุบเขา',
  oasis: 'โอเอซิส',
  mountain: 'ภูเขา',
  lake: 'ทะเลสาบ',
  ruin: 'ซากโบราณ',
};
const CLICK_MAX_PX = 5;
const ARROW_STEP = 3;

// Center coordinates from query or the current village.
function centerFrom(params, ctx) {
  const qx = parseInt(params.query.get('x'), 10);
  const qy = parseInt(params.query.get('y'), 10);
  if (Number.isInteger(qx) && Number.isInteger(qy)) return { x: qx, y: qy };
  const v = ctx.village && ctx.village.village;
  return { x: v.x, y: v.y };
}

// Draw the whole map onto the canvas 2D context.
function drawMap(canvas, map, center) {
  const ctx2 = canvas.getContext('2d');
  ctx2.clearRect(0, 0, canvas.width, canvas.height);
  for (const t of map.tiles) {
    const col = t.x - (center.x - RADIUS);
    const row = t.y - (center.y - RADIUS);
    if (col < 0 || col >= SIZE || row < 0 || row >= SIZE) continue;
    const px = col * CELL;
    const py = row * CELL;
    ctx2.fillStyle = TILE_COLORS[t.kind] || TILE_COLORS.valley;
    ctx2.fillRect(px, py, CELL, CELL);
    ctx2.strokeStyle = 'rgba(0,0,0,0.15)';
    ctx2.lineWidth = 1;
    ctx2.strokeRect(px + 0.5, py + 0.5, CELL - 1, CELL - 1);
    if (t.village) {
      ctx2.beginPath();
      ctx2.arc(px + CELL / 2, py + CELL / 2, CELL * 0.28, 0, Math.PI * 2);
      ctx2.fillStyle = t.village.is_mine ? '#1f5fbf' : '#c0392b';
      ctx2.fill();
    }
  }
  // Darker outline on the center cell.
  const ccx = (center.x - (center.x - RADIUS)) * CELL;
  const ccy = (center.y - (center.y - RADIUS)) * CELL;
  ctx2.strokeStyle = '#333';
  ctx2.lineWidth = 3;
  ctx2.strokeRect(ccx + 1.5, ccy + 1.5, CELL - 3, CELL - 3);
}

// Fill the info panel for a selected tile.
function fillInfo(panel, ctx, tile, center) {
  clear(panel);
  panel.append(h('div', { class: 'list-row' }, `พิกัด (${tile.x}, ${tile.y})`));
  panel.append(h('div', { class: 'list-row' }, TILE_LABELS[tile.kind] ?? tile.kind));
  if (tile.oasis && tile.kind === 'ruin') {
    panel.append(h('div', { class: 'list-row' }, `ผู้พิทักษ์: ${tile.oasis.animals}`));
    if (tile.oasis.owner_village_id != null) {
      panel.append(
        h('div', { class: 'list-row' }, tile.oasis.owned_by_me ? 'ของคุณ' : 'มีเจ้าของ'),
      );
    }
  } else if (tile.oasis) {
    const resLabels = { wood: 'ไม้', stone: 'หิน', iron: 'เหล็ก', food: 'อาหาร' };
    panel.append(
      h('div', { class: 'list-row' }, `โบนัสผลิต: ${resLabels[tile.oasis_type] ?? tile.oasis_type}`),
    );
    panel.append(h('div', { class: 'list-row' }, `สัตว์ป่า: ${tile.oasis.animals}`));
    if (tile.oasis.owner_village_id != null) {
      panel.append(
        h('div', { class: 'list-row' }, tile.oasis.owned_by_me ? 'ของคุณ' : 'มีเจ้าของ'),
      );
    }
  }
  const v = tile.village;
  if (v) {
    const tribeName = (ctx.meta.tribes || {})[v.tribe]?.name_th ?? v.tribe;
    panel.append(h('div', { class: 'list-row' }, v.name));
    panel.append(h('div', { class: 'list-row' }, `ผู้เล่น: ${v.player_name}`));
    panel.append(h('div', { class: 'list-row' }, `เผ่า: ${tribeName}`));
    panel.append(h('div', { class: 'list-row' }, `ประชากร: ${v.population}`));
    panel.append(h('div', { class: 'list-row' }, v.is_mine ? 'ของคุณ' : 'bot'));
  } else {
    panel.append(h('div', { class: 'list-row muted' }, 'ไม่มีหมู่บ้าน'));
  }
  const isOwn = v != null && v.is_mine;
  if (!isOwn) {
    const btn = h('button', { class: 'btn btn-primary' }, 'ส่งทัพ');
    btn.addEventListener('click', () =>
      ctx.navigate(`#/rally/${ctx.villageId}?x=${tile.x}&y=${tile.y}`),
    );
    panel.append(btn);
  }
  if (!v && tile.kind === 'valley') {
    const settleBtn = h('button', { class: 'btn' }, 'ตั้งหมู่บ้านที่นี่');
    settleBtn.addEventListener('click', () =>
      ctx.navigate(`#/rally/${ctx.villageId}?x=${tile.x}&y=${tile.y}&mission=settle`),
    );
    panel.append(settleBtn);
  }
}

// Render the map page into el.
export async function render(el, ctx, params) {
  clear(el);
  const center = centerFrom(params, ctx);
  const map = await api.get(`/map?cx=${center.x}&cy=${center.y}&r=${RADIUS}`);

  const canvas = h('canvas', {
    width: String(SIZE * CELL),
    height: String(SIZE * CELL),
    class: 'map-canvas',
  });
  drawMap(canvas, map, center);

  const info = h('div', { class: 'panel' });

  // Controls row: arrows + coordinate inputs + go button.
  const step = (dx, dy) =>
    ctx.navigate(`#/map?x=${center.x + dx}&y=${center.y + dy}`);
  const xInput = h('input', { type: 'number', value: String(center.x) });
  const yInput = h('input', { type: 'number', value: String(center.y) });
  const goBtn = h('button', { class: 'btn' }, 'ไป');
  goBtn.addEventListener('click', () => {
    const nx = parseInt(xInput.value, 10);
    const ny = parseInt(yInput.value, 10);
    if (!Number.isInteger(nx) || !Number.isInteger(ny)) return;
    ctx.navigate(`#/map?x=${nx}&y=${ny}`);
  });
  const controls = h(
    'div',
    { class: 'map-controls' },
    h('button', { class: 'btn small', onclick: () => step(0, -1) }, '↑'),
    h('div', { class: 'map-arrows' },
      h('button', { class: 'btn small', onclick: () => step(-1, 0) }, '←'),
      h('button', { class: 'btn small', onclick: () => step(1, 0) }, '→'),
    ),
    h('button', { class: 'btn small', onclick: () => step(0, 1) }, '↓'),
    h('div', { class: 'map-coords' },
      xInput,
      yInput,
      goBtn,
    ),
  );

  // Drag-to-pan + click-to-select via pointer events.
  let dragging = false;
  let startX = 0;
  let startY = 0;
  let moved = 0;
  const cellPx = () => {
    const rect = canvas.getBoundingClientRect();
    return rect.width / SIZE;
  };
  const onDown = (e) => {
    dragging = true;
    moved = 0;
    startX = e.clientX;
    startY = e.clientY;
    canvas.setPointerCapture(e.pointerId);
  };
  const onMove = (e) => {
    if (!dragging) return;
    moved = Math.max(moved, Math.hypot(e.clientX - startX, e.clientY - startY));
  };
  const onUp = (e) => {
    if (!dragging) return;
    dragging = false;
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    if (moved < CLICK_MAX_PX) {
      // Treat as a click: select the tile under the pointer.
      const rect = canvas.getBoundingClientRect();
      const col = Math.floor((e.clientX - rect.left) / cellPx());
      const row = Math.floor((e.clientY - rect.top) / cellPx());
      const tile = map.tiles.find((t) => t.x === center.x - RADIUS + col && t.y === center.y - RADIUS + row);
      if (tile) fillInfo(info, ctx, tile, center);
      return;
    }
    // Treat as a pan: convert drag distance into whole tiles.
    const dxTiles = Math.round(-dx / cellPx());
    const dyTiles = Math.round(-dy / cellPx());
    if (dxTiles !== 0 || dyTiles !== 0) {
      ctx.navigate(`#/map?x=${center.x + dxTiles}&y=${center.y + dyTiles}`);
    }
  };
  canvas.addEventListener('pointerdown', onDown);
  canvas.addEventListener('pointermove', onMove);
  canvas.addEventListener('pointerup', onUp);

  el.append(
    h('h1', { class: 'village-name' }, 'แผนที่'),
    controls,
    h('div', { class: 'map-wrap' }, canvas),
    info,
  );

  return () => {
    canvas.removeEventListener('pointerdown', onDown);
    canvas.removeEventListener('pointermove', onMove);
    canvas.removeEventListener('pointerup', onUp);
  };
}
