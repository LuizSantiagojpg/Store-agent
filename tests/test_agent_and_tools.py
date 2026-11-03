"""
Automated Test Suite for Empório da Música AI Agent & Tools.

Compatible with both `pytest` and standard library `python -m unittest` / `python tests/test_agent_and_tools.py`.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent import EmporioAgent
from src.tools import EmporioTools


class TestEmporioAgentAndTools(unittest.TestCase):
    def setUp(self) -> None:
        self.tools = EmporioTools()

    def test_violoes_up_to_1000_stock_and_status_separation(self) -> None:
        res = self.tools.search_products(category="Violões", max_price=1000.0)
        avail_ids = {p["product_id"] for p in res["available_products"]}

        # Every returned available product must be active and have stock > 0
        self.assertTrue(all(p["stock_quantity"] > 0 and p["status"] == "active" for p in res["available_products"]))
        self.assertGreaterEqual(res["total_available_in_stock"], 9)

        # Giannini GF-3D (id=96, stock=0) and Shelby SN-7C (id=113, discontinued) must NOT be in available_products
        self.assertNotIn(96, avail_ids)
        self.assertNotIn(113, avail_ids)

        unavail_ids = {p["product_id"] for p in res["unavailable_or_discontinued_matches"]}
        self.assertIn(96, unavail_ids)
        self.assertIn(113, unavail_ids)

    def test_takamine_gd20_price_and_expired_promotion(self) -> None:
        res = self.tools.get_product_details("Takamine GD20")
        self.assertTrue(res["found"])
        prod = res["product"]
        self.assertEqual(prod["product_id"], 95)
        self.assertEqual(prod["original_price_brl"], 2199.0)
        self.assertEqual(prod["stock_quantity"], 5)
        self.assertIsNone(prod["active_promotion"])
        self.assertEqual(len(prod["expired_promotions"]), 1)
        self.assertEqual(prod["expired_promotions"][0]["discount_percent"], 12.0)
        self.assertEqual(prod["pix_price_brl"], 2089.05)

    def test_active_promotion_disables_cumulative_pix_discount(self) -> None:
        res = self.tools.get_product_details("94")
        prod = res["product"]
        self.assertIsNotNone(prod["active_promotion"])
        self.assertEqual(prod["active_promotion"]["discount_percent"], 8.0)
        self.assertEqual(prod["effective_price_brl"], 5519.08)
        self.assertEqual(prod["pix_price_brl"], 5519.08)

    def test_catalog_anomaly_detection_on_products_135_to_144(self) -> None:
        res = self.tools.get_product_details("135")
        prod = res["product"]
        self.assertIsNotNone(prod["data_quality_warning"])
        self.assertIn("Music Man", prod["data_quality_warning"])
        self.assertIn("Fender", prod["data_quality_warning"])

    def test_order_lookup_and_return_eligibility(self) -> None:
        res = self.tools.lookup_customer_orders(order_id=7, reference_date="2026-02-22")
        self.assertTrue(res["found"])
        order = res["orders"][0]
        self.assertEqual(order["customer"]["name"], "Letícia Gonçalves Rocha")
        analysis = order["return_and_warranty_analysis"]
        self.assertTrue(analysis["is_within_7d_withdrawal_or_preference"])
        self.assertTrue(analysis["is_within_30d_defect_exchange"])

        res_later = self.tools.lookup_customer_orders(order_id=7, reference_date="2026-03-25")
        analysis_later = res_later["orders"][0]["return_and_warranty_analysis"]
        self.assertFalse(analysis_later["is_within_7d_withdrawal_or_preference"])
        self.assertTrue(analysis_later["is_within_90d_legal_warranty"])

    def test_out_of_scope_accessory_alert(self) -> None:
        res = self.tools.search_products(query="encordoamento e pedal de guitarra")
        self.assertIsNotNone(res["out_of_scope_accessory_alert"])
        self.assertIn("EXCLUSIVAMENTE com instrumentos musicais", res["out_of_scope_accessory_alert"])

    def test_local_llm_stringified_tool_arguments_coercion(self) -> None:
        """Ensure stringified arguments emitted by 8B local models (Llama 3.1) are properly coerced."""
        res = self.tools.search_products(
            category="Violões",
            query="",
            max_price="1000",  # type: ignore[arg-type]
            min_price="0",  # type: ignore[arg-type]
            has_electronics="False",  # type: ignore[arg-type]
            only_active_promotions="False",  # type: ignore[arg-type]
        )
        self.assertEqual(res["total_available_in_stock"], 12)

    def test_agent_end_to_end_and_session_persistence(self) -> None:
        """Verify end-to-end EmporioAgent chat execution and persistent session history."""
        agent = EmporioAgent(provider="local_deterministic")
        session_id = "unit_test_session"
        agent.memory.clear(session_id)

        out = agent.chat("Quanto custa o Takamine GD20?", session_id=session_id)
        self.assertIn("2,199.00", out["reply"])
        self.assertEqual(len(out["tool_calls"]), 1)
        self.assertEqual(out["tool_calls"][0]["tool"], "get_product_details")

        history = agent.memory.get_history(session_id)
        self.assertEqual(len(history), 2)
        agent.memory.clear(session_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
