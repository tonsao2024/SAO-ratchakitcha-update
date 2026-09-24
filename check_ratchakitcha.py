"""ตรวจราชกิจจานุเบกษาล่าสุด ๑๐๐ รายการ ตามคำค้น แล้วแจ้งเตือนผ่าน LINE Messaging API"""
import json, os, re, sys, time, random
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

BASE = os.environ.get("RATCHAKITCHA_URL", "https://ratchakitcha.soc.go.th/")
LINE_API = os.environ.get("LINE_API_BASE", "https://api.line.me")
ROOT = Path(__file__).parent
STATE = ROOT / "state" / "seen.json"
TH = timezone(timedelta(hours=7))

# NOTE: เว็บราชกิจจาฯ อยู่หลัง Cloudflare และบล็อก client ที่ดูเป็นบอท (HTTP 403)
# จึงต้องปลอมตัวเป็นเบราว์เซอร์จริง (headers + TLS fingerprint) + ลองซ้ำหลายรอบ
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
               "image/webp,image/apng,*/*;q=0.8"),
    "Accept-Language": "th-TH,th;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-CH-UA": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
    "Sec-CH-UA-Mobile": "?0",
    "Sec-CH-UA-Platform": '"Windows"',
    "Cache-Control": "max-age=0",
}
# curl_cffi จัดการ compression เอง จึงไม่ส่ง Accept-Encoding ไปให้
CURL_HEADERS = {k: v for k, v in BROWSER_HEADERS.items() if k != "Accept-Encoding"}

RETRYABLE_STATUS = {403, 408, 429, 500, 502, 503, 504}
CHALLENGE_MARKERS = ("Just a moment", "cf-challenge", "cf_clearance",
                     "Attention Required", "__cf_chl", "cf-error")
BACKOFF_BASE = float(os.environ.get("BACKOFF_BASE", "5"))  # ตั้งเป็น ~0 ตอนเทสเพื่อไม่ต้องรอ


class FetchError(Exception):
    """ดึงหน้าเว็บไม่สำเร็จ (รวมกรณีโดน Cloudflare บล็อก)"""


class LineError(Exception):
    """ส่งข้อความผ่าน LINE ไม่สำเร็จ"""


def log(msg):
    print(msg, flush=True)


def load_keywords():
    lines = (ROOT / "keywords.txt").read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.startswith("#")]


def _looks_like_challenge(text):
    head = (text or "")[:20000]
    return any(m in head for m in CHALLENGE_MARKERS)


def _check_html(status, url, text):
    """คืน html ถ้าปกติ, มิฉะนั้น raise FetchError (บอกชัดว่าโดนบล็อกหรือไม่)"""
    if status == 200 and text and len(text) > 2000 and not _looks_like_challenge(text):
        return text
    if status == 403 or _looks_like_challenge(text or ""):
        raise FetchError(f"ถูก Cloudflare บล็อก (HTTP {status}) ที่ {url} — "
                         f"จะลองวิธีอื่น/รอบถัดไป")
    raise FetchError(f"ดึง {url} ไม่สำเร็จ (HTTP {status}, ได้ {len(text or '')} ตัวอักษร)")


def _get_requests(url):
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=60)
        return _check_html(r.status_code, url, r.text)
    except FetchError:
        raise
    except requests.RequestException as e:
        raise FetchError(f"requests ล้มเหลว: {e}")


def _get_curl_cffi(url):
    try:
        from curl_cffi import requests as crequests
    except ImportError:
        raise FetchError("ไม่มีโมดูล curl_cffi (pip install -r requirements.txt)")
    try:
        # impersonate="chrome" = ใช้ TLS/JA3/HTTP2 fingerprint แบบ Chrome จริง
        r = crequests.get(url, headers=CURL_HEADERS, impersonate="chrome", timeout=60)
        return _check_html(r.status_code, url, r.text)
    except FetchError:
        raise
    except Exception as e:
        raise FetchError(f"curl_cffi ล้มเหลว: {type(e).__name__}: {e}")


def _sleep_backoff(attempt):
    delay = min(30, BACKOFF_BASE * (2 ** attempt)) + (random.uniform(0, 2) if BACKOFF_BASE else 0)
    log(f"  ⏳ รอ {delay:.0f} วินาทีแล้วลองใหม่…")
    time.sleep(delay)


def fetch_html(url):
    """ดึง html แบบทนทาน: requests+headers เบราว์เซอร์ก่อน แล้ว curl_cffi (Chrome
    fingerprint) พร้อม backoff — ถ้าไม่สำเร็จเลยจึง raise FetchError"""
    last_err = None

    log("วิธีที่ 1: requests + browser headers …")
    for attempt in range(2):
        try:
            return _get_requests(url)
        except FetchError as e:
            last_err = e
            log(f"  ✗ ครั้งที่ {attempt + 1}: {e}")
            # 403 = fingerprint โดนจำได้แล้ว ลองซ้ำด้วยวิธีเดิมไม่ช่วย → ข้ามไปวิธีถัดไป
            if "HTTP 403" in str(e) or "บล็อก" in str(e):
                break
            if attempt < 1:
                _sleep_backoff(attempt)

    log("วิธีที่ 2: curl_cffi (Chrome TLS fingerprint) …")
    for attempt in range(3):
        try:
            html = _get_curl_cffi(url)
            log(f"  ✓ สำเร็จในครั้งที่ {attempt + 1}")
            return html
        except FetchError as e:
            last_err = e
            log(f"  ✗ ครั้งที่ {attempt + 1}: {e}")
            if attempt < 2:
                _sleep_backoff(attempt)

    raise last_err or FetchError("ดึงข้อมูลไม่สำเร็จโดยไม่ทราบสาเหตุ")


