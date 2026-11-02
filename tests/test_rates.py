"""Run: .venv/bin/python -m unittest discover tests   (from the tool folder). No network, Chrome or Parity Manager needed."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mp_rates  # noqa: E402


class ParseRate(unittest.TestCase):
    def test_ota_texts_seen_in_a_real_results_file(self):
        for text, want in [("$161 nightly", 161), ("Per night $ 160 $ 160", 160), ("Per night C$ 153 C$ 155", 153),
                           ("Per night $ 120 $ 124 $ 122", 120), ("CA $132", 132), ("Rs. 2,800", 2800)]:
            self.assertEqual(mp_rates.parse_rate(text), want, text)

    def test_the_lowest_price_wins_when_several_are_listed(self):
        self.assertEqual(mp_rates.parse_rate("Per night $ 124 $ 120 $ 122"), 120)

    def test_nothing_to_read(self):
        self.assertIsNone(mp_rates.parse_rate(""))
        self.assertIsNone(mp_rates.parse_rate("Sold out"))
        self.assertIsNone(mp_rates.parse_rate(None))

    def test_brand_cents_are_kept(self):
        self.assertEqual(mp_rates.parse_brand_rate("$157 34"), 157.34)
        self.assertEqual(mp_rates.parse_brand_rate("96 90"), 96.90)
        self.assertEqual(mp_rates.parse_brand_rate("$144 00"), 144.0)
        self.assertEqual(mp_rates.parse_brand_rate("$1,157 34"), 1157.34)

    def test_brand_text_without_cents_is_left_alone(self):
        self.assertEqual(mp_rates.parse_brand_rate("$157"), 157)
        self.assertEqual(mp_rates.parse_brand_rate("$157.34"), 157.34)
        self.assertEqual(mp_rates.parse_brand_rate("$157 from 3 nights"), 3)   # not a cents pattern: falls back to the lowest number


class PriceAndSoldOut(unittest.TestCase):
    def test_every_currency_seen_in_the_real_files_is_a_price(self):
        for text in ["$ 179", "US$123", "C$ 153", "CA $132", "CAD 150", "Rs 2,800", "₹1450", "﷼269", "SAR 269", "RM 120", "¥ 360", "€ 73",
                     "£ 49", "DKK 750", "MYR 210", "₱ 3,200", "A$ 190", "$161 nightly"]:
            self.assertTrue(mp_rates.looks_like_price(text), text)

    def test_text_that_is_not_a_price(self):
        for text in ["", "nightly", "Per night", "Book now", "2 guests", None]:
            self.assertFalse(mp_rates.looks_like_price(text), text)

    def test_sold_out_wording(self):
        for text in ["Sold out", "We have no rooms available at this property for your trip dates", "No availability for your dates",
                     "This property is fully booked", "Not available for your dates"]:
            self.assertTrue(mp_rates.sold_out(text), text)
        self.assertFalse(mp_rates.sold_out("Great room, free cancellation, $129 per night"))
        self.assertFalse(mp_rates.sold_out(""))

    def test_the_old_scraper_would_have_missed_the_riyal(self):
        old = r"[$€£₹¥]|\b(?:USD|EUR|GBP|CAD|INR|AUD|CHF|JPY|MXN|ZAR|Rs\.?)\b"
        import re
        self.assertIsNone(re.search(old, "﷼269"))
        self.assertTrue(mp_rates.looks_like_price("﷼269"))


class Compare(unittest.TestCase):
    def test_more_than_two_lower_is_an_issue(self):
        self.assertEqual(mp_rates.compare(86, 89)[2], "lower_than_brand")
        self.assertEqual(mp_rates.compare(86, 89)[0], -3)

    def test_two_or_less_is_negligible(self):
        self.assertEqual(mp_rates.compare(87, 89)[2], "lower_than_brand_negligible")
        self.assertEqual(mp_rates.compare(88, 89)[2], "lower_than_brand_negligible")

    def test_not_cheaper(self):
        self.assertEqual(mp_rates.compare(89, 89)[2], "not_lower_than_brand")
        self.assertEqual(mp_rates.compare(95, 89)[2], "not_lower_than_brand")

    def test_cents_decide_close_calls(self):
        self.assertEqual(mp_rates.compare(155, 157.34)[2], "lower_than_brand")                 # 2.34 lower
        self.assertEqual(mp_rates.compare(155, 156.34)[2], "lower_than_brand_negligible")      # 1.34 lower

    def test_missing_rates(self):
        self.assertEqual(mp_rates.compare(None, 89)[2], "ota_rate_missing")
        self.assertEqual(mp_rates.compare(86, None)[2], "brand_rate_missing")


class Audit(unittest.TestCase):
    def test_input_brand_rate_is_used_when_there_is_no_live_one(self):
        import csv, tempfile
        head = ["hotel_name", "OTA_name", "status", "raw_rate_text", "branddotcom_raw_rate_text", "brand_rate", "brand_rate_source",
                "rate_comparison"]
        rows = [["Fallback", "priceline", "ok", "$ 106", "", "106.0", "csv", "not_lower_than_brand"],
                ["NoBrand", "priceline", "ok", "$ 106", "", "", "", "ota_rate_missing"]]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results_t.csv"
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f); w.writerow(head); w.writerows(rows)
            res = mp_rates.audit(path)
        self.assertEqual([c[0] for c in res["changed"]], ["NoBrand"])    # the fallback row agrees with the file; one with no brand rate at all does not

    def test_close_call_is_reported_and_confirmed_rows_stay(self):
        import csv, tempfile
        import server
        head = ["hotel_name", "OTA_name", "status", "raw_rate_text", "branddotcom_raw_rate_text", "rate_comparison", "rate_diff"]
        rows = [["Close", "priceline", "ok", "Per night $ 155 $ 155", "$157 34", "lower_than_brand_negligible", "-2"],
                ["Clear", "expedia", "ok", "$150 nightly", "$157 34", "lower_than_brand", "-7"],
                ["Same", "expedia", "ok", "$160 nightly", "$157 34", "not_lower_than_brand", "3"],
                ["Failed", "expedia", "selector_not_found", "", "", "ota_rate_missing", ""]]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "results_t.csv"
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                f.write("sep=,\n")                       # the scraper's hint line, as plain text
                w = csv.writer(f); w.writerow(head); w.writerows(rows)
            res = server.rates_check(path)
        self.assertEqual(res["rows"], 3)
        self.assertEqual([c["hotel"] for c in res["would_confirm"]], ["Close"])
        self.assertEqual(res["no_longer"], [])
        self.assertEqual(server.rates_check(None)["rows"], 0)


if __name__ == "__main__":
    unittest.main()
