# STATUS

อัปเดตล่าสุด: 2026-10-06

| Task | สถานะ | ส่ง Qwen (ครั้ง) | หมายเหตุ |
| --- | --- | --- | --- |
| T00 | merged | 0 | Claude ทำเอง |
| T01 | merged | 0 | Claude ทำเอง |
| T02 | merged | 1 | Qwen ผ่านรอบแรก ไม่ต้องแก้ |
| T03a | merged | 1 | models+session; Claude แก้ server_default JSONB 2 จุด |
| T03b | merged | 1 | ผ่านรอบแรก; ตรวจ migration เทียบ models ด้วย alembic compare_metadata ไม่มี diff |
| T04a | merged | 1 | errors/events/notify/views; Claude แก้ docstring 1 บรรทัด |
| T04b | merged | 1 | Claude แก้ข้อความไทยที่ Qwen พิมพ์เพี้ยน 2 จุด |
| T04c | merged | 1 | logic ถูกต้องตั้งแต่รอบแรก; Claude แก้สตริงไทย 4 ตัวที่มีวรรณยุกต์ซ้ำ (น้ี, แล้้ว ฯลฯ) |
| T04d | merged | 1 | ผ่านรอบแรก ไม่ต้องแก้; ฟังก์ชันเดิมไม่ถูกแก้ |
| T05 | merged | 1 | ผ่านรอบแรก ไม่ต้องแก้; ทดสอบ engine จริงกับ Postgres แล้ว (build เสร็จเอง, SIGTERM ปิดสวย) |
| T06 | todo | 0 | |
| T07 | todo | 0 | |
| T08 | todo | 0 | |

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
- Qwen ชอบพิมพ์วรรณยุกต์/สระซ้ำในสตริงไทย (เช่น "น้ี", "แล้้ว") ตรวจด้วยสคริปต์ regex หลังทุก task (ดู scripts/check_thai.py)
- ข้อความไทยที่ Qwen เขียนมักมีคำเพี้ยน/พิมพ์ผิด: ต้องอ่านทุกสตริงไทยตอนรีวิว และใส่ใน notes ให้ใช้ถ้อยคำสั้นๆ ง่ายๆ
- T02: ไม่พบข้อผิดพลาดซ้ำ ตัวเลข test คำนวณมือถูกต้อง
