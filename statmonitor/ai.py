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
        f"📌 **Коротка ставка:** (строго ОДИН конкретний маркет: П1, Ф2 (+1.5), ТМ 2.5 або Пропустити. Без комбінацій чи альтернатив!)\n"
        f"🎯 **Рекомендована ставка:** (чітка рекомендація: брати чи пропустити, і чому)\n"
        f"⭐ **Оцінка впевненості (Confidence Score):** [число від 1 до 10]/10 (Рівень ризику: Low / Medium / High)\n\n"
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
                    # Відсікаємо альтернативні маркети (наприклад: "Ф2 (+7.5) або П2" -> "Ф2 (+7.5)")
                    rec = re.split(r"\s+(?:або|чи|\/)\s+", rec, maxsplit=1, flags=re.I)[0].strip(" ,;-")
                    rec = re.split(r"\s*(?:,|\()?\s*(?:(?:з|по|за|у|в)\s+(?:поточн\w+|орієнтовн\w+)?\s*(?:коефіцієнт\w*|кеф\w*|кф\w*|@)?|(?:поточн\w+|орієнтовн\w+)?\s*(?:коефіцієнт\w*|кеф\w*|кф\w*|@))\s*(?:близько|біля|в районі|у діапазоні)?\s*[~0-9].*$", rec, maxsplit=1, flags=re.I)[0]
                    rec = re.split(r"\.(?:\s|$)", rec, maxsplit=1)[0].strip(" ,;-")
                    if len(rec) > 55:
                        rec = rec[:55].rsplit(" ", 1)[0].strip(" ,;-")
                    if rec.count("(") > rec.count(")"):
                        rec += ")" * (rec.count("(") - rec.count(")"))
                    if rec:
                        return rec
    return fallback

def extract_confidence_score(ai_verdict):
    """
    SPEC-21: Витягує оцінку сили сигналу (Confidence Score 1-10) та рівень ризику (LOW, MEDIUM, HIGH) з вердикту Gemini.
    Повертає кортеж (score: int | None, risk_level: str | None).
    """
    if not ai_verdict:
        return None, None
    
    text = str(ai_verdict)
    
    # Якщо вердикт прямо рекомендує пропустити/утриматися, фіксуємо низьку оцінку та високий ризик
    if any(w in text.lower() for w in ("пропустити матч", "рекомендація: пропустити", "краще пропустити", "утриматися від ставки")):
        return 3, "HIGH"

    # Очищуємо від HTML тегів та Markdown asterisks для надійного парсингу
    clean = re.sub(r"<[^>]+>", "", text)
    clean = re.sub(r"[*_]", "", clean)

    # Регулярний вираз для пошуку "Оцінка впевненості (Confidence Score): 8/10", "8 з 10"
    m_score = re.search(
        r"(?:оцінка\s+впевненості(?:\s*\([^)]*\))?|confidence\s*(?:score)?|впевненість|сила\s+сигналу)\s*[:\-]?\s*([0-9]{1,2})\s*(?:/|з|\s*out\s*of\s*)?\s*(?:10)?",
        clean,
        re.I
    )
    score = None
    if m_score:
        try:
            val = int(m_score.group(1))
            if 1 <= val <= 10:
                score = val
        except ValueError:
            pass

    # Пошук рівня ризику: Low / Medium / High
    risk = None
    m_risk = re.search(r"(?:рівень\s+ризику|ризик|risk(?:\s*level)?)\s*[:\-]?\s*(low|medium|high|низький|середній|високий)", clean, re.I)
    if m_risk:
        r_str = m_risk.group(1).lower()
        if "low" in r_str or "низьк" in r_str:
            risk = "LOW"
        elif "med" in r_str or "середн" in r_str:
            risk = "MEDIUM"
        elif "high" in r_str or "висок" in r_str:
            risk = "HIGH"

    # Автокласифікація ризику, якщо вказано лише числовий бал
    if score is not None and not risk:
        if score >= 8:
            risk = "LOW"
        elif score >= 6:
            risk = "MEDIUM"
        else:
            risk = "HIGH"

    return score, risk

