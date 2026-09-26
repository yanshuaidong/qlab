import { Router } from 'express'

function hasTable(db, table) {
  return Boolean(db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?").get(table))
}

function parseMaxMvYi(value) {
  if (value == null || value === '') return { value: null }
  if (Array.isArray(value) || typeof value !== 'string' || value.trim() === '') {
    return { error: 'maxMvYi 必须是有限非负数字' }
  }
  const n = Number(value)
  if (!Number.isFinite(n) || n < 0) return { error: 'maxMvYi 必须是有限非负数字' }
  return { value: n }
}

function parseBound(value, name, { min = null } = {}) {
  if (value == null || value === '') return { value: null }
  if (Array.isArray(value) || typeof value !== 'string' || value.trim() === '') {
    return { error: `${name} 必须是有限数字` }
  }
  const n = Number(value)
  if (!Number.isFinite(n) || (min != null && n < min)) {
    return { error: `${name} 必须是有限${min != null ? '非负' : ''}数字` }
  }
  return { value: n }
}

function readTradeFilters(query) {
  const minAmount = parseBound(query.minAmountWan, 'minAmountWan', { min: 0 })
  if (minAmount.error) return minAmount
  const maxAmount = parseBound(query.maxAmountWan, 'maxAmountWan', { min: 0 })
  if (maxAmount.error) return maxAmount
  const minDiscount = parseBound(query.minDiscount, 'minDiscount')
  if (minDiscount.error) return minDiscount
  const maxDiscount = parseBound(query.maxDiscount, 'maxDiscount')
  if (maxDiscount.error) return maxDiscount
  if (minAmount.value != null && maxAmount.value != null && minAmount.value > maxAmount.value) {
    return { error: 'minAmountWan 不能大于 maxAmountWan' }
  }
  if (minDiscount.value != null && maxDiscount.value != null && minDiscount.value >= maxDiscount.value) {
    return { error: 'minDiscount 必须小于 maxDiscount' }
  }
  return {
    minAmountWan: minAmount.value,
    maxAmountWan: maxAmount.value,
    minDiscount: minDiscount.value,
    maxDiscount: maxDiscount.value,
  }
}

function tradeFilterSql(filters) {
  const clauses = []
  const params = []
  if (filters.minAmountWan != null) {
    clauses.push('b.amount >= ?')
    params.push(filters.minAmountWan)
  }
  if (filters.maxAmountWan != null) {
    clauses.push('b.amount <= ?')
    params.push(filters.maxAmountWan)
  }
  const needsDaily = filters.minDiscount != null || filters.maxDiscount != null
  if (needsDaily) {
    clauses.push('d.close > 0 AND b.price IS NOT NULL')
    // 与页面两位小数一致，避免二进制浮点把恰好 3%、8% 算进开区间。
    const discountSql = 'ROUND((1.0 - b.price / d.close) * 100.0, 2)'
    if (filters.minDiscount != null) {
      clauses.push(`${discountSql} > ?`)
      params.push(filters.minDiscount)
    }
    if (filters.maxDiscount != null) {
      clauses.push(`${discountSql} < ?`)
      params.push(filters.maxDiscount)
    }
  }
  return { clauses, params, needsDaily }
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
    const maxMv = parseMaxMvYi(req.query.maxMvYi)
    if (maxMv.error) return res.status(400).json({ error: maxMv.error })
    const filters = readTradeFilters(req.query)
    if (filters.error) return res.status(400).json({ error: filters.error })
    const hasMv = hasTable(req.db, 'daily_basic')
    const hasDaily = hasTable(req.db, 'daily')
    const trade = tradeFilterSql(filters)
    const nameSql = hasTable(req.db, 'moneyflow_dc')
      ? `(SELECT m.name FROM moneyflow_dc m WHERE m.ts_code=g.ts_code AND m.name IS NOT NULL AND TRIM(m.name)<>'' ORDER BY m.trade_date DESC LIMIT 1)`
      : 'NULL'
    // daily_basic.total_mv 单位为万元，1 亿 = 10000 万元。取该证券最新一条总市值。
    const mvSql = hasMv
      ? `(SELECT d.total_mv FROM daily_basic d WHERE d.ts_code=g.ts_code ORDER BY d.trade_date DESC LIMIT 1)`
      : 'NULL'
    const maxMvWan = maxMv.value != null && hasMv ? maxMv.value * 10000 : null
    const blocked = trade.needsDaily && !hasDaily
    const join = trade.needsDaily && hasDaily
      ? 'JOIN daily d ON d.ts_code=b.ts_code AND d.trade_date=b.trade_date'
      : ''
    const where = trade.clauses.length ? `WHERE ${trade.clauses.join(' AND ')}` : ''
    const sql = `SELECT * FROM (
        SELECT g.ts_code, g.count, g.last_date, ${nameSql} AS name, ${mvSql} AS total_mv
        FROM (
          SELECT b.ts_code, COUNT(*) AS count, MAX(b.trade_date) AS last_date
          FROM block_trade b ${join} ${where}
          GROUP BY b.ts_code
        ) g
      ) s
      ${maxMvWan == null ? '' : 'WHERE s.total_mv < ?'}
      ORDER BY s.ts_code`
    const params = blocked ? [] : [...trade.params, ...(maxMvWan == null ? [] : [maxMvWan])]
    const items = blocked ? [] : req.db.prepare(sql).all(...params)
    const search = q.trim().toLowerCase()
    res.json({
      items: search ? items.filter(row => `${row.ts_code} ${row.name || ''}`.toLowerCase().includes(search)) : items,
      unit: { total_mv: '万元', amount: '万元' },
      mv_available: hasMv,
    })
  })
  router.get('/stock/:tsCode', (req, res) => {
    const tsCode = req.params.tsCode.trim().toUpperCase()
    if (!/^\d{6}\.(SH|SZ|BJ)$/.test(tsCode)) return res.status(400).json({ error: '无效的证券代码，应为 000001.SZ 等格式' })
    if (!req.db.prepare('SELECT 1 FROM block_trade WHERE ts_code=? LIMIT 1').get(tsCode)) {
      return res.status(404).json({ error: '该证券没有已入库的大宗交易记录' })
    }
    const filters = readTradeFilters(req.query)
    if (filters.error) return res.status(400).json({ error: filters.error })
    const hasDaily = hasTable(req.db, 'daily')
    const trade = tradeFilterSql(filters)
    const blocked = trade.needsDaily && !hasDaily
    const where = ['b.ts_code=?', ...trade.clauses]
    const rows = blocked ? [] : req.db.prepare(hasDaily ? `SELECT b.*, d.close,
      CASE WHEN d.close>0 AND b.price IS NOT NULL THEN (b.price/d.close-1)*100.0 ELSE NULL END AS premium_rate
      FROM block_trade b LEFT JOIN daily d ON d.ts_code=b.ts_code AND d.trade_date=b.trade_date
      WHERE ${where.join(' AND ')} ORDER BY b.trade_date,b.record_no`
      : `SELECT *,NULL AS close,NULL AS premium_rate FROM block_trade b WHERE ${where.join(' AND ')} ORDER BY trade_date,record_no`).all(tsCode, ...trade.params)
    const daily = hasDaily ? req.db.prepare(`SELECT trade_date,open,high,low,close,pct_chg,vol,amount FROM daily
      WHERE ts_code=? ORDER BY trade_date`).all(tsCode) : []
    res.json({ tsCode, rows, daily })
  })
  return router
}
