import re
import time
import requests
from datetime import datetime, timezone
from statmonitor.config import TG_BOT_TOKEN, TG_CHAT_ID, KYIV_TZ

def esc(txt):
    return str(txt).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def fmt_kyiv(dt):
    if not dt:
        return ""
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except Exception:
            return str(dt)[:16]
    if not hasattr(dt, "tzinfo") or not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KYIV_TZ).strftime("%d.%m %H:%M")

def _post_tg_chunk(url, chunk, chat_id=None, reply_markup=None):
    cid = chat_id or TG_CHAT_ID
    for attempt in range(2):
        try:
            payload = {"chat_id": cid, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True}
            if reply_markup:
                payload["reply_markup"] = reply_markup
            r = requests.post(url, json=payload, timeout=12)
            if r.status_code == 200:
                time.sleep(0.45)
                return
            if r.status_code == 429:
                wait_s = r.json().get("parameters", {}).get("retry_after", 5)
                print(f"TG 429 pause {wait_s}s...")
                time.sleep(int(wait_s) + 1)
                continue
            print(f"TG HTML err ({r.status_code}): {r.text[:120]}")
            plain = re.sub(r"<[^>]+>", "", chunk)
            plain_payload = {"chat_id": cid, "text": plain, "disable_web_page_preview": True}
            if reply_markup:
                plain_payload["reply_markup"] = reply_markup
            requests.post(url, json=plain_payload, timeout=12)
            time.sleep(0.45)
            return
        except Exception as e:
            print(f"TG msg err: {e}")

def send_tg(text, chat_id=None, reply_markup=None):
    cid = chat_id or TG_CHAT_ID
    if not TG_BOT_TOKEN or not cid or not text:
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    if len(text) <= 3800:
        _post_tg_chunk(url, text, chat_id=cid, reply_markup=reply_markup)
        return
    parts = text.split("\n\n")
    cur, c_len = [], 0
    for p in parts:
        if c_len + len(p) + 2 > 3800:
            if cur:
                _post_tg_chunk(url, "\n\n".join(cur), chat_id=cid, reply_markup=reply_markup)
            cur, c_len = [p], len(p)
        else:
            cur.append(p)
            c_len += len(p) + 2
    if cur:
        _post_tg_chunk(url, "\n\n".join(cur), chat_id=cid, reply_markup=reply_markup)

def send_photo(buf, caption):
    if not TG_BOT_TOKEN or not TG_CHAT_ID or not buf:
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
    cap = caption[:1024]
    try:
        buf.seek(0)
        files = {"photo": ("drop_chart.png", buf, "image/png")}
        data = {"chat_id": TG_CHAT_ID, "caption": cap, "parse_mode": "HTML"}
        r = requests.post(url, files=files, data=data, timeout=20)
        if r.status_code != 200:
            print(f"TG Photo err ({r.status_code}): {r.text[:120]}")
            buf.seek(0)
            data["parse_mode"] = ""
            data["caption"] = re.sub(r"<[^>]+>", "", cap)
            requests.post(url, files={"photo": ("drop_chart.png", buf, "image/png")}, data=data, timeout=20)
    except Exception as e:
        print(f"TG photo exc: {e}")
