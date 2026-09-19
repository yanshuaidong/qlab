# -*- coding: utf-8 -*-
"""把 DeepSeek 官方中文 API 文档同步到本地 Markdown。

用法：
    python main.py

输出目录：与本脚本同级，目录和文件名使用中文。
"""

from __future__ import annotations

import os
import re
import time
from datetime import date
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

BASE = "https://api-docs.deepseek.com"
ROOT = "/zh-cn"
HERE = Path(__file__).resolve().parent
OUT_DIR = HERE
IMG_DIR = OUT_DIR / "图片"
TODAY = date.today().isoformat()

DIR_MAP = {
    "quick_start": "快速开始",
    "agent_integrations": "接入工具",
    "guides": "指南",
    "api": "API文档",
    "news": "新闻",
    "img": "图片",
}

FILE_MAP = {
    "index.md": "首次调用API.md",
    "faq.md": "常见问题.md",
    "updates.md": "更新日志.md",
    "prompt-library.md": "提示词库.md",
    "pricing.md": "模型与价格.md",
    "token_usage.md": "Token用量计算.md",
    "rate_limit.md": "限速与隔离.md",
    "error_codes.md": "错误码.md",
    "astrbot.md": "接入AstrBot.md",
    "claude_code.md": "接入ClaudeCode.md",
    "codex.md": "接入Codex.md",
    "copilot_cli.md": "接入GitHubCopilotCLI.md",
    "crush.md": "接入Crush.md",
    "deepcode.md": "集成DeepCode.md",
    "github_copilot.md": "接入GitHubCopilot.md",
    "hermes.md": "接入Hermes.md",
    "kilo_code.md": "接入KiloCode.md",
    "langcli.md": "接入Langcli.md",
    "nanobot.md": "接入nanobot.md",
    "oh_my_pi.md": "在OhMyPi中使用.md",
    "openclaw.md": "接入OpenClaw.md",
    "opencode.md": "接入OpenCode.md",
    "pi_mono.md": "接入Pi.md",
    "qoder.md": "接入Qoder.md",
    "reasonix.md": "接入Reasonix.md",
    "workbuddy.md": "接入WorkBuddy.md",
    "vision.md": "图像理解.md",
    "thinking_mode.md": "思考模式.md",
    "multi_round_chat.md": "多轮对话.md",
    "chat_prefix_completion.md": "对话前缀续写.md",
    "fim_completion.md": "FIM补全.md",
    "json_mode.md": "JSON输出.md",
    "tool_calls.md": "工具调用.md",
    "files_api.md": "文件API.md",
    "kv_cache.md": "上下文硬盘缓存.md",
    "responses_api.md": "使用ResponsesAPI.md",
    "anthropic_api.md": "使用AnthropicAPI.md",
    "coding_agents.md": "接入Agent工具.md",
    "comparison_testing.md": "对比测试.md",
    "create-chat-completion.md": "对话补全.md",
    "create-response.md": "ResponsesAPI.md",
    "create-completion.md": "FIM补全API.md",
    "list-models.md": "获取模型列表.md",
    "get-user-balance.md": "查询余额.md",
    "create-file.md": "上传文件.md",
    "list-files.md": "列出文件.md",
    "retrieve-file.md": "查询文件.md",
    "delete-file.md": "删除文件.md",
    "deepseek-api.md": "DeepSeekAPI.md",
    "news0725.md": "API升级支持续写FIM.md",
    "news0802.md": "硬盘缓存降价.md",
    "news0905.md": "DeepSeek-V2.5发布.md",
    "news1120.md": "推理模型预览版.md",
    "news1210.md": "V2系列收官.md",
    "news1226.md": "DeepSeek-V3正式发布.md",
    "news250115.md": "DeepSeekAPP.md",
    "news250120.md": "DeepSeek-R1发布.md",
    "news250325.md": "V3模型更新.md",
    "news250528.md": "R1更新.md",
    "news250821.md": "V3.1发布.md",
    "news250922.md": "V3.1版本更新.md",
    "news250929.md": "V3.2-Exp发布.md",
    "news251201.md": "V3.2正式版.md",
    "news260424.md": "V4预览版.md",
    "news260813.md": "V4-Pro正式版.md",
    "news260821.md": "V4-Flash-Vision上线.md",
    "news260910.md": "V4.1Flash发布.md",
}

