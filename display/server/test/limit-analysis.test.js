import assert from 'node:assert/strict'
import { once } from 'node:events'
import { DatabaseSync } from 'node:sqlite'
import test from 'node:test'
import express from 'express'
import { createApiRouter } from '../src/routes.js'
import { readLimitAnalysis } from '../src/limit-analysis.js'
import { createLimitChartOption } from '../../web/src/utils/limit-chart.js'

function fixture(t) {
  const db = new DatabaseSync(':memory:')
  t.after(() => db.close())
  db.exec(`CREATE TABLE daily (
    ts_code TEXT, trade_date TEXT, close REAL, pre_close REAL, vol REAL,
    PRIMARY KEY (ts_code, trade_date)
  );
  CREATE TABLE moneyflow_dc (ts_code TEXT, trade_date TEXT, name TEXT, PRIMARY KEY (ts_code, trade_date));
  CREATE TABLE moneyflow_ths (ts_code TEXT, trade_date TEXT, name TEXT, PRIMARY KEY (ts_code, trade_date));`)
  return db
}

function insert(db, code, close, { date = '2026-09-17', preClose = 10, vol = 100, name = '普通股票', source = 'dc' } = {}) {
  db.prepare('INSERT INTO daily VALUES (?, ?, ?, ?, ?)').run(code, date, close, preClose, vol)
  if (name !== null) {
    const table = source === 'ths' ? 'moneyflow_ths' : 'moneyflow_dc'
    db.prepare(`INSERT INTO ${table} VALUES (?, ?, ?)`).run(code, date, name)
  }
}

test('跨板块按各自收盘限制价统计，涨跌停都返回非负数量且只读', t => {
  const db = fixture(t)
  insert(db, '600001.SH', 11)
  insert(db, '000001.SZ', 9)
  insert(db, '002001.SZ', 10.5, { name: '*ST示例' })
  insert(db, '600002.SH', 9.5, { name: 'ST示例' })
  insert(db, '300001.SZ', 12, { name: 'ST创业' })
  insert(db, '301001.SZ', 8)
  insert(db, '688001.SH', 12)
  insert(db, '689001.SH', 8)
  insert(db, '920001.BJ', 13, { name: null })
  insert(db, '830001.BJ', 7)
  insert(db, '600003.SH', 10.99) // 收盘未封板
  insert(db, '600004.SH', 12) // 超过限制价并不当成涨停
  insert(db, '600005.SH', 10.5) // 普通主板 5% 不算涨停
  db.exec('PRAGMA query_only = ON')
  const result = readLimitAnalysis(db)
  assert.equal(result.startDate, '2025-09-18')
  assert.equal(result.endDate, '2026-09-17')
  assert.equal(result.latestDate, '2026-09-17')
  assert.equal(result.estimated, true)
  assert.equal(result.days, 365)
  assert.deepEqual(result.rows, [{ date: '2026-09-17', up: 5, down: 5, totalStocks: 13, eligibleStocks: 13 }])
})

test('按价格分位四舍五入，而非固定涨跌幅阈值，停牌、无效行情和未知代码排除', t => {
  const db = fixture(t)
  insert(db, '600001.SH', 11.06, { preClose: 10.05 })
  insert(db, '000001.SZ', 9.05, { preClose: 10.05 })
  insert(db, '600002.SH', 11, { vol: 0 })
  insert(db, '600003.SH', 11, { vol: null })
  insert(db, '600004.SH', 11, { preClose: 0 })
  insert(db, '600005.SH', null)
  insert(db, '600006.SH', 11, { name: null })
  insert(db, '900001.SH', 11) // B 股不适用当前口径
  insert(db, '000001.XX', 11)
  const row = readLimitAnalysis(db).rows[0]
  assert.deepEqual(row, { date: '2026-09-17', up: 1, down: 1, totalStocks: 9, eligibleStocks: 2 })
})

test('ST按当日名称识别，支持同花顺名称回退，不借用后续名称', t => {
  const db = fixture(t)
  insert(db, '600001.SH', 10.5, { date: '2026-09-16', name: '*ST示例', source: 'ths' })
  insert(db, '600001.SH', 10.5, { name: '摘帽股票' })
  insert(db, '600002.SH', 11, { date: '2026-09-16', name: null })
  insert(db, '600002.SH', 11)
  db.exec("INSERT INTO moneyflow_dc VALUES ('600001.SH', '2026-09-16', '')")
  const result = readLimitAnalysis(db)
  assert.equal(result.rows[0].up, 1)
  assert.equal(result.rows[0].eligibleStocks, 1)
  assert.equal(result.rows[1].up, 1)
})

