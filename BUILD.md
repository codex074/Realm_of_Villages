# Realm of Villages — BUILD.md

คู่มือสร้างเกมสำหรับทีม sub-agent อ่านคู่กับ Game Design Doc
เวอร์ชันเอกสาร: 1.0 · 2026-10-06 · Stack: Python 3.12

---

## 0. วิธีใช้เอกสารนี้

### 0.1 สำหรับผู้คุมงาน (คุณ)

1. แจกงานทีละ Task ID (หัวข้อ 11) ให้ agent หนึ่งตัวต่อหนึ่ง task
2. ส่งให้ agent: **BUILD.md ทั้งไฟล์** + **ไฟล์ในช่อง "อ่าน" ของ task** + prompt ในหัวข้อ 12
3. ห้ามส่งทั้ง repo ให้ agent ส่งเฉพาะไฟล์ที่ task ระบุ (ประหยัด context)
4. รับผลแล้วรัน `uv run pytest` และ `uv run ruff check` เอง ก่อน merge
5. ทำตามลำดับ dependency ในหัวข้อ 11.1 งานที่ไม่ขึ้นต่อกันส่งให้หลาย agent ทำพร้อมกันได้
6. ถ้า agent ขอเปลี่ยน contract (ไฟล์ `docs/CHANGES_REQUESTED.md`) ให้คุณตัดสินใจ แล้วแก้ BUILD.md ก่อนแจกงานถัดไป

งบ context: เอกสารนี้ราว 30–40k tokens เหลือที่ให้ agent อ่านโค้ดและเขียนงานอีกมากในหน้าต่าง 128k
ถ้าใช้โมเดลขนาดเล็ก ให้ตัด task ใหญ่ออกเป็นครึ่งตามหัวข้อย่อยที่ระบุไว้ใน task นั้น

### 0.2 กฎเหล็กสำหรับ agent ทุกตัว

1. แก้หรือสร้างเฉพาะไฟล์ในช่อง **"สร้าง/แก้"** ของ task ตัวเองเท่านั้น
2. **ห้ามเปลี่ยน contract** ในหัวข้อ 4–9 (ชื่อฟังก์ชัน, signature, ชื่อคอลัมน์, รูปแบบ JSON, ชื่อ event)
   ถ้าจำเป็นจริง ให้เขียนเหตุผลลง `docs/CHANGES_REQUESTED.md` แล้วทำงานตาม contract เดิมไปก่อน
3. `realm/core/` ห้าม import อะไรจาก `realm.db`, `realm.services`, `realm.api`, `realm.engine`, `realm.bot`
4. ทุกฟังก์ชันที่ขึ้นกับเวลา **รับ `now: datetime` เป็น parameter** ห้ามเรียก `datetime.now()` เอง
   ยกเว้นใน worker loop, API dependency และ `realm/core/clock.py`
5. ทุกเวลาเป็น timezone-aware UTC (`datetime.now(timezone.utc)`), ห้ามใช้ naive datetime
6. Type hints ทุกฟังก์ชัน, docstring สั้นหนึ่งบรรทัดสำหรับฟังก์ชัน public
7. ต้องมี test ตามช่อง "เกณฑ์เสร็จ" และต้องผ่าน `uv run pytest` กับ `uv run ruff check`
8. ห้ามเพิ่ม dependency นอกตารางหัวข้อ 2 ถ้าจำเป็นให้ขอผ่าน `docs/CHANGES_REQUESTED.md`
9. ค่าตัวเลขของเกม (ราคา เวลา สถิติ) อ่านจาก config เสมอ ห้าม hard-code ในโค้ด
10. จบงานแล้วเขียน `docs/handoff/<TASK_ID>.md`: ทำอะไรไป ไฟล์ไหน ฟังก์ชัน public ที่เพิ่ม ข้อจำกัด และ TODO
11. ส่งไฟล์กลับเป็น **เนื้อหาเต็มทั้งไฟล์** ไม่ใช่ diff
12. ข้อความที่ผู้เล่นเห็น (UI, รายงาน) เป็นภาษาไทย ส่วนโค้ด ชื่อตัวแปร log และ comment เป็นภาษาอังกฤษ

---

## 1. ภาพรวมระบบ

เกมวางแผนสร้างหมู่บ้านแบบเรียลไทม์บนเว็บ ผู้เล่น 1 คนแข่งกับ bot ~30 ตัว รันบน home server ด้วย Docker Compose

Process ที่รัน (ทุกตัวใช้โค้ด package `realm` เดียวกัน):

| Process | คำสั่ง | หน้าที่ |
| --- | --- | --- |
| db | postgres:16 | เก็บสถานะเกมทั้งหมด + คิว event |
| migrate | `realm migrate` | รัน alembic แล้วจบ |
| api | `realm api` | FastAPI: REST + WebSocket |
| engine | `realm engine` | ดึง event ที่ถึงเวลาจากตาราง `events` มาประมวลผล |
| bots | `realm bots` | ให้ bot ที่ถึงรอบคิดตัดสินใจ แล้วเรียก service ชุดเดียวกับผู้เล่น |
| caddy | caddy:2 | เสิร์ฟไฟล์ `web/` และ proxy `/api`, `/ws` ไปที่ api |

หลักการสำคัญ:

- **ไม่มี tick ทุกวินาที** ทุกอย่างที่ใช้เวลา (สร้างเสร็จ ฝึกทหาร ทัพถึง) เป็นแถวในตาราง `events`
- **ทรัพยากรคำนวณแบบ lazy**: เก็บ stock + เวลาอัปเดตล่าสุด แล้วคำนวณเมื่อจำเป็น (`settle`)
- **Settle ก่อนเปลี่ยนเสมอ**: ก่อนแก้อะไรที่กระทบ stock หรืออัตราผลิตของหมู่บ้าน ต้อง settle ณ เวลานั้นก่อน
- **Bot ไม่มีสิทธิ์พิเศษ**: เรียก `realm.services` เหมือน API ทุกประการ (ยกเว้นตัวคูณ production ของระดับยาก)
- **นาฬิกาเกมหยุดได้**: เวลาเกม = เวลาจริง − เวลาที่หยุดสะสม (หัวข้อ 4)

---

## 2. Tech stack

| ส่วน | ใช้ | เวอร์ชัน |
| --- | --- | --- |
| ภาษา | Python | 3.12 |
| จัดการแพ็กเกจ | uv | ล่าสุด |
| Web framework | fastapi, uvicorn[standard] | fastapi ≥0.115 |
| ORM | sqlalchemy | 2.0 (sync, typed `Mapped[]`) |
| Driver | psycopg[binary] | 3.x (ใช้ทั้ง sync และ async สำหรับ LISTEN) |
| Migration | alembic | ≥1.13 |
| Validation | pydantic, pydantic-settings | 2.x |
| Config | pyyaml | 6.x |
| CLI | typer | ≥0.12 |
| Test | pytest, httpx (TestClient) | ล่าสุด |
| Lint/format | ruff | ล่าสุด, line-length 100 |
| Frontend | HTML + vanilla JS (ES modules) + Canvas 2D | ไม่มี build step ไม่ใช้ Node |
| Infra | PostgreSQL 16, Caddy 2, Docker Compose v2 | — |

เหตุผลที่ไม่ใช้ React: ไม่ต้องมี toolchain Node บน server และโค้ดสั้นพอให้ agent อ่านได้ทั้งไฟล์

---

## 3. โครงสร้าง repo

```
realm/                          # root ของ repo
├── pyproject.toml
├── uv.lock
├── alembic.ini
├── docker-compose.yml
├── docker-compose.test.yml     # postgres สำหรับรัน test
├── .env.example
├── README.md
├── docs/
│   ├── CHANGES_REQUESTED.md
│   └── handoff/                # agent เขียน <TASK_ID>.md ที่นี่
├── docker/
│   ├── Dockerfile
│   └── Caddyfile
├── scripts/
│   └── backup.sh
├── realm/                      # Python package
│   ├── __init__.py
│   ├── settings.py             # pydantic-settings
│   ├── cli.py                  # typer app ชื่อ `realm`
│   ├── config/                 # ไฟล์ YAML ข้อมูลเกม
│   │   ├── game.yaml
│   │   ├── buildings.yaml
│   │   ├── units.yaml
│   │   ├── tribes.yaml
│   │   └── bots.yaml
│   ├── core/                   # กติกาเกมล้วน ไม่มี DB ไม่มี IO (ยกเว้นโหลด config)
│   │   ├── __init__.py
│   │   ├── config.py           # pydantic models + load_config()
│   │   ├── types.py            # Res, enums
│   │   ├── clock.py
│   │   ├── economy.py
│   │   ├── construction.py
│   │   ├── slots.py
│   │   ├── units.py
│   │   ├── movement.py
│   │   ├── combat.py
│   │   └── worldgen.py
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── session.py
│   │   └── migrations/         # alembic env.py + versions/
│   ├── services/               # คำสั่งเกม ใช้ core + db, ใช้ร่วมกันโดย api / engine / bots
│   │   ├── __init__.py
│   │   ├── errors.py
│   │   ├── events.py
│   │   ├── notify.py
│   │   ├── worlds.py
│   │   ├── villages.py
│   │   ├── training.py
│   │   ├── military.py
│   │   ├── reports.py
│   │   ├── views.py            # pydantic view models ที่ API ส่งออก
│   │   └── ranking.py
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── worker.py
│   │   └── handlers.py
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── worker.py
│   │   ├── brain.py
│   │   ├── modules.py          # ตัวสร้าง candidate action แต่ละประเภท
│   │   └── memory.py
│   ├── sim/
│   │   └── simulate.py         # จำลองโลกแบบเร่งเวลา (T17)
│   └── api/
│       ├── __init__.py
│       ├── main.py             # create_app()
│       ├── deps.py
│       ├── schemas.py          # request bodies
│       ├── ws.py
│       └── routes/
│           ├── state.py
│           ├── villages.py
│           ├── military.py
│           ├── world.py        # map, ranking
│           ├── reports.py
│           └── admin.py
├── web/
│   ├── index.html
│   ├── css/style.css
│   └── js/
│       ├── api.js
│       ├── clock.js
│       ├── ws.js
│       ├── app.js              # hash router + layout
│       ├── format.js
│       └── views/
│           ├── village.js
│           ├── center.js
│           ├── map.js
│           ├── rally.js
│           ├── reports.js
│           ├── ranking.js
│           └── newgame.js
└── tests/
    ├── conftest.py
    ├── core/
    ├── services/
    ├── engine/
    ├── bot/
    └── api/
```

---

## 4. Contract: เวลา

- ทุก timestamp ในฐานข้อมูลเป็น `timestamptz` และเก็บเป็น **เวลาเกม** ยกเว้น `worlds.created_at`, `worlds.paused_at`
- เวลาเกมคำนวณจาก:

```python
# realm/core/clock.py
def game_now(real_now: datetime, paused_at: datetime | None, paused_total_s: float) -> datetime:
    """Game time = (paused_at or real_now) - paused_total."""
    base = paused_at if paused_at is not None else real_now
    return base - timedelta(seconds=paused_total_s)

def scaled(base_seconds: float, speed: int) -> float:
    """Duration after applying world speed. Never below 1 second."""
    return max(1.0, base_seconds / speed)
```

- หยุดเกม: `paused_at = real_now`
- เล่นต่อ: `paused_total_s += (real_now - paused_at).total_seconds()` แล้ว `paused_at = None`
- ความเร็วโลก (`worlds.speed` = 1, 3, 5, 10) **ไม่ได้เร่งนาฬิกา** แต่หารทุกระยะเวลา (ก่อสร้าง ฝึก เดินทัพ ช่วงคุ้มครอง ความยาวรอบ) และคูณอัตราผลิต
- Client ได้ `game_now` จาก API ทุกครั้ง แล้วนับถอยหลังด้วย `due_at - game_now` ไม่ใช้นาฬิกาเครื่อง client ตรงๆ

---

## 5. Contract: Config (YAML)

ไฟล์อยู่ที่ `realm/config/` โหลดผ่าน `realm.core.config.load_config()` ซึ่ง cache ด้วย `functools.lru_cache`
ค่าทั้งหมดด้านล่างคือ **ค่าเริ่มต้นที่ต้องใส่จริง** (ปรับ balance ทีหลังได้)

### 5.1 `game.yaml`

