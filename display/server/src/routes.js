import { Router } from 'express'
import { createBlockTradeRouter } from './block-trade-routes.js'
import { createReasonVectorRouter } from './reason-vector-routes.js'
import { VectorService } from './reason-vector-service.js'
import { isCalendarDate, readSignalAnalysis, readSignalStocks } from './signal-analysis.js'
import { readLimitAnalysis, readMainForceOutcomes, readMainForceWind } from './limit-analysis.js'

const MONEYFLOW_SOURCES = {
  dc: {
    table: 'moneyflow_dc',
    unit: '万元',
    sql: `SELECT trade_date, name, pct_change, close,
                 net_amount, net_amount_rate,
                 buy_elg_amount, buy_elg_amount_rate,
                 buy_lg_amount, buy_lg_amount_rate,
                 buy_md_amount, buy_md_amount_rate,
                 buy_sm_amount, buy_sm_amount_rate
          FROM moneyflow_dc
          WHERE ts_code = ?
          ORDER BY trade_date`,
  },
  ths: {
    table: 'moneyflow_ths',
    unit: '万元',
    sql: `SELECT trade_date, name, pct_change, latest AS close,
                 net_amount, net_d5_amount,
                 buy_lg_amount, buy_lg_amount_rate,
                 buy_md_amount, buy_md_amount_rate,
                 buy_sm_amount, buy_sm_amount_rate
          FROM moneyflow_ths
          WHERE ts_code = ?
          ORDER BY trade_date`,
  },
  l2: {
    table: 'moneyflow',
    unit: '万元',
    sql: `SELECT m.trade_date,
                 (COALESCE(m.buy_elg_amount, 0) - COALESCE(m.sell_elg_amount, 0)
                  + COALESCE(m.buy_lg_amount, 0) - COALESCE(m.sell_lg_amount, 0)) AS net_amount,
                 CASE
                   WHEN d.amount IS NULL OR d.amount = 0 THEN NULL
                   ELSE ROUND(
                     (COALESCE(m.buy_elg_amount, 0) - COALESCE(m.sell_elg_amount, 0)
                      + COALESCE(m.buy_lg_amount, 0) - COALESCE(m.sell_lg_amount, 0))
                     * 1000.0 / d.amount,
                     2
                   )
                 END AS net_amount_rate,
                 m.net_mf_vol,
                 m.net_mf_amount AS mf_net_amount,
                 m.net_mf_amount_rate AS mf_net_amount_rate,
                 (COALESCE(m.buy_elg_amount, 0) - COALESCE(m.sell_elg_amount, 0)) AS buy_elg_amount,
                 m.buy_elg_amount_rate,
                 (COALESCE(m.buy_lg_amount, 0) - COALESCE(m.sell_lg_amount, 0)) AS buy_lg_amount,
                 m.buy_lg_amount_rate,
                 (COALESCE(m.buy_md_amount, 0) - COALESCE(m.sell_md_amount, 0)) AS buy_md_amount,
                 m.buy_md_amount_rate,
                 (COALESCE(m.buy_sm_amount, 0) - COALESCE(m.sell_sm_amount, 0)) AS buy_sm_amount,
                 m.buy_sm_amount_rate
          FROM moneyflow AS m
          LEFT JOIN daily AS d
            ON d.ts_code = m.ts_code AND d.trade_date = m.trade_date
          WHERE m.ts_code = ?
          ORDER BY m.trade_date`,
  },
}

