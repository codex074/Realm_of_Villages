// Farm lists (route #/farms): saved raid targets of the current village, sent with one click.

import { api, ApiError } from '../api.js';
import { h, clear } from '../dom.js';
import { unitsLine } from '../units.js';

// Last send result per list, kept across the re-render the refresh triggers.
const lastResults = new Map();

// Render the farm lists page into el.
export async function render(el, ctx) {
  async function draw() {
    let lists;
    try {
      lists = await api.get('/farmlists');
    } catch (err) {
      if (err instanceof ApiError) ctx.toast(err.message, true);
      return;
    }
    clear(el);
    const vname = (id) => ((ctx.state && ctx.state.villages) || []).find((v) => v.id === id)?.name ?? `#${id}`;
    el.append(
      h('h1', { class: 'village-name' }, 'รายการฟาร์ม'),
      h('p', { class: 'muted' }, 'เก็บเป้าหมายที่ปล้นประจำ แล้วส่งปล้นทุกเป้าในครั้งเดียว เพิ่มเป้าหมายได้จากหน้าแผนที่ (แตะหมู่บ้าน/โอเอซิส → "+ เพิ่มในรายการฟาร์ม")'),
    );
    const nameIn = h('input', { type: 'text', maxlength: 30, placeholder: 'ชื่อรายการ', required: true });
    el.append(
      h(
        'form',
        {
          class: 'panel market-row',
          onsubmit: async (e) => {
            e.preventDefault();
            try {
              await api.post('/farmlists', { village_id: ctx.villageId, name: nameIn.value.trim() });
              await draw();
            } catch (err) {
              if (err instanceof ApiError) ctx.toast(err.message, true);
            }
          },
        },
        h('span', {}, `สร้างรายการใหม่ให้ ${vname(ctx.villageId)}`),
        nameIn,
        h('button', { class: 'btn btn-primary small', type: 'submit' }, 'สร้าง'),
      ),
    );
    if (!lists.length) el.append(h('div', { class: 'panel muted' }, 'ยังไม่มีรายการฟาร์ม'));
    for (const l of lists) {
      const checks = new Map();
      const rows = l.entries.map((e) => {
        const cb = h('input', { type: 'checkbox', checked: true });
        checks.set(e.id, cb);
        const rm = h('button', { class: 'btn small', type: 'button' }, 'ลบ');
        rm.addEventListener('click', async () => {
          try {
            await api.del(`/farmlists/${l.id}/entries/${e.id}`);
            await draw();
          } catch (err) {
            if (err instanceof ApiError) ctx.toast(err.message, true);
          }
        });
        return h(
          'div',
          { class: 'list-row farm-row' },
          cb,
          h('a', { href: `#/map?x=${e.x}&y=${e.y}&sel=1` }, `(${e.x}, ${e.y})`),
          h('span', { class: 'movement-units' }, ...unitsLine(ctx, e.units)),
          rm,
        );
      });
      const result = h('div', { class: 'farm-result' });
      const showResult = (res) => {
        clear(result);
        const ok = res.filter((r) => r.ok).length;
        result.append(h('div', {}, `ส่งสำเร็จ ${ok} / ${res.length} เป้าหมาย`));
        for (const r of res.filter((x) => !x.ok)) {
          const e = l.entries.find((x) => x.id === r.entry_id);
          result.append(h('div', { class: 'negative' }, `(${e?.x}, ${e?.y}): ${r.error}`));
        }
      };
      if (lastResults.has(l.id)) showResult(lastResults.get(l.id));
      const sendBtn = h('button', { class: 'btn btn-primary', type: 'button', disabled: !l.entries.length }, `ส่งปล้นที่เลือก`);
      sendBtn.addEventListener('click', async () => {
        sendBtn.disabled = true;
        const ids = [...checks].filter(([, cb]) => cb.checked).map(([id]) => id);
        try {
          const res = await api.post(`/farmlists/${l.id}/send`, { entry_ids: ids });
          lastResults.set(l.id, res.results);
          showResult(res.results);
          await ctx.refresh();
        } catch (err) {
          if (err instanceof ApiError) ctx.toast(err.message, true);
        }
        sendBtn.disabled = false;
      });
      const delBtn = h('button', { class: 'btn btn-danger small', type: 'button' }, 'ลบรายการ');
      delBtn.addEventListener('click', async () => {
        if (!confirm(`ลบรายการ "${l.name}"?`)) return;
        try {
          await api.del(`/farmlists/${l.id}`);
        } catch (err) {
          if (err instanceof ApiError) ctx.toast(err.message, true);
        }
        await draw();
      });
      el.append(
        h(
          'div',
          { class: 'panel' },
          h('h2', { class: 'panel-heading' }, `${l.name} · ${vname(l.village_id)} (${l.entries.length})`),
          ...(rows.length ? rows : [h('div', { class: 'muted' }, 'ยังไม่มีเป้าหมาย')]),
          h('div', { class: 'map-actions' }, sendBtn, delBtn),
          result,
        ),
      );
    }
  }
  await draw();
}