```yaml
world:
  size: 101                 # พิกัด -50..50 ทั้งแกน x และ y, ขอบวนรอบ (torus)
  bot_count: 30
  protection_hours: 72      # ชั่วโมงที่ 1x (หารด้วย speed)
  round_days: 60            # วันที่ 1x (หารด้วย speed)
  start_resources: {wood: 750, stone: 750, iron: 750, food: 750}
  player_spawn_radius: 3
  bot_spawn_min_radius: 5
  bot_spawn_max_radius: 30
  min_village_distance: 3
  tile_weights:             # ใช้สุ่มชนิดช่อง รวม 100
    valley_standard: 70     # layout 4-4-4-6
    valley_food9: 4         # 3-3-3-9
    valley_food15: 1        # 1-1-1-15
    valley_other: 10        # สุ่มจาก other_layouts
    oasis: 10
    mountain: 3
    lake: 2
  other_layouts: ["5-4-3-6", "4-5-3-6", "3-4-5-6", "5-3-4-6", "4-3-5-6", "3-5-4-6"]

economy:
  production_level0: 2.0    # ทุ่งเลเวล 0 ผลิต 2/ชม.
  production_base: 10.0     # P(1)
  production_growth: 1.4    # P(L) = base * growth^(L-1)
  storage_base: 800         # cap(L) = storage_base * storage_growth^L  (L=0 คือยังไม่สร้าง)
  storage_growth: 1.25
  hideout_base: 150         # hide(L) = hideout_base * hideout_growth^(L-1), L=0 -> 0
  hideout_growth: 1.35
  food_per_population: 1.0  # อาหาร/ชม. ต่อประชากร 1 คน

construction:
  cost_growth: 1.28
  time_growth: 1.16
  town_hall_time_factor: 0.05     # time /= (1 + 0.05*(T-1))
  second_queue_town_hall_level: 10
  training_building_factor: 0.9   # train_time *= 0.9^(L-1) ของอาคารที่ฝึก

combat:
  base_village_defense: 10
  wall_bonus_per_level: 0.03
  loss_exponent: 1.5
  ram_per_level: 2          # ต้องใช้ ram ที่รอด 2*L ตัวเพื่อลดกำแพงจาก L เป็น L-1
  catapult_per_level: 3
  chief_loyalty_min: 20
  chief_loyalty_max: 30
  loyalty_regen_per_palace_level: 1.0   # ต่อชั่วโมงที่ 1x
  scout_defense_ratio: 1.0
  conquest_loyalty: 25.0               # loyalty of a village right after it is conquered (T21)

culture:
  # แต้มสะสมขั้นต่ำเพื่อมีหมู่บ้านที่ n (index 0 = หมู่บ้านแรก)
  village_cp_thresholds: [0, 2000, 8000, 20000, 40000, 70000, 110000, 160000, 220000, 300000]
  settlers_needed: 3

upgrades:                          # อัปเกรดหน่วยที่โรงตีเหล็ก (T22)
  bonus_per_level: 0.015           # โจมตีและป้องกัน +1.5% ต่อเลเวล
  max_level: 20                    # และไม่เกินเลเวลโรงตีเหล็กของหมู่บ้าน
  cost_unit_multiple: 10           # ราคาเลเวล 1 = ราคาหน่วย x 10
  cost_growth: 1.3                 # cost(L) = base * growth^(L-1)
  time_base_s: 1800                # เวลาเลเวล 1 ที่ 1x
  time_growth: 1.2                 # time(L) = base * growth^(L-1) / speed
  unit_types: [inf, cav, siege]    # ชนิดหน่วยที่อัปเกรดได้

oasis:                             # oases, wild animals and their bonus (T23)
  bonus: 0.25                      # +25% production of the oasis resource per owned oasis
  radius: 3                        # an oasis must lie within this distance of the owning village
  max_per_village: 3
  respawn_hours: 12                # game hours between animal respawn ticks (divided by world speed)
  respawn_fraction: 0.25           # fraction of the full animal count restored per tick
  animals:                         # NPC defenders (they never attack)
    rat:    {name_th: หนูป่า, def_inf: 25, def_cav: 20, min: 8, max: 20}
    spider: {name_th: แมงมุมยักษ์, def_inf: 40, def_cav: 60, min: 4, max: 12}
    boar:   {name_th: หมูป่า, def_inf: 60, def_cav: 40, min: 2, max: 8}
```

### 5.2 `buildings.yaml`

ฟิลด์: `name_th`, `kind` (`field` | `fixed` | `center`), `produces` (เฉพาะ field), `max_level`,
`capital_max_level` (ถ้าไม่ใส่ = `max_level`), `base_cost`, `base_time_s`, `pop_per_level`, `cp_per_level`, `requires`, `fixed_slot` (เฉพาะ fixed)

```yaml
woodcutter:
  name_th: ทุ่งตัดไม้
  kind: field
  produces: wood
  max_level: 10
  capital_max_level: 15
  base_cost: {wood: 50, stone: 90, iron: 40, food: 50}
  base_time_s: 240
  pop_per_level: 1
  cp_per_level: 1
  requires: {}
quarry:
  name_th: เหมืองหิน
  kind: field
  produces: stone
  max_level: 10
  capital_max_level: 15
  base_cost: {wood: 80, stone: 40, iron: 60, food: 50}
  base_time_s: 240
  pop_per_level: 1
  cp_per_level: 1
  requires: {}
iron_mine:
  name_th: เหมืองเหล็ก
  kind: field
  produces: iron
  max_level: 10
  capital_max_level: 15
  base_cost: {wood: 90, stone: 80, iron: 30, food: 50}
  base_time_s: 270
  pop_per_level: 1
  cp_per_level: 1
  requires: {}
farm:
  name_th: ไร่นา
  kind: field
  produces: food
  max_level: 10
  capital_max_level: 15
  base_cost: {wood: 60, stone: 70, iron: 50, food: 20}
  base_time_s: 200
  pop_per_level: 0
  cp_per_level: 1
  requires: {}
town_hall:
  name_th: ศาลากลาง
  kind: fixed
  fixed_slot: 19
  max_level: 20
  base_cost: {wood: 70, stone: 50, iron: 40, food: 60}
  base_time_s: 600
  pop_per_level: 2
  cp_per_level: 2
  requires: {}
rally_point:
  name_th: จุดรวมพล
  kind: fixed
  fixed_slot: 39
  max_level: 20
  base_cost: {wood: 100, stone: 80, iron: 60, food: 40}
  base_time_s: 700
  pop_per_level: 1
  cp_per_level: 1
  requires: {}
wall:
  name_th: กำแพง
  kind: fixed
  fixed_slot: 40
  max_level: 20
  base_cost: {wood: 100, stone: 180, iron: 80, food: 50}
  base_time_s: 1200
  pop_per_level: 0
  cp_per_level: 1
  requires: {}
warehouse:
  name_th: คลังสินค้า
  kind: center
  max_level: 20
  base_cost: {wood: 120, stone: 140, iron: 80, food: 30}
  base_time_s: 900
  pop_per_level: 1
  cp_per_level: 1
  requires: {town_hall: 1}
granary:
  name_th: ยุ้งฉาง
  kind: center
  max_level: 20
  base_cost: {wood: 80, stone: 120, iron: 60, food: 20}
  base_time_s: 800
  pop_per_level: 1
  cp_per_level: 1
  requires: {town_hall: 1}
barracks:
  name_th: ค่ายทหาร
  kind: center
  max_level: 20
  base_cost: {wood: 200, stone: 160, iron: 140, food: 60}
  base_time_s: 1500
  pop_per_level: 2
  cp_per_level: 2
  requires: {town_hall: 3, rally_point: 1}
smithy:
  name_th: โรงตีเหล็ก
  kind: center
  max_level: 20
  base_cost: {wood: 180, stone: 200, iron: 220, food: 80}
  base_time_s: 1800
  pop_per_level: 2
  cp_per_level: 2
  requires: {town_hall: 3, barracks: 1}
stable:
  name_th: คอกม้า
  kind: center
  max_level: 20
  base_cost: {wood: 260, stone: 220, iron: 280, food: 100}
  base_time_s: 2200
  pop_per_level: 3
  cp_per_level: 3
  requires: {barracks: 3, smithy: 1}
workshop:
  name_th: โรงช่าง
  kind: center
  max_level: 20
  base_cost: {wood: 400, stone: 300, iron: 350, food: 150}
  base_time_s: 2700
  pop_per_level: 3
  cp_per_level: 3
  requires: {town_hall: 5, smithy: 5}
hideout:
  name_th: ห้องลับ
  kind: center
  max_level: 10
  base_cost: {wood: 40, stone: 50, iron: 30, food: 10}
  base_time_s: 400
  pop_per_level: 0
  cp_per_level: 1
  requires: {}
marketplace:
  name_th: ตลาด
  kind: center
  max_level: 20
  base_cost: {wood: 80, stone: 70, iron: 120, food: 70}
  base_time_s: 1500
  pop_per_level: 2
  cp_per_level: 3
  requires: {town_hall: 3, warehouse: 1, granary: 1}
palace:
  name_th: วัง
  kind: center
  max_level: 20
  base_cost: {wood: 600, stone: 700, iron: 500, food: 300}
  base_time_s: 3600
  pop_per_level: 4
  cp_per_level: 5
  requires: {town_hall: 5}
```

กติกา: อาคาร `center` มีได้อย่างละ 1 หลังต่อหมู่บ้าน

### 5.3 `units.yaml`

ฟิลด์: `name_th`, `type` (`inf` | `cav` | `scout` | `siege` | `special`), `attack`, `def_inf`, `def_cav`,
`speed` (ช่อง/ชม. ที่ 1x), `carry`, `upkeep` (อาหาร/ชม.), `cost`, `train_time_s`, `trained_in`, `requires`

```yaml
spearman:
  name_th: ทหารหอก
  type: inf
  attack: 10
  def_inf: 35
  def_cav: 50
  speed: 7
  carry: 40
  upkeep: 1
  cost: {wood: 70, stone: 50, iron: 30, food: 50}
  train_time_s: 600
  trained_in: barracks
  requires: {barracks: 1}
swordsman:
  name_th: ทหารดาบ
  type: inf
  attack: 40
  def_inf: 20
  def_cav: 15
  speed: 6
  carry: 50
  upkeep: 1
  cost: {wood: 60, stone: 40, iron: 110, food: 40}
  train_time_s: 720
  trained_in: barracks
  requires: {barracks: 3, smithy: 1}
scout:
  name_th: หน่วยสอดแนม
  type: scout
  attack: 0
  def_inf: 10
  def_cav: 5
  speed: 16
  carry: 0
  upkeep: 1
  cost: {wood: 50, stone: 40, iron: 40, food: 40}
  train_time_s: 500
  trained_in: barracks
  requires: {barracks: 1}
light_cavalry:
  name_th: ทหารม้าเบา
  type: cav
  attack: 60
  def_inf: 20
  def_cav: 10
  speed: 14
  carry: 80
  upkeep: 2
  cost: {wood: 160, stone: 140, iron: 220, food: 80}
  train_time_s: 1200
  trained_in: stable
  requires: {stable: 1}
heavy_cavalry:
  name_th: ทหารม้าหนัก
  type: cav
  attack: 120
  def_inf: 50
  def_cav: 70
  speed: 10
  carry: 70
  upkeep: 3
  cost: {wood: 300, stone: 250, iron: 400, food: 150}
  train_time_s: 1800
  trained_in: stable
  requires: {stable: 5}
ram:
  name_th: เครื่องกระทุ้ง
  type: siege
  attack: 60
  def_inf: 30
  def_cav: 60
  speed: 4
  carry: 0
  upkeep: 3
  cost: {wood: 400, stone: 300, iron: 200, food: 100}
  train_time_s: 3000
  trained_in: workshop
  requires: {workshop: 1}
catapult:
  name_th: เครื่องยิงหิน
  type: siege
  attack: 70
  def_inf: 20
  def_cav: 10
  speed: 3
  carry: 0
  upkeep: 6
  cost: {wood: 500, stone: 600, iron: 350, food: 150}
  train_time_s: 4500
  trained_in: workshop
  requires: {workshop: 5}
chief:
  name_th: ผู้นำ
  type: special
  attack: 40
  def_inf: 50
  def_cav: 40
  speed: 4
  carry: 0
  upkeep: 4
  cost: {wood: 7000, stone: 6000, iron: 7000, food: 5000}
  train_time_s: 30000
  trained_in: palace
  requires: {palace: 15}
settler:
  name_th: ผู้บุกเบิก
  type: special
  attack: 0
  def_inf: 80
  def_cav: 80
  speed: 5
  carry: 3000
  upkeep: 1
  cost: {wood: 1500, stone: 1300, iron: 1200, food: 1000}
  train_time_s: 10000
  trained_in: palace
  requires: {palace: 10}
```

กติกาการใช้หน่วย:
- `scout` ไปภารกิจ `scout` ได้อย่างเดียว และภารกิจ `scout` ต้องมีแต่ scout
- `settler` ไปภารกิจ `settle` ได้อย่างเดียว จำนวนเท่ากับ `settlers_needed` พอดี
- `chief` ไปได้เฉพาะ `attack` และ `reinforce`
- ในสูตรรบ หน่วย `type: cav` นับเป็น A_cav ที่เหลือทั้งหมดนับเป็น A_inf

### 5.4 `tribes.yaml`

ทุกเผ่าต้องมี modifier ครบทุก key (ค่าปกติ 1.0)

```yaml
stonehold:
  name_th: อาณาจักรศิลา
  description_th: เน้นตั้งรับ กำแพงแข็ง ทหารราบป้องกันเก่ง
  modifiers:
    wall_bonus_mult: 1.5
    inf_defense_mult: 1.15   # คูณ def_inf และ def_cav ของหน่วย type inf
    unit_cost_mult: 1.0
    carry_mult: 1.0
    cav_speed_mult: 1.0
    hideout_mult: 1.0
ironwild:
  name_th: ชนเผ่าเหล็กป่า
  description_th: เน้นบุกปล้น ทหารถูก ขนของได้มาก
  modifiers:
    wall_bonus_mult: 1.0
    inf_defense_mult: 1.0
    unit_cost_mult: 0.8
    carry_mult: 1.25
    cav_speed_mult: 1.0
    hideout_mult: 1.0
windriders:
  name_th: สหพันธ์สายลม
  description_th: เน้นความเร็ว ทหารม้าไว ห้องลับใหญ่
  modifiers:
    wall_bonus_mult: 1.0
    inf_defense_mult: 1.0
    unit_cost_mult: 1.0
    carry_mult: 1.0
    cav_speed_mult: 1.2
    hideout_mult: 2.0
```

### 5.5 `bots.yaml`

