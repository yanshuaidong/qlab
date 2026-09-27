/**
 * 摘帽：风险警示被整段撤销，股票不再处于 ST。
 * 变更类型只认「撤销ST」「撤销*ST」。「撤销叠加」只去掉其中一层，名称通常仍带 ST。
 * 实施日之后的第一份 ST 名单里仍然在列的，不记为摘帽。
 * 实施日晚于已入库名单的最后一天时，先不记，等名单更新后再算。
 * K 线标记用实施日；当天没有日线时，改记其后 10 天内的第一根 K 线。
 */

const UNCAP_WHERE = `
  s.st_type IN ('撤销ST', '撤销*ST')
  AND UPPER(IFNULL(s.name, '')) NOT LIKE '%ST%'
  AND IFNULL(s.imp_date, '') != ''
`

function hasTable(db, name) {
  return Boolean(
    db.prepare(`SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?`).get(name),
  )
}

function tradeDateExpr(hasDaily) {
  if (!hasDaily) return 's.imp_date'
  return `COALESCE(
    (SELECT MIN(k.trade_date) FROM daily k
     WHERE k.ts_code = s.ts_code
       AND k.trade_date >= s.imp_date
       AND k.trade_date <= date(s.imp_date, '+10 days')),
    s.imp_date
  )`
}

function confirmSql(hasStockSt) {
  if (!hasStockSt) return ''
  return `
    AND EXISTS (
      SELECT 1 FROM stock_st x
      WHERE x.trade_date >= s.imp_date
    )
    AND NOT EXISTS (
      SELECT 1 FROM stock_st d
      WHERE d.ts_code = s.ts_code
        AND d.trade_date = (
          SELECT MIN(x.trade_date) FROM stock_st x WHERE x.trade_date >= s.imp_date
        )
    )
  `
}

export function readUncapQuery(query) {
  if (query.uncap !== undefined && query.uncap !== '0' && query.uncap !== '1') {
    return { error: 'uncap 必须是 0 或 1' }
  }
  return { enabled: query.uncap === '1' }
}

export function uncapAvailable(db) {
  return hasTable(db, 'st')
}

export function listUncap(db, tsCode = '') {
  if (!uncapAvailable(db)) return []
  const hasDaily = hasTable(db, 'daily')
  const hasStockSt = hasTable(db, 'stock_st')
  const confirm = confirmSql(hasStockSt)
  const codeSql = tsCode ? 'AND s.ts_code = ?' : ''
  const sql = `
    SELECT s.ts_code,
           ${tradeDateExpr(hasDaily)} AS trade_date,
           s.imp_date,
           s.pub_date,
           s.name,
           s.st_type,
           s.st_reason
    FROM st s
    WHERE ${UNCAP_WHERE}
      ${confirm}
      ${codeSql}
    ORDER BY trade_date, s.ts_code, s.imp_date
  `
  return tsCode ? db.prepare(sql).all(tsCode) : db.prepare(sql).all()
}

export function uncapCodeSql(hasStockSt) {
  const confirm = confirmSql(hasStockSt)
  return `
    SELECT s.ts_code
    FROM st s
    WHERE ${UNCAP_WHERE}
      ${confirm}
  `
}
