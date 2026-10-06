# STATUS

อัปเดตล่าสุด: 2026-10-06

| Task | สถานะ | ส่ง Qwen (ครั้ง) | หมายเหตุ |
| --- | --- | --- | --- |
| T00 | merged | 0 | Claude ทำเอง |
| T01 | merged | 0 | Claude ทำเอง |
| T02 | merged | 1 | Qwen ผ่านรอบแรก ไม่ต้องแก้ |
| T03a | merged | 1 | models+session; Claude แก้ server_default JSONB 2 จุด |
| T03b | todo | 0 | alembic, migration, conftest, test, cli migrate |

สถานะที่ใช้: todo · delegated · in-review · merged · blocked · claude-fallback

## ด่าน
- [ ] G1
- [ ] G2

## การตั้งค่าที่ต่างจาก CLAUDE.md
- Qwen เรียกผ่าน `claude --settings ~/.claude-9arm.json ...` (skill qwen-agent) ไม่ใช่ `scripts/delegate.py` (OpenAI endpoint)
- ตัวห่อ: `scripts/delegate_9arm.py` (Claude เขียน) — `scripts/delegate.py` เดิมยังเก็บไว้แต่ไม่ใช้, ruff ข้ามไฟล์นี้

## บทเรียนจาก Qwen (ใส่ใน notes ของ task ถัดไป)
- ต้องเรียก Qwen ด้วย env สะอาด (wrapper ทำให้แล้ว) ไม่งั้น "Not logged in"
- JSONB server_default ต้องเป็น text("'{}'::jsonb") ไม่ใช่สตริง "{}::jsonb" (Qwen พลาดใน T03a)
- T02: ไม่พบข้อผิดพลาดซ้ำ ตัวเลข test คำนวณมือถูกต้อง