```yaml
difficulty_shares: {easy: 0.4, normal: 0.45, hard: 0.15}
difficulties:
  easy:   {think_interval_min: 60, max_actions: 1, skip_chance: 0.4, production_mult: 1.0, defend: false, spawn_min_radius: 5}
  normal: {think_interval_min: 20, max_actions: 3, skip_chance: 0.1, production_mult: 1.0, defend: false, spawn_min_radius: 8}
  hard:   {think_interval_min: 5,  max_actions: 6, skip_chance: 0.0, production_mult: 1.2, defend: true,  spawn_min_radius: 15}

personalities:
  farmer:
    name_th: ชาวนา
    share: 0.35
    weights: {economy: 1.0, build: 1.0, storage: 1.0, military: 0.2, raid: 0.0, expand: 0.3}
    army_hours: 2
    unit_mix: {spearman: 1.0}
    raid_radius: 0
    active_from_day: 0
    build_order: [warehouse:1, granary:1, rally_point:1, town_hall:3, barracks:1, warehouse:5, granary:5,
                  town_hall:5, hideout:5, palace:1, warehouse:10, granary:10, palace:10]
  turtle:
    name_th: เต่า
    share: 0.20
    weights: {economy: 0.8, build: 1.2, storage: 1.0, military: 0.8, raid: 0.0, expand: 0.1}
    army_hours: 6
    unit_mix: {spearman: 0.8, swordsman: 0.2}
    raid_radius: 0
    active_from_day: 0
    build_order: [rally_point:1, town_hall:3, barracks:1, wall:5, hideout:5, warehouse:5, granary:5,
                  barracks:5, wall:10, hideout:10, wall:15]
  raider:
    name_th: นักปล้น
    share: 0.20
    weights: {economy: 0.7, build: 1.0, storage: 1.0, military: 1.2, raid: 1.5, expand: 0.2}
    army_hours: 8
    unit_mix: {light_cavalry: 0.7, swordsman: 0.3}
    raid_radius: 12
    active_from_day: 0
    build_order: [rally_point:1, town_hall:3, barracks:3, smithy:1, warehouse:3, granary:3, stable:1,
                  hideout:3, stable:5, warehouse:8, granary:8]
  expander:
    name_th: นักขยาย
    share: 0.15
    weights: {economy: 1.0, build: 1.2, storage: 1.0, military: 0.3, raid: 0.2, expand: 1.5}
    army_hours: 2
    unit_mix: {spearman: 1.0}
    raid_radius: 6
    active_from_day: 0
    build_order: [rally_point:1, town_hall:5, warehouse:5, granary:5, palace:1, marketplace:1, palace:10]
  warlord:
    name_th: ขุนศึก
    share: 0.10
    weights: {economy: 0.8, build: 1.0, storage: 1.0, military: 1.5, raid: 1.2, expand: 0.5, conquer: 1.5}
    army_hours: 12
    unit_mix: {swordsman: 0.4, heavy_cavalry: 0.4, ram: 0.1, catapult: 0.1}
    raid_radius: 20
    active_from_day: 10
    build_order: [rally_point:1, town_hall:5, barracks:5, smithy:5, stable:5, workshop:1, palace:1, palace:15]
```

`active_from_day`: ก่อนถึงวันนี้ (นับวันเกมที่ 1x หารด้วย speed) weight `raid` และ `military` ของบุคลิกนั้นคูณ 0.3

### 5.6 `realm/core/config.py` (pydantic models)

```python
class ResAmount(BaseModel):  wood: float; stone: float; iron: float; food: float
class BuildingDef(BaseModel):
    key: str                         # เติมจาก key ของ dict ตอนโหลด
    name_th: str
    kind: Literal["field", "fixed", "center"]
    produces: Literal["wood", "stone", "iron", "food"] | None = None
    max_level: int
    capital_max_level: int | None = None
    fixed_slot: int | None = None
    base_cost: ResAmount
    base_time_s: float
    pop_per_level: int
    cp_per_level: int
    requires: dict[str, int] = {}
class UnitDef(BaseModel): key, name_th, type, attack, def_inf, def_cav, speed, carry, upkeep, cost: ResAmount,
                          train_time_s, trained_in, requires
class TribeModifiers(BaseModel): wall_bonus_mult, inf_defense_mult, unit_cost_mult, carry_mult, cav_speed_mult, hideout_mult
class TribeDef(BaseModel): key, name_th, description_th, modifiers: TribeModifiers
class DifficultyDef(BaseModel): think_interval_min, max_actions, skip_chance, production_mult, defend, spawn_min_radius
class PersonalityDef(BaseModel): key, name_th, share, weights: dict[str, float], army_hours, unit_mix: dict[str, float],
                                 raid_radius, active_from_day, build_order: list[tuple[str, int]]  # แปลงจาก "type:level"
class GameConfig(BaseModel):
    world: WorldSection; economy: EconomySection; construction: ConstructionSection
    combat: CombatSection; culture: CultureSection
    buildings: dict[str, BuildingDef]; units: dict[str, UnitDef]; tribes: dict[str, TribeDef]
    bot_difficulties: dict[str, DifficultyDef]; difficulty_shares: dict[str, float]
    personalities: dict[str, PersonalityDef]

def load_config(config_dir: str | Path | None = None) -> GameConfig: ...   # lru_cache; None = settings.config_dir
```

Validation ที่ต้องมี (raise `ValueError` พร้อมข้อความชัด):
- `requires` ทุก key ต้องเป็นอาคารที่มีอยู่, `trained_in` ต้องเป็นอาคารที่มีอยู่
- อาคาร `field` ต้องมี `produces`, อาคาร `fixed` ต้องมี `fixed_slot`
- `unit_mix` และ `build_order` อ้างถึงหน่วย/อาคารที่มีอยู่
- `share` ของบุคลิกรวมกัน = 1.0 (±0.001), `difficulty_shares` รวม = 1.0
- `tile_weights` รวม = 100

---

## 6. Contract: core (สูตรและ signature)

### 6.1 `types.py`

```python
RESOURCE_KEYS = ("wood", "stone", "iron", "food")

@dataclass(frozen=True, slots=True)
class Res:
    wood: float = 0.0
    stone: float = 0.0
    iron: float = 0.0
    food: float = 0.0
    def __add__(self, o: "Res") -> "Res": ...
    def __sub__(self, o: "Res") -> "Res": ...
    def scale(self, k: float) -> "Res": ...
    def covers(self, cost: "Res") -> bool: ...      # ทุกช่อง >= cost (เผื่อ epsilon 1e-6)
    def clamp(self, lo: "Res", hi: "Res") -> "Res": ...
    def total(self) -> float: ...
    def floor(self) -> "Res": ...
    def to_dict(self) -> dict[str, float]: ...
    @staticmethod
    def from_dict(d: Mapping[str, float]) -> "Res": ...
    @staticmethod
    def uniform(v: float) -> "Res": ...

class Mission(StrEnum):
    ATTACK = "attack"; RAID = "raid"; SCOUT = "scout"; REINFORCE = "reinforce"; SETTLE = "settle"; RETURN = "return"

class EventType(StrEnum):
    BUILD_COMPLETE = "build_complete"
    TRAIN_TICK = "train_tick"
    MOVEMENT_ARRIVE = "movement_arrive"
    STARVATION_CHECK = "starvation_check"
    ROUND_END = "round_end"

class TileKind(StrEnum):
    VALLEY = "valley"; OASIS = "oasis"; MOUNTAIN = "mountain"; LAKE = "lake"

Units = dict[str, int]        # unit_key -> count (ไม่เก็บ key ที่ count = 0)
```

### 6.2 `slots.py`

- slot 1–18 = ทุ่ง ชนิดตาม layout: layout `"a-b-c-d"` → slot 1..a = woodcutter, ถัดไป b ช่อง = quarry, c ช่อง = iron_mine, d ช่อง = farm
- slot 19 = town_hall, slot 39 = rally_point, slot 40 = wall (ตาม `fixed_slot`)
- slot 20–38 = อาคาร `center` อะไรก็ได้ (19 ช่อง)

```python
FIELD_SLOTS = range(1, 19); CENTER_SLOTS = range(20, 39); ALL_SLOTS = range(1, 41)
def field_types_for_layout(layout: str) -> dict[int, str]: ...      # slot -> field type
def slot_accepts(slot: int, btype: str, cfg: GameConfig, layout: str) -> bool: ...
def initial_buildings(layout: str, cfg: GameConfig) -> dict[int, tuple[str, int]]: ...
    # หมู่บ้านใหม่: ทุ่ง 18 ช่อง level 0, town_hall level 1, rally_point level 0, wall level 0
    # slot center ไม่มีแถว (ว่าง)
```

### 6.3 `economy.py`

```python
def field_production(level: int, cfg) -> float
    # L=0 -> production_level0, L>=1 -> production_base * production_growth**(L-1)   (ต่อชั่วโมงที่ 1x)
def storage_capacity(level: int, cfg) -> float          # storage_base * storage_growth**level
def hideout_capacity(level: int, tribe: str, cfg) -> float
    # L=0 -> 0, else hideout_base * hideout_growth**(L-1) * tribe.hideout_mult  (ต่อทรัพยากรแต่ละชนิด)
def population(buildings: Mapping[str, int] | Iterable[tuple[str, int]], cfg) -> int
    # sum(pop_per_level * level) ทุกอาคาร
def gross_production(field_levels: Iterable[tuple[str, int]], speed: int, production_mult: float, cfg) -> Res
    # รวม field_production ตามชนิดทุ่ง * speed * production_mult
def village_rates(gross: Res, population: int, troop_upkeep: float, speed: int, cfg) -> Res
    # ไม้ หิน เหล็ก = gross, อาหาร = gross.food - (population*food_per_population + troop_upkeep) * speed
def village_capacity(warehouse_level: int, granary_level: int, cfg) -> Res
    # wood/stone/iron = storage_capacity(warehouse), food = storage_capacity(granary)
def settle(stock: Res, updated_at: datetime, now: datetime, rates: Res, capacity: Res) -> Res
    # elapsed_h = max(0, (now-updated_at).total_seconds()/3600)
    # new = stock + rates*elapsed_h แล้ว clamp ทุกช่องไว้ที่ [0, capacity]
def seconds_until_food_empty(stock: Res, rates: Res) -> float | None
    # None ถ้า rates.food >= 0 ไม่งั้น stock.food / -rates.food * 3600
def culture_per_day(building_levels: Iterable[tuple[str, int]], speed: int, cfg) -> float
    # sum(cp_per_level * level) * speed
```

### 6.4 `construction.py`

```python
def building_cost(btype: str, target_level: int, cfg) -> Res
    # base_cost * cost_growth**(target_level-1)   ปัดลงเป็นจำนวนเต็มทุกช่อง
def build_time_s(btype: str, target_level: int, town_hall_level: int, speed: int, cfg) -> float
    # base_time_s * time_growth**(target_level-1) / (1 + town_hall_time_factor*(max(1,T)-1)) / speed, ขั้นต่ำ 1
def max_level(btype: str, is_capital: bool, cfg) -> int
def missing_requirements(btype: str, levels: Mapping[str, int], cfg) -> list[str]
    # คืนรายการข้อความไทย เช่น ["ต้องมี ค่ายทหาร เลเวล 3"] ถ้าว่างแปลว่าผ่าน
def queue_limit(town_hall_level: int, cfg) -> int      # 1 หรือ 2
```

`levels` = dict ของ `building_type -> level สูงสุดในหมู่บ้าน`

### 6.5 `units.py`

```python
def unit_cost(unit: str, tribe: str, cfg) -> Res                    # cost * unit_cost_mult ปัดลง
def train_time_s(unit: str, building_level: int, speed: int, cfg) -> float
    # train_time_s * training_building_factor**(max(1,L)-1) / speed, ขั้นต่ำ 1
def unit_speed(unit: str, tribe: str, cfg) -> float                 # cav คูณ cav_speed_mult
def army_speed(units: Units, tribe: str, cfg) -> float              # ต่ำสุดของหน่วยที่ count>0
def carry_capacity(units: Units, tribe: str, cfg) -> float          # sum(carry*count) * carry_mult
def troop_upkeep(units: Units, cfg) -> float                        # sum(upkeep*count) ต่อชม.ที่ 1x
def unit_defense(unit: str, tribe: str, cfg) -> tuple[float, float] # (def_inf, def_cav) หลัง modifier
def missing_unit_requirements(unit: str, levels: Mapping[str, int], cfg) -> list[str]
def validate_mission_units(mission: Mission, units: Units, cfg) -> list[str]   # กติกาหัวข้อ 5.3
def army_value(units: Units, cfg) -> float                          # sum(cost.total()*count)
```

### 6.6 `movement.py`

```python
def wrap(v: int, size: int) -> int                     # แปลงพิกัดให้อยู่ใน -(size//2)..size//2
def distance(x1: int, y1: int, x2: int, y2: int, size: int) -> float
    # dx = min(|x1-x2|, size-|x1-x2|) เช่นเดียวกับ dy, คืน sqrt(dx²+dy²)
def travel_time_s(units: Units, tribe: str, dist: float, speed: int, cfg) -> float
    # dist / army_speed * 3600 / speed, ขั้นต่ำ 1
```

### 6.7 `combat.py`

```python
@dataclass
class ArmyGroup:
    tribe: str
    units: Units
    owner_ref: int | None = None     # id อ้างอิงกลับ (เช่น home_village_id) ใช้โดย service

@dataclass
class BattleInput:
    mission: Mission                  # ATTACK หรือ RAID
    attacker: ArmyGroup
    defenders: list[ArmyGroup]        # ทุกกลุ่มที่อยู่ในหมู่บ้านเป้าหมาย (เจ้าของ + ทัพเสริม)
    defender_tribe: str               # เผ่าเจ้าของหมู่บ้าน (ใช้กับโบนัสกำแพง)
    wall_level: int
    catapult_target_level: int | None # เลเวลอาคารที่เครื่องยิงหินเล็ง (None = ไม่เล็ง)

@dataclass
class BattleResult:
    attacker_won: bool
    attack_power: float
    defense_power: float
    attacker_losses: Units
    defender_losses: list[Units]      # ลำดับเดียวกับ defenders
    wall_level_after: int
    catapult_target_level_after: int | None
    loyalty_damage: int

def resolve_battle(inp: BattleInput, cfg, rng: random.Random) -> BattleResult
def resolve_scout(attacker_scouts: int, defender_scouts: int, cfg) -> tuple[bool, int]  # (success, attacker_losses)
def plunder(stock: Res, hidden_per_resource: float, carry: float) -> Res
```

สูตร `resolve_battle`:

1. A_inf = Σ attack×count ของหน่วยที่ไม่ใช่ cav, A_cav = Σ attack×count ของหน่วย cav, A = A_inf + A_cav
2. D_inf, D_cav = Σ ค่าป้องกัน (หลัง modifier เผ่าของแต่ละกลุ่ม) × count ทุกกลุ่ม
3. ถ้า A = 0: D = D_inf + base_village_defense, ฝ่ายรุกแพ้
   ไม่งั้น D_raw = D_inf×(A_inf/A) + D_cav×(A_cav/A) + base_village_defense
