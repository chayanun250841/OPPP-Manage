# OPPP Compensation Dashboard

Dashboard สำหรับรวมยอดชดเชย PP และ FS ตามรหัสหน่วยบริการ HCODE 5 หลัก จากรายงาน OPPP นามสกุล `.xls`

## ใช้งานในเครื่อง

```bash
pip install -r requirements.txt
streamlit run app.py
```

## เผยแพร่บน Hugging Face Spaces

1. สร้าง GitHub repository แล้ว push ไฟล์ `app.py`, `requirements.txt` และ `README.md` ขึ้นไป
2. สร้าง Hugging Face Space แบบ **Streamlit** และเชื่อม repository ดังกล่าว
3. ตั้งค่าเป็น private หากรายงานมี PID หรือชื่อผู้รับบริการ

Space จะเก็บข้อมูลที่อัปโหลดไว้เพียงชั่วคราว จึงให้ดาวน์โหลด `สมุดจัดสรรบริการ.csv` หลังทำงาน และอัปโหลดกลับมาในครั้งถัดไป เพื่อรักษาประวัติการแจกแจงยอด

## กติกาการกันซ้ำ

ระบบจะกันเฉพาะแถวที่ซ้ำเหมือนกันทุกส่วน ได้แก่ รอบรายงาน, TRAN_ID, PID, HCODE, วันรับบริการ, PP และ FS. รายการบริการต่างกันของคนเดียวกันจึงยังคงอยู่.
