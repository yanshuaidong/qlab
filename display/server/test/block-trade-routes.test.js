import test from 'node:test'
import assert from 'node:assert/strict'
import { DatabaseSync } from 'node:sqlite'
import express from 'express'
import { createBlockTradeRouter } from '../src/block-trade-routes.js'

async function fixture(t, { block = true, daily = true, names = true } = {}) {
  const db = new DatabaseSync(':memory:')
  t.after(() => db.close())
  if (block) db.exec(`CREATE TABLE block_trade (trade_date TEXT,record_no INTEGER,ts_code TEXT,price REAL,vol REAL,amount REAL,buyer TEXT,seller TEXT,updated_at TEXT,PRIMARY KEY(trade_date,record_no));
    INSERT INTO block_trade VALUES
    ('2026-09-14',1,'000001.SZ',9,100,900,'买','卖','now'),
    ('2026-09-14',2,'000001.SZ',9,100,900,'买','卖','now'),
    ('2026-09-14',3,'000001.SZ',11,100,1100,'买','卖','now'),
    ('2026-09-15',1,'000001.SZ',10,100,1000,'买','卖','now'),
    ('2026-09-16',1,'000001.SZ',10,100,1000,'买','卖','now'),
    ('2026-09-17',1,'000001.SZ',NULL,100,NULL,'买','卖','now'),
    ('2026-09-14',4,'999999.SH',10,100,1000,'买','卖','now');`)
  if (daily) db.exec(`CREATE TABLE daily (ts_code TEXT,trade_date TEXT,open REAL,high REAL,low REAL,close REAL,pct_chg REAL,vol REAL,amount REAL,PRIMARY KEY(ts_code,trade_date));
    INSERT INTO daily VALUES ('000001.SZ','2026-09-14',10,11,9,10,0,1000,10000),
    ('000001.SZ','2026-09-16',10,11,9,0,0,1000,10000),
    ('000001.SZ','2026-09-17',10,11,9,10,0,1000,10000),
    ('000002.SZ','2026-09-15',99,100,98,99,0,1000,10000);`)
  if (names) db.exec(`CREATE TABLE moneyflow_dc (ts_code TEXT,trade_date TEXT,name TEXT,PRIMARY KEY(ts_code,trade_date));
    INSERT INTO moneyflow_dc VALUES ('000001.SZ','2026-09-12','旧名称'),('000001.SZ','2026-09-13','最新名称'),
    ('000001.SZ','2026-09-14',''),('000001.SZ','2026-09-15',NULL),('000002.SZ','2026-09-15','无成交股票');`)
  const app = express()
  app.use((req, _res, next) => { req.db = db; next() })
  app.use('/api/block-trade', createBlockTradeRouter())
  const server = app.listen(0, '127.0.0.1')
  await new Promise(resolve => server.once('listening', resolve))
  t.after(() => new Promise(resolve => server.close(resolve)))
  const get = async path => {
    const response = await fetch(`http://127.0.0.1:${server.address().port}/api/block-trade${path}`)
    return { status: response.status, body: await response.json() }
  }
  return { db, get }
}

test('HTTP 全局按逐笔计数，相同成交不去重，证券数单独统计', async t => {
  const { get } = await fixture(t)
  const { status, body } = await get('/overview')
  assert.equal(status, 200)
  assert.deepEqual(body.summary, { count: 7, stock_count: 2, day_count: 4, start_date: '2026-09-14', end_date: '2026-09-17' })
  assert.deepEqual(body.rows[0], { trade_date: '2026-09-14', count: 4, stock_count: 2 })
})

test('HTTP 选股只含有成交证券，名称取最近非空记录，缺名不丢代码', async t => {
  const { get } = await fixture(t)
  const { body } = await get('/stocks')
  assert.equal(body.items.length, 2)
  assert.deepEqual(body.items[0], { ts_code: '000001.SZ', count: 6, last_date: '2026-09-17', name: '最新名称', total_mv: null })
  assert.equal(body.mv_available, false)
  assert.equal(body.items[1].name, null)
  assert.equal((await get('/stocks?q=999999')).body.items.length, 1)
  assert.equal((await get(`/stocks?q=${encodeURIComponent('最新')}`)).body.items.length, 1)
  assert.equal((await get('/stocks?q=NO_MATCH')).body.items.length, 0)
  assert.equal((await get('/stocks?q=1&q=2')).status, 400)
})

test('HTTP 选股按最新总市值小于门槛筛选，缺市值不计入', async t => {
  const { db, get } = await fixture(t)
  db.exec(`CREATE TABLE daily_basic (ts_code TEXT, trade_date TEXT, total_mv REAL, PRIMARY KEY (ts_code, trade_date));
    INSERT INTO daily_basic VALUES
    ('000001.SZ','2026-09-16',500000),
    ('000001.SZ','2026-09-17',800000),
    ('999999.SH','2026-09-17',1500000);`)
  const filtered = await get('/stocks?maxMvYi=100')
  assert.equal(filtered.status, 200)
  assert.equal(filtered.body.mv_available, true)
  assert.equal(filtered.body.unit.total_mv, '万元')
  assert.deepEqual(filtered.body.items.map(row => [row.ts_code, row.total_mv]), [['000001.SZ', 800000]])
  assert.equal((await get('/stocks?maxMvYi=80')).body.items.length, 0)
  assert.equal((await get('/stocks?maxMvYi=200')).body.items.length, 2)
  assert.equal((await get('/stocks')).body.items.length, 2)
  assert.equal((await get('/stocks?maxMvYi=100&q=999999')).body.items.length, 0)
  assert.equal((await get('/stocks?maxMvYi=-1')).status, 400)
  assert.equal((await get('/stocks?maxMvYi=abc')).status, 400)
  assert.equal((await get('/stocks?maxMvYi=1&maxMvYi=2')).status, 400)
})

