import assert from 'node:assert/strict'
import { once } from 'node:events'
import { DatabaseSync } from 'node:sqlite'
import test from 'node:test'
import express from 'express'
import { createApiRouter } from '../src/routes.js'

function fixture(t) {
  const db = new DatabaseSync(':memory:')
  t.after(() => db.close())
  db.exec(`
    CREATE TABLE moneyflow_dc (ts_code TEXT, trade_date TEXT, name TEXT);
    INSERT INTO moneyflow_dc VALUES
      ('000001.SZ', '2026-09-24', '平安银行'),
      ('000002.SZ', '2026-09-24', '万科A'),
      ('600519.SH', '2026-09-24', '贵州茅台');
    CREATE TABLE hm_list (name TEXT PRIMARY KEY, intro TEXT, orgs TEXT);
    INSERT INTO hm_list VALUES ('T王', '', ''), ('陈小群', '', ''), ('闲置', '', '');
    CREATE TABLE hm_detail (
      trade_date TEXT, record_no INTEGER, ts_code TEXT, ts_name TEXT,
      hm_name TEXT, hm_orgs TEXT, tag TEXT,
      buy_amount REAL, sell_amount REAL, net_amount REAL,
      PRIMARY KEY (trade_date, record_no)
    );
    INSERT INTO hm_detail VALUES
      ('2026-09-24', 1, '000001.SZ', '平安银行', 'T王', '营业部甲', NULL, 100, 40, 60),
      ('2026-09-24', 2, '000001.SZ', '平安银行', 'T王', '营业部乙', '打板', 10, 80, -70),
      ('2026-09-23', 1, '000002.SZ', '万科A', '陈小群', '营业部丙', NULL, 5, 1, 4);
  `)
  return db
}

async function listen(t, db) {
  const app = express()
  app.use('/api', createApiRouter(() => ({ db, dbPath: ':memory:' }), {}))
  const server = app.listen(0, '127.0.0.1')
  await once(server, 'listening')
  t.after(() => new Promise((resolve, reject) => {
    server.close(err => err ? reject(err) : resolve())
    server.closeAllConnections()
  }))
  return `http://127.0.0.1:${server.address().port}/api`
}

test('游资名录按操作次数排序，明细按股票返回当天各笔', async t => {
  const base = await listen(t, fixture(t))
  const names = await (await fetch(`${base}/hm/names`)).json()
  assert.deepEqual(names.items.map(item => [item.name, item.ops]), [
    ['T王', 2],
    ['陈小群', 1],
    ['闲置', 0],
  ])
  const detail = await (await fetch(`${base}/hm/detail/${encodeURIComponent('000001.SZ')}`)).json()
  assert.equal(detail.unit.amount, '元')
  assert.deepEqual(detail.rows.map(row => [row.record_no, row.hm_name, row.net_amount, row.hm_orgs]), [
    [1, 'T王', 60, '营业部甲'],
    [2, 'T王', -70, '营业部乙'],
  ])
  assert.deepEqual((await (await fetch(`${base}/hm/detail/600519.SH`)).json()).rows, [])
})

test('股票列表可按有游资记录和具体游资筛选', async t => {
  const base = await listen(t, fixture(t))
  const all = await (await fetch(`${base}/stocks`)).json()
  assert.deepEqual(all.items.map(item => item.ts_code), ['000001.SZ', '000002.SZ', '600519.SH'])
  const anyHm = await (await fetch(`${base}/stocks?hm=1`)).json()
  assert.deepEqual(anyHm.items.map(item => item.ts_code), ['000001.SZ', '000002.SZ'])
  const named = await (await fetch(`${base}/stocks?hm=1&hmName=${encodeURIComponent('陈小群')}`)).json()
  assert.deepEqual(named.items.map(item => item.ts_code), ['000002.SZ'])
  const idle = await (await fetch(`${base}/stocks?hm=1&hmName=${encodeURIComponent('闲置')}`)).json()
  assert.deepEqual(idle.items, [])
  assert.equal((await fetch(`${base}/stocks?hm=2`)).status, 400)
  assert.equal((await fetch(`${base}/stocks?hmName=a&hmName=b`)).status, 400)
})

test('没有游资表时筛选返回空列表，名录和明细为空', async t => {
  const db = new DatabaseSync(':memory:')
  t.after(() => db.close())
  db.exec(`CREATE TABLE moneyflow_dc (ts_code TEXT, trade_date TEXT, name TEXT);
    INSERT INTO moneyflow_dc VALUES ('000001.SZ', '2026-09-24', '平安银行');`)
  const base = await listen(t, db)
  assert.deepEqual((await (await fetch(`${base}/stocks?hm=1`)).json()).items, [])
  assert.deepEqual((await (await fetch(`${base}/hm/names`)).json()).items, [])
  assert.deepEqual((await (await fetch(`${base}/hm/detail/000001.SZ`)).json()).rows, [])
  assert.equal((await (await fetch(`${base}/stocks`)).json()).items.length, 1)
})
