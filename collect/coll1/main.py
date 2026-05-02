"""
同花顺主力数据采集总入口。

用法：
  python collect/main.py
  python collect/main.py test

不加参数进入正常菜单；加 test 参数时仍进入菜单，但第 3/4 步只处理前 3 只股票。
"""
from __future__ import annotations

import argparse
import ctypes
import json
import re
import sqlite3
import sys
import time
from collections import Counter
from ctypes import wintypes
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pyautogui
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

try:
    import pytesseract
except ImportError:  # pragma: no cover
    pytesseract = None

try:
    from cnocr import CnOcr
except ImportError:  # pragma: no cover
    CnOcr = None


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
RUNS_DIR = BASE_DIR / "runs"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "ths_fund_flow.sqlite"
STEP2_DIR = BASE_DIR / "step2"

DEFAULT_LATEST_TRADE_DATE = "2026-04-30"
DATE_FMT = "%Y-%m-%d"
TEST_LIMIT = 3
CONFIGURE_OVERLAY_DELAY_SECONDS = 3
QUIT_COMMANDS = {"q", "quit", "exit", "0"}

HWND_TOP = 0
MONITOR_DEFAULTTOPRIMARY = 0x00000001
SW_RESTORE = 9
SWP_SHOWWINDOW = 0x0040
SPI_GETWORKAREA = 0x0030
DEFAULT_TITLE_KEYWORD = "同花顺"
MIN_WINDOW_WIDTH = 240
MIN_WINDOW_HEIGHT = 160


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def to_region(self) -> tuple[int, int, int, int]:
        return self.left, self.top, self.width, self.height

    def to_dict(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
            "width": self.width,
            "height": self.height,
        }

    def row_rect(self, row_index: int, rows_per_screen: int) -> "Rect":
        row_top = self.top + round(self.height * row_index / rows_per_screen)
        row_bottom = self.top + round(self.height * (row_index + 1) / rows_per_screen)
        return Rect(self.left, row_top, self.right, row_bottom)

    def center(self) -> tuple[int, int]:
        return self.left + self.width // 2, self.top + self.height // 2

    @classmethod
    def from_win_rect(cls, rect: wintypes.RECT) -> "Rect":
        return cls(rect.left, rect.top, rect.right, rect.bottom)


@dataclass(frozen=True)
class WindowMatch:
    hwnd: int
    title: str
    rect: Rect

    @property
    def area(self) -> int:
        return self.rect.width * self.rect.height


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_USER32: Any = None
_USER32_READY = False


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_positive_rect(rect: Rect) -> Rect:
    left, right = sorted([rect.left, rect.right])
    top, bottom = sorted([rect.top, rect.bottom])
    normalized = Rect(left, top, right, bottom)
    if normalized.width <= 2 or normalized.height <= 2:
        raise ValueError("框选区域太小，请重新框选。")
    return normalized


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def rect_from_mapping(value: dict[str, Any]) -> Rect:
    return Rect(
        left=int(value["left"]),
        top=int(value["top"]),
        right=int(value["right"]),
        bottom=int(value["bottom"]),
    )


def screenshot_rect(rect: Rect) -> Image.Image:
    return pyautogui.screenshot(region=rect.to_region())


def _user32() -> Any:
    global _USER32, _USER32_READY
    if sys.platform != "win32":
        raise RuntimeError("窗口布局功能仅支持 Windows。")
    if _USER32_READY:
        return _USER32

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.SetProcessDPIAware.argtypes = []
    user32.SetProcessDPIAware.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SystemParametersInfoW.argtypes = [
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        wintypes.UINT,
    ]
    user32.SystemParametersInfoW.restype = wintypes.BOOL
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wintypes.BOOL

    _USER32 = user32
    _USER32_READY = True
    return user32


def _last_error_message(prefix: str) -> str:
    error = ctypes.get_last_error()
    return f"{prefix}，WinError={error}" if error else prefix


def _enable_dpi_awareness() -> None:
    _user32().SetProcessDPIAware()


def _window_title(hwnd: int) -> str:
    user32 = _user32()
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value.strip()


def _window_rect(hwnd: int) -> Rect | None:
    rect = wintypes.RECT()
    if not _user32().GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return Rect.from_win_rect(rect)


def enumerate_matching_windows(
    title_keyword: str = DEFAULT_TITLE_KEYWORD,
    min_width: int = MIN_WINDOW_WIDTH,
    min_height: int = MIN_WINDOW_HEIGHT,
) -> list[WindowMatch]:
    user32 = _user32()
    matches: list[WindowMatch] = []

    @EnumWindowsProc
    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True

        title = _window_title(hwnd)
        if title_keyword not in title:
            return True

        rect = _window_rect(hwnd)
        if rect is None or rect.width < min_width or rect.height < min_height:
            return True

        matches.append(WindowMatch(hwnd=hwnd, title=title, rect=rect))
        return True

    if not user32.EnumWindows(callback, 0):
        raise OSError(_last_error_message("EnumWindows 失败"))

    return sorted(matches, key=lambda item: item.area, reverse=True)


def find_main_window(title_keyword: str = DEFAULT_TITLE_KEYWORD) -> tuple[WindowMatch | None, list[WindowMatch]]:
    matches = enumerate_matching_windows(title_keyword)
    return (matches[0], matches) if matches else (None, [])


def primary_work_area() -> Rect:
    rect = wintypes.RECT()
    if not _user32().SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
        raise OSError(_last_error_message("获取主屏工作区失败"))
    return Rect.from_win_rect(rect)


def window_monitor_work_area(hwnd: int) -> Rect:
    user32 = _user32()
    monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTOPRIMARY)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        raise OSError(_last_error_message("获取窗口所在显示器工作区失败"))
    return Rect.from_win_rect(info.rcWork)


def print_window_matches(matches: list[WindowMatch]) -> None:
    for index, match in enumerate(matches, 1):
        rect = match.rect
        print(
            f"{index}. hwnd={match.hwnd} title={match.title!r} "
            f"rect=({rect.left},{rect.top},{rect.width}x{rect.height})"
        )


def layout_ths_window(
    title_keyword: str = DEFAULT_TITLE_KEYWORD,
    height_ratio: float = 0.8,
    use_window_monitor: bool = False,
    dry_run: bool = False,
) -> bool:
    if not 0 < height_ratio <= 1:
        raise ValueError("height_ratio 必须在 0 到 1 之间。")

    _enable_dpi_awareness()
    user32 = _user32()
    window, matches = find_main_window(title_keyword)
    if window is None:
        print(f"未找到标题含「{title_keyword}」的可见窗口；请先打开目标程序。")
        return False

    if len(matches) > 1:
        print("匹配到多个窗口，已选面积最大者：")
        print_window_matches(matches)
    else:
        print(f"匹配窗口：{window.title!r}")

    work_area = window_monitor_work_area(window.hwnd) if use_window_monitor else primary_work_area()
    target_x = work_area.left
    target_y = work_area.top
    target_w = work_area.width
    target_h = max(1, round(work_area.height * height_ratio))

    if dry_run:
        print(f"预览调整：左上角 ({target_x},{target_y})，宽 {target_w}，高 {target_h}。")
        return True

    user32.ShowWindow(window.hwnd, SW_RESTORE)
    if not user32.SetWindowPos(window.hwnd, HWND_TOP, target_x, target_y, target_w, target_h, SWP_SHOWWINDOW):
        print(_last_error_message("SetWindowPos 失败（可能权限或窗口被占用）"))
        return False

    print(f"已调整：左上角 ({target_x},{target_y})，宽 {target_w}，高 {target_h}。")
    return True


