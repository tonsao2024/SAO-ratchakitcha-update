"""ตรวจประกาศใหม่ในราชกิจจานุเบกษาตามคำค้น สตง. แล้วแจ้งเตือนผ่าน LINE Messaging API

แหล่งข้อมูล (ฐานตั้งต้น): ชุดข้อมูลราชกิจจานุเบกษาของ Open Law Data Thailand บน Hugging Face
    https://huggingface.co/datasets/open-law-data-thailand/soc-ratchakitcha
ได้รับข้อมูลจากสำนักเลขาธิการคณะรัฐมนตรี (สลค.) และอัปเดตทุกวัน (ราว 21:00 น.)

ขั้นตอน
1. ดาวน์โหลด meta/<ปี>/<ปี-เดือน>.jsonl ของทุกเดือนที่ครอบคลุม LOOKBACK_DAYS วันล่าสุด
   (1 บรรทัด = 1 ประกาศ: doctitle, bookNo, section, category, pageNo, publishDate, source_url …)
2. เลือกประกาศที่ publishDate อยู่ในช่วงนั้น (ตัด record ทดสอบระบบ is_test ออก)
3. จับคำค้นจาก keywords.txt ใน "ชื่อเรื่อง" (doctitle) และตัดรายการที่เคยแจ้งไปแล้วออก
4. แจ้ง LINE "เฉพาะเมื่อมีรายการใหม่จริง ๆ" — รายการที่เคยแจ้งแล้วจะไม่แจ้งซ้ำ (จำใน state/seen.json)
   ถ้าไม่พบ หรือไม่มีอะไรใหม่ จะไม่ส่งข้อความเลย (ดูผลการทำงานได้ใน log / สรุปของ GitHub Actions)
   กรณียดึงข้อมูลไม่ได้ จะแจ้งเตือนแบบจำกัดความถี่ (ERROR_REPEAT_HOURS) กันข้อความรบกวนช่วงระบบล่ม
"""
import hashlib, json, os, random, re, sys, time, unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests


def _env_int(name, default, minimum=1):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        print(f"⚠️ {name}={raw!r} ไม่ใช่ตัวเลข — ใช้ค่าเริ่มต้น {default}", flush=True)
        return default


HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "https://huggingface.co").rstrip("/")
HF_DATASET = os.environ.get("HF_DATASET", "open-law-data-thailand/soc-ratchakitcha")
HF_REVISION = os.environ.get("HF_REVISION", "main")
HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()  # ไม่บังคับ (ชุดข้อมูลเป็นสาธารณะ)
DATASET_PAGE = f"https://huggingface.co/datasets/{HF_DATASET}"
SOURCE_ID = f"huggingface:{HF_DATASET}"
SOURCE_NAME = "Open Law Data Thailand"

LOOKBACK_DAYS = _env_int("LOOKBACK_DAYS", 30)  # ตรวจประกาศย้อนหลังกี่วัน
ERROR_REPEAT_HOURS = _env_int("ERROR_REPEAT_HOURS", 24, minimum=0)  # ดึงข้อมูลไม่ได้ → แจ้งซ้ำถี่สุดกี่ ชม. (0 = ทุกรอบ)
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}
BACKOFF_BASE = float(os.environ.get("BACKOFF_BASE", "5"))  # ตั้งเป็น 0 ตอนเทสเพื่อไม่ต้องรอ
LINE_API = os.environ.get("LINE_API_BASE", "https://api.line.me")

ROOT = Path(__file__).parent
STATE = ROOT / "state" / "seen.json"
TH = timezone(timedelta(hours=7))
UA = "SAO-ratchakitcha-bot/2.0 (+https://github.com/tonsao2024/SAO-ratchakitcha-update)"
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
MAX_SEEN = 2000
MAX_ITEMS_PER_RUN = 30  # เกินนี้ยกไปแจ้งรอบถัดไป กันข้อความยาวเกินขีดจำกัดของ LINE
MAX_TITLE_CHARS = 500
LINE_MAX_CHARS = 4900   # LINE รับได้ 5,000 ตัวอักษร/ข้อความ
LINE_MAX_MSGS = 5       # และ 5 ข้อความ/ครั้ง
THAI_MONTHS = ("ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.",
               "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค.")
_NORMALIZE = str.maketrans({**dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff")),
                            **{ord(t): str(i) for i, t in enumerate("๐๑๒๓๔๕๖๗๘๙")}})


