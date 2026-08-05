# Handoff: OPPP Manage Dashboard

เอกสารนี้สรุปงานล่าสุดที่ Claude ทำไว้ (ต่อจากงานเดิมของ Codex) เพื่อให้ agent ตัวถัดไป (Codex หรือ Claude) รับช่วงต่อได้ทันที

**อัปเดตล่าสุด:** 2026-08-05 — เปลี่ยนเกณฑ์การนำเข้าข้อมูลให้เหลือเฉพาะรายการ PP/FS และใช้คอลัมน์ `ยอดชดเชยทั้งสิ้น` เป็นตัวเลขเป้าหมาย

## เกณฑ์การนำเข้าข้อมูล (สำคัญที่สุด — เปลี่ยน 2026-08-05)

ที่มา: แฟ้ม `oppp_frequent_compensation_summary.xlsx` ชีต `กติกาและสูตรรวม` ที่ผู้ใช้ยืนยัน

1. **กรองเฉพาะแถวที่มีเงินใน PP หรือ FS** (`PP > 0 or FS > 0`) แถวที่ชดเชยมาจากกองทุนอื่น (HC, DRUG, AE ฯลฯ) ไม่เกี่ยวกับการวิเคราะห์ PP/FS จึงถูกตัดทิ้งตั้งแต่ `parse_report()` ไม่ให้เข้าฐานข้อมูลเลย
   - ผลจริงกับข้อมูลปีงบ 2569 ทั้งปี: อ่านได้ 9,960 แถว → เข้าเกณฑ์เพียง **1,477 แถว** (ตัดทิ้ง 8,483 แถว) ของเดิมนำเข้าทั้งหมดจึงทำให้ยอดและจำนวนรายการบนแดชบอร์ดพองเกินจริงมาก
2. **ตัดรายการซ้ำด้วย `TRAN_ID`** ทั้งภายในไฟล์เดียวกัน (`parse_report`) และข้ามไฟล์/ข้ามเดือนทั้งฐานข้อมูล (`db.insert_batch` เช็ค `tran_id` ที่มีอยู่แล้วก่อน insert) — `record_code` ยังเป็น PK ไว้เป็นตาข่ายกันซ้ำชั้นที่สอง
3. **ตัวเลขเป้าหมายคือคอลัมน์สุดท้าย `ยอดชดเชยทั้งสิ้น`** เก็บลงคอลัมน์ `records.grand_total` แยกจาก `total` (= PP+FS)
   - สองค่านี้ **ไม่เท่ากัน** เมื่อแถวเดียวกันมีเงินกองทุนอื่นปนมาด้วย เช่น PP 120 + HC 100 → `ยอดชดเชยทั้งสิ้น` = 220
   - ปีงบ 2569: `ยอดชดเชยทั้งสิ้น` = 255,000.50 บาท ส่วน PP+FS = 252,011.50 บาท
   - KPI "ยอดชดเชยทั้งสิ้นสะสม" และกราฟ Top 10 ใช้ `grand_total`; การจับคู่บริการยังใช้ PP และ FS แยกกันเหมือนเดิม (อัตราอ้างอิงเป็น PP Fee Schedule จะเอา `grand_total` ไปจับคู่ไม่ได้)

**⚠️ ถ้าฐานข้อมูลมีข้อมูลเก่าค้างอยู่** ให้ล้างข้อมูลเดิมแล้วอัปโหลดใหม่ เพราะแถวเก่ามีทั้งรายการที่ไม่มีเงิน PP/FS ปนอยู่ และ `grand_total` เป็น 0 (ยืนยันแล้วว่า production มีข้อมูลเก่า 9,960 รายการ = จำนวนแถวดิบปีงบ 2569 ก่อนกรอง)

### ปุ่มรีเซ็ตระบบ (`🧨 รีเซ็ตระบบกลับเป็นค่าเริ่มต้น`)

