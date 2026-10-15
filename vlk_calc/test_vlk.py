"""Проверка расчётов на примере из образца процедуры ВЛК (Приложение В)."""

import unittest

from vlk import Params, evaluate, find_signals

P = Params("Аммоний-ион", "мг/дм³", sigma_r=4, sigma_R=6, delta_lab=12.6)


class TestChecks(unittest.TestCase):
    def test_repeatability(self):
        c = evaluate({"вид": "повт", "x1": "1,32", "x2": "1,25"}, 1, P)
        self.assertAlmostEqual(c.value, 0.07)
        self.assertAlmostEqual(c.rel, 5.45, places=2)
        self.assertTrue(c.ok)

    def test_reference_sample(self):
        c = evaluate({"вид": "ок", "x1": "2,11", "c": "2,00"}, 1, P)
        self.assertAlmostEqual(c.value, 0.11)
        self.assertAlmostEqual(c.norm, 0.252)
        self.assertTrue(c.ok)

    def test_addition(self):
        c = evaluate({"вид": "доб", "x1": "1,285", "xd1": "3,20", "c": "2,00"}, 1, P)
        self.assertAlmostEqual(c.value, 0.085)
        self.assertAlmostEqual(c.norm, 0.434, places=3)
        self.assertTrue(c.ok)

    def test_failed_check(self):
        c = evaluate({"вид": "ок", "x1": "2,30", "c": "2,00"}, 1, P)
        self.assertFalse(c.ok)

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            evaluate({"вид": "xyz", "x1": "1"}, 1, P)


class TestSignals(unittest.TestCase):
    cl, warn, action = 4.5, 11.3, 14.7

    def signals(self, values, two_sided=False):
        return find_signals(values, self.cl, self.warn, self.action, two_sided)

    def test_stable(self):
        self.assertEqual(self.signals([3, 6, 2, 12, 5, 1, 7, 4]), {})

    def test_action_limit(self):
        self.assertIn(3, self.signals([3, 5, 15, 2]))

    def test_two_of_three_warning(self):
        s = self.signals([3, 12, 5, 12.5, 2])
        self.assertIn("2 из 3 точек за пределом предупреждения", s[4])

    def test_two_of_three_other_sides_ignored(self):
        self.assertEqual(self.signals([12, 2, -12], two_sided=True), {})

    def test_nine_on_one_side(self):
        s = self.signals([5, 6, 7, 5, 6, 8, 5, 6, 7])
        self.assertIn(9, s)

    def test_six_monotonic(self):
        s = self.signals([1, 2, 3, 4, 5, 6])
        self.assertIn("6 точек подряд монотонно растут или убывают", s[6])


if __name__ == "__main__":
    unittest.main()
