// Admin page (route #/admin): member management for administrators (multiplayer mode).

import { api, ApiError } from '../api.js';
import { h, clear } from '../dom.js';
import { fmtTime } from '../format.js';

let filterText = '';

function fail(ctx, err) {
  if (err instanceof ApiError) ctx.toast(err.message, true);
  else console.error(err);
}

// Render the member list into el.
export async function render(el, ctx) {
  async function draw() {
    let members;
    try {
      members = await api.get('/admin/members');
    } catch (err) {
      fail(ctx, err);
      clear(el);
      el.append(h('h1', { class: 'village-name' }, 'จัดการสมาชิก'), h('div', { class: 'panel muted' }, 'หน้านี้สำหรับผู้ดูแลระบบเท่านั้น'));
      return;
    }
    clear(el);
    const myId = ctx.me && ctx.me.account ? ctx.me.account.id : null;
    const search = h('input', { type: 'search', placeholder: 'ค้นหาชื่อผู้ใช้/ผู้เล่น', value: filterText });
    const list = h('div', { class: 'member-list' });
    el.append(
      h('h1', { class: 'village-name' }, 'จัดการสมาชิก'),
      h('div', { class: 'panel member-summary' },
        h('span', {}, `สมาชิกทั้งหมด ${members.length} คน`),
        h('span', { class: 'muted' }, `ผู้ดูแล ${members.filter((m) => m.is_admin).length} · ถูกระงับ ${members.filter((m) => m.is_disabled).length}`)),
      search,
      list,
    );
    const act = async (fn, okMsg) => {
      try {
        await fn();
        if (okMsg) ctx.toast(okMsg);
        await draw();
      } catch (err) {
        fail(ctx, err);
      }
    };
    function row(m) {
      const self = m.id === myId;
      const p = m.player;
      const badges = [
        m.is_admin ? h('span', { class: 'member-tag admin' }, 'ผู้ดูแล') : null,
        m.is_disabled ? h('span', { class: 'member-tag off' }, 'ถูกระงับ') : null,
        self ? h('span', { class: 'member-tag' }, 'คุณ') : null,
      ];
      const btn = (label, cls, fn) => h('button', { class: `btn small ${cls}`, type: 'button', onclick: fn }, label);
      const actions = h('div', { class: 'member-actions' },
        btn('รีเซ็ตรหัสผ่าน', '', () => {
          const pw = window.prompt(`ตั้งรหัสผ่านใหม่ให้ ${m.username} (อย่างน้อย 8 ตัว)`);
          if (pw) act(() => api.post(`/admin/members/${m.id}/password`, { password: pw }), 'ตั้งรหัสผ่านใหม่แล้ว');
        }),
        self ? null : btn(m.is_admin ? 'ถอดสิทธิ์ผู้ดูแล' : 'ตั้งเป็นผู้ดูแล', '', () => {
          if (confirm(`${m.is_admin ? 'ถอดสิทธิ์ผู้ดูแลของ' : 'ตั้งเป็นผู้ดูแล:'} ${m.username}?`)) act(() => api.post(`/admin/members/${m.id}/admin`, { value: !m.is_admin }), 'บันทึกแล้ว');
        }),
        self ? null : btn(m.is_disabled ? 'เปิดบัญชี' : 'ระงับบัญชี', m.is_disabled ? 'btn-primary' : 'btn-danger', () => {
          if (m.is_disabled || confirm(`ระงับบัญชี ${m.username}? จะถูกเตะออกจากระบบทันที`)) act(() => api.post(`/admin/members/${m.id}/disabled`, { value: !m.is_disabled }), 'บันทึกแล้ว');
        }),
        btn('ประวัติคำสั่ง', '', () => showAudit(m)),
      );
      return h('div', { class: 'panel member-card' + (m.is_disabled ? ' disabled' : ''), dataset: { q: `${m.username} ${p ? p.name : ''}`.toLowerCase() } },
        h('div', { class: 'member-head' }, h('b', {}, m.username), ...badges),
        h('div', { class: 'muted' }, p
          ? `${p.name} · ${(ctx.meta.tribes || {})[p.tribe]?.name_th ?? p.tribe} · ${p.villages} หมู่บ้าน · ประชากร ${p.population}${m.alliance ? ` · พันธมิตร ${m.alliance}` : ''}`
          : 'ยังไม่ได้เข้าร่วมโลก'),
        h('div', { class: 'muted' }, `สมัครเมื่อ ${fmtTime(m.created_at)} · ใช้งานล่าสุด ${m.last_seen ? fmtTime(m.last_seen) : '-'}`),
        actions,
      );
    }
    for (const m of members) list.append(row(m));
    const applyFilter = () => {
      filterText = search.value.trim().toLowerCase();
      for (const c of list.children) c.hidden = filterText !== '' && !c.dataset.q.includes(filterText);
    };
    search.addEventListener('input', applyFilter);
    applyFilter();

    async function showAudit(m) {
      let rows;
      try {
        rows = await api.get(`/admin/members/${m.id}/audit?limit=50`);
      } catch (err) {
        fail(ctx, err);
        return;
      }
      for (const old of el.querySelectorAll('.bottom-sheet')) old.remove();
      const sheet = h('div', { class: 'bottom-sheet' },
        h('button', { class: 'btn', type: 'button', onclick: () => sheet.remove() }, 'ปิด'),
        h('h2', { class: 'panel-heading' }, `ประวัติคำสั่งของ ${m.username}`),
        rows.length ? null : h('div', { class: 'muted' }, 'ยังไม่มีประวัติ'),
        ...rows.map((r) => h('div', { class: 'list-row audit-row' },
          h('span', { class: 'audit-method' }, r.method),
          h('span', { class: 'audit-path' }, r.path),
          h('span', { class: r.status >= 400 ? 'negative' : 'muted' }, String(r.status)),
          h('span', { class: 'muted' }, fmtTime(r.created_at)))),
      );
      el.append(sheet);
    }
  }
  await draw();
}
