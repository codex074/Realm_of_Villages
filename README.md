# Realm of Villages

เกมวางแผนสร้างหมู่บ้านแบบเรียลไทม์บนเว็บ ผู้เล่น 1 คน แข่งกับ bot ~30 ตัว
รันบน home server ด้วย Docker Compose

## ติดตั้ง

ต้องมี Docker ที่มี Compose v2

```bash
cp .env.example .env
docker compose up -d
```

## เริ่มเกม

สร้างโลกใหม่:

```bash
docker compose exec api realm new-world --speed 1 --name ผู้เล่น --tribe stonehold --bots 30 --seed 42
```

(หมายเหตุ: bot จะมาใน Phase 1 ขณะนี้สร้าง 0 ตัว)

แล้วเข้าเว็บที่ `http://<server-ip>:8080`

### เข้าจากนอกบ้าน

ใช้ Tailscale: ติดตั้ง Tailscale ทั้งบน server และทั้งบนโทรศัพท์
แล้วเข้าที่ `http://<tailscale-ip>:8080`

**อย่า** เปิด port 8080 ออกไปอินเทอร์เน็ต เพราะเกมไม่มีระบบล็อกอิน

### หยุดเกม / เล่นต่อ

```bash
docker compose exec api realm pause
docker compose exec api realm resume
```

## รัน test

```bash
docker compose -f docker-compose.test.yml up -d
uv sync
uv run pytest -q
uv run ruff check .
```

## สำรองข้อมูล

```bash
./scripts/backup.sh
```

ตั้ง crontab รันทุกวัน 03:00:

```
0 3 * * * cd /path/to/Real\ of\ Villages && ./scripts/backup.sh
```

## กู้คืนข้อมูล

```bash
docker compose stop engine api
gunzip -c backups/<file>.sql.gz | docker compose exec -T db psql -U realm realm
docker compose start engine api
```

(ต้องกู้คืนลง database ที่ว่าง)

## โครงสร้างโปรเจกต์

```
realm/            โค้ดเกม (core, db, services, api, engine, bot, cli)
web/              ไฟล์เว็บที่ Caddy เซิร์ฟ
docker/           Dockerfile และ Caddyfile
scripts/          สคริปต์ช่วยเหลือ (backup.sh)
tests/            test
```