อยู่ในหน้าผู้ดูแลระบบ ใต้การ์ดประวัติการอัปโหลด เรียก `db.reset_all_data()` ซึ่ง `TRUNCATE ... RESTART IDENTITY` ทั้ง `allocations`, `records`, `upload_batches` ในคำสั่งเดียว (ต้องอยู่คำสั่งเดียวกันเพราะ FK ของ `records`)

**ย้อนกลับไม่ได้** ต่างจากปุ่ม rollback ที่เป็น soft-delete ผ่าน `upload_batches.status` ด่านกันพลาดมี 2 ชั้นอิสระใน `reset_system()`:

1. `role == "admin"` — ต้องมี session ผู้ดูแลระบบอยู่แล้ว
2. กรอกรหัสผ่านผู้ดูแลระบบซ้ำอีกครั้งในการ์ดนั้น เทียบกับ `OPPP_ADMIN_PASSWORD_HASH`

session อย่างเดียวไม่พอโดยตั้งใจ และช่องรหัสผ่านจะถูกล้างค่าทุกครั้งหลังกด ไม่ว่าจะสำเร็จหรือไม่

### แฟ้มกติกาตีความยอดเงิน

`assets/amount_rules.json` — คัดจากชีต `กติกาและสูตรรวม` ของแฟ้มอ้างอิง เป็นการตีความที่คนยืนยันแล้ว `service_matching.explain_amount()` จะใช้แฟ้มนี้ก่อน ถ้าไม่มีกติกาจึงค่อยตกไปใช้การจับคู่อัตโนมัติ (`predict_combo_label`) ยอดที่กติการะบุว่า "กำกวม" (80, 120, 210, 240) จะขึ้นสถานะ 🟡 เสมอ เพราะยอดเดียวกันตีความได้หลายแบบ ต้องดูรหัสบริการประกอบจึงจะฟันธงได้

`assets/service_rates.json` เพิ่มหน่วยย่อยรายแผงของยาคุม (9.1ก = 40 บาท/แผง, 9.2ก = 80 บาท/แผง) เพราะข้อมูลจริงมียอด 40 และ 80 ปรากฏ ไม่ได้จ่ายครั้งละ 3 แผงเสมอ

> หมายเหตุความแม่นยำ: ตารางความถี่ในแฟ้มอ้างอิง (60→441 ครั้ง, 120→288 ครั้ง ฯลฯ) สร้างจากชุดไฟล์ที่กว้างกว่าโฟลเดอร์ `ปีงบประมาณ 2569` อย่างเดียว รันเกณฑ์เดียวกันกับ 2569 ได้ 60→363, 120→241 จึงเทียบตัวเลขตรงๆ ไม่ได้ แต่กติกาการกรองตรงกัน



## เป้าหมายของระบบ

สร้างเว็บ Dashboard สำหรับสรุปเงินชดเชยจากรายงาน OPPP รายเดือน โดย:

- รวมยอดแยกตามหน่วยบริการด้วย `HCODE` 5 หลัก
- แสดงยอด `PP`, `FS` และยอดรวม
- ตรวจสอบรายการ/ชื่อผู้รับบริการซ้ำโดยไม่รวมยอดผิด
- หน้าแรกเป็น **Executive Dashboard** สาธารณะ (ไม่ต้อง login) โชว์เฉพาะภาพรวมผลงาน ไม่มี PID/ชื่อ
- หน้า **Developer/Admin** ซ่อนไว้หลัง login เท่านั้น ใช้อัปโหลดไฟล์ + ดูข้อมูลรายบุคคล + จัดสรรบริการ
- ข้อมูลเก็บถาวรจริงใน Postgres (Supabase) ไม่ใช่ session state แบบเดิม รองรับอัปโหลดสะสมหลายเดือน และย้อนกลับ (rollback) ไฟล์ที่อัปผิดได้

> ข้อควรระวัง: แฟ้มรายงานมี PID และชื่อผู้รับบริการ จึงห้าม push ไฟล์ `.xls` ขึ้น GitHub และห้ามเปิดข้อมูลรายบุคคลก่อนมีระบบ auth ที่ปลอดภัย (ตอนนี้มีแล้วผ่าน username/password hash)

