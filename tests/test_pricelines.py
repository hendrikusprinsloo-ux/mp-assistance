"""Run: .venv/bin/python -m unittest discover tests   (from the tool folder). No network or Chrome needed: only the parts that do not touch a page."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mp_pricelines as pl  # noqa: E402


class Url(unittest.TestCase):
    def test_currency_is_added_to_the_url(self):
        out = pl.with_currency("https://www.priceline.com/relax/at/123?checkin=20261102&adults=2", "cad")
        self.assertIn("cur=CAD", out)
        self.assertIn("adults=2", out)

    def test_existing_currency_is_replaced_not_doubled(self):
        out = pl.with_currency("https://www.priceline.com/relax/at/123?cur=USD&x=1", "GBP")
        self.assertEqual(out.count("cur="), 1)
        self.assertIn("cur=GBP", out)

    def test_no_currency_leaves_the_url_alone(self):
        url = "https://www.priceline.com/relax/at/123?x=1"
        self.assertEqual(pl.with_currency(url, ""), url)


class Lowest(unittest.TestCase):
    def test_lowest_public_price_wins(self):
        self.assertEqual(pl.pick_lowest(["$ 124", "$ 120", "$ 122"]), (120, "$ 120"))

    def test_member_and_non_price_text_is_left_out(self):
        self.assertEqual(pl.pick_lowest(["Member price $ 90", "$ 120", "Book now"]), (120, "$ 120"))

    def test_nothing_found(self):
        self.assertIsNone(pl.pick_lowest([]))
        self.assertIsNone(pl.pick_lowest(["Book now", "Member price $ 90"]))

    def test_the_price_location_names_the_room_options_heading(self):
        xp = pl.price_xpath("$€")
        self.assertIn("Room Options", xp)
        self.assertIn("contains(., '$') or contains(., '€')", xp)


class FakePage:
    """Just enough of a Playwright page to run read_row without a browser."""
    def __init__(self, body, prices):
        self.url, self.body, self.prices = "https://www.priceline.com/relax/at/1", body, prices
    def goto(self, *a, **k): pass
    def wait_for_timeout(self, ms): pass
    def evaluate(self, js): return self.body
    def locator(self, sel):
        outer = self
        class L:
            def all_inner_texts(self): return outer.prices
        return L()
    def screenshot(self, **k): pass
    def close(self): pass


class FakeCtx:
    def __init__(self, page): self.page = page
    def new_page(self): return self.page


class ReadRow(unittest.TestCase):
    ROW = {"hotel_name": "H", "currency": "USD", "from_date": "11/6/26", "url": "https://x/redirect/?ota=priceline"}

    def setUp(self):
        self.waits = pl.WAITS
        pl.WAITS = (0,)

    def tearDown(self):
        pl.WAITS = self.waits

    def test_a_price_wins_over_sold_out_wording_elsewhere_on_the_page(self):
        page = FakePage("Rooms from... Sold out nearby hotels... Per night $ 160", ["Per night $ 160 $ 160"])
        out = pl.read_row(self.ROW, FakeCtx(page))
        self.assertEqual((out["status"], out["rate"]), ("ok", 160))
        self.assertEqual(out["sold_out_wording"], "Sold out")             # reported, but it did not decide the status

    def test_elements_without_text_are_ignored(self):
        out = pl.read_row(self.ROW, FakeCtx(FakePage("Rooms", [None, "", "  ", "Per night $ 160 $ 160", None])))
        self.assertEqual((out["status"], out["rate"]), ("ok", 160))
        self.assertEqual(pl.pick_lowest([None, "$ 120"]), (120, "$ 120"))        # a None in the list does not raise

    def test_no_price_and_sold_out_wording_is_sold_out(self):
        out = pl.read_row(self.ROW, FakeCtx(FakePage("We have no rooms available at this property for your trip dates", [])))
        self.assertEqual(out["status"], "sold_out")

    def test_no_price_and_no_wording_is_selector_not_found(self):
        out = pl.read_row(self.ROW, FakeCtx(FakePage("Loading", [])))
        self.assertEqual(out["status"], "selector_not_found")

    def test_page_text_is_saved_when_asked(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = pl.read_row(self.ROW, FakeCtx(FakePage("Hello page", [])), save_to=tmp)
            self.assertEqual(Path(out["saved_to"]).read_text(), "Hello page")


if __name__ == "__main__":
    unittest.main()
