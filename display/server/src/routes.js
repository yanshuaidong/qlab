import { Router } from 'express'

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

function parseMvYi(value) {
  if (value === '' || value == null) return null
  const n = Number(value)
  if (!Number.isFinite(n) || n < 0) return null
  return n
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

export function createApiRouter(getDb) {
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
    const hasDailyBasic = hasTable(req.db, 'daily_basic')
    const hasTrendMark = hasTable(req.db, 'trend_mark')
    const useMinMv = hasDailyBasic && minMvYi != null
    const useMaxMv = hasDailyBasic && maxMvYi != null
    const useSignal = scope === 'signal'
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

    const sql = `SELECT m.ts_code, m.name
       FROM moneyflow_dc m
       ${mvJoin}
       WHERE m.trade_date = (SELECT MAX(trade_date) FROM moneyflow_dc)
         ${mvSql}
         ${signalSql}
         ${searchSql}
       ORDER BY m.ts_code
       ${limitSql}`
    const stmt = req.db.prepare(sql)
    const params = []
    if (useMinMv) params.push(minMvWan)
    if (useMaxMv) params.push(maxMvWan)
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

  router.post('/marks/fail-correct', (req, res) => {
    const tsCode = String(req.body?.ts_code || '').trim()
    if (!tsCode) {
      res.status(400).json({ error: '需要 ts_code' })
      return
    }

    const result = req.db
      .prepare(
        `UPDATE trend_mark
         SET mark_type = 'fail',
             created_at = datetime('now', 'localtime')
         WHERE ts_code = ? AND mark_type = 'correct'`,
      )
      .run(tsCode)

    const items = req.db
      .prepare(
        `${MARK_SELECT}
         WHERE ts_code = ?
         ORDER BY trade_date, id`,
      )
      .all(tsCode)
    res.json({
      tsCode,
      updated: Number(result.changes || 0),
      items,
    })
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
