"""
开发用：本地读取 stock.sqlite，提供单页 K 线与 JSON API。
启动：在仓库根目录或本目录执行
  uvicorn display.stock_capital_flow.app:app --reload
若在本目录：
  uvicorn app:app --reload
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "storage" / "stock" / "stock_capital_flow" / "stock.sqlite"

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="stock_capital_flow 本地查看", version="0.1.0")


def get_conn() -> sqlite3.Connection:
    if not DB_PATH.is_file():
        raise HTTPException(
            status_code=500,
            detail=f"未找到数据库文件: {DB_PATH}",
        )
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


class StockRow(BaseModel):
    exchange: str
    stock_code: str
    name: str
    board: str | None = None
    limit_up_pct_change: float | None = None
    limit_up_count_120: int | None = None


class LimitUpDateRow(BaseModel):
    trade_date: str
    count: int


class KlineBar(BaseModel):
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float | None = None
    amplitude: float | None = None
    pct_change: float | None = None
    change_amount: float | None = None
    turnover_rate: float | None = None
    super_large_net_inflow_amount: float | None = None
    super_large_net_inflow_ratio: float | None = None
    large_net_inflow_amount: float | None = None
    large_net_inflow_ratio: float | None = None
    medium_net_inflow_amount: float | None = None
    medium_net_inflow_ratio: float | None = None
    small_net_inflow_amount: float | None = None
    small_net_inflow_ratio: float | None = None


def parse_hit_dates(hit_dates: str | None) -> list[tuple[str, float | None]]:
    out: list[tuple[str, float | None]] = []
    if not hit_dates:
        return out
    for part in hit_dates.split(","):
        raw = part.strip()
        if not raw:
            continue
        date_text, _, pct_text = raw.partition(":")
        date_text = date_text.strip()
        if not date_text:
            continue
        try:
            pct_change = float(pct_text) if pct_text.strip() else None
        except ValueError:
            pct_change = None
        out.append((date_text, pct_change))
    return out


@app.get("/api/stocks")
def api_stocks(
    q: str | None = Query(None, description="按代码或名称模糊筛选"),
    limit: int = Query(300, ge=1, le=2000),
) -> list[StockRow]:
    conn = get_conn()
    try:
        if q and q.strip():
            pat = f"%{q.strip()}%"
            cur = conn.execute(
                """
                SELECT exchange, code AS stock_code, name
                FROM stock_basic_info
                WHERE code LIKE ? OR name LIKE ?
                ORDER BY code
                LIMIT ?
                """,
                (pat, pat, limit),
            )
        else:
            cur = conn.execute(
                """
                SELECT exchange, code AS stock_code, name
                FROM stock_basic_info
                ORDER BY code
                LIMIT ?
                """,
                (limit,),
            )
        rows = cur.fetchall()
        return [StockRow.model_validate(dict(r)) for r in rows]
    finally:
        conn.close()


@app.get("/api/limit-up/dates")
def api_limit_up_dates(
    limit: int = Query(30, ge=1, le=120, description="返回最近 N 个有命中的日期"),
) -> list[LimitUpDateRow]:
    conn = get_conn()
    try:
        cur = conn.execute(
            """
            SELECT hit_dates
            FROM stock_limit_up_candidates_120
            WHERE hit_dates IS NOT NULL AND hit_dates <> ''
            """
        )
        counts: dict[str, int] = {}
        for r in cur.fetchall():
            seen_in_row: set[str] = set()
            for trade_date, _ in parse_hit_dates(r["hit_dates"]):
                if trade_date in seen_in_row:
                    continue
                counts[trade_date] = counts.get(trade_date, 0) + 1
                seen_in_row.add(trade_date)
        rows = [
            LimitUpDateRow(trade_date=trade_date, count=count)
            for trade_date, count in sorted(counts.items(), reverse=True)[:limit]
        ]
        return rows
    finally:
        conn.close()


@app.get("/api/limit-up/stocks")
def api_limit_up_stocks(
    trade_date: str = Query(..., description="涨停候选命中日期，格式 YYYY-MM-DD"),
) -> list[StockRow]:
    conn = get_conn()
    try:
        cur = conn.execute(
            """
            SELECT
                exchange,
                code AS stock_code,
                name,
                board,
                limit_up_count_120,
                hit_dates
            FROM stock_limit_up_candidates_120
            WHERE hit_dates LIKE ?
            ORDER BY code
            """,
            (f"%{trade_date}:%",),
        )
        stocks: list[StockRow] = []
        for r in cur.fetchall():
            pct_change = None
            for hit_date, hit_pct_change in parse_hit_dates(r["hit_dates"]):
                if hit_date == trade_date:
                    pct_change = hit_pct_change
                    break
            if pct_change is None and f"{trade_date}:" not in (r["hit_dates"] or ""):
                continue
            stocks.append(
                StockRow(
                    exchange=str(r["exchange"]),
                    stock_code=str(r["stock_code"]),
                    name=str(r["name"]),
                    board=str(r["board"]) if r["board"] is not None else None,
                    limit_up_pct_change=pct_change,
                    limit_up_count_120=(
                        int(r["limit_up_count_120"])
                        if r["limit_up_count_120"] is not None
                        else None
                    ),
                )
            )
        stocks.sort(
            key=lambda s: (
                -(s.limit_up_pct_change or 0),
                s.stock_code,
            )
        )
        return stocks
    finally:
        conn.close()


@app.get("/api/kline")
def api_kline(
    exchange: str = Query(..., description="交易所标识"),
    stock_code: str = Query(..., description="证券代码"),
    adjust: str = Query("", description="复权类型，当前库多为空字符串"),
) -> list[KlineBar]:
    conn = get_conn()
    try:
        cur = conn.execute(
            """
            SELECT
                d.trade_date,
                d.open,
                d.high,
                d.low,
                d.close,
                d.volume,
                d.amount,
                d.amplitude,
                d.pct_change,
                d.change_amount,
                d.turnover_rate,
                f.super_large_net_inflow_amount,
                f.super_large_net_inflow_ratio,
                f.large_net_inflow_amount,
                f.large_net_inflow_ratio,
                f.medium_net_inflow_amount,
                f.medium_net_inflow_ratio,
                f.small_net_inflow_amount,
                f.small_net_inflow_ratio
            FROM stock_daily AS d
            LEFT JOIN stock_individual_fund_flow AS f
                ON f.exchange = d.exchange
                AND f.code = d.stock_code
                AND f.trade_date = d.trade_date
            WHERE d.exchange = ? AND d.stock_code = ? AND d.adjust = ?
            ORDER BY d.trade_date ASC
            """,
            (exchange, stock_code, adjust),
        )
        bars = cur.fetchall()
        if not bars:
            raise HTTPException(
                status_code=404,
                detail="无日线数据：请检查 exchange / stock_code / adjust 是否与库内一致",
            )
        out: list[KlineBar] = []
        for r in bars:
            out.append(
                KlineBar(
                    trade_date=str(r["trade_date"]),
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                    volume=int(r["volume"] or 0),
                    amount=float(r["amount"]) if r["amount"] is not None else None,
                    amplitude=float(r["amplitude"]) if r["amplitude"] is not None else None,
                    pct_change=float(r["pct_change"]) if r["pct_change"] is not None else None,
                    change_amount=float(r["change_amount"]) if r["change_amount"] is not None else None,
                    turnover_rate=float(r["turnover_rate"]) if r["turnover_rate"] is not None else None,
                    super_large_net_inflow_amount=(
                        float(r["super_large_net_inflow_amount"])
                        if r["super_large_net_inflow_amount"] is not None
                        else None
                    ),
                    super_large_net_inflow_ratio=(
                        float(r["super_large_net_inflow_ratio"])
                        if r["super_large_net_inflow_ratio"] is not None
                        else None
                    ),
                    large_net_inflow_amount=(
                        float(r["large_net_inflow_amount"])
                        if r["large_net_inflow_amount"] is not None
                        else None
                    ),
                    large_net_inflow_ratio=(
                        float(r["large_net_inflow_ratio"])
                        if r["large_net_inflow_ratio"] is not None
                        else None
                    ),
                    medium_net_inflow_amount=(
                        float(r["medium_net_inflow_amount"])
                        if r["medium_net_inflow_amount"] is not None
                        else None
                    ),
                    medium_net_inflow_ratio=(
                        float(r["medium_net_inflow_ratio"])
                        if r["medium_net_inflow_ratio"] is not None
                        else None
                    ),
                    small_net_inflow_amount=(
                        float(r["small_net_inflow_amount"])
                        if r["small_net_inflow_amount"] is not None
                        else None
                    ),
                    small_net_inflow_ratio=(
                        float(r["small_net_inflow_ratio"])
                        if r["small_net_inflow_ratio"] is not None
                        else None
                    ),
                )
            )
        return out
    finally:
        conn.close()


@app.get("/")
def index() -> FileResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.is_file():
        raise HTTPException(status_code=500, detail=f"缺少静态页: {index_path}")
    return FileResponse(index_path, media_type="text/html; charset=utf-8")


app.mount(
    "/assets",
    StaticFiles(directory=str(STATIC_DIR)),
    name="assets",
)
