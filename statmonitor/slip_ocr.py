"""
StatMonitor - Gemini Bet Slip OCR (SPEC-31: Wave 10).
Інтелектуальне розпізнавання купонів БК (Favbet, Vbet тощо) через Gemini Vision API
та автоматичне зіставлення з активними ставками.
"""

import re
import json
import base64
import requests
from statmonitor.config import GEMINI_API_KEY, EXHAUSTED_MODELS

OCR_PROMPT = """Ти професійний експерт із розпізнавання купонів, квитанцій та скріншотів ставок.
Уважно проаналізуй зображення купона та витягни точні параметри ставки.
Поверни результат строго у форматі JSON за такою схемою:
{
  "ticket_id": "Номер квитка / ID ставки або null",
  "match_name": "Команда 1 - Команда 2 (або Гравець 1 - Гравець 2)",
  "sport": "Вид спорту (soccer, basketball, tennis, icehockey тощо)",
  "pick_label": "Точний маркет ставки (наприклад: П1, П2, Ф1 (0), Ф2 (+1.5), ТБ 2.5, ТМ 210.5, Обидві заб'ють)",
  "odds": 1.85,
  "stake_uah": 250.0,
  "potential_win_uah": 462.5,
  "placed_at": "Дата/час ставки або null"
}
Поверни ТІЛЬКИ валідний JSON без додаткових пояснень. Числа odds та stake_uah мають бути float. Якщо валюта інша (USD, EUR), переведи в UAH або вкажи еквівалент."""


def parse_bet_slip_with_gemini(image_bytes, mime_type="image/jpeg", api_key=None):
    """
    Відправляє зображення купона до Gemini Multimodal Vision API та повертає структурований словник.
    """
    key = api_key or GEMINI_API_KEY
    if not key:
        return {"success": False, "error": "GEMINI_API_KEY не налаштовано."}

    if not image_bytes:
        return {"success": False, "error": "Порожній файл зображення."}

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    models_pool = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-1.5-flash"]
    for model in models_pool:
        if model in EXHAUSTED_MODELS:
            continue

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": image_b64
                            }
                        },
                        {
                            "text": OCR_PROMPT
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "response_mime_type": "application/json",
                "maxOutputTokens": 1000
            }
        }

        try:
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                raw_txt = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()

                # Парсинг JSON
                try:
                    clean_json = raw_txt
                    if "```json" in clean_json:
                        clean_json = clean_json.split("```json", 1)[1].split("```", 1)[0].strip()
                    elif "```" in clean_json:
                        clean_json = clean_json.split("```", 1)[1].split("```", 1)[0].strip()

                    parsed = json.loads(clean_json)
                    parsed["success"] = True
                    parsed["raw_json"] = raw_txt
                    return parsed
                except Exception as je:
                    return {
                        "success": False,
                        "error": f"Помилка парсингу JSON від Gemini: {je}",
                        "raw_output": raw_txt
                    }
            elif resp.status_code in (404, 429):
                EXHAUSTED_MODELS.add(model)
                continue
            else:
                return {
                    "success": False,
                    "error": f"Gemini API Error [{resp.status_code}]: {resp.text[:200]}"
                }
        except Exception as e:
            return {"success": False, "error": f"Мережева помилка Gemini Vision: {e}"}

    return {"success": False, "error": "Всі моделі Gemini вичерпали квоту або недоступні."}


def match_slip_with_pending_bets(slip_data, pending_bets):
    """
    Зіставляє розпізнані дані купона зі списком активних нерозрахованих ставок у системі.
    Повертає: (best_match_id, confidence_pct, match_details_dict)
    """
    if not slip_data or not slip_data.get("success"):
        return None, 0, {}

    target_match = str(slip_data.get("match_name") or "").lower()
    target_pick = str(slip_data.get("pick_label") or "").lower()
    target_odds = float(slip_data.get("odds") or 0.0)

    # Витягуємо ключові слова з назви матчу (назви команд/гравців)
    words = [w.strip() for w in re.split(r"[\s\-_–—]+", target_match) if len(w.strip()) > 3]

    best_bet = None
    best_score = 0
    best_info = {}

    for bet in (pending_bets or []):
        score = 0
        b_name = str(bet.get("match_name") or "").lower()
        b_pick = str(bet.get("pick_label") or "").lower()
        b_odds = float(bet.get("odds") or 0.0)

        # 1. Співпадіння за назвами команд
        name_matches = sum(1 for w in words if w in b_name)
        if name_matches >= 2:
            score += 60
        elif name_matches == 1:
            score += 35

        # 2. Співпадіння за маркетом ставки
        if target_pick and b_pick:
            clean_tp = re.sub(r"[()+\s]", "", target_pick)
            clean_bp = re.sub(r"[()+\s]", "", b_pick)
            if clean_tp == clean_bp:
                score += 30
            elif (clean_tp in clean_bp) or (clean_bp in clean_tp):
                score += 20
            elif target_pick[:2] == b_pick[:2]:
                score += 15

        # 3. Близькість коефіцієнта (±15%)
        if target_odds > 1.0 and b_odds > 1.0:
            diff = abs(target_odds - b_odds)
            if diff <= 0.05:
                score += 10
            elif diff <= 0.20:
                score += 5

        if score > best_score:
            best_score = score
            best_bet = bet
            best_info = {
                "matched_name": bet.get("match_name"),
                "matched_pick": bet.get("pick_label"),
                "matched_odds": bet.get("odds"),
                "score": score
            }

    if best_bet and best_score >= 40:
        return best_bet.get("id"), best_score, best_info

    return None, best_score, best_info


def apply_slip_to_bet(cur, conn, bet_id, slip_data, image_path=None):
    """
    Прив'язує розпізнаний купон до ставки, позначаючи її як реальну.
    """
    try:
        from statmonitor.real_bankroll import toggle_real_bet
        raw_stk = float(slip_data.get("stake_uah", 0) or 0)
        real_stake = float(round(raw_stk)) if raw_stk > 0 else 0.0
        real_odds = float(slip_data.get("odds", 0) or 0)
        bookmaker = slip_data.get("bookmaker")

        meta = {
            "ticket_id": slip_data.get("ticket_id"),
            "ocr_match": slip_data.get("match_name"),
            "ocr_pick": slip_data.get("pick_label"),
            "potential_win_uah": slip_data.get("potential_win_uah"),
            "image_path": image_path
        }
        if bookmaker:
            meta["bookmaker"] = bookmaker

        ok, msg = toggle_real_bet(
            cur, conn, bet_id,
            is_real=True,
            real_stake=real_stake if real_stake > 0 else None,
            real_odds=real_odds if real_odds > 1.0 else None,
            bookmaker=bookmaker,
            slip_meta=meta
        )
        return ok, msg
    except Exception as e:
        return False, f"Помилка прив'язки купона до ставки #{bet_id}: {e}"
