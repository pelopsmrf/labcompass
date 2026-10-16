"""Тесты кабинета: python3 -m unittest test_app (нужны пакеты из requirements.txt и httpx)."""
import os
import re
import tempfile
import unittest
from datetime import date, timedelta

os.environ.update(DB_PATH=os.path.join(tempfile.mkdtemp(), "t.db"), SMTP_HOST="", ADMIN_EMAILS="boss@lab.ru",
                  FREE_LIMIT="3", COOKIE_SECURE="0")

from fastapi.testclient import TestClient  # noqa: E402

import equipment as eq  # noqa: E402
import mailer  # noqa: E402
import main  # noqa: E402
import remind  # noqa: E402


def login(client, email):
    client.post("/app/login", data={"email": email, "consent": "1"})
    code = re.search(r"\d{6}", mailer.sent[-1]["Subject"]).group()
    return client.post("/app/verify", data={"email": email, "code": code}, follow_redirects=False)


class TestEquipment(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(eq.add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(eq.parse_date("15.03.2026"), date(2026, 3, 15))
        self.assertEqual(eq.parse_interval("2 года"), 24)
        self.assertEqual(eq.next_due(date(2026, 3, 15), 12), date(2027, 3, 15))
        t = date(2026, 10, 16)
        self.assertEqual(eq.status("2026-10-15", t), ("overdue", -1))
        self.assertEqual(eq.status("2026-11-10", t)[0], "soon")
        self.assertEqual(eq.status("2027-01-01", t)[0], "ok")

    def test_paste(self):
        text = ("Наименование\tВид\n"
                "Весы ВЛ-210\tСИ\t1234\t0101\tповерка\t15.03.2026\t12\t\tС-ВЯ/1\n"
                "Термостат ТС-1/80\tиспыт.\t55\t\tаттестация\t01.02.2026\t1 год\n"
                "Плохая\tСИ\t\t\t\t32.13.2026\n")
        items, errors = eq.parse_paste(text)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["next_date"], "2027-03-15")
        self.assertEqual(items[1]["kind"], "ИО")
        self.assertEqual(items[1]["service"], "аттестация")
        self.assertEqual(len(errors), 1)


class TestApp(unittest.TestCase):
    def setUp(self):
        self.c = TestClient(main.app, base_url="http://testserver")

    def test_login_wrong_code_and_limits(self):
        r = self.c.post("/app/login", data={"email": "a@lab.ru"})
        self.assertEqual(r.status_code, 400)  # без согласия
        self.c.post("/app/login", data={"email": "a@lab.ru", "consent": "1"})
        r = self.c.post("/app/verify", data={"email": "a@lab.ru", "code": "000000x"})
        self.assertIn("Неверный код", r.text)
        r = self.c.post("/app/login", data={"email": "a@lab.ru", "consent": "1"})
        self.assertIn("через минуту", r.text)  # повторный код не раньше чем через минуту

    def test_flow(self):
        r = self.c.get("/app/equipment", follow_redirects=False)
        self.assertEqual(r.headers["location"], "/app/login")
        r = login(self.c, "Lab@Example.ru")
        self.assertEqual(r.headers["location"], "/app/profile")
        self.c.post("/app/profile", data={"org": "ИЛ Водоканал", "remind": "1"})
        soon = (date.today() + timedelta(days=7)).isoformat()
        r = self.c.post("/app/equipment/new", data={"name": "pH-метр", "kind": "СИ", "service": "поверка",
                                                    "next_date": soon, "interval_months": "12"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("pH-метр", r.text)
        self.assertIn("Скоро срок", r.text)
        r = self.c.post("/app/import", data={"text": "Весы\tСИ\t1\t\tповерка\t01.01.2026\t12\nПечь\tИО"})
        self.assertIn("Весы", r.text)
        r = self.c.post("/app/equipment/new", data={"name": "Четвёртое"})
        self.assertIn("бесплатном тарифе", r.text)  # лимит 3
        x = self.c.get("/app/equipment.xlsx")
        self.assertEqual(x.content[:2], b"PK")
        # чужая лаборатория не видит записи
        other = TestClient(main.app, base_url="http://testserver")
        login(other, "other@lab.ru")
        self.assertNotIn("pH-метр", other.get("/app/equipment").text)
        self.assertEqual(other.get("/app/equipment/1").status_code, 404)
        self.assertEqual(other.get("/app/admin").status_code, 403)
        # напоминание: срок через 7 дней
        mailer.sent.clear()
        self.assertGreaterEqual(remind.run(), 1)
        self.assertIn("pH-метр", mailer.sent[-1].get_content())
        # админ включает подписку → лимит снят
        admin = TestClient(main.app, base_url="http://testserver")
        login(admin, "boss@lab.ru")
        self.assertIn("lab@example.ru", admin.get("/app/admin").text)
        uid = main.db.connect().execute("SELECT id FROM users WHERE email='lab@example.ru'").fetchone()[0]
        admin.post(f"/app/admin/{uid}", data={"paid_until": "2099-01-01"})
        r = self.c.post("/app/equipment/new", data={"name": "Четвёртое"})
        self.assertIn("Четвёртое", r.text)

    def test_foreign_origin(self):
        r = self.c.post("/app/login", data={"email": "x@lab.ru", "consent": "1"},
                        headers={"origin": "https://evil.example"})
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