const SECTOR_SOURCES = {
  dc: {
    table: 'moneyflow_ind_dc',
    unit: '元',
    dateSql: `SELECT MAX(trade_date) AS trade_date FROM moneyflow_ind_dc`,
    listSql: `SELECT ts_code, name, content_type, pct_change, close,
                     net_amount, net_amount_rate, rank, buy_sm_amount_stock AS lead_stock
              FROM moneyflow_ind_dc
              WHERE trade_date = ? AND content_type = ?
              ORDER BY rank`,
    seriesSql: `SELECT trade_date, name, pct_change, close,
                       net_amount, net_amount_rate, rank, buy_sm_amount_stock AS lead_stock
                FROM moneyflow_ind_dc
                WHERE ts_code = ?
                ORDER BY trade_date`,
  },
  ths_ind: {
    table: 'moneyflow_ind_ths',
    unit: '亿元',
    dateSql: `SELECT MAX(trade_date) AS trade_date FROM moneyflow_ind_ths`,
    listSql: `SELECT ts_code, industry AS name, pct_change, close,
                     net_amount, net_buy_amount, net_sell_amount,
                     company_num, lead_stock, pct_change_stock, close_price
              FROM moneyflow_ind_ths
              WHERE trade_date = ?
              ORDER BY net_amount DESC`,
    seriesSql: `SELECT trade_date, industry AS name, pct_change, close,
                       net_amount, net_buy_amount, net_sell_amount,
                       company_num, lead_stock, pct_change_stock, close_price
                FROM moneyflow_ind_ths
                WHERE ts_code = ?
                ORDER BY trade_date`,
  },
  ths_cnt: {
    table: 'moneyflow_cnt_ths',
    unit: '亿元',
    dateSql: `SELECT MAX(trade_date) AS trade_date FROM moneyflow_cnt_ths`,
    listSql: `SELECT ts_code, name, pct_change, industry_index AS close,
                     net_amount, net_buy_amount, net_sell_amount,
                     company_num, lead_stock, pct_change_stock, close_price
              FROM moneyflow_cnt_ths
              WHERE trade_date = ?
              ORDER BY net_amount DESC`,
    seriesSql: `SELECT trade_date, name, pct_change, industry_index AS close,
                       net_amount, net_buy_amount, net_sell_amount,
                       company_num, lead_stock, pct_change_stock, close_price
                FROM moneyflow_cnt_ths
                WHERE ts_code = ?
                ORDER BY trade_date`,
  },
}

const STAT_TABLES = [
  ['daily', 'trade_date'],
  ['moneyflow', 'trade_date'],
  ['moneyflow_dc', 'trade_date'],
  ['moneyflow_ths', 'trade_date'],
  ['moneyflow_mkt_dc', 'trade_date'],
  ['moneyflow_ind_dc', 'trade_date'],
  ['moneyflow_ind_ths', 'trade_date'],
  ['moneyflow_cnt_ths', 'trade_date'],
  ['moneyflow_hsgt', 'trade_date'],
]

const MARK_TYPES = new Set(['correct', 'fail'])
const MARK_SELECT =
  'SELECT id, ts_code, trade_date, mark_type, reason, created_at FROM trend_mark'

function likePattern(q) {
  return `%${q.replace(/[%_]/g, '')}%`
}

function isTradeDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value)
}

function readHmQuery(query) {
  if (query.hm !== undefined && query.hm !== '0' && query.hm !== '1') {
    return { error: 'hm 必须是 0 或 1' }
  }
  if (query.hmName !== undefined && query.hmName !== '') {
    if (Array.isArray(query.hmName) || typeof query.hmName !== 'string') {
      return { error: 'hmName 必须是游资名称' }
    }
    const name = query.hmName.trim()
    if (name.length > 80) return { error: 'hmName 过长' }
    return { enabled: query.hm === '1', name }
  }
  return { enabled: query.hm === '1', name: '' }
}

function parseMvYi(value) {
  if (value === '' || value == null) return null
  const n = Number(value)
  if (!Number.isFinite(n) || n < 0) return null
  return n
}

function parseQueryNumber(value, name, fallback, min = null) {
  if (value === undefined) return fallback
  if (Array.isArray(value) || typeof value !== 'string' || value.trim() === '') {
    throw new RangeError(min == null ? `${name} 必须是有限数字` : `${name} 必须是有限非负数字`)
  }
  const n = Number(value)
  if (!Number.isFinite(n) || (min != null && n < min)) {
    throw new RangeError(min == null ? `${name} 必须是有限数字` : `${name} 必须是有限非负数字`)
  }
  return n
}