def parse_items(html):
    soup = BeautifulSoup(html, "html.parser")
    items = {}
    for a in soup.find_all("a", href=re.compile(r"/documents/.+\.pdf(\?|#|$)", re.I)):
        title = " ".join(a.get_text(" ", strip=True).split())
        if not title or title == "ดูรายละเอียด":
            continue
        url = requests.compat.urljoin(BASE, a["href"])
        # วันที่/เล่ม/ตอน อยู่ถัดจากลิงก์
        meta = ""
        nxt = a.find_next(string=re.compile("เล่ม"))
        if nxt and nxt.parent:
            meta = " ".join(nxt.parent.get_text(" ", strip=True).split())[:120]
        items.setdefault(url, {"title": title, "url": url, "meta": meta})
    return list(items.values())


def fetch_items():
    html = fetch_html(BASE)
    items = parse_items(html)
    if not items:
        raise FetchError("ดึงหน้ามาได้แต่ไม่พบรายการเอกสารเลย (0 รายการ) — "
                         "โครงสร้างหน้าเว็บอาจเปลี่ยน")
    return items


def push_line(text):
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    to = os.environ.get("LINE_TO")  # userId / groupId; ถ้าว่างจะ broadcast ให้เพื่อนทุกคนของบอท
    if not token:
        log("[DRY RUN] ไม่มี LINE_CHANNEL_ACCESS_TOKEN\n" + text)
        return
    chunks = [text[i:i + 4900] for i in range(0, len(text), 4900)][:5]
    msgs = [{"type": "text", "text": c} for c in chunks]
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


def save_state(seen):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"seen": sorted(seen)[-2000:]},
                                ensure_ascii=False, indent=1), encoding="utf-8")


def main():
    now = datetime.now(TH).strftime("%d/%m/%Y %H:%M")
    kws = load_keywords()
    if not os.environ.get("LINE_CHANNEL_ACCESS_TOKEN"):
        log("⚠️ ยังไม่ได้ตั้งค่า LINE_CHANNEL_ACCESS_TOKEN — จะรันแบบ DRY RUN "
            "(พิมพ์ข้อความแทนการส่ง LINE จริง)")
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"seen": []}
    seen = set(state.get("seen", []))

    try:
        items = fetch_items()
    except FetchError as e:
        # ดึงเว็บไม่ได้ → แจ้งเตือนผ่าน LINE (ถ้าตั้งค่าไว้) แล้วจบแบบไม่พัง CI
        # (exit 0) เพราะความล้มเหลวชั่วคราวของเว็บ/Cloudflare ไม่ควรทำให้รันแดง
        log(f"⚠️ ตรวจราชกิจจาฯ ไม่สำเร็จ ({now})\n{e}")
        try:
            push_line(f"⚠️ ตรวจราชกิจจาฯ ไม่สำเร็จ ({now})\n{e}\nจะลองใหม่อัตโนมัติรอบถัดไป")
        except LineError as le:
            log(f"❌ {le}")
            return 1  # ส่ง LINE ไม่ได้เลย → ให้ CI แดงเพื่อเตือนว่าต้องแก้ token
        save_state(seen)
        return 0

    log(f"ดึงข้อมูลสำเร็จ: {len(items)} รายการ, คำค้น {len(kws)} คำ, เคยเห็นแล้ว {len(seen)} รายการ")
    hits = []
    for it in items:
        matched = [k for k in kws if k in it["title"]]
        if matched and it["url"] not in seen:
            hits.append((it, matched))
            seen.add(it["url"])

    if hits:
        lines = [f"🔔 ราชกิจจาฯ พบประกาศใหม่ที่เกี่ยวกับ สตง. {len(hits)} รายการ ({now})"]
        for i, (it, m) in enumerate(hits, 1):
            lines.append(f"\n{i}. {it['title']}\n{it['meta']}\nคำที่พบ: {', '.join(m)}\n🔗 {it['url']}")
        body = "\n".join(lines)
    else:
        body = (f"✅ ราชกิจจาฯ รอบ {now}\nไม่พบประกาศใหม่ตามคำค้น สตง. ({len(kws)} คำ)\n"
                f"ตรวจแล้ว {len(items)} รายการล่าสุด\n{BASE}")
    try:
        push_line(body)
    except LineError as le:
        log(f"❌ {le}")
        save_state(seen)
        return 1

    save_state(seen)
    log(f"เสร็จสิ้น: พบใหม่ {len(hits)} รายการ (exit 0)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
