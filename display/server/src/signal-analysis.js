const DAY_MS = 24 * 60 * 60 * 1000

export function readSignalStocks(db, { date, group = 'total', page = '1', pageSize = '10' } = {}) {
  if (!isCalendarDate(date)) throw new RangeError('date 必须是有效日期（YYYY-MM-DD）')
  if (!['total', 'correct', 'fail'].includes(group)) throw new RangeError('group 必须是 total、correct 或 fail')
  const validInteger = value => ['string', 'number'].includes(typeof value)
    && /^\d+$/.test(String(value)) && Number.isSafeInteger(Number(value)) && Number(value) > 0
  if (!validInteger(page) || !validInteger(pageSize) || Number(pageSize) > 50
      || !Number.isSafeInteger((Number(page) - 1) * Number(pageSize))) {
    throw new RangeError('page 必须是正整数，pageSize 必须为 1 至 50 的整数')
  }
  const params = [date]
  const typeSql = group === 'total' ? "AND t.mark_type IN ('correct', 'fail')" : 'AND t.mark_type = ?'
  if (group !== 'total') params.push(group)
  const where = `WHERE t.trade_date = ? ${typeSql}`
  const total = db.prepare(`SELECT COUNT(*) AS total FROM trend_mark t ${where}`).get(...params).total
  const items = db.prepare(`
    SELECT t.id, t.ts_code, t.trade_date, t.mark_type, t.reason,
           (SELECT m.name FROM moneyflow_dc m WHERE m.ts_code = t.ts_code
            AND m.name IS NOT NULL AND m.name != '' ORDER BY m.trade_date DESC LIMIT 1) AS name
    FROM trend_mark t ${where}
    ORDER BY t.ts_code, t.id
    LIMIT ? OFFSET ?
  `).all(...params, Number(pageSize), (Number(page) - 1) * Number(pageSize))
  return { date, group, page: Number(page), pageSize: Number(pageSize), total, items }
}

export function isCalendarDate(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const time = Date.parse(`${value}T00:00:00.000Z`)
  return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value
}

function localToday() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

export function readSignalAnalysis(db, requestedEndDate) {
  const latestDate = db.prepare(`
    SELECT MAX(trade_date) AS date FROM trend_mark
    WHERE mark_type IN ('correct', 'fail')
  `).get()?.date
  const endDate = requestedEndDate || (isCalendarDate(latestDate) ? latestDate : localToday())
  if (!isCalendarDate(endDate) || endDate < '0002-01-01') {
    throw new RangeError('endDate 必须是有效日期（YYYY-MM-DD），且不早于 0002-01-01')
  }
  const endTime = Date.parse(`${endDate}T00:00:00.000Z`)
  const startTime = endTime - 364 * DAY_MS
  const startDate = new Date(startTime).toISOString().slice(0, 10)
  const counts = db.prepare(`
    SELECT trade_date,
           SUM(CASE WHEN mark_type = 'correct' THEN 1 ELSE 0 END) AS correct,
           SUM(CASE WHEN mark_type = 'fail' THEN 1 ELSE 0 END) AS fail
    FROM trend_mark
    WHERE trade_date >= ? AND trade_date <= ?
      AND mark_type IN ('correct', 'fail')
    GROUP BY trade_date
    ORDER BY trade_date
  `).all(startDate, endDate)
  const byDate = new Map(counts.map(row => [row.trade_date, row]))
  const rows = Array.from({ length: 365 }, (_, index) => {
    const date = new Date(startTime + index * DAY_MS).toISOString().slice(0, 10)
    const { correct = 0, fail = 0 } = byDate.get(date) || {}
    return { date, correct, fail, total: correct + fail }
  })
  return { startDate, endDate, days: rows.length, rows }
}
