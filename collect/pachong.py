#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""爬取 Tushare 官方接口文档，整理成 doc/tushare 下的知识文档。

默认从 https://tushare.pro/document/2 出发，结合官方 Markdown 接口、
仓库内接口目录、页面内链接，把接口说明按分类落到本地 Markdown。

用法：
  python collect/pachong.py
  python collect/pachong.py --start-id 24
  python collect/pachong.py --only-start
  python collect/pachong.py --index-only
  python collect/pachong.py --max-docs 8
  python collect/pachong.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_ROOT = REPO_ROOT / "doc" / "tushare"
CATALOG_PATH = REPO_ROOT / "skills" / "tushare" / "references" / "数据接口.md"

BASE_PAGE = "https://tushare.pro/document/2"
MD_API = "https://tushare.pro/wctapi/documents/{doc_id}.md"
INDEX_URL = "https://tushare.pro/document/2"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

DEFAULT_INTERVAL = 0.25
MAX_RETRIES = 4
RETRY_BACKOFF = 1.6
MIN_BODY_LEN = 40

# 官方导航里常见的分类页，用作发现入口（叶子接口仍以正文为准）。
SEED_CATEGORY_IDS = {
    14, 15, 16, 17, 18, 24, 83, 93, 134, 142, 147, 148, 157, 177,
    184, 190, 217, 218, 224, 225, 226, 251, 283, 291, 330, 342, 346,
    384, 474, 485,
}

CATEGORY_ID_TITLES = {
    14: "股票数据",
    15: "行情数据",
    16: "财务数据",
    17: "参考数据",
    18: "公募基金",
    24: "基础数据",
    83: "行业经济",
    93: "指数专题",
    134: "期货数据",
    142: "特色数据",
    147: "宏观经济",
    148: "宏观经济/国内宏观/利率数据",
    157: "期权数据",
    177: "外汇数据",
    184: "债券专题",
    190: "港股数据",
    217: "宏观经济/国际宏观",
    218: "宏观经济/国际宏观/美国利率",
    224: "宏观经济/国内宏观",
    225: "宏观经济/国内宏观/国民经济",
    226: "宏观经济/国内宏观/价格指数",
    251: "美股数据",
    283: "现货数据",
    291: "特色数据",
    330: "两融及转融通",
    342: "资金流向数据",
    346: "打板专题数据",
    384: "ETF专题",
    474: "自选组合",
    485: "量化因子库",
}

SKIP_DOC_IDS = {13, 122, 213, 234, 244, 270, 290}
SKIP_CATEGORY_TITLES = {
    "常见问题",
    "平台积分",
    "欢迎加入专业群",
    "积分与频次权限对应表",
}

API_RE = re.compile(
    r"(?:\*\*)?接口(?:名称)?(?:\*\*)?[:：]\s*`?(?P<api>[a-zA-Z_][a-zA-Z0-9_]*)`?"
)
DOC_ID_RE = re.compile(
    r"(?:document/2\?doc_id=|/wctapi/documents/)(\d+)",
    re.I,
)
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.M)
CATALOG_ROW_RE = re.compile(
    r"^\|\s*\[(?P<api>[^\]]+)\]\(https://tushare\.pro/wctapi/documents/(?P<id>\d+)\.md\)\s*"
    r"\|\s*(?P<title>[^|]+?)\s*"
    r"\|\s*(?P<category>[^|]+?)\s*"
    r"\|\s*(?P<desc>.*?)\s*\|\s*$"
)
SECTION_TITLES = {
    "输入参数",
    "输出参数",
    "接口示例",
    "接口用法",
    "数据样例",
    "调取说明",
    "数据说明",
    "功能描述",
}
INVALID_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def log(message: str) -> None:
    print(message, flush=True)


def today() -> str:
    return date.today().isoformat()