4. D = D_raw × (1 + wall_bonus_per_level × wall_bonus_mult(defender_tribe) × wall_level)
5. ชนะ: `attacker_won = A > D` (เท่ากัน = ฝ่ายรับชนะ)
6. x = (min(A,D)/max(A,D)) ** loss_exponent (ถ้า max = 0 ให้ x = 0)
7. อัตราสูญเสีย:
   - ATTACK: ผู้ชนะเสีย x, ผู้แพ้เสีย 1.0
   - RAID: ผู้ชนะเสีย x/(1+x), ผู้แพ้เสีย 1/(1+x)
8. จำนวนตาย = `int(count * ratio + 0.5)` ทุกหน่วย ทุกกลุ่ม
9. กำแพง (เฉพาะ ATTACK และผู้รุกชนะ): rams = ram ที่รอด; level = wall_level;
   `while level > 0 and rams >= ram_per_level*level: rams -= ram_per_level*level; level -= 1`
10. เครื่องยิงหิน: วิธีเดียวกันกับ catapult_target_level ใช้ catapult_per_level
11. ความภักดี (เฉพาะ ATTACK ผู้รุกชนะ): `loyalty_damage = Σ rng.randint(min,max)` ต่อ chief ที่รอด

สูตร `resolve_scout`: ถ้า defender_scouts = 0 → (True, 0)
ไม่งั้น ratio = defender_scouts×scout_defense_ratio/attacker_scouts; ratio < 1 → (True, int(attacker×ratio**1.5+0.5)); else (False, attacker_scouts)

สูตร `plunder` (แบ่งเท่ากันแบบเติมน้ำ):
1. avail = max(0, stock − hidden) ทุกชนิด
2. ถ้า Σavail ≤ carry → เอาทั้งหมด
3. ไม่งั้นวนรอบ: share = carry_left / จำนวนชนิดที่ยังมีของ; ชนิดที่ avail < share เอาหมดแล้วหักออก วนจนลงตัว ปัดลงเป็นจำนวนเต็ม

### 6.8 `worldgen.py`

```python
@dataclass(frozen=True)
class TileSpec:
    x: int; y: int; kind: TileKind; layout: str | None; oasis_type: str | None

def generate_tiles(seed: int, cfg) -> list[TileSpec]
    # ใช้ random.Random(seed) ไล่ทุกช่อง สุ่มชนิดตาม tile_weights
    # valley มี layout, oasis มี oasis_type สุ่มจาก RESOURCE_KEYS, อื่นๆ None
    # ช่อง (0,0) และรัศมี player_spawn_radius ต้องมี valley_standard อย่างน้อย 1 ช่อง (บังคับ (0,0) = 4-4-4-6)
def pick_spawns(tiles: list[TileSpec], seed: int, bot_radius_mins: list[int], cfg) -> tuple[tuple[int, int], list[tuple[int, int]]]
    # คืนตำแหน่งผู้เล่น (valley ใกล้ (0,0) ที่สุด) และตำแหน่ง bot ตามลำดับ bot_radius_mins
    # bot แต่ละตัว: valley ที่ระยะ [radius_min, bot_spawn_max_radius] ห่างหมู่บ้านอื่น ≥ min_village_distance
    # deterministic เมื่อ seed เดิม
```

---

## 7. Contract: Database schema

SQLAlchemy 2.0 (`realm/db/models.py`) + alembic migration แรก `0001_initial` สร้างทุกตารางนี้ครบตั้งแต่แรก
ทุก timestamp = `TIMESTAMP WITH TIME ZONE` | ทรัพยากร = `DOUBLE PRECISION` | JSON = `JSONB`

| ตาราง | คอลัมน์ | หมายเหตุ |
| --- | --- | --- |
| **worlds** | id BIGSERIAL PK, seed BIGINT, speed INT, size INT, status TEXT default 'running' ('running'/'ended'), created_at (เวลาจริง), game_epoch (เวลาเกมตอนเริ่ม), paused_at NULL (เวลาจริง), paused_total_s DOUBLE default 0, ends_at (เวลาเกม), winner_player_id BIGINT NULL | world ที่ status='running' และ id มากสุด = โลกปัจจุบัน |
| **players** | id PK, world_id FK, name TEXT, tribe TEXT, is_bot BOOL, production_mult DOUBLE default 1.0, culture_points DOUBLE default 0, cp_updated_at, protection_until, capital_village_id BIGINT NULL, created_at | |
| **bot_profiles** | player_id PK FK, personality TEXT, difficulty TEXT, next_think_at, memory JSONB default '{}' | |
| **tiles** | world_id FK, x INT, y INT, kind TEXT, layout TEXT NULL, oasis_type TEXT NULL, oasis_owner_village_id BIGINT NULL, animals JSONB NULL; PK(world_id,x,y) | สองคอลัมน์ท้ายใช้ใน Phase 2 |
| **villages** | id PK, world_id FK, player_id FK, name TEXT, x INT, y INT, layout TEXT, is_capital BOOL, loyalty DOUBLE default 100, wood, stone, iron, food DOUBLE, res_updated_at, created_at; UNIQUE(world_id,x,y) | |
| **buildings** | village_id FK, slot INT, type TEXT, level INT; PK(village_id,slot) | |
| **build_queue** | id PK, village_id FK, slot INT, type TEXT, target_level INT, started_at, finishes_at, event_id BIGINT | กำลังสร้างอยู่เท่านั้น ไม่มีคิวรอ |
| **troops** | id PK, home_village_id FK, location_village_id FK, unit TEXT, count INT; UNIQUE(home_village_id,location_village_id,unit) | home = จ่ายค่าอาหาร, location = อยู่ที่ไหน; ลบแถวเมื่อ count = 0 |
| **training_queue** | id PK, village_id FK, building TEXT, unit TEXT, count_total INT, count_done INT default 0, per_unit_s DOUBLE, starts_at, next_at, finishes_at | ต่ออาคาร ออร์เดอร์ใหม่เริ่มหลังออร์เดอร์เดิมจบ |
| **movements** | id PK, world_id FK, player_id FK, from_village_id FK, to_x INT, to_y INT, to_village_id BIGINT NULL, mission TEXT, units JSONB, loot JSONB default '{}', catapult_target TEXT NULL, departed_at, arrive_at, status TEXT default 'moving' ('moving'/'done') | ขากลับเป็นแถวใหม่ mission='return' |
| **events** | id PK, world_id FK, type TEXT, due_at, payload JSONB, status TEXT default 'pending' ('pending'/'done'/'failed'), attempts INT default 0, last_error TEXT NULL, created_at | INDEX(world_id,status,due_at) |
| **reports** | id PK, player_id FK, kind TEXT ('battle','scout','reinforce','settle','info'), title TEXT, data JSONB, is_read BOOL default false, created_at | INDEX(player_id,created_at DESC) |
| **unit_upgrades** | village_id FK, unit TEXT, level INT default 0, upgrading_to INT NULL, finishes_at NULL; PK(village_id,unit) | เพิ่มใน migration 0002 (T22); อัปเกรดทีละหน่วยต่อหมู่บ้าน เสร็จแบบ lazy เมื่อ finishes_at <= now |

ดัชนีเพิ่ม: `movements(to_village_id, status)`, `movements(from_village_id, status)`, `troops(location_village_id)`, `troops(home_village_id)`, `bot_profiles(next_think_at)`

`realm/db/session.py`:

```python
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)
@contextmanager
def session_scope() -> Iterator[Session]: ...   # commit เมื่อสำเร็จ rollback เมื่อ exception
```

`realm/settings.py`:

```python
class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://realm:realm@localhost:5432/realm"
    config_dir: str = str(Path(__file__).parent / "config")
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    model_config = SettingsConfigDict(env_prefix="REALM_", env_file=".env")
settings = Settings()
```

---

## 8. Contract: Service layer, event และ notify

### 8.1 กติการ่วม

- ทุกฟังก์ชันรับ `s: Session` ตัวแรก และ `now: datetime` (เวลาเกม) ตัวสุดท้ายก่อน `cfg`
- **ไม่ commit เอง** ผู้เรียก (API, engine, bot) เป็นคนคุม transaction
- ล็อกหมู่บ้านด้วย `SELECT ... FOR UPDATE` ก่อนแก้ ถ้าต้องล็อกหลายหมู่บ้าน เรียงตาม id น้อยไปมากเสมอ (กัน deadlock)
- ผิดกติกา → `raise GameError(code, message_th)`

```python
# services/errors.py
class GameError(Exception):
    def __init__(self, code: str, message: str): ...
# code ที่ใช้: NOT_FOUND, FORBIDDEN, INSUFFICIENT_RESOURCES, QUEUE_FULL, REQUIREMENTS_NOT_MET,
#              MAX_LEVEL, INVALID_SLOT, INVALID_TARGET, INVALID_UNITS, NO_UNITS, PROTECTED,
#              NOT_ENOUGH_CULTURE, WORLD_ENDED
```

### 8.2 `services/events.py`

```python
def schedule(s, world_id: int, etype: EventType, due_at: datetime, payload: dict) -> Event
def cancel_pending(s, world_id: int, etype: EventType, match: dict) -> int   # ลบ pending ที่ payload ตรงทุก key
```

| EventType | payload | สร้างโดย |
| --- | --- | --- |
| BUILD_COMPLETE | `{"build_queue_id": int}` | `villages.build` |
| TRAIN_TICK | `{"training_id": int}` | `training.train`, handler เอง |
| MOVEMENT_ARRIVE | `{"movement_id": int}` | `military.send_troops`, handler (ขากลับ) |
| STARVATION_CHECK | `{"village_id": int}` | `villages.after_change` |
| ROUND_END | `{}` | `worlds.create_world` |
| OASIS_RESPAWN | `{}` | `worlds.create_world`, handler เอง (T23) |

### 8.3 `services/notify.py`

```python
def notify(s, world_id: int, player_ids: list[int], kind: str, village_id: int | None = None) -> None
    # s.execute(select(func.pg_notify("game_events", json.dumps({...}))))
    # ส่งจริงตอน commit; payload: {"world_id","player_ids","kind","village_id"}
```

### 8.4 `services/villages.py`

```python
def lock_village(s, village_id: int) -> Village                 # FOR UPDATE, ไม่เจอ -> NOT_FOUND
def levels(s, village_id: int) -> dict[str, int]                # type -> level
def compute_rates(s, village: Village, now, cfg) -> tuple[Res, Res]   # (rates, capacity)
    # upkeep = troops ที่ home = village (ทุก location) + units ใน movements ที่ from = village และ status moving
def settle_village(s, village: Village, now, cfg) -> None       # อัปเดต stock + res_updated_at = now
def settle_player_culture(s, player: Player, now, cfg) -> None
def after_change(s, village: Village, now, cfg) -> None
    # เรียกตอนท้ายทุกคำสั่ง/handler ที่แตะหมู่บ้าน:
    # cancel STARVATION_CHECK เดิมของหมู่บ้าน แล้วถ้าอาหารจะหมด schedule ใหม่ ณ now + seconds_until_food_empty
def build(s, player_id: int, village_id: int, slot: int, btype: str, now, cfg) -> BuildQueue
    # ขั้นตอน: lock -> ตรวจเจ้าของ -> settle -> slot_accepts -> ห้ามซ้ำ (center) -> max_level
    #         -> requirements -> queue_limit (นับ build_queue ของหมู่บ้าน) -> ห้ามสร้าง slot ที่กำลังสร้าง
    #         -> หักทรัพยากร -> insert build_queue + schedule BUILD_COMPLETE -> after_change -> notify
def complete_build(s, build_queue_id: int, now, cfg) -> None    # ใช้โดย handler
    # lock -> settle (ก่อนเลเวลเปลี่ยน) -> upsert buildings -> ลบ build_queue -> after_change -> notify
def get_village_view(s, player_id: int, village_id: int, now, cfg) -> VillageView
def get_slot_view(s, player_id: int, village_id: int, slot: int, now, cfg) -> SlotView
def rename_village(s, player_id: int, village_id: int, name: str, now, cfg) -> None
```

### 8.5 `services/training.py`

```python
def train(s, player_id: int, village_id: int, unit: str, count: int, now, cfg) -> TrainingQueue
    # ตรวจ: count >= 1, อาคาร trained_in มีอยู่, requirements, ทรัพยากรพอสำหรับทั้งหมด (หักทั้งก้อน)
    # starts_at = max(now, finishes_at ของออร์เดอร์สุดท้ายในอาคารเดียวกัน)
    # per_unit_s = train_time_s(...); next_at = starts_at + per_unit_s; finishes_at = starts_at + per_unit_s*count
    # schedule TRAIN_TICK ที่ next_at
def tick_training(s, training_id: int, now, cfg) -> None   # handler
    # n = จำนวนที่เสร็จแล้วถึง now (อย่างน้อย 1, ไม่เกินที่เหลือ) -> settle -> เพิ่ม troops (home=location=village)
    # ถ้ายังไม่ครบ: next_at += per_unit_s * n และ schedule TRAIN_TICK ใหม่; ครบแล้วลบแถว
    # after_change -> notify
def get_train_options(s, player_id: int, village_id: int, now, cfg) -> list[TrainOption]
```

### 8.6 `services/military.py`

```python
def send_troops(s, player_id: int, from_village_id: int, to_x: int, to_y: int, mission: Mission,
                units: Units, now, cfg, catapult_target: str | None = None) -> Movement
    # ตรวจ: rally_point >= 1, validate_mission_units, มีทหารที่บ้านพอ, เป้าหมายไม่ใช่ตัวเอง,
    #       ATTACK/RAID/SCOUT: ต้องมีหมู่บ้านที่เป้าหมาย และเจ้าของไม่อยู่ในช่วงคุ้มครอง (PROTECTED)
    #       ผู้รุกที่ยังคุ้มครองอยู่ เมื่อโจมตีจะเสียการคุ้มครองทันที (protection_until = now)
    #       REINFORCE: เป้าหมายต้องเป็นหมู่บ้าน, SETTLE: ช่องต้องเป็น valley ว่าง และ CP พอ
    # settle -> หัก troops ที่บ้าน -> insert movement -> schedule MOVEMENT_ARRIVE -> after_change -> notify ทั้งสองฝ่าย
def preview_send(...same args...) -> SendPreview      # ไม่แก้ DB: distance, travel_time_s, arrive_at, carry, errors
def resolve_arrival(s, movement_id: int, now, cfg) -> None   # handler ทำตามตารางด้านล่าง
def recall_reinforcement(s, player_id: int, troop_id: int, now, cfg) -> Movement
```

