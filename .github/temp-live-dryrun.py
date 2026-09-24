"""ชั่วคราว: รันสคริปต์จริงกับข้อมูลจริง แต่สลับการส่ง LINE เป็นการพิมพ์ — ลบหลังตรวจเสร็จ"""
import importlib.util, json, os, shutil, tempfile
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


def run(label):
    print(f"\n===== {label} =====", flush=True)
    sent.clear()
    rc = bot.main()
    print(f"→ exit={rc} · จำนวนข้อความที่ส่ง={len(sent)}", flush=True)
    for msgs in sent:
        for m in msgs:
            print("---- ข้อความ ----\n" + m, flush=True)
    return len(sent)


def state_path():
    return WORK / "state" / "seen.json"


run("รอบที่ 1: state ว่าง (รอบแรก) — ควรแจ้งรายการที่ตรงคำค้น")
seen1 = json.loads(state_path().read_text(encoding="utf-8"))
print("\nkeys ที่จำไว้:", len(seen1["seen"]))
run("รอบที่ 2: ข้อมูลเดิม — ต้องไม่ส่งข้อความเลย")

# จำลองว่า "มีของใหม่" โดยลบรายการหนึ่งออกจาก state (เหมือนเพิ่งตรวจพบครั้งแรก)
items = json.loads(state_path().read_text(encoding="utf-8"))["seen"]
title_keys = [k for k in items if k.startswith("t:")]
drop = set()
if title_keys:
    stem = title_keys[-1].split(":", 2)[2]
    drop = {k for k in items if stem in k}
kept = [k for k in items if k not in drop]
state_path().write_text(json.dumps({"source": seen1.get("source"), "seen": kept},
                                   ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n(จำลองของใหม่ 1 รายการ — ลบ {len(drop)} คีย์ออกชั่วคราว)")
n = run("รอบที่ 3: มีของใหม่ 1 รายการ — ต้องแจ้งเฉพาะรายการนั้น")
print(f"\nสรุป: รอบ 1 ส่ง {1 if seen1['seen'] else 0} ครั้ง · รอบ 3 ส่ง {n} ครั้ง (คาดหวัง 1)")