test('HTTP 折溢价按准确证券及当日收盘计算；缺失或零收盘、缺成交价不计算', async t => {
  const { get } = await fixture(t)
  const { status, body } = await get('/stock/000001.SZ')
  assert.equal(status, 200)
  assert.equal(body.rows.length, 6)
  assert.equal(body.daily.length, 3)
  assert.ok(Math.abs(body.rows[0].premium_rate + 10) < 1e-8)
  assert.ok(Math.abs(body.rows[2].premium_rate - 10) < 1e-8)
  assert.equal(body.rows[1].record_no, 2)
  assert.deepEqual(body.rows.slice(3).map(row => row.premium_rate), [null, null, null])
  assert.equal(body.rows[3].close, null)
})

test('HTTP 无日线证券仍返回完整成交；缺名称表或行情表亦可读取成交', async t => {
  const { get } = await fixture(t, { names: false, daily: false })
  const { body } = await get('/stock/999999.SH')
  assert.equal(body.rows.length, 1)
  assert.equal(body.rows[0].premium_rate, null)
  assert.deepEqual(body.daily, [])
  assert.equal((await get('/stocks')).body.items.length, 2)
})

test('HTTP 拒绝非法代码，合法但无成交代码返回404', async t => {
  const { get } = await fixture(t)
  assert.equal((await get('/stock/000002.SZ')).status, 404)
  assert.equal((await get('/stock/invalid')).status, 400)
  assert.equal((await get('/stock/000001.sz')).status, 200)
  assert.equal((await get(`/stock/${encodeURIComponent("' OR 1=1 --")}`)).status, 400)
})

test('HTTP 单笔金额含边界，折价率不含边界，并同时筛股票和明细', async t => {
  const { db, get } = await fixture(t)
  db.exec(`INSERT INTO daily VALUES ('000001.SZ','2026-09-18',100,101,99,100,0,1000,10000);
    INSERT INTO block_trade VALUES
    ('2026-09-18',1,'000001.SZ',95,1,2000,'买','卖','now'),
    ('2026-09-18',2,'000001.SZ',97,1,2000,'买','卖','now'),
    ('2026-09-18',3,'000001.SZ',92,1,2000,'买','卖','now'),
    ('2026-09-18',4,'000001.SZ',94,1,1999.99,'买','卖','now');`)
  const matched = await get('/stocks?minAmountWan=2000&minDiscount=3&maxDiscount=8')
  assert.equal(matched.status, 200)
  assert.equal(matched.body.unit.amount, '万元')
  assert.deepEqual(matched.body.items.map(row => [row.ts_code, row.count, row.last_date]), [['000001.SZ', 1, '2026-09-18']])
  const detail = await get('/stock/000001.SZ?minAmountWan=2000&minDiscount=3&maxDiscount=8')
  assert.equal(detail.status, 200)
  assert.equal(detail.body.rows.length, 1)
  assert.equal(detail.body.rows[0].record_no, 1)
  assert.equal(detail.body.daily.length, 4)
  assert.equal((await get('/stock/000001.SZ?minAmountWan=2000&maxAmountWan=2000')).body.rows.length, 3)
  assert.equal((await get('/stocks?maxAmountWan=900')).body.items.find(row => row.ts_code === '000001.SZ').count, 2)
  assert.equal((await get('/stocks?minAmountWan=2000&maxAmountWan=1000')).status, 400)
  assert.equal((await get('/stocks?minDiscount=8&maxDiscount=8')).status, 400)
  assert.equal((await get('/stocks?minAmountWan=-1')).status, 400)
  assert.equal((await get('/stocks?minDiscount=abc')).status, 400)
  assert.equal((await get('/stock/000001.SZ?minAmountWan=1&minAmountWan=2')).status, 400)
})

test('HTTP 折价率筛选在没有日线时不把无法计算的成交算进去', async t => {
  const { get } = await fixture(t, { daily: false })
  assert.deepEqual((await get('/stocks?minDiscount=3&maxDiscount=8')).body.items, [])
  assert.deepEqual((await get('/stock/000001.SZ?minDiscount=3')).body.rows, [])
  assert.equal((await get('/stocks?minAmountWan=1000')).body.items.length, 2)
})

test('HTTP 未采集大宗表返回503提示，空表返回空数据', async t => {
  const missing = await fixture(t, { block: false })
  for (const path of ['/overview', '/stocks', '/stock/000001.SZ']) {
    const result = await missing.get(path)
    assert.equal(result.status, 503)
    assert.match(result.body.error, /collect\/block_trade.py/)
  }
  const empty = await fixture(t)
  empty.db.exec('DELETE FROM block_trade')
  assert.equal((await empty.get('/overview')).body.summary.count, 0)
  assert.deepEqual((await empty.get('/stocks')).body.items, [])
})