def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = name.replace("（", "(").replace("）", ")")
    name = name.replace("：", "-").replace(":", "-")
    name = name.replace("——", "-").replace("—", "-").replace("–", "-")
    name = name.replace("“", "").replace("”", "").replace('"', "").replace("'", "")
    name = name.replace("？", "").replace("?", "")
    name = INVALID_FILENAME_RE.sub("_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name or "untitled"


def sanitize_parts(parts: tuple[str, ...]) -> tuple[str, ...]:
    cleaned = [sanitize_filename(part) for part in parts]
    cleaned = [part for part in cleaned if part and part != "untitled"]
    return tuple(cleaned) or ("其他",)


def category_parts(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ("其他",)
    parts = [p.strip() for p in re.split(r"[,，/]", raw) if p.strip()]
    if not parts:
        return ("其他",)
    # 与现有 doc/tushare/基础数据 目录对齐：股票数据下的二级分类提到顶层。
    if parts[0] == "股票数据" and len(parts) > 1:
        parts = parts[1:]
    return sanitize_parts(tuple(parts))


def infer_parts(title: str, api: str | None) -> tuple[str, ...] | None:
    api_name = api or ""
    api_rules: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
        (("etf_", "rt_etf"), ("ETF专题",)),
        (("fut_", "ft_", "rt_fut"), ("期货数据",)),
        (("hk_", "rt_hk"), ("港股数据",)),
        (("us_",), ("美股数据",)),
        (("cb_", "bond_", "repo_", "yc_cb"), ("债券专题",)),
        (("fund_",), ("公募基金",)),
        (("factor_", "stk_factor"), ("量化因子库",)),
        (("p_save", "p_list", "p_get", "p_delete"), ("自选组合",)),
        (("idx_", "index_", "sw_", "rt_idx", "rt_sw"), ("指数专题",)),
        (("opt_",), ("期权数据",)),
        (("cn_", "sf_month"), ("宏观经济",)),
        (("stk_shock", "stk_high_shock", "stk_alert", "stk_seasoned"), ("参考数据",)),
        (("monetary", "npr"), ("大模型语料专题数据",)),
    ]
    for prefixes, parts in api_rules:
        if any(api_name.startswith(prefix) or api_name == prefix.rstrip("_") for prefix in prefixes):
            return parts
    text = f"{title} {api_name}"
    rules: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
        (("ETF",), ("ETF专题",)),
        (("期货", "仓单", "南华"), ("期货数据",)),
        (("因子",), ("量化因子库",)),
        (("自选",), ("自选组合",)),
        (("可转债", "债券回购", "国债"), ("债券专题",)),
        (("申万", "SW指数", "指数公告"), ("指数专题",)),
        (("港股",), ("港股数据",)),
        (("美股",), ("美股数据",)),
        (("基金",), ("公募基金",)),
        (("异常波动", "重点提示", "增发"), ("参考数据",)),
        (("货币政策", "政策库"), ("大模型语料专题数据",)),
        (("经济数据发布",), ("宏观经济",)),
        (("指数",), ("指数专题",)),
    ]
    for keywords, parts in rules:
        if any(keyword in text for keyword in keywords):
            return parts
    return None


def is_useful_category(item: dict) -> bool:
    title = item.get("title") or ""
    if item.get("type") != "category":
        return True
    if item.get("doc_id") in SKIP_DOC_IDS or title.startswith("doc_"):
        return False
    if title in SKIP_CATEGORY_TITLES:
        return False
    if "?" in title or "？" in title or re.match(r"^\d+\.", title):
        return False
    if len(title) > 24:
        return False
    return True


def join_category(parts: tuple[str, ...]) -> str:
    return "/".join(parts)


class HrefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[int] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href") or ""
        for match in DOC_ID_RE.finditer(href):
            self.ids.add(int(match.group(1)))


def http_get(url: str, timeout: int = 30) -> str:
    last_error: BaseException | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            return raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code in {404, 410}:
                return ""
            if exc.code not in {429, 500, 502, 503, 504} or attempt == MAX_RETRIES:
                raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt == MAX_RETRIES:
                raise
        wait = RETRY_BACKOFF * attempt
        log(f"  请求失败，{wait:.1f}s 后重试 {url} ({attempt}/{MAX_RETRIES}): {last_error}")
        time.sleep(wait)
    raise last_error if last_error else RuntimeError(f"GET 失败: {url}")


def extract_doc_ids(text: str) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for match in DOC_ID_RE.finditer(text or ""):
        doc_id = int(match.group(1))
        if doc_id not in seen:
            seen.add(doc_id)
            ids.append(doc_id)
    return ids


def extract_api(text: str, fallback: str | None = None) -> str | None:
    match = API_RE.search(text or "")
    if match:
        return match.group("api")
    if fallback and re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", fallback):
        return fallback
    return None