def prepare_stock_code_for_ocr(image: Image.Image, invert: bool = False) -> Image.Image:
    image = image.convert("L")
    image = ImageEnhance.Contrast(image).enhance(2.0)
    image = image.resize((image.width * 3, image.height * 3), Image.Resampling.LANCZOS)
    if invert:
        image = ImageOps.invert(image)
    return image.point(lambda p: 0 if p < 175 else 255)


def ocr_stock_code_image(image: Image.Image, lang: str, psm: int) -> str:
    if pytesseract is None:
        raise RuntimeError("缺少 pytesseract，请先安装后再运行股票代码 OCR。")

    config = f"--psm {psm}"
    text = pytesseract.image_to_string(prepare_stock_code_for_ocr(image), lang=lang, config=config)
    if re.search(r"\d{6}", text):
        return text

    inverted_text = pytesseract.image_to_string(
        prepare_stock_code_for_ocr(image, invert=True),
        lang=lang,
        config=config,
    )
    return inverted_text if len(inverted_text.strip()) > len(text.strip()) else text


def normalize_stock_code_text(text: str) -> str:
    text = text.replace("\n", " ")
    text = re.sub(r"[|｜]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_stock_code(text: str) -> str | None:
    normalized = normalize_stock_code_text(text)
    code_match = re.search(r"(?<!\d)(\d{6})(?!\d)", normalized)
    return code_match.group(1) if code_match else None


def preprocess_scale_for_ocr(image: Image.Image, scale: int = 4, threshold: int = 190) -> Image.Image:
    image = image.convert("L")
    image = ImageOps.autocontrast(image)
    image = ImageEnhance.Contrast(image).enhance(2.5)
    image = image.filter(ImageFilter.SHARPEN)
    image = image.resize((image.width * scale, image.height * scale), Image.Resampling.LANCZOS)
    return image.point(lambda p: 0 if p < threshold else 255)


def normalize_scale_text(text: str) -> str:
    replacements = {
        "\n": " ",
        "\r": " ",
        "，": ",",
        "。": ".",
        "：": ":",
        "％": "%",
        "万乎": "万手",
        "万于": "万手",
        "手 ": "手 ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def score_scale_ocr_text(text: str) -> int:
    normalized = normalize_scale_text(text)
    score = len(re.findall(r"\d+(?:\.\d+)?", normalized)) * 10
    for token in ["买入", "卖出", "净", "成交"]:
        if token in normalized:
            score += 5
    return score + len(normalized)


def ocr_scale_with_tesseract(image: Image.Image, lang: str, psm: int) -> str:
    if pytesseract is None:
        return ""
    config = f"--psm {psm}"
    prepared = preprocess_scale_for_ocr(image)
    try:
        attempts = [
            pytesseract.image_to_string(prepared, lang=lang, config=config),
            pytesseract.image_to_string(ImageOps.invert(prepared), lang=lang, config=config),
        ]
    except Exception:
        return ""
    return max(attempts, key=lambda text: len(text.strip())).strip()


def ocr_scale_with_cnocr(image: Image.Image) -> str:
    if CnOcr is None:
        return ""
    try:
        ocr = CnOcr()
        prepared = preprocess_scale_for_ocr(image, scale=3)
        rows = ocr.ocr(prepared)
    except Exception:
        return ""
    return " ".join(str(row.get("text", "")) for row in rows).strip()


def ocr_scale_image(image: Image.Image, lang: str, psm: int, engine: str) -> tuple[str, str]:
    engines = [engine] if engine != "auto" else ["tesseract", "cnocr"]
    results: list[tuple[str, str]] = []
    for item in engines:
        if item == "tesseract":
            results.append((item, ocr_scale_with_tesseract(image, lang=lang, psm=psm)))
        elif item == "cnocr":
            results.append((item, ocr_scale_with_cnocr(image)))
        else:
            raise ValueError(f"未知 OCR 引擎：{item}")
    return max(results, key=lambda pair: score_scale_ocr_text(pair[1]))


def parse_signed_number(value: str, sign_text: str = "") -> float:
    number = float(value)
    if "卖" in sign_text or "流出" in sign_text or "净卖" in sign_text:
        return -abs(number)
    return number


def parse_turnover_ratio(value: str) -> float:
    match = re.match(r"^([-+]?\d+)(?:\.(\d))?", value)
    if not match:
        return float(value)
    integer, first_decimal = match.groups()
    return float(f"{integer}.{first_decimal or '0'}")


def parse_scale_text(text: str, trade_date: str | None = None) -> dict[str, Any]:
    normalized = normalize_scale_text(text)
    number_texts = re.findall(r"[-+]?\d+(?:\.\d+)?", normalized)
    values = [float(item) for item in number_texts]

    buy_match = re.search(r"买入\s*([-+]?\d+(?:\.\d+)?)\s*万?手?", normalized)
    sell_match = re.search(r"卖出\s*([-+]?\d+(?:\.\d+)?)\s*万?手?", normalized)
    net_match = re.search(r"净\s*(买入|卖出)?\s*([-+]?\d+(?:\.\d+)?)\s*万?手?", normalized)
    ratio_match = re.search(r"占(?:总)?成交\s*([-+]?\d+(?:\.\d+)?)\s*%?", normalized)

    offset = 1 if re.search(r"\d+\s*天", normalized) and len(values) >= 5 else 0
    buy = float(buy_match.group(1)) if buy_match else (values[offset] if len(values) > offset else None)
    sell = float(sell_match.group(1)) if sell_match else (values[offset + 1] if len(values) > offset + 1 else None)

    if net_match:
        net = parse_signed_number(net_match.group(2), net_match.group(1) or "")
    elif len(values) > offset + 2:
        net = values[offset + 2]
    elif buy is not None and sell is not None:
        net = round(buy - sell, 2)
    else:
        net = None

    ratio = parse_turnover_ratio(ratio_match.group(1)) if ratio_match else (
        parse_turnover_ratio(number_texts[offset + 3]) if len(number_texts) > offset + 3 else None
    )

    missing = [
        key
        for key, value in {
            "institution_buy_wan_shou": buy,
            "institution_sell_wan_shou": sell,
            "net_inflow_wan_shou": net,
            "turnover_ratio_percent": ratio,
        }.items()
        if value is None
    ]
    if missing:
        raise ValueError(f"OCR 文本无法解析这些字段：{', '.join(missing)}；原文：{normalized}")

    return {
        "institution_buy_wan_shou": round(float(buy), 2),
        "institution_sell_wan_shou": round(float(sell), 2),
        "net_inflow_wan_shou": round(float(net), 2),
        "turnover_ratio_percent": round(float(ratio), 2),
        "date": trade_date or date.today().isoformat(),
    }


def build_scale_record(
    image_path: Path,
    image: Image.Image,
    rect: Rect | None,
    raw_text: str,
    ocr_engine: str,
    trade_date: str | None,
) -> dict[str, Any]:
    parsed = parse_scale_text(raw_text, trade_date=trade_date)
    return {
        **parsed,
        "source": {
            "image": str(image_path),
            "rect": rect.to_dict() if rect else None,
            "image_size": {"width": image.width, "height": image.height},
            "ocr_engine": ocr_engine,
            "ocr_text": normalize_scale_text(raw_text),
            "captured_at": now_iso(),
        },
    }


def is_quit_command(raw: str) -> bool:
    return raw.strip().lower() in QUIT_COMMANDS


def prompt_int(message: str, default: int, minimum: int = 1, allow_quit: bool = False) -> int:
    while True:
        raw = input(f"{message} [{default}]: ").strip()
        if allow_quit and is_quit_command(raw):
            raise KeyboardInterrupt("已退出配置。")
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            print("请输入整数。")
            continue
        if value < minimum:
            print(f"请输入不小于 {minimum} 的整数。")
            continue
        return value


def prompt_float(message: str, default: float, minimum: float = 0.0, allow_quit: bool = False) -> float:
    while True:
        raw = input(f"{message} [{default}]: ").strip()
        if allow_quit and is_quit_command(raw):
            raise KeyboardInterrupt("已退出配置。")
        if not raw:
            return default
        try:
            value = float(raw)
        except ValueError:
            print("请输入数字。")
            continue
        if value < minimum:
            print(f"请输入不小于 {minimum} 的数字。")
            continue
        return value


def prompt_text(message: str, default: str, allow_quit: bool = False) -> str:
    raw = input(f"{message} [{default}]: ").strip()
    if allow_quit and is_quit_command(raw):
        raise KeyboardInterrupt("已退出配置。")
    return raw or default


def wait_before_config_overlay(step_name: str) -> None:
    raw = input(f"\n{step_name}：按 Enter 后 {CONFIGURE_OVERLAY_DELAY_SECONDS} 秒开始框选；输入 q 退出配置: ")
    if is_quit_command(raw):
        raise KeyboardInterrupt("已退出配置。")
    for remaining in range(CONFIGURE_OVERLAY_DELAY_SECONDS, 0, -1):
        print(f"{remaining} 秒后开始框选...")
        time.sleep(1)


def select_rect_with_overlay(title: str, hint: str) -> Rect:
    import tkinter as tk

    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.28)
    root.configure(bg="black")
    root.title(title)

    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    canvas = tk.Canvas(root, width=screen_w, height=screen_h, bg="black", highlightthickness=0)
    canvas.pack(fill=tk.BOTH, expand=True)
    canvas.create_text(
        screen_w // 2,
        42,
        text=f"{hint}；拖拽框选，松开鼠标确认；Esc 或右键取消",
        fill="white",
        font=("Microsoft YaHei UI", 18),
    )

    state: dict[str, Any] = {"start_x": 0, "start_y": 0, "rect_id": None, "rect": None}

    def on_down(event: tk.Event) -> None:
        state["start_x"] = int(event.x)
        state["start_y"] = int(event.y)
        if state["rect_id"] is not None:
            canvas.delete(state["rect_id"])
        state["rect_id"] = canvas.create_rectangle(
            event.x,
            event.y,
            event.x,
            event.y,
            outline="#2d7dff",
            width=2,
            fill="#ffffff",
            stipple="gray25",
        )

    def on_drag(event: tk.Event) -> None:
        if state["rect_id"] is not None:
            canvas.coords(state["rect_id"], state["start_x"], state["start_y"], event.x, event.y)

    def on_up(event: tk.Event) -> None:
        state["rect"] = ensure_positive_rect(
            Rect(state["start_x"], state["start_y"], int(event.x), int(event.y))
        )
        root.quit()

    def on_escape(_: tk.Event) -> None:
        state["rect"] = None
        root.quit()

    canvas.bind("<ButtonPress-1>", on_down)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_up)
    canvas.bind("<Button-3>", on_escape)
    root.bind("<Escape>", on_escape)
    root.mainloop()
    root.destroy()

    if state["rect"] is None:
        raise KeyboardInterrupt("已取消框选。")
    return state["rect"]


