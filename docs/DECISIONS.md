# DECISIONS

| วันที่ | เรื่อง | ตัดสินใจว่า | เหตุผล |
| --- | --- | --- | --- |
| 2026-10-06 | วิธีเรียก Qwen | ใช้ `claude --settings ~/.claude-9arm.json` ผ่าน `scripts/delegate_9arm.py` แทน `scripts/delegate.py` | ผู้ใช้สั่งให้ใช้ claude-9arm; ต้องรันด้วย env สะอาด |
| 2026-10-06 | T04 แบ่งเป็น 4 งาน | T04a errors/events/notify/views, T04b worlds, T04c villages คำสั่ง, T04d villages view | context ของ Qwen เล็ก |
| 2026-10-06 | T05 handler STARVATION_CHECK | ลงทะเบียนเป็น no-op (log อย่างเดียว) ไม่ raise NotImplementedError | after_change จะ schedule event นี้แล้วตั้งแต่ Phase 0; ถ้า raise จะเกิด event failed ขัดด่าน G1; T14 เติมของจริง |
| 2026-10-06 | T05 การจัดการ handler พัง | `process_next` ครอบ handler ด้วย savepoint (`begin_nested`) แล้วตั้ง status=failed ใน transaction เดียวกัน | ได้ผลเท่า "rollback แล้วเปิด transaction ใหม่" และทดสอบกับ fixture `s` ได้ |
| 2026-10-07 | T07 แบ่งเป็น a/b/c และเพิ่ม `web/js/dom.js` | a: index/css/api/clock/ws/format, b: app.js + dom.js + newgame.js, c: village.js + center.js | context Qwen เล็ก; dom.js (ตัวสร้าง DOM ปลอดภัย ไม่ใช้ innerHTML) ใช้ร่วมกันทุก view |
| 2026-10-07 | สัญญาของ view ในหน้าเว็บ | view = `export async function render(el, ctx, params)` คืน cleanup ได้; `ctx` = `{meta, state, village, villageId, toast, refresh, navigate}`; countdown ใช้ `<span data-countdown="ISO">` ที่ app.js อัปเดตทุกวินาทีและ refetch เมื่อถึง 0 | ให้ T07b/T07c เขียนแยกกันได้ |
| 2026-10-07 | T16 แบ่งเป็น a/b และเพิ่ม `realm/bot/action.py` | a: action.py (Action + execute), memory.py, modules.py (+BotContext); b: brain.py (think), worker.py, cli, compose | กัน circular import (modules ต้องใช้ Action, brain ต้องใช้ modules); brain.py re-export Action ตามสเปก |
