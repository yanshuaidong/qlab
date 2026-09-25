import assert from 'node:assert/strict'
import { once } from 'node:events'
import { DatabaseSync } from 'node:sqlite'
import test from 'node:test'
import express from 'express'
import { createApiRouter } from '../src/routes.js'
import { isCalendarDate, readSignalAnalysis, readSignalStocks } from '../src/signal-analysis.js'

function fixture(t) {
  const db = new DatabaseSync(':memory:')
  t.after(() => db.close())
  db.exec(`CREATE TABLE trend_mark (
    id INTEGER PRIMARY KEY, ts_code TEXT, trade_date TEXT, mark_type TEXT
  );
  INSERT INTO trend_mark VALUES
    (1, '000001.SZ', '2026-05-07', 'correct'),
    (2, '000002.SZ', '2026-05-07', 'correct'),
    (3, '000003.SZ', '2026-05-07', 'fail'),
    (4, '000001.SZ', '2026-05-08', 'fail'),
    (5, '000001.SZ', '2025-05-09', 'correct'),
    (6, '000001.SZ', '2025-05-08', 'fail'),
    (7, '000001.SZ', '2026-05-09', 'unknown');
    ALTER TABLE trend_mark ADD COLUMN reason TEXT NOT NULL DEFAULT '';
    CREATE TABLE moneyflow_dc (ts_code TEXT, trade_date TEXT, name TEXT);
    INSERT INTO moneyflow_dc VALUES
      ('000001.SZ', '2026-05-06', '旧名称'),
      ('000001.SZ', '2026-05-08', '最新名称'),
      ('000002.SZ', '2026-05-06', '第二只股票');`)
  return db
}

test('每日汇总跨股票标记，同一天三个信号为三次，全年补零且只读', t => {
  const db = fixture(t)
  db.exec('PRAGMA query_only = ON')
  const result = readSignalAnalysis(db)
  assert.equal(result.endDate, '2026-05-08')
  assert.equal(result.startDate, '2025-05-09')
  assert.equal(result.days, 365)
  assert.equal(result.rows.length, 365)
  assert.deepEqual(result.rows.find(row => row.date === '2026-05-07'),
    { date: '2026-05-07', correct: 2, fail: 1, total: 3 })
  assert.deepEqual(result.rows.find(row => row.date === '2026-05-06'),
    { date: '2026-05-06', correct: 0, fail: 0, total: 0 })
  assert.deepEqual(result.rows[0], { date: '2025-05-09', correct: 1, fail: 0, total: 1 })
  assert.deepEqual(result.rows.at(-1), { date: '2026-05-08', correct: 0, fail: 1, total: 1 })
  assert.equal(result.rows.reduce((sum, row) => sum + row.total, 0), 5)
  assert.ok(result.rows.every(row => row.total === row.correct + row.fail))
})

test('指定截止日排除区间外信号，未知类型不计入', t => {
  const result = readSignalAnalysis(fixture(t), '2026-05-09')
  assert.equal(result.startDate, '2025-05-10')
  assert.equal(result.rows.reduce((sum, row) => sum + row.total, 0), 4)
  assert.equal(result.rows.at(-1).total, 0)
})

test('跨闰日和跨年仍为连续365天，空数据返回零序列', t => {
  const db = fixture(t)
  db.exec('DELETE FROM trend_mark')
  const result = readSignalAnalysis(db, '2024-03-01')
  assert.equal(result.startDate, '2023-03-03')
  assert.equal(result.rows.length, 365)
  assert.equal(new Set(result.rows.map(row => row.date)).size, 365)
  assert.equal(result.rows.at(-2).date, '2024-02-29')
  assert.ok(result.rows.every(row => row.total === 0))
  assert.equal(readSignalAnalysis(db).rows.length, 365)
})

test('校验真实日历日期，拒绝非法日期', () => {
  for (const value of ['2026-02-29', '2026-04-31', 'bad', '', ['2026-05-07'], '2026-5-7']) {
    assert.equal(isCalendarDate(value), false)
  }
  assert.equal(isCalendarDate('2024-02-29'), true)
})