พฤติกรรม `resolve_arrival` ตาม mission:

| mission | ทำอะไร |
| --- | --- |
| attack / raid | ไม่มีหมู่บ้านที่เป้าหมาย → ส่งกลับทันที ไม่มีรบ. มี → lock (เรียง id) → settle เป้าหมาย → รวม defenders จาก troops ที่ location = เป้าหมาย → `resolve_battle` (rng = `random.Random(f"{seed}:{movement.id}")`) → หักทหารที่ตาย → อัปเดตกำแพง/อาคารที่เล็ง (ลดเลเวล ถึง 0 ลบแถว ยกเว้น fixed slot) → loyalty (Phase 2) → ถ้าผู้รุกชนะ ปล้นด้วย `plunder` หัก hideout → สร้างขากลับถ้ามีผู้รอด → รายงานให้ผู้รุก เจ้าของหมู่บ้าน และเจ้าของทัพเสริม |
| scout | `resolve_scout` → สำเร็จ: รายงานทรัพยากร ทหารในหมู่บ้าน เลเวลกำแพงและอาคาร → ส่งผู้รอดกลับ. ล้มเหลว: รายงาน "หน่วยสอดแนมถูกจับได้ทั้งหมด" ฝ่ายรับได้รายงานว่าถูกสอดแนม |
| reinforce | เพิ่ม troops (home = from_village, location = เป้าหมาย) รายงานทั้งสองฝ่าย |
| settle | ช่องยัง valley ว่างและ CP ยังพอ → สร้างหมู่บ้านใหม่ (`initial_buildings`, ทรัพยากรเริ่ม 0 ยกเว้นอาหาร 0) ไม่งั้นส่งกลับ (Phase 2) |
| return | เพิ่ม units กลับ troops (home=location=from_village) → settle แล้วบวก loot (เกิน capacity ทิ้ง) |

ทุกกรณี: movement.status = 'done', เรียก `after_change` ทุกหมู่บ้านที่แตะ, notify ทุกผู้เล่นที่เกี่ยว

### 8.7 `services/reports.py`

```python
def create_report(s, player_id: int, kind: str, title: str, data: dict, now) -> Report
def list_reports(s, player_id: int, limit: int = 50, before_id: int | None = None) -> list[ReportSummary]
def get_report(s, player_id: int, report_id: int, mark_read: bool = True) -> ReportDetail
```

`data` ของรายงานรบ:

```json
{
  "mission": "raid",
  "attacker": {"player": "ชื่อ", "village": {"id": 1, "name": "...", "x": 0, "y": 0}, "tribe": "ironwild",
               "units": {"light_cavalry": 20}, "losses": {"light_cavalry": 3}},
  "defenders": [{"player": "ชื่อ", "village_id": 5, "tribe": "stonehold",
                 "units": {"spearman": 10}, "losses": {"spearman": 10}}],
  "target": {"village_id": 9, "name": "...", "x": 3, "y": -4},
  "attacker_won": true, "attack_power": 1200.0, "defense_power": 410.5,
  "loot": {"wood": 300, "stone": 300, "iron": 200, "food": 300},
  "wall": {"before": 2, "after": 2}, "catapult": null, "loyalty": null
}
```

ฝ่ายรับเห็น `attacker.units` ได้เสมอ (หลังการรบ) แต่ทัพที่กำลังเดินมาในหน้า village ไม่บอกจำนวนทหาร

### 8.8 `services/worlds.py`

```python
def current_world(s) -> World                                      # running ล่าสุด, ไม่มี -> NOT_FOUND
def world_now(world: World, real_now: datetime) -> datetime         # เรียก core.clock.game_now
def create_world(s, *, seed: int, speed: int, player_name: str, tribe: str, bot_count: int,
                 cfg, real_now: datetime) -> World
    # ปิดโลกเดิม (status='ended') -> สร้าง world -> generate_tiles + bulk insert
    # -> สุ่มบุคลิกและระดับ bot ตาม share (ใช้ random.Random(seed)) -> pick_spawns
    # -> สร้าง player มนุษย์ 1 คน + bot (ชื่อ bot สุ่มจากรายชื่อไทยในโค้ด เช่น "บ้านโคกสูง") + หมู่บ้านแรก (is_capital)
    # -> bot: production_mult จากระดับ, next_think_at = epoch + สุ่ม 0..interval
    # -> schedule ROUND_END ที่ epoch + round_days*86400/speed
def pause(s, real_now) -> World
def resume(s, real_now) -> World
def end_round(s, world_id: int, now, cfg) -> None    # handler ROUND_END: ผู้มีประชากรรวมสูงสุดชนะ, status='ended', รายงาน info ให้ทุกคน
```

### 8.9 `services/views.py` (pydantic, API ส่งออกตรงตามนี้)

```python
class Coord(BaseModel): x: int; y: int
class VillageBrief(BaseModel): id: int; name: str; x: int; y: int; is_capital: bool; population: int
class BuildingView(BaseModel): slot: int; type: str | None; level: int; name_th: str | None
class BuildQueueView(BaseModel): id: int; slot: int; type: str; target_level: int; finishes_at: datetime
class TrainingView(BaseModel): id: int; building: str; unit: str; count_total: int; count_done: int
                               next_at: datetime; finishes_at: datetime
class MovementView(BaseModel): id: int; mission: str; direction: Literal["out", "in"]
                               from_village: VillageBrief; to: Coord; to_village_name: str | None
                               arrive_at: datetime; units: Units | None   # None สำหรับทัพศัตรูขาเข้า
                               hostile: bool
class VillageView(BaseModel):
    game_now: datetime
    village: VillageBrief; tribe: str; loyalty: float
    resources: dict[str, float]; rates: dict[str, float]; capacity: dict[str, float]; hidden: float
    buildings: list[BuildingView]          # ครบ 40 slot เสมอ slot ว่าง type=None level=0
    build_queue: list[BuildQueueView]; queue_limit: int
    troops_home: Units                     # ทหารทุกเจ้าของที่อยู่ในหมู่บ้านนี้ ของเราเอง
    reinforcements_here: list[dict]        # [{"troop_ids":[..],"from_village":VillageBrief,"units":Units}]
    troops_away: list[dict]                # [{"location": VillageBrief,"units": Units}]
    training: list[TrainingView]
    movements: list[MovementView]
class CostView(BaseModel): cost: dict[str, float]; time_s: float; missing: list[str]; affordable: bool
class SlotView(BaseModel):
    slot: int; current: BuildingView | None
    upgrade: CostView | None               # None ถ้าว่างหรือตันแล้ว
    options: list[dict]                    # slot ว่าง: [{"type","name_th", **CostView}]
class TrainOption(BaseModel): unit: str; name_th: str; building: str; cost: dict[str, float]
                              time_s: float; missing: list[str]; max_affordable: int
class SendPreview(BaseModel): distance: float; travel_time_s: float; arrive_at: datetime; carry: float; errors: list[str]
class MapTile(BaseModel): x: int; y: int; kind: str; layout: str | None; oasis_type: str | None
                          village: dict | None   # {"id","name","player_id","player_name","tribe","population","is_mine","is_bot"}
class MapView(BaseModel): size: int; center: Coord; radius: int; tiles: list[MapTile]
class ReportSummary(BaseModel): id: int; kind: str; title: str; created_at: datetime; is_read: bool
class ReportDetail(ReportSummary): data: dict
class RankingRow(BaseModel): rank: int; player_id: int; name: str; tribe: str; is_bot: bool
                             villages: int; population: int
class StateView(BaseModel): game_now: datetime; paused: bool; speed: int; ends_at: datetime
                            world_id: int; player: dict; villages: list[VillageBrief]; unread_reports: int
```

---

## 9. Contract: HTTP API + WebSocket

Base path `/api` | JSON ทั้งหมด | เวลาเป็น ISO 8601 UTC
Phase 1 ไม่มี login: ผู้เล่นคือ player ที่ `is_bot = false` ของโลกปัจจุบัน (เข้าถึงผ่าน LAN/Tailscale เท่านั้น)

Error: HTTP 400 (กติกา), 404 (NOT_FOUND), 403 (FORBIDDEN), 409 (WORLD_ENDED)

```json
{"error": {"code": "INSUFFICIENT_RESOURCES", "message": "ทรัพยากรไม่พอ"}}
```

| Method | Path | Body | Response |
| --- | --- | --- | --- |
| GET | `/api/state` | — | StateView |
| GET | `/api/villages/{id}` | — | VillageView |
| PATCH | `/api/villages/{id}` | `{"name": str}` | VillageBrief |
| GET | `/api/villages/{id}/slots/{slot}` | — | SlotView |
| POST | `/api/villages/{id}/build` | `{"slot": int, "type": str}` | BuildQueueView |
| GET | `/api/villages/{id}/train-options` | — | list[TrainOption] |
| POST | `/api/villages/{id}/train` | `{"unit": str, "count": int}` | TrainingView |
| POST | `/api/villages/{id}/send/preview` | SendBody | SendPreview |
| POST | `/api/villages/{id}/send` | SendBody | MovementView |
| POST | `/api/troops/{troop_id}/recall` | — | MovementView |
| GET | `/api/map?cx=0&cy=0&r=7` | — | MapView (r สูงสุด 10) |
| GET | `/api/reports?before_id=` | — | list[ReportSummary] |
| GET | `/api/reports/{id}` | — | ReportDetail (mark read) |
| GET | `/api/ranking` | — | list[RankingRow] |
| GET | `/api/meta` | — | ข้อมูล config ที่ UI ใช้: ชื่อไทยของอาคาร/หน่วย/เผ่า, สถิติหน่วย |
| POST | `/api/admin/pause` | — | StateView |
| POST | `/api/admin/resume` | — | StateView |
| POST | `/api/admin/new-world` | `{"seed": int?, "speed": int, "player_name": str, "tribe": str, "bot_count": int}` | StateView |

SendBody: `{"to_x": int, "to_y": int, "mission": str, "units": {"unit": count}, "catapult_target": str | null}`

`realm/api/deps.py`:

```python
def get_session() -> Iterator[Session]            # session_scope ต่อ request
def get_cfg() -> GameConfig
def get_world(s) -> World
def get_now(world) -> datetime                    # world_now(world, datetime.now(timezone.utc))
def get_player(s, world) -> Player                # มนุษย์คนเดียว
```

คำสั่งที่เปลี่ยนสถานะ (POST/PATCH) ห้ามทำตอนโลก `ended` → WORLD_ENDED, ตอนหยุดเกมทำได้ปกติ

WebSocket `/ws`:
- ตอน startup แอปเปิด task หนึ่งตัวต่อ process: `psycopg.AsyncConnection` → `LISTEN game_events` → broadcast ให้ทุก socket ที่ต่ออยู่
- ข้อความที่ส่งให้ client: `{"type": "changed", "kind": "<kind>", "village_id": 12 | null}`
- client ส่ง `"ping"` ทุก 25 วินาที server ตอบ `"pong"`
- Phase 1 ส่งทุกข้อความให้ทุก client ได้ (ผู้เล่นคนเดียว) แต่ต้องกรอง `player_ids` ให้มีมนุษย์อยู่ด้วย

---

## 10. Frontend spec (`web/`)

- ไฟล์ static ล้วน เสิร์ฟโดย Caddy (production) หรือ FastAPI `StaticFiles` ที่ `/` (dev)
- ภาษาไทยทั้งหมด ฟอนต์ระบบ (`font-family: system-ui, "Noto Sans Thai", sans-serif`)
- รองรับมือถือ (กว้าง ≥ 360px) ด้วย CSS grid/flex ไม่มีเฟรมเวิร์ก CSS
- ES modules: `<script type="module" src="js/app.js">`

| ไฟล์ | หน้าที่ |
| --- | --- |
| `api.js` | `api.get(path)`, `api.post(path, body)`, `api.patch(...)`; โยน `ApiError{code,message}`; ห่อ fetch |
| `clock.js` | เก็บ offset = game_now จาก server − Date.now() ตอนได้ response; `gameNow()`, `countdown(iso)` → "1:02:03" |
| `ws.js` | ต่อ `/ws` อัตโนมัติ reconnect แบบ backoff (1,2,5,10s); `onChanged(cb)` |
| `format.js` | `fmtNum` (ปัดลง คั่นหลักพัน), `fmtDuration(s)`, `fmtTime(iso)` เวลาท้องถิ่น |
| `app.js` | hash router, แถบบน (ทรัพยากร 4 ช่อง + ปุ่มหยุด/เล่นต่อ + เวลาเกม), เมนูล่าง, ตัวเลือกหมู่บ้าน |
| `views/village.js` | `#/v/:id` ทุ่ง 18 ช่อง (grid 6×3 สีตามชนิด แสดงเลเวล + ไอคอนกำลังสร้าง), คิวก่อสร้างนับถอยหลัง, ทหารในหมู่บ้าน, ทัพเข้า-ออก |
| `views/center.js` | `#/v/:id/center` slot 19–40 แบบ grid; กดช่อง → แผงล่าง (SlotView) แสดงราคา เวลา เงื่อนไขขาด ปุ่มสร้าง/อัปเกรด; ถ้าเป็นค่ายทหาร คอกม้า โรงช่าง วัง → แสดงตัวเลือกฝึกทหาร (train-options) |
| `views/map.js` | `#/map?x=&y=` Canvas 2D 15×15 ช่อง (ช่องละ 40px, ย่อตามจอ), ลากเพื่อเลื่อน, ปุ่มลูกศร, ช่องกรอกพิกัด; สี: valley `#cfe3b4`, oasis `#7fbf6a`, mountain `#a08c74`, lake `#7fb2d9`; หมู่บ้านเราน้ำเงิน bot แดง; กดช่อง → แผงข้อมูล + ปุ่ม "ส่งทัพ" ไป `#/rally/:vid?x=&y=` |
| `views/rally.js` | `#/rally/:vid` ฟอร์ม: ช่องจำนวนแต่ละหน่วย (ปุ่ม "ทั้งหมด"), เลือกภารกิจ, พิกัด, preview (debounce 300ms) แสดงเวลาถึง/ความจุบรรทุก/ข้อผิดพลาด, ปุ่มส่ง; ด้านล่างรายการทัพเข้า-ออก และทัพเสริมพร้อมปุ่มเรียกกลับ |
| `views/reports.js` | `#/reports` รายการ (ยังไม่อ่านตัวหนา) + `#/reports/:id` ตารางหน่วย/ที่ตาย สองฝ่าย ของที่ปล้น ผลกำแพง |
| `views/ranking.js` | `#/ranking` ตารางอันดับ ไฮไลต์แถวเรา |
| `views/newgame.js` | `#/new` ฟอร์มสร้างโลก: ชื่อ เผ่า (การ์ดพร้อมคำอธิบาย) ความเร็ว จำนวน bot seed |

