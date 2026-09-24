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

## การแก้ปัญหาเบื้องต้น
- ถ้า Actions ขึ้น ✅ แต่ไม่มีข้อความเข้า LINE → ยังไม่ได้ตั้งค่า Secrets (`LINE_CHANNEL_ACCESS_TOKEN` / `LINE_TO`) ให้ทำตามข้อ 3 ด้านบน แล้วกด **Run workflow** อีกครั้ง
- ถ้า log ขึ้นว่า "ถูก Cloudflare บล็อก (HTTP 403)" → เว็บราชกิจจาฯ ปฏิเสธการเชื่อมต่อจากเซิร์ฟเวอร์ชั่วคราว สคริปต์จะลองใหม่หลายรอบ (requests + curl_cffi พร้อม backoff) และถ้ายังไม่ได้จะแจ้งเตือนผ่าน LINE แล้วรอรอบถัดไปเอง
- ถ้า log ขึ้นว่า "LINE API ตอบ 401" → Channel access token หมดอายุหรือไม่ถูกต้อง ให้ออก token ใหม่แล้วอัปเดต Secrets

## หมายเหตุ
- ตรวจจาก "ราชกิจจานุเบกษาล่าสุด ๑๐๐ รายการ" หน้าแรก และจับคำจาก **ชื่อเรื่อง**
- จำรายการที่แจ้งแล้วไว้ใน `state/seen.json` จึงไม่แจ้งซ้ำ
- cron ของ GitHub อาจช้ากว่าเวลาจริงได้ 5–15 นาที
- โควตาฟรีของ LINE OA ประมาณ 300 ข้อความ/เดือน (ใช้ ~60/เดือน)