function parseMainForceQuery(query) {
  if (Array.isArray(query.endDate)) {
    throw new RangeError('endDate 必须是有效日期（YYYY-MM-DD），且不早于 0002-01-01')
  }
  if (Array.isArray(query.date)) {
    throw new RangeError('date 必须是有效日期（YYYY-MM-DD），且不早于 0002-01-01')
  }
  return {
    endDate: query.endDate,
    date: query.date,
    minMvYi: parseQueryNumber(query.minMvYi, 'minMvYi', 400, 0),
    dc: parseQuerySwitch(query.dc, 'dc'),
    dcRate: parseQueryNumber(query.dcRate, 'dcRate', 20),
    ths: parseQuerySwitch(query.ths, 'ths'),
    thsRate: parseQueryNumber(query.thsRate, 'thsRate', 20),
    l2: parseQuerySwitch(query.l2, 'l2'),
    l2Rate: parseQueryNumber(query.l2Rate, 'l2Rate', 20),
  }
}

function parseQuerySwitch(value, name) {
  if (value === undefined) return true
  if (value === '1') return true
  if (value === '0') return false
  throw new RangeError(`${name} 必须是 0 或 1`)
}

function hasTable(db, name) {
  return Boolean(
    db
      .prepare(
        `SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?`,
      )
      .get(name),
  )
}

function tableStats(db, table, dateCol) {
  return db
    .prepare(
      `SELECT COUNT(*) AS rows, MIN(${dateCol}) AS minDate, MAX(${dateCol}) AS maxDate FROM ${table}`,
    )
    .get()
}

