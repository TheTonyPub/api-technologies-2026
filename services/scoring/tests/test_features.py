import unittest
from datetime import date

from app.features import build_features, full_months

C = {"inn": "1", "reg_date": date(2015, 3, 15), "okved": "62.01", "status": "ACTIVE"}


class FeaturesTests(unittest.TestCase):
    def test_full_months_boundary(self):
        self.assertEqual(full_months(date(2026, 3, 15), date(2026, 4, 14)), 0)
        self.assertEqual(full_months(date(2026, 3, 15), date(2026, 4, 15)), 1)

    def test_group_counts_exclude_self(self):
        members = [{"inn": "1", "is_bank_client": True}, {"inn": "2", "is_bank_client": True},
                   {"inn": "3", "is_bank_client": False}]
        num, cat = build_features(C, members, date(2026, 11, 7))
        self.assertEqual((num["groupSize"], num["groupBankClientsCount"]), (3.0, 1.0))
        self.assertEqual(cat, {"mainActivityCode": "62.01", "status": "ACTIVE"})

    def test_no_group(self):
        num, _ = build_features(C, None, date(2026, 11, 7))
        self.assertEqual((num["groupSize"], num["groupBankClientsCount"]), (0.0, 0.0))


    def test_seed_company_age(self):
        # 9990000001 из db/dev/seed_snapshot.sql, на 08.11.2026 как раз 175 месяцев (таблица в ТЗ)
        c = {"inn": "9990000001", "reg_date": date(2012, 3, 15), "okved": "64.19", "status": "ACTIVE"}
        num, _ = build_features(c, None, date(2026, 11, 8))
        self.assertEqual(num["companyAgeMonths"], 175.0)

    def test_missing_reg_date(self):
        num, _ = build_features({**C, "reg_date": None}, None, date(2026, 11, 7))
        self.assertEqual(num["companyAgeMonths"], 0.0)


if __name__ == "__main__":
    unittest.main()