class FetchError(Exception):
    """ดึงข้อมูลจาก Hugging Face ไม่สำเร็จ"""


class LineError(Exception):
    """ส่งข้อความผ่าน LINE ไม่สำเร็จ"""


def log(msg):
    print(msg, flush=True)


# ---------------------------------------------------------------- utilities
def norm(text):
    """ทำข้อความให้อยู่รูปแบบเดียวกันก่อนเทียบคำ: ำ = ํา (NFKC), เลขไทย = เลขอารบิก,
    ตัดอักขระล่องหน (zero-width) และช่องว่างทั้งหมด"""
    text = unicodedata.normalize("NFKC", text or "").translate(_NORMALIZE)
    return "".join(text.split())


def parse_day(value):
    """'2026-09-23' / '2026-09-23 00:00:00' / '2026-09-23-00131199.pdf' → date (หรือ None)"""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(value or ""))
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def thai_date(d):
    return f"{d.day} {THAI_MONTHS[d.month - 1]} {d.year + 543}"


def short_hash(text):
    """ลายนิ้วมือสั้น ๆ ของข้อความ ใช้จำว่าเคยแจ้งปัญหาหรือรายการนี้ไปแล้ว"""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def utc_now():
    return datetime.now(timezone.utc)


def iso_utc(dt=None):
    return (dt or utc_now()).isoformat(timespec="seconds")


def parse_iso(value):
    """'2026-09-24T06:51:59+00:00' → datetime (หรือ None ถ้าอ่านไม่ได้)"""
    try:
        dt = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def months_between(start, end):
    """[(ปี, เดือน), …] ตั้งแต่เดือนของ start ถึงเดือนของ end"""
    y, m, out = start.year, start.month, []
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def load_keywords():
    lines = (ROOT / "keywords.txt").read_text(encoding="utf-8").splitlines()
    kws = []
    for line in lines:
        k = line.strip()
        if k and not k.startswith("#") and norm(k) and k not in kws:
            kws.append(k)
    return kws


# ------------------------------------------------------ Hugging Face dataset
def meta_url(y, m):
    return (f"{HF_ENDPOINT}/datasets/{HF_DATASET}/resolve/{HF_REVISION}"
            f"/meta/{y:04d}/{y:04d}-{m:02d}.jsonl")


def hf_pdf_url(pdf_file):
    """สำเนา PDF บน Hugging Face (เก็บเฉพาะ 3 เดือนล่าสุด) — ใช้เมื่อต้นทางไม่มี source_url"""
    m = re.match(r"(\d{4})-(\d{2})-", pdf_file or "")
    if not m:
        return ""
    return (f"https://huggingface.co/datasets/{HF_DATASET}/resolve/{HF_REVISION}"
            f"/pdf/{m[1]}/{m[1]}-{m[2]}/{pdf_file}")


def _sleep_backoff(attempt, retry_after=None):
    delay = min(30.0, BACKOFF_BASE * (2 ** attempt))
    if retry_after and retry_after.isdigit():
        delay = min(60.0, max(delay, float(retry_after)))
    if BACKOFF_BASE:
        delay += random.uniform(0, 1)
    log(f"  ⏳ รอ {delay:.0f} วินาทีแล้วลองใหม่…")
    time.sleep(delay)


def http_get(url, attempts=4):
    """GET แบบลองซ้ำเมื่อเน็ต/เซิร์ฟเวอร์ขัดข้องชั่วคราว — คืน bytes หรือ None ถ้า 404 (ยังไม่มีไฟล์)"""
    headers = {"User-Agent": UA}
    if HF_TOKEN:
        headers["Authorization"] = f"Bearer {HF_TOKEN}"
    last = "ไม่ทราบสาเหตุ"
    for attempt in range(attempts):
        retry_after = None
        try:
            r = requests.get(url, headers=headers, timeout=(15, 120))
        except requests.RequestException as e:
            last = f"เชื่อมต่อไม่ได้ ({type(e).__name__}: {e})"
        else:
            if r.status_code == 200:
                return r.content
            if r.status_code == 404:
                return None
            if r.status_code in (401, 403):
                raise FetchError(f"HTTP {r.status_code} ที่ {url} — ชุดข้อมูลอาจถูกย้าย/ปิดสิทธิ์ "
                                 f"หรือ HF_TOKEN ไม่ถูกต้อง")
            if r.status_code not in RETRYABLE_STATUS:
                raise FetchError(f"HTTP {r.status_code} ที่ {url}: {r.text[:200]}")
            last = f"HTTP {r.status_code}"
            retry_after = r.headers.get("Retry-After")
        log(f"  ✗ ครั้งที่ {attempt + 1}/{attempts}: {last}")
        if attempt < attempts - 1:
            _sleep_backoff(attempt, retry_after)
    raise FetchError(f"ดึง {url} ไม่สำเร็จหลังลอง {attempts} ครั้ง ({last})")


