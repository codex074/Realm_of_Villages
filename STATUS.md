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
| T06a | merged | 1 | ผ่านรอบแรก ไม่ต้องแก้ (ครั้งแรกส่งไม่สำเร็จเพราะสคริปต์ผมเอง ไม่นับ) |
| T06b | merged | 1 | ผ่านรอบแรก ไม่ต้องแก้; ทดสอบ E2E จริง (API+engine+WS) ผ่าน |
| T07a | merged | 1 | JS ถูกต้อง; Claude แก้คำไทยผิด 2 จุด (แผนท่ี, อับดับ) |
| T07b | merged | 1 | Claude แก้ 2 จุดใน app.js (interval ซ้ำ, villageId ตอนไม่มี id); ทดสอบในเบราว์เซอร์จริงผ่าน |
| T07c | merged | 1 | Claude แก้คำไทยผิด ~8 จุด + bug container ของ slot panel + null guard ใน app.js; ทดสอบในเบราว์เซอร์จริงผ่าน (desktop+mobile) |
| T10a | merged | 1 | worldgen ถูกต้อง ผ่านรอบแรก |
| T10b | merged | 1 | Claude แก้ "บ่าน" ใน worlds.py+test (Qwen พิมพ์ผิดทั้งโค้ดและ test พร้อมกัน!) และเปลี่ยนชื่อ bot ให้สุ่มจริง |
| T12a | merged | 1 | Claude แก้ข้อความไทย 5 ข้อความที่ Qwen พิมพ์เพี้ยนแม้ให้คัดลอก |
| T12b | merged | 1 | ผ่านรอบแรก ตัวเลขรบตรวจอิสระตรงกัน (38/50, 27/36) |
| T11 | merged | 1 | ผ่านรอบแรก ไม่ต้องแก้ (ข้อความไทยที่ให้คัดลอก ถูกต้องครบ) |
| T13a | merged | 1 | Claude แก้คำไทย "น้ี"x2 "ท่ี"x1 ที่ Qwen พิมพ์ผิดแม้ให้คัดลอก; logic ถูกต้อง |
| T13b | todo | 0 | military: resolve_arrival รบ/สอดแนม/เสริม + reports |
| T08 | merged | 1 | Claude แก้ healthcheck (ขาด "CMD"); build+up จริงผ่าน: migrate, เว็บ/API/WS ผ่าน Caddy :8080, engine ทำงาน, backup.sh ใช้ได้ |

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
- ระวัง: Qwen พิมพ์คำไทยผิดเหมือนกันทั้งในโค้ดและ test ทำให้ test ผ่านทั้งที่ผิด -> เพิ่ม KNOWN_BAD ใน check_thai.py และอ่านสตริงไทยทุกครั้ง
- Qwen ลืม "CMD" ใน healthcheck.test ของ compose; test_cmd ที่ใช้ python ต้องเรียกผ่าน `uv run` (python3 ระบบเป็น 3.9 ไม่มี yaml)
- Qwen ใส่ "บ่าน" แทน "บ้าน", "เปลี่ี่ยน", "ท่ี" ซ้ำๆ: ใส่ในโจทย์ให้คัดลอกสตริงไทยตามที่ระบุเป๊ะ และรัน scripts/check_thai.py + อ่านทวนทุกครั้ง
- Qwen สลับ/พิมพ์ตัวอักษรไทยผิดได้ (เช่น "อับดับ" แทน "อันดับ") ที่ regex จับไม่ได้ ต้องอ่านสตริงไทยทุกตัวเอง
- Qwen ชอบพิมพ์วรรณยุกต์/สระซ้ำในสตริงไทย (เช่น "น้ี", "แล้้ว") ตรวจด้วยสคริปต์ regex หลังทุก task (ดู scripts/check_thai.py)
- ข้อความไทยที่ Qwen เขียนมักมีคำเพี้ยน/พิมพ์ผิด: ต้องอ่านทุกสตริงไทยตอนรีวิว และใส่ใน notes ให้ใช้ถ้อยคำสั้นๆ ง่ายๆ
- T02: ไม่พบข้อผิดพลาดซ้ำ ตัวเลข test คำนวณมือถูกต้อง
