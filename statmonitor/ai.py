import re
import requests
from statmonitor.config import GEMINI_API_KEY, EXHAUSTED_MODELS
from statmonitor.notifier import esc

def analyze_gemini(match, title, c_str, drops):
    if not GEMINI_API_KEY:
        return None
    prompt = (
        f"Ти професійний спортивний аналітик та експерт з оцінки букмекерських рухів ліній (Smart Money).\n"
        f"Матч: {match} ({title}, початок {c_str} за Києвом).\n"
        f"Просідання коефіцієнтів (рух ринку):\n{drops}\n\n"
        f"Проведи глибокий аналіз матчу українською мовою з урахуванням складів, поточної форми, свіжих новин та прихованих причин руху котирувань.\n"
        f"Формат відповіді (строго за цими розділами, до 1100 символів):\n"
        f"📌 **Коротка ставка:** (тільки маркет без слів про коефіцієнт: П1, Ф2 (+1.5), ТМ 2.5 або Пропустити)\n"
        f"🎯 **Рекомендована ставка:** (чітка рекомендація: брати чи пропустити, і чому)\n\n"
        f"🏥 **Склади та кадрові втрати:** (травми, дискваліфікації лідерів, очікувана ротація чи підтверджені склади)\n"
        f"🔥 **Поточна форма та тонус:** (серії команд, тонус ключових бомбардирів/воротарів, втома через календар)\n"
        f"🗣️ **Інсайди, чутки та суть прогрузу:** (чому саме сюди йдуть великі гроші: інсайд про проблеми, зміна тактики чи пастка бука)\n"
        f"⚖️ **Оцінка валую (Value):** (чи вигідний поточний коефіцієнт після падіння, чи лінію вже віджали занадто низько)"
    )
    for model in ["gemini-3.5-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-3.8-flash"]:
        if model in EXHAUSTED_MODELS:
            continue
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        cfg = {"temperature": 0.35, "maxOutputTokens": 1200}
        if "2.5" in model:
            cfg["thinkingConfig"] = {"thinkingBudget": 0}

        # Спочатку намагаємося використати Google Search Grounding для свіжих новин/складів
        payload_with_search = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": cfg,
        }
        try:
            r = requests.post(url, json=payload_with_search, timeout=35)
            # Якщо модель не підтримує tools у даному режимі, повторюємо чистий запит
            if r.status_code != 200:
                payload_pure = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": cfg}
                r = requests.post(url, json=payload_pure, timeout=30)

            if r.status_code == 200:
                parts = r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                txt = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
                if len(txt) >= 40:
                    clean = esc(txt)
                    clean = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", clean)
                    return clean
            elif r.status_code in (404, 429):
                EXHAUSTED_MODELS.add(model)
        except Exception:
            pass
    return None

def extract_short_pick(ai_verdict, fallback):
    if not ai_verdict:
        return fallback
    for tag in ("Коротка ставка", "Рекомендована ставка"):
        for line in ai_verdict.splitlines():
            if tag in line:
                clean = re.sub(r"<[^>]+>", "", line)
                clean = re.sub(r"[*_]", "", clean)
                if ":" in clean:
                    rec = clean.split(":", 1)[1].strip(" *_:;-")
                    if any(w in rec.lower() for w in ("пропустити", "утриматися")):
                        return "⏭ Пропустити матч"
                    rec = re.split(r"\s*(?:,|\()?\s*(?:(?:з|по|за|у|в)\s+(?:поточн\w+|орієнтовн\w+)?\s*(?:коефіцієнт\w*|кеф\w*|кф\w*|@)?|(?:поточн\w+|орієнтовн\w+)?\s*(?:коефіцієнт\w*|кеф\w*|кф\w*|@))\s*(?:близько|біля|в районі|у діапазоні)?\s*[~0-9].*$", rec, maxsplit=1, flags=re.I)[0]
                    rec = re.split(r"\.(?:\s|$)", rec, maxsplit=1)[0].strip(" ,;-")
                    if len(rec) > 55:
                        rec = rec[:55].rsplit(" ", 1)[0].strip(" ,;-")
                    if rec.count("(") > rec.count(")"):
                        rec += ")" * (rec.count("(") - rec.count(")"))
                    if rec:
                        return rec
    return fallback