## ที่เก็บโค้ด / การเผยแพร่ (เปลี่ยนจากเดิม)

- GitHub: https://github.com/chayanun250841/OPPP-Manage (branch `main`)
- **Hugging Face Space ถูกลบทิ้งแล้ว** — HF บล็อกการ downgrade จาก ZeroGPU เป็น CPU basic ถ้าไม่มี PRO subscription และ Space ใหม่ก็เจอ hardware picker ที่ CPU Basic กดไม่ได้ (ต้อง verify บัญชี) จึงย้ายทั้งหมดไป **Render** แทน
- **Deploy จริงอยู่ที่ Render**: https://oppp-manage.onrender.com (service ชื่อ `OPPP-Manage`, Free instance, auto-deploy จาก GitHub `main`)
- Git remote ในเครื่อง: `origin` = GitHub เท่านั้น (remote `hf` เดิมยังอาจค้างอยู่ในเครื่อง แต่ไม่ได้ใช้แล้วเพราะ HF Space ถูกลบ)

## ฐานข้อมูล: Supabase Postgres

- โปรเจกต์ Supabase ชื่อ `oppp-manage`, region **Southeast Asia (Singapore / ap-southeast-1)**
- **สำคัญ**: ต้องต่อผ่าน **Session pooler** (`aws-0-ap-southeast-1.pooler.supabase.com:5432`) ไม่ใช่ Direct connection (`db.xxx.supabase.co:5432`) เพราะ Direct ใช้ IPv6 ซึ่ง Render เข้าไม่ถึง (error "Network is unreachable")
- Username ของ pooler ต้องเป็นรูปแบบ `postgres.<project-ref>` (เช่น `postgres.wmgptvmspxmevpzxviwt`) ไม่ใช่ `postgres` เฉยๆ ไม่งั้นจะเจอ "password authentication failed"
- Connection string เก็บเป็น env var `DATABASE_URL` ใน Render → Environment (ไม่ commit ลง repo)
- Schema ถูกสร้างอัตโนมัติตอน `app.py` เริ่มทำงาน ผ่าน `db.init_db()` (ดู `db.py` → ตัวแปร `SCHEMA`)
- ตารางหลัก 3 ตาราง:
  - `upload_batches` — 1 แถวต่อ 1 ไฟล์ที่อัปโหลด (มี `status` = `active` / `rolled_back` ใช้ทำ rollback แบบ soft-delete)
  - `records` — ข้อมูลรายรายการ (record_code เป็น PRIMARY KEY กันซ้ำข้ามไฟล์/ข้ามเดือนอัตโนมัติผ่าน `ON CONFLICT DO NOTHING`)
  - `allocations` — สมุดจัดสรรบริการ (เดิมเป็น in-memory ledger, ตอนนี้ persist ถาวร)
- ทุก query อ่านข้อมูลจะ `JOIN` กับ `upload_batches` และกรอง `WHERE status = 'active'` เสมอ เพื่อให้ batch ที่ถูก rollback หายไปจากสรุปทันทีโดยไม่ต้องลบข้อมูลจริง

## Environment Variables ที่ต้องตั้งใน Render

| Key | ค่า | หมายเหตุ |
| --- | --- | --- |
| `DATABASE_URL` | connection string แบบ Session pooler ของ Supabase | ห้ามใส่ลงโค้ด/commit |
| `OPPP_ADMIN_USERNAME` | `Chayanun250841` | ตามที่ผู้ใช้กำหนด |
| `OPPP_ADMIN_PASSWORD_HASH` | sha256 hash ของรหัสผ่านที่ตั้ง | สร้างด้วย `python -c "import hashlib; print(hashlib.sha256('รหัสผ่าน'.encode()).hexdigest())"` — **ห้าม**เก็บรหัสผ่าน plaintext ไว้ที่ไหนทั้งสิ้น |

