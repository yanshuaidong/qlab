"""标签格式与数据库写入测试；仅使用内存数据库，不调用 AI。

手动执行：python -m unittest discover -s research/stock/tagging -p "test_*.py"
"""

import json
import sqlite3
import unittest

from research.stock.tagging.main import (
    DDL,
    InsufficientEvidence,
    build_prompt,
    fetch_pending,
    save_tags,
    validate_response,
)


class TaggingTests(unittest.TestCase):
    def setUp(self):
        self.reason = "；".join(f"独立驱动依据{i:02d}" for i in range(31))
        self.item = {
            "id": 1,
            "ts_code": "000001.SZ",
            "trade_date": "2026-09-17",
            "reason": self.reason,
        }
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("""CREATE TABLE trend_mark (
            id INTEGER PRIMARY KEY, ts_code TEXT, trade_date TEXT,
            reason TEXT, mark_type TEXT
        )""")
        self.conn.execute(
            "INSERT INTO trend_mark VALUES (?, ?, ?, ?, ?)",
            (1, self.item["ts_code"], self.item["trade_date"], self.reason, "fail"),
        )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def tags(self, count=10):
        return [{"name": f"驱动标签{i:02d}", "evidence": f"独立驱动依据{i:02d}"} for i in range(count)]

    def response(self, tags):
        return json.dumps({"status": "ok", "tags": tags}, ensure_ascii=False)

    def test_count_bounds(self):
        for count in (10, 30):
            self.assertEqual(len(validate_response(self.response(self.tags(count)), self.reason)), count)
        for count in (0, 9, 31):
            with self.assertRaises(ValueError):
                validate_response(self.response(self.tags(count)), self.reason)

    def test_reject_duplicate_and_fabricated_evidence(self):
        tags = self.tags()
        tags[1]["name"] = tags[0]["name"]
        with self.assertRaises(ValueError):
            validate_response(self.response(tags), self.reason)
        tags = self.tags()
        tags[0]["evidence"] = "原文里完全没有的证据"
        with self.assertRaises(ValueError):
            validate_response(self.response(tags), self.reason)

    def test_insufficient_evidence_is_not_success(self):
        with self.assertRaises(InsufficientEvidence):
            validate_response(
                '{"status":"insufficient_evidence","tags":[],"message":"依据不足"}',
                self.reason,
            )

    def test_fenced_json_and_malformed_response(self):
        text = "```json\n" + self.response(self.tags()) + "\n```"
        self.assertEqual(len(validate_response(text, self.reason)), 10)
        for text in ("[]", "不是JSON", '{"status":"unknown","tags":[]}'):
            with self.assertRaises(ValueError):
                validate_response(text, self.reason)

    def test_no_label_leakage_into_prompt(self):
        item = dict(self.item, mark_type="fail")
        prompt = build_prompt(item)
        self.assertNotIn("mark_type", prompt)
        self.assertNotIn('"fail"', prompt)
        self.assertIn(self.reason, prompt)

    def test_save_and_resume_without_modifying_original(self):
        # 尚未创建结果表时也能读取；失败标记同样参与标签提炼。
        self.assertEqual(len(fetch_pending(self.conn, 0)), 1)
        self.conn.execute(DDL)
        self.assertTrue(save_tags(self.conn, self.item, self.tags(), force=False))
        self.assertEqual(fetch_pending(self.conn, 0), [])
        self.assertEqual(len(fetch_pending(self.conn, 0, force=True)), 1)
        original = self.conn.execute("SELECT reason, mark_type FROM trend_mark WHERE id = 1").fetchone()
        self.assertEqual(tuple(original), (self.reason, "fail"))
        self.assertFalse(save_tags(self.conn, self.item, self.tags(), force=False))
        self.assertTrue(save_tags(self.conn, self.item, self.tags(), force=True))
        self.conn.execute("UPDATE trend_mark SET reason = reason || '新增信息' WHERE id = 1")
        self.conn.commit()
        self.assertEqual(len(fetch_pending(self.conn, 0)), 1)
        self.assertFalse(save_tags(self.conn, self.item, self.tags(), force=True))

    def test_deleted_signal_is_not_written(self):
        self.conn.execute(DDL)
        self.conn.execute("DELETE FROM trend_mark WHERE id = 1")
        self.conn.commit()
        self.assertFalse(save_tags(self.conn, self.item, self.tags(), force=False))

    def test_skip_unfinished_reasons(self):
        for index, reason in enumerate(("", "  ", None, "初筛待处理", "  标注失败：超时"), 2):
            self.conn.execute(
                "INSERT INTO trend_mark VALUES (?, ?, ?, ?, ?)",
                (index, "000002.SZ", "2026-09-17", reason, "correct"),
            )
        self.conn.commit()
        self.assertEqual([row["id"] for row in fetch_pending(self.conn, 0)], [1])


if __name__ == "__main__":
    unittest.main()
