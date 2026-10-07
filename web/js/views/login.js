// Login / register form (route #/login), used in multiplayer mode.

import { api, ApiError } from '../api.js';
import { h, clear } from '../dom.js';

// Render the login form into el.
export async function render(el, ctx) {
  clear(el);
  let registering = false;

  const userInput = h('input', {
    type: 'text',
    required: true,
    maxlength: 20,
    autocomplete: 'username',
  });
  const passInput = h('input', {
    type: 'password',
    required: true,
    autocomplete: 'current-password',
  });
  const submitBtn = h('button', { class: 'btn btn-primary', type: 'submit' }, 'เข้าสู่ระบบ');
  const switchBtn = h('button', { class: 'btn', type: 'button' }, 'สมัครบัญชีใหม่');
  const hint = h('p', { class: 'newgame-subtitle' }, 'เข้าสู่ระบบเพื่อเล่นต่อ');

  function applyMode() {
    submitBtn.textContent = registering ? 'สมัครและเข้าสู่ระบบ' : 'เข้าสู่ระบบ';
    switchBtn.textContent = registering ? 'มีบัญชีแล้ว' : 'สมัครบัญชีใหม่';
    hint.textContent = registering
      ? 'ชื่อผู้ใช้ 3-20 ตัว (a-z, 0-9, _ -) รหัสผ่านอย่างน้อย 8 ตัว'
      : 'เข้าสู่ระบบเพื่อเล่นต่อ';
    passInput.autocomplete = registering ? 'new-password' : 'current-password';
  }
  switchBtn.addEventListener('click', () => {
    registering = !registering;
    applyMode();
  });

  const form = h(
    'form',
    {
      class: 'newgame-form',
      onsubmit: async (e) => {
        e.preventDefault();
        submitBtn.disabled = true;
        try {
          await api.post(registering ? '/auth/register' : '/auth/login', {
            username: userInput.value.trim(),
            password: passInput.value,
          });
          window.location.hash = '#/';
          await ctx.start();
        } catch (err) {
          if (err instanceof ApiError) ctx.toast(err.message, true);
          submitBtn.disabled = false;
        }
      },
    },
    h('div', { class: 'form-row' }, h('label', { class: 'form-label' }, 'ชื่อผู้ใช้'), userInput),
    h('div', { class: 'form-row' }, h('label', { class: 'form-label' }, 'รหัสผ่าน'), passInput),
    h('div', { class: 'form-row' }, submitBtn),
    h('div', { class: 'form-row' }, switchBtn),
  );

  el.append(
    h('div', { class: 'newgame' }, h('h1', { class: 'newgame-title' }, 'Realm of Villages'), hint, form),
  );
  applyMode();
  userInput.focus();
}