HEADERS = {
    "User-Agent": "qlab-doc-mirror/1.0 (+local archive of https://api-docs.deepseek.com/zh-cn/)",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 侧栏折叠分类的入口页，访问后可展开子链接
SEED_PAGES = [
    f"{BASE}{ROOT}/",
    f"{BASE}{ROOT}/quick_start/pricing",
    f"{BASE}{ROOT}/quick_start/token_usage",
    f"{BASE}{ROOT}/quick_start/rate_limit",
    f"{BASE}{ROOT}/quick_start/error_codes",
    f"{BASE}{ROOT}/quick_start/agent_integrations/claude_code",
    f"{BASE}{ROOT}/guides/vision",
    f"{BASE}{ROOT}/guides/thinking_mode",
    f"{BASE}{ROOT}/api/create-chat-completion",
    f"{BASE}{ROOT}/api/create-file",
    f"{BASE}{ROOT}/news/news260910",
    f"{BASE}{ROOT}/updates",
    f"{BASE}{ROOT}/faq",
    f"{BASE}{ROOT}/prompt-library",
    f"{BASE}{ROOT}/guides/coding_agents",
]

# JS 里存在、侧栏不一定展开的页面
EXTRA_PAGES = [
    f"{BASE}{ROOT}/api/create-response",
    f"{BASE}{ROOT}/api/create-completion",
    f"{BASE}{ROOT}/api/list-models",
    f"{BASE}{ROOT}/api/get-user-balance",
    f"{BASE}{ROOT}/api/list-files",
    f"{BASE}{ROOT}/api/retrieve-file",
    f"{BASE}{ROOT}/api/delete-file",
    f"{BASE}{ROOT}/api/deepseek-api",
    f"{BASE}{ROOT}/quick_start/agent_integrations/codex",
    f"{BASE}{ROOT}/quick_start/agent_integrations/opencode",
    f"{BASE}{ROOT}/quick_start/agent_integrations/openclaw",
    f"{BASE}{ROOT}/quick_start/agent_integrations/hermes",
    f"{BASE}{ROOT}/quick_start/agent_integrations/reasonix",
    f"{BASE}{ROOT}/quick_start/agent_integrations/workbuddy",
    f"{BASE}{ROOT}/quick_start/agent_integrations/qoder",
    f"{BASE}{ROOT}/quick_start/agent_integrations/astrbot",
    f"{BASE}{ROOT}/quick_start/agent_integrations/copilot_cli",
    f"{BASE}{ROOT}/quick_start/agent_integrations/crush",
    f"{BASE}{ROOT}/quick_start/agent_integrations/deepcode",
    f"{BASE}{ROOT}/quick_start/agent_integrations/github_copilot",
    f"{BASE}{ROOT}/quick_start/agent_integrations/kilo_code",
    f"{BASE}{ROOT}/quick_start/agent_integrations/langcli",
    f"{BASE}{ROOT}/quick_start/agent_integrations/nanobot",
    f"{BASE}{ROOT}/quick_start/agent_integrations/oh_my_pi",
    f"{BASE}{ROOT}/quick_start/agent_integrations/pi_mono",
]

SKIP_PATH_RE = re.compile(
    r"/assets/|/api_samples/|/docusaurus-plugin-content-docs/"
    r"|/img/|\.(?:js|css|map|svg|png|jpe?g|gif|webp|ico)$",
    re.I,
)

PAGE_ORDER = {
    "首次调用API.md": 0,
    "快速开始/模型与价格.md": 1,
    "快速开始/Token用量计算.md": 2,
    "快速开始/限速与隔离.md": 3,
    "快速开始/错误码.md": 4,
    "指南/图像理解.md": 10,
    "指南/思考模式.md": 11,
    "指南/多轮对话.md": 12,
    "指南/对话前缀续写.md": 13,
    "指南/FIM补全.md": 14,
    "指南/JSON输出.md": 15,
    "指南/工具调用.md": 16,
    "指南/文件API.md": 17,
    "指南/上下文硬盘缓存.md": 18,
    "指南/使用ResponsesAPI.md": 19,
    "指南/使用AnthropicAPI.md": 20,
    "API文档/对话补全.md": 30,
    "API文档/ResponsesAPI.md": 31,
    "API文档/FIM补全API.md": 32,
    "API文档/获取模型列表.md": 33,
    "API文档/查询余额.md": 34,
    "API文档/上传文件.md": 35,
    "API文档/列出文件.md": 36,
    "API文档/查询文件.md": 37,
    "API文档/删除文件.md": 38,
    "API文档/DeepSeekAPI.md": 39,
}


def normalize_url(url: str) -> str:
    url = unescape(url).split("#")[0].split("?")[0]
    parsed = urlparse(url)
    if parsed.netloc and parsed.netloc != "api-docs.deepseek.com":
        return url
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    if path in ("", "/"):
        path = f"{ROOT}/"
    if path == ROOT:
        path = f"{ROOT}/"
    return f"{BASE}{path}" if path.startswith("/") else url


def is_doc_url(url: str) -> bool:
    if not url.startswith(BASE):
        return False
    path = urlparse(url).path
    if not path.startswith(f"{ROOT}"):
        return False
    if SKIP_PATH_RE.search(path):
        return False
    return True


def url_to_relpath(url: str) -> Path:
    path = urlparse(normalize_url(url)).path
    if path in (f"{ROOT}", f"{ROOT}/"):
        return Path(FILE_MAP["index.md"])
    rel = path[len(ROOT) :].lstrip("/")
    parts = rel.split("/")
    dirs = [DIR_MAP.get(part, part) for part in parts[:-1]]
    filename = FILE_MAP.get(parts[-1] + ".md", parts[-1] + ".md")
    return Path(*dirs, filename) if dirs else Path(filename)


def local_md_path(url: str) -> Path:
    return OUT_DIR / url_to_relpath(url)


def rel_between(from_md: Path, to_md: Path) -> str:
    return Path(os.path.relpath(to_md, from_md.parent)).as_posix()


class Mirror:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.pages: dict[str, dict] = {}
        self.images: dict[str, Path] = {}

    def get(self, url: str) -> requests.Response:
        last_err = None
        for attempt in range(3):
            try:
                resp = self.session.get(url, timeout=30)
                # 官网常不带 charset，requests 会误判成 latin-1，导致中文乱码
                if "charset" not in (resp.headers.get("content-type") or "").lower():
                    resp.encoding = "utf-8"
                return resp
            except requests.RequestException as exc:
                last_err = exc
                time.sleep(1.2 * (attempt + 1))
        raise RuntimeError(f"请求失败 {url}: {last_err}")

    def discover(self) -> list[str]:
        seen: set[str] = set()
        queue = [normalize_url(u) for u in SEED_PAGES + EXTRA_PAGES]
        found: list[str] = []

        while queue:
            url = queue.pop(0)
            url = normalize_url(url)
            if url in seen or not is_doc_url(url):
                continue
            seen.add(url)
            print(f"[discover] {url}", flush=True)
            try:
                resp = self.get(url)
            except Exception as exc:
                print(f"  skip: {exc}", flush=True)
                continue
            final = normalize_url(resp.url)
            if resp.status_code != 200 or "text/html" not in resp.headers.get("content-type", ""):
                print(f"  skip status={resp.status_code}", flush=True)
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            h1 = soup.select_one("article h1, .theme-doc-markdown h1, h1")
            title = ""
            if h1 is not None:
                title = h1.get_text(" ", strip=True)
            if not title:
                title = (soup.title.string or "").replace(" | DeepSeek API Docs", "").strip()
            article = (
                soup.select_one("article .theme-doc-markdown")
                or soup.select_one("article .markdown")
                or soup.select_one(".theme-doc-markdown")
                or soup.select_one("article")
            )
            if article is None:
                print("  skip: no article", flush=True)
                continue
            self.pages[final] = {"title": title, "soup": soup, "article": article, "url": final}
            found.append(final)
            for a in soup.select("a[href]"):
                href = a.get("href") or ""
                if href.startswith("#") or href.startswith("mailto:"):
                    continue
                absu = normalize_url(urljoin(final, href))
                if is_doc_url(absu) and absu not in seen:
                    queue.append(absu)
            time.sleep(0.15)
        return found

    def convert_all(self) -> None:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        IMG_DIR.mkdir(parents=True, exist_ok=True)
        for url, meta in self.pages.items():
            md_path = local_md_path(url)
            md_path.parent.mkdir(parents=True, exist_ok=True)
            body = self.html_to_md(meta["article"], md_path, page_url=url)
            body = cleanup_markdown(body)
            header = (
                f"---\n"
                f"title: {yaml_escape(meta['title'])}\n"
                f"source: {url}\n"
                f"fetched: {TODAY}\n"
                f"---\n\n"
                f"# {meta['title']}\n\n"
                f"> 来源：[{url}]({url})\n\n"
            )
            # 正文里通常已有同名 h1，去掉重复
            body = re.sub(rf"^#\s+{re.escape(meta['title'])}\s*\n+", "", body, count=1)
            md_path.write_text(header + body.strip() + "\n", encoding="utf-8", newline="\n")
            print(f"[write] {md_path.relative_to(HERE)}", flush=True)

    def html_to_md(self, root: Tag, md_path: Path, page_url: str) -> str:
        for nav in root.select("nav.theme-doc-toc-desktop, nav.theme-doc-toc-mobile, .table-of-contents"):
            nav.decompose()
        for node in root.select("button, svg, .hash-link, .clean-btn"):
            node.decompose()
        return self._block(root, md_path, page_url).strip() + "\n"

    def _block(self, node: Tag, md_path: Path, page_url: str) -> str:
        parts: list[str] = []
        for child in node.children:
            if isinstance(child, NavigableString):
                text = str(child)
                if text.strip():
                    parts.append(text)
                continue
            if not isinstance(child, Tag):
                continue
            name = child.name.lower()
            classes = child.get("class") or []
            if name in {"script", "style", "svg", "button", "nav"}:
                continue
            if "pagination-nav" in classes or "theme-doc-footer" in classes:
                continue
            if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                level = int(name[1])
                text = self._inline(child, md_path, page_url).strip()
                if text:
                    parts.append(f"{'#' * level} {text}\n\n")
                continue
            if name == "p":
                text = self._inline(child, md_path, page_url).strip()
                if text:
                    parts.append(text + "\n\n")
                continue
            if name == "pre":
                parts.append(self._code(child) + "\n\n")
                continue
            if name == "table":
                parts.append(self._table(child, md_path, page_url) + "\n\n")
                continue
            if name in {"ul", "ol"}:
                parts.append(self._list(child, md_path, page_url, ordered=name == "ol") + "\n")
                continue
            if name == "blockquote":
                inner = self._block(child, md_path, page_url).strip()
                quoted = "\n".join(f"> {line}" if line else ">" for line in inner.splitlines())
                parts.append(quoted + "\n\n")
                continue
            if name == "hr":
                parts.append("---\n\n")
                continue
            if name == "img":
                parts.append(self._image(child, md_path, page_url) + "\n\n")
                continue
            if name == "details":
                summary = child.find("summary")
                title = self._inline(summary, md_path, page_url).strip() if summary else "详情"
                if summary:
                    summary.extract()
                inner = self._block(child, md_path, page_url).strip()
                parts.append(f"<details>\n<summary>{title}</summary>\n\n{inner}\n\n</details>\n\n")
                continue
            if "tabs-container" in classes:
                parts.append(self._tabs(child, md_path, page_url))
                continue
            if name in {"div", "section", "article", "main", "span", "figure", "figcaption", "header", "footer"}:
                parts.append(self._block(child, md_path, page_url))
                continue
            if name == "br":
                parts.append("\n")
                continue
            if name == "li":
                parts.append(self._inline(child, md_path, page_url) + "\n")
                continue
            parts.append(self._block(child, md_path, page_url))
        return "".join(parts)

    def _inline(self, node: Tag | NavigableString | None, md_path: Path, page_url: str) -> str:
        if node is None:
            return ""
        if isinstance(node, NavigableString):
            return collapse_ws(str(node))
        parts: list[str] = []
        for child in node.children:
            if isinstance(child, NavigableString):
                parts.append(collapse_ws(str(child)))
                continue
            if not isinstance(child, Tag):
                continue
            name = child.name.lower()
            if name in {"svg", "button", "script", "style"}:
                continue
            if name == "br":
                parts.append("\n")
                continue
            if name == "img":
                parts.append(self._image(child, md_path, page_url))
                continue
            if name == "a":
                href = child.get("href") or ""
                text = self._inline(child, md_path, page_url).strip() or href
                if href.startswith("#"):
                    parts.append(text)
                    continue
                absu = urljoin(page_url, href)
                if is_doc_url(normalize_url(absu)):
                    target = local_md_path(absu)
                    href = rel_between(md_path, target)
                    frag = urlparse(child.get("href") or "").fragment
                    if frag:
                        href += f"#{frag}"
                parts.append(f"[{text}]({href})")
                continue
            if name == "code":
                code = child.get_text("", strip=False)
                code = code.replace("`", "\\`")
                parts.append(f"`{code.strip()}`")
                continue
            if name in {"strong", "b"}:
                parts.append(f"**{self._inline(child, md_path, page_url).strip()}**")
                continue
            if name in {"em", "i"}:
                parts.append(f"*{self._inline(child, md_path, page_url).strip()}*")
                continue
            if name == "sup":
                parts.append(f"^{self._inline(child, md_path, page_url).strip()}^")
                continue
            if name == "pre":
                parts.append("\n" + self._code(child) + "\n")
                continue
            parts.append(self._inline(child, md_path, page_url))
        return "".join(parts)

    def _code(self, pre: Tag) -> str:
        clone = BeautifulSoup(str(pre), "html.parser")
        node = clone.find("pre") or clone
        for br in node.find_all("br"):
            br.replace_with("\n")
        lang = ""
        classes = " ".join(pre.get("class") or [])
        match = re.search(r"language-([A-Za-z0-9_+-]+)", classes)
        if match:
            lang = match.group(1)
        text = node.get_text("")
        text = text.replace("\u00a0", " ").rstrip() + "\n"
        fence = "```"
        if "```" in text:
            fence = "````"
        return f"{fence}{lang}\n{text}{fence}"

    def _table(self, table: Tag, md_path: Path, page_url: str) -> str:
        rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = []
            for cell in tr.find_all(["th", "td"]):
                text = self._inline(cell, md_path, page_url)
                text = re.sub(r"\s+", " ", text).strip().replace("|", "\\|")
                cells.append(text)
            if cells:
                rows.append(cells)
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        for row in rows:
            while len(row) < width:
                row.append("")
        header = rows[0]
        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
        ]
        for row in rows[1:]:
            lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)

    def _list(self, node: Tag, md_path: Path, page_url: str, ordered: bool) -> str:
        lines: list[str] = []
        index = 1
        for li in node.find_all("li", recursive=False):
            nested = ""
            sublists = li.find_all(["ul", "ol"], recursive=False)
            for sub in sublists:
                nested += self._list(sub, md_path, page_url, ordered=sub.name == "ol")
                sub.extract()
            text = self._inline(li, md_path, page_url).strip()
            prefix = f"{index}." if ordered else "-"
            lines.append(f"{prefix} {text}")
            if nested:
                for nline in nested.splitlines():
                    lines.append("  " + nline)
            index += 1
        return "\n".join(lines) + "\n"

    def _tabs(self, node: Tag, md_path: Path, page_url: str) -> str:
        labels = [
            self._inline(item, md_path, page_url).strip()
            for item in node.select('[role="tab"], .tabs__item')
        ]
        panels = node.select('[role="tabpanel"]')
        if not panels:
            panels = [c for c in node.find_all("div", recursive=False) if c.get_text(strip=True)]
        parts = ["\n"]
        for i, panel in enumerate(panels):
            label = labels[i] if i < len(labels) else f"示例 {i + 1}"
            if label:
                parts.append(f"**{label}**\n\n")
            parts.append(self._block(panel, md_path, page_url))
        return "".join(parts)

    def _image(self, img: Tag, md_path: Path, page_url: str) -> str:
        src = img.get("src") or ""
        alt = (img.get("alt") or "").strip() or Path(urlparse(src).path).name
        if not src:
            return alt
        absu = urljoin(page_url, src)
        local = self.download_image(absu)
        if local is None:
            return f"![{alt}]({absu})"
        rel = rel_between(md_path, local)
        return f"![{alt}]({rel})"

    def download_image(self, url: str) -> Path | None:
        url = url.split("?")[0]
        if url in self.images:
            return self.images[url]
        parsed = urlparse(url)
        if parsed.netloc and parsed.netloc != "api-docs.deepseek.com":
            return None
        name = Path(unquote(parsed.path)).name
        if not name:
            return None
        dest = IMG_DIR / name
        if dest.exists() and dest.stat().st_size > 0:
            self.images[url] = dest
            return dest
        print(f"[img] {url}", flush=True)
        try:
            resp = self.get(url)
        except Exception as exc:
            print(f"  img fail: {exc}", flush=True)
            return None
        if resp.status_code != 200 or not resp.content:
            return None
        dest.write_bytes(resp.content)
        self.images[url] = dest
        return dest


