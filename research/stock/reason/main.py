#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主力大幅流入原因标注：从库中取信号，用 Claude Agent SDK 搜索总结后写回。"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import sys
import time
from datetime import date, datetime
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    ServerToolUseBlock,
    TextBlock,
    ToolUseBlock,
    query,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_PATH = REPO_ROOT / ".env"
DB_PATH = REPO_ROOT / "storage" / "stock" / "data.sqlite"
HERE = Path(__file__).resolve().parent
WORK_DIR = HERE / "work"
BACKUP_PATH = WORK_DIR / "backup_before_write.jsonl"

DEFAULT_LIMIT = 20
DEFAULT_CONCURRENCY = 4
MAX_CHARS = 300
MODEL = "deepseek-flash[1m]"
ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic"

SYSTEM_PROMPT = (
    "你在标注 A 股主力大幅流入的核心原因或直接导火索。"
    "禁止多轮思考、禁止复盘、禁止再开一轮推理。"
    "整个过程只允许两步：调用一次 WebSearch，然后立刻给出最终一段话。"
    "查询词一次写全，必须带上该交易日，不要拆成多次搜索，不要打开或连点更多网页。"
    "只写最关键的一条原因，一两句说清即可，不要铺开成复盘。"
    "只能依据该交易日当天及之前已经公开的信息，站在当日收盘时点解释盘中流入。"
    "禁止写该日之后才发生或才披露的事，包括次日研报、之后的连板或三日偏离上榜、之后才公布的财报和澄清。"
    "不要罗列资金净流入金额、不要写龙虎榜席位、不要写多重共振清单、不要写投资建议。"
    "最终回答必须是一段中文，不要 markdown，不要标题，不要分点，不要多段落，不要编号。"
    "字数严格控制在 300 字以内。只根据搜索到的公开信息总结，不要编造。"
)

PROMPT_TEMPLATE = (
    "{date}，{name}主力大幅流入，核心原因或直接导火索是什么？\n"
    "1. 使用 WebSearch 只搜索一次，查询词必须带上「{date}」；\n"
    "2. 只写最关键的一条原因，一段话、300字以内；\n"
    "3. 只准用{date}当天及此前已公开的信息，不要写该日之后的事；"
)

RETRY_LOOKAHEAD_HINT = (
    "上一稿用了该交易日之后才发生或才披露的信息。"
    "必须重写：只保留当日及此前已公开的事实，删掉次日、连板统计、事后财报和澄清。"
)

CN_DATE_RE = re.compile(r"(?:(?P<y>\d{4})年)?(?P<m>\d{1,2})月(?P<d>\d{1,2})日")
LOOKAHEAD_PHRASE_RE = re.compile(
    r"次日|第二天|隔日|"
    r"起连续[二三四五][日天]|"
    r"连续[三四]日涨幅偏离|"
    r"之后(?:才)?(?:披露|公布|公告)|"
    r"随后(?:才)?(?:披露|公布|公告|回应)"
)


def log(message: str) -> None:
    print(message, flush=True)


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            values[key] = value
    return values


def format_cn_date(trade_date: str) -> str:
    year, month, day = trade_date.split("-")
    return f"{int(year)}年{int(month)}月{int(day)}日"


def build_prompt(trade_date: str, name: str, extra: str = "") -> str:
    text = PROMPT_TEMPLATE.format(date=format_cn_date(trade_date), name=name)
    extra = extra.strip()
    if extra:
        return text + "\n" + extra
    return text


def lookahead_hits(text: str, trade_date: str) -> bool:
    """是否写了交易日之后才知道的事。"""
    if LOOKAHEAD_PHRASE_RE.search(text):
        return True
    year, month, day = (int(part) for part in trade_date.split("-"))
    limit = date(year, month, day)
    for match in CN_DATE_RE.finditer(text):
        y = int(match.group("y") or year)
        try:
            found = date(y, int(match.group("m")), int(match.group("d")))
        except ValueError:
            continue
        if found > limit:
            return True
    return False


def clean_paragraph(text: str, limit: int = MAX_CHARS) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"[#>*`_]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in ("。", "！", "？", "；", ".", "!", "?"):
        idx = cut.rfind(sep)
        if idx >= int(limit * 0.6):
            return cut[: idx + 1]
    return cut


