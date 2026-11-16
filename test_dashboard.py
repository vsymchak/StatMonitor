from dashboard import compute_metrics, INITIAL_BANKROLL, format_verdict_markdown

def test_format_verdict_markdown():
    raw_html = "📌 <b>Коротка ставка:</b> Ф2 (+1.5)<br>🎯 <b>Рекомендована ставка:</b> Ставити &amp; вигравати!"
    formatted = format_verdict_markdown(raw_html)
    assert "<b>" not in formatted
    assert "</b>" not in formatted
    assert "<br>" not in formatted
    assert "**Коротка ставка:**" in formatted
    assert "&amp;" not in formatted
    assert "&" in formatted

def test_compute_metrics_empty():
    m = compute_metrics([])
    assert m["current_bank"] == INITIAL_BANKROLL
    assert m["net_profit"] == 0.0
    assert m["roi_pct"] == 0.0
    assert m["win_rate"] == 0.0
    assert m["total_bets"] == 0

def test_compute_metrics_with_bets():
    data = [
        {"status": "WON", "stake_uah": 300.0, "profit_uah": 270.0},
        {"status": "LOST", "stake_uah": 200.0, "profit_uah": -200.0},
        {"status": "VOID", "stake_uah": 100.0, "profit_uah": 0.0},
        {"status": "PENDING", "stake_uah": 250.0, "profit_uah": 0.0},
    ]
    m = compute_metrics(data)

    # Net profit: 270 - 200 = 70.0 грн
    assert m["net_profit"] == 70.0
    # Bankroll: 10000 + 70 = 10070.0 грн
    assert m["current_bank"] == 10070.0
    # Turnover: 300 + 200 + 100 = 600 грн
    assert m["turnover"] == 600.0
    # ROI: (70 / 600) * 100% = 11.67%
    assert round(m["roi_pct"], 2) == 11.67
    # Win rate: 1 won / (1 won + 1 lost) = 50.0%
    assert m["win_rate"] == 50.0
    assert m["total_bets"] == 4
    assert m["pending"] == 1

if __name__ == "__main__":
    test_format_verdict_markdown()
    test_compute_metrics_empty()
    test_compute_metrics_with_bets()
    print("Всі тести dashboard успішно пройдено!")