def write_preview_image(name: str, rect: Rect) -> str:
    preview_dir = BASE_DIR / "config_previews"
    preview_dir.mkdir(parents=True, exist_ok=True)
    path = preview_dir / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    screenshot_rect(rect).save(path)
    return str(path)


def select_config_rect(step_name: str, title: str, hint: str) -> Rect:
    wait_before_config_overlay(step_name)
    return select_rect_with_overlay(title, hint)


def action_layout_window() -> None:
    ok = layout_ths_window(
        title_keyword="同花顺",
        height_ratio=0.8,
        use_window_monitor=False,
        dry_run=False,
    )
    if not ok:
        raise RuntimeError("调整同花顺窗口失败。")


def action_configure() -> None:
    existing = load_json(CONFIG_PATH) if CONFIG_PATH.exists() else {}
    print("\n配置过程中可输入 q 退出；框选时可按 Esc 或右键取消，不会写入半成品 config.json。")
    print("\n第 1 个区域：左侧股票列表区域。")
    stock_region = select_config_rect("第 1 个区域", "配置股票列表区域", "框选左侧股票列表区域")
    print("\n第 2 个区域：主力比例尺文字区域。")
    scale_region = select_config_rect("第 2 个区域", "配置主力比例尺区域", "框选主力比例尺文字区域")
    print("\n第 3 个区域：双向柱状图区域。")
    bar_region = select_config_rect("第 3 个区域", "配置双向柱状图区域", "框选双向柱状图区域")

    rows_per_screen = prompt_int("这一屏显示多少只股票（输入 q 退出）", int(existing.get("rows_per_screen", 18)), allow_quit=True)
    record_count = prompt_int("正常模式计划采集多少只股票（输入 q 退出）", int(existing.get("record_count", rows_per_screen)), allow_quit=True)
    latest_trade_date = prompt_text(
        "柱状图最右侧交易日（输入 q 退出）",
        str(existing.get("latest_trade_date", DEFAULT_LATEST_TRADE_DATE)),
        allow_quit=True,
    )
    settle_seconds = prompt_float(
        "点击股票后等待页面稳定秒数（输入 q 退出）",
        float(existing.get("settle_seconds", 0.8)),
        allow_quit=True,
    )
    scroll_settle_seconds = prompt_float(
        "按 Down 后等待秒数（输入 q 退出）",
        float(existing.get("navigation", {}).get("settle_seconds", 1.0)),
        allow_quit=True,
    )

    first_x, first_y = stock_region.row_rect(0, rows_per_screen).center()
    bottom_x, bottom_y = stock_region.row_rect(rows_per_screen - 1, rows_per_screen).center()
    config = {
        "version": 1,
        "created_at": now_iso(),
        "stock_list_region": stock_region.to_dict(),
        "scale_text_region": scale_region.to_dict(),
        "bar_chart_region": bar_region.to_dict(),
        "rows_per_screen": rows_per_screen,
        "record_count": record_count,
        "latest_trade_date": latest_trade_date,
        "settle_seconds": settle_seconds,
        "initial_click": {
            "x": first_x,
            "y": first_y,
            "enabled": True,
            "settle_seconds": settle_seconds,
        },
        "bottom_row_click": {
            "x": bottom_x,
            "y": bottom_y,
            "settle_seconds": settle_seconds,
        },
        "navigation": {
            "advance_mode": "down",
            "next_key": "down",
            "settle_seconds": scroll_settle_seconds,
            "key_interval": 0.2,
        },
        "ocr": {
            "stock_code_lang": "eng",
            "stock_code_psm": 6,
            "scale_lang": "chi_sim+eng",
            "scale_psm": 7,
            "scale_engine": "auto",
        },
        "paths": {
            "runs_dir": str(RUNS_DIR),
            "sqlite_path": str(DB_PATH),
        },
        "previews": {
            "stock_list_region": write_preview_image("stock_list_region", stock_region),
            "scale_text_region": write_preview_image("scale_text_region", scale_region),
            "bar_chart_region": write_preview_image("bar_chart_region", bar_region),
        },
    }
    save_json(CONFIG_PATH, config)
    print(f"\n已写入配置：{CONFIG_PATH}")


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"未找到配置文件：{CONFIG_PATH}；请先执行菜单 2。")
    return load_json(CONFIG_PATH)