def extract_title(text: str, fallback: str) -> str:
    for match in HEADING_RE.finditer(text or ""):
        title = match.group(1).strip().strip("#").strip()
        title = re.sub(r"^[-]+$", "", title).strip()
        if title and title.lower() not in {"tushare", "tushare数据"}:
            return re.sub(r"^Tushare\s*", "", title).strip() or title
    for line in (text or "").splitlines():
        stripped = line.strip().strip("#").strip()
        stripped = stripped.strip("-").strip()
        if stripped and not stripped.startswith("<") and "接口" not in stripped[:2]:
            if len(stripped) <= 40:
                return stripped
            break
    return fallback


def is_api_doc(text: str) -> bool:
    if not text or len(text.strip()) < MIN_BODY_LEN:
        return False
    markers = ("输入参数", "输出参数", "接口：", "接口:", "接口示例", "数据样例")
    return any(marker in text for marker in markers)


def load_local_catalog(path: Path) -> dict[int, dict]:
    items: dict[int, dict] = {}
    if not path.is_file():
        return items
    for raw in path.read_text(encoding="utf-8").splitlines():
        match = CATALOG_ROW_RE.match(raw.strip())
        if not match:
            continue
        doc_id = int(match.group("id"))
        title = match.group("title").strip()
        category = match.group("category").strip()
        api = match.group("api").strip()
        desc = re.sub(r"<br\s*/?>", "", match.group("desc")).strip()
        items[doc_id] = {
            "doc_id": doc_id,
            "title": title,
            "api": api,
            "category": join_category(category_parts(category)),
            "parts": category_parts(category),
            "desc": desc,
        }
    return items


def fetch_index_ids() -> set[int]:
    ids: set[int] = set()
    try:
        html = http_get(INDEX_URL)
    except Exception as exc:  # noqa: BLE001
        log(f"索引页抓取失败，跳过 HTML 发现: {exc}")
        return ids
    parser = HrefParser()
    parser.feed(html)
    ids.update(parser.ids)
    ids.update(extract_doc_ids(html))
    return ids


def fetch_markdown(doc_id: int) -> str:
    return http_get(MD_API.format(doc_id=doc_id)).strip()