ตั้งค่าครบทั้ง 3 ตัวแล้วที่ Render ตอนนี้ (ยืนยันแล้วว่า `DATABASE_URL` เชื่อมต่อสำเร็จ ไม่มี error ในหน้าแรก)

## สถาปัตยกรรมไฟล์

- `app.py` — Gradio Blocks UI ทั้งหมด (parse .xls, executive dashboard, hidden admin console, event wiring)
- `db.py` — data access layer ทั้งหมดที่คุย Postgres ผ่าน `psycopg2` (ไม่มี ORM)
- `requirements.txt` — `gradio`, `pandas`, `xlrd`, `psycopg2-binary`
- `README.md` — ยังพูดถึง Hugging Face อยู่ (**ยังไม่ได้อัปเดต** ให้ตรงกับ Render — ควรแก้ทีหลัง)

## โครงสร้างหน้าเว็บใหม่

1. **Accordion ซ่อนไว้บนสุด** (`🔒 สำหรับผู้ดูแลระบบ`, ปิดอยู่โดย default) — กรอก username/password login ที่นี่
2. **หน้าแรก (public, ไม่ต้อง login)** — Executive Dashboard:
   - Header banner สไตล์กระทรวงสาธารณสุข (navy + gold, ธีม custom `NAVY`/`GOLD` ใน `app.py`)
   - KPI cards 6 ใบ: ยอดรวมสะสม, PP สะสม, FS สะสม, จำนวนรายการสะสม, จำนวนหน่วยบริการ, รอบข้อมูลล่าสุด
   - กราฟเส้นแนวโน้มรายเดือน + กราฟแท่ง Top 10 HCODE + ตารางสรุปทั้งหมด
   - `gr.Timer(30)` รีเฟรชข้อมูลอัตโนมัติทุก 30 วินาที (ให้ความรู้สึก realtime)
3. **หน้า Developer (ซ่อนด้วย `visible=False`, โผล่มาหลัง login สำเร็จเท่านั้น)**:
   - อัปโหลดไฟล์ `.xls` หลายไฟล์พร้อมกัน + ช่องกรอกผู้บันทึก → กดปุ่ม **"⚙️ ประมวลผลและบันทึกลงฐานข้อมูล"**
   - ตารางประวัติการอัปโหลด (ทุกไฟล์ที่เคยอัป) + dropdown เลือกไฟล์ + ปุ่ม "↩️ ย้อนกลับ" / "♻️ กู้คืน" (soft-delete ผ่าน `upload_batches.status`)
   - แท็บ "ตรวจสอบรายบุคคล", "ข้อมูลต้นทาง" (โชว์ PID/ชื่อ เฉพาะ admin), "จัดสรรบริการ" (เขียนลงตาราง `allocations` จริง ไม่ใช่ CSV import/export แบบเดิมแล้ว — ตัดฟีเจอร์ import CSV ของ ledger ออกเพราะไม่จำเป็นอีกต่อไปเมื่อมี DB ถาวร เหลือแค่ export ไว้ backup)

## ⚠️ ปัญหาที่ยังไม่ได้แก้ (ต้องตามต่อ)

**ปุ่ม "⚙️ ประมวลผลและบันทึกลงฐานข้อมูล" กดแล้วดูเหมือนไม่มีอะไรเกิดขึ้น** — ผู้ใช้ทดสอบอัปโหลดไฟล์จริง 2 ไฟล์ (`6906_OP_02.xls` ~292KB, `6907_OP_01.xls` ~1.1MB) กรอกผู้บันทึก "Admin" แล้วกดปุ่ม แต่ไม่เห็นผลลัพธ์ใดๆ บน production (Render)

ยังไม่ได้ debug จริงจัง แนวทางที่ควรเช็คก่อน:

