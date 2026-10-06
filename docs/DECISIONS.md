# DECISIONS

| วันที่ | เรื่อง | ตัดสินใจว่า | เหตุผล |
| --- | --- | --- | --- |
| 2026-10-06 | วิธีเรียก Qwen | ใช้ `claude --settings ~/.claude-9arm.json` ผ่าน `scripts/delegate_9arm.py` แทน `scripts/delegate.py` | ผู้ใช้สั่งให้ใช้ claude-9arm; ต้องรันด้วย env สะอาด |
| 2026-10-06 | T04 แบ่งเป็น 4 งาน | T04a errors/events/notify/views, T04b worlds, T04c villages คำสั่ง, T04d villages view | context ของ Qwen เล็ก |
| 2026-10-06 | T05 handler STARVATION_CHECK | ลงทะเบียนเป็น no-op (log อย่างเดียว) ไม่ raise NotImplementedError | after_change จะ schedule event นี้แล้วตั้งแต่ Phase 0; ถ้า raise จะเกิด event failed ขัดด่าน G1; T14 เติมของจริง |
| 2026-10-06 | T05 การจัดการ handler พัง | `process_next` ครอบ handler ด้วย savepoint (`begin_nested`) แล้วตั้ง status=failed ใน transaction เดียวกัน | ได้ผลเท่า "rollback แล้วเปิด transaction ใหม่" และทดสอบกับ fixture `s` ได้ |
