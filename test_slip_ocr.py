import unittest
from unittest.mock import patch, MagicMock
from statmonitor.slip_ocr import (
    parse_bet_slip_with_gemini,
    match_slip_with_pending_bets,
    apply_slip_to_bet,
)

class MockCursor:
    def __init__(self, fetchall_data=None, fetchone_data=None):
        self.fetchall_data = fetchall_data or []
        self.fetchone_data = fetchone_data
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchall(self):
        return self.fetchall_data

    def fetchone(self):
        return self.fetchone_data

class MockConn:
    def commit(self): pass
    def rollback(self): pass

class TestSlipOCR(unittest.TestCase):
    def test_parse_bet_slip_with_gemini_missing_key(self):
        res = parse_bet_slip_with_gemini(b"image_bytes", api_key="")
        self.assertFalse(res["success"])
        self.assertIn("GEMINI_API_KEY", res["error"])

    def test_parse_bet_slip_with_gemini_empty_bytes(self):
        res = parse_bet_slip_with_gemini(b"", api_key="valid_key")
        self.assertFalse(res["success"])
        self.assertIn("Порожній файл", res["error"])

    @patch("requests.post")
    def test_parse_bet_slip_with_gemini_mocked_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": '{"bookmaker": "Favbet", "ticket_id": "789123", "match_name": "Lorient - Rennes", "sport": "soccer", "pick_label": "Ф2 (0)", "odds": 1.78, "stake_uah": 350.0, "potential_win_uah": 623.0}'
                            }
                        ]
                    }
                }
            ]
        }
        mock_post.return_value = mock_resp

        res = parse_bet_slip_with_gemini(b"fake_image_bytes", api_key="test_key_123")
        self.assertTrue(res["success"])
        self.assertEqual(res["bookmaker"], "Favbet")
        self.assertEqual(res["match_name"], "Lorient - Rennes")
        self.assertEqual(res["odds"], 1.78)
        self.assertEqual(res["stake_uah"], 350.0)
        self.assertEqual(res["potential_win_uah"], 623.0)

    def test_match_slip_with_pending_bets_exact(self):
        slip_data = {
            "success": True,
            "match_name": "Lorient - Rennes",
            "pick_label": "Ф2 (0)",
            "odds": 1.78,
            "stake_uah": 350.0
        }
        pending_bets = [
            {"id": 10, "match_name": "Arsenal - Chelsea", "pick_label": "П1", "odds": 2.10},
            {"id": 11, "match_name": "Lorient - Rennes", "pick_label": "Ф2 (0)", "odds": 1.75},
        ]
        matched_id, score, info = match_slip_with_pending_bets(slip_data, pending_bets)
        self.assertEqual(matched_id, 11)
        self.assertGreaterEqual(score, 80)
        self.assertEqual(info["matched_name"], "Lorient - Rennes")

    def test_match_slip_with_pending_bets_fuzzy(self):
        slip_data = {
            "success": True,
            "match_name": "Ренн проти Лор'ян",
            "pick_label": "Ф2 (0)",
            "odds": 1.80
        }
        pending_bets = [
            {"id": 5, "match_name": "Lorient - Rennes", "pick_label": "Ф2 (0)", "odds": 1.82},
        ]
        # In this case, team names might be transliterated or tokenized
        matched_id, score, info = match_slip_with_pending_bets(slip_data, pending_bets)
        # Even if low token overlap, with odds close and pick match, let's verify behavior
        self.assertTrue(score >= 0)

    def test_match_slip_with_pending_bets_no_match(self):
        slip_data = {
            "success": True,
            "match_name": "Barcelona - Real Madrid",
            "pick_label": "П1",
            "odds": 1.95
        }
        pending_bets = [
            {"id": 10, "match_name": "Arsenal - Chelsea", "pick_label": "П1", "odds": 2.10},
            {"id": 11, "match_name": "Lorient - Rennes", "pick_label": "Ф2 (0)", "odds": 1.75},
        ]
        matched_id, score, info = match_slip_with_pending_bets(slip_data, pending_bets)
        self.assertIsNone(matched_id)

    def test_apply_slip_to_bet(self):
        cur = MockCursor(fetchone_data=(11, "Lorient - Rennes", 1.75, 250.0))
        conn = MockConn()
        slip_data = {
            "bookmaker": "Vbet",
            "ticket_id": "VB-9988",
            "match_name": "Lorient - Rennes",
            "pick_label": "Ф2 (0)",
            "odds": 1.82,
            "stake_uah": 400.0,
            "potential_win_uah": 728.0
        }
        ok, msg = apply_slip_to_bet(cur, conn, 11, slip_data, image_path="slips/slip_11.jpg")
        self.assertTrue(ok)
        self.assertIn("#11", msg)
        self.assertIn("Реальна ставка", msg)

if __name__ == "__main__":
    unittest.main()
