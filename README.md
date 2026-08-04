---
title: OPPP Compensation Dashboard
emoji: 💰
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: 6.22.0
python_version: '3.12'
app_file: app.py
pinned: false
license: apache-2.0
---

# OPPP Compensation Dashboard

Dashboard สำหรับรวมยอดชดเชย PP และ FS ตามรหัสหน่วยบริการ HCODE 5 หลัก จากรายงาน OPPP นามสกุล `.xls`

## ใช้งานในเครื่อง

```bash
pip install -r requirements.txt
python app.py
```

## เผยแพร่บน Hugging Face Spaces

1. สร้าง GitHub repository แล้ว push ไฟล์ `app.py`, `requirements.txt` และ `README.md` ขึ้นไป
2. สร้าง Hugging Face Space แบบ **Gradio** ตั้งค่าเป็น Private และ push โค้ดจาก repository นี้เข้า Space
3. Hugging Face จะติดตั้ง dependencies จาก `requirements.txt` และรัน `app.py` อัตโนมัติ
4. ตั้ง Hardware ของ Space เป็น **CPU Basic** (แอปนี้เป็นงาน CPU เท่านั้น ไม่ต้องใช้ ZeroGPU)

Space จะเก็บข้อมูลที่อัปโหลดไว้เพียงชั่วคราว จึงให้ดาวน์โหลด CSV สมุดจัดสรรบริการหลังทำงาน และอัปโหลดกลับมาในครั้งถัดไป เพื่อรักษาประวัติการแจกแจงยอด

## กติกาการกันซ้ำ

ระบบจะกันเฉพาะแถวที่ซ้ำเหมือนกันทุกส่วน ได้แก่ รอบรายงาน, TRAN_ID, PID, HCODE, วันรับบริการ, PP และ FS. รายการบริการต่างกันของคนเดียวกันจึงยังคงอยู่.

## เข้าสู่ระบบ / สิทธิ์การเข้าถึง

- ผู้ที่ยังไม่เข้าสู่ระบบเห็นเฉพาะแท็บ "สรุปตาม HCODE" (ยอดรวม ไม่มี PID/ชื่อ)
- ผู้เข้าสู่ระบบด้วยรหัสผ่านผู้ดูแลที่ถูกต้องจะเห็นแท็บ "ตรวจสอบรายบุคคล", "ข้อมูลต้นทาง" และ "จัดสรรบริการ" เพิ่มเติม
- ตั้งรหัสผ่านโดยเก็บเฉพาะค่า hash ผ่านตัวแปรแวดล้อม `OPPP_ADMIN_PASSWORD_HASH` (ห้ามใส่ plaintext ลงโค้ดหรือ commit)
  - สร้างค่า hash ด้วยคำสั่ง:
    ```bash
    python -c "import hashlib; print(hashlib.sha256('รหัสผ่านของคุณ'.encode()).hexdigest())"
    ```
  - นำค่าที่ได้ไปตั้งใน Hugging Face Space ที่ `Settings -> Variables and secrets` ด้วยชื่อ `OPPP_ADMIN_PASSWORD_HASH`
- อย่าเปิด Space เป็น Public จนกว่าจะตั้งค่า secret นี้แล้ว มิฉะนั้นข้อมูลรายบุคคลจะยังไม่ถูกป้องกัน

## จัดสรรบริการ

แท็บ "จัดสรรบริการ" (เฉพาะผู้เข้าสู่ระบบ) ใช้แจกแจงยอดของรายการที่ไม่ระบุบริการ เช่น ตรวจหลังคลอด, ตรวจฟัน โดยบันทึกลงสมุดจัดสรรที่มีคอลัมน์ รหัสรายการ, ประเภทเงิน, บริการ, จำนวนเงิน, หมายเหตุ, ผู้บันทึก, เวลา พร้อมแสดงยอดคงเหลือต่อรายการและเตือนเมื่อจัดสรรเกินยอด เนื่องจาก Hugging Face Space ไม่เก็บข้อมูลถาวร ให้ดาวน์โหลดสมุดจัดสรรเป็น CSV หลังทำงานทุกครั้ง แล้วนำเข้ากลับมาในครั้งถัดไปด้วยปุ่มนำเข้า
