# SAO-ratchakitcha-update
บอท LINE แจ้งเตือนประกาศใหม่ในราชกิจจานุเบกษา (https://ratchakitcha.soc.go.th/) ตามคำค้น สตง.
ตรวจวันละ 2 รอบ **09:00 / 18:00 น.** (GitHub Actions) — พบ = ส่งชื่อเรื่อง + ลิงก์ PDF, ไม่พบ = แจ้งว่าไม่พบ

## ตั้งค่า (ทำครั้งเดียว)
1. ไปที่ https://developers.line.biz/console/ → สร้าง Provider → สร้าง **Messaging API channel**
   (LINE Notify ปิดบริการแล้วตั้งแต่ 31 มี.ค. 2025 จึงใช้ Messaging API แทน)
2. แท็บ Messaging API → สแกน QR เพิ่มบอทเป็นเพื่อน → กด **Issue Channel access token (long-lived)**
3. GitHub repo → Settings → Secrets and variables → Actions → New repository secret
   - `LINE_CHANNEL_ACCESS_TOKEN` = token จากข้อ 2
   - `LINE_TO` (ไม่ใส่ก็ได้) = User ID ของคุณ (อยู่ในแท็บ Basic settings ด้านล่าง "Your user ID") หรือ Group ID
     ถ้าไม่ใส่ ระบบจะ broadcast ให้ทุกคนที่แอดบอท
4. Settings → Actions → General → Workflow permissions → เลือก **Read and write**
5. แท็บ Actions → "Ratchakitcha SAO alert" → **Run workflow** เพื่อทดสอบ

## แก้คำค้น
แก้ไฟล์ `keywords.txt` (หนึ่งบรรทัดต่อหนึ่งคำ)

## หมายเหตุ
- ตรวจจาก "ราชกิจจานุเบกษาล่าสุด ๑๐๐ รายการ" หน้าแรก และจับคำจาก **ชื่อเรื่อง**
- จำรายการที่แจ้งแล้วไว้ใน `state/seen.json` จึงไม่แจ้งซ้ำ
- cron ของ GitHub อาจช้ากว่าเวลาจริงได้ 5–15 นาที
- โควตาฟรีของ LINE OA ประมาณ 300 ข้อความ/เดือน (ใช้ ~60/เดือน)
