// Join the running world as a new player (route #/join), multiplayer mode.

import { api, ApiError } from '../api.js';
import { h, clear } from '../dom.js';

// Render the join form into el.
export async function render(el, ctx) {
  clear(el);
  const tribes = Object.entries(ctx.meta.tribes || {});
  const selected = { tribe: tribes[0] ? tribes[0][0] : '' };
  const defaultName = ctx.me && ctx.me.account ? ctx.me.account.username : '';

  const nameInput = h('input', { type: 'text', required: true, value: defaultName, maxlength: 20 });
  const submitBtn = h('button', { class: 'btn btn-primary', type: 'submit' }, 'เข้าร่วมโลก');

  const tribeCards = h('div', { class: 'tribe-cards' });
  for (const [key, t] of tribes) {
    const radio = h('input', {
      type: 'radio',
      name: 'tribe',
      value: key,
      checked: key === selected.tribe,
    });
    const card = h(
      'label',
      { class: 'tribe-card' + (key === selected.tribe ? ' selected' : '') },
      radio,
      h('div', { class: 'tribe-name' }, t.name_th),
      h('div', { class: 'tribe-desc' }, t.description_th),
    );
    radio.addEventListener('change', () => {
      selected.tribe = key;
      for (const c of tribeCards.children) c.classList.remove('selected');
      card.classList.add('selected');
    });
    tribeCards.append(card);
  }

  const form = h(
    'form',
    {
      class: 'newgame-form',
      onsubmit: async (e) => {
        e.preventDefault();
        submitBtn.disabled = true;
        try {
          await api.post('/world/join', { name: nameInput.value.trim(), tribe: selected.tribe });
          ctx.toast('เข้าร่วมโลกแล้ว');
          window.location.hash = '#/';
          await ctx.start();
        } catch (err) {
          if (err instanceof ApiError) ctx.toast(err.message, true);
          submitBtn.disabled = false;
        }
      },
    },
    h('div', { class: 'form-row' }, h('label', { class: 'form-label' }, 'ชื่อผู้เล่น'), nameInput),
    h('div', { class: 'form-row' }, h('label', { class: 'form-label' }, 'เผ่า'), tribeCards),
    h('div', { class: 'form-row' }, submitBtn),
  );

  el.append(
    h(
      'div',
      { class: 'newgame' },
      h('h1', { class: 'newgame-title' }, 'Realm of Villages'),
      h('p', { class: 'newgame-subtitle' }, 'เลือกชื่อและเผ่า แล้วเริ่มหมู่บ้านของคุณ'),
      form,
    ),
  );
}
