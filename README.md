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
streamlit run app.py
```

## เผยแพร่บน Hugging Face Spaces

1. สร้าง GitHub repository แล้ว push ไฟล์ `app.py`, `requirements.txt` และ `README.md` ขึ้นไป
2. สร้าง Hugging Face Space แบบ **Gradio** ตั้งค่าเป็น Private และ push โค้ดจาก repository นี้เข้า Space
3. Hugging Face จะติดตั้ง dependencies จาก `requirements.txt` และรัน `app.py` อัตโนมัติ

Space จะเก็บข้อมูลที่อัปโหลดไว้เพียงชั่วคราว จึงให้ดาวน์โหลด `สมุดจัดสรรบริการ.csv` หลังทำงาน และอัปโหลดกลับมาในครั้งถัดไป เพื่อรักษาประวัติการแจกแจงยอด

## กติกาการกันซ้ำ

ระบบจะกันเฉพาะแถวที่ซ้ำเหมือนกันทุกส่วน ได้แก่ รอบรายงาน, TRAN_ID, PID, HCODE, วันรับบริการ, PP และ FS. รายการบริการต่างกันของคนเดียวกันจึงยังคงอยู่.