พฤติกรรม:
- ตัวเลขทรัพยากรบนแถบบนอัปเดตทุก 1 วินาทีจาก `resources + rates × เวลาที่ผ่าน` ตัดที่ capacity, อาหารติดลบแสดงสีแดง
- เมื่อได้ WS `changed` ของหมู่บ้านที่เปิดอยู่ → refetch หน้า (debounce 300ms)
- เมื่อ countdown ใดถึง 0 → refetch หลัง 1.5 วินาที (กันกรณี WS หลุด)
- ข้อผิดพลาดจาก API แสดงเป็น toast ด้านล่าง 4 วินาที
- เปิดครั้งแรกถ้า `/api/state` ตอบ 404 → ไป `#/new`

---

## 11. รายการ Task

### 11.1 ลำดับและการทำขนาน

| Task | ชื่อ | ขึ้นกับ | ทำขนานกับ |
| --- | --- | --- | --- |
| T00 | โครง repo | — | — |
| T01 | Config + loader | T00 | T03 |
| T02 | core: clock, economy, construction, slots | T01 | T03, T12 |
| T03 | DB models + migration + test fixture | T00 | T01, T02 |
| T04 | services: world แบบย่อ, village, build | T02, T03 | T07 |
| T05 | engine worker + BUILD_COMPLETE | T04 | T06 |
| T06 | API Phase 0 + WebSocket | T04 | T05 |
| T07 | Web: แถบบน, หมู่บ้าน, ใจกลาง, หน้าโลกใหม่ | T06 (ใช้ contract ทำก่อนได้) | T05 |
| T08 | Docker + Caddy + backup + README | T05, T06 | T07 |
| — | **ด่าน G1** | | |
| T10 | worldgen + create_world เต็ม | T02, T04 | T11, T12 |
| T11 | หน่วยทหาร + ฝึก + TRAIN_TICK | T04, T05 | T10, T12 |
| T12 | core: units, movement, combat | T02 | T10, T11 |
| T13 | ส่งทัพ + MOVEMENT_ARRIVE + รายงาน | T11, T12 | T14 |
| T14 | อาหาร อดตาย คุ้มครอง ROUND_END ranking | T11 | T13 |
| T15 | API + Web: แผนที่ จุดรวมพล รายงาน อันดับ ฝึกทหาร | T13, T14, T07 | T16 |
| T16 | Bot framework + brain (เศรษฐกิจ ฝึก ปล้น) | T13 | T15 |
| T17 | Simulator เร่งเวลา + smoke test balance | T16 | — |
| — | **ด่าน G2 (จบ MVP)** | | |
| T20–T26 | Phase 2 | G2 | ดูหัวข้อ 11.4 |

### 11.2 Phase 0 — แกนเกม

---

#### T00 · โครง repo

**เป้าหมาย** repo ที่ `uv sync`, `uv run pytest`, `uv run ruff check`, `uv run realm --help` ทำงานได้

**อ่าน** BUILD.md เท่านั้น

**สร้าง/แก้** `pyproject.toml`, `.env.example`, `.gitignore`, `README.md` (ร่าง), `realm/__init__.py`, `realm/settings.py`,
`realm/cli.py`, `__init__.py` ของทุก subpackage ในหัวข้อ 3, `tests/conftest.py` (ว่าง), `tests/test_smoke.py`,
`docs/CHANGES_REQUESTED.md`, `docs/handoff/.gitkeep`, `docker-compose.test.yml`

**รายละเอียด**
- `pyproject.toml`: name `realm`, requires-python `>=3.12`, dependencies ตามหัวข้อ 2, dev group: pytest, httpx, ruff
- `[project.scripts] realm = "realm.cli:app"`; ruff line-length 100, target py312, select `E,F,I,B,UP`
- `[tool.pytest.ini_options] testpaths=["tests"]`
- `cli.py`: typer app มีคำสั่งว่าง (พิมพ์ "not implemented"): `migrate`, `new-world`, `api`, `engine`, `bots`, `pause`, `resume`, `simulate`
- `docker-compose.test.yml`: postgres:16 port 5433, user/pass/db = `realm_test`
- `.env.example`: `REALM_DATABASE_URL=postgresql+psycopg://realm:realm@db:5432/realm`

**เกณฑ์เสร็จ** `test_smoke.py` import `realm.settings` ได้; ruff ผ่าน; `realm --help` แสดงคำสั่งครบ 8 ตัว

---

#### T01 · Config + loader

**อ่าน** `realm/settings.py`

**สร้าง/แก้** `realm/config/*.yaml` (5 ไฟล์ ตามหัวข้อ 5 ทุกค่า), `realm/core/config.py`, `realm/core/types.py`, `tests/core/test_config.py`, `tests/core/test_types.py`

**รายละเอียด**
- โหลด YAML ทั้ง 5 ไฟล์ แปลงเป็น `GameConfig` ตามหัวข้อ 5.6 เติม `key` ให้ทุก def
- `build_order` แปลง `"town_hall:3"` → `("town_hall", 3)`
- validation ทุกข้อในหัวข้อ 5.6
- `types.py` ตามหัวข้อ 6.1 ครบ

**เกณฑ์เสร็จ**
- โหลด config จริงผ่าน, มีอาคาร 16 ชนิด หน่วย 9 ชนิด เผ่า 3 บุคลิก 5
- test แต่ละ validation: สร้าง config ผิดใน `tmp_path` แล้วต้อง `ValueError`
- test `Res`: บวก ลบ scale covers clamp floor from_dict/to_dict

---

#### T02 · core: clock, economy, construction, slots

**อ่าน** `realm/core/config.py`, `realm/core/types.py`

**สร้าง/แก้** `realm/core/clock.py`, `economy.py`, `construction.py`, `slots.py`, `tests/core/test_clock.py`, `test_economy.py`, `test_construction.py`, `test_slots.py`

**รายละเอียด** ตามหัวข้อ 4, 6.2, 6.3, 6.4 ทุกฟังก์ชัน

**เกณฑ์เสร็จ** (test ต้องมีอย่างน้อยกรณีเหล่านี้)
- `field_production(0)=2`, `(1)=10`, `(10)≈206.6` (tolerance 0.1)
- `storage_capacity(0)=800`, `(1)=1000`
- `settle`: ผลิต 100/ชม. ผ่าน 30 นาที +50; ตันที่ capacity; อาหารติดลบตันที่ 0; `now < updated_at` ไม่เปลี่ยน
- `seconds_until_food_empty`: stock 100 rate −50 → 7200
- `building_cost("woodcutter", 2)` = floor(base × 1.28)
- `build_time_s` ด้วย town hall 1 กับ 11 ต่างกัน 1.5 เท่า; speed 10 เร็วขึ้น 10 เท่า; ขั้นต่ำ 1
- `missing_requirements("stable", {"barracks": 3})` บอกว่าขาดโรงตีเหล็ก
- `field_types_for_layout("3-3-3-9")` มี farm 9 ช่อง slot 10–18
- `game_now` ตอนหยุดเกมคงที่, เล่นต่อแล้วเดินต่อจากจุดเดิม

---

#### T03 · DB models + migration + test fixture

**อ่าน** หัวข้อ 7, `realm/settings.py`

**สร้าง/แก้** `realm/db/models.py`, `realm/db/session.py`, `alembic.ini`, `realm/db/migrations/env.py`, `script.py.mako`, `versions/0001_initial.py`, `tests/conftest.py`, `tests/services/test_db_smoke.py`, เติมคำสั่ง `migrate` ใน `realm/cli.py`

**รายละเอียด**
- Model ชื่อ class: `World, Player, BotProfile, Tile, Village, Building, BuildQueue, Troop, TrainingQueue, Movement, Event, Report`
- คอลัมน์ ชนิด ค่า default index ตรงหัวข้อ 7 ทุกตัว
- migration เขียนเอง (ไม่ autogenerate ใน CI) ให้ตรงกับ models
- `realm migrate` = `alembic upgrade head` ผ่าน API ของ alembic
- `tests/conftest.py`:
  - อ่าน `REALM_TEST_DATABASE_URL` (default `postgresql+psycopg://realm_test:realm_test@localhost:5433/realm_test`)
  - fixture `db_engine` (session scope): drop schema → upgrade head
  - fixture `s`: connection + transaction ที่ rollback หลังจบ test (ใช้ `join_transaction_mode="create_savepoint"`)
  - fixture `cfg`: `load_config()`
  - fixture `t0`: `datetime(2026, 1, 1, tzinfo=timezone.utc)`
  - ถ้าต่อ DB ไม่ได้ ให้ `pytest.skip` test ที่ใช้ DB พร้อมข้อความบอกให้รัน `docker compose -f docker-compose.test.yml up -d`

**เกณฑ์เสร็จ** migration ขึ้นได้บน DB ว่าง; test insert world → player → village → building แล้ว query กลับได้; unique (world,x,y) ทำงาน

---

#### T04 · services: world แบบย่อ, village, build

**อ่าน** `realm/core/*.py`, `realm/db/models.py`, `realm/db/session.py`, `tests/conftest.py`

**สร้าง/แก้** `realm/services/errors.py`, `events.py`, `notify.py`, `worlds.py` (Phase 0), `villages.py`, `views.py`, `tests/services/test_villages.py`, `tests/services/test_worlds.py`

**รายละเอียด**
- ทำตามหัวข้อ 8.1–8.4, 8.8, 8.9
- `create_world` Phase 0: ยังไม่ gen แผนที่ทั้งโลก สร้างแค่ tile (0,0) valley `4-4-4-6`, ผู้เล่น 1 คน หมู่บ้าน 1 แห่ง, ไม่มี bot (T10 จะแทนที่)
- `get_village_view` ต้องคืนครบ 40 slot
- ฟิลด์ที่ยังไม่มีระบบ (training, movements, troops) คืนลิสต์ว่าง
- `pause`, `resume`, `current_world`, `world_now` ใช้งานได้จริง

**เกณฑ์เสร็จ**
- สร้างโลก → หมู่บ้านมีทรัพยากรเริ่ม 750, town_hall เลเวล 1, ทุ่ง 18 ช่องเลเวล 0
- `build` ทุ่ง slot 1 → ทรัพยากรลดตามราคา, มี build_queue 1 แถว, มี event BUILD_COMPLETE ที่เวลาถูก
- สร้างแถวที่สองตอน town_hall < 10 → QUEUE_FULL
- ทรัพยากรไม่พอ → INSUFFICIENT_RESOURCES; ขาดเงื่อนไข → REQUIREMENTS_NOT_MET; slot ผิดชนิด → INVALID_SLOT
- `complete_build` → เลเวลขึ้น, rates ของ view เปลี่ยน, ทรัพยากร ณ เวลาเสร็จถูกต้อง (settle ก่อนเปลี่ยน)
- ผู้เล่นอื่นสั่งหมู่บ้านเรา → FORBIDDEN

---

#### T05 · engine worker + BUILD_COMPLETE

**อ่าน** `realm/services/*.py`, `realm/db/models.py`, `realm/db/session.py`, `realm/core/types.py`

**สร้าง/แก้** `realm/engine/worker.py`, `realm/engine/handlers.py`, เติมคำสั่ง `engine` ใน `realm/cli.py`, `tests/engine/test_worker.py`

**รายละเอียด**

```python
# handlers.py
Handler = Callable[[Session, Event, GameConfig], None]
HANDLERS: dict[EventType, Handler] = {EventType.BUILD_COMPLETE: handle_build_complete, ...}
# handler ใช้ event.due_at เป็น now เสมอ (ไม่ใช่เวลาปัจจุบัน)

# worker.py
def process_next(s: Session, world: World, now: datetime, cfg) -> bool
    # SELECT events WHERE world_id AND status='pending' AND due_at <= now
    #   ORDER BY due_at, id LIMIT 1 FOR UPDATE SKIP LOCKED
    # ไม่มี -> False; มี -> HANDLERS[type](s, ev, cfg); ev.status='done' -> True
def run_forever(cfg, idle_sleep: float = 0.5) -> None
    # วน: โหลดโลก running (ข้ามถ้า paused) -> ทีละ event ต่อ transaction
    # handler โยน exception: rollback แล้วเปิด transaction ใหม่ตั้ง status='failed', attempts+1, last_error
    # ไม่มีงาน -> sleep(idle_sleep); จับ SIGTERM ให้ปิดสวย
```

- handler ที่ยังไม่มีระบบ (TRAIN_TICK ฯลฯ) ให้ลงทะเบียนเป็นฟังก์ชันที่ `raise NotImplementedError` (T11, T13, T14 จะเติม)
- logging ระดับ INFO: ทุก event ที่ทำเสร็จ (type, id, ใช้เวลากี่ ms)

**เกณฑ์เสร็จ**
- สั่งสร้าง → เรียก `process_next` ด้วย now ก่อนถึงเวลา → False; หลังเวลา → True และเลเวลขึ้น
- event 3 ตัวเวลาต่างกัน ประมวลผลตามลำดับเวลา
- handler พัง → event เป็น failed และ worker ไม่ล้ม

---

#### T06 · API Phase 0 + WebSocket

**อ่าน** `realm/services/*.py`, `realm/db/session.py`, `realm/core/config.py`

**สร้าง/แก้** `realm/api/main.py`, `deps.py`, `schemas.py`, `ws.py`, `routes/state.py`, `routes/villages.py`, `routes/admin.py`, เติมคำสั่ง `api`, `new-world`, `pause`, `resume` ใน `realm/cli.py`, `tests/api/test_api_phase0.py`