def collapse_ws(text: str) -> str:
    text = unescape(text).replace("\u00a0", " ").replace("\u200b", "")
    return re.sub(r"[ \t]+", " ", text)


def yaml_escape(text: str) -> str:
    if any(ch in text for ch in ":#{}[],&*?|-<>=!%@`'\""):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def cleanup_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\x00", "")
    text = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad]", "", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    # 去掉页内「本页总览」空目录
    text = re.sub(r"^## 本页总览\n(?:\n|[-*].*\n)*", "", text, flags=re.M)
    return text.strip() + "\n"


def write_index(pages: dict[str, dict]) -> None:
    groups: dict[str, list[tuple[str, Path, str]]] = {
        "快速开始": [],
        "接入 Agent 工具": [],
        "API 指南": [],
        "API 文档": [],
        "新闻": [],
        "其它": [],
    }
    for url, meta in pages.items():
        rel = url_to_relpath(url)
        posix = rel.as_posix()
        if posix.startswith("快速开始/接入工具/"):
            key = "接入 Agent 工具"
        elif posix.startswith("快速开始/") or posix == "首次调用API.md":
            key = "快速开始"
        elif posix.startswith("指南/"):
            key = "API 指南"
        elif posix.startswith("API文档/"):
            key = "API 文档"
        elif posix.startswith("新闻/"):
            key = "新闻"
        else:
            key = "其它"
        groups[key].append((meta["title"], rel, url))

    def sort_key(item: tuple[str, Path, str]) -> tuple[int, str]:
        posix = item[1].as_posix()
        return (PAGE_ORDER.get(posix, 100), posix)

    lines = [
        "# DeepSeek API 官方文档（本地镜像）",
        "",
        f"同步日期：{TODAY}",
        "",
        "本目录由 [main.py](./main.py) 从 [DeepSeek API 中文文档](https://api-docs.deepseek.com/zh-cn/) 抓取并转成 Markdown，便于离线查阅。",
        "",
        "重新同步：",
        "",
        "```bash",
        "python doc/deepseek/main.py",
        "```",
        "",
        "官方文档可能随时更新，本地内容以每次同步时的网页为准。",
        "",
    ]
    for section in ["快速开始", "接入 Agent 工具", "API 指南", "API 文档", "新闻", "其它"]:
        items = sorted(groups[section], key=sort_key)
        if not items:
            continue
        lines.append(f"## {section}")
        lines.append("")
        for title, rel, url in items:
            lines.append(f"- [{title}]({rel.as_posix()}) — {url}")
        lines.append("")

    lines.extend(
        [
            "## 外部链接（未镜像）",
            "",
            "- [申请 API Key](https://platform.deepseek.com/api_keys)",
            "- [DeepSeek Harness 入门](https://deepseek-harness.github.io/deepseek-harness/guide/quickstart)",
            "- [官方 FAQ](https://static.deepseek.com/faq/index.html?lang=zh#/category/4)",
            "- [Awesome DeepSeek Integration](https://github.com/deepseek-ai/awesome-deepseek-integration/tree/main)",
            "- [贡献你的 Agent 接入](https://github.com/deepseek-ai/awesome-deepseek-agent/tree/main)",
            "",
        ]
    )
    (HERE / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("[write] README.md", flush=True)


def main() -> None:
    mirror = Mirror()
    found = mirror.discover()
    print(f"discovered {len(found)} pages", flush=True)
    if not found:
        raise SystemExit("没有抓到任何文档页")
    mirror.convert_all()
    write_index(mirror.pages)
    print("done", flush=True)


if __name__ == "__main__":
    main()
