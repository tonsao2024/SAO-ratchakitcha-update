# SAO-ratchakitcha-update
บอท LINE แจ้งเตือนประกาศใหม่ในราชกิจจานุเบกษาตามคำค้น สตง.
ดึงข้อมูลจาก**ฐานตั้งต้น [Open Law Data Thailand](https://huggingface.co/open-law-data-thailand)** —
ชุดข้อมูล [`soc-ratchakitcha`](https://huggingface.co/datasets/open-law-data-thailand/soc-ratchakitcha) บน Hugging Face
(ข้อมูลจากสำนักเลขาธิการคณะรัฐมนตรี แบบ machine-readable อัปเดตทุกวัน) แทนการเปิดหน้าเว็บ ratchakitcha.soc.go.th โดยตรง
จึงไม่ติดปัญหาเว็บบล็อกการเชื่อมต่อจากเซิร์ฟเวอร์ (Cloudflare 403) อีก

ตรวจวันละ 2 รอบ **09:00 / 18:00 น.** (GitHub Actions) — พบ = ส่งชื่อเรื่อง + วันที่/เล่ม/ตอน/หน้า + ลิงก์ PDF ต้นฉบับ, ไม่พบ = แจ้งว่าไม่พบ

## ตั้งค่า (ทำครั้งเดียว)
1. ไปที่ https://developers.line.biz/console/ → สร้าง Provider → สร้าง **Messaging API channel**
   (LINE Notify ปิดบริการแล้วตั้งแต่ 31 มี.ค. 2025 จึงใช้ Messaging API แทน)
2. แท็บ Messaging API → สแกน QR เพิ่มบอทเป็นเพื่อน → กด **Issue Channel access token (long-lived)**
3. GitHub repo → Settings → Secrets and variables → Actions → New repository secret
   - `LINE_CHANNEL_ACCESS_TOKEN` = token จากข้อ 2
   - `LINE_TO` (ไม่ใส่ก็ได้) = User ID ของคุณ (อยู่ในแท็บ Basic settings ด้านล่าง "Your user ID") หรือ Group ID
     ถ้าไม่ใส่ ระบบจะ broadcast ให้ทุกคนที่แอดบอท
   - `HF_TOKEN` (ไม่ใส่ก็ได้) = Hugging Face access token แบบ Read — ใช้เฉพาะกรณีถูกจำกัดจำนวนครั้ง (HTTP 429)
4. Settings → Actions → General → Workflow permissions → เลือก **Read and write**
5. แท็บ Actions → "Ratchakitcha SAO alert" → **Run workflow** เพื่อทดสอบ
   (ติ๊ก **"ทดสอบเท่านั้น"** ถ้าต้องการดูผลโดยไม่ส่ง LINE จริง — ข้อความที่จะส่งจะแสดงในหน้าสรุปของรอบนั้น)

## แก้คำค้น
แก้ไฟล์ `keywords.txt` (หนึ่งบรรทัดต่อหนึ่งคำ) — ระบบเทียบคำโดยไม่สนช่องว่าง อักขระล่องหน และเลขไทย/อารบิก

## ทำงานอย่างไร
1. ดาวน์โหลดไฟล์ `meta/<ปี>/<ปี-เดือน>.jsonl` ของเดือนที่ครอบคลุม **30 วันล่าสุด** จากชุดข้อมูล (ไฟล์ละ ~2–3 MB)
2. เลือกประกาศที่วันที่ประกาศ (`publishDate`) อยู่ใน 30 วันล่าสุด และตัด record ทดสอบระบบของต้นทาง (`is_test`) ออก
3. จับคำค้นจาก**ชื่อเรื่อง** (`doctitle`)
4. แจ้ง LINE เฉพาะรายการที่ยังไม่เคยแจ้ง — จำไว้ใน `state/seen.json` (บันทึกเฉพาะเมื่อส่ง LINE สำเร็จ)

ลิงก์ในข้อความชี้ไปที่ PDF ต้นฉบับบน ratchakitcha.soc.go.th (ถ้าต้นทางไม่มีลิงก์ จะใช้สำเนา PDF บน Hugging Face)
รอบแรกหลังเปลี่ยนแหล่งข้อมูลจะแจ้งรายการย้อนหลัง 30 วันที่ตรงคำค้น หลังจากนั้นแจ้งเฉพาะรายการใหม่

## ตั้งค่าเพิ่มเติม (ไม่บังคับ)
ใส่เป็น `env:` ในขั้นตอน `python check_ratchakitcha.py` ของ `.github/workflows/check.yml`

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
| :--- | :--- | :--- |
| `LOOKBACK_DAYS` | `30` | ตรวจประกาศย้อนหลังกี่วัน (รายการที่เคยแจ้งแล้วจะไม่แจ้งซ้ำ) |
| `STALE_DAYS` | `5` | ถ้าประกาศล่าสุดในฐานเก่ากว่านี้ จะเตือนว่าฐานข้อมูลอาจไม่อัปเดต |
| `DRY_RUN` | – | `1` = พิมพ์ข้อความแทนการส่ง LINE และไม่บันทึก state |

## การแก้ปัญหาเบื้องต้น
- ถ้า Actions ขึ้น ✅ แต่ไม่มีข้อความเข้า LINE → ยังไม่ได้ตั้งค่า Secrets (`LINE_CHANNEL_ACCESS_TOKEN` / `LINE_TO`) ให้ทำตามข้อ 3 ด้านบน แล้วกด **Run workflow** อีกครั้ง
  (ระหว่างที่ยังไม่มี token บอทจะทำงานแบบ DRY RUN และยังไม่จำว่าแจ้งแล้ว เมื่อใส่ token จะได้รับรายการย้อนหลังตาม `LOOKBACK_DAYS`)
- ถ้าได้ข้อความ "ดึงข้อมูลจาก Open Law Data Thailand (Hugging Face) ไม่ได้" → Hugging Face ขัดข้องชั่วคราว สคริปต์ลองซ้ำให้แล้วหลายครั้ง และจะลองใหม่เองในรอบถัดไป
  ถ้าเจอ HTTP 429 บ่อย ให้เพิ่ม Secret `HF_TOKEN`; ถ้าขึ้นว่า "ไม่พบไฟล์ meta" แปลว่าชุดข้อมูลอาจเปลี่ยนโครงสร้าง
- ถ้าได้คำเตือน "ฐานข้อมูลอาจยังไม่อัปเดต" → ชุดข้อมูลไม่มีประกาศใหม่เกิน `STALE_DAYS` วัน ให้ตรวจที่
  [หน้าชุดข้อมูล](https://huggingface.co/datasets/open-law-data-thailand/soc-ratchakitcha) หรือดูเว็บราชกิจจาฯ โดยตรง
- ถ้า log ขึ้นว่า "LINE API ตอบ 401" → Channel access token หมดอายุหรือไม่ถูกต้อง ให้ออก token ใหม่แล้วอัปเดต Secrets

## หมายเหตุ
- ชุดข้อมูลบน Hugging Face อัปเดต**วันละครั้งราว 21:00–22:00 น.** ประกาศของแต่ละวันจึงมักถูกแจ้งใน**รอบ 09:00 น. ของวันถัดไป**
  (รอบ 18:00 น. ส่วนใหญ่จะไม่พบรายการใหม่ ถ้าต้องการให้แจ้งเร็วขึ้น เปลี่ยน cron ของรอบนี้เป็น `"30 15 * * *"` = 22:30 น.)
- cron ของ GitHub อาจช้ากว่าเวลาจริงได้ 5–15 นาที
- โควตาฟรีของ LINE OA ประมาณ 300 ข้อความ/เดือน (ใช้ ~60/เดือน)
- ข้อมูลราชกิจจานุเบกษา: [Open Law Data Thailand](https://www.openlawdatathailand.org/) / สำนักเลขาธิการคณะรัฐมนตรี
  สัญญาอนุญาต [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — การอ้างอิงทางกฎหมายควรตรวจกับ PDF ต้นฉบับ