def connect(readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
    conn.row_factory = sqlite3.Row
    return conn


def fetch_pending(conn: sqlite3.Connection, limit: int) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT t.id, t.ts_code, t.trade_date, t.mark_type, t.reason,
               COALESCE(m.name, t.ts_code) AS name
        FROM trend_mark t
        LEFT JOIN moneyflow_dc m
          ON m.ts_code = t.ts_code AND m.trade_date = t.trade_date
        WHERE t.reason LIKE '初筛%'
           OR TRIM(t.reason) = ''
        ORDER BY t.id
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def snapshot_backup(items: list[dict[str, object]]) -> None:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with BACKUP_PATH.open("a", encoding="utf-8") as fh:
        for item in items:
            fh.write(
                json.dumps(
                    {
                        "backed_up_at": stamp,
                        "id": item["id"],
                        "ts_code": item["ts_code"],
                        "trade_date": item["trade_date"],
                        "mark_type": item["mark_type"],
                        "reason": item["reason"],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def update_reason(conn: sqlite3.Connection, item_id: int, reason: str) -> None:
    conn.execute(
        """
        UPDATE trend_mark
        SET reason = ?
        WHERE id = ?
          AND (reason LIKE '初筛%' OR TRIM(reason) = '')
        """,
        (reason, item_id),
    )
    conn.commit()


def deepseek_env(api_key: str) -> dict[str, str]:
    return {
        "ANTHROPIC_BASE_URL": ANTHROPIC_BASE_URL,
        "ANTHROPIC_AUTH_TOKEN": api_key,
        "ANTHROPIC_API_KEY": api_key,
        "ANTHROPIC_MODEL": MODEL,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": MODEL,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": MODEL,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-flash",
        "CLAUDE_CODE_SUBAGENT_MODEL": "deepseek-flash",
        "CLAUDE_CODE_EFFORT_LEVEL": "low",
    }


def resolve_cli_path() -> str:
    raw = os.environ.get("CLAUDE_CLI_PATH", "").strip()
    candidates = [
        Path(raw) if raw else None,
        Path(os.environ.get("APPDATA", ""))
        / "npm"
        / "node_modules"
        / "@anthropic-ai"
        / "claude-code"
        / "bin"
        / "claude.exe",
    ]
    for path in candidates:
        if path and path.is_file():
            return str(path)
    raise FileNotFoundError(
        "未找到 claude.exe。请安装 Claude Code，或设置 CLAUDE_CLI_PATH。"
    )


def extract_text(message: object) -> str:
    if not isinstance(message, AssistantMessage):
        return ""
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextBlock) and block.text:
            parts.append(block.text)
    return "".join(parts).strip()


def make_search_limit_hook(limit: int = 1):
    used = {"n": 0}

    async def hook(input_data, tool_use_id, context):
        name = str(input_data.get("tool_name") or "")
        if name not in {"WebSearch", "web_search"}:
            return {}
        if used["n"] >= limit:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "只允许搜索一次。不要继续思考或再搜，立刻输出最终一段话。"
                    ),
                }
            }
        used["n"] += 1
        return {}

    return hook


def log_tool_uses(message: object, prefix: str = "") -> int:
    if not isinstance(message, AssistantMessage):
        return 0
    n = 0
    for block in message.content:
        if not isinstance(block, (ToolUseBlock, ServerToolUseBlock)):
            continue
        name = str(block.name)
        if name not in {"WebSearch", "web_search"}:
            continue
        n += 1
        query_text = str((block.input or {}).get("query") or "")
        log(f"{prefix}搜索: {query_text}")
    return n


async def reason_one(
    prompt: str,
    api_key: str,
    cli_path: str,
    prefix: str = "  ",
) -> tuple[str, int, int]:
    last_text = ""
    result_text = ""
    error_bits: list[str] = []
    searches = 0
    turns = 0
    options = ClaudeAgentOptions(
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        tools=["WebSearch"],
        allowed_tools=["WebSearch"],
        permission_mode="bypassPermissions",
        max_turns=2,
        thinking={"type": "disabled"},
        effort="low",
        skills=[],
        strict_mcp_config=True,
        hooks={
            "PreToolUse": [HookMatcher(hooks=[make_search_limit_hook(1)])],
        },
        setting_sources=[],
        cwd=str(WORK_DIR),
        cli_path=cli_path,
        env=deepseek_env(api_key),
    )
    try:
        async for message in query(prompt=prompt, options=options):
            searches += log_tool_uses(message, prefix)
            text = extract_text(message)
            if text:
                last_text = text
            if isinstance(message, ResultMessage):
                turns = message.num_turns
                if message.result:
                    result_text = message.result.strip()
                if message.is_error:
                    extra = message.result or ""
                    if message.errors:
                        extra = extra or "；".join(message.errors)
                    error_bits.append(extra or f"subtype={message.subtype}")
    except Exception as exc:
        if last_text:
            text = clean_paragraph(last_text)
            if text:
                return text, searches, turns
        raise RuntimeError(str(exc)) from exc
    text = clean_paragraph(result_text or last_text)
    if error_bits and not text:
        raise RuntimeError(error_bits[-1])
    if not text:
        raise RuntimeError("模型没有返回可用正文")
    return text, searches, turns