def crop_row_from_screen(region: Rect, row_index: int, rows_per_screen: int) -> tuple[Rect, Image.Image]:
    row_rect = region.row_rect(row_index, rows_per_screen)
    return row_rect, screenshot_rect(row_rect)


def ocr_stock_code(image: Image.Image, config: dict[str, Any]) -> tuple[str | None, str]:
    ocr_config = config.get("ocr", {})
    lang = str(ocr_config.get("stock_code_lang", "eng"))
    psm = int(ocr_config.get("stock_code_psm", 6))
    raw_text = ocr_stock_code_image(image, lang=lang, psm=psm)
    return parse_stock_code(raw_text), normalize_stock_code_text(raw_text)


def ocr_scale_record(
    *,
    image_path: Path,
    image: Image.Image,
    rect: Rect,
    config: dict[str, Any],
) -> dict[str, Any]:
    ocr_config = config.get("ocr", {})
    engine, text = ocr_scale_image(
        image,
        lang=str(ocr_config.get("scale_lang", "chi_sim+eng")),
        psm=int(ocr_config.get("scale_psm", 7)),
        engine=str(ocr_config.get("scale_engine", "auto")),
    )
    return build_scale_record(
        image_path=image_path,
        image=image,
        rect=rect,
        raw_text=text,
        ocr_engine=engine,
        trade_date=str(config.get("latest_trade_date", DEFAULT_LATEST_TRADE_DATE)),
    )


def click_point(x: int, y: int, settle_seconds: float) -> None:
    pyautogui.click(x=x, y=y)
    time.sleep(settle_seconds)


def press_down(config: dict[str, Any]) -> None:
    nav = config.get("navigation", {})
    pyautogui.press(str(nav.get("next_key", "down")))
    time.sleep(float(nav.get("settle_seconds", 1.0)))


def build_run_dir() -> tuple[str, Path]:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_DIR / run_id
    (run_dir / "images" / "stock_codes").mkdir(parents=True, exist_ok=True)
    (run_dir / "images" / "scale").mkdir(parents=True, exist_ok=True)
    (run_dir / "images" / "bars").mkdir(parents=True, exist_ok=True)
    return run_id, run_dir


def save_run_payloads(
    run_dir: Path,
    run_id: str,
    config: dict[str, Any],
    stock_rows: list[dict[str, Any]],
    scale_rows: list[dict[str, Any]],
) -> None:
    payload_meta = {
        "version": 1,
        "run_id": run_id,
        "created_at": now_iso(),
        "config": str(CONFIG_PATH),
        "latest_trade_date": config.get("latest_trade_date", DEFAULT_LATEST_TRADE_DATE),
    }
    save_json(run_dir / "stock_codes.json", {**payload_meta, "data": stock_rows})
    save_json(run_dir / "scale_ocr.json", {**payload_meta, "data": scale_rows})


