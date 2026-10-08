# โหมดหลายผู้เล่น (Phase 3)

## เปิดใช้งาน
1. ใส่ใน `.env` แล้ว `docker compose up -d --build`:
   ```
   REALM_AUTH_REQUIRED=true
   ```
   (ถ้าเข้าผ่าน HTTPS ให้เติม `REALM_COOKIE_SECURE=true` ด้วย)
2. เปิดเว็บ → สมัครบัญชีแรก = ผู้ดูแล (admin) → สร้างโลกจากหน้า "สร้างโลก"
3. คนอื่นสมัครบัญชีเอง แล้วเลือกชื่อ/เผ่าเพื่อ "เข้าร่วมโลก" (เกิดที่ขอบรัศมีที่มีหมู่บ้านอยู่ ได้เขตคุ้มครองเริ่มต้นเท่าผู้เล่นแรก)
4. ไม่ตั้ง `REALM_AUTH_REQUIRED` = เล่นคนเดียวเหมือนเดิม (ไม่ต้อง login)

## กติกาที่เปลี่ยนเมื่อมีหลายคน
- ปุ่มหยุด/เล่นต่อ/สร้างโลกใหม่ เฉพาะ admin; หยุดเกมไม่ได้เมื่อมีผู้เล่นมนุษย์มากกว่า 1 คน
- พันธมิตร: ตั้ง/เชิญ/ตอบรับ/ออก/ไล่ (หัวหน้าเท่านั้นเชิญ-ไล่) สูงสุด 20 คน มีแชทภายในพันธมิตร
- โจมตี/ปล้น/สอดแนมพวกเดียวกันไม่ได้ (ส่งกำลังเสริมได้)
- WebSocket ส่งเหตุการณ์ให้เฉพาะเจ้าของที่เกี่ยวข้อง และต้อง login ก่อนเชื่อมต่อ
- จำกัดคำสั่งที่เปลี่ยนสถานะ 60 ครั้ง/10 วินาที ต่อบัญชี (หน้า login จำกัดต่อ IP) และกันคำสั่งเดิมซ้ำภายใน 1 วินาที
- ทุกคำสั่งที่เปลี่ยนสถานะถูกบันทึกในตาราง `audit_log` (บัญชี, ผู้เล่น, method, path, status, เวลา) ไว้ตรวจสอบการโกง

## หลัง Caddy / reverse proxy
ตัวจำกัดอัตราอ่าน IP จาก header `X-Forwarded-For` (Caddy ใส่ให้เอง) จึงห้ามเปิดพอร์ต api (8000) ออกอินเทอร์เน็ตตรง ๆ ให้เข้าผ่าน Caddy เท่านั้น

## ตรวจ audit log
```bash
docker compose exec db psql -U realm -d realm -c "select a.username, l.method, l.path, l.status, l.created_at from audit_log l left join accounts a on a.id=l.account_id order by l.id desc limit 50"
```

## สำรองข้อมูล
`./scripts/backup.sh` สำรองทั้งฐานข้อมูล รวมบัญชี (รหัสผ่านเก็บเป็น scrypt hash) และพันธมิตร

## Cloudflare Tunnel (เข้าจากอินเทอร์เน็ตโดยไม่เปิดพอร์ต)
1. สร้าง tunnel ใน Cloudflare Zero Trust แล้วตั้ง Public Hostname (เช่น `rov.example.com`) ชี้ไป `http://caddy:80`
2. ใส่ token ใน `cloudflared.env` (ไฟล์นี้ไม่เข้า git): `TUNNEL_TOKEN=<token>`
3. ใน `.env` ตั้ง `REALM_AUTH_REQUIRED=true` และ `REALM_COOKIE_SECURE=true`
4. `docker compose --profile tunnel up -d --build`
ตัวจำกัดอัตราอ่าน IP จริงจาก header `CF-Connecting-IP` และ Caddy เชื่อ header จาก proxy ในเครือข่ายภายใน
