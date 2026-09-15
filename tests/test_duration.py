"""Human duration grammar and exact component arithmetic."""

from decimal import Decimal, localcontext
import unittest

from burnbag_duration import parse_duration


class DurationTests(unittest.TestCase):
    def assert_duration(self, text, **expected):
        self.assertEqual(parse_duration(text), {
            unit: Decimal(str(value)) for unit, value in expected.items()})

    def test_requested_five_hour_spellings(self):
        for text in ("5h", "5H", "5 h", "5 H", "5 hours", "five hours",
                     "5:00:00", "05:00:00"):
            with self.subTest(text=text):
                self.assert_duration(text, hours=5)

    def test_two_clock_fields_mean_minutes_and_seconds(self):
        self.assert_duration("5:00", minutes=5)
        self.assert_duration("05:12.125", minutes=5, seconds="12.125")
        self.assert_duration("0:00.1", seconds="0.1")
        self.assert_duration("100:59", minutes=100, seconds=59)

    def test_three_clock_fields_allow_long_hours_and_fractional_seconds(self):
        self.assert_duration("1000:59:59.5", hours=1000, minutes=59, seconds="59.5")
        self.assert_duration("1:2:3", hours=1, minutes=2, seconds=3)

    def test_all_units_and_common_abbreviations_are_case_insensitive(self):
        cases = {
            "seconds": ("s", "sec", "secs", "second", "seconds"),
            "minutes": ("m", "min", "mins", "minute", "minutes"),
            "hours": ("h", "hr", "hrs", "hour", "hours"),
            "days": ("d", "day", "days"),
            "weeks": ("w", "wk", "wks", "week", "weeks"),
            "months": ("mo", "mos", "mon", "month", "months"),
            "years": ("y", "yr", "yrs", "year", "years"),
            "decades": ("dec", "decade", "decades"),
            "centuries": ("c", "cent", "century", "centuries"),
            "millennia": ("mil", "millennium", "millennia", "millenniums",
                          "millenium", "millenia", "milleniums"),
        }
        for unit, aliases in cases.items():
            for alias in aliases:
                for spelling in (alias, alias.upper(), alias.capitalize()):
                    with self.subTest(spelling=spelling):
                        self.assert_duration("2 " + spelling, **{unit: 2})

    def test_minute_and_month_abbreviations_are_distinct(self):
        self.assert_duration("5M 5MO", minutes=5, months=5)

    def test_decimal_quantities_remain_exact(self):
        self.assert_duration(".5h", hours="0.5")
        self.assert_duration("0.1 seconds 0.2 seconds", seconds="0.3")
        self.assert_duration("2.75 days .25 months", days="2.75", months="0.25")

    def test_additive_compounds_and_repeated_units(self):
        cases = ("1h30m", "1 hour 30 minutes", "one hour and thirty minutes",
                 "one hour, thirty minutes", "one hour, and thirty minutes",
                 "0.5h 30min .5h", "  One\tHOUR\nThirty MINUTES  ")
        for text in cases:
            with self.subTest(text=text):
                self.assert_duration(text, hours=1, minutes=30)

    def test_english_small_quantities(self):
        cases = (("one", 1), ("nine", 9), ("ten", 10), ("eleven", 11),
                 ("fifteen", 15), ("nineteen", 19), ("twenty", 20),
                 ("thirty-five", 35), ("forty two", 42), ("ninety-nine", 99))
        for words, amount in cases:
            with self.subTest(words=words):
                self.assert_duration(words + " seconds", seconds=amount)

    def test_english_hundreds_with_and_without_conjunction(self):
        cases = (("one hundred", 100), ("three hundred one", 301),
                 ("three hundred and one", 301),
                 ("nine hundred and ninety-nine", 999))
        for words, amount in cases:
            with self.subTest(words=words):
                self.assert_duration(words + " minutes", minutes=amount)

    def test_english_descending_scales(self):
        cases = (("one thousand", 1000), ("one thousand and five", 1005),
                 ("one million two hundred thousand thirty-one", 1200031),
                 ("nine hundred ninety-nine trillion one billion two million three thousand four", 999001002003004),
                 ("one quintillion", 10 ** 18))
        for words, amount in cases:
            with self.subTest(words=words):
                self.assert_duration(words + " seconds", seconds=amount)

    def test_zero_components_allowed_when_duration_is_positive(self):
        self.assert_duration("zero hours five minutes zero seconds", minutes=5)
        self.assert_duration("0h .1s", seconds=".1")

    def test_rejects_empty_and_zero_durations(self):
        for text in ("", "   ", "0s", "zero hours", "0 hours zero minutes", "0:00", "00:00:00.0", None):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "empty|greater than zero"):
                    parse_duration(text)

    def test_rejects_invalid_clock_fields(self):
        for text in ("5:60", "5:00:60", "5:60:00", "5:", ":05", "1:2:3:4", "1.5:00",
                     "5:00 hours", "5 : 00", "1:00:-1", "5:000", "1:00:00."):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError, "Clock duration"):
                    parse_duration(text)

    def test_rejects_signed_nonfinite_and_unsupported_numeric_formats(self):
        for text in ("-5h", "+5h", "NaN hours", "Infinity hours", "inf s", "1e3 s", "0x10 h",
                     "1. hours", "1..5h", "1/2h", "1,000h", "５h", "2² hours"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_duration(text)

    def test_rejects_missing_quantities_units_and_trailing_garbage(self):
        for text in ("5", "five", "hours", "5 fortnights", "5h junk", "5h 30", "fivehours",
                     "5h30", "h5", "5h!", "5h,", "5h and", "5h,, 1m", "5h and and 1m"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_duration(text)

    def test_rejects_ambiguous_or_malformed_english_quantities(self):
        cases = ("one two", "twenty thirteen", "one hundred hundred", "one and two",
                 "one thousand thousand", "one million one billion", "zero hundred",
                 "zero thousand", "one hundred and", "hundred", "one thousand and",
                 "one-hundred", "twenty--five", "one hundred zero", "one thousand zero",
                 "one 2", "-five", "one million and five thousand")
        for words in cases:
            with self.subTest(words=words):
                with self.assertRaises(ValueError):
                    parse_duration(words + " hours")

    def test_long_finite_values_do_not_overflow_or_depend_on_decimal_context(self):
        quantity = "9" * 400
        with localcontext() as context:
            context.prec = 3
            self.assert_duration(quantity + "s 1s", seconds="1" + "0" * 400)
            self.assert_duration("0." + "0" * 200 + "1s", seconds="0." + "0" * 200 + "1")
        self.assert_duration("9" * 400 + ":00", minutes="9" * 400)

    def test_input_length_is_bounded_before_parsing(self):
        with self.assertRaisesRegex(ValueError, "too long"):
            parse_duration("9" * 1024 + "s")
        with self.assertRaisesRegex(ValueError, "too long"):
            parse_duration(" " * 1024 + "1s")


if __name__ == "__main__":
    unittest.main()
