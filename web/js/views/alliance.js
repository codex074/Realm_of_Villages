// Alliance page (route #/alliance): create, invites, members, kick, leave and chat.

import { api, ApiError } from '../api.js';
import { h, clear } from '../dom.js';

const CHAT_POLL_MS = 5000;

function fail(ctx, err) {
  if (err instanceof ApiError) ctx.toast(err.message, true);
  else console.error(err);
}

// Render the alliance page into el; returns a cleanup that stops the chat poller.
export async function render(el, ctx) {
  let timer = null;
  let stopped = false;

  async function draw() {
    const [alliance, invites] = await Promise.all([api.get('/alliance'), api.get('/alliance/invites')]);
    if (stopped) return;
    clear(el);
    if (timer) {
      clearInterval(timer);
      timer = null;
    }
    el.append(h('h1', { class: 'village-name' }, 'พันธมิตร'));
    if (!alliance) {
      drawInvites(invites);
      drawCreate();
    } else {
      drawAlliance(alliance);
    }
  }

  async function act(fn, okMessage) {
    try {
      await fn();
      if (okMessage) ctx.toast(okMessage);
      await draw();
    } catch (err) {
      fail(ctx, err);
    }
  }

  function drawInvites(invites) {
    if (invites.length === 0) return;
    const panel = h('div', { class: 'panel' }, h('div', { class: 'form-label' }, 'คำเชิญ'));
    for (const inv of invites) {
      panel.append(
        h(
          'div',
          { class: 'alliance-row' },
          h('span', {}, inv.alliance_name),
          h(
            'button',
            {
              class: 'btn btn-primary',
              type: 'button',
              onclick: () =>
                act(() => api.post(`/alliance/invites/${inv.alliance_id}/accept`), 'เข้าร่วมพันธมิตรแล้ว'),
            },
            'ตอบรับ',
          ),
          h(
            'button',
            {
              class: 'btn',
              type: 'button',
              onclick: () => act(() => api.post(`/alliance/invites/${inv.alliance_id}/decline`)),
            },
            'ปฏิเสธ',
          ),
        ),
      );
    }
    el.append(panel);
  }

  function drawCreate() {
    const nameInput = h('input', { type: 'text', required: true, maxlength: 20, placeholder: 'ชื่อพันธมิตร' });
    el.append(
      h(
        'form',
        {
          class: 'panel newgame-form',
          onsubmit: (e) => {
            e.preventDefault();
            act(() => api.post('/alliance', { name: nameInput.value.trim() }), 'ตั้งพันธมิตรแล้ว');
          },
        },
        h('div', { class: 'form-label' }, 'ตั้งพันธมิตรใหม่'),
        h('div', { class: 'form-row' }, nameInput),
        h('div', { class: 'form-row' }, h('button', { class: 'btn btn-primary', type: 'submit' }, 'ตั้งพันธมิตร')),
      ),
    );
  }

  function drawAlliance(alliance) {
    const myId = ctx.state && ctx.state.player ? ctx.state.player.id : null;
    const isLeader = alliance.leader_player_id === myId;

    const members = h('div', { class: 'panel' }, h('div', { class: 'form-label' }, alliance.name));
    for (const m of alliance.members) {
      members.append(
        h(
          'div',
          { class: 'alliance-row' },
          h('span', {}, m.name + (m.role === 'leader' ? ' (หัวหน้า)' : '')),
          h('span', { class: 'muted' }, ctx.meta.tribes?.[m.tribe]?.name_th ?? m.tribe),
          isLeader && m.player_id !== myId
            ? h(
                'button',
                {
                  class: 'btn btn-danger',
                  type: 'button',
                  onclick: () => {
                    if (confirm(`ไล่ ${m.name} ออกจากพันธมิตร?`)) {
                      act(() => api.post('/alliance/kick', { player_id: m.player_id }));
                    }
                  },
                },
                'ไล่ออก',
              )
            : null,
        ),
      );
    }
    el.append(members);

    if (isLeader) {
      const nameInput = h('input', { type: 'text', required: true, maxlength: 20, placeholder: 'ชื่อผู้เล่นที่จะเชิญ' });
      const panel = h(
        'form',
        {
          class: 'panel newgame-form',
          onsubmit: (e) => {
            e.preventDefault();
            act(() => api.post('/alliance/invite', { player_name: nameInput.value.trim() }), 'ส่งคำเชิญแล้ว');
          },
        },
        h('div', { class: 'form-label' }, 'เชิญผู้เล่น'),
        h('div', { class: 'form-row' }, nameInput),
        h('div', { class: 'form-row' }, h('button', { class: 'btn btn-primary', type: 'submit' }, 'เชิญ')),
      );
      if (alliance.invites.length > 0) {
        panel.append(h('div', { class: 'muted' }, 'รอตอบรับ: ' + alliance.invites.map((i) => i.name).join(', ')));
      }
      el.append(panel);
    }

    drawChat();

    el.append(
      h(
        'div',
        { class: 'panel' },
        h(
          'button',
          {
            class: 'btn btn-danger',
            type: 'button',
            onclick: () => {
              if (confirm('ออกจากพันธมิตร?')) act(() => api.post('/alliance/leave'), 'ออกจากพันธมิตรแล้ว');
            },
          },
          'ออกจากพันธมิตร',
        ),
      ),
    );
  }

  function drawChat() {
    let lastId = 0;
    const log = h('div', { class: 'chat-log' });
    const input = h('input', { type: 'text', maxlength: 300, placeholder: 'พิมพ์ข้อความ', required: true });

    function append(messages) {
      for (const m of messages) {
        if (m.id <= lastId) continue;
        lastId = m.id;
        log.append(h('div', { class: 'chat-msg' }, h('b', {}, m.name + ': '), m.text));
      }
      if (messages.length > 0) log.scrollTop = log.scrollHeight;
    }

    async function poll() {
      try {
        append(await api.get(`/alliance/messages?after=${lastId}`));
      } catch {
        // Keep polling; transient errors are ignored.
      }
    }

    el.append(
      h(
        'form',
        {
          class: 'panel newgame-form',
          onsubmit: async (e) => {
            e.preventDefault();
            const text = input.value.trim();
            if (!text) return;
            try {
              append([await api.post('/alliance/messages', { text })]);
              input.value = '';
            } catch (err) {
              fail(ctx, err);
            }
          },
        },
        h('div', { class: 'form-label' }, 'แชทพันธมิตร'),
        log,
        h('div', { class: 'form-row' }, input),
        h('div', { class: 'form-row' }, h('button', { class: 'btn btn-primary', type: 'submit' }, 'ส่ง')),
      ),
    );
    poll();
    timer = setInterval(poll, CHAT_POLL_MS);
  }

  await draw();
  return () => {
    stopped = true;
    if (timer) clearInterval(timer);
  };
}