1. **เช็ค browser console** (DevTools → Console/Network) ตอนกดปุ่ม ว่ามี JS error หรือ request ค้างอยู่ไหม
2. **เช็ค Render → Logs** ตอนกดปุ่ม ว่ามี Python traceback ขึ้นมาไหม (ถ้า exception หลุดจาก `process_upload` โดยไม่ถูก catch อาจทำให้ Gradio event handler ค้าง)
3. **สงสัยเรื่อง performance**: Render free tier มี CPU จำกัดมาก (แชร์ 0.1 vCPU) การ parse ไฟล์ `.xls` ด้วย pandas (โดยเฉพาะไฟล์ 1.1MB ที่มีหลายร้อย/พันแถว) + insert ลง Postgres อาจใช้เวลานานกว่าที่คิด ให้ลองรอ 30-60 วินาทีหลังกดปุ่มดูก่อนว่าเป็นแค่ "ช้า" หรือ "ค้างจริง"
4. **เช็คว่า `uploader_name` ไม่ว่าง** — โค้ดใน `process_upload()` (`app.py`) จะ return ข้อความ error ทันทีถ้าไม่กรอกชื่อผู้บันทึก แต่จากภาพที่ทดสอบกรอกไว้แล้วว่า "Admin" จึงไม่น่าใช่สาเหตุนี้
5. ลองทดสอบ local ก่อน (`python app.py` พร้อมตั้ง `DATABASE_URL` เดียวกันในเครื่อง) จะ debug ง่ายกว่าเพราะเห็น traceback ตรงๆ ใน terminal ไม่ต้องผ่าน Render log delay

## ผลทดสอบที่ทำแล้ว (ก่อนเจอบั๊กข้างบน)

- ✅ Local: boot สำเร็จโดยไม่มี `DATABASE_URL` (fail gracefully, ไม่ crash)
- ✅ Local: login/logout ด้วย username+password ทดสอบทำงานถูกต้อง, หน้า Developer โผล่/ซ่อนตาม role
- ✅ Production (Render): เชื่อมต่อ Supabase สำเร็จผ่าน Session pooler, schema ถูกสร้างอัตโนมัติ, หน้าแรกโหลด "ข้อมูลสะสม 0 รายการ" โดยไม่มี error
- ❌ Production: ยังไม่เคยอัปโหลดไฟล์ผ่านสำเร็จเลยสักไฟล์ (ติดปัญหาข้างบน)

## สิ่งที่ควรทำต่อ

### 1. Debug ปุ่มอัปโหลดตามหัวข้อข้างบนก่อนเป็นอันดับแรก

### 2. อัปเดต README.md

ยังพูดถึง Hugging Face/Gradio Space อยู่ทั้งหมด ต้องเขียนใหม่ให้ตรงกับ Render + Supabase + โครงสร้างหน้าใหม่

### 3. พิจารณาลบไฟล์/remote ที่เกี่ยวกับ HF ที่ไม่ใช้แล้ว

`git remote` ชื่อ `hf` (ถ้ายังอยู่ในเครื่อง) ไม่ได้ใช้แล้วเพราะ Space ถูกลบไปแล้ว

### 4. Free tier caveats ที่ควรรู้

- Render free instance **sleep เมื่อไม่มีคนใช้งาน** และ cold start ใช้เวลา ~30-60 วิ (ปกติ ไม่ใช่บั๊ก)
- Supabase free tier ก็มีนโยบาย pause โปรเจกต์ที่ไม่ได้ใช้งานนานเกิน 1 สัปดาห์เช่นกัน ควรเข้าใช้งานเป็นระยะ หรือพิจารณาอัปเกรดถ้าจะใช้งานจริงจัง

## คำสั่ง Git ที่เคยใช้

```powershell
git status --short
git add app.py db.py requirements.txt
git commit -m "..."
git push origin main
```

ไฟล์รายงานยังขึ้นเป็น untracked เช่น:

```text
?? "ปีงบประมาณ 2569/"
```

ให้ปล่อยไว้แบบนี้ และอย่าใช้ `git add .` เพราะจะเสี่ยง upload ข้อมูลจริง
