"""打板专题采集测试，无需联网或真实数据库。"""

import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from collect import board_topic as bt


def frame(rows, columns):
    return pd.DataFrame(rows, columns=columns)


class BoardTopicTest(unittest.TestCase):
    def setUp(self):
        self.conn = bt.init_db(Path(":memory:"))
        self.addCleanup(self.conn.close)

    def test_schema_maps_sql_names_and_can_reopen(self):
        bt.init_db(Path(":memory:"))
        tables = {
            row[0]
            for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertTrue(set(bt.SPECS) <= tables)
        self.assertIn("board_topic_slice", tables)
        self.assertIn("import_log", tables)

        limit_cols = [row[1] for row in self.conn.execute("PRAGMA table_info(limit_list_d)")]
        self.assertIn("limit_flag", limit_cols)
        self.assertNotIn("limit", limit_cols)

        tdx_cols = [row[1] for row in self.conn.execute("PRAGMA table_info(tdx_daily)")]
        self.assertIn("pct_3d", tdx_cols)
        self.assertIn("pct_1y", tdx_cols)
        self.assertNotIn("3day", tdx_cols)
        self.assertNotIn("1year", tdx_cols)

        self.assertIn("intro", [row[1] for row in self.conn.execute("PRAGMA table_info(hm_list)")])
        self.assertNotIn("desc", [row[1] for row in self.conn.execute("PRAGMA table_info(hm_list)")])
        self.assertIn("intro", [row[1] for row in self.conn.execute("PRAGMA table_info(kpl_concept_cons)")])
        self.assertEqual(
            bt.SPECS["ths_hot"]["pk"],
            ("trade_date", "market", "data_type", "ts_code", "rank_time"),
        )

    def test_rename_and_trade_date_format(self):
        limit = frame(
            [("20260924", "000001.SZ", "U")],
            ["trade_date", "ts_code", "limit"],
        )
        prepared = bt.prepare_frame(limit, bt.SPECS["limit_list_d"], {"limit_flag": "Z"}, expect_date="2026-09-24")
        self.assertEqual(prepared.loc[0, "limit_flag"], "U")
        self.assertEqual(prepared.loc[0, "trade_date"], "2026-09-24")

        blank = frame([("20260924", "000001.SZ", None)], ["trade_date", "ts_code", "limit"])
        filled = bt.prepare_frame(blank, bt.SPECS["limit_list_d"], {"limit_flag": "D"}, expect_date="2026-09-24")
        self.assertEqual(filled.loc[0, "limit_flag"], "D")

        hot = frame([("20260924", "000001.SZ", None, "2026-09-24 15:00:00")], ["trade_date", "ts_code", "data_type", "rank_time"])
        hot_row = bt.prepare_frame(hot, bt.SPECS["ths_hot"], {"market": "热股", "data_type": "热股"}, expect_date="2026-09-24")
        self.assertEqual(hot_row.loc[0, "market"], "热股")
        self.assertEqual(hot_row.loc[0, "data_type"], "热股")

        renamed = bt.prepare_frame(
            frame([("880001.TDX", "20260924", 1.25, 9.5)], ["ts_code", "trade_date", "3day", "1year"]),
            bt.SPECS["tdx_daily"],
            expect_date="2026-09-24",
        )
        self.assertEqual(renamed.loc[0, "pct_3d"], 1.25)
        self.assertEqual(renamed.loc[0, "pct_1y"], 9.5)

        names = bt.prepare_frame(
            frame([("赵老哥", "说明", "营业部")], ["name", "desc", "orgs"]),
            bt.SPECS["hm_list"],
        )
        self.assertEqual(names.loc[0, "intro"], "说明")

        saved = bt.upsert_rows(self.conn, "limit_step", frame([("000001.SZ", "平安银行", "20260924", "2")], ["ts_code", "name", "trade_date", "nums"]))
        self.conn.commit()
        self.assertEqual(saved, 1)
        self.assertEqual(
            self.conn.execute("SELECT trade_date, nums FROM limit_step").fetchone(),
            ("2026-09-24", "2"),
        )

    def test_snapshot_upsert_updates_same_name(self):
        row = frame([("赵老哥", "旧说明", "营业部")], ["name", "desc", "orgs"])
        bt.upsert_rows(self.conn, "hm_list", row)
        bt.upsert_rows(self.conn, "hm_list", frame([("赵老哥", "新说明", "新营业部")], ["name", "desc", "orgs"]))
        self.conn.commit()
        self.assertEqual(
            self.conn.execute("SELECT intro, orgs FROM hm_list").fetchall(),
            [("新说明", "新营业部")],
        )

    def test_daily_replace_keeps_duplicates_and_is_idempotent(self):
        rows = frame(
            [
                ("20260924", "000001.SZ", "理由", 1.0),
                ("20260924", "000001.SZ", "理由", 1.0),
                ("20260924", "000002.SZ", "另一理由", 2.0),
            ],
            ["trade_date", "ts_code", "reason", "close"],
        )
        self.assertEqual(bt.replace_rows(self.conn, "top_list", "20260924", rows), 3)
        bt.replace_rows(self.conn, "top_list", "20260924", rows.iloc[::-1])
        self.conn.commit()
        stored = self.conn.execute(
            "SELECT trade_date, record_no, ts_code FROM top_list ORDER BY record_no"
        ).fetchall()
        self.assertEqual(stored, [
            ("2026-09-24", 1, "000001.SZ"),
            ("2026-09-24", 2, "000001.SZ"),
            ("2026-09-24", 3, "000002.SZ"),
        ])

    def test_empty_success_clears_only_that_day_and_bad_date_keeps_rows(self):
        row = frame([("20260924", "000001.SZ", "理由")], ["trade_date", "ts_code", "reason"])
        other = frame([("20260923", "000001.SZ", "理由")], ["trade_date", "ts_code", "reason"])
        bt.replace_rows(self.conn, "top_list", "20260924", row)
        bt.replace_rows(self.conn, "top_list", "20260923", other)
        with self.assertRaises(ValueError):
            bt.replace_rows(self.conn, "top_list", "20260924", frame(
                [("20260923", "000001.SZ", "理由")], ["trade_date", "ts_code", "reason"],
            ))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM top_list").fetchone()[0], 2)
        self.assertEqual(bt.replace_rows(self.conn, "top_list", "20260924", frame([], ["trade_date"])), 0)
        self.assertEqual(
            self.conn.execute("SELECT trade_date FROM top_list").fetchall(),
            [("2026-09-23",)],
        )

    def test_replace_failure_rolls_back_delete(self):
        bt.replace_rows(self.conn, "top_list", "20260924", frame(
            [("20260924", "000001.SZ", "理由")], ["trade_date", "ts_code", "reason"],
        ))
        self.conn.commit()
        self.conn.execute("CREATE TRIGGER reject_trade BEFORE INSERT ON top_list BEGIN SELECT RAISE(ABORT, 'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            bt.commit_slice(
                self.conn, "top_list", "20260924",
                lambda: bt.replace_rows(self.conn, "top_list", "20260924", frame(
                    [("20260924", "000002.SZ", "新理由")], ["trade_date", "ts_code", "reason"],
                )),
            )
        self.assertEqual(self.conn.execute("SELECT ts_code FROM top_list").fetchone()[0], "000001.SZ")
        self.assertIsNone(self.conn.execute("SELECT status FROM board_topic_slice").fetchone())

    @patch.object(bt, "call_api")
    def test_pagination_keeps_short_tail(self, api):
        columns = ["trade_date", "ts_code", "name"]
        api.side_effect = [
            frame([("20260924", "000001.SZ", "甲"), ("20260924", "000002.SZ", "乙")], columns),
            frame([("20260924", "000003.SZ", "丙"), ("20260924", "000004.SZ", "丁")], columns),
            frame([("20260924", "000005.SZ", "戊")], columns),
        ]
        result = bt.fetch_pages(None, "dc_member", page_size=2, interval=0, fields="trade_date,ts_code,name", trade_date="20260924")
        self.assertEqual(len(result), 5)
        self.assertEqual([call.kwargs["offset"] for call in api.call_args_list], [0, 2, 4])

    @patch.object(bt, "call_api")
    def test_duplicate_page_and_oversize_are_rejected(self, api):
        page = frame([("20260924", "000001.SZ"), ("20260924", "000002.SZ")], ["trade_date", "ts_code"])
        api.return_value = page
        with self.assertRaisesRegex(ValueError, "重复分页"):
            bt.fetch_pages(None, "dc_member", page_size=2, interval=0, fields="trade_date,ts_code")
        api.return_value = frame(
            [("20260924", "000001.SZ"), ("20260924", "000002.SZ"), ("20260924", "000003.SZ")],
            ["trade_date", "ts_code"],
        )
        with self.assertRaisesRegex(ValueError, "超过分页大小"):
            bt.fetch_pages(None, "dc_member", page_size=2, interval=0, fields="trade_date,ts_code")

    @patch.object(bt, "MAX_PAGES", 1)
    @patch.object(bt, "call_api")
    def test_page_guard_does_not_return_a_truncated_frame(self, api):
        api.return_value = frame([("20260924", "000001.SZ"), ("20260924", "000002.SZ")], ["trade_date", "ts_code"])
        with self.assertRaisesRegex(ValueError, "分页超过安全上限"):
            bt.fetch_pages(None, "tdx_member", page_size=2, interval=0, fields="trade_date,ts_code")
        self.assertEqual(api.call_count, 1)

    @patch.object(bt, "call_api")
    def test_variant_params_are_requested(self, api):
        api.return_value = pd.DataFrame()
        rows, status, _message = bt.collect_api(None, self.conn, "limit_list_d", ["20260924"], "20250926", "20260926")
        self.assertEqual((rows, status), (0, "ok"))
        self.assertEqual([call.kwargs["limit_type"] for call in api.call_args_list], ["U", "D", "Z"])
        self.assertTrue(all("limit" in call.kwargs["fields"].split(",") for call in api.call_args_list))
        self.assertTrue(all(call.kwargs["trade_date"] == "20260924" for call in api.call_args_list))

        api.reset_mock()
        bt.collect_api(None, self.conn, "kpl_list", ["20260924"], "20250926", "20260926")
        self.assertEqual(
            [call.kwargs["tag"] for call in api.call_args_list],
            ["涨停", "炸板", "跌停", "自然涨停", "竞价"],
        )

        api.reset_mock()
        bt.collect_api(None, self.conn, "ths_hot", ["20260924"], "20250926", "20260926")
        self.assertEqual(
            [call.kwargs["market"] for call in api.call_args_list],
            ["热股", "ETF", "可转债", "行业板块", "概念板块", "期货", "港股", "热基", "美股"],
        )
        self.assertTrue(all(call.kwargs["is_new"] == "N" for call in api.call_args_list))

        api.reset_mock()
        bt.collect_api(None, self.conn, "dc_index", ["20260924"], "20250926", "20260926")
        self.assertEqual([call.kwargs["idx_type"] for call in api.call_args_list], ["行业板块", "概念板块", "地域板块"])

    @patch.object(bt, "call_api")
    def test_permission_error_stops_the_api(self, api):
        api.side_effect = RuntimeError("抱歉，您没有接口访问权限")
        rows, status, message = bt.collect_api(None, self.conn, "stk_auction", ["20260924", "20260925"], "20250926", "20260926")
        self.assertEqual(api.call_count, 1)
        self.assertEqual(rows, 0)
        self.assertEqual(status, "failed")
        self.assertIn("权限", message)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM stk_auction").fetchone()[0], 0)

    @patch.object(bt, "call_api")
    def test_failed_day_keeps_existing_rows_and_later_day_continues(self, api):
        bt.replace_rows(self.conn, "top_list", "20260924", frame(
            [("20260924", "000001.SZ", "理由")], ["trade_date", "ts_code", "reason"],
        ))
        self.conn.commit()
        api.side_effect = [
            RuntimeError("network"),
            frame([("20260925", "000002.SZ", "次日")], ["trade_date", "ts_code", "reason"]),
        ]
        rows, status, message = bt.collect_api(None, self.conn, "top_list", ["20260924", "20260925"], "20250926", "20260926")
        self.assertEqual((rows, status), (1, "partial"))
        self.assertIn("20260924", message)
        self.assertEqual(
            self.conn.execute("SELECT trade_date, ts_code FROM top_list ORDER BY trade_date").fetchall(),
            [("2026-09-24", "000001.SZ"), ("2026-09-25", "000002.SZ")],
        )

    @patch.object(bt, "call_api")
    def test_completed_slice_is_skipped(self, api):
        api.return_value = pd.DataFrame()
        bt.collect_api(None, self.conn, "limit_step", ["20260924"], "20250926", "20260926")
        api.reset_mock()
        rows, status, message = bt.collect_api(None, self.conn, "limit_step", ["20260924"], "20250926", "20260926")
        self.assertEqual(api.call_count, 0)
        self.assertEqual((rows, status), (0, "ok"))
        self.assertIn("跳过已完成切片 1 个", message)

    @patch.object(bt, "THS_INDEX_CAP", 2)
    @patch.object(bt, "call_api")
    def test_ths_index_splits_at_cap_without_offset(self, api):
        def part(code):
            return frame([(code, "名称")], ["ts_code", "name"])

        api.side_effect = [
            frame([("1.TI", "甲"), ("2.TI", "乙")], ["ts_code", "name"]),
            part("A.TI"),
            part("HK.TI"),
            part("US.TI"),
            *[pd.DataFrame() for _ in range(6)],
        ]
        rows, status, _message = bt.collect_api(None, self.conn, "ths_index", [], "20250926", "20260926")
        self.assertEqual((rows, status), (3, "ok"))
        self.assertNotIn("offset", api.call_args_list[0].kwargs)
        self.assertEqual([call.kwargs.get("exchange") for call in api.call_args_list[1:4]], ["A", "HK", "US"])
        self.assertEqual(
            self.conn.execute("SELECT ts_code FROM ths_index ORDER BY ts_code").fetchall(),
            [("A.TI",), ("HK.TI",), ("US.TI",)],
        )


if __name__ == "__main__":
    unittest.main()
