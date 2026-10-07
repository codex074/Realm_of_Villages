# STATUS

อัปเดตล่าสุด: 2026-10-07

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
| T13b | merged | 1 | ผ่านรอบแรก; Claude แก้ลูปหักทหารตาย (sloppy แต่ผลถูก); Qwen แก้ test_worker เพราะ stub MOVEMENT_ARRIVE เปลี่ยน (wrapper หยุดด้วย exit 4 ครั้งเดียว ตรวจแล้วชอบธรรม) |
| T14 | merged | 1 | ผ่านรอบแรก ไม่ต้องแก้; ข้อความไทยถูกครบ; ป้องกัน starvation event วนไม่รู้จบแล้ว |
| T15a | merged | 1 | ผ่านรอบแรก ไม่ต้องแก้ (277 tests) |
| T15b | merged | 1 | Claude แก้คำไทย 3 จุด (มีย, สุม, เวลาถิง); โครงสร้างถูก |
| T15c | merged | 1 | ผ่านรอบแรก ข้อความไทยถูกครบ; ทดสอบในเบราว์เซอร์จริง: ปล้นสำเร็จ (loot 500x4), รายงานสองฝ่าย, badge, แผงฝึกทหาร ทำงานถูก |
| T16a | merged | 1 | Claude แก้บั๊กจริง: modules.raid อ่าน village.protection_until (ไม่มีคอลัมน์ ต้องเป็นของ Player) แต่ test ตั้ง attribute เองจึงผ่านทั้งที่ผิด |
| T16b | merged | 1 | ผ่านรอบแรก ไม่ต้องแก้ (wrapper หยุด exit 4 เพราะ Qwen เพิ่ม tests/bot/__init__.py กันชื่อ test_worker ซ้ำ ชอบธรรม; 320 tests ผ่าน) |
| T17 | merged | 1 | Qwen เขียน simulator แต่ session ค้างเกิน 30 นาที (test ช้า ~114s/รอบ); Claude แก้เอง: brain ข้ามโมดูลสร้างเมื่อคิวเต็ม + cap ความล้มเหลวต่อชนิด (เร็วขึ้น 3 เท่า), บั๊ก KeyError spearman ใน modules.training ที่ simulator เจอ (678 ครั้ง), เรียง query ตาม slot/id ให้ deterministic, test ปรับเป็น speed 1 (7s) |
| T20a | merged | 1 | logic ถูก; Qwen พิมพ์ข้อความไทยเดิมใน military.py เพี้ยนไปด้วย (บ่าน/น้ี/ตั้้ง ~15 จุด) Claude แก้ทั้งหมดแล้ว |
| T20b | merged | 0 | Claude ทำเอง (แก้เล็ก 3 ไฟล์เว็บ); เพิ่ม config combat.conquest_loyalty สำหรับ T21 |
| T21 | merged | 1 | ผ่านรอบแรก ไม่ต้องแก้; ข้อความไทยถูกครบเพราะให้ Qwen Edit จุดเล็ก + ไฟล์ใหม่ (conquest.py) แทนเขียนไฟล์ใหญ่ซ้ำ |
| T22 | merged | 2 | a=Claude (table+migration+config), b,c=Qwen รอบแรกผ่านไม่ต้องแก้ (Edit จุดเล็ก → ข้อความไทยไม่เพี้ยน); ตัวเลข balance upgrades เป็นค่าที่ Claude ตั้งเอง รอผู้ใช้ทบทวน |
| T23 | merged | 2 | a,b=Qwen รอบแรกผ่าน; Claude แก้ compute_rates ให้ใช้ query เดียวแทน 4 query (hot path), c=Claude ทำเอง (map panel); ตัวเลขสัตว์/โบนัสเป็นค่าที่ Claude ตั้งเอง รอทบทวน |
| T25 | merged | 3 | a รอบแรกผ่าน; b สองรอบ; Claude แก้ไทยเพี้ยน (ส่่ง, ได้ร่ับ) ; ทดสอบ test ล้มสุ่ม 1 ครั้งเกิดจากผมรัน pytest ซ้อนกับ wrapper ของ Qwen บน DB เดียวกัน (อย่าทำ) |
| T26a | merged | 1 | Qwen ทำครบทุกข้อแต่ session ชน context 131k ตอนท้าย (โจทย์ใหญ่เกิน → แบ่ง task ให้เล็กลง หรือใช้ test_cmd แคบ); Claude แก้ 2 test เดิมที่ต้องเปลี่ยน (monument option, จำนวน event) |
| T26b | merged | 1 | bots ruins_race+monument ผ่านรอบแรก (wrapper หยุด exit 4 เพราะแก้ bots.yaml/BUILD.md ตามที่สั่ง); T26c web (แผนที่/อันดับ/รายงานซาก) Claude ทำเอง |
| T08 | merged | 1 | Claude แก้ healthcheck (ขาด "CMD"); build+up จริงผ่าน: migrate, เว็บ/API/WS ผ่าน Caddy :8080, engine ทำงาน, backup.sh ใช้ได้ |
| T24 | merged | 2 | ผู้ใช้ตัดสินให้ผ่าน: เกณฑ์ sim ตีความเป็นรอบ 60 วัน@1x (DECISIONS_phase3.md) |
| T30a | merged | 1 | Phase 3: accounts/sessions/auth API/get_player ตาม session; Claude แก้ไทยเพี้ยน 4 ข้อความ + แก้บั๊ก wt.sh (ชื่อ DB ตัวพิมพ์ใหญ่ทำให้ test ถูก skip เงียบ ต้องดู "skipped" ในผล pytest ทุกครั้ง) |
| T30b | merged | 1 | join_world, admin เฉพาะ admin, pause ปิดเมื่อมนุษย์ >1; ผ่านรอบแรก ไม่ต้องแก้ |
| T31a | merged | 1 | alliances service; logic ถูก Claude แก้ไทยเพี้ยน 5 ข้อความ |
| T31b | delegated | 1 | alliance API |

