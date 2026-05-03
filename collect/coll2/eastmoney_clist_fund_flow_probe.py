from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


URL = "https://push2delay.eastmoney.com/api/qt/clist/get"
ORIGINAL_CURL_URL = "https://push2.eastmoney.com/api/qt/clist/get"

DEFAULT_PARAMS = {
    "cb": "jQuery112301826670222612532_1777778229692",
    "fid": "f62",
    "po": "1",
    "pz": "50",
    "pn": "1",
    "np": "1",
    "fltt": "2",
    "invt": "2",
    "ut": "8dec03ba335b81bf4ebdf7b29ec27d15",
    "fs": (
        "m:0+t:6+f:!2,m:0+t:13+f:!2,m:0+t:80+f:!2,"
        "m:1+t:2+f:!2,m:1+t:23+f:!2,m:0+t:7+f:!2,m:1+t:3+f:!2"
    ),
    "fields": (
        "f12,f14,f2,f3,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,"
        "f204,f205,f124,f1,f13"
    ),
}

HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Pragma": "no-cache",
    "Referer": "https://data.eastmoney.com/zjlx/detail.html",
    "Sec-Fetch-Dest": "script",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "same-site",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    ),
    "sec-ch-ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

COOKIE = (
    "qgqp_b_id=70f78c1dbdc8e7857932b3ea5be3da75; "
    "st_nvi=YNgltYYTqh8W7xtyoP33yad86; "
    "nid18=000842679b010e1a44cbeba60a0c8e65; "
    "nid18_create_time=1774360784169; "
    "gviem=9OaX7PUMujwXKWXgPds0w21e3; "
    "gviem_create_time=1774360784169; "
    "fullscreengg=1; "
    "fullscreengg2=1; "
    "st_si=80714220325454; "
    "st_asi=delete; "
    "st_pvi=87318324090858; "
    "st_sp=2025-07-03%2022%3A32%3A30; "
    "st_inirUrl=https%3A%2F%2Fportal.eastmoneyfutures.com%2F; "
    "st_sn=14; "
    "st_psi=20260503111709772-113300300813-7556889797"
)

FIELD_NAMES = {
    "f1": "市场标识/状态",
    "f2": "最新价",
    "f3": "涨跌幅",
    "f12": "股票代码",
    "f13": "市场代码",
    "f14": "股票名称",
    "f62": "主力净流入-净额",
    "f184": "主力净流入-净占比",
    "f66": "超大单净流入-净额",
    "f69": "超大单净流入-净占比",
    "f72": "大单净流入-净额",
    "f75": "大单净流入-净占比",
    "f78": "中单净流入-净额",
    "f81": "中单净流入-净占比",
    "f84": "小单净流入-净额",
    "f87": "小单净流入-净占比",
    "f124": "更新时间 Unix 秒",
    "f204": "保留字段 f204",
    "f205": "保留字段 f205",
}


def parse_jsonp(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)

    match = re.match(r"^[\w$]+\((.*)\);?$", stripped, flags=re.S)
    if not match:
        raise ValueError(f"响应不是 JSON/JSONP: {stripped[:120]}")
    return json.loads(match.group(1))


def unix_seconds_to_text(value: object) -> str | None:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def fetch_page(page: int, page_size: int, timeout: float) -> dict[str, Any]:
    params = dict(DEFAULT_PARAMS)
    params["pn"] = str(page)
    params["pz"] = str(page_size)

    response = requests.get(
        URL,
        params=params,
        headers=HEADERS,
        cookies=parse_cookie(COOKIE),
        timeout=timeout,
    )
    response.raise_for_status()
    return parse_jsonp(response.text)


def parse_cookie(cookie: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for part in cookie.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        pairs[key.strip()] = value.strip()
    return pairs


def explain_row(row: dict[str, Any]) -> dict[str, Any]:
    explained = {}
    for key, value in row.items():
        label = FIELD_NAMES.get(key, key)
        if key == "f124":
            explained[f"{key} {label}"] = unix_seconds_to_text(value) or value
        else:
            explained[f"{key} {label}"] = value
    return explained


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Probe Eastmoney clist fund-flow endpoint from a browser curl. "
            "This endpoint is expected to return current snapshot/list data, "
            "not per-stock historical rows."
        )
    )
    parser.add_argument("--pages", type=int, default=1, help="Pages to fetch.")
    parser.add_argument("--page-size", type=int, default=50, help="Rows per page.")
    parser.add_argument("--timeout", type=float, default=15, help="Request timeout.")
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.5,
        help="Seconds to sleep between pages.",
    )
    parser.add_argument(
        "--save-raw",
        type=Path,
        default=None,
        help="Optional path to save decoded JSON response list.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    decoded_pages: list[dict[str, Any]] = []

    print("Endpoint:", URL)
    print("Original curl endpoint:", ORIGINAL_CURL_URL)
    print("Important params:")
    print("  fid =", DEFAULT_PARAMS["fid"])
    print("  fs  =", DEFAULT_PARAMS["fs"])
    print("  fields =", DEFAULT_PARAMS["fields"])
    print(
        "Observation: this clist URL has page/sort/filter params but no stock code, "
        "start date, end date, or date period param."
    )
    print()

    for page in range(1, args.pages + 1):
        decoded = fetch_page(page=page, page_size=args.page_size, timeout=args.timeout)
        decoded_pages.append(decoded)

        data = decoded.get("data") or {}
        rows = data.get("diff") or []
        total = data.get("total")
        print(f"Page {page}: total={total}, rows={len(rows)}")

        if rows:
            update_times = sorted(
                {
                    text
                    for row in rows
                    if (text := unix_seconds_to_text(row.get("f124")))
                }
            )
            print("f124 update times:", ", ".join(update_times) or "N/A")
            print("First row:")
            print(json.dumps(explain_row(rows[0]), ensure_ascii=False, indent=2))
        else:
            print("No rows returned.")
        print()

        if args.sleep > 0 and page < args.pages:
            time.sleep(args.sleep)

    if args.save_raw:
        args.save_raw.parent.mkdir(parents=True, exist_ok=True)
        args.save_raw.write_text(
            json.dumps(decoded_pages, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Saved decoded JSON to {args.save_raw}")


if __name__ == "__main__":
    main()
