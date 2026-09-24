"""ทดสอบพฤติกรรม "แจ้งเฉพาะของใหม่จริง ๆ" ของ check_ratchakitcha.py

รัน:  python tests/test_check_ratchakitcha.py
ไม่ต่อเน็ต — ดึงข้อมูล (fetch_records) และส่ง LINE (push_line) ถูกแทนด้วยข้อมูลจำลอง
"""
import importlib.util, json, os, shutil, sys, tempfile, unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAO = "ประกาศสำนักงานการตรวจเงินแผ่นดิน เรื่อง แต่งตั้งเจ้าหน้าที่ตรวจสอบ"
OTHER = "ประกาศกระทรวงเกษตรและสหกรณ์ เรื่อง กำหนดเขตเพาะเลี้ยงสัตว์น้ำ"


def load_bot(work):
    """โหลดสคริปต์ใหม่ในโฟลเดอร์ทดสอบ (state จะอยู่ที่ work/state/seen.json)"""
    spec = importlib.util.spec_from_file_location("ratchakitcha_under_test", work / "check_ratchakitcha.py")
    bot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bot)
    bot.DRY_RUN = False
    return bot


class QuietAlertTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        shutil.copy(ROOT / "check_ratchakitcha.py", self.work / "check_ratchakitcha.py")
        shutil.copy(ROOT / "keywords.txt", self.work / "keywords.txt")
        (self.work / "state").mkdir()
        self.records, self.pushed, self.fail_with = [], [], None
        self.bot = load_bot(self.work)
        self.bot.fetch_records = self.fake_fetch
        self.bot.push_line = self.pushed.append
        self.today = datetime.now(self.bot.TH).date()
        os.environ["LINE_CHANNEL_ACCESS_TOKEN"] = "test-token"
        os.environ["LINE_TO"] = "U0000000000000"
        os.environ.pop("DRY_RUN", None)

    def tearDown(self):
        os.environ.pop("LINE_CHANNEL_ACCESS_TOKEN", None)
        os.environ.pop("LINE_TO", None)
        self.tmp.cleanup()

    # ------------------------------------------------------------- helpers
    def fake_fetch(self, start, end):
        if self.fail_with:
            raise self.bot.FetchError(self.fail_with)
        return [r for r in self.records if r["publishDate"] >= start.isoformat()]

    def rec(self, title, days_ago, pdf, rid=None, **extra):
        d = self.today - timedelta(days=days_ago)
        return {"id": rid or pdf.replace(".pdf", ""), "doctitle": title, "bookNo": "143",
                "section": "57", "category": "ก", "pageNo": "9", "publishDate": d.isoformat(),
                "pdf_file": pdf, "source_url": f"https://ratchakitcha.soc.go.th/documents/{pdf}",
                "is_test": False, **extra}

    def state(self):
        return json.loads((self.work / "state" / "seen.json").read_text(encoding="utf-8"))

    def text(self):
        return "\n\n".join(self.pushed[0]) if self.pushed else ""

    # --------------------------------------------------------------- tests
    def test_only_alerts_when_there_is_something_new(self):
        """รอบแรกแจ้งของที่ตรงคำค้น แล้วรอบถัดไปต้องเงียบเมื่อไม่มีอะไรใหม่"""
        self.records = [self.rec(SAO, 1, "a.pdf"), self.rec(OTHER, 1, "b.pdf")]
        self.assertEqual(self.bot.main(), 0)
        self.assertEqual(len(self.pushed), 1)
        self.assertIn("1 รายการ", self.text())

        self.pushed.clear()
        self.assertEqual(self.bot.main(), 0)
        self.assertEqual(self.pushed, [], "ไม่มีของใหม่แล้วต้องไม่ส่งข้อความเลย")

    def test_no_new_items_never_notifies(self):
        """ตรวจแล้วไม่พบอะไรตรงคำค้นเลย → เงียบ ไม่มีข้อความ 'ไม่พบประกาศใหม่' อีกต่อไป"""
        self.records = [self.rec(OTHER, 1, "a.pdf")]
        self.assertEqual(self.bot.main(), 0)
        self.assertEqual(self.pushed, [])

    def test_alerts_only_new_items(self):
        """มีของใหม่ 1 รายการ → แจ้งเฉพาะรายการนั้น ไม่พูดถึงรายการที่เคยแจ้งแล้ว"""
        self.records = [self.rec(SAO + " ฉบับที่ 1", 2, "a.pdf"), self.rec(OTHER, 1, "b.pdf")]
        self.bot.main()
        self.pushed.clear()
        self.records.append(self.rec(SAO + " ฉบับที่ 2", 0, "c.pdf"))
        self.bot.main()
        self.assertEqual(len(self.pushed), 1)
        self.assertIn("1 รายการ", self.text())
        self.assertNotIn("ฉบับที่ 1", self.text())

    def test_same_announcement_reissued_not_alerted_again(self):
        """ประกาศเดิมถูกออก record ใหม่ (id/pdf ต่าง แต่ชื่อ+วันที่เดิม) → ไม่แจ้งซ้ำ"""
        self.records = [self.rec(SAO, 0, "a.pdf")]
        self.bot.main()
        self.pushed.clear()
        self.records = [self.rec(SAO, 0, "a-rev2.pdf", rid="2026-01-01-99999999")]
        self.bot.main()
        self.assertEqual(self.pushed, [])

    def test_duplicate_rows_in_same_run_alerted_once(self):
        """ชื่อ+วันเดียวกัน 2 record ในรอบเดียว → แจ้งรายการเดียว"""
        self.records = [self.rec(SAO, 0, "h1.pdf", rid="2026-01-01-00000001"),
                        self.rec(SAO, 0, "h2.pdf", rid="2026-01-01-00000002")]
        self.bot.main()
        self.assertEqual(len(self.pushed), 1)
        self.assertIn("1 รายการ", self.text())

    def test_old_state_file_format_still_recognised(self):
        """state เดิม (เวอร์ชันก่อนหน้า) ต้องอ่านได้ และรายการที่เคยแจ้งแล้วต้องไม่แจ้งซ้ำ"""
        (self.work / "state" / "seen.json").write_text(json.dumps(
            {"source": self.bot.SOURCE_ID, "seen": ["a.pdf"]}, ensure_ascii=False), encoding="utf-8")
        self.records = [self.rec(SAO, 0, "a.pdf")]
        self.assertEqual(self.bot.main(), 0)
        self.assertEqual(self.pushed, [])

    def test_fetch_error_alerts_once_within_repeat_window(self):
        """ดึงข้อมูลไม่ได้ → แจ้งครั้งเดียว ไม่ยิงซ้ำทุกรอบ"""
        self.fail_with = "HTTP 503 ที่ https://huggingface.co/x: busy"
        self.bot.main()
        self.assertEqual(len(self.pushed), 1)
        self.assertIn("ไม่สำเร็จ", self.text())
        self.assertTrue(self.state()["last_error"]["sig"])

        self.pushed.clear()
        self.bot.main()
        self.assertEqual(self.pushed, [], "ปัญหาเดิมภายใน ERROR_REPEAT_HOURS ต้องไม่แจ้งซ้ำ")

    def test_fetch_error_realerts_after_repeat_window(self):
        """ปัญหาเดิมแต่ผ่านไปเกิน ERROR_REPEAT_HOURS → แจ้งอีกครั้ง (ไม่ได้ปิดการเตือนถาวร)"""
        self.fail_with = "HTTP 503 ที่ https://huggingface.co/x: busy"
        self.bot.main()
        data = self.state()
        data["last_error"]["at"] = (datetime.now(timezone.utc)
                                    - timedelta(hours=self.bot.ERROR_REPEAT_HOURS + 1)).isoformat(timespec="seconds")
        (self.work / "state" / "seen.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.pushed.clear()
        self.bot.main()
        self.assertEqual(len(self.pushed), 1)

    def test_recovery_clears_error_state(self):
        """กลับมาดึงข้อมูลได้ → ล้าง last_error เพื่อให้รอบถัดไปถ้าพังจะได้แจ้งทันที"""
        self.fail_with = "HTTP 503 ที่ https://huggingface.co/x: busy"
        self.bot.main()
        self.fail_with = None
        self.pushed.clear()
        self.bot.main()
        self.assertEqual(self.pushed, [])
        self.assertNotIn("last_error", self.state())

    def test_dry_run_sends_nothing_and_keeps_state(self):
        """DRY RUN → ไม่ส่ง LINE จริง และไม่บันทึก state (รายการจะถูกแจ้งเมื่อรันจริง)"""
        self.bot.DRY_RUN = True
        self.records = [self.rec(SAO, 0, "a.pdf")]
        self.bot.main()
        self.assertEqual(self.pushed, [])
        self.assertFalse((self.work / "state" / "seen.json").exists())

    def test_test_records_ignored(self):
        """record ทดสอบระบบของต้นทาง (is_test) ต้องไม่ถูกแจ้ง"""
        self.records = [self.rec(SAO + " ทดสอบระบบ", 0, "a.pdf", is_test=True)]
        self.bot.main()
        self.assertEqual(self.pushed, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
