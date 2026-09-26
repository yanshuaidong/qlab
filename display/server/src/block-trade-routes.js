import { Router } from 'express'

function hasTable(db, table) {
  return Boolean(db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?").get(table))
}

export function createBlockTradeRouter() {
  const router = Router()
  router.use((req, res, next) => {
    if (!hasTable(req.db, 'block_trade')) return res.status(503).json({ error: '尚未入库大宗交易，请先运行 python collect/block_trade.py' })
    next()
  })
  router.get('/overview', (req, res) => {
    const rows = req.db.prepare(`SELECT trade_date, COUNT(*) AS count, COUNT(DISTINCT ts_code) AS stock_count
      FROM block_trade GROUP BY trade_date ORDER BY trade_date`).all()
    const summary = req.db.prepare(`SELECT COUNT(*) AS count, COUNT(DISTINCT ts_code) AS stock_count,
      COUNT(DISTINCT trade_date) AS day_count, MIN(trade_date) AS start_date, MAX(trade_date) AS end_date FROM block_trade`).get()
    res.json({ rows, summary })
  })
  router.get('/stocks', (req, res) => {
    const q = req.query.q ?? ''
    if (typeof q !== 'string' || q.length > 100) return res.status(400).json({ error: 'q 必须是长度不超过 100 的字符串' })
    const nameSql = hasTable(req.db, 'moneyflow_dc')
      ? `(SELECT m.name FROM moneyflow_dc m WHERE m.ts_code=b.ts_code AND m.name IS NOT NULL AND TRIM(m.name)<>'' ORDER BY m.trade_date DESC LIMIT 1)`
      : 'NULL'
    const items = req.db.prepare(`SELECT b.*, ${nameSql} AS name FROM
      (SELECT ts_code,COUNT(*) AS count,MAX(trade_date) AS last_date FROM block_trade GROUP BY ts_code) b
      ORDER BY b.ts_code`).all()
    const search = q.trim().toLowerCase()
    res.json({ items: search ? items.filter(row => `${row.ts_code} ${row.name || ''}`.toLowerCase().includes(search)) : items })
  })
  router.get('/stock/:tsCode', (req, res) => {
    const tsCode = req.params.tsCode.trim().toUpperCase()
    if (!/^\d{6}\.(SH|SZ|BJ)$/.test(tsCode)) return res.status(400).json({ error: '无效的证券代码，应为 000001.SZ 等格式' })
    if (!req.db.prepare('SELECT 1 FROM block_trade WHERE ts_code=? LIMIT 1').get(tsCode)) {
      return res.status(404).json({ error: '该证券没有已入库的大宗交易记录' })
    }
    const hasDaily = hasTable(req.db, 'daily')
    const rows = req.db.prepare(hasDaily ? `SELECT b.*, d.close,
      CASE WHEN d.close>0 AND b.price IS NOT NULL THEN (b.price/d.close-1)*100.0 ELSE NULL END AS premium_rate
      FROM block_trade b LEFT JOIN daily d ON d.ts_code=b.ts_code AND d.trade_date=b.trade_date
      WHERE b.ts_code=? ORDER BY b.trade_date,b.record_no`
      : `SELECT *,NULL AS close,NULL AS premium_rate FROM block_trade WHERE ts_code=? ORDER BY trade_date,record_no`).all(tsCode)
    const daily = hasDaily ? req.db.prepare(`SELECT trade_date,open,high,low,close,pct_chg,vol,amount FROM daily
      WHERE ts_code=? ORDER BY trade_date`).all(tsCode) : []
    res.json({ tsCode, rows, daily })
  })
  return router
}