def parse_jsonl(body):
    rows, bad = [], 0
    for line in body.decode("utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            bad += 1
    return rows, bad


def fetch_records(start, end):
    """โหลด metadata ทุกเดือนที่ครอบคลุมช่วง start–end จากชุดข้อมูลบน Hugging Face"""
    records, found = [], 0
    for y, m in months_between(start, end):
        name = f"meta/{y:04d}/{y:04d}-{m:02d}.jsonl"
        log(f"ดาวน์โหลด {name} …")
        body = http_get(meta_url(y, m))
        if body is None:
            # เช่น เช้าวันที่ 1 ของเดือน ฐานยังไม่ได้สร้างไฟล์ของเดือนใหม่
            log("  – ยังไม่มีไฟล์ของเดือนนี้ (ข้าม)")
            continue
        found += 1
        rows, bad = parse_jsonl(body)
        log(f"  ✓ {len(rows):,} รายการ ({len(body) / 1e6:.1f} MB)"
            + (f", ข้ามบรรทัดที่อ่านไม่ได้ {bad}" if bad else ""))
        records.extend(rows)
    if not found:
        raise FetchError("ไม่พบไฟล์ meta ของเดือนที่ต้องการเลย — ชุดข้อมูลอาจเปลี่ยนโครงสร้าง "
                         f"(ตรวจที่ {DATASET_PAGE})")
    if not any(str(r.get("doctitle") or "").strip() for r in records):
        raise FetchError("ดาวน์โหลดได้แต่ไม่พบชื่อเรื่อง (doctitle) เลย — รูปแบบข้อมูลอาจเปลี่ยน")
    return records


def describe(rec, d):
    """เช่น '23 ก.ย. 2569 · เล่ม 143 ตอนที่ 57 ก หน้า 9' / '… ตอนพิเศษ 232 ง หน้า 94'"""
    book, section, cat, page = (str(rec.get(k) or "").strip()
                                for k in ("bookNo", "section", "category", "pageNo"))
    parts = [f"เล่ม {book}"] if book else []
    if section:
        if cat.endswith("พิเศษ"):
            parts.append(f"ตอนพิเศษ {section} {cat[:-len('พิเศษ')]}".strip())
        else:
            parts.append(f"ตอนที่ {section} {cat}".strip())
    elif cat:
        parts.append(cat)
    if page:
        parts.append(f"หน้า {page}")
    return " · ".join(x for x in (thai_date(d) if d else "", " ".join(parts)) if x)


def to_item(rec):
    pdf = str(rec.get("pdf_file") or "").strip()
    rid = str(rec.get("id") or "").strip()
    src = str(rec.get("source_url") or "").strip()
    d = parse_day(rec.get("publishDate")) or parse_day(rid) or parse_day(pdf)
    title = " ".join(str(rec.get("doctitle") or "").split())
    key = pdf or rid or src                   # pdf_file = รหัสคงที่ ไม่ซ้ำ (join key ของชุดข้อมูล)
    alt = {k for k in (pdf, rid, src, title_key(title, d)) if k} - {key}
    return {
        "key": key,
        "alt_keys": alt,                      # รองรับ state เดิม (URL) และ record ที่ถูกออกใหม่ด้วยรหัสอื่น
        "title": title,
        "date": d,
        "url": src or hf_pdf_url(pdf) or DATASET_PAGE,
        "meta": describe(rec, d),
        "is_test": rec.get("is_test") is True or str(rec.get("is_test")).lower() == "true",
    }


def title_key(title, d):
    """คีย์สำรองจากชื่อเรื่อง+วันที่ — กันแจ้งซ้ำเมื่อประกาศเดิมโผล่มาอีก record ที่ id/pdf_file ต่างกัน"""
    body = norm(title)
    if not body:
        return ""
    return f"t:{d.isoformat() if d else ''}:{short_hash(body)}"


def find_hits(items, kws, seen):
    nkws = [(k, norm(k)) for k in kws]
    hits, claimed = [], set()  # claimed = คีย์ของรายการที่จะแจ้งในรอบนี้ (กัน record ซ้ำในรอบเดียวกัน)
    for it in items:
        if not it["key"] or not it["title"]:
            continue
        keys = {it["key"]} | it["alt_keys"]
        if keys & seen or keys & claimed:
            continue
        title = norm(it["title"])
        found = [(k, nk) for k, nk in nkws if nk in title]
        # ไม่ต้องแสดงคำที่เป็นส่วนหนึ่งของคำที่ยาวกว่า (เช่น "ตรวจเงินแผ่นดิน" ใน "สำนักงานการตรวจเงินแผ่นดิน")
        matched = [k for k, nk in found if not any(nk != o and nk in o for _, o in found)]
        if matched:
            claimed |= keys
            hits.append((it, matched))
    return sorted(hits, key=lambda h: (h[0]["date"], h[0]["key"]), reverse=True)


# ------------------------------------------------------------------ messages
def format_hit(i, it, matched):
    title = it["title"]
    if len(title) > MAX_TITLE_CHARS:
        title = title[:MAX_TITLE_CHARS - 1] + "…"
    lines = [f"{i}. {title}"]
    if it["meta"]:
        lines.append(f"📅 {it['meta']}")
    lines += [f"คำที่พบ: {', '.join(matched)}", f"🔗 {it['url']}"]
    return "\n".join(lines)


def source_footer(newest):
    """บรรทัดปิดท้ายข้อความที่แจ้งเตือน — บอกว่าข้อมูลในฐานล่าสุดถึงวันไหน"""
    return f"แหล่งข้อมูล: {SOURCE_NAME}" + (f" (ข้อมูลถึง {thai_date(newest)})" if newest else "")


def pack(blocks):
    """รวม blocks เป็นข้อความ LINE ละไม่เกิน LINE_MAX_CHARS ตัวอักษร โดยไม่ตัดกลางรายการ"""
    msgs, cur = [], ""
    for b in blocks:
        while len(b) > LINE_MAX_CHARS:
            if cur:
                msgs.append(cur)
                cur = ""
            msgs.append(b[:LINE_MAX_CHARS])
            b = b[LINE_MAX_CHARS:]
        if not b:
            continue
        if cur and len(cur) + 2 + len(b) > LINE_MAX_CHARS:
            msgs.append(cur)
            cur = b
        else:
            cur = f"{cur}\n\n{b}" if cur else b
    if cur:
        msgs.append(cur)
    if len(msgs) > LINE_MAX_MSGS:  # กันไว้ก่อน ปกติไม่ถึงเพราะจำกัดจำนวนรายการ/ความยาวชื่อเรื่องแล้ว
        note = "\n…(ข้อความยาวเกินขีดจำกัดของ LINE)"
        msgs = msgs[:LINE_MAX_MSGS]
        msgs[-1] = msgs[-1][:LINE_MAX_CHARS - len(note)] + note
    return msgs


# ---------------------------------------------------------------- delivery
def push_line(messages):
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
    to = os.environ.get("LINE_TO", "").strip()  # userId / groupId; ถ้าว่างจะ broadcast ให้เพื่อนทุกคนของบอท
    msgs = [{"type": "text", "text": m} for m in messages[:LINE_MAX_MSGS]]
    endpoint, body = ("push", {"to": to, "messages": msgs}) if to else ("broadcast", {"messages": msgs})
    try:
        r = requests.post(f"{LINE_API}/v2/bot/message/{endpoint}",
                          headers={"Authorization": f"Bearer {token}"}, json=body, timeout=30)
    except requests.RequestException as e:
        raise LineError(f"เชื่อมต่อ LINE API ไม่ได้: {e}")
    log(f"LINE {endpoint}: {r.status_code} {r.text[:300]}")
    if r.status_code >= 400:
        raise LineError(f"LINE API ตอบ {r.status_code}: {r.text[:300]} "
                        f"(ตรวจว่า Channel access token / LINE_TO ถูกต้องหรือไม่)")


def write_summary(title, text):
    """เขียนบันทึกลงหน้าสรุปของ GitHub Actions (ถ้ารันใน Actions)"""
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if os.environ.get("GITHUB_ACTIONS") != "true" or not summary:
        return
    try:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### {title}\n\n```text\n{text}\n```\n\n")
    except OSError as e:
        log(f"⚠️ เขียนสรุปของ Actions ไม่ได้: {e}")


def report_to_actions(messages, sent):
    """แสดงข้อความในหน้าสรุปของ GitHub Actions (และเป็น notice เมื่อไม่ได้ส่งจริง)"""
    text = "\n\n".join(messages)
    write_summary(f"ข้อความ LINE ({'ส่งแล้ว' if sent else 'DRY RUN — ไม่ได้ส่งจริง'})", text)
    if os.environ.get("GITHUB_ACTIONS") == "true" and not sent:
        esc = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::notice title=ข้อความ LINE (DRY RUN)::{esc}", flush=True)


def deliver(messages, sending):
    if sending:
        push_line(messages)
    else:
        log("[DRY RUN] ไม่ได้ส่ง LINE จริง — ข้อความที่จะส่ง:\n" + "\n\n".join(messages))
    report_to_actions(messages, sending)


# ------------------------------------------------------------------- state
def load_state():
    """คืน (source, seen, last_error) โดย last_error = {"sig": str, "at": datetime|None}"""
    try:
        data = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    except (OSError, ValueError) as e:
        log(f"⚠️ อ่าน {STATE} ไม่ได้ ({e}) — เริ่มจำใหม่")
        data = {}
    if not isinstance(data, dict):
        data = {}
    err = data.get("last_error") if isinstance(data.get("last_error"), dict) else {}
    seen = {str(x) for x in data.get("seen") or [] if x}
    return data.get("source"), seen, {"sig": str(err.get("sig") or ""), "at": parse_iso(err.get("at"))}


def save_state(seen, last_error=None):
    """บันทึก state — last_error = {"sig", "at", "detail"} เพื่อจำว่าปัญหานี้แจ้งไปแล้ว (None = ล้าง)"""
    STATE.parent.mkdir(parents=True, exist_ok=True)
    data = {"source": SOURCE_ID, "seen": sorted(seen)[-MAX_SEEN:]}
    if last_error:
        data["last_error"] = last_error
    STATE.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# -------------------------------------------------------------------- main
def main():
    now = datetime.now(TH)
    now_str = now.strftime("%d/%m/%Y %H:%M")
    today = now.date()
    cutoff = today - timedelta(days=LOOKBACK_DAYS)
    kws = load_keywords()
    sending = bool(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")) and not DRY_RUN
    if not sending:
        log("⚠️ DRY RUN — " + ("ตั้ง DRY_RUN ไว้" if DRY_RUN else "ยังไม่ได้ตั้งค่า LINE_CHANNEL_ACCESS_TOKEN")
            + ": จะพิมพ์ข้อความแทนการส่ง LINE และไม่บันทึก state")
    source, seen, last_error = load_state()
    first_run = source != SOURCE_ID
    log(f"แหล่งข้อมูล: {DATASET_PAGE}")
    log(f"ตรวจประกาศวันที่ {cutoff} ถึง {today} ({LOOKBACK_DAYS} วัน), คำค้น {len(kws)} คำ, "
        f"เคยแจ้งแล้ว {len(seen)} รายการ" + (" [รอบแรกของแหล่งข้อมูลนี้]" if first_run else ""))

    try:
        records = fetch_records(cutoff, today)
    except FetchError as e:
        # ดึงข้อมูลไม่ได้ → แจ้งเตือนผ่าน LINE แล้วจบแบบไม่พัง CI (exit 0)
        # เพราะความขัดข้องชั่วคราวของ Hugging Face ไม่ควรทำให้รันแดง
        # แต่ถ้าเพิ่งแจ้งปัญหาเดิมไปเมื่อไม่นาน จะไม่ส่งซ้ำ (กันข้อความรบกวนช่วงระบบล่มยาว)
        detail = str(e)
        sig = short_hash(detail)
        last_at = last_error["at"]
        if (last_error["sig"] == sig and last_at
                and utc_now() - last_at < timedelta(hours=ERROR_REPEAT_HOURS)):
            log(f"ℹ️ ดึงข้อมูลไม่ได้เหมือนรอบก่อน (แจ้งไปแล้ว {last_at.astimezone(TH):%d/%m %H:%M} น.) "
                f"— ไม่ส่งซ้ำภายใน {ERROR_REPEAT_HOURS} ชม.\n{detail}")
            write_summary("ℹ️ ดึงข้อมูลไม่ได้ (แจ้งไปแล้ว — ไม่ส่งซ้ำ)", detail)
            return 0
        msg = (f"⚠️ ตรวจราชกิจจาฯ ไม่สำเร็จ ({now_str})\n"
               f"ดึงข้อมูลจาก {SOURCE_NAME} (Hugging Face) ไม่ได้\n{detail}\n"
               f"จะลองใหม่อัตโนมัติรอบถัดไป\n{DATASET_PAGE}")
        log(msg)
        try:
            deliver([msg], sending)
        except LineError as le:
            log(f"❌ {le}")
            return 1  # ส่ง LINE ไม่ได้เลย → ให้ CI แดงเพื่อเตือนว่าต้องแก้ token
        if sending:
            save_state(seen, {"sig": sig, "at": iso_utc(), "detail": detail[:200]})
        return 0

    items = [it for it in map(to_item, records) if not it["is_test"]]
    newest = max((it["date"] for it in items
                  if it["date"] and it["date"] <= today + timedelta(days=1)), default=None)
    recent = [it for it in items if it["date"] and it["date"] >= cutoff]
    hits = find_hits(recent, kws, seen)
    to_send = hits[:MAX_ITEMS_PER_RUN]
    log(f"ประกาศในช่วงที่ตรวจ {len(recent):,} รายการ (ข้อมูลถึง {newest or '-'}), "
        f"ตรงคำค้นและยังไม่เคยแจ้ง {len(hits)} รายการ")

    first_note = (f"(รอบแรกหลังเปลี่ยนมาใช้ฐานข้อมูล {SOURCE_NAME} — ตรวจย้อนหลัง {LOOKBACK_DAYS} วัน)"
                  if first_run else "")
    if not hits:
        # ไม่มีของใหม่จริง ๆ → ไม่ส่งข้อความ LINE (กันการรบกวน) แต่ทิ้งร่องรอยไว้ใน Actions
        dates = [it["date"] for it in recent]
        span = (f"ตรวจแล้ว {len(recent):,} รายการ (ประกาศ {thai_date(min(dates))} – {thai_date(max(dates))})"
                if dates else "ไม่มีประกาศในช่วงที่ตรวจ")
        log(f"ℹ️ ไม่พบประกาศใหม่ตามคำค้น สตง. ({len(kws)} คำ) — {span} — ไม่ส่งข้อความ LINE")
        write_summary("ℹ️ ไม่พบประกาศใหม่ (ไม่ส่ง LINE)", "\n".join(x for x in (
            f"ตรวจคำค้น {len(kws)} คำ · {span}",
            f"เคยแจ้งแล้ว {len(seen)} รายการ (จะไม่แจ้งซ้ำ)",
            source_footer(newest),
            DATASET_PAGE) if x))
        if sending and last_error["sig"]:
            save_state(seen)  # กลับมาปกติแล้ว → ล้างสถานะแจ้งปัญหา เพื่อให้รอบถัดไปถ้าพังจะได้แจ้งทันที
        return 0

    head = f"🔔 ราชกิจจาฯ พบประกาศใหม่ที่เกี่ยวกับ สตง. {len(hits)} รายการ ({now_str})"
    blocks = ["\n".join(x for x in (head, first_note) if x)]
    blocks += [format_hit(i, it, m) for i, (it, m) in enumerate(to_send, 1)]
    if len(hits) > len(to_send):
        blocks.append(f"…ยังมีอีก {len(hits) - len(to_send)} รายการ จะแจ้งในรอบถัดไป")
    blocks.append(source_footer(newest))

    try:
        deliver(pack(blocks), sending)
    except LineError as le:
        log(f"❌ {le}")
        return 1  # ไม่บันทึก state → รายการเหล่านี้จะถูกแจ้งอีกครั้งในรอบถัดไป

    if sending:
        for it, _ in to_send:  # จำทุกคีย์ (รวมชื่อเรื่อง+วันที่) กันแจ้งซ้ำถ้าประกาศเดิมถูกออกด้วยรหัสอื่น
            seen.update({it["key"]} | it["alt_keys"])
        save_state(seen)
    log(f"เสร็จสิ้น: แจ้ง {len(to_send)} รายการ" + ("" if sending else " (DRY RUN)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