**รายละเอียด**
- endpoint ตามหัวข้อ 9 เฉพาะ: state, villages (GET, PATCH, slots, build), meta, admin ทั้ง 3
- exception handler แปลง `GameError` → JSON error ตามหัวข้อ 9
- `create_app(serve_static: bool = True)`: mount `web/` ที่ `/` เมื่อ serve_static
- WebSocket ตามหัวข้อ 9 (LISTEN ด้วย psycopg async; แปลง URL ตัด `+psycopg` ออก)
- `realm new-world --speed 1 --name ผู้เล่น --tribe stonehold --bots 30 --seed 42`

**เกณฑ์เสร็จ** test ด้วย `fastapi.testclient.TestClient`: new-world → state → village view 40 slot → build สำเร็จ → build ซ้ำได้ error 400 code QUEUE_FULL → pause แล้ว state.paused = true

---

#### T07 · Web Phase 0

**อ่าน** หัวข้อ 9, 10 (ไม่ต้องอ่านโค้ด Python)

**สร้าง/แก้** `web/index.html`, `web/css/style.css`, `web/js/api.js`, `clock.js`, `ws.js`, `format.js`, `app.js`, `views/village.js`, `views/center.js`, `views/newgame.js`

**รายละเอียด** ตามหัวข้อ 10 เฉพาะไฟล์ข้างบน; `center.js` ยังไม่ต้องทำส่วนฝึกทหาร (T15)

**เกณฑ์เสร็จ** (ทดสอบมือกับ API จริง) สร้างโลกจากหน้าเว็บได้; เห็นทุ่งและใจกลางหมู่บ้าน; สร้างอาคารได้; นับถอยหลังแล้วเลเวลขึ้นเองโดยไม่ต้องรีเฟรช; ตัวเลขทรัพยากรวิ่ง; ใช้บนมือถือได้; ไม่มี error ใน console

---

#### T08 · Docker + Caddy + backup + README

**อ่าน** `pyproject.toml`, `realm/cli.py`, `realm/settings.py`

**สร้าง/แก้** `docker/Dockerfile`, `docker/Caddyfile`, `docker-compose.yml`, `scripts/backup.sh`, `README.md`

**รายละเอียด**
- Dockerfile: `python:3.12-slim` + copy uv binary จาก `ghcr.io/astral-sh/uv`, `uv sync --frozen --no-dev`, user ไม่ใช่ root
- compose services: `db` (postgres:16, volume `pgdata`, healthcheck `pg_isready`), `migrate` (one-shot, depends db healthy),
  `api`, `engine`, `bots` (depends migrate completed_successfully, `restart: unless-stopped`), `caddy` (port 8080:80, เสิร์ฟ `/srv/web`, proxy `/api/*` และ `/ws` ไป `api:8000`)
- service `bots` ใน Phase 0 ให้ใส่ไว้แต่ comment ออก
- `backup.sh`: `pg_dump` จาก container db แบบ gzip ลง `./backups/realm-YYYYmmdd-HHMM.sql.gz` เก็บ 14 ไฟล์ล่าสุด พร้อมตัวอย่างบรรทัด crontab
- README: ติดตั้ง Docker, `cp .env.example .env`, `docker compose up -d`, สร้างโลก (`docker compose exec api realm new-world ...`), เข้าเว็บ `http://<ip>:8080`, เข้าจากนอกบ้านผ่าน Tailscale, วิธีรัน test, วิธี restore backup

**เกณฑ์เสร็จ** `docker compose up -d` บนเครื่องว่างแล้วเล่นได้จากเบราว์เซอร์อีกเครื่องใน LAN

---

### ด่าน G1 (ต้องผ่านก่อนเริ่ม Phase 1)

- [ ] เปิดเกมทิ้งไว้ 24 ชั่วโมงที่ speed 10 ทรัพยากรไม่เกินคลัง ไม่ติดลบ ไม่มี event failed
- [ ] ปิด container engine 10 นาทีแล้วเปิดใหม่ งานค้างเสร็จครบตามลำดับเวลา
- [ ] หยุดเกม 10 นาทีแล้วเล่นต่อ เวลาที่เหลือของคิวไม่ลด
- [ ] test ทั้งหมดผ่าน, ruff ผ่าน

### 11.3 Phase 1 — MVP เล่นคนเดียวกับ bot

---

#### T10 · worldgen + create_world เต็ม

**อ่าน** `realm/core/config.py`, `types.py`, `slots.py`, `realm/services/worlds.py`, `realm/db/models.py`

**สร้าง/แก้** `realm/core/worldgen.py`, `realm/services/worlds.py` (แทน create_world), `tests/core/test_worldgen.py`, `tests/services/test_create_world.py`

**รายละเอียด** หัวข้อ 6.8 และ 8.8; insert tiles แบบ bulk (`s.execute(insert(Tile), rows)`); ชื่อ bot สุ่มจากลิสต์ไทยอย่างน้อย 60 ชื่อในโค้ด ไม่ซ้ำกันในโลกเดียว; ชื่อหมู่บ้านแรก = "บ้านของ<ชื่อผู้เล่น>"

**เกณฑ์เสร็จ** seed เดิมได้โลกเดิมทุกช่อง; สัดส่วนชนิดช่องห่างจาก weight ไม่เกิน 2%; ผู้เล่นอยู่ (0,0); bot 30 ตัวอยู่บน valley ห่างกัน ≥ 3; bot ระดับยากห่างผู้เล่น ≥ 15; สร้างโลก 101×101 เสร็จใน < 5 วินาที

---

#### T11 · หน่วยทหาร + ฝึก + TRAIN_TICK

**อ่าน** `realm/core/*.py`, `realm/services/villages.py`, `events.py`, `views.py`, `realm/engine/handlers.py`, `realm/db/models.py`

**สร้าง/แก้** `realm/core/units.py` (เฉพาะฟังก์ชันที่ไม่เกี่ยวกับ movement: cost, train_time, upkeep, defense, requirements, army_value, carry, speed), `realm/services/training.py`, `realm/services/villages.py` (เติม upkeep ใน `compute_rates`, เติม troops_home/training ใน view), `realm/engine/handlers.py` (TRAIN_TICK), `tests/core/test_units.py`, `tests/services/test_training.py`

> ถ้า T12 เสร็จก่อนและมี `units.py` แล้ว ให้เพิ่มเฉพาะฟังก์ชันที่ยังขาด ห้ามแก้ของเดิม

**เกณฑ์เสร็จ** ฝึก 5 ตัว → เสร็จทีละตัวตาม per_unit_s; worker หยุดไป 1 ชม. แล้ว tick เดียวได้หลายตัว; ออร์เดอร์ที่สองในค่ายเดียวกันเริ่มต่อจากออร์เดอร์แรก; ค่าอาหารลดตาม upkeep; เผ่า ironwild จ่ายถูกกว่า 20%; ขาดอาคาร → REQUIREMENTS_NOT_MET

---

#### T12 · core: units, movement, combat (pure)

**อ่าน** `realm/core/config.py`, `types.py`

**สร้าง/แก้** `realm/core/units.py` (ทั้งไฟล์ตามหัวข้อ 6.5), `realm/core/movement.py`, `realm/core/combat.py`, `tests/core/test_movement.py`, `tests/core/test_combat.py`

> ถ้า T11 เสร็จก่อน ให้รวมไฟล์ `units.py` โดยไม่เปลี่ยน signature ที่มีอยู่

**เกณฑ์เสร็จ** (ตัวเลขตรวจด้วยมือแล้วเขียนเป็น test)
- distance บน torus: (−50,0) กับ (50,0) = 1
- travel_time: ม้าเบา 14 ช่อง/ชม. ไป 7 ช่องที่ 1x = 1800 วินาที; ทัพผสมใช้ตัวช้าสุด; windriders ม้าเร็วขึ้น 20%
- ทหารดาบ 100 ตัว (A=4000) โจมตีหมู่บ้านว่างกำแพง 0 → D=10, ชนะ, เสีย int(100×(10/4000)^1.5+0.5) = 0
- ทหารหอก 100 ตัวรับม้าเบา 50 ตัว: D_cav=5000 > A=3000 ฝ่ายรับชนะ ตัวเลข losses ตรงสูตร
- RAID เสียน้อยกว่า ATTACK ทั้งสองฝ่ายเมื่อกำลังเท่าเดิม
- stonehold กำแพง 10 ได้โบนัส 1+0.03×1.5×10 = 1.45
- ram 30 ตัวรอด vs กำแพง 5: 5→4 ใช้ 10, 4→3 ใช้ 8, 3→2 ใช้ 6, 2→1 ใช้ 4 (เหลือ 2) 1→0 ใช้ 2 → กำแพง 0
- plunder: stock 1000/50/1000/1000 hidden 0 carry 1000 → หิน 50 ที่เหลือแบ่ง 316/316/316 (ปัดลง)
- scout: 10 vs 0 สำเร็จไม่เสีย; 10 vs 5 สำเร็จเสีย int(10×0.5^1.5+0.5)=4; 10 vs 10 ล้มเหลวตายหมด
- chief: rng seed เดิมได้ loyalty_damage เดิม

---

#### T13 · ส่งทัพ + MOVEMENT_ARRIVE + รายงาน

**อ่าน** `realm/core/*.py`, `realm/services/*.py`, `realm/engine/handlers.py`, `realm/db/models.py`

**สร้าง/แก้** `realm/services/military.py`, `realm/services/reports.py`, `realm/services/villages.py` (เติม movements, troops_away, reinforcements_here ใน view), `realm/engine/handlers.py` (MOVEMENT_ARRIVE), `tests/services/test_military.py`

**รายละเอียด** หัวข้อ 8.6, 8.7; mission `settle` ให้ตรวจแล้ว `raise GameError("INVALID_UNITS", "ยังไม่เปิดใช้")` ไว้ก่อน (Phase 2); catapult_target ต้องเป็นอาคารที่มีในหมู่บ้านเป้าหมาย ไม่งั้นสุ่มเป้าจากอาคาร center ที่มี

แบ่งครึ่งได้ (ถ้า context ไม่พอ): T13a = send_troops + preview + return; T13b = resolve_arrival การรบ สอดแนม เสริมกำลัง + รายงาน

**เกณฑ์เสร็จ**
- ส่งปล้น → ทหารหายจากบ้าน → ถึงเวลาเกิดการรบ → ขากลับพร้อมของ → ของเข้าคลัง (เกินคลังทิ้ง)
- ทัพเสริมช่วยป้องกันได้จริง และตายตามสัดส่วนเมื่อแพ้
- สอดแนมสำเร็จได้รายงานทรัพยากร; ล้มเหลวฝ่ายรับได้รายงาน
- โจมตีผู้เล่นที่คุ้มครองอยู่ → PROTECTED; ผู้รุกที่คุ้มครองอยู่เสียการคุ้มครองเมื่อส่งโจมตี
- ห้องลับกันของไม่ให้ถูกปล้น
- ล็อกหมู่บ้านเรียงตาม id (test สองทัพถึงเวลาเดียวกันไม่ deadlock)

---

#### T14 · อาหาร อดตาย คุ้มครอง ROUND_END ranking

**อ่าน** `realm/core/economy.py`, `realm/services/villages.py`, `worlds.py`, `reports.py`, `realm/engine/handlers.py`

**สร้าง/แก้** `realm/services/villages.py` (`after_change` + handle starvation), `realm/services/worlds.py` (`end_round`), `realm/services/ranking.py`, `realm/engine/handlers.py` (STARVATION_CHECK, ROUND_END), `tests/services/test_starvation.py`, `tests/services/test_round.py`

**รายละเอียด**
- STARVATION_CHECK: settle; ถ้าอาหาร ≤ 0 และอัตราอาหารติดลบ → ฆ่าทหารที่ home = หมู่บ้านนี้ เรียงจาก upkeep ต่อตัวสูงสุด อยู่บ้านก่อนอยู่นอกบ้าน ทีละตัวจนอัตราอาหาร ≥ 0 → รายงาน info "ทหารอดอาหารตาย" → after_change
- ทหารในขบวนเดินทางไม่ถูกฆ่า (นับ upkeep แต่ข้าม) ถ้าฆ่าทหารในบ้านหมดแล้วยังติดลบ ปล่อยไว้ (อาหารค้างที่ 0)
- ranking: เรียงประชากรรวม → จำนวนหมู่บ้าน → id

**เกณฑ์เสร็จ** ฝึกทหารจนอาหารติดลบ → ถึงเวลาที่คำนวณ ทหาร upkeep สูงตายก่อน; ROUND_END ประกาศผู้ชนะและห้ามสั่งงานต่อ (WORLD_ENDED); ranking เรียงถูก

---

#### T15 · API + Web: แผนที่ จุดรวมพล รายงาน อันดับ ฝึกทหาร

**อ่าน** หัวข้อ 9–10, `realm/api/main.py`, `deps.py`, `routes/villages.py`, `realm/services/views.py`, `web/js/app.js`, `api.js`, `views/center.js`

**สร้าง/แก้** `realm/api/routes/military.py`, `routes/world.py`, `routes/reports.py`, `routes/villages.py` (train, train-options), `realm/api/main.py` (include routers), `realm/services/` เฉพาะ `get_map` ใน `worlds.py`, `web/js/views/map.js`, `rally.js`, `reports.js`, `ranking.js`, `center.js` (ส่วนฝึกทหาร), `app.js` (เมนู + badge รายงานใหม่), `tests/api/test_api_phase1.py`

แบ่งครึ่งได้: T15a = API + test; T15b = Web

**เกณฑ์เสร็จ** endpoint Phase 1 ครบตามหัวข้อ 9 และมี test ทุกตัว; เล่นวงจร ฝึก → ดูแผนที่ → ส่งปล้น → อ่านรายงาน ได้จากเว็บล้วน

---

#### T16 · Bot framework + brain

**อ่าน** `realm/core/*.py`, `realm/services/*.py` (ดู signature), `realm/db/models.py`, `realm/config/bots.yaml`