test('股票明细与当日柱子计数一致、按类型过滤、稳定分页且不因名称缺失丢失股票', t => {
  const db = fixture(t)
  db.prepare('UPDATE trend_mark SET reason = ? WHERE id = 1').run('信号原因')
  db.exec('PRAGMA query_only = ON')
  const day = readSignalAnalysis(db).rows.find(row => row.date === '2026-05-07')
  for (const group of ['total', 'correct', 'fail']) {
    const result = readSignalStocks(db, { date: day.date, group })
    assert.equal(result.total, day[group])
    assert.equal(result.items.length, day[group])
    assert.ok(result.items.every(item => item.trade_date === day.date))
    if (group !== 'total') assert.ok(result.items.every(item => item.mark_type === group))
  }
  const first = readSignalStocks(db, { date: day.date, pageSize: '1' })
  assert.equal(first.items[0].name, '最新名称')
  assert.equal(first.items[0].reason, '信号原因')
  const second = readSignalStocks(db, { date: day.date, pageSize: '1', page: '2' })
  assert.equal(second.total, 3)
  assert.equal(second.items[0].ts_code, '000002.SZ')
  const third = readSignalStocks(db, { date: day.date, pageSize: '1', page: '3' })
  assert.equal(third.items[0].name, null)
  assert.equal(third.items[0].ts_code, '000003.SZ')
  assert.equal(readSignalStocks(db, { date: '2026-05-09' }).total, 0)
  assert.deepEqual(readSignalStocks(db, { date: day.date, page: '2' }).items, [])
})

test('API返回365天统计，拒绝非法或重复日期参数，刷新反映标记修改', async t => {
  const db = fixture(t)
  const app = express()
  app.use('/api', createApiRouter(() => ({ db, dbPath: ':memory:' }), {}))
  const server = app.listen(0, '127.0.0.1')
  await once(server, 'listening')
  t.after(() => new Promise((resolve, reject) => {
    server.close(err => err ? reject(err) : resolve())
    server.closeAllConnections()
  }))
  const url = `http://127.0.0.1:${server.address().port}/api/signal-analysis`
  const response = await fetch(url)
  assert.equal(response.status, 200)
  assert.equal((await response.json()).rows.length, 365)
  for (const query of ['endDate=2026-02-30', 'endDate=', 'endDate=0001-01-01', 'endDate=2026-05-07&endDate=2026-05-08']) {
    const invalid = await fetch(`${url}?${query}`)
    assert.equal(invalid.status, 400)
    assert.match((await invalid.json()).error, /endDate/)
  }
  const detailResponse = await fetch(`${url}/signals?date=2026-05-07&group=correct&pageSize=1&page=2`)
  assert.equal(detailResponse.status, 200)
  const detail = await detailResponse.json()
  assert.equal(detail.total, 2)
  assert.equal(detail.items[0].ts_code, '000002.SZ')
  for (const query of [
    '', 'date=2026-02-30', 'date=2026-05-07&date=2026-05-08',
    'date=2026-05-07&group=bad', 'date=2026-05-07&group=fail&group=correct',
    'date=2026-05-07&page=0', 'date=2026-05-07&page=1.5',
    'date=2026-05-07&page=1&page=2', 'date=2026-05-07&pageSize=51',
    'date=2026-05-07&pageSize=abc', 'date=2026-05-07&pageSize=0',
  ]) {
    const invalid = await fetch(`${url}/signals?${query}`)
    assert.equal(invalid.status, 400, query)
    assert.ok((await invalid.json()).error)
  }
  db.exec("UPDATE trend_mark SET mark_type = 'fail' WHERE id = 1")
  const changed = await (await fetch(`${url}/signals?date=2026-05-07&group=fail`)).json()
  assert.equal(changed.total, 2)
  const refreshed = await (await fetch(`${url}?endDate=2026-05-07`)).json()
  assert.deepEqual(refreshed.rows.at(-1), { date: '2026-05-07', correct: 1, fail: 2, total: 3 })
})
