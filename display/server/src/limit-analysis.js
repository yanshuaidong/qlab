import { isCalendarDate } from './signal-analysis.js'

const DAY_MS = 24 * 60 * 60 * 1000

function resolveWindow(db, requestedEndDate) {
  if (requestedEndDate !== undefined
      && (!isCalendarDate(requestedEndDate) || requestedEndDate < '0002-01-01')) {
    throw new RangeError('endDate 必须是有效日期（YYYY-MM-DD），且不早于 0002-01-01')
  }
  const latestDate = db.prepare('SELECT MAX(trade_date) AS date FROM daily').get()?.date || null
  const now = new Date()
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  const endDate = requestedEndDate || latestDate || today
  const startDate = new Date(Date.parse(`${endDate}T00:00:00.000Z`) - 364 * DAY_MS)
    .toISOString().slice(0, 10)
  return { startDate, endDate, latestDate }
}

function assertFinite(value, label) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new RangeError(`${label} 必须是有限数字`)
  }
}

function assertSwitch(value, label) {
  if (typeof value !== 'boolean') throw new RangeError(`${label} 必须是 0 或 1`)
}

const FLOW_SOURCES = [
  { key: 'dc', table: 'moneyflow_dc', column: 'buy_elg_amount_rate', rateKey: 'dcRate' },
  { key: 'ths', table: 'moneyflow_ths', column: 'buy_lg_amount_rate', rateKey: 'thsRate' },
  { key: 'l2', table: 'moneyflow', column: 'buy_elg_amount_rate', rateKey: 'l2Rate' },
]

export function readMainForceWind(db, {
  endDate: requestedEndDate,
  minMvYi = 400,
  dc = true,
  dcRate = 20,
  ths = true,
  thsRate = 20,
  l2 = true,
  l2Rate = 20,
} = {}) {
  const { startDate, endDate, latestDate } = resolveWindow(db, requestedEndDate)
  assertFinite(minMvYi, 'minMvYi')
  if (minMvYi < 0) throw new RangeError('minMvYi 必须是有限非负数字')
  const flags = { dc, ths, l2 }
  const rates = { dcRate, thsRate, l2Rate }
  for (const source of FLOW_SOURCES) {
    assertSwitch(flags[source.key], source.key)
    assertFinite(rates[source.rateKey], source.rateKey)
  }

  const minMvWan = minMvYi * 10000
  const branches = []
  const params = [startDate, endDate]
  for (const source of FLOW_SOURCES) {
    if (!flags[source.key]) continue
    branches.push(`SELECT m.trade_date, m.ts_code
      FROM ${source.table} m
      INNER JOIN daily_basic b ON b.ts_code = m.ts_code AND b.trade_date = m.trade_date
      WHERE m.trade_date >= ? AND m.trade_date <= ?
        AND b.total_mv >= ? AND m.${source.column} >= ?`)
    params.push(startDate, endDate, minMvWan, rates[source.rateKey])
  }
  const hits = branches.length
    ? `hits AS (${branches.join('\nUNION\n')})`
    : `hits AS (SELECT NULL AS trade_date, NULL AS ts_code WHERE 0)`
  const rows = db.prepare(`
    WITH days AS (
      SELECT DISTINCT trade_date AS date FROM daily
      WHERE trade_date >= ? AND trade_date <= ?
    ), ${hits}
    SELECT d.date, COUNT(h.ts_code) AS count
    FROM days d
    LEFT JOIN hits h ON h.trade_date = d.date
    GROUP BY d.date
    ORDER BY d.date
  `).all(...params).map(row => ({ date: row.date, count: row.count }))

  return { startDate, endDate, latestDate, minMvYi, rows }
}

export function readLimitAnalysis(db, requestedEndDate) {
  const { startDate, endDate, latestDate } = resolveWindow(db, requestedEndDate)

  // 只使用同一交易日的名称识别 ST，避免用最新名称回填历史风险警示状态。
  // 没有官方涨跌停价，只能估算；缺少名称的主板股票不参与估算。
  // 年度统计扫描大量行，顺序读日线避免日期索引反复回表；物化限制价，避免汇总时重复查询名称。
  const rows = db.prepare(`
    WITH prices AS (
      SELECT d.ts_code, d.trade_date, d.close, d.pre_close, d.vol,
        COALESCE(
          (SELECT CASE WHEN NULLIF(TRIM(m.name), '') IS NULL THEN NULL
             WHEN UPPER(m.name) LIKE '%ST%' THEN 5 ELSE 10 END FROM moneyflow_dc m
           WHERE m.ts_code = d.ts_code AND m.trade_date = d.trade_date),
          (SELECT CASE WHEN NULLIF(TRIM(t.name), '') IS NULL THEN NULL
             WHEN UPPER(t.name) LIKE '%ST%' THEN 5 ELSE 10 END FROM moneyflow_ths t
           WHERE t.ts_code = d.ts_code AND t.trade_date = d.trade_date)
        ) AS main_limit_pct
      FROM daily d NOT INDEXED
      WHERE d.trade_date >= ? AND d.trade_date <= ?
    ), limits AS MATERIALIZED (
      SELECT trade_date, close, pre_close, vol, CASE
        WHEN ts_code GLOB '[0-9][0-9][0-9][0-9][0-9][0-9].BJ' THEN 30
        WHEN ts_code GLOB '68[89][0-9][0-9][0-9].SH' THEN 20
        WHEN ts_code GLOB '30[01][0-9][0-9][0-9].SZ' AND trade_date >= '2020-08-24' THEN 20
        WHEN (ts_code GLOB '60[0-9][0-9][0-9][0-9].SH'
           OR ts_code GLOB '00[0-9][0-9][0-9][0-9].SZ'
           OR ts_code GLOB '30[01][0-9][0-9][0-9].SZ')
          THEN main_limit_pct
        ELSE NULL
      END AS limit_pct
      FROM prices
    ), classified AS (
      SELECT *, (limit_pct IS NOT NULL AND close > 0 AND pre_close > 0 AND vol > 0) AS eligible
      FROM limits
    )
    SELECT trade_date AS date, COUNT(*) AS totalStocks,
      SUM(CASE WHEN eligible THEN 1 ELSE 0 END) AS eligibleStocks,
      SUM(CASE WHEN eligible AND close > pre_close
        AND ROUND(close * 100) = ROUND(ROUND(pre_close * 100) * (100 + limit_pct) / 100.0)
        THEN 1 ELSE 0 END) AS up,
      SUM(CASE WHEN eligible AND close < pre_close
        AND ROUND(close * 100) = ROUND(ROUND(pre_close * 100) * (100 - limit_pct) / 100.0)
        THEN 1 ELSE 0 END) AS down
    FROM classified
    GROUP BY trade_date ORDER BY trade_date
  `).all(startDate, endDate).map(row => ({ ...row }))

  return { startDate, endDate, latestDate, days: 365, estimated: true, rows }
}
