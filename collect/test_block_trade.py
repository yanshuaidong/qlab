"""大宗交易采集测试，无需联网或真实数据库。"""

import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from collect import block_trade as bt


def frame(*rows):
    return pd.DataFrame(rows, columns=bt.FIELDS)


ROW = ("000001.SZ", "20260924", 10.0, 20.0, 200.0, "买方", "卖方")


class BlockTradeTest(unittest.TestCase):
    def setUp(self):
        self.conn = bt.init_db(Path(":memory:"))
        self.addCleanup(self.conn.close)

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM block_trade").fetchone()[0]

    def test_preserves_identical_trades_and_rerun_is_idempotent(self):
        data = frame(ROW, ROW, (*ROW[:2], 11.0, *ROW[3:]))
        self.assertEqual(bt.replace_day(self.conn, "20260924", data), 3)
        bt.replace_day(self.conn, "20260924", data.iloc[::-1])
        self.assertEqual(self.count(), 3)
        self.assertEqual(self.conn.execute("SELECT MIN(trade_date), MAX(record_no) FROM block_trade").fetchone(), ("2026-09-24", 3))

    def test_replaces_only_requested_day(self):
        bt.replace_day(self.conn, "20260924", frame(ROW, ROW))
        bt.replace_day(self.conn, "20260923", frame((ROW[0], "20260923", *ROW[2:])))
        bt.replace_day(self.conn, "20260924", frame(ROW))
        self.assertEqual(self.count(), 2)

    def test_invalid_or_empty_response_preserves_existing_rows(self):
        bt.replace_day(self.conn, "20260924", frame(ROW))
        for data in (frame(), frame((ROW[0], "20260923", *ROW[2:])), frame((None, *ROW[1:])), frame((ROW[0], ROW[1], "invalid", *ROW[3:]))):
            with self.subTest(data=data), self.assertRaises(ValueError):
                bt.replace_day(self.conn, "20260924", data)
            self.assertEqual(self.count(), 1)

    def test_insert_failure_rolls_back_delete(self):
        bt.replace_day(self.conn, "20260924", frame(ROW))
        self.conn.execute("CREATE TRIGGER reject_trade BEFORE INSERT ON block_trade BEGIN SELECT RAISE(ABORT, 'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            bt.replace_day(self.conn, "20260924", frame(ROW, ROW))
        self.assertEqual(self.count(), 1)

    @patch.object(bt, "PAGE_SIZE", 2)
    @patch.object(bt, "call_api")
    def test_pagination_keeps_identical_rows(self, api):
        api.side_effect = [frame(ROW, ROW), frame(ROW)]
        self.assertEqual(len(bt.fetch_day(None, "20260924")), 3)
        self.assertEqual([c.kwargs["offset"] for c in api.call_args_list], [0, 2])
        self.assertEqual([c.kwargs["limit"] for c in api.call_args_list], [2, 2])

    @patch.object(bt, "PAGE_SIZE", 2)
    @patch.object(bt, "call_api")
    def test_exact_page_boundary_requests_empty_page(self, api):
        api.side_effect = [frame(ROW, ROW), frame()]
        self.assertEqual(len(bt.fetch_day(None, "20260924")), 2)
        self.assertEqual(api.call_count, 2)

    @patch.object(bt, "PAGE_SIZE", 2)
    @patch.object(bt, "call_api")
    def test_repeated_page_fails_instead_of_truncating(self, api):
        api.return_value = frame(ROW, ROW)
        with self.assertRaisesRegex(ValueError, "重复分页"):
            bt.fetch_day(None, "20260924")

    @patch.object(bt, "call_api")
    def test_schema_and_date_checks(self, api):
        for data in (frame(ROW).drop(columns="buyer"), frame((ROW[0], "20260923", *ROW[2:]))):
            api.return_value = data
            with self.assertRaises(ValueError):
                bt.fetch_day(None, "20260924")

    @patch.object(bt.requests, "post")
    def test_http_error_is_not_treated_as_empty_data(self, post):
        post.return_value.raise_for_status.side_effect = bt.requests.HTTPError("503")
        with self.assertRaises(bt.requests.HTTPError):
            bt.TushareClient("test-token").query("block_trade", trade_date="20260924")
        post.return_value.json.assert_not_called()

    @patch.object(bt.requests, "post")
    def test_api_error_is_reported(self, post):
        post.return_value.json.return_value = {"code": -1, "msg": "权限不足"}
        with self.assertRaisesRegex(RuntimeError, "权限不足"):
            bt.TushareClient("test-token").query("block_trade")

    @patch.object(bt.requests, "post")
    def test_https_client_decodes_response(self, post):
        post.return_value.json.return_value = {"code": 0, "data": {"fields": list(bt.FIELDS), "items": [ROW]}}
        data = bt.TushareClient("test-token").query("block_trade", fields=",".join(bt.FIELDS), trade_date="20260924")
        self.assertEqual(len(data), 1)
        self.assertEqual(post.call_args.args[0], "https://api.tushare.pro")
        self.assertEqual(post.call_args.kwargs["json"]["params"], {"trade_date": "20260924"})

    @patch.object(bt, "fetch_day")
    def test_partial_failure_is_reported_and_existing_day_preserved(self, fetch):
        bt.replace_day(self.conn, "20260923", frame((ROW[0], "20260923", *ROW[2:])))
        fetch.side_effect = [RuntimeError("network"), frame(ROW)]
        rows, status, message = bt.collect(None, self.conn, ["20260923", "20260924"])
        self.assertEqual((rows, status), (1, "partial"))
        self.assertIn("20260923", message)
        self.assertEqual(self.count(), 2)


if __name__ == "__main__":
    unittest.main()
