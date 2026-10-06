// New world form (route #/new).

import { api, ApiError } from '../api.js';
import { h, clear } from '../dom.js';

const DEFAULT_NAME = 'ผู้เล่น';
const DEFAULT_BOTS = 30;

// Render the new-world form into el.
export async function render(el, ctx) {
  clear(el);
  const tribes = Object.entries(ctx.meta.tribes || {});
  const speeds = (ctx.meta.speeds || [1, 3, 5, 10]).map(Number);
  const selected = { tribe: tribes[0] ? tribes[0][0] : '' };

  const nameInput = h('input', {
    type: 'text',
    required: true,
    value: DEFAULT_NAME,
    maxlength: 32,
  });
  const botInput = h('input', {
    type: 'number',
    min: '0',
    max: '60',
    value: String(DEFAULT_BOTS),
  });
  const seedInput = h('input', { type: 'number' });
  const speedSelect = h(
    'select',
    {},
    speeds.map((s) => h('option', { value: String(s) }, `x${s}`)),
  );
  const submitBtn = h('button', { class: 'btn btn-primary', type: 'submit' }, 'เริ่มเกม');

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
          const seed = seedInput.value.trim() === '' ? null : Number(seedInput.value);
          await api.post('/admin/new-world', {
            player_name: nameInput.value.trim(),
            tribe: selected.tribe,
            speed: Number(speedSelect.value),
            bot_count: Number(botInput.value) || 0,
            seed,
          });
          ctx.toast('สร้างโลกแล้ว');
          window.location.hash = '#/';
          await ctx.refresh();
        } catch (err) {
          if (err instanceof ApiError) ctx.toast(err.message, true);
          submitBtn.disabled = false;
        }
      },
    },
    h('div', { class: 'form-row' }, h('label', { class: 'form-label' }, 'ชื่อผู้เล่น'), nameInput),
    h('div', { class: 'form-row' }, h('label', { class: 'form-label' }, 'เผ่า'), tribeCards),
    h(
      'div',
      { class: 'form-row form-row-inline' },
      h('label', { class: 'form-label' }, 'ความเร็ว'),
      speedSelect,
    ),
    h(
      'div',
      { class: 'form-row form-row-inline' },
      h('label', { class: 'form-label' }, 'จำนวน bot'),
      botInput,
    ),
    h(
      'div',
      { class: 'form-row form-row-inline' },
      h('label', { class: 'form-label' }, 'seed'),
      seedInput,
    ),
    h('div', { class: 'form-row' }, submitBtn),
  );

  el.append(
    h('div', { class: 'newgame' },
      h('h1', { class: 'newgame-title' }, 'Realm of Villages'),
      h('p', { class: 'newgame-subtitle' }, 'สร้างโลกและเริ่มเกม'),
      form,
    ),
  );
}
