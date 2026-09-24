"""ตรวจราชกิจจานุเบกษาล่าสุด ๑๐๐ รายการ ตามคำค้น แล้วแจ้งเตือนผ่าน LINE Messaging API"""
import json, os, re, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

BASE = "https://ratchakitcha.soc.go.th/"
ROOT = Path(__file__).parent
STATE = ROOT / "state" / "seen.json"
TH = timezone(timedelta(hours=7))
UA = {"User-Agent": "Mozilla/5.0 (SAO-ratchakitcha-bot)"}


def load_keywords():
    lines = (ROOT / "keywords.txt").read_text(encoding="utf-8").splitlines()
    return [l.strip() for l in lines if l.strip() and not l.startswith("#")]


def fetch_items():
    r = requests.get(BASE, headers=UA, timeout=60)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    items = {}
    for a in soup.find_all("a", href=re.compile(r"/documents/\d+\.pdf")):
        title = " ".join(a.get_text(" ", strip=True).split())
        if not title or title == "ดูรายละเอียด":
            continue
        url = requests.compat.urljoin(BASE, a["href"])
        # วันที่/เล่ม/ตอน อยู่ถัดจากลิงก์
        meta = ""
        nxt = a.find_next(string=re.compile("เล่ม"))
        if nxt:
            meta = " ".join(nxt.parent.get_text(" ", strip=True).split())[:120]
        items.setdefault(url, {"title": title, "url": url, "meta": meta})
    return list(items.values())


def push_line(text):
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    to = os.environ.get("LINE_TO")  # userId / groupId; ถ้าว่างจะ broadcast ให้เพื่อนทุกคนของบอท
    if not token:
        print("[DRY RUN] ไม่มี LINE_CHANNEL_ACCESS_TOKEN\n" + text)
        return
    chunks = [text[i:i + 4900] for i in range(0, len(text), 4900)][:5]
    msgs = [{"type": "text", "text": c} for c in chunks]
    endpoint, body = ("push", {"to": to, "messages": msgs}) if to else ("broadcast", {"messages": msgs})
    r = requests.post(f"https://api.line.me/v2/bot/message/{endpoint}",
                      headers={"Authorization": f"Bearer {token}"}, json=body, timeout=30)
    print("LINE:", r.status_code, r.text)
    r.raise_for_status()


def main():
    now = datetime.now(TH).strftime("%d/%m/%Y %H:%M")
    kws = load_keywords()
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"seen": []}
    seen = set(state["seen"])
    try:
        items = fetch_items()
    except Exception as e:
        push_line(f"⚠️ ตรวจราชกิจจาฯ ไม่สำเร็จ ({now})\n{e}")
        sys.exit(1)

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
        push_line("\n".join(lines))
    else:
        push_line(f"✅ ราชกิจจาฯ รอบ {now}\nไม่พบประกาศใหม่ตามคำค้น สตง. ({len(kws)} คำ)\n"
                  f"ตรวจแล้ว {len(items)} รายการล่าสุด\n{BASE}")

    state["seen"] = sorted(seen)[-2000:]
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