สถานะที่ใช้: todo · delegated · in-review · merged · blocked · claude-fallback

## งานค้างที่ผู้ใช้สั่งไว้
- UI สไตล์ยุคกลางแฟนตาซีวาดมือ: ทำรอบแรกแล้ว (2026-10-07): ไอคอน SVG 43 ตัว (web/img/icons.svg สร้างจาก scripts/build_icons.py), ธีม web/css/theme.css, แผนที่วาดภูมิประเทศด้วยไอคอน, หน้า #/help "วิธีเล่น"; ยังเหลือขัดเกลา: ไอคอนขวาน/หัวม้า, หน้ารายงาน/จุดรวมพล/ตลาดใส่ไอคอนหน่วย, แอนิเมชันเล็กน้อย
- แจ้งเตือนผ่าน ./scripts/notify.sh ทุก task ที่ merge (CLAUDE.md 5.8)
- T24: เกณฑ์ sim 20 วัน@1x ยังไม่ผ่าน (รอผล speed 3 แล้วเสนอปรับ balance ให้ผู้ใช้ตัดสิน)

## ด่าน
- [ ] G1
- [ ] G2  (เกณฑ์ T17 ผ่านแล้วอัตโนมัติ: 5 วัน/30 bot ใน 1:51, failed 0, ประชากรโตทุกบุคลิก, ปล้น 99 ครั้ง; ที่เหลือต้องทดสอบมือ)

## การตั้งค่าที่ต่างจาก CLAUDE.md
- Qwen เรียกผ่าน `claude --settings ~/.claude-9arm.json ...` (skill qwen-agent) ไม่ใช่ `scripts/delegate.py` (OpenAI endpoint)
- ตัวห่อ: `scripts/delegate_9arm.py` (Claude เขียน) — `scripts/delegate.py` เดิมยังเก็บไว้แต่ไม่ใช้, ruff ข้ามไฟล์นี้

## บทเรียนจาก Qwen (ใส่ใน notes ของ task ถัดไป)
- ต้องเรียก Qwen ด้วย env สะอาด (wrapper ทำให้แล้ว) ไม่งั้น "Not logged in"
- JSONB server_default ต้องเป็น text("'{}'::jsonb") ไม่ใช่สตริง "{}::jsonb" (Qwen พลาดใน T03a)
- การจำลองจริงเจอบั๊กที่ unit test ไม่เจอ (KeyError fallback, query ไม่มี ORDER BY ทำให้ผลไม่ deterministic): รัน `realm simulate` ทุกครั้งที่แก้ bot
- ระวัง: test ของ Qwen อาจ "ตั้ง attribute ที่ไม่มีใน model" แล้วผ่านทั้งที่ของจริงพัง (เจอใน T16a) -> ใส่ใน notes ให้ test ตั้งค่าผ่านคอลัมน์จริงเท่านั้น และรีวิวว่าฟิลด์ที่โค้ดอ่านมีใน models.py จริง
- ระวัง: Qwen พิมพ์คำไทยผิดเหมือนกันทั้งในโค้ดและ test ทำให้ test ผ่านทั้งที่ผิด -> เพิ่ม KNOWN_BAD ใน check_thai.py และอ่านสตริงไทยทุกครั้ง
- Qwen ลืม "CMD" ใน healthcheck.test ของ compose; test_cmd ที่ใช้ python ต้องเรียกผ่าน `uv run` (python3 ระบบเป็น 3.9 ไม่มี yaml)
- ห้าม commit/รัน pytest บน DB เดียวกันระหว่างที่ Qwen กำลังรันอยู่ (ใช้ worktree + DB แยก: scripts/wt.sh)
- เร่งความเร็ว (2026-10-07): โหลด tiles ด้วย COPY (create_world 0.8s -> 0.05s, ชุด test 201s -> 62s)
- วิธีกันข้อความไทยเพี้ยน: ให้ Qwen สร้างไฟล์ใหม่ และใช้ Edit จุดเล็กกับไฟล์เดิม ห้าม Write ทับไฟล์ที่มีสตริงไทย (ใช้ได้ผลใน T21)
- Qwen ใส่ "บ่าน" แทน "บ้าน", "เปลี่ี่ยน", "ท่ี" ซ้ำๆ: ใส่ในโจทย์ให้คัดลอกสตริงไทยตามที่ระบุเป๊ะ และรัน scripts/check_thai.py + อ่านทวนทุกครั้ง
- Qwen สลับ/พิมพ์ตัวอักษรไทยผิดได้ (เช่น "อับดับ" แทน "อันดับ") ที่ regex จับไม่ได้ ต้องอ่านสตริงไทยทุกตัวเอง
- Qwen ชอบพิมพ์วรรณยุกต์/สระซ้ำในสตริงไทย (เช่น "น้ี", "แล้้ว") ตรวจด้วยสคริปต์ regex หลังทุก task (ดู scripts/check_thai.py)
- ข้อความไทยที่ Qwen เขียนมักมีคำเพี้ยน/พิมพ์ผิด: ต้องอ่านทุกสตริงไทยตอนรีวิว และใส่ใน notes ให้ใช้ถ้อยคำสั้นๆ ง่ายๆ
- T02: ไม่พบข้อผิดพลาดซ้ำ ตัวเลข test คำนวณมือถูกต้อง