**สร้าง/แก้** `realm/bot/worker.py`, `brain.py`, `modules.py`, `memory.py`, เติมคำสั่ง `bots` ใน `realm/cli.py`, `tests/bot/test_brain.py`, `tests/bot/test_worker.py`; เปิด service `bots` ใน `docker-compose.yml`

**รายละเอียด**

```python
# worker.py
def think_due_bots(s, world: World, now: datetime, cfg, rng: random.Random, limit: int = 10) -> int
    # SELECT bot_profiles JOIN players WHERE next_think_at <= now ORDER BY next_think_at LIMIT n FOR UPDATE SKIP LOCKED
    # แต่ละตัว: savepoint -> brain.think(...) -> next_think_at = now + think_interval_min*60/speed
    # exception -> log + ข้าม (ตั้ง next_think_at เหมือนเดิม)
def run_forever(cfg) -> None    # วนทุก 1 วินาที ข้ามโลกที่หยุด

# brain.py
@dataclass
class Action:
    kind: str          # "build" | "train" | "raid"
    score: float
    params: dict
    def execute(self, s, bot: Player, village: Village, now, cfg) -> None   # เรียก services เท่านั้น

def think(s, bot: Player, profile: BotProfile, now, cfg, rng) -> list[Action]
    # 1. อัปเดต memory จากรายงานใหม่ของ bot (memory.update_from_reports)
    # 2. ทุกหมู่บ้านของ bot: settle -> รวม candidate จากทุก module -> คูณ weight บุคลิก
    # 3. เรียง score มากไปน้อย ทำทีละตัวไม่เกิน max_actions (ข้ามแต่ละตัวด้วยโอกาส skip_chance)
    #    ทำแล้ว GameError -> ข้ามไปตัวถัดไป (เช่นทรัพยากรไม่พอหลังทำตัวก่อน)
    # 4. คืนรายการที่ทำสำเร็จ (ใช้ใน test/log)
```

Module (`modules.py`) แต่ละตัวคืน `list[Action]` ที่ score > 0:

| module | weight | สูตร score |
| --- | --- | --- |
| `field_upgrades` | economy | ทุกทุ่งที่อัปได้: `100 × gain_per_hour / cost.total() × need` โดย need = ค่าเฉลี่ยอัตราผลิต 4 ชนิด ÷ อัตราของชนิดนั้น (clamp 0.5–2) ถ้าอาหารสุทธิ < 10% ของผลผลิตรวม ทุ่งอาหาร need = 3 |
| `storage` | storage | ไม้/หิน/เหล็กชนิดใด ≥ 85% คลัง → warehouse score 5; อาหาร ≥ 85% → granary score 5 |
| `build_order` | build | ขั้นแรกใน build_order ที่ยังไม่ถึงและเงื่อนไขครบ → score 3 (slot: อาคารเดิม หรือ slot center ว่างแรก) |
| `training` | military | target = ผลผลิตรวม/ชม. × army_hours × speed; ถ้า army_value < target → score `4 × (1 − value/target)`; เลือกหน่วยจาก unit_mix ที่ฝึกได้ (สุ่มตามน้ำหนัก ถ้าฝึกไม่ได้ใช้ spearman) จำนวน = ใช้ไม่เกิน 50% ของทรัพยากรตอนนี้ |
| `raid` | raid | ถ้ามีหน่วยที่ carry > 0 อยู่บ้าน ≥ 5 ตัว และ raid_radius > 0: เป้า = หมู่บ้านอื่นในรัศมีที่ไม่คุ้มครอง ไม่ใช่ของตัวเอง; คะแนนเป้า = `expected_loot / distance` (expected_loot = last_loot จาก memory หรือ 0.5 × carry) × (1 + grudge ของเจ้าของเป้า); ข้ามเป้าที่ fails ≥ 2 ใน 24 ชม. เกม; score action = `3 × min(1, expected_loot/carry)` ส่งหน่วย carry > 0 ทั้งหมดที่อยู่บ้าน |

ก่อน `active_from_day` ของบุคลิก: weight military และ raid คูณ 0.3

`memory.py`: โครงสร้าง JSON

```json
{
  "last_report_id": 0,
  "targets": {"<village_id>": {"last_raid_at": "iso", "last_loot": 0, "last_losses": 0, "fails": 0, "fail_times": []}},
  "grudges": {"<player_id>": 0.0}
}
```

- อ่านรายงานรบที่ id > last_report_id: ถ้า bot เป็นผู้รุก อัปเดต targets (ชนะ → last_loot = ผลรวมของที่ได้, fails = 0; แพ้ → fails + 1); ถ้า bot เป็นผู้ถูกโจมตี → grudges[ผู้รุก] += 1
- grudge ลดลง 10% ต่อวันเกม

**เกณฑ์เสร็จ**
- bot ชาวนาบนหมู่บ้านใหม่ คิด 1 รอบ → สั่งสร้างทุ่งหรือคลังอย่างน้อย 1 อย่าง
- bot นักปล้นมีม้าเบา 10 ตัวและมีหมู่บ้านอื่นในรัศมี → ส่ง raid
- ระดับ easy ทำไม่เกิน 1 action; hard ไม่เกิน 6
- memory อัปเดตถูกจากรายงานจำลอง
- bot ไม่เคยแก้ตาราง villages/troops ตรง (ตรวจด้วยการ mock services หรือ grep ใน test)

---

#### T17 · Simulator เร่งเวลา

**อ่าน** `realm/engine/worker.py`, `realm/bot/worker.py`, `realm/services/worlds.py`, `ranking.py`

**สร้าง/แก้** `realm/sim/simulate.py`, เติมคำสั่ง `simulate` ใน `realm/cli.py`, `tests/test_simulate.py`

**รายละเอียด**

```
realm simulate --days 5 --speed 1 --seed 42 --bots 30 [--with-player-idle] [--report out.csv]
```

- ใช้ DB จริง (โลกใหม่) แต่ไม่ใช้นาฬิกาจริง: วน `now = min(event ถัดไป, bot ถัดไปที่ต้องคิด)` → `process_next` / `think_due_bots` จนถึงวันที่กำหนด
- ทุก 12 ชม. เกม พิมพ์ตาราง: วัน, ประชากรเฉลี่ยแยกบุคลิก, จำนวนทหารรวม, จำนวนการปล้น, event failed
- `--report` เขียน CSV ของแต่ละ snapshot

**เกณฑ์เสร็จ** จำลอง 5 วันเกม 30 bot เสร็จในเวลาจริง < 10 นาทีบนเครื่อง 2 core; ไม่มี event failed; ประชากรเฉลี่ยทุกบุคลิกโตขึ้นจากวันแรก; มีการปล้นเกิดขึ้น > 0 ครั้ง

---

### ด่าน G2 (จบ MVP)

- [ ] เล่นจบหนึ่งรอบที่ speed 10 (6 วันจริง) ได้โดยไม่ต้องแก้ DB มือ
- [ ] bot 30 ตัวทำงานได้ CPU เฉลี่ย < 30% บนเครื่อง 2 core
- [ ] simulator 5 วันเกมผ่านเกณฑ์ T17
- [ ] ผู้เล่นแพ้หรือชนะ bot ได้จริง (bot นักปล้นมาปล้นผู้เล่นที่ไม่สร้างทหาร)

### 11.4 Phase 2 — ครบรอบเกม (สเปกระดับ task, ลงรายละเอียดเพิ่มก่อนแจกงาน)

| Task | งาน | ไฟล์หลัก | เกณฑ์เสร็จ |
| --- | --- | --- | --- |
| T20 | แต้มวัฒนธรรม + ผู้บุกเบิก + mission settle + สลับหมู่บ้านใน UI | services/military.py, villages.py, web app.js | ตั้งหมู่บ้านที่ 2 ได้เมื่อ CP ถึง 2,000 และผู้บุกเบิก 3 คนหายไป |
| T21 | ผู้นำ ความภักดี ยึดเมือง (ห้ามยึดเมืองหลวง) | services/military.py, combat (ใช้ loyalty_damage) | loyalty ≤ 0 → หมู่บ้านเปลี่ยนเจ้าของ ทหารเจ้าของเก่าในหมู่บ้านถูกส่งกลับ/ตาย, ฟื้น loyalty ตามเลเวลวัง |
| T22 | โรงตีเหล็กอัปเกรดหน่วย +1.5%/เลเวล (ตารางใหม่ `unit_upgrades` ผ่าน migration ใหม่) | migration 0002, core/combat, services | ผลอัปเกรดเข้าสูตรรบ |
| T23 | โอเอซิส: สัตว์ป่า NPC, ยึดด้วย attack, โบนัส +25% ให้หมู่บ้านในรัศมี 3 | worldgen (animals), military, economy | ปล้นสัตว์ได้, ยึดแล้วอัตราผลิตเพิ่ม, สัตว์เกิดใหม่ทุก 12 ชม. เกม |
| T24 | Bot: เต่า/นักขยาย/ขุนศึก เต็มรูป, module `defend` (hard: เห็นทัพเข้าใน 15 นาที → ส่งทหารบุกหลบไปปล้นเป้าใกล้สุด + ใช้ทรัพยากรให้หมด), module `expand`, ขุนศึกยึดเมือง | bot/modules.py | simulator 20 วัน: นักขยายมีเฉลี่ย ≥ 3 หมู่บ้าน, ขุนศึกยึดเมืองได้ ≥ 1 |
| T25 | ตลาด: ส่งทรัพยากรระหว่างหมู่บ้านตัวเอง (mission `trade`), แลกกับ NPC อัตรา 1:1 หักค่าธรรมเนียม 10% | services/market.py, web | ส่งของถึงตามเวลา, แลกได้ |
| T26 | Endgame: วันที่ 41 ซากโบราณ 5 แห่ง + ผู้พิทักษ์ NPC, ยึดได้สิทธิ์สร้าง `monument` (เลเวล 1–50), ใครถึง 50 ก่อนชนะ | worldgen, buildings.yaml, services, ROUND_END | bot ขุนศึกแข่งยึดซาก, ชนะด้วยอนุสาวรีย์ได้ |

### 11.5 Phase 3 — Multiplayer (โครงร่าง)

- ระบบบัญชี: ตาราง `accounts` (username, password hash ด้วย argon2), session cookie, `get_player` อ่านจาก session
- หลายผู้เล่นมนุษย์ต่อโลก, สมัครเข้าโลกที่กำลังเล่น (เกิดที่ขอบรัศมีปัจจุบัน)
- พันธมิตร: ตาราง `alliances`, `alliance_members`, เสริมกำลังกันได้ แชทพันธมิตร
- WS กรองข้อความตาม player_ids จริง
- rate limit ต่อผู้เล่น, ตรวจคำสั่งซ้ำซ้อน, log สำหรับตรวจโกง
- ปิดปุ่มหยุดเกมเมื่อมีมนุษย์ > 1 คน

---

## 12. Prompt สำหรับ sub-agent

คัดลอกแล้วแทนค่าใน `{...}`:

```
คุณคือนักพัฒนา Python อาวุโสในโปรเจกต์เกม "Realm of Villages"

เอกสาร BUILD.md ด้านล่างคือสเปกหลัก อ่านหัวข้อ 0 (กฎเหล็ก) และ contract หัวข้อ 4–10 ให้ครบก่อนเขียนโค้ด

งานของคุณ: Task {TASK_ID} · {ชื่อ task}
ทำตามหัวข้อ 11 ของ task นี้ทุกข้อ แก้เฉพาะไฟล์ในช่อง "สร้าง/แก้"

ไฟล์ที่มีอยู่แล้วที่ต้องใช้ (อย่าแก้ ยกเว้นอยู่ในช่องสร้าง/แก้):
{วางเนื้อหาไฟล์ตามช่อง "อ่าน" ทีละไฟล์ โดยขึ้นต้นด้วย ### path/to/file.py}

รูปแบบคำตอบ:
1. รายการไฟล์ที่สร้าง/แก้
2. เนื้อหาเต็มของทุกไฟล์ ในรูป
   ### path/to/file.py
   ```python
   ...
   ```
3. คำสั่งรัน test ที่เกี่ยวข้อง
4. เนื้อหาไฟล์ docs/handoff/{TASK_ID}.md
5. ถ้า contract ไม่พอหรือขัดกัน: หยุด เขียนคำถามสั้นๆ ไว้ใน docs/CHANGES_REQUESTED.md แล้วทำส่วนที่ทำได้

ห้ามแต่งฟังก์ชัน ตาราง หรือ endpoint ที่ไม่มีใน contract
ห้ามใส่ตัวเลข balance ในโค้ด อ่านจาก cfg เสมอ

--- BUILD.md ---
{วาง BUILD.md ทั้งไฟล์}
```

เคล็ดลับการคุมงาน:
- ถ้า agent ตอบไม่ครบไฟล์ ให้สั่ง "ส่งเฉพาะไฟล์ X ต่อจากที่ค้าง" แทนการขอใหม่ทั้งหมด
- ถ้า test ไม่ผ่าน ส่งกลับไปพร้อม output ของ pytest (ตัดเหลือส่วน error) ให้ agent ตัวเดิมแก้
- รวมงานทีละ task แล้วรัน test ทั้งชุด ก่อนแจก task ที่ขึ้นกับมัน
- task ที่ขนานกันและแตะไฟล์เดียวกัน (T11/T12 → `units.py`) ให้ merge มือ หรือทำตามลำดับ

---

## 13. คำสั่งที่ใช้บ่อย

```bash
# dev บนเครื่อง
uv sync
docker compose -f docker-compose.test.yml up -d       # postgres สำหรับ test
uv run pytest -q
uv run ruff check . && uv run ruff format .

# รันแบบ dev ไม่ใช้ docker (ต้องมี postgres)
uv run realm migrate
uv run realm new-world --speed 10 --name ผู้เล่น --tribe stonehold --bots 30 --seed 42
uv run realm api        # http://localhost:8000
uv run realm engine
uv run realm bots

# home server
docker compose up -d --build
docker compose exec api realm new-world --speed 5 --name ผู้เล่น --tribe windriders --bots 30
docker compose logs -f engine bots
./scripts/backup.sh

# ปรับ balance แล้วจำลองดูผล
uv run realm simulate --days 5 --speed 1 --seed 7 --bots 30 --report sim.csv
```
