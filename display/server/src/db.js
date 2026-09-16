import fs from 'node:fs'
import path from 'node:path'
import { DatabaseSync } from 'node:sqlite'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
export const REPO_ROOT = path.resolve(__dirname, '../../..')

const REQUIRED_TABLES = [
  'daily',
  'moneyflow',
  'moneyflow_dc',
  'moneyflow_ths',
  'moneyflow_mkt_dc',
  'moneyflow_ind_dc',
  'moneyflow_ind_ths',
  'moneyflow_cnt_ths',
  'moneyflow_hsgt',
]

export function resolveDbPath() {
  const raw = process.env.STOCK_DB_PATH
  if (!raw) {
    return path.join(REPO_ROOT, 'storage', 'stock', 'data.sqlite')
  }
  return path.isAbsolute(raw) ? raw : path.resolve(REPO_ROOT, raw)
}

export function openDb() {
  const dbPath = resolveDbPath()
  if (!fs.existsSync(dbPath)) {
    throw new Error(
      `数据库不存在: ${dbPath}。可用环境变量 STOCK_DB_PATH 指定路径。`,
    )
  }

  const db = new DatabaseSync(dbPath)
  db.exec('PRAGMA journal_mode = WAL')
  db.exec('PRAGMA busy_timeout = 5000')

  const tables = db
    .prepare(`SELECT name FROM sqlite_master WHERE type = 'table'`)
    .all()
    .map((row) => row.name)
  const missing = REQUIRED_TABLES.filter((name) => !tables.includes(name))
  if (missing.length) {
    db.close()
    throw new Error(
      `缺少表: ${missing.join(', ')}。当前库: ${dbPath}。可用 STOCK_DB_PATH 指向完整库（README 默认 storage/stock/data.sqlite）。`,
    )
  }

  ensureTrendMark(db)

  return { db, dbPath }
}

const TREND_MARK_DDL = `
  CREATE TABLE trend_mark (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    mark_type TEXT NOT NULL CHECK (mark_type IN ('correct', 'fail')),
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (ts_code, trade_date)
  )
`

function ensureTrendMark(db) {
  const existing = db
    .prepare(
      `SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'trend_mark'`,
    )
    .get()
  if (!existing) {
    db.exec(TREND_MARK_DDL)
    return
  }

  const sql = existing.sql || ''
  const hasReason = /\breason\b/i.test(sql)
  const isNewTypes = sql.includes("'correct'") && sql.includes("'fail'")
  if (hasReason && isNewTypes) return

  const cols = db.prepare('PRAGMA table_info(trend_mark)').all()
  const colNames = new Set(cols.map((col) => col.name))
  const reasonExpr = colNames.has('reason') ? `COALESCE(reason, '')` : `''`

  db.exec('BEGIN')
  try {
    db.exec('DROP TABLE IF EXISTS trend_mark_new')
    db.exec(`
      CREATE TABLE trend_mark_new (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_code TEXT NOT NULL,
        trade_date TEXT NOT NULL,
        mark_type TEXT NOT NULL CHECK (mark_type IN ('correct', 'fail')),
        reason TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
        UNIQUE (ts_code, trade_date)
      )
    `)
    db.exec(`
      INSERT INTO trend_mark_new (id, ts_code, trade_date, mark_type, reason, created_at)
      SELECT id, ts_code, trade_date,
             CASE mark_type
               WHEN 'start' THEN 'correct'
               WHEN 'correct' THEN 'correct'
               WHEN 'fail' THEN 'fail'
             END,
             ${reasonExpr},
             created_at
      FROM trend_mark
      WHERE mark_type IN ('start', 'correct', 'fail')
    `)
    db.exec('DROP TABLE trend_mark')
    db.exec('ALTER TABLE trend_mark_new RENAME TO trend_mark')
    db.exec('COMMIT')
  } catch (err) {
    db.exec('ROLLBACK')
    throw err
  }
}