def normalize_tables(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    i = 0

    def is_row(line: str) -> bool:
        stripped = line.strip()
        if "|" not in stripped:
            return False
        if stripped.startswith("#") or stripped.startswith(">"):
            return False
        return stripped.count("|") >= 1 and not stripped.startswith("```")

    def is_sep(line: str) -> bool:
        stripped = line.strip().strip("|")
        parts = [p.strip() for p in stripped.split("|")]
        return bool(parts) and all(re.fullmatch(r":?-{3,}:?", p or "") for p in parts if p != "")

    def cells(line: str) -> list[str]:
        stripped = line.strip()
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        return [c.strip() for c in stripped.split("|")]

    def emit(rows: list[list[str]]) -> None:
        width = max(len(row) for row in rows)
        norm = [row + [""] * (width - len(row)) for row in rows]
        header = norm[0]
        body = norm[1:]
        if body and all(re.fullmatch(r":?-{3,}:?", (c or "-")) for c in body[0]):
            body = body[1:]
        out.append("| " + " | ".join(header) + " |")
        out.append("| " + " | ".join("---" for _ in header) + " |")
        for row in body:
            out.append("| " + " | ".join(row) + " |")

    while i < len(lines):
        if is_row(lines[i]):
            block = [cells(lines[i])]
            i += 1
            while i < len(lines) and (is_row(lines[i]) or is_sep(lines[i])):
                block.append(cells(lines[i]))
                i += 1
            if len(block) >= 2:
                emit(block)
            else:
                out.append(lines[i - 1])
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def promote_sections(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        title = match.group(1).strip()
        title = title.strip("*").strip()
        if title in SECTION_TITLES:
            return f"## {title}"
        return match.group(0)

    text = re.sub(r"^\s*\*\*(.+?)\*\*\s*$", repl, text, flags=re.M)
    text = re.sub(r"^_{2,}(.+?)_{2,}\s*$", repl, text, flags=re.M)
    return text


def polish_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("https://waditu.com/", "https://tushare.pro/")
    text = re.sub(r'<a href="([^"]+)">([^<]+)</a>', r"[\2](\1)", text, flags=re.I)
    text = promote_sections(text)
    text = normalize_tables(text)
    text = re.sub(r"(## [^\n]+)\n(?=\|)", r"\1\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def yaml_escape(value: str) -> str:
    if any(ch in value for ch in ":#{}[]&*?|-<>=!%@`'\""):
        return json.dumps(value, ensure_ascii=False)
    return value


def render_doc(
    *,
    title: str,
    doc_id: int,
    api: str | None,
    category: str,
    body: str,
    doc_type: str,
) -> str:
    lines = [
        "---",
        f"title: {yaml_escape(title)}",
        f"doc_id: {doc_id}",
        f"category: {yaml_escape(category)}",
        f"type: {doc_type}",
        f"source: {BASE_PAGE}?doc_id={doc_id}",
        f"markdown: {MD_API.format(doc_id=doc_id)}",
        f"updated: {today()}",
    ]
    if api:
        lines.append(f"api: {api}")
    lines.extend(["---", "", f"# {title}", ""])
    if api:
        lines.append(f"> **接口：** `{api}` · [官方文档]({BASE_PAGE}?doc_id={doc_id})")
        lines.append("")
    else:
        lines.append(f"> [官方文档]({BASE_PAGE}?doc_id={doc_id})")
        lines.append("")
    body = polish_markdown(body)
    # 去掉正文里重复的一级标题，避免知识文档出现两个 H1。
    body_lines = body.splitlines()
    if body_lines:
        first = body_lines[0].lstrip("# ").strip()
        if first == title or first.rstrip("- ").strip() == title:
            body_lines = body_lines[1:]
            while body_lines and re.fullmatch(r"-{3,}", body_lines[0].strip()):
                body_lines = body_lines[1:]
            body = "\n".join(body_lines).strip()
    if body:
        lines.append(body)
        lines.append("")
    return "\n".join(lines)


def unique_path(directory: Path, filename: str) -> Path:
    path = directory / filename
    if not path.exists():
        return path
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    n = 2
    while True:
        candidate = directory / f"{stem}_{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def write_text(path: Path, content: str, dry_run: bool) -> None:
    if dry_run:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def parse_start_id(url_or_id: str) -> int | None:
    text = (url_or_id or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    match = re.search(r"doc_id=(\d+)", text)
    if match:
        return int(match.group(1))
    return None


def build_index(docs: list[dict], version_note: str) -> str:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in docs:
        grouped[item["category"]].append(item)

    def sort_key(item: dict) -> tuple:
        return (0 if item["type"] == "category" else 1, item["title"], item["doc_id"])

    categories = sorted(grouped)
    lines = [
        "# Tushare 接口知识文档",
        "",
        "本文档由 `collect/pachong.py` 从 [Tushare 官方文档](https://tushare.pro/document/2) 同步，供本地检索和智能体使用。",
        "",
        "## 版本信息",
        "",
        version_note.strip() or "- 来源：https://tushare.pro",
        "",
        f"- 同步日期：{today()}",
        f"- 文档数量：{sum(1 for d in docs if d['type'] == 'api')} 个接口，"
        f"{sum(1 for d in docs if d['type'] == 'category')} 个分类页",
        "",
        "## 分类索引",
        "",
    ]
    for category in categories:
        items = sorted(grouped[category], key=sort_key)
        apis = [d for d in items if d["type"] == "api"]
        lines.append(f"### {category}")
        lines.append("")
        lines.append(f"**数量：** {len(apis)} 个接口")
        lines.append("")
        lines.append("| 接口 | 标题 | 文档ID | 路径 |")
        lines.append("|------|------|--------|------|")
        for item in apis:
            api = f"`{item['api']}`" if item.get("api") else "-"
            rel = item["rel_path"].replace("\\", "/")
            lines.append(
                f"| {api} | {item['title']} | {item['doc_id']} | [{rel}]({rel}) |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def existing_version_note() -> str:
    readme = DOC_ROOT / "README.md"
    if not readme.is_file():
        return "- 官网：https://tushare.pro"
    text = readme.read_text(encoding="utf-8")
    start = text.find("| 项目 |")
    if start < 0 or "| tushare |" not in text:
        return "- 官网：https://tushare.pro"
    lines: list[str] = []
    for line in text[start:].splitlines():
        if line.startswith("|"):
            lines.append(line)
            continue
        break
    return "\n".join(lines).strip() or "- 官网：https://tushare.pro"


def parse_front_matter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    meta: dict[str, str] = {}
    for raw in text[3:end].splitlines():
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        meta[key.strip()] = value.strip().strip('"')
    return meta


def docs_from_disk() -> list[dict]:
    items: list[dict] = []
    for path in DOC_ROOT.rglob("*.md"):
        if path.name == "README.md" and path.parent == DOC_ROOT:
            continue
        meta = parse_front_matter(path.read_text(encoding="utf-8"))
        if not meta.get("doc_id"):
            continue
        rel = path.relative_to(DOC_ROOT).as_posix()
        items.append(
            {
                "doc_id": int(meta["doc_id"]) if str(meta["doc_id"]).isdigit() else 0,
                "title": meta.get("title") or path.stem,
                "api": meta.get("api") or None,
                "category": meta.get("category") or "其他",
                "type": meta.get("type") or ("category" if path.name == "README.md" else "api"),
                "rel_path": rel,
            }
        )
    return items


def in_scope(item: dict, start_id: int | None, start_category: str | None) -> bool:
    if start_id is None:
        return True
    if item["doc_id"] == start_id:
        return True
    if start_category:
        return item["category"] == start_category or item["category"].startswith(
            start_category + "/"
        )
    return False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="爬取 Tushare 文档到 doc/tushare")
    parser.add_argument(
        "--start-id",
        default="https://tushare.pro/document/2?doc_id=24",
        help="起始 doc_id 或文档 URL，作为发现入口之一",
    )
    parser.add_argument(
        "--only-start",
        action="store_true",
        help="只保存起始分类及其子文档；默认保存全部发现的文档",
    )
    parser.add_argument("--max-docs", type=int, default=0, help="最多抓取正文数，0 表示不限制")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL, help="请求间隔秒")
    parser.add_argument("--dry-run", action="store_true", help="只发现和打印，不写文件")
    parser.add_argument("--index-only", action="store_true", help="不爬取，仅根据已有文件重建索引")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_stdio()
    if args.index_only:
        written = docs_from_disk()
        if not written:
            log("本地没有可索引的知识文档")
            return 1
        index = build_index(written, existing_version_note())
        write_text(DOC_ROOT / "README.md", index, args.dry_run)
        log(f"已根据本地文件重建索引：接口 {sum(1 for d in written if d['type']=='api')}，分类 {sum(1 for d in written if d['type']=='category')}")
        return 0
    start_id = parse_start_id(args.start_id)
    save_all = not args.only_start
    interval = max(0.05, args.interval)

    catalog = load_local_catalog(CATALOG_PATH)
    log(f"本地目录 {len(catalog)} 条：{CATALOG_PATH if CATALOG_PATH.is_file() else '不存在'}")

    queue: deque[int] = deque()
    seen: set[int] = set()

    def enqueue(doc_id: int) -> None:
        if doc_id <= 0 or doc_id in seen or doc_id in SKIP_DOC_IDS:
            return
        seen.add(doc_id)
        queue.append(doc_id)

    if start_id:
        enqueue(start_id)
    for doc_id in sorted(SEED_CATEGORY_IDS):
        enqueue(doc_id)
    for doc_id in catalog:
        enqueue(doc_id)

    log("抓取文档索引页…")
    for doc_id in sorted(fetch_index_ids()):
        enqueue(doc_id)
    log(f"待抓取 {len(queue)} 个 doc_id")

    fetched: dict[int, dict] = {}
    pulled = 0
    while queue:
        if args.max_docs and pulled >= args.max_docs:
            log(f"已达 --max-docs={args.max_docs}，停止抓取正文")
            break
        doc_id = queue.popleft()
        time.sleep(interval)
        try:
            body = fetch_markdown(doc_id)
        except Exception as exc:  # noqa: BLE001
            log(f"  doc_id={doc_id} 失败: {exc}")
            continue
        pulled += 1
        child_ids = extract_doc_ids(body)
        for child in child_ids:
            enqueue(child)

        meta = catalog.get(doc_id, {})
        if not body.strip() and meta:
            body = (
                f"接口：{meta.get('api') or ''}\n"
                f"描述：{meta.get('desc') or '官方 Markdown 已不可用。'}\n\n"
                "官方文档页面当前返回 404，以下信息来自本地接口目录，仅作知识索引。"
            )
            log(f"  doc_id={doc_id} 官方正文缺失，使用目录摘要")
        api = extract_api(body, meta.get("api"))
        title = CATEGORY_ID_TITLES.get(doc_id) or meta.get("title") or extract_title(body, f"doc_{doc_id}")
        doc_type = "api" if is_api_doc(body) or meta.get("api") else "category"
        if meta.get("parts"):
            parts = meta["parts"]
        elif doc_id in CATEGORY_ID_TITLES:
            parts = category_parts(CATEGORY_ID_TITLES[doc_id])
        elif doc_type == "category":
            parts = category_parts(title)
        else:
            parts = infer_parts(title, api) or ("其他",)
        parts = sanitize_parts(parts)
        category = join_category(parts)
        fetched[doc_id] = {
            "doc_id": doc_id,
            "title": title,
            "api": api,
            "parts": parts,
            "category": category,
            "type": doc_type,
            "body": body,
            "children": child_ids,
        }
        mark = "接口" if doc_type == "api" else "分类"
        log(f"  [{pulled}] {mark} {doc_id} {title}" + (f" ({api})" if api else ""))

    if not fetched:
        log("没有抓到任何文档")
        return 1

    # 用可靠的分类页补全尚未归类的叶子文档。
    for item in fetched.values():
        if item["type"] != "category" or not is_useful_category(item):
            continue
        parent_parts = item["parts"]
        if not parent_parts or parent_parts == ("其他",):
            continue
        for child_id in item["children"]:
            child = fetched.get(child_id)
            if not child or child["doc_id"] in catalog or child["type"] != "api":
                continue
            if child["category"] == "其他":
                child["parts"] = parent_parts
                child["category"] = join_category(parent_parts)

    for item in fetched.values():
        if item["type"] == "api" and item["category"] == "其他":
            inferred = infer_parts(item["title"], item.get("api"))
            if inferred:
                item["parts"] = inferred
                item["category"] = join_category(inferred)

    start_category = None
    if start_id and start_id in fetched:
        start_category = fetched[start_id]["category"]
    elif start_id and start_id in catalog:
        start_category = catalog[start_id]["category"]

    written: list[dict] = []
    used_paths: set[Path] = set()
    for item in sorted(fetched.values(), key=lambda x: (x["category"], x["type"], x["doc_id"])):
        if not save_all and not in_scope(item, start_id, start_category):
            continue
        if item["type"] == "category" and not is_useful_category(item):
            continue
        if not item["body"] or len(item["body"].strip()) < MIN_BODY_LEN:
            continue
        parts = sanitize_parts(item["parts"])
        item["parts"] = parts
        item["category"] = join_category(parts)
        rel_dir = Path(*parts) if parts else Path()
        filename = "README.md" if item["type"] == "category" else sanitize_filename(item["title"]) + ".md"
        abs_dir = DOC_ROOT / rel_dir
        path = abs_dir / filename
        if item["type"] == "category" and path in used_paths:
            continue
        if path in used_paths:
            path = abs_dir / f"{Path(filename).stem}_{item['doc_id']}{Path(filename).suffix}"
        used_paths.add(path)
        rel_path = path.relative_to(DOC_ROOT).as_posix()
        content = render_doc(
            title=item["title"],
            doc_id=item["doc_id"],
            api=item["api"],
            category=item["category"],
            body=item["body"],
            doc_type=item["type"],
        )
        try:
            write_text(path, content, args.dry_run)
        except OSError as exc:
            log(f"  写入失败 {rel_path}: {exc}")
            continue
        record = dict(item)
        record["rel_path"] = rel_path
        written.append(record)
        action = "将写入" if args.dry_run else "已写入"
        log(f"  {action} {rel_path}")

    if not written:
        log("过滤后没有可保存的文档。默认会保存全部；--only-start 才会按起始分类裁剪")
        return 1

    index = build_index(written, existing_version_note())
    write_text(DOC_ROOT / "README.md", index, args.dry_run)
    log(f"{'将更新' if args.dry_run else '已更新'} {DOC_ROOT / 'README.md'}")
    log(f"完成：接口 {sum(1 for d in written if d['type']=='api')}，分类 {sum(1 for d in written if d['type']=='category')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
