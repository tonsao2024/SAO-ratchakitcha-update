"""ชั่วคราว: รันสคริปต์จริงกับข้อมูลจริง แต่สลับการส่ง LINE เป็นการพิมพ์ — ลบหลังตรวจเสร็จ"""
import importlib.util, json, os, shutil, tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = Path(tempfile.mkdtemp(prefix="live-"))
shutil.copy(ROOT / "check_ratchakitcha.py", WORK / "check_ratchakitcha.py")
shutil.copy(ROOT / "keywords.txt", WORK / "keywords.txt")
(WORK / "state").mkdir()
os.environ["LINE_CHANNEL_ACCESS_TOKEN"] = "dummy-not-used"
os.environ["LINE_TO"] = "U-dummy"
os.environ.pop("DRY_RUN", None)

spec = importlib.util.spec_from_file_location("bot", WORK / "check_ratchakitcha.py")
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)
sent = []
bot.push_line = sent.append  # แทนการยิง LINE จริง (main() จะคิดว่า "ส่งสำเร็จ" และบันทึก state)

real_fetch = bot.fetch_records
FAKE = {"new": None}


def fetch_with_fake(start, end):
    rows = real_fetch(start, end)
    return rows + ([FAKE["new"]] if FAKE["new"] else [])


def run(label):
    print(f"\n===== {label} =====", flush=True)
    sent.clear()
    rc = bot.main()
    print(f"→ exit={rc} · จำนวนข้อความที่ส่ง={len(sent)}", flush=True)
    for msgs in sent:
        for m in msgs:
            print("---- ข้อความ ----\n" + m, flush=True)
    return len(sent)


state_path = WORK / "state" / "seen.json"
run("รอบที่ 1: state ว่าง (รอบแรก) — ควรแจ้งรายการที่ตรงคำค้น")
print("keys ที่จำไว้:", len(json.loads(state_path.read_text(encoding="utf-8"))["seen"]))
run("รอบที่ 2: ข้อมูลเดิม — ต้องไม่ส่งข้อความเลย")

FAKE["new"] = {
    "id": f"{date.today().isoformat()}-15000000",
    "doctitle": "ประกาศสำนักงานการตรวจเงินแผ่นดิน เรื่อง การจัดซื้อจัดจ้าง (ข้อมูลจำลองเพื่อทดสอบ)",
    "bookNo": "143", "section": "57", "category": "ก", "pageNo": "99",
    "publishDate": date.today().isoformat(),
    "pdf_file": f"{date.today().isoformat()}-15000000.pdf",
    "source_url": f"https://ratchakitcha.soc.go.th/documents/15000000.pdf", "is_test": False,
}
n3 = run("รอบที่ 3: เพิ่มรายการใหม่ 1 รายการ — ต้องแจ้งเฉพาะรายการใหม่ ไม่พูดถึงรายการเดิม")
FAKE["new"] = None
n4 = run("รอบที่ 4: ข้อมูลเดิมอีกครั้ง — ต้องเงียบ")
print(f"\nสรุป: รอบ 1 = 1 · รอบ 2 = 0 · รอบ 3 = {n3} (คาดหวัง 1) · รอบ 4 = {n4} (คาดหวัง 0)")