export function createApiRouter(getDb, vectors = new VectorService()) {
  const router = Router()

  router.use((req, res, next) => {
    const ctx = getDb()
    if (ctx.error) {
      res.status(503).json({ error: ctx.error })
      return
    }
    req.db = ctx.db
    req.dbPath = ctx.dbPath
    next()
  })

  router.use('/block-trade', createBlockTradeRouter())
  router.use('/reason-vector', createReasonVectorRouter(vectors))

  router.get('/meta', (req, res) => {
    const tables = {}
    for (const [table, dateCol] of STAT_TABLES) {
      tables[table] = tableStats(req.db, table, dateCol)
    }

    const defaultStock =
      req.db
        .prepare(
          `SELECT ts_code, name FROM moneyflow_dc
           WHERE trade_date = (SELECT MAX(trade_date) FROM moneyflow_dc)
             AND ts_code = '600519.SH'`,
        )
        .get() ||
      req.db
        .prepare(
          `SELECT ts_code, name FROM moneyflow_dc
           WHERE trade_date = (SELECT MAX(trade_date) FROM moneyflow_dc)
           ORDER BY ts_code
           LIMIT 1`,
        )
        .get() ||
      null

    res.json({
      dbPath: req.dbPath,
      tables,
      defaultStock,
    })
  })

  router.get('/stocks', (req, res) => {
    const q = String(req.query.q || '').trim()
    const minMvYi = parseMvYi(req.query.minMvYi)
    const maxMvYi = parseMvYi(req.query.maxMvYi)
    const scope = String(req.query.scope || '').trim().toLowerCase()
    const hmQuery = readHmQuery(req.query)
    if (hmQuery.error) {
      res.status(400).json({ error: hmQuery.error })
      return
    }
    const hasDailyBasic = hasTable(req.db, 'daily_basic')
    const hasTrendMark = hasTable(req.db, 'trend_mark')
    const useMinMv = hasDailyBasic && minMvYi != null
    const useMaxMv = hasDailyBasic && maxMvYi != null
    const useSignal = scope === 'signal'
    const useHm = hmQuery.enabled || hmQuery.name !== ''
    if (useHm && !hasTable(req.db, 'hm_detail')) {
      res.json({ items: [] })
      return
    }
    if (useSignal && !hasTrendMark) {
      res.json({ items: [] })
      return
    }
    // daily_basic.total_mv 单位为万元，1 亿 = 10000 万元
    const minMvWan = useMinMv ? minMvYi * 10000 : null
    const maxMvWan = useMaxMv ? maxMvYi * 10000 : null
    const like = q ? likePattern(q) : null
    const searchSql = q ? 'AND (m.ts_code LIKE ? OR m.name LIKE ?)' : ''
    const limitSql = q ? 'LIMIT 50' : ''
    const mvJoin =
      useMinMv || useMaxMv
        ? `INNER JOIN daily_basic b
           ON b.ts_code = m.ts_code
          AND b.trade_date = (SELECT MAX(trade_date) FROM daily_basic)`
        : ''
    const mvSql = [
      useMinMv ? 'AND b.total_mv >= ?' : '',
      useMaxMv ? 'AND b.total_mv <= ?' : '',
    ]
      .filter(Boolean)
      .join('\n           ')
    const signalSql = useSignal
      ? `AND EXISTS (
           SELECT 1 FROM trend_mark t
           WHERE t.ts_code = m.ts_code
             AND t.mark_type IN ('correct', 'fail')
         )`
      : ''
    const hmSql = useHm
      ? `AND m.ts_code IN (
           SELECT ts_code FROM hm_detail
           ${hmQuery.name ? 'WHERE hm_name = ?' : ''}
         )`
      : ''

    const sql = `SELECT m.ts_code, m.name
       FROM moneyflow_dc m
       ${mvJoin}
       WHERE m.trade_date = (SELECT MAX(trade_date) FROM moneyflow_dc)
         ${mvSql}
         ${signalSql}
         ${hmSql}
         ${searchSql}
       ORDER BY m.ts_code
       ${limitSql}`
    const stmt = req.db.prepare(sql)
    const params = []
    if (useMinMv) params.push(minMvWan)
    if (useMaxMv) params.push(maxMvWan)
    if (useHm && hmQuery.name) params.push(hmQuery.name)
    if (q) params.push(like, like)
    const items = params.length ? stmt.all(...params) : stmt.all()
    res.json({ items })
  })

  router.get('/daily/:tsCode', (req, res) => {
    const tsCode = String(req.params.tsCode || '').trim()
    const rows = req.db
      .prepare(
        `SELECT trade_date, open, high, low, close, pre_close, change, pct_chg,
                vol, amount, ah_vol, ah_amount
         FROM daily
         WHERE ts_code = ?
         ORDER BY trade_date`,
      )
      .all(tsCode)
    res.json({
      tsCode,
      unit: { vol: '手', amount: '千元' },
      rows,
    })
  })

  router.get('/daily-basic/:tsCode', (req, res) => {
    const tsCode = String(req.params.tsCode || '').trim()
    if (!hasTable(req.db, 'daily_basic')) {
      res.json({ tsCode, item: null })
      return
    }
    const item =
      req.db
        .prepare(
          `SELECT ts_code, trade_date, total_mv, circ_mv, pe, pe_ttm, pb
           FROM daily_basic
           WHERE ts_code = ?
           ORDER BY trade_date DESC
           LIMIT 1`,
        )
        .get(tsCode) || null
    res.json({
      tsCode,
      unit: { total_mv: '万元', circ_mv: '万元' },
      item,
    })
  })

  router.get('/moneyflow/:tsCode', (req, res) => {
    const tsCode = String(req.params.tsCode || '').trim()
    const source = String(req.query.source || 'dc').toLowerCase()
    const spec = MONEYFLOW_SOURCES[source]
    if (!spec) {
      res.status(400).json({ error: 'source 必须是 dc、ths 或 l2' })
      return
    }
    const rows = req.db.prepare(spec.sql).all(tsCode)
    res.json({
      tsCode,
      source,
      unit: spec.unit,
      rows,
    })
  })

  router.get('/limit-analysis', (req, res, next) => {
    try {
      res.json(readLimitAnalysis(req.db, req.query.endDate))
    } catch (err) {
      if (err instanceof RangeError) return res.status(400).json({ error: err.message })
      next(err)
    }
  })

  router.get('/limit-analysis/main-force', (req, res, next) => {
    try {
      res.json(readMainForceWind(req.db, parseMainForceQuery(req.query)))
    } catch (err) {
      if (err instanceof RangeError) return res.status(400).json({ error: err.message })
      next(err)
    }
  })

  router.get('/limit-analysis/main-force/outcomes', (req, res, next) => {
    try {
      res.json(readMainForceOutcomes(req.db, parseMainForceQuery(req.query)))
    } catch (err) {
      if (err instanceof RangeError) return res.status(400).json({ error: err.message })
      next(err)
    }
  })

  router.get('/market-flow', (req, res) => {
    const rows = req.db
      .prepare(
        `SELECT trade_date, close_sh, pct_change_sh, close_sz, pct_change_sz,
                net_amount, net_amount_rate,
                buy_elg_amount, buy_elg_amount_rate,
                buy_lg_amount, buy_lg_amount_rate,
                buy_md_amount, buy_md_amount_rate,
                buy_sm_amount, buy_sm_amount_rate
         FROM moneyflow_mkt_dc
         ORDER BY trade_date`,
      )
      .all()
    res.json({
      unit: { flow: '元', index: '点' },
      rows,
    })
  })

  router.get('/sectors', (req, res) => {
    const source = String(req.query.source || 'dc').toLowerCase()
    const spec = SECTOR_SOURCES[source]
    if (!spec) {
      res.status(400).json({ error: 'source 必须是 dc、ths_ind 或 ths_cnt' })
      return
    }

    let date = String(req.query.date || '').trim()
    if (!date) {
      date = req.db.prepare(spec.dateSql).get()?.trade_date || ''
    }
    if (!date) {
      res.json({ source, date: null, unit: spec.unit, rows: [] })
      return
    }

    let rows
    if (source === 'dc') {
      const contentType = String(req.query.type || '行业').trim()
      rows = req.db.prepare(spec.listSql).all(date, contentType)
    } else {
      rows = req.db.prepare(spec.listSql).all(date)
    }

    res.json({
      source,
      date,
      unit: spec.unit,
      rows,
    })
  })

  router.get('/sector/:tsCode', (req, res) => {
    const tsCode = String(req.params.tsCode || '').trim()
    const source = String(req.query.source || 'dc').toLowerCase()
    const spec = SECTOR_SOURCES[source]
    if (!spec) {
      res.status(400).json({ error: 'source 必须是 dc、ths_ind 或 ths_cnt' })
      return
    }
    const rows = req.db.prepare(spec.seriesSql).all(tsCode)
    res.json({
      tsCode,
      source,
      unit: spec.unit,
      rows,
    })
  })

  const PHASE_TABLES = {
    adx: 'phase_adx',
    lr: 'phase_lr',
    hmm: 'phase_hmm',
  }

  router.get('/phases/:tsCode', (req, res) => {
    const tsCode = String(req.params.tsCode || '').trim()
    const payload = { tsCode, adx: [], lr: [], hmm: [] }
    for (const [key, table] of Object.entries(PHASE_TABLES)) {
      if (!hasTable(req.db, table)) continue
      payload[key] = req.db
        .prepare(
          `SELECT trade_date, phase FROM ${table}
           WHERE ts_code = ?
           ORDER BY trade_date`,
        )
        .all(tsCode)
    }
    res.json(payload)
  })

  router.get('/signal-analysis/signals', (req, res, next) => {
    try {
      res.json(readSignalStocks(req.db, req.query))
    } catch (err) {
      if (err instanceof RangeError) return res.status(400).json({ error: err.message })
      next(err)
    }
  })

  router.get('/signal-analysis', (req, res) => {
    const endDate = req.query.endDate
    if (endDate !== undefined && (!isCalendarDate(endDate) || endDate < '0002-01-01')) {
      res.status(400).json({ error: 'endDate 必须是有效日期（YYYY-MM-DD），且不早于 0002-01-01' })
      return
    }
    res.json(readSignalAnalysis(req.db, endDate))
  })

  router.get('/marks/:tsCode', (req, res) => {
    const tsCode = String(req.params.tsCode || '').trim()
    const items = req.db
      .prepare(
        `${MARK_SELECT}
         WHERE ts_code = ?
         ORDER BY trade_date, id`,
      )
      .all(tsCode)
    res.json({ tsCode, items })
  })

  router.post('/marks', (req, res) => {
    const tsCode = String(req.body?.ts_code || '').trim()
    const tradeDate = String(req.body?.trade_date || '').trim()
    const markType = String(req.body?.mark_type || '').trim()
    const reason = String(req.body?.reason || '').trim()
    if (!tsCode || !isTradeDate(tradeDate) || !MARK_TYPES.has(markType)) {
      res.status(400).json({
        error:
          '需要 ts_code、trade_date（YYYY-MM-DD）和 mark_type（correct/fail）',
      })
      return
    }

    req.db
      .prepare(
        `INSERT INTO trend_mark (ts_code, trade_date, mark_type, reason)
         VALUES (?, ?, ?, ?)
         ON CONFLICT(ts_code, trade_date) DO UPDATE SET
           mark_type = excluded.mark_type,
           reason = excluded.reason,
           created_at = datetime('now', 'localtime')`,
      )
      .run(tsCode, tradeDate, markType, reason)

    const item = req.db
      .prepare(`${MARK_SELECT} WHERE ts_code = ? AND trade_date = ?`)
      .get(tsCode, tradeDate)
    res.json({ item })
  })

  router.delete('/marks/:id', (req, res) => {
    const id = Number(req.params.id)
    if (!Number.isInteger(id) || id <= 0) {
      res.status(400).json({ error: '无效的标记 id' })
      return
    }
    const existing = req.db.prepare(`${MARK_SELECT} WHERE id = ?`).get(id)
    if (!existing) {
      res.status(404).json({ error: '标记不存在' })
      return
    }
    req.db.prepare('DELETE FROM trend_mark WHERE id = ?').run(id)
    res.json({ ok: true, item: existing })
  })

  router.get('/hm/names', (req, res) => {
    if (!hasTable(req.db, 'hm_detail')) {
      res.json({ items: [] })
      return
    }
    const items = hasTable(req.db, 'hm_list')
      ? req.db
          .prepare(
            `SELECT l.name AS name, COUNT(d.hm_name) AS ops
             FROM hm_list l
             LEFT JOIN hm_detail d ON d.hm_name = l.name
             GROUP BY l.name
             ORDER BY ops DESC, l.name`,
          )
          .all()
      : req.db
          .prepare(
            `SELECT hm_name AS name, COUNT(*) AS ops
             FROM hm_detail
             WHERE hm_name IS NOT NULL AND hm_name != ''
             GROUP BY hm_name
             ORDER BY ops DESC, hm_name`,
          )
          .all()
    res.json({ items })
  })

  router.get('/hm/detail/:tsCode', (req, res) => {
    const tsCode = String(req.params.tsCode || '').trim()
    if (!hasTable(req.db, 'hm_detail')) {
      res.json({ tsCode, unit: { amount: '元' }, rows: [] })
      return
    }
    const rows = req.db
      .prepare(
        `SELECT trade_date, record_no, ts_code, ts_name, hm_name, hm_orgs, tag,
                buy_amount, sell_amount, net_amount
         FROM hm_detail
         WHERE ts_code = ?
         ORDER BY trade_date, net_amount DESC, record_no`,
      )
      .all(tsCode)
    res.json({
      tsCode,
      unit: { amount: '元' },
      rows,
    })
  })

  router.get('/block-trades/:tsCode', (req, res) => {
    const tsCode = String(req.params.tsCode || '').trim()
    const empty = {
      tsCode,
      unit: { price: '元', vol: '万股', amount: '万元' },
      rows: [],
    }
    if (!hasTable(req.db, 'block_trade')) {
      res.json(empty)
      return
    }
    const hasDaily = hasTable(req.db, 'daily')
    const rows = hasDaily
      ? req.db
          .prepare(
            `SELECT b.trade_date, b.record_no, b.ts_code, b.price, b.vol, b.amount,
                    b.buyer, b.seller, d.close,
                    CASE WHEN d.close > 0 AND b.price IS NOT NULL
                      THEN (b.price / d.close - 1) * 100.0
                      ELSE NULL END AS premium_rate
             FROM block_trade b
             LEFT JOIN daily d ON d.ts_code = b.ts_code AND d.trade_date = b.trade_date
             WHERE b.ts_code = ?
             ORDER BY b.trade_date, b.record_no`,
          )
          .all(tsCode)
      : req.db
          .prepare(
            `SELECT trade_date, record_no, ts_code, price, vol, amount, buyer, seller,
                    NULL AS close, NULL AS premium_rate
             FROM block_trade
             WHERE ts_code = ?
             ORDER BY trade_date, record_no`,
          )
          .all(tsCode)
    res.json({ ...empty, rows })
  })

  router.get('/hsgt', (req, res) => {
    const rows = req.db
      .prepare(
        `SELECT trade_date, ggt_ss, ggt_sz, hgt, sgt, north_money, south_money
         FROM moneyflow_hsgt
         ORDER BY trade_date`,
      )
      .all()
    res.json({
      unit: '百万元',
      rows,
    })
  })

  return router
}
