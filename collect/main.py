import akshare as ak
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "tempstock.sqlite"
TABLE_NAME = "stock_individual_fund_flow_rank"


def main():
    df = ak.stock_individual_fund_flow_rank(indicator="今日")

    conn = sqlite3.connect(str(DB_PATH))
    df.to_sql(TABLE_NAME, conn, if_exists="replace", index=False)
    conn.close()

    print(f"写入成功：{DB_PATH} 表 {TABLE_NAME}，共 {len(df)} 条记录")


if __name__ == "__main__":
    main()