async def run(limit: int, dry_run: bool, concurrency: int) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not DB_PATH.is_file():
        log(f"数据库不存在: {DB_PATH}")
        return 1

    env = load_env(ENV_PATH)
    api_key = env.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        log(f"未找到 DEEPSEEK_API_KEY: {ENV_PATH}")
        return 1

    os.environ.update(deepseek_env(api_key))
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    cli_path = resolve_cli_path()

    conn = connect(readonly=True)
    try:
        items = fetch_pending(conn, limit)
    finally:
        conn.close()

    if not items:
        log("没有待标注记录")
        return 0

    workers = max(1, min(concurrency, len(items)))
    log(
        f"待处理 {len(items)} 条，并发 {workers}，"
        f"{'只跑不入库' if dry_run else '回写 trend_mark.reason'}"
    )
    if not dry_run:
        snapshot_backup(items)

    write_conn = None if dry_run else connect(readonly=False)
    sem = asyncio.Semaphore(workers)
    total = len(items)

    async def annotate(index: int, item: dict[str, object]) -> dict[str, object]:
        prefix = f"[{index}/{total}] "
        async with sem:
            log(f"{prefix}开始 id={item['id']} {item['ts_code']} {item['trade_date']} {item['name']}")
            started = time.perf_counter()
            trade_date = str(item["trade_date"])
            prompt = build_prompt(trade_date, str(item["name"]))
            try:
                reason, searches, turns = await reason_one(
                    prompt, api_key, cli_path, prefix=prefix
                )
                if lookahead_hits(reason, trade_date):
                    log(f"{prefix}写到了未来信息，重试一次")
                    reason, extra_searches, extra_turns = await reason_one(
                        build_prompt(trade_date, str(item["name"]), RETRY_LOOKAHEAD_HINT),
                        api_key,
                        cli_path,
                        prefix=prefix,
                    )
                    searches += extra_searches
                    turns += extra_turns
                    if lookahead_hits(reason, trade_date):
                        log(f"{prefix}重试后仍可能含未来信息")
            except Exception as exc:
                cost = time.perf_counter() - started
                log(f"{prefix}失败: {exc}，用时 {cost:.1f}s")
                return {
                    "index": index,
                    "item": item,
                    "ok": False,
                    "reason": f"标注失败：{exc}",
                    "cost": cost,
                }
            cost = time.perf_counter() - started
            log(f"{prefix}完成 {len(reason)} 字，搜索 {searches} 次，{turns} 轮，用时 {cost:.1f}s")
            return {
                "index": index,
                "item": item,
                "ok": True,
                "reason": reason,
                "cost": cost,
            }

    ok = 0
    fail = 0
    elapsed_ok: list[float] = []
    wall_started = time.perf_counter()
    try:
        tasks = [
            asyncio.create_task(annotate(i, item))
            for i, item in enumerate(items, start=1)
        ]
        for fut in asyncio.as_completed(tasks):
            result = await fut
            item = result["item"]
            if not isinstance(item, dict):
                raise TypeError("item")
            reason = str(result["reason"])
            if result["ok"]:
                if write_conn is not None:
                    update_reason(write_conn, int(item["id"]), reason)
                    log(f"[{result['index']}/{total}] 已入库 id={item['id']}")
                ok += 1
                elapsed_ok.append(float(result["cost"]))
            else:
                fail += 1
    finally:
        if write_conn is not None:
            write_conn.close()

    wall = time.perf_counter() - wall_started
    avg = (sum(elapsed_ok) / len(elapsed_ok)) if elapsed_ok else 0.0
    done_n = ok + fail
    effective = (wall / done_n) if done_n else 0.0
    log(
        f"结束：成功 {ok}，失败 {fail}，单条均耗时 {avg:.1f}s，"
        f"墙钟 {wall:.1f}s（约 {effective:.1f}s/条）"
        + ("，未入库" if dry_run else f"，已回写 {DB_PATH}")
    )
    return 0 if fail == 0 else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="主力大幅流入原因标注（实验）")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="本次处理条数，默认 20")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"同时处理条数，默认 {DEFAULT_CONCURRENCY}",
    )
    parser.add_argument("--dry-run", action="store_true", help="只跑标注，不回写数据库")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.limit <= 0:
        log("--limit 必须大于 0")
        return 1
    if args.concurrency <= 0:
        log("--concurrency 必须大于 0")
        return 1
    return asyncio.run(
        run(
            limit=args.limit,
            dry_run=args.dry_run,
            concurrency=args.concurrency,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
