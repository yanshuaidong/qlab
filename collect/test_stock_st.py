"""ST 名单和变更采集测试，无需联网。"""

import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from collect import stock_st as st


def frame(columns, *rows):
    return pd.DataFrame(rows, columns=columns)


STOCK = ("300125.SZ", "聆达股份", "20260807", "ST", "风险警示板")
EVENT = (
    "300125.SZ",
    "聆达股份",
    "20260806",
    "20260807",
    "撤销*ST",
    "撤销退市风险警示",
    "公司股票撤销退市风险警示",
)


class StockStTest(unittest.TestCase):
    def setUp(self):
        self.conn = st.init_db(Path(":memory:"))
        self.addCleanup(self.conn.close)

    def test_stock_st_day_is_replaced_and_dates_are_normalized(self):
        data = frame(st.STOCK_ST_FIELDS, STOCK, ("000001.SZ", "*ST平安", "20260807", "ST", "风险警示板"))
        self.assertEqual(st.replace_stock_st_day(self.conn, "20260807", data), 2)
        st.replace_stock_st_day(self.conn, "20260807", frame(st.STOCK_ST_FIELDS, STOCK))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stock_st").fetchone()[0], 1)
        self.assertEqual(
            self.conn.execute("SELECT trade_date, name FROM stock_st").fetchone(),
            ("2026-08-07", "聆达股份"),
        )

    def test_empty_stock_st_keeps_existing_day(self):
        st.replace_stock_st_day(self.conn, "20260807", frame(st.STOCK_ST_FIELDS, STOCK))
        with self.assertRaisesRegex(ValueError, "空名单"):
            st.replace_stock_st_day(self.conn, "20260807", frame(st.STOCK_ST_FIELDS))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stock_st").fetchone()[0], 1)
        self.assertEqual(st.replace_stock_st_day(self.conn, "20260806", frame(st.STOCK_ST_FIELDS)), 0)

    def test_st_events_upsert_by_identity(self):
        rows = frame(st.ST_FIELDS, EVENT, (*EVENT[:4], "叠加*ST", "叠加", "说明"))
        self.assertEqual(st.upsert_st_rows(self.conn, rows), 2)
        revised = frame(st.ST_FIELDS, (*EVENT[:5], "原因已修订", EVENT[6]))
        self.assertEqual(st.upsert_st_rows(self.conn, revised), 1)
        stored = self.conn.execute(
            "SELECT pub_date, imp_date, st_reason FROM st WHERE st_type='撤销*ST'"
        ).fetchone()
        self.assertEqual(stored, ("2026-08-06", "2026-08-07", "原因已修订"))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM st").fetchone()[0], 2)

    def test_st_event_requires_dates_and_type(self):
        broken = frame(st.ST_FIELDS, (*EVENT[:3], None, *EVENT[4:]))
        with self.assertRaisesRegex(ValueError, "imp_date"):
            st.upsert_st_rows(self.conn, broken)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM st").fetchone()[0], 0)

    @patch.object(st, "PAGE_SIZE", 1)
    @patch.object(st, "call_api")
    def test_stock_st_pagination(self, api):
        first = frame(st.STOCK_ST_FIELDS, STOCK)
        second = frame(st.STOCK_ST_FIELDS, ("000010.SZ", "ST美丽", "20260807", "ST", "风险警示板"))
        api.side_effect = [first, second, frame(st.STOCK_ST_FIELDS)]
        result = st.fetch_pages(None, "stock_st", st.STOCK_ST_FIELDS, "trade_date", "20260807", trade_date="20260807")
        self.assertEqual(len(result), 2)
        self.assertEqual([call.kwargs["offset"] for call in api.call_args_list], [0, 1, 2])

    @patch.object(st, "PAGE_SIZE", 1)
    @patch.object(st, "call_api")
    def test_repeated_page_is_rejected(self, api):
        api.return_value = frame(st.STOCK_ST_FIELDS, STOCK)
        with self.assertRaisesRegex(ValueError, "重复分页"):
            st.fetch_pages(None, "stock_st", st.STOCK_ST_FIELDS, "trade_date", "20260807", trade_date="20260807")

    def test_slice_resume_skips_completed_days(self):
        st.mark_slice(self.conn, "stock_st", "20260807", 1, "ok")
        self.conn.commit()

        def fail_fetch(*_args, **_kwargs):
            raise AssertionError("已完成的日期不应再次请求")

        with patch.object(st, "fetch_pages", fail_fetch):
            rows, status, message = st.collect_stock_st(None, self.conn, ["20260807"])
        self.assertEqual((rows, status, message), (0, "ok", ""))

    def test_insert_failure_rolls_back_stock_st_replace(self):
        st.replace_stock_st_day(self.conn, "20260807", frame(st.STOCK_ST_FIELDS, STOCK))
        self.conn.execute(
            "CREATE TRIGGER reject_stock_st BEFORE INSERT ON stock_st BEGIN SELECT RAISE(ABORT, 'test'); END"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            st.replace_stock_st_day(
                self.conn,
                "20260807",
                frame(st.STOCK_ST_FIELDS, STOCK, ("000010.SZ", "ST美丽", "20260807", "ST", "风险警示板")),
            )
        self.assertEqual(
            self.conn.execute("SELECT name FROM stock_st").fetchone()[0],
            "聆达股份",
        )


if __name__ == "__main__":
    unittest.main()