test('365天范围含首尾、日期排序、缺失日期不补零；零涨跌停与不可估算有区别', t => {
  const db = fixture(t)
  insert(db, '600001.SH', 11, { date: '2025-09-17' })
  insert(db, '600001.SH', 11, { date: '2025-09-18' })
  insert(db, '600001.SH', 10, { date: '2026-09-15' })
  insert(db, '600001.SH', 11, { date: '2026-09-16', name: null })
  insert(db, '600001.SH', 9)
  insert(db, '600001.SH', 11, { date: '2026-09-18' })
  const result = readLimitAnalysis(db, '2026-09-17')
  assert.deepEqual(result.rows.map(row => row.date), ['2025-09-18', '2026-09-15', '2026-09-16', '2026-09-17'])
  assert.equal(result.rows[1].up, 0)
  assert.equal(result.rows[1].down, 0)
  assert.equal(result.rows[1].eligibleStocks, 1)
  assert.equal(result.rows[2].eligibleStocks, 0)
  assert.equal(result.rows.at(-1).down, 1)
})

test('空库、无数据区间、闰年与创业板旧规则', t => {
  const db = fixture(t)
  const result = readLimitAnalysis(db, '2024-03-01')
  assert.equal(result.startDate, '2023-03-03')
  assert.equal(result.latestDate, null)
  assert.deepEqual(result.rows, [])
  assert.deepEqual(readLimitAnalysis(db).rows, [])
  insert(db, '300001.SZ', 11, { date: '2020-08-21' })
  insert(db, '300001.SZ', 12, { date: '2020-08-24' })
  assert.deepEqual(readLimitAnalysis(db).rows.map(row => row.up), [1, 1])
  assert.deepEqual(readLimitAnalysis(db, '2019-01-01').rows, [])
})

test('图表同一日期正负柱对齐、零轴对称、跌停悬停以正数展示', () => {
  const option = createLimitChartOption([
    { date: '2026-09-16', up: 7, down: 2, eligibleStocks: 100 },
    { date: '2026-09-17', up: 0, down: 0, eligibleStocks: 100 },
    { date: '2026-09-18', up: 0, down: 0, eligibleStocks: 0 },
  ])
  assert.deepEqual(option.xAxis.data, ['2026-09-16', '2026-09-17', '2026-09-18'])
  assert.deepEqual(option.series[0].data, [7, 0, null])
  assert.deepEqual(option.series[1].data, [-2, -0, null])
  assert.equal(option.series[0].stack, option.series[1].stack)
  assert.equal(option.yAxis.min, -option.yAxis.max)
  assert.equal(option.tooltip.valueFormatter(-2), '2 只')
  assert.equal(option.tooltip.valueFormatter(null), '—')
  assert.equal(option.yAxis.axisLabel.formatter(-10), 10)
  assert.equal(option.dataZoom.length, 2)
  assert.ok(createLimitChartOption([]).yAxis.max > 0)
})

test('API校验日期参数，刷新能读取新行情', async t => {
  const db = fixture(t)
  insert(db, '600001.SH', 11)
  const app = express()
  app.use('/api', createApiRouter(() => ({ db, dbPath: ':memory:' }), {}))
  const server = app.listen(0, '127.0.0.1')
  await once(server, 'listening')
  t.after(() => new Promise((resolve, reject) => {
    server.close(err => err ? reject(err) : resolve())
    server.closeAllConnections()
  }))
  const url = `http://127.0.0.1:${server.address().port}/api/limit-analysis`
  const response = await fetch(url)
  assert.equal(response.status, 200)
  assert.equal((await response.json()).rows[0].up, 1)
  for (const query of ['endDate=', 'endDate=bad', 'endDate=2026-02-29', 'endDate=0001-01-01', 'endDate=2026-9-17', 'endDate=2026-09-16&endDate=2026-09-17']) {
    const invalid = await fetch(`${url}?${query}`)
    assert.equal(invalid.status, 400, query)
    assert.match((await invalid.json()).error, /endDate/)
  }
  insert(db, '000001.SZ', 9)
  const refreshed = await (await fetch(`${url}?endDate=2026-09-17`)).json()
  assert.equal(refreshed.rows[0].down, 1)
})