def collect_one_stock(
    *,
    run_dir: Path,
    row_index: int,
    stock_index: int,
    stock_region: Rect,
    scale_region: Rect,
    bar_region: Rect,
    rows_per_screen: int,
    config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    row_rect, row_image = crop_row_from_screen(stock_region, row_index, rows_per_screen)
    code, raw_text = ocr_stock_code(row_image, config)
    code_for_name = code or "unknown"

    row_image_path = run_dir / "images" / "stock_codes" / f"{stock_index:04d}_{code_for_name}.png"
    row_image.save(row_image_path)

    scale_image = screenshot_rect(scale_region)
    scale_image_path = run_dir / "images" / "scale" / f"{stock_index:04d}_{code_for_name}.png"
    scale_image.save(scale_image_path)

    bar_image = screenshot_rect(bar_region)
    bar_image_path = run_dir / "images" / "bars" / f"{stock_index:04d}_{code_for_name}.png"
    bar_image.save(bar_image_path)

    stock_record = {
        "index": stock_index,
        "row": row_index + 1,
        "code": code,
        "raw_text": raw_text,
        "stock_code_image": str(row_image_path),
        "bar_image": str(bar_image_path),
        "scale_image": str(scale_image_path),
        "rect": row_rect.to_dict(),
        "captured_at": now_iso(),
    }

    try:
        parsed_scale = ocr_scale_record(
            image_path=scale_image_path,
            image=scale_image,
            rect=scale_region,
            config=config,
        )
        scale_record = {
            "index": stock_index,
            "stock_code": code,
            "parse_ok": True,
            **parsed_scale,
        }
    except Exception as exc:
        scale_record = {
            "index": stock_index,
            "stock_code": code,
            "parse_ok": False,
            "date": str(config.get("latest_trade_date", DEFAULT_LATEST_TRADE_DATE)),
            "error": str(exc),
            "source": {
                "image": str(scale_image_path),
                "rect": scale_region.to_dict(),
                "captured_at": now_iso(),
            },
        }

    print(
        f"{stock_index:04d}. code={code or '未识别'} "
        f"scale={'OK' if scale_record.get('parse_ok') else 'FAIL'}"
    )
    return stock_record, scale_record


def action_collect(test_mode: bool) -> None:
    config = load_config()
    stock_region = rect_from_mapping(config["stock_list_region"])
    scale_region = rect_from_mapping(config["scale_text_region"])
    bar_region = rect_from_mapping(config["bar_chart_region"])
    rows_per_screen = int(config["rows_per_screen"])
    total = int(config["record_count"])
    if test_mode:
        total = min(TEST_LIMIT, total)

    run_id, run_dir = build_run_dir()
    print(f"\nrun_id={run_id}")
    print(f"输出目录：{run_dir}")
    if test_mode:
        print("TEST 模式：第 3 步只采集前 3 只。")

    click = config.get("initial_click", {})
    if click.get("enabled", True):
        click_point(
            int(click.get("x", stock_region.row_rect(0, rows_per_screen).center()[0])),
            int(click.get("y", stock_region.row_rect(0, rows_per_screen).center()[1])),
            float(click.get("settle_seconds", 0.8)),
        )

    stock_rows: list[dict[str, Any]] = []
    scale_rows: list[dict[str, Any]] = []

    first_screen_count = min(rows_per_screen, total)
    for row_index in range(first_screen_count):
        x, y = stock_region.row_rect(row_index, rows_per_screen).center()
        click_point(x, y, float(config.get("settle_seconds", 0.8)))
        stock_record, scale_record = collect_one_stock(
            run_dir=run_dir,
            row_index=row_index,
            stock_index=len(stock_rows) + 1,
            stock_region=stock_region,
            scale_region=scale_region,
            bar_region=bar_region,
            rows_per_screen=rows_per_screen,
            config=config,
        )
        stock_rows.append(stock_record)
        scale_rows.append(scale_record)
        save_run_payloads(run_dir, run_id, config, stock_rows, scale_rows)

    if len(stock_rows) < total:
        bottom_x, bottom_y = stock_region.row_rect(rows_per_screen - 1, rows_per_screen).center()
        click_point(bottom_x, bottom_y, float(config.get("settle_seconds", 0.8)))
        press_down(config)

    while len(stock_rows) < total:
        stock_record, scale_record = collect_one_stock(
            run_dir=run_dir,
            row_index=rows_per_screen - 1,
            stock_index=len(stock_rows) + 1,
            stock_region=stock_region,
            scale_region=scale_region,
            bar_region=bar_region,
            rows_per_screen=rows_per_screen,
            config=config,
        )
        stock_rows.append(stock_record)
        scale_rows.append(scale_record)
        save_run_payloads(run_dir, run_id, config, stock_rows, scale_rows)
        if len(stock_rows) < total:
            press_down(config)

    print(f"\n第 3 步完成，已采集 {len(stock_rows)} 只。")
    print(f"请检查：{run_dir / 'stock_codes.json'}")
    print(f"请检查：{run_dir / 'scale_ocr.json'}")


BAR_RED_COLORS = {
    (221, 9, 22),    # 浅红色
    (211, 65, 75),   # 过渡红色
    (176, 7, 17),    # 深红色
    (185, 37, 47),   # 顶部红色
}

BAR_GREEN_COLORS = {
    (19, 114, 0),    # 浅绿色
    (60, 131, 48),   # 过渡绿色
    (12, 76, 0),     # 深绿色
    (160, 186, 159), # 底部绿色
}

BAR_STRUCTURE_COLORS = {
    (221, 9, 22),  # 浅红色
    (176, 7, 17),  # 深红色
    (19, 114, 0),  # 浅绿色
    (12, 76, 0),   # 深绿色
}

ZERO_LINE_COLOR = (118, 115, 66)

CHART_BACKGROUND_COLORS = {
    (249, 251, 255),  # 背景色
    (210, 224, 244),  # 横线色
    ZERO_LINE_COLOR,  # 零轴线
}

EXPECTED_BAR_WIDTH = 5
EXPECTED_BAR_GAP = 2
BAR_WIDTH_TOLERANCE = 2
BAR_GAP_TOLERANCE = 1
MIN_BAR_WIDTH = max(2, EXPECTED_BAR_WIDTH - BAR_WIDTH_TOLERANCE)
MAX_BAR_WIDTH = EXPECTED_BAR_WIDTH + BAR_WIDTH_TOLERANCE
ZERO_AXIS_SCAN_RADIUS = 3


@dataclass(frozen=True)
class BarGeometry:
    width: int
    gap: int
    phase: int

    @property
    def step(self) -> int:
        return self.width + self.gap


def is_red(pixel: tuple[int, int, int]) -> bool:
    return pixel in BAR_RED_COLORS


def is_green(pixel: tuple[int, int, int]) -> bool:
    return pixel in BAR_GREEN_COLORS


def is_structure_bar_pixel(pixel: tuple[int, int, int]) -> bool:
    return pixel in BAR_STRUCTURE_COLORS


def is_background_or_line(pixel: tuple[int, int, int]) -> bool:
    return pixel in CHART_BACKGROUND_COLORS


def is_bar_body_pixel(pixel: tuple[int, int, int]) -> bool:
    return not is_background_or_line(pixel)


def group_contiguous(values: list[int]) -> list[list[int]]:
    groups: list[list[int]] = []
    for value in values:
        if not groups or value > groups[-1][-1] + 1:
            groups.append([value])
        else:
            groups[-1].append(value)
    return groups


def is_bar_marker_pixel(pixel: tuple[int, int, int]) -> bool:
    return is_red(pixel) or is_green(pixel)


def flatten_bar_columns(img: Image.Image, *, structure_only: bool = False) -> list[bool]:
    width, height = img.size
    column_has_bar: list[bool] = []
    for x in range(width):
        has_bar_pixel = False
        for y in range(height):
            pixel = img.getpixel((x, y))
            if (is_structure_bar_pixel(pixel) if structure_only else is_bar_marker_pixel(pixel)):
                has_bar_pixel = True
                break
        column_has_bar.append(has_bar_pixel)
    return column_has_bar


def groups_from_right(column_has_bar: list[bool]) -> list[list[int]]:
    groups_from_newest: list[list[int]] = []
    x = len(column_has_bar) - 1
    while x >= 0:
        while x >= 0 and not column_has_bar[x]:
            x -= 1
        if x < 0:
            break

        end = x
        while x >= 0 and column_has_bar[x]:
            x -= 1
        start = x + 1
        groups_from_newest.append(list(range(start, end + 1)))

    return list(reversed(groups_from_newest))


def group_gap(left_group: list[int], right_group: list[int]) -> int:
    return right_group[0] - left_group[-1] - 1


def is_expected_bar_width(width: int) -> bool:
    return MIN_BAR_WIDTH <= width <= MAX_BAR_WIDTH


def is_expected_bar_gap(gap: int) -> bool:
    return EXPECTED_BAR_GAP - BAR_GAP_TOLERANCE <= gap <= EXPECTED_BAR_GAP + BAR_GAP_TOLERANCE


def discard_left_partial_bar(groups: list[list[int]]) -> list[list[int]]:
    if len(groups) < 2:
        return groups

    full_widths = [len(group) for group in groups if is_expected_bar_width(len(group))]
    if not full_widths:
        return groups

    typical_width = sorted(full_widths)[len(full_widths) // 2]
    first = groups[0]
    if first[0] == 0 and len(first) < typical_width * 0.75:
        return groups[1:]
    return groups


def clean_bar_groups(groups: list[list[int]]) -> list[list[int]]:
    groups = discard_left_partial_bar(groups)
    cleaned: list[list[int]] = []
    for group in groups:
        width = len(group)
        if width < MIN_BAR_WIDTH:
            continue
        if width <= MAX_BAR_WIDTH:
            cleaned.append(group)
            continue

        # A group wider than one bar usually means the 2px gap was polluted by
        # a stray marker pixel. Split it back into the observed 5px bar rhythm.
        start = group[0]
        while start <= group[-1]:
            end = min(start + EXPECTED_BAR_WIDTH - 1, group[-1])
            chunk = list(range(start, end + 1))
            if len(chunk) >= MIN_BAR_WIDTH:
                cleaned.append(chunk)
            start = end + EXPECTED_BAR_GAP + 1

    if len(cleaned) < 2:
        return cleaned

    validated: list[list[int]] = []
    for index, group in enumerate(cleaned):
        previous_gap_ok = index > 0 and is_expected_bar_gap(group_gap(cleaned[index - 1], group))
        next_gap_ok = index + 1 < len(cleaned) and is_expected_bar_gap(group_gap(group, cleaned[index + 1]))
        if previous_gap_ok or next_gap_ok or is_expected_bar_width(len(group)):
            validated.append(group)
    return validated


def median_int(values: list[int]) -> int:
    if not values:
        raise ValueError("median_int requires at least one value")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return round((ordered[middle - 1] + ordered[middle]) / 2)


def mode_int(values: list[int], default: int) -> int:
    if not values:
        return default
    counts = Counter(values)
    max_count = max(counts.values())
    modes = sorted(value for value, count in counts.items() if count == max_count)
    return modes[len(modes) // 2]


def infer_bar_geometry(groups: list[list[int]], image_width: int) -> BarGeometry:
    widths = [len(group) for group in groups if 1 <= len(group) <= EXPECTED_BAR_WIDTH * 3]
    width = max(1, mode_int(widths, EXPECTED_BAR_WIDTH))

    gaps = [
        group_gap(left_group, right_group)
        for left_group, right_group in zip(groups, groups[1:])
        if 1 <= group_gap(left_group, right_group) <= EXPECTED_BAR_WIDTH * 4
    ]
    gap = max(1, mode_int(gaps, EXPECTED_BAR_GAP))
    step = max(1, width + gap)

    phase_candidates = [
        group[0] % step
        for group in groups
        if max(1, width - BAR_WIDTH_TOLERANCE) <= len(group) <= width + BAR_WIDTH_TOLERANCE
    ]
    if not phase_candidates:
        phase_candidates = [group[0] % step for group in groups]
    phase = mode_int(phase_candidates, 0)
    if phase + width > image_width and image_width >= width:
        phase = max(0, image_width - width)
    return BarGeometry(width=width, gap=gap, phase=phase)


def planned_bar_groups(image_width: int, geometry: BarGeometry) -> list[list[int]]:
    groups: list[list[int]] = []
    x = geometry.phase
    while x < image_width:
        end = min(x + geometry.width, image_width)
        if end > x:
            groups.append(list(range(x, end)))
        x += geometry.step
    return groups


def row_has_bar_body(img: Image.Image, columns: list[int], y: int) -> bool:
    if y < 0 or y >= img.height:
        return False
    return any(is_bar_body_pixel(img.getpixel((x, y))) for x in columns if 0 <= x < img.width)


def bar_group_has_known_color(img: Image.Image, columns: list[int]) -> bool:
    for x in columns:
        for y in range(img.height):
            if is_bar_marker_pixel(img.getpixel((x, y))):
                return True
    return False


def bar_group_has_zero_axis_body(img: Image.Image, columns: list[int], zero_y: int) -> bool:
    start_y = max(0, zero_y - ZERO_AXIS_SCAN_RADIUS)
    end_y = min(img.height - 1, zero_y + ZERO_AXIS_SCAN_RADIUS)
    for y in range(start_y, end_y + 1):
        if row_has_bar_body(img, columns, y):
            return True
    return False


def is_planned_bar_present(img: Image.Image, columns: list[int], zero_y: int) -> bool:
    return bar_group_has_known_color(img, columns) or bar_group_has_zero_axis_body(img, columns, zero_y)


def scan_bar_height(img: Image.Image, columns: list[int], zero_y: int, direction: int) -> int:
    y = zero_y - 1 if direction < 0 else zero_y
    leading_empty_rows = 0
    height = 0
    while 0 <= y < img.height:
        if row_has_bar_body(img, columns, y):
            height += 1
            leading_empty_rows = 0
        elif height:
            break
        else:
            leading_empty_rows += 1
            if leading_empty_rows > ZERO_AXIS_SCAN_RADIUS:
                break
        y += direction
    return height


def detect_zero_y_from_line(img: Image.Image) -> int | None:
    width, height = img.size
    best_score = 0
    best_y = 0
    for y in range(height):
        score = 0
        for x in range(width):
            if img.getpixel((x, y)) == ZERO_LINE_COLOR:
                score += 1
        if score > best_score:
            best_score = score
            best_y = y
    if best_score >= max(8, width // 12):
        return best_y
    return None


def detect_zero_y_from_bar_groups(img: Image.Image, bar_groups: list[list[int]]) -> int:
    height = img.height
    candidates: list[int] = []
    red_bottoms: list[int] = []
    green_tops: list[int] = []

    for columns in bar_groups:
        red_ys: list[int] = []
        green_ys: list[int] = []
        for x in columns:
            for y in range(height):
                pixel = img.getpixel((x, y))
                if is_red(pixel):
                    red_ys.append(y)
                elif is_green(pixel):
                    green_ys.append(y)

        if red_ys and green_ys:
            red_bottom = max(red_ys)
            green_top = min(green_ys)
            if red_bottom < green_top:
                candidates.append(red_bottom + 1)
        elif red_ys:
            red_bottoms.append(max(red_ys))
        elif green_ys:
            green_tops.append(min(green_ys))

    if candidates:
        return median_int(candidates)
    if red_bottoms:
        return min(height - 1, median_int(red_bottoms) + 1)
    if green_tops:
        return median_int(green_tops)
    return height // 2


def extract_bars_from_image(image_path: Path) -> tuple[int, list[dict[str, Any]]]:
    img = Image.open(image_path).convert("RGB")
    structure_groups = groups_from_right(flatten_bar_columns(img, structure_only=True))
    marker_groups = clean_bar_groups(groups_from_right(flatten_bar_columns(img)))
    geometry_source_groups = structure_groups or marker_groups
    geometry = infer_bar_geometry(geometry_source_groups, img.width)
    line_zero_y = detect_zero_y_from_line(img)
    zero_y = line_zero_y if line_zero_y is not None else detect_zero_y_from_bar_groups(img, marker_groups or structure_groups)
    bar_groups = [
        columns
        for columns in planned_bar_groups(img.width, geometry)
        if is_planned_bar_present(img, columns, zero_y)
    ]
    bars: list[dict[str, Any]] = []
    for index, columns in enumerate(bar_groups):
        red_height = scan_bar_height(img, columns, zero_y, direction=-1)
        green_height = scan_bar_height(img, columns, zero_y, direction=1)
        if red_height == 0 and green_height == 0:
            continue
        bars.append(
            {
                "bar_index_from_left": index,
                "bar_index_from_right": len(bar_groups) - index - 1,
                "x_start": columns[0],
                "x_end": columns[-1],
                "red_height_px": red_height,
                "green_height_px": green_height,
            }
        )
    return zero_y, bars


def latest_run_dir() -> Path:
    if not RUNS_DIR.exists():
        raise FileNotFoundError("还没有 runs 目录，请先执行菜单 3。")
    candidates = [path for path in RUNS_DIR.iterdir() if path.is_dir()]
    if not candidates:
        raise FileNotFoundError("还没有采集 run，请先执行菜单 3。")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def choose_run_dir() -> Path:
    default = latest_run_dir()
    raw = input(f"请输入 run 目录，直接回车使用最新：{default}: ").strip()
    run_dir = Path(raw) if raw else default
    if not run_dir.exists():
        raise FileNotFoundError(f"run 目录不存在：{run_dir}")
    return run_dir


def payload_data(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    if isinstance(payload, list):
        return payload
    raise ValueError("JSON 结构必须是数组，或包含 data 数组的对象。")


def parse_date(value: str) -> date:
    text = value.strip()
    for fmt in (DATE_FMT, "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"invalid date: {value!r}, use YYYY-MM-DD or YYYYMMDD")


def iter_trade_date_json_paths() -> list[Path]:
    search_roots = [BASE_DIR, STEP2_DIR]
    paths: dict[Path, None] = {}
    for root in search_roots:
        if not root.exists():
            continue
        for path in root.glob("china_trade_dates_*.json"):
            paths[path.resolve()] = None
    return sorted(paths, key=lambda item: item.stat().st_mtime, reverse=True)


def load_trade_dates(latest_trade_date: str, count: int) -> list[str]:
    if count <= 0:
        return []

    for path in iter_trade_date_json_paths():
        try:
            payload = load_json(path)
        except Exception:
            continue
        values = payload.get("trade_dates") if isinstance(payload, dict) else None
        if not isinstance(values, list) or latest_trade_date not in values:
            continue
        latest_index = values.index(latest_trade_date)
        start = latest_index - count + 1
        if start >= 0:
            return [str(item) for item in values[start : latest_index + 1]]

    return generate_trade_dates(latest_trade_date, count)


def get_china_trade_dates(start_date: date, end_date: date) -> list[str]:
    if start_date > end_date:
        raise ValueError("start_date must be earlier than or equal to end_date")
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError("缺少 akshare，且本地交易日历 JSON 不足；请安装 akshare 或保留 china_trade_dates_*.json。") from exc

    calendar = ak.tool_trade_date_hist_sina()
    dates = [parse_date(str(item)) for item in calendar["trade_date"].tolist()]
    return [day.strftime(DATE_FMT) for day in dates if start_date <= day <= end_date]


def build_trade_date_payload(start_date: date, end_date: date) -> dict[str, Any]:
    trade_dates = get_china_trade_dates(start_date, end_date)
    return {
        "meta": {
            "market": "CN_A_SHARE",
            "source": "akshare.tool_trade_date_hist_sina",
            "start_date": start_date.strftime(DATE_FMT),
            "end_date": end_date.strftime(DATE_FMT),
            "trade_days": len(trade_dates),
        },
        "trade_dates": trade_dates,
    }


def default_trade_dates_output_path(start_date: date, end_date: date) -> Path:
    return BASE_DIR / f"china_trade_dates_{start_date:%Y%m%d}_{end_date:%Y%m%d}.json"


def generate_trade_dates(latest_trade_date: str, count: int) -> list[str]:
    latest = parse_date(latest_trade_date)
    span_days = max(count * 2 + 30, 365)
    last_error: Exception | None = None
    for _ in range(4):
        start = latest - timedelta(days=span_days)
        try:
            payload = build_trade_date_payload(start, latest)
        except Exception as exc:
            last_error = exc
            span_days *= 2
            continue

        values = payload.get("trade_dates") if isinstance(payload, dict) else None
        if isinstance(values, list) and latest_trade_date in values:
            latest_index = values.index(latest_trade_date)
            start_index = latest_index - count + 1
            if start_index >= 0:
                output_path = default_trade_dates_output_path(start, latest)
                save_json(output_path, payload)
                return [str(item) for item in values[start_index : latest_index + 1]]
        span_days *= 2

    message = f"无法生成足够的交易日历：latest={latest_trade_date}, count={count}"
    if last_error is not None:
        message = f"{message}；最后一次错误：{last_error}"
    raise RuntimeError(message)


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ths_fund_flow (
            stock_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            institution_buy_wan_shou REAL,
            institution_sell_wan_shou REAL,
            net_inflow_wan_shou REAL,
            turnover_ratio_percent REAL,
            source_run_id TEXT,
            source_bar_image TEXT,
            estimated INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (stock_code, trade_date)
        )
        """
    )
    return conn


def upsert_record(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO ths_fund_flow (
            stock_code,
            trade_date,
            institution_buy_wan_shou,
            institution_sell_wan_shou,
            net_inflow_wan_shou,
            turnover_ratio_percent,
            source_run_id,
            source_bar_image,
            estimated,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(stock_code, trade_date) DO UPDATE SET
            institution_buy_wan_shou=excluded.institution_buy_wan_shou,
            institution_sell_wan_shou=excluded.institution_sell_wan_shou,
            net_inflow_wan_shou=excluded.net_inflow_wan_shou,
            turnover_ratio_percent=excluded.turnover_ratio_percent,
            source_run_id=excluded.source_run_id,
            source_bar_image=excluded.source_bar_image,
            estimated=excluded.estimated,
            updated_at=excluded.updated_at
        """,
        (
            record["stock_code"],
            record["trade_date"],
            record["institution_buy_wan_shou"],
            record["institution_sell_wan_shou"],
            record["net_inflow_wan_shou"],
            record["turnover_ratio_percent"],
            record["source_run_id"],
            record["source_bar_image"],
            int(record["estimated"]),
            record["updated_at"],
        ),
    )


def delete_stock_run_rows(conn: sqlite3.Connection, *, run_id: str, stock_code: str) -> None:
    conn.execute(
        "DELETE FROM ths_fund_flow WHERE source_run_id = ? AND stock_code = ?",
        (run_id, stock_code),
    )


def scale_by_latest_bar(scale_record: dict[str, Any], latest_bar: dict[str, Any]) -> tuple[float, float]:
    buy = float(scale_record["institution_buy_wan_shou"])
    sell = float(scale_record["institution_sell_wan_shou"])
    red_height = float(latest_bar["red_height_px"])
    green_height = float(latest_bar["green_height_px"])
    if buy != 0 and red_height <= 0:
        raise ValueError("最新柱子的红柱高度为 0，无法拟合买入比例。")
    if sell != 0 and green_height <= 0:
        raise ValueError("最新柱子的绿柱高度为 0，无法拟合卖出比例。")
    buy_scale = buy / red_height if red_height else 0.0
    sell_scale = sell / green_height if green_height else 0.0
    return buy_scale, sell_scale


def build_db_rows_for_stock(
    *,
    run_id: str,
    stock_record: dict[str, Any],
    scale_record: dict[str, Any],
    latest_trade_date: str,
) -> list[dict[str, Any]]:
    stock_code = stock_record.get("code") or scale_record.get("stock_code")
    if not stock_code:
        raise ValueError(f"第 {stock_record.get('index')} 条没有股票代码。")
    if not scale_record.get("parse_ok", True):
        raise ValueError(f"{stock_code} 的比例尺 OCR 未成功：{scale_record.get('error')}")

    bar_image = Path(str(stock_record["bar_image"]))
    zero_y, bars = extract_bars_from_image(bar_image)
    if not bars:
        raise ValueError(f"{stock_code} 未识别到柱状图：{bar_image}")

    dates = load_trade_dates(latest_trade_date, len(bars))
    buy_scale, sell_scale = scale_by_latest_bar(scale_record, bars[-1])
    rows: list[dict[str, Any]] = []

    for date_value, bar in zip(dates, bars):
        is_latest = date_value == latest_trade_date
        if is_latest:
            buy = round(float(scale_record["institution_buy_wan_shou"]), 2)
            sell = round(float(scale_record["institution_sell_wan_shou"]), 2)
            net = round(float(scale_record["net_inflow_wan_shou"]), 2)
            ratio = (
                round(float(scale_record["turnover_ratio_percent"]), 2)
                if scale_record.get("turnover_ratio_percent") is not None
                else None
            )
        else:
            buy = round(float(bar["red_height_px"]) * buy_scale, 2)
            sell = round(float(bar["green_height_px"]) * sell_scale, 2)
            net = round(buy - sell, 2)
            ratio = None

        rows.append(
            {
                "stock_code": str(stock_code),
                "trade_date": date_value,
                "institution_buy_wan_shou": buy,
                "institution_sell_wan_shou": sell,
                "net_inflow_wan_shou": net,
                "turnover_ratio_percent": ratio,
                "source_run_id": run_id,
                "source_bar_image": str(bar_image),
                "estimated": not is_latest,
                "updated_at": now_iso(),
                "zero_y": zero_y,
            }
        )
    return rows


def action_import(test_mode: bool) -> None:
    config = load_config()
    latest_trade_date = str(config.get("latest_trade_date", DEFAULT_LATEST_TRADE_DATE))
    run_dir = choose_run_dir()
    run_id = run_dir.name
    stock_rows = payload_data(load_json(run_dir / "stock_codes.json"))
    scale_rows = payload_data(load_json(run_dir / "scale_ocr.json"))
    scale_by_index = {int(row["index"]): row for row in scale_rows if "index" in row}

    if test_mode:
        print("TEST 模式：第 4 步只识别/入库前 3 只。")
        stock_rows = stock_rows[:TEST_LIMIT]

    conn = init_db(DB_PATH)
    inserted_rows = 0
    failed: list[str] = []
    try:
        for stock_record in stock_rows:
            index = int(stock_record["index"])
            scale_record = scale_by_index.get(index)
            if scale_record is None:
                failed.append(f"index={index}: 缺少比例尺 OCR 记录")
                continue
            try:
                db_rows = build_db_rows_for_stock(
                    run_id=run_id,
                    stock_record=stock_record,
                    scale_record=scale_record,
                    latest_trade_date=latest_trade_date,
                )
                delete_stock_run_rows(conn, run_id=run_id, stock_code=str(db_rows[0]["stock_code"]))
                for row in db_rows:
                    upsert_record(conn, row)
                inserted_rows += len(db_rows)
                print(f"{index:04d}. {stock_record.get('code')} 入库 {len(db_rows)} 条")
            except Exception as exc:
                failed.append(f"index={index} code={stock_record.get('code')}: {exc}")
        conn.commit()
    finally:
        conn.close()

    print(f"\n第 4 步完成，写入/更新 {inserted_rows} 条。")
    print(f"SQLite：{DB_PATH}")
    if failed:
        print("\n以下股票处理失败：")
        for item in failed:
            print(f"- {item}")


def print_menu(test_mode: bool) -> None:
    suffix = " TEST" if test_mode else ""
    print(f"\n同花顺主力数据采集{suffix}")
    print("1. 按默认配置调整同花顺窗口大小")
    print("2. 配置所有需要截图的区域，写入 config.json")
    print("3. 前半段采集：股票代码 + 主力比例尺 OCR + 柱状图截图")
    print("4. 后半段识别柱状图并入库 SQLite")
    print("0. 退出")


def run_menu(test_mode: bool) -> int:
    while True:
        print_menu(test_mode)
        try:
            choice = input("请选择: ").strip()
        except EOFError:
            print()
            return 0
        try:
            if choice == "1":
                action_layout_window()
            elif choice == "2":
                action_configure()
            elif choice == "3":
                action_collect(test_mode)
            elif choice == "4":
                action_import(test_mode)
            elif choice in {"0", "q", "Q", "exit"}:
                return 0
            else:
                print("请输入 1/2/3/4，或 0 退出。")
                continue
        except KeyboardInterrupt as exc:
            print(f"\n{exc or '已取消。'}")
        except Exception as exc:
            print(f"错误：{exc}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("mode", nargs="?", choices=["test"])
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        raise SystemExit("只支持一个可选参数：test")
    return args


def main(argv: list[str] | None = None) -> int:
    if sys.platform != "win32":
        print("该脚本面向 Windows 桌面截图/OCR 场景。")
        return 1
    pyautogui.PAUSE = 0.05
    args = parse_args(argv)
    return run_menu(test_mode=args.mode == "test")


if __name__ == "__main__":
    raise SystemExit(main())
